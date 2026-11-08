"""US embassy alerts: each post's WordPress RSS feed, <cc>.usembassy.gov/category/alert/feed/ (no combined feed),
with a Google News site: search as the fallback when a post's own feed returns HTTP 403 or an HTML "Technical
Difficulties" page (every post did on 31 Oct and 8 Nov 2026).

Polled for the posts that matter most: every country at advisory level 3 or 4, plus a fixed list. The alert type is
only in the title prefix ("Security Alert: ...", "Demonstration Alert - ..."). A search result counts only if its
title is an alert and it is dated within FALLBACK_DAYS; results are marked `via: google-news` and carry the post's
alerts page, because a Google News link is a redirect, not the embassy's page. A post whose own feed and the search
both fail, or whose search finds nothing recent, is recorded in health and keeps its previous alerts.
"""
import html
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .common import fetch_or_none, now_utc

# ISO code -> post host where it isn't <iso>.usembassy.gov
HOST = {"GB": "uk.usembassy.gov"}
EXTRA_POSTS = ["UA", "IL", "PS", "LB", "IQ", "JO", "SA", "AE", "QA", "KW", "BH", "OM", "EG", "TR", "PK", "IN",
               "TW", "KR", "PH", "VN", "MX", "VE", "CO", "CU", "HT", "NG", "ET", "SO", "KE", "CD", "SD"]
NO_POST = {"KP", "IR", "SY"}   # no US embassy (protecting-power or virtual sites only)
TYPE_RE = re.compile(r"^\s*([A-Za-z ]{3,40}?)\s+(?:Alert|Message)\s*[:\-–—]", re.I)
NOTICE_RE = re.compile(r"\bmessage for u\.?\s?s\.? citizens\b", re.I)
# Google News appends the site's name to each title: "Security Alert: ... - U.S. Embassy in Ukraine".
GN_TAIL_RE = re.compile(r"\s+-\s+(?:U\.?S\.?\s+(?:Embassy|Mission)\b.*|[a-z]{2}\.usembassy\.gov.*)$", re.I)
FALLBACK_DAYS = 30
MAX_ALERTS = 10


def posts(advisories: dict) -> list[str]:
    hot = {r["iso"] for r in advisories.values() if r["level"] >= 3 and r["iso"]}
    return sorted((hot | set(EXTRA_POSTS)) - NO_POST)


def post_host(iso: str) -> str:
    return HOST.get(iso, f"{iso.lower()}.usembassy.gov")


def feed_url(iso: str) -> str:
    return f"https://{post_host(iso)}/category/alert/feed/"


def alerts_page(iso: str) -> str:
    return f"https://{post_host(iso)}/category/alert/"


def search_url(iso: str) -> str:
    q = (f'site:{post_host(iso)} ("Security Alert" OR "Demonstration Alert" OR "Weather Alert" '
         f'OR "Health Alert" OR "Message for U.S. Citizens") when:{FALLBACK_DAYS}d')
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )


def parse_rss(xml: str, iso: str, search: bool = False) -> list[dict]:
    """RSS items as alerts. `search=True` for Google News results: drop the site name it appends to each title."""
    if "<rss" not in xml and "<channel" not in xml:
        raise ValueError("not RSS")
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def tag(name):
            m = re.search(rf"<{name}>(.*?)</{name}>", item, re.S)
            if not m:
                return ""
            v = m.group(1).strip()
            if v.startswith("<![CDATA[") and v.endswith("]]>"):
                v = v[9:-3]
            return html.unescape(re.sub(r"<[^>]+>", " ", v)).strip()
        title, link, pub = re.sub(r"\s+", " ", tag("title")).strip(), tag("link"), tag("pubDate")
        if search:
            title = GN_TAIL_RE.sub("", title).strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        try:
            when = parsedate_to_datetime(pub).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if pub else None
        except (TypeError, ValueError):
            when = None
        m = TYPE_RE.match(title)
        out.append({"iso": iso, "title": title, "link": link, "published_at": when,
                    "type": (m.group(1).strip().lower() if m else "alert")})
    return out


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def is_alert(title: str) -> bool:
    return bool(TYPE_RE.match(title) or NOTICE_RE.search(title))


def search_results(items: list[dict], iso: str, when: str) -> list[dict]:
    """Search hits that are alerts dated within FALLBACK_DAYS of `when`, newest first, one per title and day."""
    cutoff = _t(when) - timedelta(days=FALLBACK_DAYS)
    seen, keep = set(), []
    for a in sorted((a for a in items if a["published_at"]), key=lambda a: a["published_at"], reverse=True):
        key = (a["title"].lower(), a["published_at"][:10])
        if key in seen or not is_alert(a["title"]) or _t(a["published_at"]) < cutoff:
            continue
        seen.add(key)
        keep.append({**a, "via": "google-news", "post_url": alerts_page(iso)})
    return keep[:MAX_ALERTS]


def _try_parse(body: bytes | None, iso: str, search: bool = False) -> tuple[list[dict] | None, str | None]:
    if body is None:
        return None, None
    try:
        return parse_rss(body.decode("utf-8", "replace"), iso, search=search), None
    except Exception as e:  # noqa: BLE001
        return None, f"parse: {type(e).__name__}"


def collect(advisories: dict, previous: dict | None = None, when: str | None = None, fetch=fetch_or_none):
    """({iso: [alerts]}, {iso: error}, {iso: "google-news"} for posts answered by the search).

    A post whose own feed fails tries the Google News search; if that finds no recent alert either, the post keeps
    its previous alerts and the error is recorded.
    """
    when = when or now_utc()
    out, errors, via = dict(previous or {}), {}, {}
    for iso in posts(advisories):
        body, err = fetch(feed_url(iso), 25)
        items, perr = _try_parse(body, iso)
        if items is not None:
            out[iso] = items[:MAX_ALERTS]
            continue
        fb_body, fb_err = fetch(search_url(iso), 25)
        found, fb_perr = _try_parse(fb_body, iso, search=True)
        kept = search_results(found or [], iso, when)
        if kept:
            out[iso] = kept
            via[iso] = "google-news"
            continue
        why = fb_err or fb_perr or f"no alert in the last {FALLBACK_DAYS} days"
        errors[iso] = f"{err or perr or 'unavailable'}; Google News: {why}"
    return out, errors, via
