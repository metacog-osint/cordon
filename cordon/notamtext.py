"""A NOTAM's own words, read: its Q) line, its items A) to G), its D) schedule as UTC windows, and the shape its E)
text draws (method cordon-feed-1.3, 26 Nov 2026).

Used for Cordon's NOTAM feed items (cordon/feed.py notam_items) and for the space-operations areas Launch reads
(cordon/notamlaunch.py, /data/notams/launch.json). Nothing here adds a cause, a time or a place the NOTAM does not
state: a schedule or a shape Cordon cannot read in full is left unread and says so, and the NOTAM's own text is
always kept beside what was read from it.

  - qline(): the Q) line's FIR, Q-code, lower and upper flight levels, centre and radius (NM; 999 is the whole FIR).
  - items(): the text of each item A) to G), found in order (a ")" inside E) is not an item).
  - windows(): the D) schedule within B) and C) as UTC [start, end] pairs. Read: times (0800-1600, 2253 - 2359,
    0800 TO 1600, 0000/0700, H24), days (05, 04 11 18 25), day ranges (01-05, 30-02 across a month end), month
    names (NOV 28 ..., DEC 01-04), week days (MON, TUE-FRI), DLY, DAILY and EVERY, BTN, EXC of days or week days
    (EXC SAT SUN, EXC 25-26), and written-out windows (2611242330 TO 2611250800). A time with no days of its own
    holds every day (or the named week days) from B) to C), clipped to B) and C), so an overnight 2200-1000 runs
    from B) to the morning after; a window that ends at or before its start ends the next day (2217-0155). A day
    number lower than the one before it, with no month named, is in the next month; a new group of days after a
    time, with no month named anywhere, starts again from B)'s month. Not read (window_mode "span", the one window
    B) to C)): sunrise and sunset (SR, SS, HJ, HN), anything else, and any window from named days that would fall
    outside B) to C) (a misread, not a clip). Measured 26 Nov 2026 on 6,131 active NOTAMs with a D) item: 3,820
    daily, 1,566 schedule, 737 span (about half of those sunrise or sunset), 8 with no window.
  - shape(): polygons from runs of three or more positions joined only by separators (-, commas, TO, AND), not on
    a line, route, track or corridor; circles from "RADIUS n NM|KM|M CENTRE(D) ON <position>", "n NM RADIUS OF
    <position>" and "CENTRE <position> RADIUS n"; a circle the text excludes (EXC A CIRCLE ...) is not drawn.
    Arcs are not read. Circles are 32-sided polygons, as Cordon draws NGA's.
  - geometry(): the footprint for the map, first that applies: the shape from the E) text (the NOTAM's own words),
    NMS's own polygon (when it is not the Q) line circle and sits where the Q) line puts the NOTAM: on 26 Nov 2026,
    562 of 855 international NOTAMs with an NMS polygon had it elsewhere, often a circle round the A) aerodrome),
    the Q) line circle, the Q) line centre (radius 999 or none), NMS's point.

Standard library only.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

NM_M = 1852.0
EARTH_M = 6371008.8
CIRCLE_SIDES = 32

QLINE = re.compile(r"Q\)\s*([A-Z0-9]{3,4})\s*/\s*(Q[A-Z]{4})\s*/[^/\n]*/[^/\n]*/[^/\n]*/\s*(\d{3})\s*/\s*(\d{3})\s*/"
                   r"\s*(\d{2})(\d{2})([NS])\s*(\d{3})(\d{2})([EW])\s*(\d{3})?")
ITEM_LETTERS = "ABCDEFG"


# ---------- Q) line and items ----------

def qline(text: str | None) -> dict | None:
    """{fir, code, lower_fl, upper_fl, lat, lon, radius_nm} from the Q) line, or None."""
    m = QLINE.search(text or "")
    if not m:
        return None
    lat = int(m.group(5)) + int(m.group(6)) / 60
    lon = int(m.group(8)) + int(m.group(9)) / 60
    return {"fir": m.group(1), "code": m.group(2), "lower_fl": int(m.group(3)), "upper_fl": int(m.group(4)),
            "lat": round(-lat if m.group(7) == "S" else lat, 4), "lon": round(-lon if m.group(10) == "W" else lon, 4),
            "radius_nm": int(m.group(11)) if m.group(11) else None}


def items(text: str | None) -> dict:
    """{letter: text} for the items A) to G), each found after the one before it."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    found, pos = [], 0
    for letter in ITEM_LETTERS:
        m = re.compile(r"(?:^|(?<=[\s)]))" + letter + r"\)\s*").search(t, pos)
        if m:
            found.append((letter, m.start(), m.end()))
            pos = m.end()
    out = {}
    for i, (letter, _, body) in enumerate(found):
        stop = found[i + 1][1] if i + 1 < len(found) else len(t)
        out[letter] = t[body:stop].strip()
    return out


