"""One collection run: every source independently. A failing source keeps its last good data and is recorded in
data/health.json; nothing here stops the others. Data files hold content only (fetch times live in health.json),
so the hourly workflow commits only when something changed."""
from . import canada, cdc, easa, embassy, faa, faaprn, fcdo, navarea, nms, safetravel, state, tfr
from .common import append_jsonl, health, load, now_utc, save


def run(when: str | None = None) -> dict:
    when = when or now_utc()
    summary = {}

    advisories, changes, err = state.collect(load("advisories.json", {}).get("advisories"), when)
    if err:
        health("state-travel-advisories", False, err, when)
    else:
        save("advisories.json", {"source": state.SOURCE_URL, "advisories": advisories})
        append_jsonl("changes.jsonl", [{**c, "lane": "state"} for c in changes])
        health("state-travel-advisories", True, f"{len(advisories)} advisories", when)
    summary["state"] = err or f"{len(advisories)} advisories, {len(changes)} changes"

    prev_alerts = load("alerts.json", {}).get("posts", {})
    alerts, errors, via = embassy.collect(advisories, prev_alerts, when)
    tried = len(embassy.posts(advisories))
    ok = tried - len(errors)
    searched = f" ({len(via)} only through Google News search)" if via else ""
    save("alerts.json", {"posts": alerts})
    health("us-embassy-alerts", ok > 0, f"{ok} of {tried} posts answered{searched}"
           + (f"; e.g. {next(iter(errors.values()))}" if errors else ""), when)
    summary["embassy"] = f"{ok} of {tried} posts{searched}"

    czibs, cz_changes, err = easa.collect(load("czibs.json", {}).get("bulletins"), when)
    if err:
        health("easa-czib", False, err, when)
    else:
        save("czibs.json", {"source": easa.SOURCE_URL, "bulletins": czibs})
        append_jsonl("changes.jsonl", [{**c, "lane": "easa"} for c in cz_changes])
        health("easa-czib", True, f"{sum(b['status'] == 'active' for b in czibs)} active", when)
    summary["easa"] = err or f"{len(czibs)} bulletins, {len(cz_changes)} changes"

    warnings, err, source, held = navarea.collect(load("navarea.json", {}).get("warnings"), when)
    newest = navarea.newest(warnings)  # of what is held now, new or kept: the feed reads staleness from this
    if err:
        health("nga-navwarnings", False, err, when, newest_item=newest)
    else:
        save("navarea.json", {"source": source, "warnings": warnings})
        # An area whose file failed keeps its earlier warnings; `since` is when its file last answered.
        before = (load("health.json", {}).get("nga-navwarnings") or {}).get("held_areas") or {}
        held_areas = {a: {"error": e, "since": (before.get(a) or {}).get("since") or when} for a, e in held.items()}
        kept = "".join(f"; {a} kept from the list of {h['since']} ({h['error']})" for a, h in held_areas.items())
        health("nga-navwarnings", True, f"{len(warnings)} warnings in force{kept}", when, newest_item=newest,
               held_areas=held_areas)
    summary["nga"] = err or f"{len(warnings)} warnings"

    programs, airports, err = faa.collect(when)
    if err:
        health("faa-nas-status", False, err, when)
    else:
        known = {**(load("faa_nas.json", {}).get("airports") or {}), **airports}  # keep places seen before
        save("faa_nas.json", {"source": faa.SOURCE_URL, "programs": programs, "airports": dict(sorted(known.items()))})
        n = faa.counts(programs)
        append_jsonl("faa_counts.jsonl", [{"at": when, **n}])  # Cordon's own baseline of concurrent programs
        health("faa-nas-status", True, f"{n['ground_stop']} ground stops, {n['ground_delay']} ground delay programs, "
                                       f"{n['closure']} closures", when)
    summary["faa"] = err or f"{len(programs)} programs"

    countries, uk_changes, err, read, failed = fcdo.collect(load("fcdo.json", {}).get("countries"), when)
    if err:
        health("uk-fcdo-travel-advice", False, err, when)
    else:
        save("fcdo.json", {"source": fcdo.SOURCE_URL, "countries": countries})
        append_jsonl("changes.jsonl", [{**c, "lane": "fcdo"} for c in uk_changes])
        unread = sum(1 for r in countries.values() if r.get("alert_status") is None)
        against = sum(1 for r in countries.values() if r.get("alert_status"))
        health("uk-fcdo-travel-advice", True, f"{len(countries)} countries, {against} with advice against some travel; "
               f"{read} country pages read" + (f", {failed} failed" if failed else "")
               + (f", {unread} not yet read" if unread else ""), when)
    summary["fcdo"] = err or f"{len(countries)} countries, {len(uk_changes)} changes, {read} pages read"

    places, ca_changes, generated, err = canada.collect(load("canada.json", {}).get("countries"), when)
    if err:
        health("gac-travel-advisories", False, err, when)
    else:
        save("canada.json", {"source": canada.SOURCE_URL, "generated": generated, "countries": places})
        append_jsonl("changes.jsonl", [{**c, "lane": "canada"} for c in ca_changes])
        n = {lv: sum(1 for r in places.values() if r["level"] == lv) for lv in canada.LEVELS}
        regional = sum(1 for r in places.values() if r["regional"])
        health("gac-travel-advisories", True, f"{len(places)} places: {n[3]} avoid all travel, {n[2]} avoid "
               f"non-essential travel, {n[1]} high degree of caution, {regional} with regional advisories; index "
               f"generated {generated or 'at an unstated time'}", when)
    summary["canada"] = err or f"{len(places)} places, {len(ca_changes)} changes"

    dests, nz_changes, err, read, failed = safetravel.collect(load("safetravel.json", {}).get("countries"), when)
    if err:
        health("nz-mfat-safetravel", False, err, when)
    else:
        save("safetravel.json", {"source": safetravel.SOURCE_URL, "countries": dests})
        append_jsonl("changes.jsonl", [{**c, "lane": "safetravel"} for c in nz_changes])
        n = {lv: sum(1 for r in dests.values() if r["level"] == lv) for lv in safetravel.LEVELS}
        regional = sum(1 for r in dests.values() if r.get("regional_note"))
        unread = sum(1 for r in dests.values() if not r.get("page_for"))
        health("nz-mfat-safetravel", True, f"{len(dests)} destinations: {n['avoid']} do not travel, {n['high']} avoid "
               f"non-essential travel, {n['medium']} increased caution, {regional} with other levels in some areas; "
               f"{read} country pages read" + (f", {failed} failed" if failed else "")
               + (f", {unread} not yet read" if unread else ""), when)
    summary["safetravel"] = err or f"{len(dests)} destinations, {len(nz_changes)} changes, {read} pages read"

    notices, cdc_changes, err = cdc.collect(load("cdc.json", {}).get("notices"), when)
    if err:
        health("cdc-travel-notices", False, err, when)
    else:
        save("cdc.json", {"source": cdc.SOURCE_URL, "notices": notices})
        append_jsonl("changes.jsonl", [{**c, "lane": "cdc"} for c in cdc_changes])
        n = {lv: sum(1 for r in notices.values() if r["level"] == lv) for lv in cdc.LEVELS}
        unplaced = sum(1 for r in notices.values() if not r["countries"])
        health("cdc-travel-notices", True, f"{len(notices)} notices: {n[4]} level 4, {n[3]} level 3, {n[2]} level 2, "
               f"{n[1]} level 1" + (f"; {unplaced} matched no country" if unplaced else ""), when)
    summary["cdc"] = err or f"{len(notices)} notices, {len(cdc_changes)} changes"


    held_tfr = load("tfr.json", {})
    tfrs, err, read, failed = tfr.collect(held_tfr.get("tfrs"), when)
    if err:
        health("faa-tfr", False, err, when)
    else:
        gone = tfr.remember(held_tfr.get("tfrs"), tfrs, held_tfr.get("gone"), when)
        save("tfr.json", {"source": tfr.LIST_URL, "tfrs": tfrs, "gone": gone})
        health("faa-tfr", True, tfr.health_detail(tfrs, read, failed), when)
    summary["tfr"] = err or f"{len(tfrs)} TFRs, {read} details read"

    sections, prn_changes, err = faaprn.collect(load("faa_prn.json", {}).get("sections"), when)
    if err:
        health("faa-prohibitions-notices", False, err, when)
    else:
        save("faa_prn.json", {"source": faaprn.SOURCE_URL, "sections": sections})
        append_jsonl("changes.jsonl", [{**c, "lane": "faaprn"} for c in prn_changes])
        health("faa-prohibitions-notices", True, faaprn.summary(sections), when)
    summary["faaprn"] = err or f"{len(sections)} sections, {len(prn_changes)} changes"

    # FAA NMS-API: the suite's one NOTAM reader (cordon/nms.py). No feed items of its own yet: it publishes subset
    # files for other programs. Health is written only when a request was made, so "waiting" (no keys) and the
    # bulk-window wait leave the feed's health block untouched.
    st, asked = nms.collect()
    if asked:
        health("faa-nms", st.get("status") == "ok", st.get("error") or
               f"{st.get('mode')}; {(st.get('counts') or {}).get('held', 0)} held; subsets {st.get('subsets')}", when)
    summary["nms"] = (f"{st.get('status')} ({st.get('mode') or '-'}): " +
                      (st.get("error") or st.get("note") or f"subsets {st.get('subsets')}, {st.get('requests')} requests"))
    return summary
