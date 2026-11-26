"""Significance of international NOTAMs (method tic-significance-0.1, Cordon's part: cause, rarity, dynamics, tier).

The method is tic-doctrine's docs/significance.md: a closure or warning is the footprint of an event, so it is ranked
by the event (what caused it, how rare that is here, how the chain behaves), not by its shape. This module does the
first part for the FAA NMS-API's international NOTAMs (classification INTL), from what Cordon alone knows. Coincidence
(other lines at the same place and time) and consequence (people and sites inside) come later, from COP, so the tier
here never uses them.

Which NOTAMs: international ones whose ICAO Q-code subject (letters 2-3 of NMS's selectionCode, else of the Q) line)
is a restriction or warning in SUBJECTS. Everything else is out of scope and never ranked.

Steps, each writing its reasons:
  - cause(): from the Q-code subject first (CODE_CAUSE: WM, WE, RD, RA military and test; WH, WD, WR a hazard to
    people only with ordnance, structure-demolition, evacuation or release words, else quarry, mine and avalanche
    blasting or spraying (scheduled and routine), training (military and test), or CODE_DEFAULT), then the NOTAM's
    own words (WORDS, in order; RT, RR, RP and WU take their cause from the words alone). Fireworks under WD or WH
    are scheduled and routine. Space words (nms.LAUNCH_WORDS, see space()) make it space operations, which Launch
    owns, and a GNSS subject (G) is Noisefloor's and Launch's: both are excluded from the ranking.
  - the baseline (new_baseline(), update(); small, committed, never pruned): counts of new NOTAMs per (region,
    subject, cause group) per day, where the region is the FIR (affectedFir, else location) and the wider scope its
    ICAO prefix (first two letters; a prefix, not a country; its count is the sum of its regions'); each scope's
    first day (its history starts the first day any international NOTAM is seen there); half-octave histograms of
    area and duration per (region, subject).
  - the chains (working state, beside the baseline, pruned CHAIN_KEEP_DAYS after a chain ends; rebuildable from the
    permanent archive): one entry per ranked NOTAM held, keyed as the store keys it (number, FIR, location), with
    the number of the chain's first NOTAM ("o"; assess() gives it as chain_first, the feed's subject). A NOTAM
    counts once, when its chain starts: the same version seen again, a later version, a copy for another location,
    or a replacement of a NOTAM already chained does not count again.
  - rarity(): rare (none), uncommon (at most two) or common, for the same subject and cause group, against the 365
    days before the NOTAM was first seen (or the whole history, if shorter), at the narrowest scope with at least
    MIN_HISTORY_DAYS of history; before that, history_short with the count and the days held.
  - dynamics along a chain: a replacing NOTAM (type R, naming the one it replaces) or a cancel (type C): date_slips
    (start moved later before the earlier start was reached: a postponement, not a day-by-day re-activation),
    extended (end moved later), enlarged (radius grew or ceiling rose), cancelled_early.
  - large(): area (the Q) line circle) above the (region, subject)'s 95th percentile, once the region has
    MIN_HISTORY_DAYS of history and MIN_SIZE_N are held.
  - tier(): significant only for a hazard-to-people or disaster cause that is rare; notable for rare, a hazard-to-
    people cause, two or more date slips or enlarged, or large for region on an RT, RP or RD area; scheduled and
    unknown causes never above notable; the rest routine.

Rarity and size are judged once, when a NOTAM is first seen, against the history before it, and kept on its chain,
so a later burst of the same kind does not make the first one common after the fact.

Standard library only. Pure functions: the lane (cordon/nms.py) loads, updates and stores the baseline and chains.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta

from . import nms

METHOD = "tic-significance-0.1"
FORMAT = "cordon-significance-baseline/2"
MIN_HISTORY_DAYS = 90      # a scope's rarity label needs this much history (the note's rule)
WINDOW_DAYS = 365          # rarity counts over the year before (or the whole history, if shorter)
MIN_SIZE_N = 30            # "large for region" needs this many NOTAMs of the subject held in the region (and the
                           # region MIN_HISTORY_DAYS of history)
LARGE_PCT = 0.95           # ... and means an area above their 95th percentile
CHAIN_KEEP_DAYS = 16     # an ended chain is kept as long as the store keeps an ended NOTAM (nms.ENDED_KEEP_DAYS)
NM_KM = 1.852

# The ICAO Q-code subjects ranked (restrictions and warnings; the note's table, counts on 19 Nov 2026).
SUBJECTS = {"RT": "temporary restricted area", "WU": "unmanned aircraft", "RD": "danger area", "RR": "restricted area",
            "RA": "airspace reservation", "WE": "exercise", "WM": "missile, gun or rocket firing", "WH": "blasting",
            "RP": "prohibited area", "WD": "demolition of explosives", "WR": "radioactive or toxic materials"}
# Subjects whose code sets the cause (the publisher chose it, as a US regulation number does).
CODE_CAUSE = {"WH": ("blasting", "hazard_to_people"), "WD": ("demolition of explosives", "hazard_to_people"),
              "WR": ("radioactive or toxic materials", "hazard_to_people"),
              "WM": ("missile, gun or rocket firing", "military_and_test"), "WE": ("exercise", "military_and_test"),
              "RD": ("danger area", "military_and_test"), "RA": ("airspace reservation", "military_and_test")}
AREA_SUBJECTS = ("RT", "RP", "RD")   # "large for region" lifts these to notable

FIREWORKS = re.compile(r"\b(?:FIRE ?WORKS?|PYROTECHNIC\w*)\b")
# Words in the NOTAM's own text, first match wins: (pattern, cause, cause group). Fireworks come first (a display is
# scheduled, whatever else it says), then hazard to people, disaster response, scheduled events and VIP movements (a
# VIP closure often says "security" too; the movement is the cause), security, then military.
WORDS = [
    (FIREWORKS, "fireworks", "scheduled_and_routine"),
    (re.compile(r"\b(?:DETONAT\w*|EXPLOSI\w*|DEMOLITION|BLASTING|UXO|UNEXPLODED|ORDNANCE DISPOSAL|BOMB DISPOSAL)\b"),
     "detonation or demolition", "hazard_to_people"),
    (re.compile(r"\b(?:HAZMAT|CHEMICAL\w*|RADIOLOGICAL|RADIOACTIVE|TOXIC|PLUME)\b"), "hazardous materials",
     "hazard_to_people"),
    (re.compile(r"\b(?:EVACUAT\w*|SHELTER IN PLACE)\b"), "evacuation", "hazard_to_people"),
    (re.compile(r"\b(?:FIRE ?FIGHT\w*|FOREST FIRES?|WILD ?FIRES?|BUSH ?FIRES?)\b"), "fire", "disaster_response"),
    (re.compile(r"\b(?:SEARCH AND RESCUE|SAR OPS?|RESCUE OPS?|RESCUE OPERATIONS?)\b"), "search and rescue",
     "disaster_response"),
    (re.compile(r"\b(?:DISASTER|RELIEF|HUMANITARIAN|FLOOD\w*|EARTHQUAKE)\b"), "relief operations",
     "disaster_response"),
    (re.compile(r"\b(?:VIP|VVIP|HEAD OF STATE|PRESIDENT\w*|PRIME MINISTER|STATE VISIT|ROYAL|SUMMIT)\b"),
     "VIP movement", "scheduled_and_routine"),
    (re.compile(r"\b(?:AIR ?SHOWS?|AIR DISPLAY|AEROBATIC\w*|SPORTS?|FOOTBALL|STADIUM|MARATHON|FESTIVAL|PARADE|"
                r"CELEBRATION\w*|CEREMONY|CONCERT|OLYMPIC\w*)\b"), "public event", "scheduled_and_routine"),
    (re.compile(r"\b(?:LAW ENFORCEMENT|POLICE)\b"), "law enforcement operation", "security_and_law_enforcement"),
    (re.compile(r"\b(?:SECURITY|COUNTER ?TERROR\w*|ANTI-?TERROR\w*)\b"), "security area",
     "security_and_law_enforcement"),
    (re.compile(r"\b(?:MILITARY|MIL|MISSILES?|GUNNERY|FIRING|FRNG|LIVE FIRE|ARTILLERY|MORTAR|EXERCISES?|EXER|"
                r"MANOEUVRES?|MANEUVERS?|AIR DEFEN[CS]E|SHOOTING|BOMBING)\b"), "military operation",
     "military_and_test"),
]
# WH (blasting), WD (demolition of explosives) and WR (radioactive or toxic materials) are a hazard to people only
# with words for ordnance, the demolition of a structure, an evacuation or a release; without them most are quarry,
# mine and avalanche-control blasting, explosives training, or forest and crop spraying (measured 19-25 Nov 2026:
# 102 of 111 such notices). Then, in order: routine work words (scheduled and routine), military words (military and
# test), else CODE_DEFAULT.
CODE_HAZARD = re.compile(r"\b(?:DETONAT\w*|UXO|UXB|UNEXPLODED|ORDNANCE|BOMBS?|MUNITIONS?|AMMUNITIONS?|EOD|"
                         r"DEMOLITION OF (?:THE|A|AN)\b|DEMOLISH\w*|CHIMNEYS?|COOLING TOWERS?|BUILDINGS?|BRIDGES?|"
                         r"STRUCTURES?|EVACUAT\w*|SHELTER IN PLACE|LEAK\w*|PLUME|SPILL\w*|HAZMAT)\b")
CODE_ROUTINE = [
    (re.compile(r"\b(?:QUARR\w*|MINES?|MINING|OPEN PIT|OPENCAST)\b"), "quarry or mine blasting"),
    (re.compile(r"\bAVALANCHE\b"), "avalanche control"),
    (re.compile(r"\b(?:ROADS?|CONSTRUCTION|TUNNEL\w*|SEISMIC|SURVEY)\b"), "construction or survey blasting"),
    (re.compile(r"\b(?:FOREST TREATMENT|AERIAL TREATMENT|TREATMENT|SPRAY\w*|AGRICULTUR\w*|PLANTATIONS?|CROPS?|"
                r"PESTICIDE\w*|LOCUST\w*)\b"), "forest or crop spraying"),
]
CODE_MILITARY = re.compile(r"\b(?:MILITARY|MIL|TRG|TRAINING|FIRING|FRNG|EXERCISES?|EXER|RANGE)\b")
CODE_DEFAULT = {"WH": ("blasting, no hazard words", "scheduled_and_routine"),
                "WD": ("demolition of explosives, no hazard words", "military_and_test"),
                "WR": ("radioactive or toxic materials, no hazard words", "unknown")}
# nms.LAUNCH_WORDS (Launch's candidate words) also catch military firing ("MISSILE", "ROCKET"), model rockets, the
# "SPACE FLT" inside "AIRSPACE FLT" and "STAGE". A launch-word hit makes a NOTAM space operations only when it is
# one of the space phrases themselves, or a rocket launch, or a rocket with a stage.
WEAK_LAUNCH = {"MISSILE", "ROCKET", "STAGE"}
ROCKET_LAUNCH = re.compile(r"\bROCKET\b.{0,40}\bLAUNCH|\bLAUNCH\w*\b.{0,40}\bROCKET\b", re.S)
MODEL_ROCKET = re.compile(r"\bMODEL ROCKETS?\b")


# ---------- one NOTAM ----------

def subject(m: dict, text: str | None = None) -> str:
    """The Q-code subject (letters 2-3): NMS's selectionCode, else the ICAO text's Q) line."""
    sc = (m.get("selectionCode") or "").strip()
    if len(sc) >= 3:
        return sc[1:3].upper()
    hit = nms.QLINE.search(text or "")
    return hit.group(1)[1:3] if hit else ""


def candidate(f: dict) -> bool:
    """An international NOTAM (classification INTL) of a ranked subject, not a cancellation."""
    m = nms.meta(f)
    return m.get("classification") == "INTL" and m.get("type") != "C" and subject(m, nms.icao_text(f)) in SUBJECTS


def space(text: str) -> str | None:
    """The launch words that make a NOTAM space operations (Launch's), or None. See WEAK_LAUNCH."""
    t = (text or "").upper()
    hits = []
    for h in nms.LAUNCH_WORDS.finditer(t):
        w = h.group(0)
        if w.startswith("SPACE") and t[max(0, h.start() - 3):h.start()] == "AIR":
            continue                                    # AIRSPACE FLT, AIRSPACE VEHICLE...
        hits.append(w)
    strong = [w for w in hits if w not in WEAK_LAUNCH]
    if strong:
        return strong[0]
    if "ROCKET" in hits and not MODEL_ROCKET.search(t) and ("STAGE" in hits or ROCKET_LAUNCH.search(t)):
        return "ROCKET LAUNCH" if ROCKET_LAUNCH.search(t) else "ROCKET, STAGE"
    return None


def cause(f: dict) -> dict:
    """{cause, cause_group, cause_basis, excluded}: the Q-code subject first, then the NOTAM's own words.
    excluded names the program that owns the NOTAM (Launch for space operations, Noisefloor for GNSS), else None."""
    m, icao = nms.meta(f), nms.icao_text(f)
    subj = subject(m, icao)
    text = (m.get("text") or icao or "").upper()
    code = f"Q-code {subj}" + (f" ({SUBJECTS[subj]})" if subj in SUBJECTS else "")
    if subj[:1] == "G":
        return {"cause": "GNSS", "cause_group": "gnss", "cause_basis": [code], "excluded": "noisefloor"}
    sp = space(text)
    if sp:
        return {"cause": "space operations", "cause_group": "space_operations",
                "cause_basis": [code, "text: " + sp], "excluded": "launch"}
    words = None
    for pat, c, g in WORDS:
        hit = pat.search(text)
        if hit:
            words = (c, g, "text: " + hit.group(0))
            break
    if subj in CODE_CAUSE:
        c, g = CODE_CAUSE[subj]
        if subj in ("WD", "WH") and words and words[0] == "fireworks":
            return {"cause": "fireworks", "cause_group": "scheduled_and_routine", "cause_basis": [code, words[2]],
                    "excluded": None}
        if subj in CODE_DEFAULT:
            return dict(_hazard_code(subj, c, code, text), excluded=None)
        basis = [code] + ([words[2]] if words and words[1] == g else [])   # words never override the code's group
        return {"cause": c, "cause_group": g, "cause_basis": basis, "excluded": None}
    if words:
        return {"cause": words[0], "cause_group": words[1], "cause_basis": [code, words[2]], "excluded": None}
    return {"cause": "unknown", "cause_group": "unknown", "cause_basis": [code, "no cause words"], "excluded": None}


def _hazard_code(subj: str, c: str, code: str, text: str) -> dict:
    """WH, WD, WR: a hazard to people only with hazard words and no routine work or training words (see
    CODE_HAZARD); else routine work, military, or CODE_DEFAULT."""
    hz = CODE_HAZARD.search(text)
    routine = next(((pat.search(text), name) for pat, name in CODE_ROUTINE if pat.search(text)), None)
    mil = CODE_MILITARY.search(text)
    if hz and not routine and not (mil and mil.group(0) in ("TRG", "TRAINING")):
        return {"cause": c, "cause_group": "hazard_to_people", "cause_basis": [code, "text: " + hz.group(0)]}
    if routine:
        return {"cause": routine[1], "cause_group": "scheduled_and_routine",
                "cause_basis": [code, "text: " + routine[0].group(0)]}
    if mil:
        return {"cause": c + " (military)", "cause_group": "military_and_test", "cause_basis": [code, "text: " +
                                                                                               mil.group(0)]}
    dc, dg = CODE_DEFAULT[subj]
    return {"cause": dc, "cause_group": dg, "cause_basis": [code, "no hazard words"]}


def region(m: dict) -> str:
    """The FIR (affectedFir), else the location."""
    return (m.get("affectedFir") or m.get("location") or m.get("icaoLocation") or "").strip().upper()


def prefix(reg: str) -> str:
    """The wider scope: the region's first two ICAO letters (an ICAO prefix, not a country)."""
    return reg[:2]


def radius_nm(f: dict) -> int | None:
    """The Q) line radius in NM (NMS's radius field, else the ICAO text); 999 (the whole FIR) and none are None."""
    m = nms.meta(f)
    r = m.get("radius")
    if r in (None, ""):
        hit = re.search(r"Q\)\s*[^\n]*/\d{4}[NS]\d{5}[EW](\d{3})", nms.icao_text(f) or "")
        r = hit.group(1) if hit else None
    try:
        r = int(str(r).strip())
    except (TypeError, ValueError):
        return None
    return r if 0 <= r < 999 else None


def area_km2(f: dict) -> float | None:
    """Area of the Q) line circle in km2 (the radius ICAO's Q) line gives; the drawn shape may be smaller)."""
    r = radius_nm(f)
    return round(math.pi * (max(r, 1) * NM_KM) ** 2, 1) if r is not None else None


def _min(s) -> int | None:
    d = nms._dt(s) if s and not str(s).upper().startswith("PERM") else None
    return int(d.timestamp() // 60) if d else None


def hours(m: dict) -> float | None:
    """effectiveStart to effectiveEnd in hours; None for a permanent NOTAM."""
    a, b = _min(m.get("effectiveStart")), _min(m.get("effectiveEnd"))
    return round((b - a) / 60, 1) if a is not None and b is not None and b >= a else None


def _fl(m: dict) -> int | None:
    v = nms._fl(m.get("maximumFl"), -1)
    return v if v >= 0 else None


# ---------- the baseline (committed, small) and the chains (working state) ----------

def new_baseline(start: str) -> dict:
    """An empty baseline whose history starts on day start (YYYY-MM-DD). Days are counted from start."""
    return {"format": FORMAT, "method": METHOD, "start": start, "updated_at": None, "first": {}, "counts": {},
            "sizes": {}}


def dumps(b: dict) -> str:
    """The baseline as committed: compact JSON with one region or scope per line, so a run's diff is a few lines."""
    lines = ["{"]
    keys = list(b)
    for i, k in enumerate(keys):
        end = "," if i < len(keys) - 1 else ""
        v = b[k]
        if isinstance(v, dict) and v and k in ("first", "counts", "sizes"):
            items = [f" {json.dumps(kk)}:{json.dumps(v[kk], separators=(',', ':'), sort_keys=True)}"
                     for kk in sorted(v)]
            lines.append(f"{json.dumps(k)}:{{")
            lines.append(",\n".join(items))
            lines.append("}" + end)
        else:
            lines.append(f"{json.dumps(k)}:{json.dumps(v, separators=(',', ':'))}{end}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def day_of(b: dict, when: datetime) -> int:
    """Days since the baseline's start."""
    return (when.date() - datetime.fromisoformat(b["start"]).date()).days


def _bin(v: float) -> int:
    """Half-octave bin of a positive value (bin k holds 2^(k/2) to 2^((k+1)/2))."""
    return math.floor(2 * math.log2(max(v, 1e-3)))


def _edge(k: int) -> float:
    return round(2 ** ((k + 1) / 2), 1)


def _p95_bin(hist: dict) -> tuple[int, int]:
    """(the bin holding the 95th percentile, the count)."""
    n = sum(hist.values())
    run = 0
    for k in sorted(hist, key=int):
        run += hist[k]
        if run >= LARGE_PCT * n:
            return int(k), n
    return 0, n


def _history(b: dict, scope: str, day: int) -> int | None:
    first = b["first"].get(scope)
    return day - first if first is not None else None


def large(b: dict, reg: str, subj: str, area: float | None, day: int) -> tuple[bool | None, list]:
    """Whether the area (the Q) line circle) is above the (region, subject)'s 95th percentile among the NOTAMs held
    before this one: None until the region has MIN_HISTORY_DAYS of history (as rarity) and MIN_SIZE_N are held. The
    numbers: [[p95, n]] when above, else [[n, days held]]."""
    hist = (b["sizes"].get(f"{reg}|{subj}") or {}).get("a") or {}
    n, held = sum(hist.values()), _history(b, reg, day) or 0
    if area is None or n < MIN_SIZE_N or held < MIN_HISTORY_DAYS:
        return None, [[n, held]]
    k, n = _p95_bin(hist)
    return (True, [[_edge(k), n, area]]) if _bin(area) > k else (False, [[n, held]])


def large_text(flag: bool | None, nums: list, subj: str, reg: str) -> str:
    if flag is None:
        n, held = nums[0][:2]
        return (f"{n} {subj} NOTAMs held in {reg} over {held} days; size is judged from {MIN_SIZE_N} and "
                f"{MIN_HISTORY_DAYS} days")
    if not flag:
        return f"area not above the 95th percentile of {subj} NOTAMs in {reg}"
    p, n, area = nums[0]
    return f"area {area:g} km2, above the 95th percentile (about {p:g} km2) of {n} {subj} NOTAMs in {reg}"


def _key(scope: str, subj: str, group: str) -> str:
    return f"{scope}|{subj}|{group}"


def _count(b: dict, scope: str, subj: str, group: str, lo: int, hi: int) -> int:
    """New NOTAMs of a subject and cause group in a scope from day lo to day hi. Counts are kept per region only; a
    prefix's count is the sum of its regions'."""
    if len(scope) == 2:
        tail = f"|{subj}|{group}"
        keys = [k for k in b["counts"] if k.startswith(scope) and k.endswith(tail)]
    else:
        keys = [_key(scope, subj, group)]
    return sum(v for k in keys for d, v in (b["counts"].get(k) or {}).items() if lo <= int(d) <= hi)


def rarity(b: dict, reg: str, subj: str, group: str, day: int) -> tuple[str, list]:
    """(label, [scope, count, days]) for a NOTAM of this subject and cause group first seen in this region on this
    day, against what the baseline held before it (the same day's earlier ones included): the region if it has
    MIN_HISTORY_DAYS of history, else its ICAO prefix if that has, else history_short with the region's count and days
    held. A scope's history starts the first day an international NOTAM of any subject was seen there."""
    for scope in (reg, prefix(reg)):
        held = _history(b, scope, day)
        if held is None or held < MIN_HISTORY_DAYS:
            continue
        win = min(WINDOW_DAYS, held)
        n = _count(b, scope, subj, group, day - win, day)
        return ("rare" if n == 0 else "uncommon" if n <= 2 else "common"), [scope, n, win]
    held = _history(b, reg, day) or 0
    return "history_short", [reg, _count(b, reg, subj, group, day - held, day), held]


def rarity_text(label: str, nums: list, subj: str, reg: str, group: str = "") -> str:
    scope, n, days = nums
    where = scope if scope == reg else f"ICAO prefix {scope}"
    what = f"{subj} NOTAMs" + (f" ({group.replace('_', ' ')})" if group else "")
    if label == "history_short":
        return f"{n} earlier {what} in {where} in the {days} days held; rarity needs {MIN_HISTORY_DAYS} days of history"
    return f"{n} earlier {what} in {where} in {days} days"


def _note_first(b: dict, reg: str, day: int) -> None:
    for scope in (reg, prefix(reg)):
        if scope and (b["first"].get(scope) is None or day < b["first"][scope]):
            b["first"][scope] = day


def _add(b: dict, reg: str, subj: str, group: str, day: int, area: float | None, hrs: float | None) -> None:
    c = b["counts"].setdefault(_key(reg, subj, group), {})
    c[str(day)] = c.get(str(day), 0) + 1
    s = b["sizes"].setdefault(f"{reg}|{subj}", {})
    for name, v in (("a", area), ("d", hrs)):
        if v is not None:
            h = s.setdefault(name, {})
            k = str(_bin(v))
            h[k] = h.get(k, 0) + 1


def _order(f: dict) -> tuple:
    m = nms.meta(f)
    return (m.get("lastUpdated") or m.get("issued") or "", m.get("issued") or "", m.get("number") or "")


def _permanent(m: dict) -> bool:
    return str(m.get("effectiveEnd") or "").upper().startswith("PERM")


def update(b: dict, chains: dict, feats: list[dict], now: datetime, counted_before: str | None = None) -> dict:
    """One pull's features into the baseline and the chains (sorted by lastUpdated here). Every international NOTAM
    starts its scopes' history; a ranked one starts or continues a chain and counts once, when its chain starts,
    under its cause group. A NOTAM already chained (the same version again, or a later version) is not counted
    again; a replacing one continues the chain it names (its dynamics) and is not counted; a cancel closes its chain.
    Space and GNSS NOTAMs (other programs') are neither chained nor counted.

    A date slip is a start moved later while the earlier NOTAM had not yet started (a postponement); a replacement
    issued after the earlier start (a standing area re-activated day by day) is not a slip.

    counted_before: when the chains were lost (an Actions cache miss), the baseline's last update time; a NOTAM
    issued before it was counted then, so it is chained without counting again. A NOTAM NMS lists once per location
    (one number and FIR, several locations) is one chain per location and counts once. Returns counts."""
    day = day_of(b, now)
    out = {"seen": 0, "new": 0, "replaced": 0, "cancelled": 0, "repeat": 0, "rechained": 0, "other_location": 0,
           "excluded": 0}
    held = {k.rsplit("|", 1)[0] for k in chains}       # number|FIR of every chain
    for f in sorted(feats, key=_order):
        m = nms.meta(f)
        if m.get("classification") != "INTL":
            continue
        reg = region(m)
        if not reg:
            continue
        _note_first(b, reg, day)
        typ, ref = m.get("type"), nms.refers(f)
        if typ == "C":
            ch = chains.get(ref) if ref else None
            if ch and ch.get("x") is None:
                t = _min(m.get("effectiveStart") or m.get("issued"))
                ch["x"] = t if t is not None else int(now.timestamp() // 60)
                ch["ce"] = bool(ch.get("e") is not None and ch["x"] < ch["e"])
                out["cancelled"] += 1
            continue
        subj = subject(m, nms.icao_text(f))
        if subj not in SUBJECTS:
            continue
        out["seen"] += 1
        k = nms.key(f)
        if k in chains:
            chains[k]["id"] = m.get("id")
            out["repeat"] += 1
            continue
        c = cause(f)
        if c["excluded"]:
            out["excluded"] += 1
            continue
        a, h = area_km2(f), hours(m)
        s, e, fl = _min(m.get("effectiveStart")), _min(m.get("effectiveEnd")), _fl(m)
        old = chains.get(ref) if typ == "R" and ref else None
        if old is not None:
            issued = _min(m.get("issued")) or int(now.timestamp() // 60)
            slip = bool(s is not None and old.get("s") is not None and s > old["s"] and issued < old["s"])
            ch = {**old, "id": m.get("id"), "o": old.get("o") or ref.split("|", 1)[0],
                  "s": s, "e": e, "a": a, "fl": fl, "n": old.get("n", 1) + 1,
                  "sl": old.get("sl", 0) + (1 if slip else 0),
                  "ex": bool(old.get("ex") or (e is not None and old.get("e") is not None and e > old["e"])
                             or (_permanent(m) and old.get("e") is not None)),
                  "en": bool(old.get("en") or (a is not None and old.get("a") is not None and a > old["a"])
                             or (fl is not None and old.get("fl") is not None and fl > old["fl"]))}
            ch.pop("x", None)
            ch.pop("ce", None)
            if old.get("x") is None:
                old["x"] = int(now.timestamp() // 60)      # the replaced NOTAM ends where its replacement is seen
            chains[k] = ch
            held.add(k.rsplit("|", 1)[0])
            out["replaced"] += 1
            continue
        # a new chain, judged against the history before it
        g = c["cause_group"]
        lab, rn = rarity(b, reg, subj, g, day)
        big, ln = large(b, reg, subj, a, day)
        chains[k] = {"id": m.get("id"), "o": m.get("number"), "r": reg, "q": subj, "g": g, "d": day,
                     "s": s, "e": e, "a": a, "fl": fl,
                     "n": 1, "sl": 0, "ex": False, "en": False, "ra": lab, "rn": rn, "lg": big, "ln": ln}
        if k.rsplit("|", 1)[0] in held:
            out["other_location"] += 1                  # counted under its first location
            continue
        held.add(k.rsplit("|", 1)[0])
        if counted_before and (m.get("issued") or m.get("lastUpdated") or "9") < counted_before:
            out["rechained"] += 1                       # counted before the chains were lost
            continue
        _add(b, reg, subj, g, day, a, h)
        out["new"] += 1
    b["updated_at"] = nms.iso(now)
    return out


def prune(chains: dict, now: datetime) -> dict:
    """Drop chains ended (or closed) over CHAIN_KEEP_DAYS ago. Only the chains are pruned: they are working state,
    rebuildable from the permanent archive. The baseline's daily counts are never pruned (all data is kept)."""
    cut = int((now - timedelta(days=CHAIN_KEEP_DAYS)).timestamp() // 60)
    gone = [k for k, ch in chains.items()
            if (ch["x"] if ch.get("x") is not None else ch.get("e")) is not None
            and (ch["x"] if ch.get("x") is not None else ch["e"]) < cut]
    for k in gone:
        del chains[k]
    return {"chains_dropped": len(gone), "chains": len(chains)}


def replay(pulls, b: dict | None = None, chains: dict | None = None, deadline: float | None = None
           ) -> tuple[dict | None, dict, dict]:
    """The baseline and chains from archived pulls: an iterable of (pulled_at, features) in time order (each
    archive day file, grouped by its records' pulled_at). For the backfill. Returns (baseline, chains, counts)."""
    chains = {} if chains is None else chains
    total: dict = {}
    now = last_prune = None
    for t, feats in pulls:
        now = nms._dt(t)
        if b is None:
            b = new_baseline(now.strftime("%Y-%m-%d"))
        for k, v in update(b, chains, feats, now).items():
            total[k] = total.get(k, 0) + v
        if last_prune is None or now - last_prune > timedelta(days=1):
            prune(chains, now)
            last_prune = now
    if b is not None and now is not None:
        prune(chains, now)
    return b, chains, total


# ---------- dynamics, tier, basis ----------

def dynamics(ch: dict | None) -> dict:
    """date_slips, extended, enlarged, cancelled_early, and how many NOTAMs the chain has had."""
    ch = ch or {}
    return {"date_slips": ch.get("sl", 0), "extended": bool(ch.get("ex")), "enlarged": bool(ch.get("en")),
            "cancelled_early": bool(ch.get("ce")), "notams": ch.get("n", 1)}


def tier(group: str, rarity_label: str, dyn: dict, large_flag: bool | None, subj: str) -> tuple[str, list[str]]:
    """(tier, reasons) from what Cordon alone knows (no coincidence or consequence; those come from COP)."""
    reasons = []
    if rarity_label == "rare":
        reasons.append("rare here")
    if group == "hazard_to_people":
        reasons.append("hazard to people")
    if dyn.get("date_slips", 0) >= 2:
        reasons.append(f"date moved {dyn['date_slips']} times")
    if dyn.get("enlarged"):
        reasons.append("enlarged")
    if large_flag and subj in AREA_SUBJECTS:
        reasons.append("large for the region")
    t = "notable" if reasons else "routine"
    if group in ("hazard_to_people", "disaster_response") and rarity_label == "rare":
        t = "significant"
    if group in ("scheduled_and_routine", "unknown") and t == "significant":
        t = "notable"                                # the caps (unreachable by these rules; kept for COP's)
    return t, reasons


def _phrase(c: dict, subj: str) -> str:
    name = SUBJECTS.get(subj, subj)
    if c["cause_group"] == "unknown":
        return f"{name} notice, cause not stated"
    if c["cause"] == name:
        return f"{name} notice"
    return f"{c['cause']} notice ({name})"


def basis(c: dict, subj: str, reg: str, country: str | None, rar: str, rnums: list, dyn: dict,
          big: bool | None, held_days: int | None = None) -> str:
    """One plain sentence, e.g. "blasting notice, Russia (UUWV); history short (8 days)". A short history is
    given as the days held now (held_days), which is what a reader weighs; rarity_basis keeps the first-seen count."""
    parts = [_phrase(c, subj) + ", " + (f"{country} ({reg})" if country else reg)]
    scope, n, days = rnums
    if rar == "history_short":
        parts.append(f"history short ({days if held_days is None else held_days} days)")
    else:
        where = scope if scope == reg else "ICAO prefix " + scope
        parts.append(f"{rar} ({n} in {where} in {days} days)")
    if dyn.get("date_slips"):
        parts.append(f"date moved {dyn['date_slips']} time{'s' if dyn['date_slips'] > 1 else ''}")
    for w in ("enlarged", "extended"):
        if dyn.get(w):
            parts.append(w)
    if big and subj in AREA_SUBJECTS:
        parts.append("large for the region")
    return "; ".join(parts)


def country_of(f: dict) -> str | None:
    """The country the NOTAM's point lies in (the kit's Natural Earth outlines), by name; None at sea."""
    from tic_doctrine import geo
    pts = geo.geometry_points(f.get("geometry"))
    if not pts:
        return None
    lat, lon = pts[0]                                   # the kit gives (lat, lon)
    cc = geo.country_at(lat, lon)
    return (geo.name(cc) or cc) if cc else None


def assess(f: dict, b: dict, chains: dict, now: datetime, country=country_of) -> dict | None:
    """The significance block for one held NOTAM, or None when it is out of scope or excluded (space, GNSS)."""
    if not candidate(f):
        return None
    m = nms.meta(f)
    c = cause(f)
    if c["excluded"]:
        return None
    reg, subj = region(m), subject(m, nms.icao_text(f))
    ch = chains.get(nms.key(f))
    if ch is None:
        # not seen through the chains (a store rebuilt from the published files): judged now
        lab, rn = rarity(b, reg, subj, c["cause_group"], day_of(b, now))
        big, ln = large(b, reg, subj, area_km2(f), day_of(b, now))
        ch = {"ra": lab, "rn": rn, "lg": big, "ln": ln}
    dyn = dynamics(ch)
    first = ch.get("o") or (nms.refers(f) or "").split("|", 1)[0] or m.get("number")
    t, reasons = tier(c["cause_group"], ch["ra"], dyn, ch.get("lg"), subj)
    return {"tier": t, "method": METHOD, "cause": c["cause"], "cause_group": c["cause_group"],
            "cause_basis": c["cause_basis"], "rarity": ch["ra"],
            "rarity_basis": rarity_text(ch["ra"], ch["rn"], subj, reg, ch.get("g") or c["cause_group"]),
            "rarity_counts": {"scope": ch["rn"][0], "earlier": ch["rn"][1], "days": ch["rn"][2]},
            "dynamics": dyn, "chain_first": first,
            "large_for_region": ch.get("lg"), "large_basis": large_text(ch.get("lg"), ch["ln"], subj, reg),
            "reasons": reasons,
            "basis": basis(c, subj, reg, country(f) if country and t != "routine" else None, ch["ra"], ch["rn"],
                           dyn, ch.get("lg"), day_of(b, now) - b["first"].get(reg, day_of(b, now)))}


def active(f: dict, now: datetime) -> bool:
    """In force or still to come: not past its end (a permanent NOTAM stays active)."""
    e = nms.meta(f).get("effectiveEnd")
    if not e or str(e).upper().startswith("PERM"):
        return True
    d = nms._dt(e)
    return d is None or d >= now


def ranked(store: dict, b: dict, chains: dict, now: datetime, country=country_of) -> tuple[list[dict], dict]:
    """The held international NOTAMs, active, that are notable or significant: each its trimmed NMS feature plus
    properties.significance, significant first, newest issued first within a tier; and the count of each tier. A
    NOTAM NMS lists once per location appears once (its first location in key order)."""
    out, tiers = [], {"significant": 0, "notable": 0, "routine": 0, "excluded": 0}
    seen = set()
    for k, f in sorted(store.items()):
        if not candidate(f) or not active(f, now):
            continue
        nf = k.rsplit("|", 1)[0]
        if nf in seen:
            continue
        seen.add(nf)
        s = assess(f, b, chains, now, country=country)
        if s is None:
            tiers["excluded"] += 1
            continue
        tiers[s["tier"]] += 1
        if s["tier"] == "routine":
            continue
        g = nms.trim(f)
        g["properties"]["significance"] = s
        out.append(g)
    out.sort(key=lambda g: (nms.meta(g).get("issued") or "", nms.meta(g).get("number") or ""), reverse=True)
    out.sort(key=lambda g: g["properties"]["significance"]["tier"] != "significant")
    return out, tiers
