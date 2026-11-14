"""UK Foreign, Commonwealth & Development Office (FCDO) foreign travel advice, from the GOV.UK Content API.

Source: https://www.gov.uk/api/content/foreign-travel-advice (JSON, no key). Checked live 14 Nov 2026: 226 countries
and territories, each with `public_updated_at` and the FCDO's own one-line `change_description`. The index does not
carry the advice itself; each country's page (/api/content/foreign-travel-advice/<slug>) has `alert_status`, the list
of the FCDO's "advise against" statements in force (for Ukraine on 14 Nov: avoid_all_travel_to_parts and
avoid_all_but_essential_travel_to_parts). Licence: Open Government Licence v3.0.

A country page is read only when its `public_updated_at` differs from the one its status was last read for, so after
the first run Cordon asks for a handful of pages an hour, not 226. MAX_PAGES caps one run; a page that fails keeps
its last status and is asked for again next run.

Cordon reports the FCDO's statements as published and orders them only to pick a title (whole country before parts,
all travel before all but essential); it does not rank the FCDO against the State Department's levels.
"""
import json
import re
import time

from .common import fetch_or_none, load, now_utc, to_utc

SOURCE_URL = "https://www.gov.uk/api/content/foreign-travel-advice"
PAGE_URL = "https://www.gov.uk/foreign-travel-advice"
COUNTRY_API = SOURCE_URL + "/{slug}"
MAX_PAGES = 240  # one run; the first run reads every country once (about 226)
PAUSE_S = 0.1
MIN_COUNTRIES = 150  # the FCDO lists about 226; far fewer means a broken response
# The FCDO's statements, most severe first, in the words GOV.UK shows them.
ALERTS = {
    "avoid_all_travel_to_whole_country": "all travel to the whole country",
    "avoid_all_but_essential_travel_to_whole_country": "all but essential travel to the whole country",
    "avoid_all_travel_to_parts": "all travel to parts",
    "avoid_all_but_essential_travel_to_parts": "all but essential travel to parts",
}


def words(statuses) -> str:
    """'advises against all travel to parts and all but essential travel to parts', or 'no advice against travel'."""
    if statuses is None:
        return "advice status not yet read"
    s = sorted(statuses, key=lambda x: list(ALERTS).index(x) if x in ALERTS else len(ALERTS))
    if not s:
        return "no advice against travel"
    return "advises against " + " and ".join(ALERTS.get(x, x.replace("_", " ")) for x in s)


def iso_for(slug: str) -> str | None:
    return ((load("fcdo_iso.json", {}).get("codes") or {}).get(slug) or {}).get("iso")


def parse_index(doc) -> dict:
    """{slug: {slug, name, updated, change, link}} from the index document."""
    kids = ((doc or {}).get("links") or {}).get("children")
    if not isinstance(kids, list):
        raise ValueError("no children in the index")
    out = {}
    for k in kids:
        c = ((k or {}).get("details") or {}).get("country") or {}
        slug = c.get("slug") or (k.get("base_path") or "").rsplit("/", 1)[-1]
        if not slug or not re.fullmatch(r"[a-z0-9-]+", slug):
            continue
        out[slug] = {"slug": slug, "name": (c.get("name") or k.get("title") or slug).strip(),
                     "updated": to_utc(k.get("public_updated_at") or ""),
                     "change": re.sub(r"\s+", " ", ((k.get("details") or {}).get("change_description") or "")).strip()[:300],
                     "link": k.get("web_url") or f"{PAGE_URL}/{slug}"}
    return out


def parse_country(doc) -> list[str]:
    """The alert_status list from a country page (empty when the FCDO advises against no travel)."""
    st = ((doc or {}).get("details") or {}).get("alert_status")
    if st is None:
        st = []
    if not isinstance(st, list) or not all(isinstance(x, str) for x in st):
        raise ValueError("alert_status is not a list of strings")
    return sorted(set(st))


def diff(old: dict, new: dict, when: str) -> list[dict]:
    """A change of the FCDO's statements, where both the old and new statuses were read."""
    out = []
    for slug, rec in new.items():
        prev = old.get(slug) or {}
        if prev.get("alert_status") is None or rec.get("alert_status") is None:
            continue
        if prev["alert_status"] != rec["alert_status"]:
            out.append({"at": when, "key": slug, "iso": rec.get("iso"), "name": rec["name"], "link": rec["link"],
                        "kind": "alert", "from": prev["alert_status"], "to": rec["alert_status"],
                        "change": rec.get("change")})
    return out


def collect(old: dict | None, when: str | None = None, fetch=fetch_or_none, pause: float = PAUSE_S):
    """(countries, changes, error, pages_read, pages_failed). On error the caller keeps the old set."""
    when = when or now_utc()
    old = old or {}
    body, err = fetch(SOURCE_URL, 40)
    if body is None:
        return old, [], err, 0, 0
    try:
        new = parse_index(json.loads(body.decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as e:
        return old, [], f"unreadable: {type(e).__name__}", 0, 0
    if len(new) < MIN_COUNTRIES:
        return old, [], f"only {len(new)} countries listed", 0, 0
    read = failed = 0
    for slug, rec in new.items():
        prev = old.get(slug) or {}
        rec["iso"] = iso_for(slug)
        rec["alert_status"] = prev.get("alert_status")
        rec["status_for"] = prev.get("status_for")
        if rec["alert_status"] is not None and rec["status_for"] == rec["updated"]:
            continue
        if read + failed >= MAX_PAGES:
            continue
        page, perr = fetch(COUNTRY_API.format(slug=slug), 30)
        if pause:
            time.sleep(pause)
        try:
            if page is None:
                raise ValueError(perr)
            rec["alert_status"] = parse_country(json.loads(page.decode("utf-8")))
            rec["status_for"] = rec["updated"]
            read += 1
        except (ValueError, UnicodeDecodeError):
            failed += 1  # keeps the last status read; asked for again next run
    return dict(sorted(new.items())), diff(old, new, when), None, read, failed
