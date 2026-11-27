"""Space-operations NOTAMs for Launch: /data/notams/launch.json (method cordon-notam-launch-1.0, 26 Nov 2026).

Launch owns space operations (rocket launches, stage and debris fall, reentry); Cordon leaves them out of its own
ranking (significance.cause() excludes them) and out of its feed items. This file gives Launch what Cordon already
reads from each such NOTAM, so Launch need not read it again: the footprint, the UTC windows from the D) schedule,
the hazard in the NOTAM's own words and the NOTAM's own text. It does not match NOTAMs to launches: that is
Launch's (launch/live.py), and nothing here names a vehicle, a provider or a launch.

Chosen from the held set (cordon/nms.py), each NOTAM separately (one record per store entry, as launch-areas.json):

  - in the launch-areas subset (nms.launch_area: an R, W or X Q-code subject or no Q) line, not a cancellation,
    not permanent, open at most 62 days, reaching FL100 with a Q) line, or with launch words);
  - space operations by Cordon's own rule (significance.space: a strong launch word, or ROCKET with a launch or a
    stage; not AIRSPACE, not a model rocket);
  - with a Q) line, a Q-code subject R, W or X (an aerodrome or facility notice that mentions a rocket range is
    not a hazard area);
  - in force, still to come, or ended within RECENT_HOURS (Launch drops a closure a day after it ends).

Each feature is the trimmed NMS feature (as in launch-areas.json) with Cordon's footprint as its geometry
(notamtext.geometry: the E) text's shape, NMS's polygon where it agrees with the Q) line, else the Q) line circle)
and properties.launch holding what Cordon read (the whole ICAO text stays in properties.coreNOTAMData, as NMS gives
it). Standard library only.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import nms, notamtext, significance

METHOD = "cordon-notam-launch-1.0"
FILE = "launch.json"
RECENT_HOURS = 24
ABOUT = ("Space-operations NOTAMs (rocket launch, stage and debris fall, reentry), each with Cordon's footprint, its "
         "UTC windows read from the D) schedule (window_mode says how: single, schedule, daily, or span when the "
         "schedule was not read in full) and the NOTAM's own words. Not matched to launches: that is Launch's. "
         "Read this file, never the FAA.")
# The hazard, from the NOTAM's own words, most specific first (the first that matches names it).
HAZARDS = [
    ("reentry", re.compile(r"\bRE-?ENTRY|\bSPLASH ?DOWN|\bDEBRIS RETURN")),
    ("debris fall", re.compile(r"\bSPACE ?DEBRIS|\bUNBURNED DEBRIS|\bFALLING (?:DEBRIS|OBJECTS|PARTS)|"
                               r"\bDEBRIS (?:FALL|IMPACT|AREA|ZONE)")),
    ("stage fall", re.compile(r"\bSTAGE\b|\bBOOSTER|\bFAIRING")),
    ("launch", re.compile(r"\bLAUNCH|\bROCKET|\bAEROSPACE|\bSPACE ?(?:VEHICLE|CRAFT|OPERATIONS|FLIGHT|FLT)|"
                          r"\bMISSILE")),
]


def hazard(text: str) -> tuple[str | None, list[str]]:
    """(hazard, hazard_words): the hazard, normalised (reentry, debris fall, stage fall, launch), and every launch
    word the NOTAM uses, in its own spelling and order."""
    t = (text or "").upper()
    words = []
    for h in nms.LAUNCH_WORDS.finditer(t):
        w = h.group(0)
        if w.startswith("SPACE") and t[max(0, h.start() - 3):h.start()] == "AIR":
            continue
        if w not in words:
            words.append(w)
    for name, rx in HAZARDS:
        if rx.search(t):
            return name, words
    return None, words


def selected(f: dict, now: datetime) -> bool:
    """Space-operations NOTAMs of launch-areas (significance.space), not cancellations, with a Q-code subject R, W
    or X or no Q) line, in force, still to come, or ended within the last day."""
    m, text = nms.meta(f), nms.icao_text(f) or ""
    if m.get("type") == "C" or not nms.launch_area(f) or not significance.space(text):
        return False
    q = notamtext.qline(text)
    if q and q["code"][1:2] not in ("R", "W", "X"):
        return False
    end = nms._dt(m.get("effectiveEnd"))
    return end is None or end >= now - timedelta(hours=RECENT_HOURS)


def record(f: dict) -> dict:
    """The feature Launch reads: the trimmed NMS feature, Cordon's footprint, and properties.launch."""
    m, text = nms.meta(f), nms.icao_text(f) or ""
    q = notamtext.qline(text)
    it = notamtext.items(text)
    geom, basis, precision = notamtext.geometry(f, text)
    ws, mode = notamtext.windows(m.get("effectiveStart"), m.get("effectiveEnd"), m.get("schedule") or it.get("D"))
    hz, words = hazard(text)
    ref = nms.refers(f)
    launch = {
        "method": METHOD, "id": m.get("id"), "number": m.get("number"),
        "fir": (q or {}).get("fir") or m.get("affectedFir"), "location": m.get("icaoLocation") or m.get("location"),
        "classification": m.get("classification"), "type": m.get("type"),
        "replaces": ref.split("|", 1)[0] if ref else None,
        "issued": m.get("issued"), "last_updated": m.get("lastUpdated"),
        "q_code": (q or {}).get("code"), "lower_fl": (q or {}).get("lower_fl"), "upper_fl": (q or {}).get("upper_fl"),
        "lower": it.get("F"), "upper": it.get("G"),
        "hazard": hz, "hazard_words": words,
        "effective_start": m.get("effectiveStart"), "effective_end": m.get("effectiveEnd"),
        "estimated": m.get("estimated"), "schedule": m.get("schedule") or it.get("D"),
        "windows": ws, "window_mode": mode,
        "geometry_basis": basis, "precision_class": precision,
        "text": notamtext.e_text(text, m.get("text")),
    }
    t = nms.trim(f)
    return {"type": "Feature", "geometry": geom, "properties": {**t["properties"], "launch": launch}}


def collection(store: dict, now: datetime) -> list[dict]:
    """The selected NOTAMs, in store-key order."""
    return [record(f) for k, f in sorted(store.items()) if selected(f, now)]
