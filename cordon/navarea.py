"""NGA navigational warnings in force (NAVAREA IV and XII, HYDROLANT, HYDROPAC, HYDROARC), from NGA's Maritime
Safety Information site (US government, public domain).

Two forms of the same list, both NGA's own. The JSON API is tried first. It is accepted only when its newest warning
is recent: on 31 Oct 2026 it answered with a database whose newest warning was dated 10 May 2024, and from that
evening the whole site answered HTTP 503 with a maintenance page. That page links NGA's daily in-force lists as plain
text, one file per area, and those are read when the API fails or is stale. NGA issues warnings every day, so a list
whose newest warning is more than STALE_DAYS old is a stale list, never a quiet sea.

Each warning is plain text; positions are written like "19-23.0N 092-03.1W". Cordon keeps the text, the positions it
finds, and a category from the wording. A warning that says "AREA BOUND BY" is drawn as a polygon; otherwise its
positions are points.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from .common import fetch_or_none, now_utc

SOURCE_URL = "https://msi.nga.mil/api/publications/broadcast-warn?output=json&status=active"
PAGE_URL = "https://msi.nga.mil/NavWarnings"
TEXT_URL = "https://msi.nga.mil/apology_objects/DailyMem{}.txt"
TEXT_FILES = {"4": "IV", "12": "XII", "A": "LAN", "P": "PAC", "C": "ARC"}
STALE_DAYS = 7
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
AREAS = {"4": "NAVAREA IV", "12": "NAVAREA XII", "A": "HYDROLANT", "P": "HYDROPAC", "C": "HYDROARC"}
POS_RE = re.compile(r"(\d{1,2})-(\d{2}(?:\.\d+)?)\s*([NS])\s+(\d{1,3})-(\d{2}(?:\.\d+)?)\s*([EW])")
# First match wins, most consequential first.
CATEGORIES = [
    ("launch", r"ROCKET|MISSILE|SPACE DEBRIS|LAUNCH"),
    ("gnss", r"\bGNSS\b|\bGPS\b|JAMMING|SPOOFING"),
    ("military", r"GUNNERY|FIRING|NAVAL EXERCISE|MILITARY EXERCISE|LIVE FIRE|HAZARDOUS OPERATIONS"),
    ("mines", r"\bMINE\b|MINES\b|UNEXPLODED|ORDNANCE"),
    ("piracy", r"PIRACY|PIRATE|ARMED ROBBERY|HIJACK"),
    ("security", r"SECURITY INCIDENT|\bATTACK(ED)?\b|EXPLOSION"),
    ("search_and_rescue", r"SEARCH AND RESCUE|OVERDUE|MISSING VESSEL|PERSON IN WATER|TAKING ON WATER|"
                          r"KEEP A SHARP LOOKOUT"),
    ("pollution", r"OIL SPILL|POLLUTION"),
    ("port", r"\bPORT OF\b|PORT [A-Z ]{0,30}(CLOSED|RESTRICTIONS)|CHANNEL CLOSED"),
    ("radio_service", r"OFF AIR|UNRELIABLE|\bDSC\b|NAVTEX|RADIO STATION|COMMUNICATION FACILIT|E-?MAIL [A-Z ]*UNUSABLE|"
                      r"HF RECEIVE|UNABLE TO RECEIVE|DISSEMINATION ADVISORY|\(ENC\) ADVISORY"),
    ("ice", r"ICEBERG|SEA ICE|ICE LIMIT"),
    ("wreck", r"WRECK|DERELICT|ADRIFT|SUNKEN|SUBMERGED|ABANDONED VESSEL|\bSANK\b|\bSUNK\b|ON FIRE|CAPSIZED"),
    ("cable_pipeline", r"CABLE|PIPELINE"),
    ("underwater_ops", r"UNDERWATER OPERATIONS|DIVING|\bROV\b|SALVAGE"),
    ("drilling_survey", r"DRILLING|SURVEY|SEISMIC|RIG\b|MINING OPERATIONS"),
    ("shoal", r"SHOAL|LESS (WATER )?THAN CHARTED|DEPTHS? (OF|REPORTED)|DISCOLORED WATER"),
    ("hazard", r"REEF|AGROUND|OBSTRUCTION|UNCHARTED|ROCK\b|FOUL GROUND|SCIENTIFIC MOORING|OCEAN BOTTOM MOORING|"
               r"VOLCANIC|PLATFORM [A-Z ]*ESTABLISHED"),
    ("restricted_area", r"ANCHORING PROHIBITED|NAVIGATION PROHIBITED|PROHIBITED AREA|RESTRICTED AREA|SAFETY ZONE|EXCLUSION ZONE"),
    ("aids_to_navigation", r"LIGHT|BUOY|RACON|BEACON|AIS AID|NAVIGATIONAL AIDS|INOPERATIVE"),
]
INDEX_RE = re.compile(r"WARNINGS IN FORCE", re.I)
SELF_CANCEL_RE = re.compile(r"^\s*(?:\d+\.\s*)?CANCEL\b[^\n]*\bTHIS (?:MSG|MESSAGE)\b", re.I | re.M)


CHART_RE = re.compile(r"^(DNC|CHART|ENC)S? [\dA-Z, ]+\.?$")
PLACE_RE = re.compile(r"^[A-Z][A-Z '.\-]*$")  # also "U.A.E." and "ST. KITTS AND NEVIS."
NUMBERED_RE = re.compile(r"^\d+\.\s")


def _header_kind(line: str) -> str | None:
    """'chart' for a chart reference (DNC 10.), 'place' for a sea or country line, None for the warning's own words.
    A place line is a few plain words that name no hazard: "LIGHTS UNLIT" and "HAZARDOUS OPERATIONS" are not places."""
    if CHART_RE.match(line):
        return "chart"
    if PLACE_RE.match(line) and len(line.split()) <= 5 and category(line) == "other":
        return "place"
    return None


def header(text: str) -> tuple[str | None, str | None, str]:
    """(sea, place, headline). A warning opens with its sea areas, often a country or place, sometimes a chart
    reference; then come its own words. The sea is the first of those lines and the place the last (when there are
    two or more); the headline is the first sentence after them. The last line is never taken as a header, and a
    line with no full stop counts only when another header line or a numbered paragraph follows it."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    places, i = [], 0
    while i < len(lines) - 1:
        kind = _header_kind(lines[i])
        if not kind:
            break
        if kind == "place":
            if not lines[i].endswith(".") and not (_header_kind(lines[i + 1]) or NUMBERED_RE.match(lines[i + 1])):
                break
            places.append(lines[i].rstrip(".").title())
        i += 1
    body = re.sub(r"\s+", " ", re.sub(r"^\d+\.\s*", "", " ".join(lines[i:])))
    cut = body.find(". ")
    head = (body[:cut + 1] if 0 < cut < 160 else body[:160]).strip()
    head = re.sub(r"\s*[:,]?\s+(?:A|1)\.$", "", head)  # "LIGHTS UNLIT: A." -> "LIGHTS UNLIT": the list follows in the text
    return (places[0] if places else None), (places[-1] if len(places) > 1 else None), head


