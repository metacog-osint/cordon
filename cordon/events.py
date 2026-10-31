"""Dated events for Verdict's calendar (site/data/events.json): when each active EASA bulletin expires unless
renewed, and what State changed in the last 30 days (advisory levels and embassy departure status).

Shaped like Verdict's calendar/events.json entries, with origin "cordon" and a ref (the bulletin's base number,
e.g. CZIB-2026-04) so Verdict can link each event to the forecasts that name it.
"""
from datetime import datetime, timedelta, timezone

EASA_PAGE = "https://www.easa.europa.eu/en/domains/air-operations/czibs"
POSTURE_WORDS = {"normal": "normal operations", "authorized_departure": "authorized departure",
                 "ordered_departure": "ordered departure", "suspended_operations": "suspended operations"}
RECENT_DAYS = 30


def build(czibs: list[dict], changes: list[dict], now: datetime | None = None) -> dict:
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
    for c in changes:
        if c.get("lane") != "state" or c.get("kind") not in ("level", "posture") or c.get("at", "") < cutoff:
            continue
        if c["kind"] == "level":
            what = f"US travel advisory raised from level {c['from']} to {c['to']}" if (c["to"] or 0) > (c["from"] or 0) \
                else f"US travel advisory lowered from level {c['from']} to {c['to']}"
        else:
            what = (f"US embassy status changed from {POSTURE_WORDS.get(c['from'], c['from'])} to "
                    f"{POSTURE_WORDS.get(c['to'], c['to'])} (read from the advisory text; under review)")
        out.append({
            "id": f"{c['at'][:10]}-state-{c['key'].lower()}-{c['kind']}", "date": c["at"][:10],
            "title": f"{c['name']}: {what}", "kind": "advisory_change", "occurred": True,
            "countries": [c["iso"]] if c.get("iso") else [], "origin": "cordon", "ref": c["key"],
            "source": {"publisher": "US Department of State", "url": c.get("link"),
                       "descriptor": "Travel advisory change detected by Cordon"},
        })
    out.sort(key=lambda e: (e["date"], e["id"]))
    return {"source": "cordon", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "about": "Dated events for Verdict's calendar, from Cordon (https://metacog-osint.github.io/cordon/)",
            "events": out}
