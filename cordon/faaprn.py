"""FAA Prohibitions, Restrictions and Notices: the US flight prohibitions (SFARs) and security NOTAMs (KICZ) for
foreign airspace, the US counterpart of EASA's conflict-zone bulletins.

Source: https://www.faa.gov/air_traffic/publications/us_restrictions (HTML, no key; robots.txt allows it). Checked
live 15 Nov 2026: one h2 per country or region, each with a list of entries. An entry names an SFAR ("Special Federal
Aviation Regulation (SFAR) 119 - Prohibitions Against Certain Flights in the Kabul Flight Information Region (FIR)
(OAKX)"), a KICZ NOTAM with its number ("KICZ NOTAM A0054/26 - United States of America Advisory for Potentially
Hazardous Situation in the Overwater Areas Above the Pacific Ocean in the Central America Flight Information Region
(MHCC)"), an FAA background notice, or other references (routing rules for US territory, CFR sections, ICAO letters,
DOT and OFAC notices). Cordon reads the SFARs and KICZ NOTAMs, keeps the background notices as links, and leaves the
rest. The page gives no dates; the NOTAM number carries its year (A0054/26 is 2026).

Terms: the FAA states no licence on the page; faa.gov's Web Policies link the standard US Government system-use
notice. Cordon treats the content as a US Government work, not subject to US copyright (17 U.S.C. 105), as for its
other FAA lanes; that is Cordon's reading, not an FAA statement.

A change is an SFAR or KICZ NOTAM that appears in or leaves a section between two of Cordon's reads (none on the
first read).
"""
import html
import re

from . import cdc
from .common import fetch_or_none, now_utc

PAGE_URL = "https://www.faa.gov/air_traffic/publications/us_restrictions"
SOURCE_URL = PAGE_URL
MIN_SECTIONS = 10  # 24 sections on 15 Nov 2026; far fewer means a broken page
# The FAA's section names, where the kit's country names do not match, or the section is a sea or region.
SECTION_ISO = {"Korea, North": "KP", "Russian Federation": "RU", "Central America": None, "Pacific Ocean": None,
               "Persian Gulf and Gulf of Oman": None, "United States": "US"}
H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S | re.I)
ANCHOR_RE = re.compile(r'class="ck-anchor"[^>]*\bid="([^"]+)"|\bid="([^"]+)"[^>]*class="ck-anchor"', re.I)
LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.S | re.I)
HREF_RE = re.compile(r'href="([^"]+)"', re.I)
SFAR_RE = re.compile(r"\bSFAR\)?\s*(\d{2,3})\b")
NOTAM_RE = re.compile(r"\bA(\d{4})/(\d{2})\b")
FIR_RE = re.compile(r"\(([A-Z]{4})(?:\s+FIR)?\)")
NOT_FIR = {"SFAR", "KICZ", "UNSC"}
# Strongest first: what the section asks of US operators.
KINDS = ("prohibition", "advisory", "pointer", "notice")
WORDS = {"prohibition": "US flight prohibition", "advisory": "US advisory for potentially hazardous airspace",
         "pointer": "US pointer NOTAM", "notice": "US notice"}


def _text(s: str) -> str:
    """Tags dropped without a space: the FAA wraps acronyms in <abbr> ("(<abbr>SFAR</abbr>) 117"); a line break is
    a space."""
    s = re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", " ", s, flags=re.I))
    return re.sub(r"\s+", " ", html.unescape(s)).replace("​", "").strip()


def _url(href: str) -> str:
    href = html.unescape(href)
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://www.faa.gov" + href
    return PAGE_URL + "/" + href  # relative to the page ("media/KICZ_A0003-22_...pdf")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def iso_for(name: str) -> str | None:
    if name in SECTION_ISO:
        return SECTION_ISO[name]
    return cdc.iso_for(name)


def entry(li: str) -> dict | None:
    """{key, kind, label, text, url} for an SFAR or KICZ NOTAM entry; {kind: background, ...} for an FAA background
    notice; None for anything else."""
    text = _text(li)
    hrefs = HREF_RE.findall(li)
    url = _url(hrefs[0]) if hrefs else PAGE_URL
    firs = sorted(set(FIR_RE.findall(text)) - NOT_FIR)
    m = SFAR_RE.search(text)
    if m and "Special Federal Aviation Regulation" in text:
        return {"key": f"SFAR-{m.group(1)}", "kind": "prohibition", "label": f"SFAR {m.group(1)}", "text": text,
                "url": url, "firs": firs}
    m = NOTAM_RE.search(text)
    if m and "KICZ" in text:
        low = text.lower()
        kind = ("prohibition" if "prohibition" in low else "advisory" if "advisory" in low
                else "pointer" if "pointer" in low else "notice")
        return {"key": f"KICZ-A{m.group(1)}-{m.group(2)}", "kind": kind, "label": f"KICZ NOTAM A{m.group(1)}/{m.group(2)}",
                "text": text, "url": url, "firs": firs}
    if text.startswith("FAA Background Information"):
        return {"kind": "background", "text": text, "url": url}
    return None


