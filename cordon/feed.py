"""Cordon's feed in contract v2 (tic-feed/2) and the compact data the map page reads.

Every item is a measurement (kind observation): what an authority has published, with its own ladder value as
response_stage. A change in the last 30 days (a level raised or lowered, a departure order) is an anomaly against the
previous value. Each item is checked with the doctrine kit's linter; a failing item is dropped and listed.
"""
import re
from datetime import datetime, timedelta, timezone

from . import airports, canada, cdc, faa, faaprn, fcdo, launchwarn, navarea, rev21, safetravel, tfr
from .common import ROOT, digest, load, point, read_jsonl, to_utc  # first: puts the doctrine kit on sys.path
from tic_doctrine import CONTRACT, CONTRACT_REV, __version__ as KIT, contract, geo, registers, vocab  # noqa: E402

SITE = "https://cordon.theintelligence.company/"
METHOD = "cordon-feed-1.2"
RECENT_DAYS = 30
STALE_HOURS = 48  # a source with no good fetch for this long is stale, whatever it last said
NEW_HOURS = 72  # a navigational warning issued within this long is new
# A new warning of these kinds is an anomaly, not routine (launch and military added by Tom, 13 Nov 2026).
NEW_ALERT = {"security", "mines", "piracy", "gnss", "launch", "military"}
HAND_POINT = {"PS-GZ": [34.38, 31.42], "PS-WB": [35.25, 31.95],  # [lon, lat], as Watchfloor places them
              "PT-20": [-25.67, 37.74]}  # the Azores (Ponta Delgada), which Canada advises on apart from Portugal
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
FCDO_SRC = {"id": "uk-fcdo-travel-advice", "publisher": "UK Foreign, Commonwealth & Development Office (FCDO)",
            "licence": "Open Government Licence v3.0", "grade": "A1", "independence_group": "uk-fcdo",
            "source_type": "official notice", "descriptor": "Foreign travel advice (GOV.UK Content API)"}
CANADA_SRC = {"id": "gac-travel-advisories", "publisher": "Global Affairs Canada (Government of Canada)",
              "licence": "Open Government Licence - Canada", "grade": "A1", "independence_group": "gac",
              "source_type": "official notice", "descriptor": "Travel advice and advisories (travel.gc.ca open data)"}
SAFETRAVEL_SRC = {"id": "nz-mfat-safetravel", "publisher": "New Zealand Ministry of Foreign Affairs and Trade (MFAT)",
                  "licence": "Crown copyright, Creative Commons Attribution 4.0 International", "grade": "A1",
                  "independence_group": "nz-mfat", "source_type": "official notice",
                  "descriptor": "Travel advice (safetravel.govt.nz)"}
CDC_SRC = {"id": "cdc-travel-notices", "publisher": "US Centers for Disease Control and Prevention (CDC), Travelers' Health",
           "licence": "US public domain (CDC asks for credit and a no-endorsement disclaimer)", "grade": "A1",
           "independence_group": "cdc", "source_type": "official notice",
           "descriptor": "Travel health notice (wwwnc.cdc.gov/travel/notices)"}
TFR_SRC = {"id": "faa-tfr", "publisher": "US Federal Aviation Administration (FAA)", "url": tfr.SITE_URL,
           "licence": "US Government work, not subject to US copyright (17 U.S.C. 105); the FAA states no licence on "
           "the TFR site", "grade": "A1", "independence_group": "faa", "source_type": "official notice",
           "descriptor": "Temporary flight restriction (NOTAM), with the FAA's own boundary"}
FAA_WORDS = {"ground_stop": "ground stop", "ground_delay": "ground delay program", "closure": "airport closure"}
FAAPRN_SRC = {"id": "faa-prohibitions-notices", "publisher": "US Federal Aviation Administration (FAA)",
              "url": faaprn.PAGE_URL, "licence": "US Government work, not subject to US copyright (17 U.S.C. 105); "
              "the FAA states no licence on the page", "grade": "A1", "independence_group": "faa",
              "source_type": "official notice",
              "descriptor": "Prohibitions, Restrictions and Notices: US flight prohibitions (SFARs) and security "
                            "NOTAMs (KICZ) for foreign airspace"}
