"""Dated events for Verdict's calendar (site/data/events.json): when each active EASA bulletin expires unless
renewed, and what changed in the last 30 days in the travel advice Cordon reads: State's advisory levels and embassy
departure status, the UK FCDO's advise-against statements, Canada's and New Zealand's levels and regional advice,
CDC's travel health notices (issued, level changed, removed), and the FAA's SFARs and KICZ NOTAMs for foreign
airspace (listed, withdrawn).

Shaped like Verdict's calendar/events.json entries, with origin "cordon" and a ref (the bulletin's base number,
e.g. CZIB-2026-04, or the lane's own key) so Verdict can link each event to the forecasts that name it.

A change is one Cordon saw between two of its own reads (data/changes.jsonl), dated the day Cordon saw it; two of
one kind for one place on one day are one event, the later. Canada also says in its own update notes when it
issued, changed or removed an advisory. Such an update in the last 30 days is an event too, dated by Canada, when
the note names the advisory (canada.names_advisory_change; Tom, 15 Nov 2026) and no change Cordon saw for that
place within COVER_DAYS after it already stands for it. Cordon holds only Canada's latest update per place, so one
replaced before Verdict's daily sync is missed.
"""
import re
from datetime import datetime, timedelta, timezone

from . import canada as ca, cdc, fcdo, japan, netherlands, safetravel
from .feed import (CANADA_SRC, CDC_SRC, FAAPRN_SRC, FCDO_SRC, JAPAN_SRC, NL_SRC, SAFETRAVEL_SRC, STATE_SRC)

EASA_PAGE = "https://www.easa.europa.eu/en/domains/air-operations/czibs"
POSTURE_WORDS = {"normal": "normal operations", "authorized_departure": "authorized departure",
                 "ordered_departure": "ordered departure", "suspended_operations": "suspended operations",
                 "no_post": "no US embassy"}
RECENT_DAYS = 30
COVER_DAYS = 2  # a Canada change Cordon saw within this long after Canada's own update is that update
# The change kinds each lane turns into events (State's text-only edits, new and removed advisories stay out).
KINDS = {"state": {"level", "posture"}, "fcdo": {"alert"}, "canada": {"level", "regional"},
         "safetravel": {"level", "regional"}, "japan": {"level", "regional"},
         "netherlands": {"level", "regional"}, "cdc": {"new", "level", "removed"}, "faaprn": {"new", "removed"}}
PUBLISHERS = {"state": STATE_SRC["publisher"], "fcdo": FCDO_SRC["publisher"], "canada": CANADA_SRC["publisher"],
              "safetravel": SAFETRAVEL_SRC["publisher"], "cdc": CDC_SRC["publisher"],
              "faaprn": FAAPRN_SRC["publisher"], "japan": JAPAN_SRC["publisher"],
              "netherlands": NL_SRC["publisher"]}


def _slug(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(key).lower()).strip("-")


def _moved(a, b, order=None) -> str:
    """'raised' or 'lowered' (order: the levels from least to most severe; numbers otherwise)."""
    if order:
        a, b = (order.index(x) if x in order else -1 for x in (a, b))
    return "raised" if (b or 0) > (a or 0) else "lowered"


def _what(c: dict) -> str:
    lane, kind, a, b = c["lane"], c["kind"], c.get("from"), c.get("to")
    if lane == "state":
        if kind == "level":
            return f"US travel advisory {_moved(a, b)} from level {a} to {b}"
        return (f"US embassy status changed from {POSTURE_WORDS.get(a, a)} to {POSTURE_WORDS.get(b, b)} "
                "(read from the advisory text; under review)")
    if lane == "fcdo":
        return f'UK FCDO advice changed from "{fcdo.words(a)}" to "{fcdo.words(b)}"'
    if lane == "canada":
        if kind == "level":
            out = (f'Canada\'s travel advisory {_moved(a, b)} from "{ca.LEVELS.get(a, a)}" to '
                   f'"{ca.LEVELS.get(b, b)}"')
        else:
            out = "Canada added regional advisories" if b else "Canada removed its regional advisories"
        note = ca.first_note({"update": c.get("change")})
        return out + (f" (Canada's note: {note})" if note else "")
    if lane == "safetravel":
        if kind == "level":
            return (f'New Zealand SafeTravel advice {_moved(a, b, safetravel.ORDER)} from '
                    f'"{safetravel.LEVELS.get(a, a)}" to "{safetravel.LEVELS.get(b, b)}"')
        if not a:
            return f'New Zealand SafeTravel added a note on other levels in some areas: "{b}"'
        if not b:
            return f'New Zealand SafeTravel removed its note on other levels in some areas (was: "{a}")'
        return f'New Zealand SafeTravel reworded its note on other levels in some areas: "{b}"'
    if lane == "japan":
        if kind == "level":
            return (f"Japan's danger level {_moved(a, b)} from "
                    f'"{japan.LEVELS.get(a, "no danger level in force")}" to "{japan.LEVELS.get(b, "no danger level in force")}"')
        return (f"Japan changed the danger levels in force in some areas (levels {', '.join(map(str, a or [])) or 'none'}"
                f" to {', '.join(map(str, b or [])) or 'none'})")
    if lane == "netherlands":
        if kind == "level":
            return (f'Netherlands travel advice {_moved(a, b, netherlands.ORDER)} from '
                    f'"{netherlands.LEVELS.get(a, a)}" to "{netherlands.LEVELS.get(b, b)}"')
        return (f"Netherlands changed the colours in force in some areas ({', '.join(netherlands.COLOURS_EN.get(c, c) for c in a or [])}"
                f" to {', '.join(netherlands.COLOURS_EN.get(c, c) for c in b or [])})")
    if lane == "faaprn":
        what = "listed" if kind == "new" else "withdrew"
        return f"FAA {what} {c.get('label') or c['key']} ({c.get('entry_kind') or 'notice'}) for US operators"
    # cdc
    if kind == "new":
        return f"CDC issued a level {b} travel health notice ({cdc.LEVELS.get(b, b)})"
    if kind == "removed":
        return f"CDC removed its level {a} travel health notice"
    return f"CDC travel health notice {_moved(a, b)} from level {a} to level {b} ({cdc.LEVELS.get(b, b)})"


