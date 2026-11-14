"""Government of Canada travel advice and advisories (Global Affairs Canada), from its open data index.

Source: https://data.international.gc.ca/travel-voyage/index-alpha-eng.json (JSON, no key), the dataset "Country
Travel Advice and Advisories" on open.canada.ca (bef2ebb3-ca9a-485f-aaff-5dc36eb89426, updated continually).
Licence: Open Government Licence - Canada. Checked live 14 Nov 2026: 230 places, keyed by ISO code (the Azores as
PT-20), each with `advisory-state` 0-3, the advisory in Canada's own words (`eng.advisory-text`, which also says
"with regional advisories"), `has-regional-advisory`, the publication time as a Unix `timestamp`, the kind of the latest
update (`recent-updates-type`: "Regular text update", "Editorial change", "Regional advisory modified", "National
advisory removed" ...) and Canada's own one-line note of it (`eng.recent-updates`). One file carries everything, so
one request a run.

Cordon reports Canada's levels in Canada's words. It does not rank them against the State Department's levels or the
UK's statements.
"""
import json
import re
from datetime import datetime, timezone

from .common import fetch_or_none, now_utc

SOURCE_URL = "https://data.international.gc.ca/travel-voyage/index-alpha-eng.json"
DATASET_URL = "https://open.canada.ca/data/en/dataset/bef2ebb3-ca9a-485f-aaff-5dc36eb89426"
PAGE_URL = "https://travel.gc.ca/destinations/{slug}"
SITE_URL = "https://travel.gc.ca/travelling/advisories"
MIN_COUNTRIES = 150  # Canada lists about 230; far fewer means a broken response
# Canada's four levels, in its own words (the index adds "(with regional advisories)" where it has them).
LEVELS = {0: "Exercise normal security precautions", 1: "Exercise a high degree of caution",
          2: "Avoid non-essential travel", 3: "Avoid all travel"}
# Canada's own statement that an advisory (national or regional) was issued, changed or removed: the update's kind
# ("Regional advisory modified", "National advisory removed" ...), or a note that starts with its risk level section.
# The note matters because the kind does not always say so: Mexico's update of 12 Nov 2026 removed a regional advisory
# ("Risk levels section - removed advisory to avoid non-essential travel to the west-central coast") under the kind
# "Regular text update".
ADVISORY_UPDATE = re.compile(r"advisory", re.I)
RISK_NOTE = re.compile(r"^Risk levels?\b", re.I)
# Updates that do not count as new: Canada's own "Editorial change", and a note about only the "Need help?" section
# (embassy and consulate contacts). On 13 Nov 2026 23 of 30 updates in 72 hours were "updated mission coordinates".
EDITORIAL = "Editorial change"
CONTACTS_ONLY = re.compile(r"^(The )?Need help\? section", re.I)
KEY_RE = re.compile(r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$")


def _utc(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def counts_as_new(rec: dict) -> bool:
    """An update worth listing as new (not editorial, not only the contacts section)."""
    note = rec.get("update") or ""
    return rec.get("update_type") != EDITORIAL and not (CONTACTS_ONLY.match(note) and ";" not in note)


def declares_change(rec: dict) -> bool:
    """Canada's own word that this update issued, changed or removed an advisory."""
    return bool(ADVISORY_UPDATE.search(rec.get("update_type") or "") or RISK_NOTE.match(rec.get("update") or ""))


def parse(doc) -> dict:
    """{key: {key, iso, name, level, advisory, regional, updated, update_type, update, link}} from the index."""
    rows = (doc or {}).get("data") if isinstance(doc, dict) else None
    if not isinstance(rows, dict):
        raise ValueError("no data in the index")
    out = {}
    for key, r in rows.items():
        r = r or {}
        key = str(r.get("country-iso") or key).strip().upper()
        level = r.get("advisory-state")
        if not KEY_RE.match(key) or level not in LEVELS:
            continue
        eng = r.get("eng") or {}
        slug = str(eng.get("url-slug") or "").strip()
        out[key] = {"key": key, "iso": key[:2], "name": (eng.get("name") or r.get("country-eng") or key).strip(),
                    "level": level, "advisory": (eng.get("advisory-text") or LEVELS[level]).strip(),
                    "regional": bool(r.get("has-regional-advisory")),
                    "updated": _utc((r.get("date-published") or {}).get("timestamp")),
                    "update_type": (r.get("recent-updates-type") or "").strip() or None,
                    "update": re.sub(r"\s+", " ", str(eng.get("recent-updates") or "")).strip()[:300] or None,
                    "link": PAGE_URL.format(slug=slug) if re.fullmatch(r"[a-z0-9-]+", slug) else SITE_URL}
    return out


def diff(old: dict, new: dict, when: str) -> list[dict]:
    """A level change, or regional advisories added or removed, against what Cordon held before."""
    out = []
    for key, rec in new.items():
        prev = old.get(key)
        if not prev:
            continue
        if prev.get("level") != rec["level"]:
            out.append({"at": when, "key": key, "iso": rec["iso"], "name": rec["name"], "link": rec["link"],
                        "kind": "level", "from": prev.get("level"), "to": rec["level"], "change": rec.get("update")})
        if bool(prev.get("regional")) != rec["regional"]:
            out.append({"at": when, "key": key, "iso": rec["iso"], "name": rec["name"], "link": rec["link"],
                        "kind": "regional", "from": bool(prev.get("regional")), "to": rec["regional"],
                        "change": rec.get("update")})
    return out


def collect(old: dict | None, when: str | None = None, fetch=fetch_or_none):
    """(countries, changes, generated, error). On error the caller keeps the old set."""
    when = when or now_utc()
    old = old or {}
    body, err = fetch(SOURCE_URL, 40)
    if body is None:
        return old, [], None, err
    try:
        doc = json.loads(body.decode("utf-8-sig"))
        new = parse(doc)
    except (ValueError, UnicodeDecodeError) as e:
        return old, [], None, f"unreadable: {type(e).__name__}"
    if len(new) < MIN_COUNTRIES:
        return old, [], None, f"only {len(new)} places listed"
    generated = _utc(((doc.get("metadata") or {}).get("generated") or {}).get("timestamp"))
    return dict(sorted(new.items())), diff(old, new, when), generated, None
