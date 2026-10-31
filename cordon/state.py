"""State Department travel advisories (official JSON, keyless) and post departure status read from their text.

State's feed gives 218 advisories with a FIPS country code, a title carrying the level, and the advisory text as
HTML. `Published` equals `Updated` on every item, so a revision is found by hashing the text. Departure status has
no field: it is read from the text with a phrase set, and every change is flagged for a person to review, because the
wording varies (Saudi Arabia, 23 Oct 2026: staff were "ordered ... to leave", not "ordered departure").
"""
import html
import json
import re

from .common import digest, fetch_or_none, fips_to_iso, now_utc

SOURCE_URL = "https://cadataapi.state.gov/api/TravelAdvisories"
LEVEL_RE = re.compile(r"Level\s+([1-4])\s*:\s*(.+)$", re.I)
TITLE_RE = re.compile(r"^(.*?)\s*(?:Travel Advisory)?\s*-\s*Level\s+[1-4]", re.I)
# The title decides where State's code is shared or isn't FIPS 10-4 (checked against the live feed, 31 Oct 2026:
# 14 advisories use ISO or State's own codes, e.g. Switzerland "SR", Guinea-Bissau "GW", Bonaire "A1").
TITLE_ISO = {
    "gaza": ("PS", "PS-GZ"), "the west bank": ("PS", "PS-WB"), "west bank": ("PS", "PS-WB"),
    "curaçao": ("CW", "CW"), "curacao": ("CW", "CW"), "são tomé and príncipe": ("ST", "ST"),
    "sao tome and principe": ("ST", "ST"), "sint maarten": ("SX", "SX"), "saint barthelemy": ("BL", "BL"),
    "bonaire": ("BQ", "BQ-BO"), "saba and sint eustatius": ("BQ", "BQ-SE"), "martinique": ("MQ", "MQ"),
    "switzerland": ("CH", "CH"), "french guiana": ("GF", "GF"), "turks and caicos islands": ("TC", "TC"),
    "saint kitts and nevis": ("KN", "KN"), "guinea-bissau": ("GW", "GW"), "tonga": ("TO", "TO"),
    "french west indies": ("GP", "FR-WI"), "french saint martin": ("MF", "MF"),  # State's MF is ISO, FIPS MF is Mayotte
}

# Departure status, most severe first. Each pattern must name the post, staff or family members leaving.
POSTURE = [
    ("suspended_operations", re.compile(
        r"(suspended (?:its |all |normal )?(?:operations|embassy operations|consular operations)"
        r"|(?:embassy|consulate)[^.]{0,80}(?:has |have )?(?:suspended operations|closed))", re.I)),
    ("ordered_departure", re.compile(
        r"(ordered (?:the )?departure|ordered non-emergency[^.]{0,160}to leave"
        r"|ordered[^.]{0,120}family members[^.]{0,60}to leave|on ordered departure)", re.I)),
    ("authorized_departure", re.compile(
        r"(authorized (?:the )?(?:voluntary )?departure|authorized non-emergency[^.]{0,160}to leave"
        r"|on authorized departure)", re.I)),
]


def plain(html_text: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html_text or "")
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def posture_of(text: str) -> dict:
    """{'state', 'sentence'} from the advisory text; 'normal' when no departure phrase matches.

    "U.S." becomes "US" first so sentences split on real full stops. Suspended operations counts only when the
    sentence names the embassy (Russia's text says its consulates suspended operations; the embassy still runs).
    """
    t = text.replace("U.S.", "US")
    for state, rx in POSTURE:
        for m in rx.finditer(t):
            start = t.rfind(".", 0, m.start()) + 1
            end = t.find(".", m.end())
            sentence = t[start:end + 1 if end > 0 else None].strip()
            if state == "suspended_operations" and not re.search(r"\bEmbassy\b", sentence):
                continue
            return {"state": state, "sentence": sentence[:400]}
    return {"state": "normal", "sentence": None}


def parse(items: list[dict]) -> dict:
    """{key: record} from State's JSON. key is the ISO code, or PS-GZ / PS-WB for Gaza and the West Bank."""
    out = {}
    for it in items:
        title = (it.get("Title") or "").strip()
        m = LEVEL_RE.search(title)
        if not m:
            continue
        title = re.sub(r"\s+", " ", title.replace("\xa0", " "))
        name_m = TITLE_RE.match(title)
        name = (name_m.group(1) if name_m else title.split(" - ")[0]).strip()
        cat = it.get("Category") or []
        if isinstance(cat, str):  # some responses carry the list as text, "['IR']"
            try:
                cat = json.loads(cat.replace("'", '"'))
            except ValueError:
                cat = []
        fips = cat[0] if cat else None
        iso, key = None, None
        if name.lower() in TITLE_ISO:
            iso, key = TITLE_ISO[name.lower()]
        elif fips:
            iso = fips_to_iso(fips)
            key = iso
        if not key:
            continue
        text = plain(it.get("Summary", ""))
        out[key] = {
            "key": key, "iso": iso, "fips": fips, "name": name, "title": title,
            "level": int(m.group(1)), "level_text": m.group(2).strip().rstrip("."),
            "link": it.get("Link"), "updated": it.get("Updated") or it.get("Published"),
            "text_hash": digest(text), "posture": posture_of(text), "words": len(text.split()),
        }
    return out


def diff(old: dict, new: dict, when: str) -> list[dict]:
    """Level, departure-status and text changes between two snapshots (new advisories and removals included)."""
    changes = []
    for key, rec in new.items():
        prev = old.get(key)
        base = {"at": when, "key": key, "iso": rec["iso"], "name": rec["name"], "link": rec["link"]}
        if prev is None:
            if old:  # not the first run
                changes.append({**base, "kind": "new", "from": None, "to": rec["level"]})
            continue
        if prev["level"] != rec["level"]:
            changes.append({**base, "kind": "level", "from": prev["level"], "to": rec["level"]})
        if prev["posture"]["state"] != rec["posture"]["state"]:
            changes.append({**base, "kind": "posture", "from": prev["posture"]["state"],
                            "to": rec["posture"]["state"], "sentence": rec["posture"]["sentence"],
                            "needs_review": True})
        elif prev["text_hash"] != rec["text_hash"]:
            changes.append({**base, "kind": "text", "from": prev.get("updated"), "to": rec.get("updated")})
    for key, prev in old.items():
        if key not in new:
            changes.append({"at": when, "key": key, "iso": prev["iso"], "name": prev["name"], "link": prev["link"],
                            "kind": "removed", "from": prev["level"], "to": None})
    return changes


def collect(old: dict | None, when: str | None = None, fetch=fetch_or_none):
    """(snapshot, changes, error). A failed fetch keeps the old snapshot and reports the error."""
    when = when or now_utc()
    body, err = fetch(SOURCE_URL, 40)
    if body is None:
        return old or {}, [], err
    try:
        new = parse(json.loads(body))
    except ValueError as e:
        return old or {}, [], f"parse: {e}"
    if len(new) < 150:  # State lists about 218; far fewer means a broken response, not 70 countries made safe
        return old or {}, [], f"only {len(new)} advisories parsed"
    return new, diff(old or {}, new, when), None