def e_text(icao: str | None, fallback: str | None = None) -> str:
    """The E) item, the NOTAM's own words (the whole text when it has no items)."""
    e = items(icao).get("E")
    if e:
        return e
    return (fallback or icao or "").replace("\r\n", "\n").replace("\r", "\n").strip()


# ---------- the D) schedule ----------

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
WD = "|".join(WEEKDAYS)
TOKEN = re.compile(
    r"(?P<dtp>(?<!\d)(?P<t0>\d{10})\s*(?:-|TO)\s*(?P<t1>\d{10})(?!\d))"
    r"|(?P<time>(?<!\d)(?P<h0>\d{2})(?P<m0>\d{2})\s*(?:-|/|TO)\s*(?P<h1>\d{2})(?P<m1>\d{2})(?!\d))"
    r"|(?P<h24>\bH24\b)"
    r"|(?P<range>(?<!\d)(?P<d0>\d{1,2})\s*-\s*(?P<d1>\d{1,2})(?!\d))"
    r"|(?P<day>(?<!\d)\d{1,2}(?!\d))"
    r"|(?P<mon>\b(?:" + "|".join(MONTHS) + r")\b)"
    r"|(?P<wday>\b(?P<w0>" + WD + r")\b(?:\s*-\s*(?P<w1>" + WD + r")\b)?)"
    r"|(?P<daily>\b(?:DLY|DAILY)\b)"
    r"|(?P<exc>\bEXC(?:EPT)?\b)"
    r"|(?P<skip>\b(?:BTN|AND|UTC|EVERY)\b)"
    r"|(?P<sep>[\s,;.:/]+)"
    r"|(?P<other>\S+)")
MAX_WINDOWS = 400


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


class _Unread(Exception):
    pass


def _date(year: int, month: int, day: int) -> datetime:
    while month > 12:
        year, month = year + 1, month - 12
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError as e:
        raise _Unread(str(e)) from e


def _days(d0: datetime, d1: datetime) -> list[datetime]:
    out = []
    while d0 <= d1 and len(out) < 370:
        out.append(d0)
        d0 += timedelta(days=1)
    return out


def _weekdays(m: re.Match) -> set[int]:
    a = WEEKDAYS.index(m.group("w0"))
    b = WEEKDAYS.index(m.group("w1")) if m.group("w1") else a
    return {(a + i) % 7 for i in range((b - a) % 7 + 1)}


