"""NGA navigational warnings in force (NAVAREA IV and XII, HYDROLANT, HYDROPAC, HYDROARC), from NGA's Maritime
Safety Information API (US government, public domain).

Each warning is plain text; positions are written like "19-23.0N 092-03.1W". Cordon keeps the text, the positions it
finds, and a category from the wording. A warning that says "AREA BOUND BY" is drawn as a polygon; otherwise its
positions are points.
"""
import json
import re

from .common import fetch_or_none, now_utc

SOURCE_URL = "https://msi.nga.mil/api/publications/broadcast-warn?output=json&status=active"
PAGE_URL = "https://msi.nga.mil/NavWarnings"
AREAS = {"4": "NAVAREA IV", "12": "NAVAREA XII", "A": "HYDROLANT", "P": "HYDROPAC", "C": "HYDROARC"}
POS_RE = re.compile(r"(\d{1,2})-(\d{2}(?:\.\d+)?)\s*([NS])\s+(\d{1,3})-(\d{2}(?:\.\d+)?)\s*([EW])")
# First match wins, most consequential first.
CATEGORIES = [
    ("launch", r"ROCKET|MISSILE|SPACE DEBRIS|LAUNCH"),
    ("gnss", r"\bGNSS\b|\bGPS\b|JAMMING|SPOOFING"),
    ("military", r"GUNNERY|FIRING|NAVAL EXERCISE|MILITARY EXERCISE|LIVE FIRE|HAZARDOUS OPERATIONS"),
    ("mines", r"\bMINE\b|MINES\b|UNEXPLODED|ORDNANCE"),
    ("piracy", r"PIRACY|PIRATE|ARMED ROBBERY|HIJACK"),
    ("search_and_rescue", r"SEARCH AND RESCUE|OVERDUE|MISSING VESSEL|PERSON IN WATER|TAKING ON WATER|"
                          r"KEEP A SHARP LOOKOUT"),
    ("pollution", r"OIL SPILL|POLLUTION"),
    ("port", r"\bPORT OF\b|PORT [A-Z ]{0,30}(CLOSED|RESTRICTIONS)|CHANNEL CLOSED"),
    ("radio_service", r"OFF AIR|UNRELIABLE|\bDSC\b|NAVTEX|RADIO STATION|COMMUNICATION FACILIT"),
    ("wreck", r"WRECK|DERELICT|ADRIFT|SUNKEN|SUBMERGED|ABANDONED VESSEL"),
    ("cable_pipeline", r"CABLE|PIPELINE"),
    ("underwater_ops", r"UNDERWATER OPERATIONS|DIVING|\bROV\b|SALVAGE"),
    ("drilling_survey", r"DRILLING|SURVEY|SEISMIC|RIG\b"),
    ("shoal", r"SHOAL|LESS WATER THAN CHARTED|DEPTH OF"),
    ("hazard", r"REEF|AGROUND|OBSTRUCTION|UNCHARTED|ROCK\b"),
    ("restricted_area", r"ANCHORING PROHIBITED|PROHIBITED AREA|RESTRICTED AREA|SAFETY ZONE|EXCLUSION ZONE"),
    ("aids_to_navigation", r"LIGHT|BUOY|RACON|BEACON|AIS AID|NAVIGATIONAL AIDS|INOPERATIVE"),
]
INDEX_RE = re.compile(r"WARNINGS IN FORCE", re.I)
SELF_CANCEL_RE = re.compile(r"^\s*(?:\d+\.\s*)?CANCEL\b[^\n]*\bTHIS (?:MSG|MESSAGE)\b", re.I | re.M)


def headline(text: str) -> tuple[str | None, str]:
    """(place, headline): skip the sea-area line, take a short place line, then the warning's own words."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    place = None
    i = 0
    if lines and len(lines[0].split()) <= 5 and lines[0].endswith("."):
        i = 1
        if len(lines) > 2 and len(lines[1].split()) <= 4 and lines[1].endswith(".") and not POS_RE.search(lines[1]):
            place = lines[1].rstrip(".").title()
            i = 2
    body = " ".join(lines[i:])
    body = re.sub(r"^\d+\.\s*", "", body)
    body = re.sub(r"\s+", " ", body)
    cut = body.find(". ")
    return place, (body[:cut + 1] if 0 < cut < 160 else body[:160]).strip()


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
    t = (text or "").upper()
    for name, rx in CATEGORIES:
        if re.search(rx, t):
            return name
    return "other"


def geometry(text: str, pts: list[list[float]]):
    if not pts:
        return None
    if len(pts) >= 3 and re.search(r"AREA[S]? BOUND", (text or "").upper()):
        ring = pts + [pts[0]] if pts[0] != pts[-1] else pts
        return {"type": "Polygon", "coordinates": [ring]}
    if len(pts) == 1:
        return {"type": "Point", "coordinates": pts[0]}
    return {"type": "MultiPoint", "coordinates": pts}


def parse(doc: dict) -> list[dict]:
    out = []
    for w in doc.get("broadcast-warn", []):
        text = (w.get("text") or "").strip()
        if INDEX_RE.search(text[:200]):
            continue  # a list of warnings in force, not a warning
        place_line, head_line = headline(text)
        if SELF_CANCEL_RE.match(head_line or ""):
            continue  # "cancel ... and this msg": the hazard is over
        area = str(w.get("navArea") or "")
        pts = positions(text)
        first = text.splitlines()[0].strip() if text else ""
        sea = None if (not first or first[0].isdigit()) else first.rstrip(".").title()
        place, head = place_line, head_line
        out.append({
            "id": f"{area}-{w.get('msgNumber')}-{w.get('msgYear')}", "area": AREAS.get(area, area),
            "subregion": w.get("subregion"), "number": f"{AREAS.get(area, area)} {w.get('msgNumber')}/{w.get('msgYear')}",
            "issued": w.get("issueDate"), "authority": (w.get("authority") or "").strip()[:160],
            "category": category(text), "sea": sea, "place": place, "headline": head,
            "text": text[:2000], "geometry": geometry(text, pts),
        })
    return out


def collect(old: list[dict] | None, when: str | None = None, fetch=fetch_or_none):
    when = when or now_utc()
    body, err = fetch(SOURCE_URL, 60)
    if body is None:
        return old or [], err
    try:
        new = parse(json.loads(body))
    except ValueError as e:
        return old or [], f"parse: {e}"
    if not new:
        return old or [], "no warnings parsed"
    return new, None