def positions(text: str) -> list[list[float]]:
    """[[lon, lat], ...] in the order written, rounded to 0.001 degree."""
    out = []
    for d1, m1, ns, d2, m2, ew in POS_RE.findall(text or ""):
        lat = int(d1) + float(m1) / 60
        lon = int(d2) + float(m2) / 60
        if lat > 90 or lon > 180:
            continue
        out.append([round(-lon if ew == "W" else lon, 3), round(-lat if ns == "S" else lat, 3)])
    return out


def category(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").upper())  # the wording wraps across lines
    for name, rx in CATEGORIES:
        if re.search(rx, t):
            return name
    return "other"


BOUND_RE = re.compile(r"AREAS? BOUND(?:ED)? BY:?", re.I)
PARAGRAPH_RE = re.compile(r"^\s*\d+\.\s", re.M)
LETTERED_RE = re.compile(r"^\s*[A-Z]\.\s", re.M)
CANCEL_AT_RE = re.compile(r"CANCEL THIS (?:MSG|MESSAGE) (\d{6}Z) ([A-Z]{3}) (\d{2})\b", re.I)


def areas(text: str) -> list[list[list[float]]]:
    """One closed ring for each area a warning bounds. "AREA BOUND BY" is followed by one area's corners; "AREAS
    BOUND BY:" by lettered areas (A., B., ...), each with its own corners. An area ends at the next lettered item, the
    next numbered paragraph or the next "bound by"."""
    text = text or ""
    rings = []
    marks = list(BOUND_RE.finditer(text))
    for n, m in enumerate(marks):
        tail = text[m.end():marks[n + 1].start() if n + 1 < len(marks) else len(text)]
        stop = PARAGRAPH_RE.search(tail)
        tail = tail[:stop.start()] if stop else tail
        for chunk in LETTERED_RE.split(tail):
            pts = positions(chunk)
            if len(pts) >= 3:
                rings.append(pts + [pts[0]] if pts[0] != pts[-1] else pts)
    return rings


def cancel_time(text: str) -> str | None:
    """'CANCEL THIS MSG 220300Z NOV 26' -> '2026-11-22T03:00:00Z': when the warning says it ends."""
    m = CANCEL_AT_RE.search(re.sub(r"\s+", " ", text or ""))
    return issued_time(f"{m.group(1)} {m.group(2).upper()} {2000 + int(m.group(3))}") if m else None


def in_force(w: dict, when: str) -> bool:
    """False once a warning's own cancel time has passed (NGA's lists are refreshed once a day)."""
    return not (w.get("cancel_at") and w["cancel_at"] <= when)


def geometry(text: str, pts: list[list[float]]):
    if not pts:
        return None
    rings = areas(text)
    if len(rings) == 1:
        return {"type": "Polygon", "coordinates": [rings[0]]}
    if rings:
        return {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
    if len(pts) == 1:
        return {"type": "Point", "coordinates": pts[0]}
    return {"type": "MultiPoint", "coordinates": pts}


def issued_time(s: str) -> str | None:
    """'081653Z MAY 2024' -> '2024-05-08T16:53:00Z'."""
    m = re.match(r"(\d{2})(\d{2})(\d{2})Z\s+([A-Z]{3})\s+(\d{4})", (s or "").strip().upper())
    if not m or m.group(4) not in MONTHS:
        return None
    try:
        return datetime(int(m.group(5)), MONTHS[m.group(4)], int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def newest(warnings: list[dict] | None) -> str | None:
    """The latest issue time in a set of warnings, as UTC; None when no warning carries a readable one."""
    return max((t for t in (issued_time(w.get("issued")) for w in warnings or []) if t), default=None)


def is_stale(newest_at: str | None, when: str) -> bool:
    """True when the newest warning is more than STALE_DAYS before `when` (or there is none to date)."""
    if not newest_at:
        return True
    limit = datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ") - timedelta(days=STALE_DAYS)
    return newest_at < limit.strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(area: str, number, year, subregion, issued, authority: str, text: str) -> dict | None:
    """One warning as Cordon keeps it; None for an index list or a message that only cancels."""
    text = (text or "").strip()
    if INDEX_RE.search(text[:200]):
        return None  # a list of warnings in force, not a warning
    sea, place, head = header(text)
    if SELF_CANCEL_RE.match(head or ""):
        return None  # "cancel ... and this msg": the hazard is over
    return {
        "id": f"{area}-{number}-{year}", "area": AREAS.get(area, area), "subregion": subregion,
        "number": f"{AREAS.get(area, area)} {number}/{year}", "issued": issued,
        "authority": (authority or "").strip()[:160], "category": category(text), "sea": sea, "place": place,
        "headline": head, "text": text[:2000], "geometry": geometry(text, positions(text)),
        "cancel_at": cancel_time(text),
    }


def parse(doc: dict) -> list[dict]:
    """Warnings from the JSON API."""
    out = []
    for w in doc.get("broadcast-warn", []):
        r = _record(str(w.get("navArea") or ""), w.get("msgNumber"), w.get("msgYear"), w.get("subregion"),
                    w.get("issueDate"), w.get("authority"), w.get("text"))
        if r:
            out.append(r)
    return out


TEXT_DATE_RE = re.compile(r"^(\d{6}Z) ([A-Z]{3}) (\d{2})\.?\s*$")
TEXT_HEAD_RE = re.compile(r"^(NAVAREA IV|NAVAREA XII|HYDROLANT|HYDROPAC|HYDROARC) (\d+)/(\d{2})(?:\(([A-Z0-9, ]+)\))?\.?\s*$")


def parse_text(text: str, area: str) -> list[dict]:
    """Warnings from one of NGA's daily in-force lists. Each message opens with its date-time group on one line
    ("120859Z NOV 26") and its number on the next ("NAVAREA IV 1090/26." or "HYDROPAC 3306/26(63)."); the text runs
    to the next such pair. Ids match the API's, so a warning keeps its id whichever form it was read from."""
    lines = (text or "").replace("\r", "").split("\n")
    starts = [i for i in range(len(lines) - 1) if TEXT_DATE_RE.match(lines[i]) and
              (TEXT_HEAD_RE.match(lines[i + 1]) or ("", ""))[1] == AREAS[area]]
    out = []
    for n, i in enumerate(starts):
        d, h = TEXT_DATE_RE.match(lines[i]), TEXT_HEAD_RE.match(lines[i + 1])
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        r = _record(area, int(h.group(2)), 2000 + int(h.group(3)), h.group(4),
                    f"{d.group(1)} {d.group(2)} {2000 + int(d.group(3))}", "",
                    "\n".join(ln.rstrip() for ln in lines[i + 2:end]))
        if r:
            out.append(r)
    return out


def _fresh(new: list[dict], when: str):
    at = newest(new)
    return (None, f"stale: newest warning {(at or 'undated')[:10]}") if is_stale(at, when) else (new, None)


def _from_api(fetch, when: str):
    body, err = fetch(SOURCE_URL, 60)
    if body is None:
        return None, err
    try:
        new = parse(json.loads(body))
    except ValueError as e:
        return None, f"parse: {e}"
    return _fresh(new, when) if new else (None, "no warnings parsed")


def _from_text(fetch, when: str):
    out = []
    for area, name in TEXT_FILES.items():
        body, err = fetch(TEXT_URL.format(name), 60)
        if body is None:
            return None, f"{AREAS[area]}: {err}"
        got = parse_text(body.decode("utf-8", "replace"), area)
        if not got:
            return None, f"{AREAS[area]}: no warnings parsed"
        out += got
    return _fresh(out, when)


def collect(old: list[dict] | None, when: str | None = None, fetch=fetch_or_none):
    """(warnings, error, source). The API first, then the daily text lists; a form that fails, or whose newest
    warning is over STALE_DAYS old, is passed over. With neither usable the previous warnings are kept and the error
    names both failures, so health never records a stale list as a good fetch."""
    when = when or now_utc()
    new, api_err = _from_api(fetch, when)
    if new:
        return new, None, SOURCE_URL
    new, text_err = _from_text(fetch, when)
    if new:
        return new, None, TEXT_URL.format("*")
    return old or [], f"API: {api_err}; daily lists: {text_err}", None
