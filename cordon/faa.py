"""FAA National Airspace System status: ground stops, ground delay programs and airport closures.

Source: the JSON behind https://nasstatus.faa.gov/ (the FAA's ATC System Command Center page), at
/api/airport-events. Checked live 13 Nov 2026: no key, no sign-in, HTTP 200, `Cache-Control: no-cache`; the legacy
XML at /api/airport-status-information (linked as "XML" in the page footer) showed a new Update_Time each few minutes.
The JSON is preferred over the XML: its times are UTC (the XML gives local "6:30 pm EST" end times) and each airport
carries the FAA's own latitude and longitude, so no outside airport list is needed. The FAA states no licence on
nasstatus; it is a work of the US Government, so not subject to copyright in the US (17 U.S.C. 105).

Cordon reports what the FAA lists: the program, the airport, and the reason in the FAA's own words ("wind", "other",
"airport volume"). It never infers a cause.

Tier: a ground stop is an anomaly when the number of ground stops in effect at once is unusual against Cordon's own
count of them (data/faa_counts.jsonl, one row per collection), or when the FAA lists it against something other than
an airport (an air route traffic control center, or "ALL"): how the feed shows a nationwide stop is not yet seen, so
both shapes are covered. A ground stop at one airport on a normal day is routine. Ground delay programs and closures
are routine.
"""
import json
import re
from datetime import datetime, timedelta

from .common import fetch_or_none, now_utc, to_utc  # first: puts the doctrine kit on sys.path
from tic_doctrine import geo  # noqa: E402

SOURCE_URL = "https://nasstatus.faa.gov/api/airport-events"
PAGE_URL = "https://nasstatus.faa.gov/"
STALE_HOURS = 3  # programs last hours; with no good fetch for this long the held list is withheld
BASELINE_DAYS = 30
MIN_SAMPLES = 72  # about three days of hourly runs before the measured baseline replaces the prior
PRIOR_THRESHOLD = 4  # concurrent ground stops that count as unusual until the baseline is measured
FLOOR = 3  # never call fewer than this many concurrent ground stops unusual
QUANTILE = 0.99
NOT_AN_AIRPORT = re.compile(r"^(Z[A-Z]{2}|ALL|NAS|DCC|ATCSCC|CONUS|US)$")  # US ARTCCs are Z.. (ZNY, ZLA ...)
KINDS = {"groundStop": "ground_stop", "groundDelay": "ground_delay", "airportClosure": "closure"}


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None  # NaN


def wide_scope(airport: str) -> bool:
    """True when the FAA lists the program against something other than one airport."""
    return bool(NOT_AN_AIRPORT.match((airport or "").upper()))


def parse(rows) -> tuple[list[dict], dict]:
    """(programs, airports) from the airport-events JSON. airports maps id -> [lon, lat, name]."""
    if not isinstance(rows, list):
        raise ValueError("airport-events is not a list")
    programs, airports = [], {}
    for a in rows:
        if not isinstance(a, dict) or not a.get("airportId"):
            continue
        apt = str(a["airportId"]).strip().upper()
        lat, lon = _num(a.get("latitude")), _num(a.get("longitude"))
        name = (a.get("airportLongName") or "").strip()
        if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
            airports[apt] = [round(lon, 5), round(lat, 5), name]
        for key, kind in KINDS.items():
            p = a.get(key)
            if not isinstance(p, dict):
                continue
            start = to_utc(p.get("startTime") or "")
            rec = {"kind": kind, "airport": apt, "airport_name": name, "start": start,
                   "end": to_utc(p.get("endTime") or ""), "updated": to_utc(p.get("updatedAt") or p.get("sourceTimeStamp") or "")}
            if kind == "closure":
                rec.update({"notam": re.sub(r"\s+", " ", (p.get("simpleText") or "").strip())[:400],
                            "issued": to_utc(p.get("issuedDate") or "")})
            else:
                rec.update({"reason": (p.get("impactingCondition") or "").strip()[:120],
                            "center": p.get("center"), "advisory_url": p.get("advisoryUrl"),
                            "included_facilities": len(p.get("includedFacilities") or []),
                            "included_flights": (p.get("includedFlights") or "").strip(" :") or None})
                if kind == "ground_stop":
                    rec["probability_of_extension"] = p.get("probabilityOfExtension")
                else:
                    rec.update({"avg_delay_min": _num(p.get("avgDelay")), "max_delay_min": _num(p.get("maxDelay"))})
            programs.append(rec)
    programs.sort(key=lambda r: (r["kind"], r["airport"], r["start"] or ""))
    return programs, airports


def counts(programs: list[dict]) -> dict:
    return {k: sum(1 for p in programs if p["kind"] == k) for k in ("ground_stop", "ground_delay", "closure")}


def baseline(rows: list[dict], now: datetime) -> dict:
    """How many concurrent ground stops are normal, from Cordon's own counts over BASELINE_DAYS (before now).

    threshold: the count at or above which ground stops are unusual. Until MIN_SAMPLES rows exist it is the prior
    (PRIOR_THRESHOLD); after that one more than the 99th percentile of the counts, and never under FLOOR."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff = (now - timedelta(days=BASELINE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    xs = sorted(r["ground_stop"] for r in rows if cutoff <= r.get("at", "") < stamp and isinstance(r.get("ground_stop"), int))
    if len(xs) < MIN_SAMPLES:
        return {"threshold": PRIOR_THRESHOLD, "basis": "prior", "samples": len(xs), "p99": None}
    q = xs[int(QUANTILE * (len(xs) - 1))]
    return {"threshold": max(FLOOR, q + 1), "basis": "measured", "samples": len(xs), "p99": q}


def country(apt: str, where) -> list[str]:
    if where:
        cc = geo.country_at(where[1], where[0])
        if cc:
            return [cc]
    return ["US"] if wide_scope(apt) else []


def collect(when: str | None = None, fetch=fetch_or_none):
    """(programs, airports, error). On error the caller keeps the last good data."""
    when = when or now_utc()
    body, err = fetch(SOURCE_URL, 30)
    if body is None:
        return None, None, err
    try:
        programs, airports = parse(json.loads(body.decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as e:
        return None, None, f"unreadable: {type(e).__name__}"
    return programs, airports, None


def in_effect(programs: list[dict], now: datetime, fresh: bool) -> list[dict]:
    """What to publish. A fresh list is the FAA's word, even past a listed end time (stops are often extended).
    From a held list (the latest fetch failed) a program whose end time has passed is dropped."""
    if fresh:
        return list(programs)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return [p for p in programs if not p.get("end") or p["end"] >= stamp]