def _schedule(d: str, start: datetime, end: datetime) -> tuple[list[tuple[datetime, datetime, bool]], str]:
    """(windows as (start, end, every_day), mode). every_day: the window came from a time with no days of its own,
    so it is clipped to B) to C) (an overnight 2200-1000 runs from the evening before B) to the morning after C)).
    Raises _Unread for anything not read in full."""
    year, month = start.year, start.month
    day0 = start.replace(hour=0, minute=0, second=0, microsecond=0)
    every = _days(day0 - timedelta(days=1), end.replace(hour=0, minute=0, second=0, microsecond=0))
    pending: list[datetime] = []
    pending_every = False                     # pending holds every day (DLY, or week days), not listed dates
    last: tuple[list[datetime], bool] | None = None
    last_day = None
    month_named = listed = excluding = after_time = any_month = False
    excluded_days: set = set()
    excluded_wdays: set = set()
    out = []
    for m in TOKEN.finditer(d.upper()):
        kind = m.lastgroup
        if kind in ("sep", "skip"):
            continue
        if kind == "other":
            raise _Unread(m.group(0))
        if kind == "exc":
            excluding = True
            continue
        if kind == "mon":
            mo = MONTHS.index(m.group(0)) + 1
            month = mo + (12 if mo < start.month - 6 else 0)
            last_day, month_named, any_month = None, True, True
            continue
        if kind == "daily":
            if excluding:
                raise _Unread(m.group(0))
            if after_time and not pending and last and last[1]:
                continue                                # 1100-2300 DLY: the time was already every day
            pending, pending_every = list(every), True
            continue
        if kind == "dtp":
            if excluding or pending:
                raise _Unread(m.group(0))
            s, e = (datetime.strptime(m.group(g), "%y%m%d%H%M").replace(tzinfo=timezone.utc) for g in ("t0", "t1"))
            if e <= s:
                raise _Unread(m.group(0))
            out.append((s, e, False))
            listed, after_time = True, True
            continue
        if kind == "wday":
            if excluding:
                excluded_wdays |= _weekdays(m)
            else:
                wd = _weekdays(m)
                pending, pending_every = [x for x in every if x.weekday() in wd], True
            continue
        if kind in ("day", "range"):
            d0 = int(m.group("d0") if kind == "range" else m.group(0))
            d1 = int(m.group("d1")) if kind == "range" else d0
            if after_time and not month_named and not any_month:  # a new group after a time: from B) again
                month = start.month
                if _date(year, month, d0) < day0:
                    month += 1
            elif last_day is not None and d0 < last_day and not month_named:
                month += 1                              # 29, 30, 01: the next month
            month_named = after_time = False
            a = _date(year, month, d0)
            if d1 < d0:                                 # 30-02: across a month end
                month += 1
            got = _days(a, _date(year, month, d1))
            last_day = d1
            if excluding:
                excluded_days |= set(got)
            else:
                if pending_every:
                    pending, pending_every = [], False
                pending += got
                listed = True
            continue
        # a time: for the days just named, else the days of the time before it, else every day from B) to C)
        if excluding:
            raise _Unread("a time after EXC")
        if kind == "h24":
            h0, m0, h1, m1 = 0, 0, 24, 0
        else:
            h0, m0, h1, m1 = (int(m.group(g)) for g in ("h0", "m0", "h1", "m1"))
        if not (0 <= h0 <= 23 and 0 <= m0 <= 59 and (0 <= h1 <= 23 and 0 <= m1 <= 59 or (h1, m1) == (24, 0))):
            raise _Unread(m.group(0))
        if pending:
            days, ev = pending, pending_every
        elif last:
            days, ev = last
        else:
            days, ev = list(every), True
        last, pending, pending_every, after_time = (days, ev), [], False, True
        for day in days:
            s = day + timedelta(hours=h0, minutes=m0)
            e = day + timedelta(hours=h1, minutes=m1)
            if e <= s:
                e += timedelta(days=1)
            out.append((s, e, ev))
        if len(out) > MAX_WINDOWS:
            raise _Unread("too many windows")
    if pending or not out or excluding and not (excluded_days or excluded_wdays):
        raise _Unread("days with no time")
    out = [w for w in out if w[0].replace(hour=0, minute=0) not in excluded_days
           and w[0].weekday() not in excluded_wdays]
    return out, "schedule" if listed else "daily"


def windows(start: str | None, end: str | None, schedule: str | None) -> tuple[list[dict], str]:
    """(windows, window_mode). window_mode: "single" (no D): the one window B) to C); "schedule" (days and times
    read from D) or "daily" (times only, every day or the named week days from B) to C)); "span": D) given but not
    read in full, so the one window B) to C); "" when B) or C) is missing or permanent (no window). A window from
    named days that falls outside B) to C) means the schedule was misread: "span"."""
    a, b = _dt(start), _dt(end)
    if not a or not b or b < a:
        return [], ""
    d = (schedule or "").strip()
    if not d:
        return [{"start": _iso(a), "end": _iso(b)}], "single"
    try:
        got, mode = _schedule(d, a, b)
    except _Unread:
        return [{"start": _iso(a), "end": _iso(b)}], "span"
    slack = timedelta(minutes=1)
    kept = []
    for s, e, ev in got:
        if ev:                                          # every day: clipped to B) to C)
            s, e = max(s, a), min(e, b)
            if e > s:
                kept.append((s, e))
        elif s < a - slack or e > b + slack:
            return [{"start": _iso(a), "end": _iso(b)}], "span"
        else:
            kept.append((max(s, a), min(e, b)))
    if not kept:
        return [{"start": _iso(a), "end": _iso(b)}], "span"
    got = kept
    seen, out = set(), []
    for s, e in sorted(got):
        k = (_iso(s), _iso(e))
        if k not in seen:
            seen.add(k)
            out.append({"start": k[0], "end": k[1]})
    return out, mode


# ---------- the shape in the E) text ----------

COORD = re.compile(r"(?<![\d.])(\d{2})(\d{2})(\d{2}(?:\.\d+)?)?\s?([NS])\s*[,/]?\s*"
                   r"(\d{3})(\d{2})(\d{2}(?:\.\d+)?)?\s?([EW])(?![A-Z])")