STALE_BY_SOURCE = {FAA_SRC["id"]: faa.STALE_HOURS, TFR_SRC["id"]: tfr.STALE_HOURS}
# Lines are tracklines as published; a GeometryCollection is areas or circles with tracklines; MultiPoint is a set of
# positions with no shape given, so its extent is approximate.
PRECISION = {"Point": "point", "LineString": "point", "MultiLineString": "point", "Polygon": "area",
             "MultiPolygon": "area", "GeometryCollection": "area"}
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
    A stale or never source has its items withheld from the feed (counted in `withheld`): it reads as no data.
    NGA's `held_areas` names any area whose daily file failed and whose earlier warnings were kept, with the time its
    file last answered; an area held for STALE_HOURS is withheld the same way (see build)."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {}
    for sid, h in sorted((health or {}).items()):
        cutoff = (now - timedelta(hours=STALE_BY_SOURCE.get(sid, STALE_HOURS))).strftime("%Y-%m-%dT%H:%M:%SZ")
        last_ok = h.get("last_ok")
        state = ("never" if not last_ok else "stale" if last_ok < cutoff
                 else "failing" if h.get("failures") else "fresh")
        out[sid] = {"state": state, "last_ok": last_ok, "last_error": h.get("last_error"),
                    "failures": h.get("failures", 0), "checked_at": h.get("checked_at"), "detail": h.get("detail")}
        if h.get("held_areas"):
            out[sid]["held_areas"] = h["held_areas"]
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


POSTAL = re.compile(r"^[A-Z]{2}$")


