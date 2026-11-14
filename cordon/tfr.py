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
import re
import time
import xml.etree.ElementTree as ET

from .common import fetch_or_none, now_utc, to_utc
from .navarea import circle, unwrap

LIST_URL = "https://tfr.faa.gov/tfrapi/exportTfrList"
DETAIL_URL = "https://tfr.faa.gov/download/detail_{id}.xml"
PAGE_URL = "https://tfr.faa.gov/tfr3/?page=detail_{id}"
SITE_URL = "https://tfr.faa.gov/"
MAX_DETAILS = 80
PAUSE_S = 0.2  # between detail fetches, to be gentle with the FAA's server
TEXT_MAX = 6000
STALE_HOURS = 6  # launch and VIP TFRs last hours; with no good list for this long the held set is withheld
NEW_HOURS = 72
# A TFR of these types issued within NEW_HOURS is an anomaly (as for NGA's launch, military and security warnings).
NEW_ALERT = {"SPACE OPERATIONS", "SECURITY", "SPECIAL"}
# Types left out of the feed (kept in data). Empty for now; "SPACE OPERATIONS" would leave them to Launch.
SKIP_TYPES: set[str] = set()
# The list's state field for US territories with their own ISO code; every other TFR is the US's. (The world outlines
# are thinned to about 5 km, so a TFR at Brownsville or Starbase would otherwise also be tagged Mexico.)
TERRITORIES = {"PR": "PR", "GU": "GU", "VI": "VI", "AS": "AS", "MP": "MP"}
STATUTORY_RE = re.compile(r"SECTION 352 OF PUBLIC LAW 108-7", re.I)
NOTAM_RE = re.compile(r"^\d{1,2}/\d{1,5}$")
COORD_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([NSEW])\s*$")
NM = 1852.0


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
    if len(text) > TEXT_MAX:
        text = text[:TEXT_MAX] + f" [Cut by Cordon: {len(text) - TEXT_MAX} more characters in the FAA's text]"
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


def in_force(rec: dict, stamp: str) -> bool:
    """Not past its expiry (a TFR with no expiry, or no detail yet, stays listed while the FAA lists it)."""
    exp = (rec.get("detail") or {}).get("expires")
    return not exp or exp >= stamp
