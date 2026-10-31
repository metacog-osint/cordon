"""EASA Conflict Zone Information Bulletins, from EASA's CSV export of the CZIB table.

Each bulletin has a number with its revision ("CZIB-2026-04-R2"), dates as dd/mm/yyyy, a status (Active or
Withdrawn) and the affected countries as names. EASA content may be reused with acknowledgement of the source.
"""
import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path

from .common import fetch_or_none, now_utc  # first: puts the doctrine kit on sys.path
from tic_doctrine import geo  # noqa: E402

SOURCE_URL = "https://www.easa.europa.eu/en/domains/air-operations/czibs/export?page=&_format=csv"
PAGE_URL = "https://www.easa.europa.eu/en/domains/air-operations/czibs"
ALIAS = {"democratic people's republic of korea": "KP", "north korea": "KP", "south sudan": "SS",
         "russia": "RU", "russian federation": "RU", "united arab emirates": "AE", "iran": "IR", "syria": "SY",
         "democratic republic of the congo": "CD", "palestine": "PS", "uae": "AE"}


def _date(v: str) -> str | None:
    v = (v or "").strip()
    try:
        return datetime.strptime(v, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def country_codes(names: str) -> list[str]:
    """'Bahrain, Kuwait, Qatar' -> ['BH', 'KW', 'QA'] via the kit's country names plus aliases."""
    out = []
    for n in re.split(r",|\band\b", names or ""):
        n = n.strip().strip(".").lower()
        if not n:
            continue
        cc = ALIAS.get(n) or _name_index().get(n)
        if cc and cc not in out:
            out.append(cc)
    return out


_INDEX = None


def _name_index() -> dict:
    """Lower-case Natural Earth country name -> ISO code, from the kit's geo/countries.json."""
    global _INDEX
    if _INDEX is None:
        p = Path(geo.__file__).resolve().parents[2] / "geo" / "countries.json"
        _INDEX = {c["name"].lower(): c["cc"] for c in json.loads(p.read_text(encoding="utf-8"))["countries"]
                  if c.get("name")}
    return _INDEX


def base_number(number: str) -> str:
    """'CZIB-2026-04-R2' -> 'CZIB-2026-04'; '2025-01 R3' -> 'CZIB-2025-01'; 'CZIB-2017-03R20' -> 'CZIB-2017-03'."""
    m = re.search(r"(\d{4})-(\d{2})", number or "")
    return f"CZIB-{m.group(1)}-{m.group(2)}" if m else (number or "").strip()


def parse(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    out = []
    for r in rows:
        number = (r.get("CZIB number") or "").strip()
        if not number:
            continue
        out.append({
            "number": re.sub(r"\s+", " ", number), "id": base_number(number),
            "subject": re.sub(r"\s+", " ", (r.get("Subject") or "").strip()),
            "status": (r.get("Status") or "").strip().lower(),
            "issued": _date(r.get("Issue date")), "valid_until": _date(r.get("Valid until")),
            "revision": re.sub(r"\s+", " ", (r.get("Revision") or "").strip())[:300],
            "airspace": re.sub(r"\s+", " ", (r.get("Affected Airspace") or "").strip())[:300],
            "countries": country_codes(r.get("Affected Country") or ""),
            "recommendation": re.sub(r"\s+", " ", (r.get("Recommendation(s)") or "").strip())[:500],
        })
    return out


def diff(old: list[dict], new: list[dict], when: str) -> list[dict]:
    """Renewals (new revision or later validity), status changes and new bulletins."""
    before = {b["id"]: b for b in old}
    changes = []
    for b in new:
        p = before.get(b["id"])
        base = {"at": when, "id": b["id"], "number": b["number"], "subject": b["subject"]}
        if p is None:
            if old:
                changes.append({**base, "kind": "new", "status": b["status"], "valid_until": b["valid_until"]})
        elif p["status"] != b["status"]:
            changes.append({**base, "kind": "status", "from": p["status"], "to": b["status"]})
        elif p["number"] != b["number"] or p["valid_until"] != b["valid_until"]:
            changes.append({**base, "kind": "revised", "from": [p["number"], p["valid_until"]],
                            "to": [b["number"], b["valid_until"]]})
    return changes


def collect(old: list[dict] | None, when: str | None = None, fetch=fetch_or_none):
    when = when or now_utc()
    body, err = fetch(SOURCE_URL, 40)
    if body is None:
        return old or [], [], err
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("cp1252", "replace")  # EASA's CSV says UTF-8 but carries Windows-1252 dashes
    new = parse(text)
    if len(new) < 5:
        return old or [], [], f"only {len(new)} bulletins parsed"
    return new, diff(old or [], new, when), None