def us_subdivisions(countries: list, geom: dict | None, postal: str | None = None) -> list[str]:
    """ISO 3166-2 codes of the US states an item is in (kit 0.5.7 `subdivisions`): the source's own two-letter state
    when it gives one (the FAA's TFR list), else the states its shape's vertices fall in. Only for US items with a
    shape; a country-level item (at the country's label point, in Kansas) gets none."""
    if "US" not in (countries or []):
        return []
    if postal and POSTAL.match(postal) and postal not in tfr.TERRITORIES and postal != "US":
        return [f"US-{postal}"]
    return geo.subdivisions_for_geometry(geom) if geom else []


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
        # The id keeps the program's start (a second program at one airport is a second item); the subject is the
        # airport's program of that kind, whatever its start (rev 2.1).
        props = {**_base(fetched), "id": f"cordon:faa:{kind}:{apt}:{start or 'open'}", "title": title,
                 "subject_id": f"cordon:faa:{kind}:{apt}",
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
        rev21.event(props, to_utc(p.get("start")), to_utc(p.get("end")))
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
        if where:
            # Impact (Tom, 15 Nov 2026): whether the airport is one of the FAA's Core 30, whose programs ripple across
            # the system, or how far it is from the nearest. Measured only; the tier rule above is unchanged.
            near = airports.nearest_core30([(where[1], where[0])])
            code = apt.upper()[1:] if len(apt) == 4 and apt.upper().startswith("K") else apt.upper()
            props["measures"]["core30"] = code in airports.CORE30
            if near:
                props["measures"]["nearest_core30"] = {"airport": near[0], "km": near[1]}
            subs = us_subdivisions(props["countries"], geom)
            if subs:
                props["subdivisions"] = subs
        if geom is None and wide:
            geom = point("US")
            props["precision_class"] = "country"
        out.append({"type": "Feature", "geometry": geom, "properties": props})
    return out


def fcdo_items(data: dict, now: datetime, changes: list[dict]) -> list[dict]:
    """The FCDO's advice for every country where it advises against some travel, whose statements changed in the
    last RECENT_DAYS, or whose advice it updated in the last NEW_HOURS (with the FCDO's own note of what changed)."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched = data.get("fetched_at") or stamp
    new_from = (now - timedelta(hours=NEW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    last = {c["key"]: c for c in changes if c.get("lane") == "fcdo" and c.get("kind") == "alert"}
    out = []
    for slug, r in sorted((data.get("countries") or {}).items()):
        st, ch = r.get("alert_status"), last.get(slug)
        is_new = bool(r.get("updated") and r["updated"] >= new_from)
        if not st and not ch and not is_new:
            continue
        title = f"UK FCDO, {r['name']}: {fcdo.words(st)}"
        if is_new and r.get("change"):
            title += f" (updated: {r['change']})"
        props = {**_base(fetched), "id": f"cordon:fcdo:{slug}", "title": title, "tier": "anomaly" if ch else "routine",
                 "data_as_of": r.get("updated") or fetched, "countries": [r["iso"]] if r.get("iso") else [],
                 "precision_class": "country", "requirement_ids": ["CD-PIR-6"], "ie_aspect": ["informational"],
                 "pmesii_pt": ["political"], "ascope": ["areas"],
                 "sources": [{**FCDO_SRC, "url": r["link"], "accessed_at": fetched}], "link": r["link"],
                 "measures": {"alert_status": st, "advice": fcdo.words(st), "change": r.get("change") or None,
                              "updated": r.get("updated"), "new": is_new}}
        if ch:
            props["baseline_ref"] = {"id": "previous-fcdo-alert-status", "type": "fixed", "version": "1",
                                     "window": "the FCDO's previous statements for the country"}
            props["measures"].update({"changed_at": ch["at"], "from": ch["from"], "from_advice": fcdo.words(ch["from"])})
        rev21.event(props, r.get("updated"))
        if ch:
            rev21.stamp(props, "changed", ch["at"])  # the FCDO's statements have no order: changed, not raised
        elif is_new:
            rev21.stamp(props, "changed", r["updated"])  # updated advice for a country the FCDO already advised on
        geom = _pt(r["iso"], r["iso"]) if r.get("iso") else None
        out.append(_place({"type": "Feature", "geometry": geom, "properties": props}, r["link"]))
    return out


def canada_items(data: dict, now: datetime, changes: list[dict]) -> list[dict]:
    """Canada's advisory for every place above its lowest level or with regional advisories, whose level or regional
    advisories changed in the last RECENT_DAYS, or that Canada updated in the last NEW_HOURS other than editorially or
    in its contacts section alone (with Canada's own note of what changed)."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched = data.get("fetched_at") or stamp
    new_from = (now - timedelta(hours=NEW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mine = [c for c in changes if c.get("lane") == "canada"]
    lvl = {c["key"]: c for c in mine if c.get("kind") == "level"}
    reg = {c["key"]: c for c in mine if c.get("kind") == "regional"}
    out = []
    for key, r in sorted((data.get("countries") or {}).items()):
        is_new = bool(r.get("updated") and r["updated"] >= new_from and canada.counts_as_new(r))
        declared = is_new and canada.declares_change(r)
        lc, rc = lvl.get(key), reg.get(key)
        if not (r["level"] >= 1 or r.get("regional") or lc or rc or is_new):
            continue
        title = f"Canada, {r['name']}: {r['advisory']}"
        if is_new and r.get("update"):
            title += f" (updated: {r['update']})"
        props = {**_base(fetched), "id": f"cordon:canada:{key}", "title": title,
                 "tier": "anomaly" if (lc or rc or declared) else "routine",
                 "data_as_of": r.get("updated") or fetched, "countries": [r["iso"]], "precision_class": "country",
                 "requirement_ids": ["CD-PIR-8"], "ie_aspect": ["informational"], "pmesii_pt": ["political"],
                 "ascope": ["areas"], "sources": [{**CANADA_SRC, "url": r["link"], "accessed_at": fetched}],
                 "link": r["link"], "measures": {"level": r["level"], "advisory": r["advisory"],
                                                 "regional": bool(r.get("regional")), "update_type": r.get("update_type"),
                                                 "update": r.get("update"), "updated": r.get("updated"), "new": is_new}}
        if lc or rc:
            props["baseline_ref"] = {"id": "previous-gac-advisory", "type": "fixed", "version": "1",
                                     "window": "Canada's previous level and regional advisories for the place"}
        elif declared:
            props["baseline_ref"] = {"id": "gac-declared-advisory-change", "type": "fixed", "version": "1",
                                     "window": f"Canada's own label for its latest update, published in the last "
                                               f"{NEW_HOURS} hours"}
        if lc:
            props["measures"].update({"changed_at": lc["at"], "from_level": lc["from"],
                                      "from_advice": canada.LEVELS.get(lc["from"])})
        if rc:
            props["measures"].update({"regional_changed_at": rc["at"], "from_regional": rc["from"]})
        rev21.event(props, r.get("updated"))
        rev21.signal(props, "Canada risk level 0-3", r["level"], "level 0-3")
        if lc:
            rev21.stamp(props, rev21.moved(lc["from"], r["level"]), lc["at"])
        elif rc:
            rev21.stamp(props, "changed", rc["at"])
        elif is_new:
            rev21.stamp(props, "changed", r["updated"])
        out.append(_place({"type": "Feature", "geometry": _pt(key, r["iso"]), "properties": props}, r["link"]))
    return out


def safetravel_items(data: dict, now: datetime, changes: list[dict]) -> list[dict]:
    """New Zealand's advice for every destination at "Exercise increased caution" or above, or with other levels in
    some areas, whose level or regional note changed in the last RECENT_DAYS, or that MFAT updated in the last NEW_HOURS
    (MFAT gives a day, not a time, so "the last NEW_HOURS" is read as from that day on)."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched = data.get("fetched_at") or stamp
    new_from = (now - timedelta(hours=NEW_HOURS)).strftime("%Y-%m-%d")
    mine = [c for c in changes if c.get("lane") == "safetravel"]
    lvl = {c["key"]: c for c in mine if c.get("kind") == "level"}
    reg = {c["key"]: c for c in mine if c.get("kind") == "regional"}
    out = []
    for key, r in sorted((data.get("countries") or {}).items()):
        is_new = bool(r.get("updated") and r["updated"] >= new_from)
        lc, rc = lvl.get(key), reg.get(key)
        if not (safetravel.level_rank(r["level"]) >= 2 or r.get("regional_note") or lc or rc or is_new):
            continue
        title = f"New Zealand, {r['name']}: {r['advice']}"
        if r.get("regional_note"):
            # MFAT words this note four ways (14 Nov 2026: "with higher advice levels in some areas" 54 times, "See
            # regional advice below", "There are areas of Bolivia where higher advice levels apply ...", "in Mozambique
            # overall due to ..."); the title uses one phrase and measures.regional_note keeps MFAT's words.
            title += " (other levels apply in some areas)"
        props = {**_base(fetched), "id": f"cordon:safetravel:{key}", "title": title,
                 "tier": "anomaly" if (lc or rc) else "routine",
                 "data_as_of": f"{r['updated']}T00:00:00Z" if r.get("updated") else fetched,
                 "countries": [r["iso"]], "precision_class": "country", "requirement_ids": ["CD-PIR-10"],
                 "ie_aspect": ["informational"], "pmesii_pt": ["political"], "ascope": ["areas"],
                 "sources": [{**SAFETRAVEL_SRC, "url": r["link"], "accessed_at": fetched}], "link": r["link"],
                 "measures": {"level": r["level"], "advice": r["advice"], "regional_note": r.get("regional_note"),
                              "region": r.get("region"), "updated": r.get("updated"), "new": is_new}}
        if lc or rc:
            props["baseline_ref"] = {"id": "previous-mfat-advice", "type": "fixed", "version": "1",
                                     "window": "New Zealand's previous level and regional note for the destination"}
        if lc:
            props["measures"].update({"changed_at": lc["at"], "from_level": lc["from"],
                                      "from_advice": safetravel.LEVELS.get(lc["from"])})
        if rc:
            props["measures"].update({"regional_changed_at": rc["at"], "from_regional_note": rc["from"]})
        rev21.event(props, rev21.day(r.get("updated")), precision="day")  # MFAT gives a day, not a time
        if safetravel.level_rank(r["level"]) >= 0:  # 1 exercise normal precautions ... 4 do not travel; 0 no level
            rev21.signal(props, "NZ SafeTravel level 1-4", safetravel.level_rank(r["level"]), "level 1-4")
        if lc:
            rev21.stamp(props, rev21.moved(safetravel.level_rank(lc["from"]), safetravel.level_rank(r["level"])),
                        lc["at"])
        elif rc:
            rev21.stamp(props, "changed", rc["at"])
        elif is_new:
            rev21.stamp(props, "changed", rev21.day(r["updated"]))
        out.append(_place({"type": "Feature", "geometry": _pt(key, r["iso"]), "properties": props}, r["link"]))
    return out


def cdc_items(data: dict, now: datetime, changes: list[dict]) -> list[dict]:
    """Every CDC travel health notice in force, in CDC's words. A notice Cordon saw appear, or whose level it saw
    change, in the last RECENT_DAYS is an anomaly; one CDC published or updated in the last NEW_HOURS is marked new."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched = data.get("fetched_at") or stamp
    new_from = (now - timedelta(hours=NEW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    last = {c["key"]: c for c in changes if c.get("lane") == "cdc" and c.get("kind") in ("new", "level")}
    out = []
    for slug, r in sorted((data.get("notices") or {}).items()):
        ch = last.get(slug)
        is_new = bool(r.get("published") and r["published"] >= new_from)
        props = {**_base(fetched), "id": f"cordon:cdc:{slug}",
                 "title": f"CDC Level {r['level']} ({r['level_text']}): {r['disease_place']}",
                 "tier": "anomaly" if ch else "routine", "data_as_of": r.get("published") or fetched,
                 "countries": r["countries"], "precision_class": "country", "requirement_ids": ["CD-PIR-9"],
                 "ie_aspect": ["physical"], "pmesii_pt": ["social"], "ascope": ["events"],
                 "sources": [{**CDC_SRC, "url": r["link"], "accessed_at": fetched}], "link": r["link"],
                 "measures": {"level": r["level"], "level_text": r["level_text"], "summary": r.get("summary"),
                              "published": r.get("published"), "date": r.get("date"), "new": is_new}}
        if ch:
            props["baseline_ref"] = {"id": "previous-cdc-notices", "type": "fixed", "version": "1",
                                     "window": "the CDC notices Cordon held before, and each notice's previous level"}
            props["measures"].update({"changed_at": ch["at"], "change": ch["kind"], "from_level": ch["from"]})
        rev21.event(props, rev21.day(r.get("published")), precision="day")
        rev21.signal(props, "CDC travel notice level 1-4", r["level"], "level 1-4")
        if ch:
            rev21.stamp(props, "new" if ch["kind"] == "new" else rev21.moved(ch["from"], r["level"]), ch["at"])
        elif is_new:
            rev21.stamp(props, "new", r["published"])
        pts = [p["coordinates"] for p in (point(c) for c in r["countries"]) if p]
        geom = ({"type": "Point", "coordinates": pts[0]} if len(pts) == 1
                else {"type": "MultiPoint", "coordinates": pts} if pts else None)
        out.append(_place({"type": "Feature", "geometry": geom, "properties": props}, r["link"]))
    return out


def tfr_items(data: dict, now: datetime) -> tuple[list[dict], dict]:
    """(items, counts) for the TFRs the FAA lists, drawn with the FAA's own outline. Left out and counted: TFRs past
    their own expiry (expired), TFRs with no area (no_shape: the standing nationwide notices) and types in
    tfr.SKIP_TYPES (skipped). A TFR whose detail has not been read yet is listed with the FAA's page as its visual."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched = data.get("fetched_at") or stamp
    new_from = (now - timedelta(hours=tfr.NEW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, n = [], {"expired": 0, "no_shape": 0, "skipped": 0}
    subjects = tfr.subjects(data.get("tfrs"), data.get("gone"))
    for nid, r in sorted((data.get("tfrs") or {}).items()):
        d = r.get("detail") or {}
        g = d.get("geometry")
        if r["type"] in tfr.SKIP_TYPES:
            n["skipped"] += 1
            continue
        if not tfr.in_force(r, stamp):
            n["expired"] += 1
            continue
        if d and not g:
            n["no_shape"] += 1
            continue
        place = d.get("city") or (r.get("description") or "").split(",")[0].strip() or "no place given"
        where = f"{place}, {r['state']}" if r.get("state") and r["state"] != "USA" else place
        title = f"FAA TFR {nid} ({r['type'].lower() or 'type not given'}): {where}"
        if d.get("name") and d["name"] != nid:
            title += f" ({d['name']})"
        issued = d.get("issued")
        is_new = bool(issued and issued >= new_from)
        imp = tfr.impact(r) if g else {}
        again = tfr.reissue(nid, r, data.get("tfrs") or {}, data.get("gone") or {}) if is_new and g else None
        fresh = is_new and not (again and not again["enlarged"])
        # New, not a plain re-issue, not statutory, and of some impact (a high one for VIP TFRs); see tfr.impact.
        alert = (fresh and not d.get("statutory") and imp.get("impact") in ("moderate", "high")
                 and (r["type"] in tfr.NEW_ALERT or (r["type"] in tfr.IMPACT_ALERT and imp.get("impact") == "high")))
        page = tfr.PAGE_URL.format(id=tfr.file_id(nid))
        props = {**_base(fetched), "id": f"cordon:tfr:{nid.replace('/', '-')}", "title": title,
                 "tier": "anomaly" if alert else "routine", "data_as_of": issued or fetched,
                 "countries": [tfr.TERRITORIES.get(r.get("state") or "", "US")],
                 "precision_class": "area" if g else "none", "ncf": ["transport_by_air"],
                 "sector": vocab.derive_sectors(["transport_by_air"]), "requirement_ids": ["CD-PIR-7"],
                 "ie_aspect": ["physical"], "pmesii_pt": ["infrastructure"], "ascope": ["areas"],
                 "sources": [{**TFR_SRC, "url": page, "accessed_at": fetched}], "link": page,
                 "measures": {"notam_id": nid, "type": r["type"], "new": is_new,
                              **{k: r[k] for k in ("facility", "state", "description", "created") if r.get(k)},
                              **{k: d[k] for k in ("effective", "issued", "regulation", "purpose", "floor", "ceiling",
                                                   "statutory") if d.get(k)},
                              **({"text": tfr.display_text(d["text"])} if d.get("text") else {}), **imp}}
        if again:
            props["measures"]["reissue_of"] = again["of"]
            props["measures"]["enlarged"] = again["enlarged"]
        subject = subjects[nid]
        props["subject_id"] = f"cordon:tfr:{subject.replace('/', '-')}"
        rev21.event(props, d.get("effective") or issued, d.get("expires"))
        if is_new:
            # A re-issue that took over its predecessor's subject is a change of that restriction, not a new one.
            rev21.stamp(props, "changed" if subject != nid else "new", issued)
        subs = us_subdivisions(props["countries"], g, r.get("state"))
        if subs:
            props["subdivisions"] = subs
        if d.get("expires"):
            props["valid_until"] = d["expires"]
        if alert:
            props["baseline_ref"] = {"id": "faa-tfrs-in-force", "type": "rolling", "version": "2",
                                     "window": f"the TFRs the FAA listed {tfr.NEW_HOURS} hours earlier, and those Cordon "
                                               f"held in the {tfr.GONE_DAYS} days before (re-issues)"}
        if not g:
            props["visual"] = {"type": "page", "url": page}  # detail not read yet: the FAA's page stands in
        out.append({"type": "Feature", "geometry": g, "properties": props})
    return out, n


def faaprn_items(data: dict, now: datetime, changes: list[dict]) -> list[dict]:
    """One item per country or region where the FAA lists an SFAR or a KICZ NOTAM for US operators, titled by the
    strongest of them (prohibition, advisory, pointer). A section where Cordon saw one appear or go in the last
    RECENT_DAYS is an anomaly; one that appeared in the last NEW_HOURS is marked new. Seas and regions with no
    country (Central America's Pacific, the Pacific Ocean, the Persian Gulf and Gulf of Oman) have no point."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    fetched = data.get("fetched_at") or stamp
    new_from = (now - timedelta(hours=NEW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mine = {}
    for c in changes:
        if c.get("lane") == "faaprn":
            mine.setdefault(c["section"], []).append(c)
    out = []
    for skey, s in sorted((data.get("sections") or {}).items()):
        if not s.get("entries"):
            continue
        ents = sorted(s["entries"].values(), key=lambda e: (faaprn.KINDS.index(e["kind"]), e["key"]))
        top = faaprn.strongest(s["entries"])
        ch = mine.get(skey, [])
        added = sorted({c["label"] for c in ch if c["kind"] == "new" and c["key"] in s["entries"]})
        removed = sorted({c["label"] for c in ch if c["kind"] == "removed" and c["key"] not in s["entries"]})
        is_new = any(c["kind"] == "new" and c["at"] >= new_from for c in ch)
        link = f"{faaprn.PAGE_URL}#{s.get('anchor') or skey}"
        iso = s.get("iso")
        props = {**_base(fetched), "id": f"cordon:faaprn:{skey}",
                 "title": f"FAA, {s['name']}: {faaprn.WORDS[top]} (" + ", ".join(e["label"] for e in ents) + ")",
                 "tier": "anomaly" if (added or removed) else "routine", "data_as_of": fetched,
                 "countries": [iso] if iso else [], "precision_class": "country" if iso else "none",
                 "ncf": ["transport_by_air"], "sector": vocab.derive_sectors(["transport_by_air"]),
                 "requirement_ids": ["CD-PIR-11"], "ie_aspect": ["physical"], "pmesii_pt": ["military", "infrastructure"],
                 "ascope": ["areas"], "sources": [{**FAAPRN_SRC, "url": link, "accessed_at": fetched}], "link": link,
                 "measures": {"strongest": top, "new": is_new,
                              "entries": [{k: e[k] for k in ("key", "label", "kind", "text", "url", "firs")} for e in ents],
                              "firs": sorted({f for e in ents for f in e.get("firs") or []}),
                              "background": s.get("background") or []}}
        if added or removed:
            props["baseline_ref"] = {"id": "previous-faa-prohibitions", "type": "fixed", "version": "1",
                                     "window": "the SFARs and KICZ NOTAMs the FAA listed for the section before"}
            props["measures"].update({"changed_at": max(c["at"] for c in ch), "added": added, "removed": removed})
            rev21.stamp(props, "changed", props["measures"]["changed_at"])  # an SFAR or KICZ NOTAM listed or taken off
        feat = {"type": "Feature", "geometry": _pt(iso, iso) if iso else None, "properties": props}
        out.append(_place(feat, link))
    return out


def build(adv: dict, alerts: dict, czibs: dict, nav: dict, now: datetime | None = None,
          health: dict | None = None, nas: dict | None = None, faa_counts: list[dict] | None = None,
          uk: dict | None = None, tfrs: dict | None = None, ca: dict | None = None,
          health_notices: dict | None = None, nz: dict | None = None, prn: dict | None = None,
          dropped_log=None) -> dict:
    """`dropped_log`: a path; the items the linter drops are appended there whole (cordon/dropped.py, C5)."""
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
            rev21.stamp(props, rev21.moved(ch["from"], r["level"]), ch["at"])
        rev21.event(props, to_utc(r.get("updated")))  # the date the advisory took effect
        rev21.signal(props, "State Dept advisory level 1-4", r["level"], "level 1-4")
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
                # normal < authorized departure < ordered departure < suspended operations
                rev21.stamp(pp, rev21.moved(rev21.POSTURE_RANK.get(pc.get("from")),
                                            rev21.POSTURE_RANK.get(r["posture"]["state"])), pc["at"])
            rev21.event(pp, to_utc(r.get("updated")))
            feats.append(_place({"type": "Feature", "geometry": _pt(key, r["iso"]), "properties": pp}, r["link"]))

    cz_fetched = czibs.get("fetched_at") or fetched
    czib_revised = {c["id"]: c for c in changes if c.get("lane") == "easa" and c.get("kind") in ("new", "revised", "status")}
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
        rev21.event(props, rev21.day(b.get("issued")), rev21.day(b.get("valid_until")), "day")
        rv = czib_revised.get(b["id"])
        if rv:
            rev21.stamp(props, "new" if rv["kind"] == "new" else "changed", rv["at"])  # Cordon's record of it
        geom = {"type": "MultiPoint", "coordinates": pts} if len(pts) > 1 else ({"type": "Point", "coordinates": pts[0]}
                                                                                if pts else None)
        if geom is None:
            props.update({"precision_class": "none", "visual": {"type": "page", "url": EASA_SRC["url"]}})
        feats.append({"type": "Feature", "geometry": geom, "properties": props})

    nv_fetched = nav.get("fetched_at") or fetched
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    new_from = (now - timedelta(hours=NEW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    expired = 0
    old_areas = navarea.held_too_long(nga.get("held_areas"), stamp, STALE_HOURS)
    shown = []
    for w in nav.get("warnings") or []:
        if w["category"] not in NOTABLE:
            continue
        if w.get("area") in old_areas:
            nga["withheld"] = nga.get("withheld", 0) + 1  # its area's file has not answered for STALE_HOURS
            continue
        if not navarea.in_force(w, stamp):
            expired += 1  # past its own "cancel this msg" time, though still on NGA's daily list
            continue
        shown.append(w)
    # One item per hazard: a warning NGA also broadcast in another series is listed on the lead, not drawn twice.
    leads, merged = navarea.rebroadcasts(shown)
    if merged:
        nga["rebroadcasts_merged"] = len(merged)
    for w in shown:
        if w["id"] in merged:
            continue
        g = w.get("geometry")
        issued = nga_time(w.get("issued"))
        is_new = bool(issued and issued >= new_from)
        alert = is_new and w["category"] in NEW_ALERT
        ncf = ["transport_by_vessel"] + (["provide_pnt"] if w["category"] == "gnss" else [])
        props = {**_base(nv_fetched), "id": f"cordon:navwarn:{w['id']}", "title": f"{w['number']}: {w['headline']}",
                 "tier": "anomaly" if alert else "routine", "data_as_of": issued or nv_fetched, "countries": [],
                 "precision_class": PRECISION.get((g or {}).get("type"), "approximate") if g else "none", "ncf": ncf, "sector": vocab.derive_sectors(ncf), "requirement_ids": ["CD-PIR-4"],
                 "ie_aspect": ["physical"], "pmesii_pt": ["infrastructure"], "ascope": ["areas"],
                 "sources": [{**NGA_SRC, "accessed_at": nv_fetched}],
                 "measures": {"category": w["category"], "sea": w.get("sea"), "place": w.get("place"),
                              "authority": w.get("authority"), "text": navarea.display_text(w["text"]), "new": is_new,
                              **{k: w[k] for k in ("radius_m", "corridor_half_width_m") if w.get(k)}}}
        if w["category"] == "launch":  # windows, hazard and cancels in the warning's own words (cordon/launchwarn.py)
            props["measures"].update(launchwarn.measures(navarea.display_text(w["text"]), issued, w.get("area")))
        if w.get("cancel_at"):
            props["valid_until"] = w["cancel_at"]
        # When the hazard is in force: the windows in the warning's own words (Cordon's launch-window reader, used on
        # every category), else from issue to NGA's own cancel time when it set one.
        wins = launchwarn.parse_windows(w["text"], datetime.strptime(issued, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc))[0] if issued and w.get("text") else []
        if wins:
            rev21.event(props, min(x["start"] for x in wins), max(x["end"] for x in wins))
        else:
            rev21.event(props, issued, w.get("cancel_at"))
        if is_new:
            rev21.stamp(props, "new", issued)
        if w["category"] == "security":
            # NGA relays an incident others report: one origin, corroboration left to COP (Tom, 18 Nov 2026).
            props["corroboration"] = rev21.corroboration("reported", None, None, issued or nv_fetched)
        if w["id"] in leads:
            props["measures"]["rebroadcasts"] = [{**r, "id": f"cordon:navwarn:{r['id']}"} for r in leads[w["id"]]]
            props["title"] += " (also " + ", ".join(r["number"] for r in leads[w["id"]]) + ")"
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
        # One item per alert subject (Tom, 18 Nov 2026): a post re-dated under the same headline is the newest
        # reading of one alert, with the earlier posts' dates and links in measures.earlier.
        subjects = {}
        for a in items:
            subjects.setdefault(rev21.alert_subject(iso, a["title"]), []).append(a)
        for subject, posts in subjects.items():
            posts = sorted(posts, key=lambda x: (x.get("published_at") or "", x["link"]), reverse=True)
            a, earlier = posts[0], posts[1:]
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
                     "link": a["link"], "measures": {"type": a.get("type")}, "subject_id": subject}
            if earlier:
                props["measures"]["earlier"] = [{"title": e["title"], "published_at": e.get("published_at"),
                                                 "link": e["link"]} for e in earlier]
            pub = a.get("published_at")
            rev21.event(props, pub)
            # A re-dated alert is a change of one alert; the post's own date times it.
            rev21.stamp(props, "changed" if earlier else "new", pub)
            # The embassy speaks within its own remit: one official origin (D11).
            first = min([pub] + [e.get("published_at") for e in earlier if e.get("published_at")]) if pub else None
            props["corroboration"] = rev21.corroboration("corroborated", "official", src["id"], first or al_fetched)
            feats.append({"type": "Feature", "geometry": point(iso), "properties": props})

    if nas is not None:
        fa = src_health.setdefault(FAA_SRC["id"], {"state": "never"})
        if fa["state"] in ("stale", "never"):
            fa["withheld"] = len(nas.get("programs") or [])
        else:
            feats += faa_items(nas, fa["state"], now,
                               faa_counts if faa_counts is not None else read_jsonl("faa_counts.jsonl"))

    if uk is not None:
        fc = src_health.setdefault(FCDO_SRC["id"], {"state": "never"})
        if fc["state"] in ("stale", "never"):
            fc["withheld"] = sum(1 for r in (uk.get("countries") or {}).values() if r.get("alert_status"))
        else:
            feats += fcdo_items(uk, now, changes)

    if ca is not None:
        cs = src_health.setdefault(CANADA_SRC["id"], {"state": "never"})
        if cs["state"] in ("stale", "never"):
            cs["withheld"] = sum(1 for r in (ca.get("countries") or {}).values() if r["level"] >= 1 or r.get("regional"))
        else:
            feats += canada_items(ca, now, changes)

    if nz is not None:
        ns = src_health.setdefault(SAFETRAVEL_SRC["id"], {"state": "never"})
        if ns["state"] in ("stale", "never"):
            ns["withheld"] = sum(1 for r in (nz.get("countries") or {}).values()
                                 if safetravel.level_rank(r["level"]) >= 2 or r.get("regional_note"))
        else:
            feats += safetravel_items(nz, now, changes)

    if health_notices is not None:
        cd = src_health.setdefault(CDC_SRC["id"], {"state": "never"})
        if cd["state"] in ("stale", "never"):
            cd["withheld"] = len(health_notices.get("notices") or {})
        else:
            feats += cdc_items(health_notices, now, changes)

    if prn is not None:
        pr = src_health.setdefault(FAAPRN_SRC["id"], {"state": "never"})
        if pr["state"] in ("stale", "never"):
            pr["withheld"] = sum(1 for s in (prn.get("sections") or {}).values() if s.get("entries"))
        else:
            feats += faaprn_items(prn, now, changes)

    if tfrs is not None:
        tf = src_health.setdefault(TFR_SRC["id"], {"state": "never"})
        if tf["state"] in ("stale", "never"):
            tf["withheld"] = len(tfrs.get("tfrs") or {})
        else:
            items, counts = tfr_items(tfrs, now)
            feats += items
            tf.update({k: v for k, v in counts.items() if v})

    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Published when built (rev 2.1): the history step after the build runs with --now at the feed's generated_at,
    # so a change it records is never later than the item's publication. Each source's accessed_at keeps its read.
    for f in feats:
        f["properties"]["published_at"] = stamp
    rev21.finish(feats, src_health)
    for e in src_health.values():  # every lane carries the revision 2.1 health members, read or not
        e.setdefault("last_ok", None)
        e.setdefault("last_error", None)
        e.setdefault("failures", 0)
        e.setdefault("checked_at", stamp)
    regs = registers.ids(ROOT / "doctrine")
    kept, dropped = [], []
    for f in feats:
        errs = [m for _, sev, m in contract.check(f, regs, rev=CONTRACT_REV) if sev == "error"]
        (dropped.append({"id": f["properties"]["id"], "errors": errs}) if errs else kept.append(f))
    if dropped_log is not None and dropped:
        from . import dropped as dropped_store
        dropped_store.append(dropped_log, dropped, {f["properties"]["id"]: f for f in feats},
                             now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return {"type": "FeatureCollection", "contract": CONTRACT, "contract_rev": CONTRACT_REV, "kit": KIT,
            "program": "cordon", "generated_at": stamp,
            "licence": "Cordon code MIT; State Department, NGA and FAA content US public domain; EASA content with "
                       "acknowledgement; UK FCDO content under the Open Government Licence v3.0; Government of Canada "
                       "content under the Open Government Licence - Canada; CDC content US public domain; New Zealand MFAT "
                       "content Crown copyright under CC BY 4.0",
            "attribution": "Cordon, The Intelligence Company. Sources: US Department of State, EASA, NGA, FAA, UK FCDO, "
                           "Global Affairs Canada. Contains public sector information licensed under the Open "
                           "Government Licence v3.0. Contains information licensed under the Open Government "
                           "Licence - Canada. Health notices: Source: CDC; available free at "
                           "wwwnc.cdc.gov/travel/notices; their use here does not imply endorsement by CDC, HHS or the "
                           "US Government. New Zealand travel advice: Ministry of Foreign Affairs and Trade, "
                           "SafeTravel (safetravel.govt.nz), licensed under CC BY 4.0.",
            "language_key": "https://github.com/metacog-osint/tic-doctrine/blob/main/docs/language-key.md",
            "health": src_health, "dropped": dropped, "features": kept}