def parse(body) -> dict:
    """{section slug: {key, name, iso, anchor, entries: {key: entry}, background: [{text, url}], other: n}} for every
    section with an anchor (the country and region sections; the page's headings without one are not sections)."""
    page = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    parts = H2_RE.split(page)
    out = {}
    for i in range(1, len(parts), 2):
        a = ANCHOR_RE.search(parts[i])
        if not a:
            continue
        name = _text(parts[i])
        if not name:
            continue
        block = re.split(r"<h[12]\b|</main>", parts[i + 1], maxsplit=1)[0]
        entries, background, other = {}, [], 0
        for li in LI_RE.findall(block):
            e = entry(li)
            if e is None:
                other += 1
            elif e["kind"] == "background":
                background.append({"text": e["text"], "url": e["url"]})
            else:
                entries.setdefault(e["key"], e)
        key = slug(name)
        out[key] = {"key": key, "name": name, "iso": iso_for(name), "anchor": a.group(1) or a.group(2),
                    "entries": dict(sorted(entries.items())), "background": background, "other": other}
    return out


def strongest(entries: dict) -> str | None:
    kinds = {e["kind"] for e in entries.values()}
    return next((k for k in KINDS if k in kinds), None)


def diff(old: dict, new: dict, when: str) -> list[dict]:
    """An SFAR or KICZ NOTAM that appeared in or left a section, against the set Cordon held before (none on the first
    read). A section that left the page counts each of its entries as removed."""
    if not old:
        return []
    out = []
    for skey in sorted(set(old) | set(new)):
        a = (old.get(skey) or {}).get("entries") or {}
        b = (new.get(skey) or {}).get("entries") or {}
        sec = new.get(skey) or old.get(skey)
        base = {"at": when, "section": skey, "name": sec["name"], "iso": sec.get("iso"),
                "link": f"{PAGE_URL}#{sec.get('anchor') or skey}"}
        for k in sorted(set(b) - set(a)):
            out.append({**base, "key": k, "kind": "new", "label": b[k]["label"], "entry_kind": b[k]["kind"],
                        "text": b[k]["text"], "url": b[k]["url"], "from": None, "to": b[k]["kind"]})
        for k in sorted(set(a) - set(b)):
            out.append({**base, "key": k, "kind": "removed", "label": a[k]["label"], "entry_kind": a[k]["kind"],
                        "text": a[k]["text"], "url": a[k]["url"], "from": a[k]["kind"], "to": None})
    return out


def collect(old: dict | None, when: str | None = None, fetch=fetch_or_none):
    """(sections, changes, error). On error the caller keeps the old set."""
    when = when or now_utc()
    old = old or {}
    body, err = fetch(SOURCE_URL, 40)
    if body is None:
        return old, [], err
    try:
        new = parse(body)
    except (ValueError, UnicodeDecodeError) as e:
        return old, [], f"unreadable: {type(e).__name__}"
    if len(new) < MIN_SECTIONS:
        return old, [], f"only {len(new)} sections found"
    return dict(sorted(new.items())), diff(old, new, when), None


def summary(sections: dict) -> str:
    """The health line: sections with an SFAR or KICZ NOTAM, and the entries by kind."""
    live = [s for s in sections.values() if s["entries"]]
    ent = [e for s in live for e in s["entries"].values()]
    n = {k: sum(1 for e in ent if e["kind"] == k) for k in KINDS}
    sfar = sum(1 for e in ent if e["key"].startswith("SFAR-"))
    return (f"{len(live)} of {len(sections)} sections with an SFAR or KICZ NOTAM: {sfar} SFARs, {len(ent) - sfar} "
            f"KICZ NOTAMs; {n['prohibition']} prohibitions, {n['advisory']} advisories, {n['pointer']} pointers"
            + (f", {n['notice']} other notices" if n["notice"] else ""))
