"""Cordon's feed in contract v2 (tic-feed/2) and the compact data the map page reads.

Every item is a measurement (kind observation): what an authority has published, with its own ladder value as
response_stage. A change in the last 30 days (a level raised or lowered, a departure order) is an anomaly against the
previous value. Each item is checked with the doctrine kit's linter; a failing item is dropped and listed.
"""
from datetime import datetime, timedelta, timezone

from . import faa, navarea
from .common import ROOT, digest, load, point, read_jsonl, to_utc  # first: puts the doctrine kit on sys.path
from tic_doctrine import CONTRACT, contract, registers, vocab  # noqa: E402

SITE = "https://cordon.theintelligence.company/"
METHOD = "cordon-feed-1.0"
RECENT_DAYS = 30
STALE_HOURS = 48  # a source with no good fetch for this long is stale, whatever it last said
NEW_HOURS = 72  # a navigational warning issued within this long is new
# A new warning of these kinds is an anomaly, not routine (launch and military added by Tom, 13 Nov 2026).
NEW_ALERT = {"security", "mines", "piracy", "gnss", "launch", "military"}
HAND_POINT = {"PS-GZ": [34.38, 31.42], "PS-WB": [35.25, 31.95]}  # [lon, lat], as Watchfloor places them
NOTABLE = {"launch", "gnss", "military", "mines", "piracy", "security", "ice", "restricted_area", "search_and_rescue", "pollution",
           "port", "cable_pipeline", "wreck", "hazard", "underwater_ops"}
STATE_SRC = {"id": "state-travel-advisories", "publisher": "US Department of State", "licence":
             "US public domain (seals and logos restricted)", "grade": "A1", "independence_group": "us-state-department",
             "source_type": "official notice", "descriptor": "Official travel advisory (travel.state.gov)"}
EASA_SRC = {"id": "easa-czib", "publisher": "European Union Aviation Safety Agency (EASA)",
            "url": "https://www.easa.europa.eu/en/domains/air-operations/czibs",
            "licence": "EASA content, reusable with acknowledgement", "grade": "A1", "independence_group": "easa",
            "source_type": "official notice", "descriptor": "Conflict Zone Information Bulletin"}
NGA_SRC = {"id": "nga-navwarnings", "publisher": "US National Geospatial-Intelligence Agency (NGA)",
           "url": "https://msi.nga.mil/NavWarnings", "licence": "US public domain", "grade": "A1",
           "independence_group": "nga", "source_type": "official notice",
           "descriptor": "Navigational warning broadcast (NAVAREA IV/XII, HYDROLANT, HYDROPAC, HYDROARC)"}
EMBASSY_SRC = {"publisher": "US Department of State (embassy)", "licence": "US public domain", "grade": "A1",
               "independence_group": "us-state-department", "source_type": "official notice",
               "descriptor": "US embassy alert"}
FAA_SRC = {"id": "faa-nas-status", "publisher": "US Federal Aviation Administration (FAA), ATC System Command Center",
           "url": faa.PAGE_URL, "licence": "US Government work, not subject to US copyright (17 U.S.C. 105); "
           "the FAA states no licence on nasstatus", "grade": "A1", "independence_group": "faa",
           "source_type": "official notice", "descriptor": "National Airspace System status: airport events "
           "(ground stops, ground delay programs, closures)"}
FAA_WORDS = {"ground_stop": "ground stop", "ground_delay": "ground delay program", "closure": "airport closure"}
STALE_BY_SOURCE = {FAA_SRC["id"]: faa.STALE_HOURS}
POSTURE_WORDS = {"authorized_departure": "authorized departure", "ordered_departure": "ordered departure",
                 "suspended_operations": "suspended operations"}
nga_time = navarea.issued_time


