"""NGA navigational warnings in force (NAVAREA IV and XII, HYDROLANT, HYDROPAC, HYDROARC), from NGA's Maritime
Safety Information site (US government, public domain).

Two forms of the same list, both NGA's own. The JSON API is tried first. It is accepted only when its newest warning
is recent: on 31 Oct 2026 it answered with a database whose newest warning was dated 10 May 2024, and from that
evening the whole site answered HTTP 503 with a maintenance page. That page links NGA's daily in-force lists as plain
text, one file per area, and those are read when the API fails or is stale. NGA issues warnings every day, so a list
whose newest warning is more than STALE_DAYS old is a stale list, never a quiet sea.

Each warning is plain text; positions are written like "19-23.0N 092-03.1W". Cordon keeps the text, the positions it
finds, and a category from the wording. The shape follows the wording (a shape crossing 180 degrees keeps its
longitudes continuous, so some run past 180): "AREA BOUND BY" is a polygon, "TRACKLINE
JOINING" a line, and "WITHIN N MILES OF" a position a circle (drawn as a polygon of CIRCLE_SIDES sides). "WITHIN N
MILES OF TRACKLINE JOINING" is the line, with N kept as the corridor's half-width. A warning with none of these
wordings is drawn as its points. NGA's "MILES" are nautical miles.
"""
import json
import math
import re
from datetime import datetime, timedelta, timezone

from .common import fetch_or_none, now_utc

SOURCE_URL = "https://msi.nga.mil/api/publications/broadcast-warn?output=json&status=active"
PAGE_URL = "https://msi.nga.mil/NavWarnings"
TEXT_URL = "https://msi.nga.mil/apology_objects/DailyMem{}.txt"
TEXT_FILES = {"4": "IV", "12": "XII", "A": "LAN", "P": "PAC", "C": "ARC"}
STALE_DAYS = 7
TEXT_MAX = 6000  # characters of warning text kept; longer text is cut with a note saying so (TEXT_CUT)
TEXT_CUT = "\n[Cut by Cordon: {} more characters. Full text: NGA, msi.nga.mil/NavWarnings]"
CIRCLE_SIDES = 32
EARTH_M = 6371008.8
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


BOUND_RE = re.compile(r"\b(?:AREAS?\s+)?BOUND(?:ED)?\s+BY:?", re.I)  # also "A. BOUND BY" (HYDROLANT 237/26)
PARAGRAPH_RE = re.compile(r"^\s*\d+\.\s", re.M)
LETTERED_RE = re.compile(r"^\s*[A-Z]\.\s", re.M)
CANCEL_AT_RE = re.compile(r"CANCEL THIS (?:MSG|MESSAGE) (\d{6}Z) ([A-Z]{3}) (\d{2})\b", re.I)
LINE_RE = re.compile(r"TRA?C?K ?LINES? JOINING:?", re.I)  # "TRAKLINE" is NGA's own spelling in HYDROLANT 2088/24
WITHIN_RE = re.compile(r"WITHIN\s+(\d+(?:\.\d+)?|[A-Z]+)\s+(?:NAUTICAL\s+)?(METERS?|METRES?|KILOMETERS?|KILOMETRES?|"
                       r"MILES?|NM|YARDS?|CABLES?)\s+OF:?", re.I)
NUMBER_WORDS = {w: i for i, w in enumerate(["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT",
                                             "NINE", "TEN", "ELEVEN", "TWELVE"])} | {"FIFTEEN": 15, "TWENTY": 20, "HALF": 0.5}
UNIT_M = {"METER": 1, "METRE": 1, "KILOMETER": 1000, "KILOMETRE": 1000, "MILE": 1852, "NM": 1852, "YARD": 0.9144,
          "CABLE": 185.2}


def distance_m(number: str, unit: str) -> float | None:
    """'12', 'MILES' -> 22224 m. NGA's miles are nautical miles; numbers come as digits or words."""
    n = float(number) if number[0].isdigit() else NUMBER_WORDS.get(number.upper())
    u = UNIT_M.get(unit.upper().rstrip("S"))
    return round(n * u, 1) if n and u else None


def unwrap(pts: list[list[float]]) -> list[list[float]]:
    """Longitudes made continuous along a ring or line: a shape that crosses 180 degrees (HYDROPAC 3257/26, from
    179-58W to 178-00E) carries on past the line (178-00E becomes -182.0) instead of being drawn the long way round
    the world. The first position sets the side."""
    out = []
    for lon, lat in pts:
        if out:
            lon += 360 * round((out[-1][0] - lon) / 360)
        out.append([round(lon, 3), lat])
    return out


