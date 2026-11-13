"""One collection run: every source independently. A failing source keeps its last good data and is recorded in
data/health.json; nothing here stops the others. Data files hold content only (fetch times live in health.json),
so the hourly workflow commits only when something changed."""
from . import easa, embassy, faa, navarea, state
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

    warnings, err, source = navarea.collect(load("navarea.json", {}).get("warnings"), when)
    newest = navarea.newest(warnings)  # of what is held now, new or kept: the feed reads staleness from this
    if err:
        health("nga-navwarnings", False, err, when, newest_item=newest)
    else:
        save("navarea.json", {"source": source, "warnings": warnings})
        health("nga-navwarnings", True, f"{len(warnings)} warnings in force", when, newest_item=newest)
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
    return summary