JOIN = re.compile(r"^[\s,;\-–/.]*(?:(?:TO|THEN|AND)\b[\s,;\-–/.]*)?$")
LINE_WORDS = re.compile(r"\b(?:LINE|ROUTE|TRACK|TRACKLINE|ALONG|AXIS|CORRIDOR|EITHER SIDE|SEGMENT)\b")
DIST = r"(\d+(?:\.\d+)?)\s*(NM|KM|M)\b"
POS = r"(" + COORD.pattern + r")"
CIRCLES = [
    # RADIUS 300M CENTER 351020N1365524E; RADIUS OF 5NM CENTRED ON ...
    (re.compile(r"\bRADIUS\s*(?:OF\s*)?" + DIST + r"[\s,]*(?:CENT(?:ER|RE)(?:D)?|CENTRED|CENTERED)\s*(?:ON|AT)?\s*:?\s*"
                + POS), 1, 2, 3),
    # WI 1.5NM RADIUS OF 532210N 0024107W
    (re.compile(DIST + r"\s*RADIUS\s*(?:OF|CENT(?:ER|RE)D?\s*(?:ON|AT)?)\s*:?\s*" + POS), 1, 2, 3),
    # CENTRE 351020N1365524E RADIUS 300M
    (re.compile(r"\bCENT(?:ER|RE)(?:D)?\s*(?:ON|AT)?\s*:?\s*" + POS + r"[\s,]*(?:WITH\s*)?(?:A\s*)?RADIUS\s*(?:OF\s*)?"
                + DIST), 10, 11, 1),
]
EXCLUDED = re.compile(r"\bEXC(?:EPT|LUDING)?\b[^\n]{0,20}$")


def _coord(m: re.Match, base: int = 0) -> list[float] | None:
    """[lon, lat] from a COORD match (its eight groups after group `base`; 0 for COORD itself, or the group number of
    the position inside a CIRCLES pattern), or None when it is not a position."""
    g = [m.group(base + i) for i in range(1, 9)]
    la_d, la_m, la_s, ns, lo_d, lo_m, lo_s, ew = g
    if int(la_m) > 59 or int(lo_m) > 59 or (la_s and float(la_s) >= 60) or (lo_s and float(lo_s) >= 60):
        return None
    lat = int(la_d) + int(la_m) / 60 + (float(la_s) / 3600 if la_s else 0)
    lon = int(lo_d) + int(lo_m) / 60 + (float(lo_s) / 3600 if lo_s else 0)
    if lat > 90 or lon > 180:
        return None
    return [round(-lon if ew == "W" else lon, 5), round(-lat if ns == "S" else lat, 5)]


def _unwrap(ring: list[list[float]]) -> list[list[float]]:
    """Longitudes kept continuous along a ring, so a shape across 180 degrees stays one shape."""
    out = []
    for lon, lat in ring:
        if out:
            while lon - out[-1][0] > 180:
                lon -= 360
            while out[-1][0] - lon > 180:
                lon += 360
        out.append([lon, lat])
    return out


def circle(lon: float, lat: float, radius_m: float, sides: int = CIRCLE_SIDES) -> list[list[float]]:
    """A closed ring of `sides` points at radius_m around (lon, lat), on a sphere."""
    la, lo, d = math.radians(lat), math.radians(lon), radius_m / EARTH_M
    ring = []
    for i in range(sides):
        b = 2 * math.pi * i / sides
        la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(b))
        lo2 = lo + math.atan2(math.sin(b) * math.sin(d) * math.cos(la), math.cos(d) - math.sin(la) * math.sin(la2))
        ring.append([round(math.degrees(lo2), 5), round(math.degrees(la2), 5)])
    ring = _unwrap(ring)
    return ring + [list(ring[0])]


def _metres(v: str, unit: str) -> float:
    return float(v) * {"NM": NM_M, "KM": 1000.0, "M": 1.0}[unit]


def shape(text: str | None) -> list[dict]:
    """The shapes the E) text draws: [{kind: polygon|circle, ring, radius_m?}], in the order written."""
    t = (text or "").upper()
    out = []
    used = []
    for pat, dist_g, unit_g, pos_g in CIRCLES:  # group numbers: the distance, its unit, the position
        for m in pat.finditer(t):
            if any(a <= m.start() < b for a, b in used):
                continue
            if EXCLUDED.search(t[max(0, m.start() - 40):m.start()]):
                continue
            pos = _coord(m, pos_g)
            if not pos:
                continue
            r = _metres(m.group(dist_g), m.group(unit_g))
            if not 0 < r <= 2000 * NM_M:
                continue
            used.append((m.start(), m.end()))
            out.append((m.start(), {"kind": "circle", "ring": circle(pos[0], pos[1], r), "radius_m": round(r)}))
    runs, run, prev_end = [], [], None
    for m in COORD.finditer(t):
        if any(a <= m.start() < b for a, b in used):     # a circle's centre is not a vertex
            if run:
                runs.append(run)
            run, prev_end = [], None
            continue
        p = _coord(m)
        if not p:
            continue
        if run and not JOIN.match(t[prev_end:m.start()]):
            runs.append(run)
            run = []
        run.append((m.start(), p))
        prev_end = m.end()
    if run:
        runs.append(run)
    for r in runs:
        pts = [p for _, p in r]
        uniq = [p for i, p in enumerate(pts) if p not in pts[:i]]
        if len(uniq) < 3:
            continue
        line_start = t.rfind("\n", 0, r[0][0]) + 1
        if LINE_WORDS.search(t[max(line_start - 80, 0):r[0][0]]):
            continue                                     # a line or a route, not an area
        ring = _unwrap(uniq)
        out.append((r[0][0], {"kind": "polygon", "ring": ring + [list(ring[0])]}))
    return [s for _, s in sorted(out, key=lambda x: x[0])]