def shapes(text: str) -> dict:
    """What a warning's wording draws: {"areas": [ring], "lines": [(points, half_width_m)], "circles": [(centre,
    radius_m)]}. Each "bound by", "trackline joining" or "within N of" runs to the next of them or the next numbered
    paragraph; inside it, lettered items (A., B., ...) are separate areas or lines. A "within N of" with no position
    before a trackline gives that line its half-width."""
    text = text or ""
    marks = sorted([(m.start(), m.end(), "area", None) for m in BOUND_RE.finditer(text)]
                   + [(m.start(), m.end(), "line", None) for m in LINE_RE.finditer(text)]
                   + [(m.start(), m.end(), "within", distance_m(m.group(1), m.group(2))) for m in WITHIN_RE.finditer(text)])
    out, width = {"areas": [], "lines": [], "circles": []}, None
    for n, (_, end, kind, dist) in enumerate(marks):
        tail = text[end:marks[n + 1][0] if n + 1 < len(marks) else len(text)]
        stop = PARAGRAPH_RE.search(tail)
        tail = tail[:stop.start()] if stop else tail
        if kind == "within":
            pts = positions(tail)
            if not pts and n + 1 < len(marks) and marks[n + 1][2] == "line":
                width = dist  # "WITHIN 500 METERS OF TRACKLINE JOINING"
            elif dist:
                out["circles"] += [(p, dist) for p in pts]
            continue
        for chunk in LETTERED_RE.split(tail):
            pts = positions(chunk)
            pts = unwrap(pts)
            if kind == "area" and len(pts) >= 3:
                out["areas"].append(pts + [pts[0]] if pts[0] != pts[-1] else pts)
            elif kind == "line" and len(pts) >= 2:
                out["lines"].append((pts, width))
        width = None
    return out


def areas(text: str) -> list[list[list[float]]]:
    """One closed ring for each area a warning bounds (see shapes)."""
    return shapes(text)["areas"]


def circle(centre: list[float], radius_m: float, sides: int = CIRCLE_SIDES) -> list[list[float]]:
    """A closed ring of `sides` points at radius_m around [lon, lat] (spherical earth; the radii in warnings are a few
    miles, so the flat approximation is well under a metre out)."""
    lon0, lat0 = centre
    d = math.degrees(radius_m / EARTH_M)
    ring = [[round(lon0 + d * math.sin(b) / max(math.cos(math.radians(lat0)), 0.01), 4), round(lat0 + d * math.cos(b), 4)]
            for b in (2 * math.pi * i / sides for i in range(sides))]
    return ring + [ring[0]]


def cancel_time(text: str) -> str | None:
    """'CANCEL THIS MSG 220300Z NOV 26' -> '2026-11-22T03:00:00Z': when the warning says it ends."""
    m = CANCEL_AT_RE.search(re.sub(r"\s+", " ", text or ""))
    return issued_time(f"{m.group(1)} {m.group(2).upper()} {2000 + int(m.group(3))}") if m else None


def in_force(w: dict, when: str) -> bool:
    """False once a warning's own cancel time has passed (NGA's lists are refreshed once a day)."""
    return not (w.get("cancel_at") and w["cancel_at"] <= when)


def geometry(text: str, pts: list[list[float]]):
    """Polygons for areas and circles, lines for tracklines (a GeometryCollection when a warning has both), else the
    positions as points."""
    if not pts:
        return None
    s = shapes(text)
    rings = s["areas"] + [circle(c, r) for c, r in s["circles"]]
    lines = [p for p, _ in s["lines"]]
    parts = []
    if rings:
        parts.append({"type": "Polygon", "coordinates": [rings[0]]} if len(rings) == 1
                     else {"type": "MultiPolygon", "coordinates": [[r] for r in rings]})
    if lines:
        parts.append({"type": "LineString", "coordinates": lines[0]} if len(lines) == 1
                     else {"type": "MultiLineString", "coordinates": lines})
    if len(parts) == 1:
        return parts[0]
    if parts:
        return {"type": "GeometryCollection", "geometries": parts}
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
    s = shapes(text)
    rec = {
        "id": f"{area}-{number}-{year}", "area": AREAS.get(area, area), "subregion": subregion,
        "number": f"{AREAS.get(area, area)} {number}/{year}", "issued": issued,
        "authority": (authority or "").strip()[:160], "category": category(text), "sea": sea, "place": place,
        "headline": head, "text": text if len(text) <= TEXT_MAX else text[:TEXT_MAX] + TEXT_CUT.format(len(text) - TEXT_MAX),
        "geometry": geometry(text, positions(text)), "cancel_at": cancel_time(text),
    }
    if s["circles"]:
        rec["radius_m"] = sorted({r for _, r in s["circles"]})
    if any(w for _, w in s["lines"]):
        rec["corridor_half_width_m"] = sorted({w for _, w in s["lines"] if w})
    return rec


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