def _change_event(c: dict) -> dict:
    countries = c.get("countries") if c["lane"] == "cdc" else ([c["iso"]] if c.get("iso") else [])
    if c["lane"] == "faaprn":  # the FAA's page, at the section; the entry's own document is in the descriptor
        c = {**c, "link": c.get("link") or FAAPRN_SRC["url"]}
    return {
        "id": f"{c['at'][:10]}-{c['lane']}-{_slug(c['key'])}-{c['kind']}", "date": c["at"][:10],
        "title": f"{c['name']}: {_what(c)}", "kind": "advisory_change", "occurred": True,
        "countries": list(countries or []), "origin": "cordon", "ref": c["key"],
        "source": {"publisher": PUBLISHERS[c["lane"]], "url": c.get("link"),
                   "descriptor": "Travel advisory change detected by Cordon" if c["lane"] == "state"
                   else "Change detected by Cordon between two of its reads"},
    }


def _canada_declared(places: dict, changes: list[dict], cutoff: str) -> list[dict]:
    """Canada's own updates in the window that name an advisory change, unless a change Cordon saw covers them."""
    seen = {}
    for c in changes:
        if c.get("lane") == "canada" and c.get("kind") in KINDS["canada"]:
            seen.setdefault(c["key"], []).append(c["at"])
    out = []
    for key, rec in sorted((places or {}).items()):
        when = rec.get("updated") or ""
        if when < cutoff or not ca.names_advisory_change(rec):
            continue
        until = (datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ") + timedelta(days=COVER_DAYS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        if any(when <= at <= until for at in seen.get(key, [])):
            continue
        kind = rec.get("update_type") or ""
        said = f", {kind}" if ca.ADVISORY_UPDATE.search(kind) else ""
        out.append({
            "id": f"{when[:10]}-canada-{_slug(key)}-update", "date": when[:10],
            "title": f"{rec['name']}: Canada's travel advice{said}: {ca.first_note(rec)}", "kind": "advisory_change",
            "occurred": True, "countries": [rec["iso"]] if rec.get("iso") else [], "origin": "cordon", "ref": key,
            "source": {"publisher": PUBLISHERS["canada"], "url": rec.get("link"),
                       "descriptor": f"Canada's own update note of {when} (read by Cordon)"},
        })
    return out


def build(czibs: list[dict], changes: list[dict], now: datetime | None = None, canada: dict | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    cutoff = (now - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for b in czibs:
        if b.get("status") != "active" or not b.get("valid_until") or b["valid_until"] < today:
            continue
        area = b["subject"][0].lower() + b["subject"][1:] if b.get("subject") else b["id"]
        out.append({
            "id": f"{b['valid_until']}-easa-{b['id'].lower()}", "date": b["valid_until"],
            "title": f"EASA conflict-zone bulletin {b['number']} ({area}) expires unless renewed",
            "kind": "bulletin_expiry", "countries": b.get("countries", []), "origin": "cordon", "ref": b["id"],
            "source": {"publisher": "EASA", "url": EASA_PAGE,
                       "descriptor": f"{b['number']}, valid until {b['valid_until']} (read by Cordon)"},
        })
    recent = [c for c in changes if c.get("kind") in KINDS.get(c.get("lane"), ()) and c.get("at", "") >= cutoff]
    by_id = {}
    for c in recent:  # changes.jsonl is in time order, so the later of two on one day wins
        e = _change_event(c)
        by_id[e["id"]] = e
    out += list(by_id.values()) + _canada_declared(canada, recent, cutoff)
    out.sort(key=lambda e: (e["date"], e["id"]))
    return {"source": "cordon", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "about": "Dated events for Verdict's calendar, from Cordon (https://cordon.theintelligence.company/)",
            "events": out}