# ---------- the footprint ----------

def _is_q_circle(ring: list, q: dict | None) -> bool:
    """Whether NMS's polygon is the Q) line circle (every vertex at the Q) radius from its centre, within 10%)."""
    if not q or not q.get("radius_nm") or len(ring) < 16:
        return False
    r = q["radius_nm"] * NM_M
    return all(abs(_dist(q["lon"], q["lat"], p[0], p[1]) - r) <= max(0.1 * r, 500) for p in ring)


def _dist(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_M * math.asin(math.sqrt(min(1.0, a)))


def _polys(rings: list) -> dict:
    return ({"type": "Polygon", "coordinates": [rings[0]]} if len(rings) == 1
            else {"type": "MultiPolygon", "coordinates": [[r] for r in rings]})


def _agrees(rings: list, q: dict | None, international: bool) -> bool:
    """Whether NMS's polygons sit where the Q) line puts the NOTAM: each ring's centre within 1.25 times the Q) radius
    (at least 5 NM) plus 5 km of the Q) centre. For NOTAMs issued outside the United States NMS's polygon is often
    elsewhere (a circle round the A) aerodrome, or a shape far from the area the text gives), so such a polygon is
    used only when it agrees; with no Q) radius to test against, only a US NOTAM's polygon is used."""
    if not q or not q.get("radius_nm") or q["radius_nm"] >= 999:
        return not international
    lim = max(q["radius_nm"], 5) * NM_M * 1.25 + 5000
    for r in rings:
        pts = r[:-1] if len(r) > 1 and r[0] == r[-1] else r
        lon, lat = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        if _dist(q["lon"], q["lat"], lon, lat) > lim:
            return False
    return True


def geometry(f: dict, icao: str | None = None) -> tuple[dict | None, str, str]:
    """(geometry, basis, precision_class) for one NMS feature, in this order: "text" (the shape the E) text draws,
    in the NOTAM's own words), "nms" (NMS's own polygon, when it is not just the Q) line circle and agrees with the
    Q) line), "q-line circle" (the Q) line's centre and radius: an envelope), "q-line point" (the Q) line centre;
    radius 999, the whole FIR, or none), "nms point", or "none"."""
    q = qline(icao)
    notam = ((f.get("properties") or {}).get("coreNOTAMData") or {}).get("notam") or {}
    international = notam.get("classification") == "INTL"
    g0 = f.get("geometry") or {}
    parts = g0.get("geometries") if g0.get("type") == "GeometryCollection" else [g0] if g0 else []
    drawn = shape(e_text(icao))
    if drawn:
        return _polys([s["ring"] for s in drawn]), "text", "area"
    nms_rings = []
    for g in parts or []:
        if (g or {}).get("type") == "Polygon" and g["coordinates"] and len(g["coordinates"][0]) >= 4:
            nms_rings.append(g["coordinates"][0])
        elif (g or {}).get("type") == "MultiPolygon":
            nms_rings += [p[0] for p in g["coordinates"] if p and len(p[0]) >= 4]
    own = [_unwrap([list(p[:2]) for p in r]) for r in nms_rings if not _is_q_circle(r, q)]
    if own and _agrees(own, q, international):
        return _polys(own), "nms", "area"
    if q and q.get("radius_nm") and q["radius_nm"] < 999:
        return ({"type": "Polygon", "coordinates": [circle(q["lon"], q["lat"], max(q["radius_nm"], 1) * NM_M)]},
                "q-line circle", "approximate")
    if q:
        return {"type": "Point", "coordinates": [q["lon"], q["lat"]]}, "q-line point", "approximate"
    for g in parts or []:
        if (g or {}).get("type") == "Point":
            return {"type": "Point", "coordinates": list(g["coordinates"][:2])}, "nms point", "approximate"
    return None, "none", "none"
