"""New Zealand travel advice (SafeTravel, Ministry of Foreign Affairs and Trade).

Source: https://www.safetravel.govt.nz/destinations (HTML, no key). The page embeds its whole destination list as
JSON in `<div id="js-country-listing" data-content="...">` (HTML-escaped): one row per destination with `code`
(ISO 3166-1 alpha-2 in lower case; Kosovo's is blank), `link` {title, href}, `region`, `adviceLevel` (normal, low,
medium, high, avoid), `nearestOffices` and `updatedDate` ("27 July 2026": a day, no time). The same block carries
MFAT's own words for each level (`adviceLevels`). Checked live 14 Nov 2026: 222 destinations. There is no RSS.

Areas with a higher (or lower) level inside a country appear only on the country's own page, in the advice band
under its headline ("Exercise increased caution" / "with higher advice levels in some areas"). Cordon reads a
country page only when its `updatedDate` moves, so after the first run a run reads a handful at most.

Terms (safetravel.govt.nz/copyright, read 14 Nov 2026): Crown copyright, licensed under Creative Commons Attribution
4.0 International; attribute the Ministry of Foreign Affairs and Trade in words, not with its logos; the site's
design, photographs and imagery are excluded. robots.txt disallows nothing.

Cordon reports New Zealand's levels in MFAT's words. It does not rank them against other governments' levels.
"""
import html
import json
import re
import time
from datetime import datetime
from urllib.parse import quote

from .common import fetch_or_none, now_utc

SITE = "https://www.safetravel.govt.nz"
SOURCE_URL = SITE + "/destinations"
MIN_COUNTRIES = 150  # MFAT lists about 222; far fewer means a broken page
MAX_PAGES = 240  # country pages read in one run (the first run reads them all, about 0.5 s each)
PAUSE_S = 0.2  # between country pages
# MFAT's levels, lowest first, in its own words (the page's adviceLevels list; that list wins when present).
ORDER = ["normal", "low", "medium", "high", "avoid"]
LEVELS = {"normal": "No advice level at this time", "low": "Exercise normal safety and security precautions",
          "medium": "Exercise increased caution", "high": "Avoid non-essential travel", "avoid": "Do not travel"}
HAND_CODE = {"kosovo": "XK"}  # rows MFAT lists with no code, by their link slug
LISTING_RE = re.compile(r'id="js-country-listing"\s+data-content="([^"]+)"')
BAND_RE = re.compile(r'rounded-b-2xl[^"]*">\s*<p[^>]*>\s*<strong[^>]*>.*?<span>([^<]+)</span>\s*</strong>\s*'
                     r'(?:<span>([^<]+)</span>)?', re.S)
PAGE_DATE_RE = re.compile(r"Page updated\s+(\d{1,2} [A-Z][a-z]+ \d{4})")


def iso_date(text: str | None) -> str | None:
    """'27 July 2026' -> '2026-07-27' (MFAT gives a day only; the time zone is not stated, New Zealand's own
    presumably)."""
    try:
        return datetime.strptime((text or "").strip(), "%d %B %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def level_rank(level: str | None) -> int:
    return ORDER.index(level) if level in ORDER else -1


def parse_listing(body: str) -> tuple[dict, dict]:
    """({key: {key, iso, name, slug, region, level, advice, updated, link}}, {level: words}) from the page."""
    m = LISTING_RE.search(body)
    if not m:
        raise ValueError("no destination list on the page")
    doc = json.loads(html.unescape(m.group(1)))
    words = {x["value"]: x["title"].strip() for x in doc.get("adviceLevels") or []
             if isinstance(x, dict) and x.get("value") in LEVELS and x.get("title")}
    words = {**LEVELS, **words}
    out = {}
    for r in doc.get("data") or []:
        link = (r.get("link") or {})
        href = str(link.get("href") or "")
        slug = href.rsplit("/", 1)[-1] if href.startswith("/destinations/") else ""
        code = str(r.get("code") or "").strip().upper() or HAND_CODE.get(slug, "")
        level = r.get("adviceLevel")
        if not re.fullmatch(r"[A-Z]{2}", code) or level not in LEVELS or not re.fullmatch(r"[^/?#\s]+", slug):
            continue
        out[code] = {"key": code, "iso": code, "name": (link.get("title") or code).strip(), "slug": slug,
                     "region": r.get("region"), "level": level, "advice": words[level],
                     "updated": iso_date(r.get("updatedDate")), "link": SITE + quote(href, safe="/,-")}
    return out, words


def parse_page(body: str) -> dict:
    """{headline, regional_note, page_updated} from a country page's advice band. regional_note is MFAT's own words
    under the headline, None when there are none. On 14 Nov 2026 every such note (57) said other levels apply in some
    areas: "with higher advice levels in some areas" (54), "See regional advice below" (Myanmar), "There are areas of
    Bolivia where higher advice levels apply. See regional advice below." and "in Mozambique overall due to the risk of
    violent crime and terrorist activity" (its page has do-not-travel areas)."""
    m = BAND_RE.search(body)
    if not m:
        raise ValueError("no advice band on the page")
    d = PAGE_DATE_RE.search(body)
    note = html.unescape(m.group(2)).strip() if m.group(2) else None
    return {"headline": html.unescape(m.group(1)).strip(), "regional_note": note or None,
            "page_updated": iso_date(d.group(1)) if d else None}


def diff(old: dict, new: dict, when: str) -> list[dict]:
    """A level change, or the regional note added, removed or reworded, against what Cordon held before. The regional
    note counts only when both the old and the new page were read."""
    out = []
    for key, rec in new.items():
        prev = old.get(key)
        if not prev:
            continue
        base = {"at": when, "key": key, "iso": rec["iso"], "name": rec["name"], "link": rec["link"]}
        if prev.get("level") != rec["level"]:
            out.append({**base, "kind": "level", "from": prev.get("level"), "to": rec["level"]})
        if prev.get("page_for") and rec.get("page_for") and prev.get("regional_note") != rec.get("regional_note"):
            out.append({**base, "kind": "regional", "from": prev.get("regional_note"), "to": rec.get("regional_note")})
    return out


def collect(old: dict | None, when: str | None = None, fetch=fetch_or_none, pause: float = PAUSE_S):
    """(countries, changes, error, pages_read, pages_failed). On error the caller keeps the old set."""
    when = when or now_utc()
    old = old or {}
    body, err = fetch(SOURCE_URL, 40)
    if body is None:
        return old, [], err, 0, 0
    try:
        new, _ = parse_listing(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, KeyError, TypeError) as e:
        return old, [], f"unreadable: {type(e).__name__}", 0, 0
    if len(new) < MIN_COUNTRIES:
        return old, [], f"only {len(new)} destinations listed", 0, 0
    read = failed = 0
    for key, rec in new.items():
        prev = old.get(key) or {}
        for k in ("headline", "regional_note", "page_updated", "page_for"):
            rec[k] = prev.get(k)
        if rec["page_for"] and rec["page_for"] == rec["updated"]:
            continue
        if read + failed >= MAX_PAGES:
            continue
        page, perr = fetch(rec["link"], 30)
        if pause:
            time.sleep(pause)
        try:
            if page is None:
                raise ValueError(perr)
            rec.update(parse_page(page.decode("utf-8")))
            rec["page_for"] = rec["updated"]
            read += 1
        except (ValueError, UnicodeDecodeError):
            failed += 1  # keeps the last page read; asked for again next run
    return dict(sorted(new.items())), diff(old, new, when), None, read, failed