def _from_text(fetch, when: str, old: list[dict] | None = None):
    """(warnings, error, held). One file per area. A file that fails, or yields no warnings, keeps that area's
    warnings from `old` while at least one other file answers; `held` maps each such area to the reason. With every
    file failing, the error names the first."""
    out, held = [], {}
    for area, name in TEXT_FILES.items():
        body, err = fetch(TEXT_URL.format(name), 60)
        got = parse_text(body.decode("utf-8", "replace"), area) if body is not None else []
        if not got:
            held[AREAS[area]] = err or "no warnings parsed"
            out += [w for w in old or [] if w.get("area") == AREAS[area]]
            continue
        out += got
    if len(held) == len(TEXT_FILES):
        name, err = next(iter(held.items()))
        return None, f"{name}: {err}", {}
    new, err = _fresh(out, when)
    return new, err, held


# Rebroadcasts. NGA puts some warnings out in two series (NAVAREA XII 788/26 and HYDROPAC 3257/26 on 13 Nov 2026) and
# neither copy cites the other, so they are matched on what they say: same category, the same time groups, and the
# same positions in the same order. A NAVAREA copy leads, then the earliest issued.
REBROADCAST_TOL = 0.05  # degrees; positions further apart than this differ
TIME_TOKEN_RE = re.compile(r"\b\d{4}(?:\d{2})?Z\b")
SERIES_RANK = {"NAVAREA IV": 0, "NAVAREA XII": 0}


def _same_place(a: list[list[float]], b: list[list[float]]) -> list[int] | None:
    """Indexes of the positions that differ, or None when the two are not the same shape. Up to a fifth of the
    positions may differ (at least one, from three positions up); fewer than three must match exactly."""
    if not a or len(a) != len(b):
        return None
    diff = [i for i, (p, q) in enumerate(zip(a, b))
            if abs((p[0] - q[0] + 180) % 360 - 180) > REBROADCAST_TOL or abs(p[1] - q[1]) > REBROADCAST_TOL]
    allowed = max(1, len(a) // 5) if len(a) >= 3 else 0
    return diff if len(diff) <= allowed else None


def rebroadcasts(warnings: list[dict]) -> tuple[dict, dict]:
    """({lead id: [rebroadcast, ...]}, {rebroadcast id: lead id}). Each group holds at most one warning per series.
    A rebroadcast is listed with its number, issue time, and every position that differs from the lead's, as both
    were written; nothing is corrected."""
    def key(w):
        return (SERIES_RANK.get(w.get("area"), 1), issued_time(w.get("issued")) or "9999", w["id"])
    sig = {w["id"]: (positions(w.get("text")),
                     tuple(sorted(TIME_TOKEN_RE.findall(re.sub(r"\s+", " ", (w.get("text") or "").upper())))))
           for w in warnings}
    groups, leads, merged = [], {}, {}
    for w in sorted(warnings, key=key):
        pts, times = sig[w["id"]]
        for g in groups:
            lead = g[0]
            lpts, ltimes = sig[lead["id"]]
            if (lead["category"] != w["category"] or ltimes != times
                    or w.get("area") in {m.get("area") for m in g}):
                continue
            diff = _same_place(lpts, pts)
            if diff is None:
                continue
            g.append(w)
            merged[w["id"]] = lead["id"]
            leads.setdefault(lead["id"], []).append({
                "id": w["id"], "number": w["number"], "issued": issued_time(w.get("issued")),
                "vertex_differences": [{"position": i + 1, "lead": lpts[i], "rebroadcast": pts[i]} for i in diff]})
            break
        else:
            groups.append([w])
    return leads, merged


def held_too_long(held_areas: dict | None, when: str, hours: float) -> set[str]:
    """Areas whose list has been held (kept from an earlier fetch) since before `hours` ago."""
    limit = (datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ") - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {a for a, h in (held_areas or {}).items() if (h.get("since") or when) < limit}


def collect(old: list[dict] | None, when: str | None = None, fetch=fetch_or_none):
    """(warnings, error, source, held). The API first, then the daily text lists; a form that fails, or whose newest
    warning is over STALE_DAYS old, is passed over. With neither usable the previous warnings are kept and the error
    names both failures, so health never records a stale list as a good fetch. `held` names the areas whose text file
    failed this run and whose previous warnings were kept (see _from_text)."""
    when = when or now_utc()
    new, api_err = _from_api(fetch, when)
    if new:
        return new, None, SOURCE_URL, {}
    new, text_err, held = _from_text(fetch, when, old)
    if new:
        return new, None, TEXT_URL.format("*"), held
    return old or [], f"API: {api_err}; daily lists: {text_err}", None, {}