def source_health(health: dict | None, nav: dict, now: datetime) -> dict:
    """The feed's health block: one entry per source, with a state a reader can act on.

    fresh    the latest attempt worked
    failing  the latest attempt failed; the last good fetch is under STALE_HOURS old, so the data still stand
    stale    no good fetch for STALE_HOURS (FAA: faa.STALE_HOURS) or more; or, for NGA, the newest warning held is over
             navarea.STALE_DAYS old (NGA issues warnings daily, so that is a frozen list, never a quiet sea)
    never    no good fetch on record
    A stale or never source has its items withheld from the feed (counted in `withheld`): it reads as no data."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {}
    for sid, h in sorted((health or {}).items()):
        cutoff = (now - timedelta(hours=STALE_BY_SOURCE.get(sid, STALE_HOURS))).strftime("%Y-%m-%dT%H:%M:%SZ")
        last_ok = h.get("last_ok")
        state = ("never" if not last_ok else "stale" if last_ok < cutoff
                 else "failing" if h.get("failures") else "fresh")
        out[sid] = {"state": state, "last_ok": last_ok, "last_error": h.get("last_error"),
                    "failures": h.get("failures", 0), "checked_at": h.get("checked_at"), "detail": h.get("detail")}
    held = nav.get("warnings") or []
    if held or NGA_SRC["id"] in out:
        e = out.setdefault(NGA_SRC["id"], {"state": "fresh"})
        e["newest_item"] = navarea.newest(held)
        if held and e["state"] in ("fresh", "failing") and navarea.is_stale(e["newest_item"], stamp):
            e["state"] = "stale"
    return out


_FIPS_POINTS = None


def _pt(key: str, iso: str):
    """A point for a country: hand placements, then the kit's label points, then the label points carried in
    data/fips_iso.json (Taiwan, for one). None for places drawn inside another country (France's overseas regions)."""
    global _FIPS_POINTS
    if key in HAND_POINT:
        return {"type": "Point", "coordinates": HAND_POINT[key]}
    p = point(iso) if iso else None
    if p:
        return p
    if _FIPS_POINTS is None:
        _FIPS_POINTS = {c["iso"]: c["point"] for c in (load("fips_iso.json", {}).get("codes") or {}).values()
                        if c.get("iso") and c.get("point")}
    q = _FIPS_POINTS.get(iso)
    return {"type": "Point", "coordinates": [q[1], q[0]]} if q else None


def _place(feature: dict, link: str) -> dict:
    """With no point, the item still needs a visual: the source's own page."""
    if feature["geometry"] is None:
        feature["properties"]["visual"] = {"type": "page", "url": link}
    return feature


def _base(fetched: str) -> dict:
    return {"contract": CONTRACT, "program": "cordon", "kind": "observation", "status": "actual", "msg_type": "new",
            "human_review": "none", "us_person_data": "none", "status_class": "reported", "method_version": METHOD,
            "product_category": "current", "published_at": fetched}


def recent_changes(now: datetime) -> list[dict]:
    cutoff = (now - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [c for c in read_jsonl("changes.jsonl") if c.get("at", "") >= cutoff]


def faa_items(nas: dict, state: str, now: datetime, counts_rows: list[dict]) -> list[dict]:
    """FAA programs as items, placed at the FAA's own airport coordinates. See cordon/faa.py for the tiers."""
    fetched = nas.get("fetched_at") or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    progs = faa.in_effect(nas.get("programs") or [], now, state == "fresh")
    places = nas.get("airports") or {}
    base = faa.baseline(counts_rows, now)
    stops = sum(1 for p in progs if p["kind"] == "ground_stop")
    many = stops >= base["threshold"]
    out = []
    for p in progs:
        apt, kind = p["airport"], p["kind"]
        where = places.get(apt)
        name = p.get("airport_name") or (where[2] if where and len(where) > 2 else "")
        label = f"{apt} ({name})" if name else apt
        wide = faa.wide_scope(apt)
        if kind == "closure":
            title = f"FAA lists {label} as closed: {p.get('notam') or 'no text given'}"
        else:
            title = f"FAA {FAA_WORDS[kind]}: {label}; reason as listed: {p.get('reason') or 'none given'}"
            if kind == "ground_delay" and p.get("avg_delay_min") is not None:
                title += f"; average delay {int(p['avg_delay_min'])} min"
        anomaly = kind == "ground_stop" and (many or wide)
        start = (p.get("start") or "").replace("-", "").replace(":", "")[:13]
        props = {**_base(fetched), "id": f"cordon:faa:{kind}:{apt}:{start or 'open'}", "title": title,
                 "tier": "anomaly" if anomaly else "routine", "data_as_of": p.get("updated") or fetched,
                 "countries": faa.country(apt, where), "precision_class": "point" if where else "none",
                 "ncf": ["transport_by_air"], "sector": vocab.derive_sectors(["transport_by_air"]),
                 "requirement_ids": ["CD-PIR-5"], "ie_aspect": ["physical"], "pmesii_pt": ["infrastructure"],
                 "ascope": ["structures", "events"], "sources": [{**FAA_SRC, "accessed_at": fetched}],
                 "link": faa.PAGE_URL,
                 "measures": {"program": kind, "airport": apt, "airport_name": name or None,
                              **{k: v for k, v in p.items() if k not in ("kind", "airport", "airport_name", "updated")
                                 and v is not None}}}
        if p.get("end"):
            props["valid_until"] = p["end"]
        if kind == "ground_stop":
            props["measures"].update({"ground_stops_in_effect": stops, "unusual_at": base["threshold"],
                                      "baseline_basis": base["basis"], "baseline_samples": base["samples"]})
        if anomaly:
            props["baseline_ref"] = (
                {"id": "faa-concurrent-ground-stops", "type": "rolling", "version": "1",
                 "window": f"ground stops in effect at once, Cordon's own counts over {faa.BASELINE_DAYS} days "
                           f"(unusual at {base['threshold']} or more; {base['basis']}, {base['samples']} counts)"}
                if many else {"id": "faa-ground-stop-scope", "type": "fixed", "version": "1",
                              "window": "a ground stop listed against a center or the whole system, not one airport"})
        if not where and not wide:
            props["visual"] = {"type": "page", "url": faa.PAGE_URL}
        geom = {"type": "Point", "coordinates": where[:2]} if where else None
        if geom is None and wide:
            geom = point("US")
            props["precision_class"] = "country"
        out.append({"type": "Feature", "geometry": geom, "properties": props})
    return out


def build(adv: dict, alerts: dict, czibs: dict, nav: dict, now: datetime | None = None,
          health: dict | None = None, nas: dict | None = None, faa_counts: list[dict] | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    src_health = source_health(health, nav, now)
    nga = src_health.get(NGA_SRC["id"]) or {}
    if nga.get("state") in ("stale", "never"):
        nga["withheld"] = sum(1 for w in nav.get("warnings") or [] if w["category"] in NOTABLE)
        nav = {**nav, "warnings": []}
    fetched = adv.get("fetched_at") or now.strftime("%Y-%m-%dT%H:%M:%SZ")
    changes = recent_changes(now)
    last_level = {c["key"]: c for c in changes if c.get("lane") == "state" and c["kind"] == "level"}
    last_posture = {c["key"]: c for c in changes if c.get("lane") == "state" and c["kind"] == "posture"}
    feats = []

    for key, r in sorted((adv.get("advisories") or {}).items()):
        ch = last_level.get(key)
        props = {**_base(fetched), "id": f"cordon:advisory:{key}", "title": f"{r['name']}: Level {r['level']}, "
                 f"{r['level_text']}", "tier": "anomaly" if ch else "routine",
                 "data_as_of": to_utc(r.get("updated")) or fetched, "countries": [r["iso"]] if r["iso"] else [],
                 "response_stage": f"state_travel_advisory:level_{r['level']}", "precision_class": "country",
                 "requirement_ids": ["CD-PIR-1"], "ie_aspect": ["informational"], "pmesii_pt": ["political"],
                 "ascope": ["areas"], "sources": [{**STATE_SRC, "url": r["link"], "accessed_at": fetched}],
                 "link": r["link"], "measures": {"level": r["level"], "posture": r["posture"]["state"]}}
        if ch:
            props.update({"baseline_ref": {"id": "previous-advisory-level", "window": "the advisory's previous level",
                                           "type": "fixed", "version": "1"},
                          "measures": {**props["measures"], "changed_at": ch["at"], "from_level": ch["from"]}})
        feats.append(_place({"type": "Feature", "geometry": _pt(key, r["iso"]), "properties": props}, r["link"]))
        if r["posture"]["state"] != "normal":
            pc = last_posture.get(key)
            word = POSTURE_WORDS[r["posture"]["state"]]
            pp = {**_base(fetched), "id": f"cordon:posture:{key}", "title": f"{r['name']}: US embassy on {word}"
                  if r["posture"]["state"] != "suspended_operations" else f"{r['name']}: US embassy has suspended operations",
                  "tier": "anomaly" if pc else "routine", "data_as_of": to_utc(r.get("updated")) or fetched,
                  "countries": [r["iso"]] if r["iso"] else [],
                  "response_stage": f"state_post_posture:{r['posture']['state']}", "precision_class": "country",
                  "requirement_ids": ["CD-PIR-2"], "ie_aspect": ["informational"], "pmesii_pt": ["political"],
                  "ascope": ["organizations"], "sources": [{**STATE_SRC, "url": r["link"], "accessed_at": fetched}],
                  "link": r["link"], "measures": {"sentence": r["posture"]["sentence"],
                                                  "read_from_text": True, "needs_review": bool(pc)}}
            if pc:
                pp["baseline_ref"] = {"id": "previous-post-posture", "window": "the post's previous status",
                                      "type": "fixed", "version": "1"}
                pp["warning_problem_id"] = "CD-WP-1"
                pp.update({"indicator_id": "CD-IND-1", "hypothesis_id": "CD-WP-1-H1", "direction": "neutral",
                           "indicator_state": "present"})
            feats.append(_place({"type": "Feature", "geometry": _pt(key, r["iso"]), "properties": pp}, r["link"]))

    cz_fetched = czibs.get("fetched_at") or fetched
    for b in czibs.get("bulletins") or []:
        if b["status"] != "active":
            continue
        pts = [p["coordinates"] for p in (point(c) for c in b["countries"]) if p]
        props = {**_base(cz_fetched), "id": f"cordon:czib:{b['id']}", "title": f"EASA {b['number']}: {b['subject']}",
                 "tier": "routine", "data_as_of": f"{b['issued']}T00:00:00Z" if b.get("issued") else cz_fetched,
                 "valid_until": f"{b['valid_until']}T23:59:00Z" if b.get("valid_until") else None,
                 "countries": b["countries"], "response_stage": "easa_czib:active", "precision_class": "country",
                 "ncf": ["transport_by_air"], "sector": vocab.derive_sectors(["transport_by_air"]),
                 "requirement_ids": ["CD-PIR-3"], "ie_aspect": ["physical"], "pmesii_pt": ["military", "infrastructure"],
                 "ascope": ["areas"], "sources": [{**EASA_SRC, "accessed_at": cz_fetched}],
                 "measures": {"airspace": b["airspace"], "recommendation": b["recommendation"], "revision": b["revision"]}}
        if not props["valid_until"]:
            props.pop("valid_until")
        geom = {"type": "MultiPoint", "coordinates": pts} if len(pts) > 1 else ({"type": "Point", "coordinates": pts[0]}
                                                                                if pts else None)
        if geom is None:
            props.update({"precision_class": "none", "visual": {"type": "page", "url": EASA_SRC["url"]}})
        feats.append({"type": "Feature", "geometry": geom, "properties": props})

    nv_fetched = nav.get("fetched_at") or fetched
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    new_from = (now - timedelta(hours=NEW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    expired = 0
    for w in nav.get("warnings") or []:
        if w["category"] not in NOTABLE:
            continue
        if not navarea.in_force(w, stamp):
            expired += 1  # past its own "cancel this msg" time, though still on NGA's daily list
            continue
        g = w.get("geometry")
        issued = nga_time(w.get("issued"))
        is_new = bool(issued and issued >= new_from)
        alert = is_new and w["category"] in NEW_ALERT
        ncf = ["transport_by_vessel"] + (["provide_pnt"] if w["category"] == "gnss" else [])
        props = {**_base(nv_fetched), "id": f"cordon:navwarn:{w['id']}", "title": f"{w['number']}: {w['headline']}",
                 "tier": "anomaly" if alert else "routine", "data_as_of": issued or nv_fetched, "countries": [],
                 "precision_class": {"Point": "point", "Polygon": "area", "MultiPolygon": "area"}.get(
                     (g or {}).get("type"), "approximate")
                 if g else "none", "ncf": ncf, "sector": vocab.derive_sectors(ncf), "requirement_ids": ["CD-PIR-4"],
                 "ie_aspect": ["physical"], "pmesii_pt": ["infrastructure"], "ascope": ["areas"],
                 "sources": [{**NGA_SRC, "accessed_at": nv_fetched}],
                 "measures": {"category": w["category"], "sea": w.get("sea"), "place": w.get("place"),
                              "authority": w.get("authority"), "text": w["text"], "new": is_new}}
        if w.get("cancel_at"):
            props["valid_until"] = w["cancel_at"]
        if alert:
            props["baseline_ref"] = {"id": "nga-warnings-in-force", "type": "rolling", "version": "1",
                                     "window": f"the warnings in force {NEW_HOURS} hours earlier"}
        if not g:
            props["visual"] = {"type": "page", "url": NGA_SRC["url"]}
        feats.append({"type": "Feature", "geometry": g, "properties": props})

    if expired:
        nga["expired"] = expired

    al_fetched = alerts.get("fetched_at") or fetched
    for iso, items in sorted((alerts.get("posts") or {}).items()):
        for a in items:
            src = {**EMBASSY_SRC, "id": f"usembassy-{iso.lower()}", "url": a["link"], "accessed_at": al_fetched}
            if a.get("via") == "google-news":
                # The link is a Google News redirect: cite the post's own alerts page, and say how it was found.
                src.update({"url": a.get("post_url") or a["link"],
                            "descriptor": "US embassy alert; title and date from a Google News search of the post's "
                                          "site, because the post's own alert feed did not answer"})
            props = {**_base(al_fetched), "id": f"cordon:alert:{iso}:{digest(a['link'])[7:19]}",
                     "title": f"US embassy ({iso}): {a['title']}", "tier": "routine",
                     "data_as_of": a.get("published_at") or al_fetched, "countries": [iso], "precision_class": "country",
                     "requirement_ids": ["CD-PIR-2"], "ie_aspect": ["informational"], "pmesii_pt": ["social"],
                     "ascope": ["events"], "sources": [src],
                     "link": a["link"], "measures": {"type": a.get("type")}}
            feats.append({"type": "Feature", "geometry": point(iso), "properties": props})

    if nas is not None:
        fa = src_health.setdefault(FAA_SRC["id"], {"state": "never"})
        if fa["state"] in ("stale", "never"):
            fa["withheld"] = len(nas.get("programs") or [])
        else:
            feats += faa_items(nas, fa["state"], now,
                               faa_counts if faa_counts is not None else read_jsonl("faa_counts.jsonl"))

    regs = registers.ids(ROOT / "doctrine")
    kept, dropped = [], []
    for f in feats:
        errs = [m for _, sev, m in contract.check(f, regs) if sev == "error"]
        (dropped.append({"id": f["properties"]["id"], "errors": errs}) if errs else kept.append(f))
    return {"type": "FeatureCollection", "contract": CONTRACT, "program": "cordon", "generated_at": fetched,
            "licence": "Cordon code MIT; State Department, NGA and FAA content US public domain; EASA content with acknowledgement",
            "attribution": "Cordon, The Intelligence Company. Sources: US Department of State, EASA, NGA, FAA.",
            "language_key": "https://github.com/metacog-osint/tic-doctrine/blob/main/docs/language-key.md",
            "health": src_health, "dropped": dropped, "features": kept}
