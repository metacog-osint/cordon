"""FAA temporary flight restrictions (TFRs): space operations, security, hazards, VIP movements and others, with shapes.

Source: the FAA's TFR site, checked live 14 Nov 2026. No key, no sign-in, no robots.txt (HTTP 404).
- The list, https://tfr.faa.gov/tfrapi/exportTfrList (JSON): one row per TFR with notam_id, type ("SPACE OPERATIONS",
  "SECURITY", "HAZARDS", "VIP" ...), facility, state, a one-line description and a creation date. 52 rows on 14 Nov.
- One detail file per TFR, https://tfr.faa.gov/download/detail_<n>_<nnnn>.xml (the FAA's XNOTAM format): the NOTAM
  text, issue, effective and expiry times, floor and ceiling, and each area's outline. `abdMergedArea` is the FAA's
  own outline with circles already turned into rings, so Cordon draws it as given; an area with no outline but a
  circle (`Avx` codeType CIR, radius in NM) is drawn as a 32-sided ring.
Times: `dateEffective` / `dateExpire` are UTC. On 14 Nov they matched the UTC range that ends each NOTAM's text
(6/7131: 2026-11-14T20:53 = "2611142053") although `codeTimeZone` said CST, the zone the FAA's page displays; a
survey by another session found the same in all 46 TFRs whose text states times.

Not listed in the feed: TFRs with no area (the standing nationwide notices: special security instructions, the DC
area, drones near critical infrastructure; 13 on 14 Nov). They are kept in data and counted in the health block.
The statutory TFRs over stadiums and Disney parks (Public Law 108-7, section 352) are listed but never count as new.

A detail file is read once per NOTAM (the FAA cancels a changed TFR and reissues it under a new number); MAX_DETAILS
caps one run and a failed detail is asked for again next run. Terms: the FAA states none on the TFR site; it is a work
of the US Government, not subject to US copyright (17 U.S.C. 105). That is Cordon's reading, not an FAA statement.
"""
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from . import airports
from .common import fetch_or_none, now_utc, to_utc
from .navarea import circle, unwrap

LIST_URL = "https://tfr.faa.gov/tfrapi/exportTfrList"
DETAIL_URL = "https://tfr.faa.gov/download/detail_{id}.xml"
PAGE_URL = "https://tfr.faa.gov/tfr3/?page=detail_{id}"
SITE_URL = "https://tfr.faa.gov/"
MAX_DETAILS = 80
PAUSE_S = 0.2  # between detail fetches, to be gentle with the FAA's server
TEXT_MAX = 6000  # characters of TFR text SHOWN in the feed; data/tfr.json keeps the whole text (C4, 18 Nov 2026)
STALE_HOURS = 6  # launch and VIP TFRs last hours; with no good list for this long the held set is withheld
NEW_HOURS = 72
# A TFR of these types issued within NEW_HOURS is an anomaly (as for NGA's launch, military and security warnings).
NEW_ALERT = {"SPACE OPERATIONS", "SECURITY", "SPECIAL"}
# Types left out of the feed (kept in data and counted as skipped in health), each with the TIC program that
# publishes it instead. SPACE OPERATIONS TFRs are Launch's (launch.theintelligence.company), which tiers a new one
# anomaly by the same 72-hour rule; COP drew each twice while both carried them (Tom, 14 Nov 2026). Empty this to
# bring them back.
SKIP_TYPES: dict[str, str] = {"SPACE OPERATIONS": "Launch"}
# The list's state field for US territories with their own ISO code; every other TFR is the US's. (The world outlines
# are thinned to about 5 km, so a TFR at Brownsville or Starbase would otherwise also be tagged Mexico.)
TERRITORIES = {"PR": "PR", "GU": "GU", "VI": "VI", "AS": "AS", "MP": "MP"}
STATUTORY_RE = re.compile(r"SECTION 352 OF PUBLIC LAW 108-7", re.I)
NOTAM_RE = re.compile(r"^\d{1,2}/\d{1,5}$")
COORD_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([NSEW])\s*$")
NM = 1852.0


def display_text(text: str) -> str:
    """The text as the feed shows it: cut at TEXT_MAX with a note saying so. Stored text is whole; text an earlier
    version of Cordon already cut (it carries the note) is left as it is."""
    if len(text) <= TEXT_MAX or "[Cut by Cordon" in text:
        return text
    return text[:TEXT_MAX] + f" [Cut by Cordon: {len(text) - TEXT_MAX} more characters in the FAA's text]"


