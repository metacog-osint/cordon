"""Cordon's feed in contract v2 (tic-feed/2) and the compact data the map page reads.

Every item is a measurement (kind observation): what an authority has published, with its own ladder value as
response_stage. A change in the last 30 days (a level raised or lowered, a departure order) is an anomaly against the
previous value. Each item is checked with the doctrine kit's linter; a failing item is dropped and listed.
"""
import re
from datetime import datetime, timedelta, timezone

from .common import ROOT, digest, load, point, read_jsonl, to_utc  # first: puts the doctrine kit on sys.path
from tic_doctrine import CONTRACT, contract, registers, vocab  # noqa: E402

SITE = "https://metacog-osint.github.io/cordon/"
METHOD = "cordon-feed-1.0"
RECENT_DAYS = 30
HAND_POINT = {"PS-GZ": [34.38, 31.42], "PS-WB": [35.25, 31.95]}  # [lon, lat], as Watchfloor places them
NOTABLE = {"launch", "gnss", "military", "mines", "piracy", "restricted_area", "search_and_rescue", "pollution",
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
POSTURE_WORDS = {"authorized_departure": "authorized departure", "ordered_departure": "ordered departure",
                 "suspended_operations": "suspended operations"}
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def nga_time(s: str) -> str | None:
    """'081653Z MAY 2024' -> '2024-05-08T16:53:00Z'."""
    m = re.match(r"(\d{2})(\d{2})(\d{2})Z\s+([A-Z]{3})\s+(\d{4})", (s or "").strip().upper())
    if not m or m.group(4) not in MONTHS:
        return None
    try:
        return datetime(int(m.group(5)), MONTHS[m.group(4)], int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


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


def build(adv: dict, alerts: dict, czibs: dict, nav: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
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
    for w in nav.get("warnings") or []:
        if w["category"] not in NOTABLE:
            continue
        g = w.get("geometry")
        ncf = ["transport_by_vessel"] + (["provide_pnt"] if w["category"] == "gnss" else [])
        props = {**_base(nv_fetched), "id": f"cordon:navwarn:{w['id']}", "title": f"{w['number']}: {w['headline']}",
                 "tier": "routine", "data_as_of": nga_time(w.get("issued")) or nv_fetched, "countries": [],
                 "precision_class": {"Point": "point", "Polygon": "area"}.get((g or {}).get("type"), "approximate")
                 if g else "none", "ncf": ncf, "sector": vocab.derive_sectors(ncf), "requirement_ids": ["CD-PIR-4"],
                 "ie_aspect": ["physical"], "pmesii_pt": ["infrastructure"], "ascope": ["areas"],
                 "sources": [{**NGA_SRC, "accessed_at": nv_fetched}],
                 "measures": {"category": w["category"], "sea": w.get("sea"), "place": w.get("place"),
                              "authority": w.get("authority"), "text": w["text"]}}
        if not g:
            props["visual"] = {"type": "page", "url": NGA_SRC["url"]}
        feats.append({"type": "Feature", "geometry": g, "properties": props})

    al_fetched = alerts.get("fetched_at") or fetched
    for iso, items in sorted((alerts.get("posts") or {}).items()):
        for a in items:
            props = {**_base(al_fetched), "id": f"cordon:alert:{iso}:{digest(a['link'])[7:19]}",
                     "title": f"US embassy ({iso}): {a['title']}", "tier": "routine",
                     "data_as_of": a.get("published_at") or al_fetched, "countries": [iso], "precision_class": "country",
                     "requirement_ids": ["CD-PIR-2"], "ie_aspect": ["informational"], "pmesii_pt": ["social"],
                     "ascope": ["events"], "sources": [{**EMBASSY_SRC, "id": f"usembassy-{iso.lower()}",
                                                         "url": a["link"], "accessed_at": al_fetched}],
                     "link": a["link"], "measures": {"type": a.get("type")}}
            feats.append({"type": "Feature", "geometry": point(iso), "properties": props})

    regs = registers.ids(ROOT / "doctrine")
    kept, dropped = [], []
    for f in feats:
        errs = [m for _, sev, m in contract.check(f, regs) if sev == "error"]
        (dropped.append({"id": f["properties"]["id"], "errors": errs}) if errs else kept.append(f))
    return {"type": "FeatureCollection", "contract": CONTRACT, "program": "cordon", "generated_at": fetched,
            "licence": "Cordon code MIT; State Department and NGA content US public domain; EASA content with acknowledgement",
            "attribution": "Cordon, The Intelligence Company. Sources: US Department of State, EASA, NGA.",
            "language_key": "https://github.com/metacog-osint/tic-doctrine/blob/main/docs/language-key.md",
            "dropped": dropped, "features": kept}