def file_id(notam_id: str) -> str:
    """'6/7131' -> '6_7131', as the FAA names the detail file and page."""
    return notam_id.strip().replace("/", "_")


def coord(text: str) -> float | None:
    m = COORD_RE.match(text or "")
    if not m:
        return None
    v = float(m.group(1))
    return -v if m.group(2) in "SW" else v


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first(root, tag):
    for e in root.iter():
        if _local(e.tag) == tag:
            return (e.text or "").strip()
    return ""


def _all(root, tag):
    return [e for e in root.iter() if _local(e.tag) == tag]


def _height(val: str, uom: str, code: str) -> str | None:
    """The FAA's floor or ceiling in words: surface, FL180, FL999, 5000 ft MSL / AGL."""
    if not val:
        return None
    if uom == "FL":
        return f"FL{val}"
    if val in ("0", "0.0"):  # the FAA writes SFC as 0 ft, with HEI or ALT
        return "surface"
    return f"{val} {uom.lower() or 'ft'} {'AGL' if code == 'HEI' else 'MSL'}"


def _point(avx):
    lat, lon = coord(_first(avx, "geoLat")), coord(_first(avx, "geoLong"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return [round(lon, 5), round(lat, 5)]


def _rings(group) -> list[list[list[float]]]:
    """One closed ring per area in a TFRAreaGroup: the merged outline, or a circle stated by centre and radius."""
    out = []
    for area in _all(group, "abdMergedArea"):
        ring = [p for p in (_point(a) for a in area if _local(a.tag) == "Avx") if p]
        if len(ring) >= 3:
            out.append(ring)
    if not out:
        for avx in _all(group, "Avx"):
            if _first(avx, "codeType").upper() != "CIR":
                continue
            c = _point(avx)
            try:
                r = float(_first(avx, "valRadiusArc")) * {"NM": NM, "SM": 1609.344, "KM": 1000.0}.get(
                    _first(avx, "uomRadiusArc").upper() or "NM", 1.0)
            except ValueError:
                r = 0
            if c and r > 0:
                out.append(circle(c, r))
                break
    rings = []
    for ring in out:
        if any(abs(p[0]) > 170 for p in ring):  # only near the date line: unwrap rounds to 3 decimals (about 100 m)
            ring = unwrap(ring)
        rings.append(ring if ring[0] == ring[-1] else ring + [ring[0]])
    return [r for r in rings if len(r) >= 4]


def parse_detail(body: bytes) -> dict:
    """The fields Cordon keeps from one detail XML."""
    root = ET.fromstring(body)
    groups = _all(root, "TFRAreaGroup") or [root]
    rings = [r for g in groups for r in _rings(g)]
    geom = ({"type": "Polygon", "coordinates": [rings[0]]} if len(rings) == 1
            else {"type": "MultiPolygon", "coordinates": [[r] for r in rings]} if rings else None)
    area = (_all(root, "aseTFRArea") or [None])[0]
    floor = ceiling = None
    if area is not None:
        floor = _height(_first(area, "valDistVerLower"), _first(area, "uomDistVerLower"), _first(area, "codeDistVerLower"))
        ceiling = _height(_first(area, "valDistVerUpper"), _first(area, "uomDistVerUpper"), _first(area, "codeDistVerUpper"))
    text = re.sub(r"\s+", " ", _first(root, "txtDescrUSNS"))
    statutory = bool(STATUTORY_RE.search(text))
    tfr = next((e for e in root.iter() if _local(e.tag) == "TfrNot"), None)
    regulation = next((((c.text or "").strip()) for c in (tfr if tfr is not None else []) if _local(c.tag) == "codeType"), "")
    return {"name": _first(root, "txtLocalName"), "issued": to_utc(_first(root, "dateIssued")),
            "effective": to_utc(_first(root, "dateEffective")), "expires": to_utc(_first(root, "dateExpire")),
            "regulation": regulation or None, "purpose": _first(root, "txtDescrPurpose") or None,
            "city": _first(root, "txtNameCity") or None, "floor": floor, "ceiling": ceiling,
            "statutory": statutory, "text": text, "geometry": geom}


def parse_list(rows) -> dict:
    """{notam_id: {notam_id, type, facility, state, description, created}} from the list JSON."""
    if not isinstance(rows, list):
        raise ValueError("TFR list is not a list")
    out = {}
    for r in rows:
        nid = str((r or {}).get("notam_id") or "").strip()
        if not NOTAM_RE.match(nid):
            continue
        out[nid] = {"notam_id": nid, "type": str(r.get("type") or "").strip().upper(),
                    "facility": (r.get("facility") or "").strip() or None, "state": (r.get("state") or "").strip() or None,
                    "description": re.sub(r"\s+", " ", str(r.get("description") or "")).strip()[:300],
                    "created": (r.get("creation_date") or "").strip() or None}
    return out


def health_detail(tfrs: dict, read: int, failed: int) -> str:
    """The faa-tfr health line: how many TFRs the FAA lists, how many have an area, how many are left to another
    program (SKIP_TYPES; counted whether or not they are still in force, as the feed's skipped count is), and how
    many detail files this run read."""
    shapes = sum(1 for r in tfrs.values() if (r.get("detail") or {}).get("geometry"))
    out = f"{len(tfrs)} TFRs listed, {shapes} with an area"
    for kind, program in sorted(SKIP_TYPES.items()):
        n = sum(1 for r in tfrs.values() if r.get("type") == kind)
        if n:
            out += f"; {n} {kind.lower()} {'TFR' if n == 1 else 'TFRs'} left to {program}"
    return out + f"; {read} detail files read" + (f", {failed} failed" if failed else "")


def collect(old: dict | None, when: str | None = None, fetch=fetch_or_none, pause: float = PAUSE_S):
    """(tfrs, error, details_read, details_failed). On error the caller keeps the old set."""
    when = when or now_utc()
    old = old or {}
    body, err = fetch(LIST_URL, 30)
    if body is None:
        return old, err, 0, 0
    try:
        listed = parse_list(json.loads(body.decode("utf-8-sig")))
    except (ValueError, UnicodeDecodeError) as e:
        return old, f"unreadable: {type(e).__name__}", 0, 0
    if not listed:
        return old, "the list was empty", 0, 0
    read = failed = 0
    out = {}
    for nid, rec in listed.items():
        prev = old.get(nid) or {}
        # first read of this field (15 Nov 2026): a TFR already held keeps the FAA's issue time as its first sighting
        rec["first_seen"] = prev.get("first_seen") or (prev.get("detail") or {}).get("issued") or when
        if prev.get("subject"):
            rec["subject"] = prev["subject"]  # stamped once by remember(), never changed (feed revision 2.1)
        if prev.get("detail") and prev.get("created") == rec["created"]:
            out[nid] = {**rec, "detail": prev["detail"]}
            continue
        rec["detail"] = None
        if read + failed < MAX_DETAILS:
            if pause and (read or failed):
                time.sleep(pause)
            page, perr = fetch(DETAIL_URL.format(id=file_id(nid)), 30)
            try:
                if page is None:
                    raise ValueError(perr)
                rec["detail"] = parse_detail(page)
                read += 1
            except (ValueError, ET.ParseError):
                failed += 1
        out[nid] = rec
    return dict(sorted(out.items())), None, read, failed


# Impact (Tom, 15 Nov 2026: alerts should weigh what a restriction does, so a small volcano or range TFR far from
# busy airspace is not flagged like one over a hub). Measured on the 43 shaped TFRs held 15 Nov (space operations
# left out): hazards 11-1,066 km2 up to 11,000 ft; most security TFRs 11-700 km2; DC's SFRA 11,571 km2; the VIP TFR
# at Anchorage 10,646 km2 to 17,999 ft. FL180 is the floor of Class A (jet routes); 56 km (30 nm) is about the
# outer edge of a Class B airport's arrival and departure airspace.
NEAR_CORE_KM = 56.0
NEAR_CORE_CEILING_FT = 3000
CLASS_A_FT = 18000
WIDE_KM2 = 2500.0
SIZEABLE_KM2 = 500.0
MODERATE_KM2 = 250.0
# Reaching Class A counts only over CLASS_A_MIN_KM2 or more (Tom, 16 Nov 2026 UTC): a 29 km2 surface-to-unlimited
# munitions test off Santa Rosa Island (6/7507) is a point that jet traffic steps around, not a moderate impact.
# 100 km2 is about a 5.6 km radius, the size of a VIP TFR's 3 nm inner ring.
CLASS_A_MIN_KM2 = 100.0
# A VIP TFR is listed but routine unless its impact is high (a presidential visit's 30 nm ring is).
IMPACT_ALERT = {"VIP"}
# Re-issues (item 4 of Tom's list, 15 Nov 2026): the FAA cancels a changed TFR and issues it under a new number,
# and long-running ranges are renewed. A new TFR is a re-issue when one of the same type, whose bounding box
# overlaps its own by REISSUE_IOU, was held before it, now or within GONE_DAYS; it counts as new only if it is
# larger (area over ENLARGED_BY times the earlier one, or a higher ceiling).
GONE_DAYS = 14
REISSUE_IOU = 0.5
ENLARGED_BY = 1.25


def feet(height: str | None) -> int | None:
    """Feet from the words _height writes: "surface" 0, "FL180" 18000, "5000 ft MSL" 5000; None if unreadable."""
    if not height:
        return None
    if height == "surface":
        return 0
    m = re.match(r"FL(\d+)$", height)
    if m:
        return int(m.group(1)) * 100
    m = re.match(r"(\d+(?:\.\d+)?) ft\b", height)
    return int(float(m.group(1))) if m else None


def _polys(geom: dict | None) -> list:
    if not geom:
        return []
    return [geom["coordinates"]] if geom["type"] == "Polygon" else list(geom["coordinates"])


def area_km2(geom: dict | None) -> float:
    """Area of a TFR's outer rings in km2 (equirectangular about each ring's mean latitude; fine at TFR sizes)."""
    total = 0.0
    for poly in _polys(geom):
        ring = poly[0]
        lat0 = sum(p[1] for p in ring) / len(ring)
        kx, ky = 111.32 * math.cos(math.radians(lat0)), 110.57
        a = sum((x1 * kx) * (y2 * ky) - (x2 * kx) * (y1 * ky) for (x1, y1), (x2, y2) in zip(ring, ring[1:]))
        total += abs(a) / 2
    return round(total, 1)


def bbox(geom: dict | None) -> list[float] | None:
    pts = [p for poly in _polys(geom) for p in poly[0]]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]


def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def impact(rec: dict) -> dict:
    """What a TFR restricts, as measures, and a level: high, moderate or low.

    high: within NEAR_CORE_KM of a Core 30 airport with a ceiling of NEAR_CORE_CEILING_FT or more; or WIDE_KM2 or
          more; or reaching Class A (FL180) over SIZEABLE_KM2 or more.
    moderate: any one of reaching Class A over CLASS_A_MIN_KM2 or more, MODERATE_KM2 or more, or within NEAR_CORE_KM
          of a Core 30 airport.
    low: the rest (small, low and away from the busiest airports, such as most volcano, fire and range TFRs)."""
    d = rec.get("detail") or {}
    g = d.get("geometry")
    area = area_km2(g)
    ceiling, floor = feet(d.get("ceiling")), feet(d.get("floor"))
    pts = [(p[1], p[0]) for poly in _polys(g) for p in poly[0]]
    near = airports.nearest_core30(pts)
    hours = None
    if d.get("effective") and d.get("expires"):
        hours = round((datetime.fromisoformat(d["expires"].replace("Z", "+00:00"))
                       - datetime.fromisoformat(d["effective"].replace("Z", "+00:00"))).total_seconds() / 3600, 1)
    close = bool(near and near[1] <= NEAR_CORE_KM)
    class_a = ceiling is not None and ceiling >= CLASS_A_FT and area >= CLASS_A_MIN_KM2
    why = []
    if close and (ceiling is None or ceiling >= NEAR_CORE_CEILING_FT):
        why.append(f"within {int(NEAR_CORE_KM)} km of {near[0]} (Core 30)")
    if area >= WIDE_KM2:
        why.append(f"{area:,.0f} km2")
    if class_a and area >= SIZEABLE_KM2:
        why.append(f"reaches FL{CLASS_A_FT // 100} over {area:,.0f} km2")
    if why:
        level = "high"
    elif class_a or area >= MODERATE_KM2 or close:
        level = "moderate"
        why = [w for w, on in ((f"reaches FL{CLASS_A_FT // 100} over {area:,.0f} km2", class_a), (f"{area:,.0f} km2", area >= MODERATE_KM2),
                               (f"within {int(NEAR_CORE_KM)} km of {near[0] if near else ''} (Core 30)", close)) if on]
    else:
        level = "low"
    out = {"area_km2": area, "ceiling_ft": ceiling, "floor_ft": floor, "hours": hours, "impact": level,
           "impact_basis": why}
    if near:
        out["nearest_core30"] = {"airport": near[0], "km": near[1]}
    return out


def memory_entry(rec: dict, first_seen: str) -> dict:
    """What Cordon keeps of a TFR to recognise its re-issue later, and the subject it carried (feed revision 2.1)."""
    d = rec.get("detail") or {}
    out = {"type": rec.get("type"), "state": rec.get("state"), "bbox": bbox(d.get("geometry")),
           "area_km2": area_km2(d.get("geometry")), "ceiling_ft": feet(d.get("ceiling")), "first_seen": first_seen}
    if rec.get("subject"):
        out["subject"] = rec["subject"]
    return out


def subject_of(nid: str, rec: dict, held: dict, gone: dict, taken: set | None = None) -> str:
    """The restriction a TFR is a reading of (feed revision 2.1 subject_id; the NOTAM id it started under), so that a
    re-issue reads as a change of one restriction and not a new one and an end.

    Stamped once (rec["subject"], kept in data/tfr.json by remember()) and never changed after. Until then: a re-issue
    whose predecessor has left the FAA's list takes the predecessor's subject, unless a TFR still listed already
    carries it (the first re-issue of a split takes it). A re-issue listed alongside its predecessor keeps its own
    subject: two restrictions in force at once are two subjects, and sharing one would cost the history log a false
    new and end. A TFR with no area yet (detail not read) keeps its own."""
    if rec.get("subject"):
        return rec["subject"]
    again = reissue(nid, rec, held, gone)
    if not again or again["of"] in held or again["of"] not in (gone or {}):
        return nid
    s = gone[again["of"]].get("subject") or again["of"]
    if taken is None:
        taken = {r.get("subject") or k for k, r in held.items() if k != nid}
    return nid if s in taken else s


def stamp_subjects(new: dict, gone: dict) -> None:
    """Give every listed TFR not yet stamped its subject, oldest first, so the first re-issue of a split takes the
    predecessor's subject and later ones keep their own."""
    taken = {r["subject"] for r in new.values() if r.get("subject")}
    for nid in sorted((k for k, r in new.items() if not r.get("subject")),
                      key=lambda k: (new[k].get("first_seen") or "", k)):
        s = subject_of(nid, new[nid], new, gone, taken)
        new[nid]["subject"] = s
        taken.add(s)


def subjects(held: dict, gone: dict) -> dict:
    """{nid: subject} for the listed TFRs: their stamps, and for any not yet stamped (a data file from before revision
    2.1) what stamp_subjects() would give them, without changing the data."""
    copy = {k: dict(r) for k, r in (held or {}).items()}
    stamp_subjects(copy, gone or {})
    return {k: r["subject"] for k, r in copy.items()}


def remember(old: dict, new: dict, gone: dict | None, when: str) -> dict:
    """The TFRs that left the FAA's list in the last GONE_DAYS, for re-issue checks: the earlier memory, pruned, plus
    any TFR held before this read and not listed now. Also stamps each listed TFR's subject (stamp_subjects), against
    the memory including this read's departures, so a TFR re-issued in the hour its predecessor left counts too."""
    cutoff = (datetime.fromisoformat(when.replace("Z", "+00:00")) - timedelta(days=GONE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {k: v for k, v in (gone or {}).items() if (v.get("left_at") or "") >= cutoff and k not in new}
    for nid, rec in (old or {}).items():
        if nid not in new and (rec.get("detail") or {}).get("geometry"):
            out[nid] = {**memory_entry(rec, rec.get("first_seen") or ""), "left_at": when}
    stamp_subjects(new, out)
    return dict(sorted(out.items()))


def reissue(nid: str, rec: dict, held: dict, gone: dict) -> dict | None:
    """{of, enlarged} when this TFR repeats one Cordon held before it (see GONE_DAYS), else None."""
    me = memory_entry(rec, rec.get("first_seen") or "")
    if not me["bbox"]:
        return None
    mine = me["first_seen"] or "9999"
    others = [(k, memory_entry(r, r.get("first_seen") or "")) for k, r in held.items() if k != nid]
    others += list((gone or {}).items())
    best = None
    for k, o in others:
        if o.get("type") != me["type"] or not o.get("bbox") or (o.get("first_seen") or "") >= mine:
            continue
        if _iou(o["bbox"], me["bbox"]) >= REISSUE_IOU and (best is None or (o.get("first_seen") or "") > best[1]["first_seen"]):
            best = (k, o)
    if not best:
        return None
    o = best[1]
    bigger = (me["area_km2"] > ENLARGED_BY * (o.get("area_km2") or 0)
              or (me["ceiling_ft"] or 0) > (o.get("ceiling_ft") or 0))
    return {"of": best[0], "enlarged": bigger}


def in_force(rec: dict, stamp: str) -> bool:
    """Not past its expiry (a TFR with no expiry, or no detail yet, stays listed while the FAA lists it)."""
    exp = (rec.get("detail") or {}).get("expires")
    return not exp or exp >= stamp
