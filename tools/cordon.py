"""Cordon command line. Standard library only.

    python tools/cordon.py collect          fetch every source; update data/ (a failing source keeps its last data)
    python tools/cordon.py build            write site/ (the map page, feed.geojson, map.json) from data/
    python tools/cordon.py check            lint the feed with the doctrine kit; check the registers
"""
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cordon import collect, feed  # noqa: E402
from cordon.common import load, read_jsonl  # noqa: E402
from tic_doctrine import contract, registers  # noqa: E402

SRC, OUT = ROOT / "site_src", ROOT / "site"
LANES = {"advisories.json": "state-travel-advisories", "alerts.json": "us-embassy-alerts",
         "czibs.json": "easa-czib", "navarea.json": "nga-navwarnings"}


def data() -> dict:
    """Every data file, each stamped with its source's last good fetch from health.json."""
    health = load("health.json", {})
    out = {"health": health}
    for name, src in LANES.items():
        d = dict(load(name, {}) or {})
        d["fetched_at"] = (health.get(src) or {}).get("last_ok")
        out[name] = d
    return out


def map_data(d: dict, fc: dict) -> dict:
    """The compact picture the map page draws."""
    adv = d["advisories.json"].get("advisories") or {}
    return {
        "generated_at": fc["generated_at"],
        "advisories": [{"key": k, "iso": r["iso"], "name": r["name"], "level": r["level"], "level_text": r["level_text"],
                        "link": r["link"], "updated": r.get("updated"), "posture": r["posture"]["state"],
                        "sentence": r["posture"]["sentence"]} for k, r in sorted(adv.items())],
        "czibs": [b for b in d["czibs.json"].get("bulletins") or [] if b["status"] == "active"],
        "warnings": [{k: w.get(k) for k in ("id", "number", "category", "headline", "sea", "place", "issued", "geometry")}
                     for w in d["navarea.json"].get("warnings") or [] if w.get("geometry")],
        "alerts": d["alerts.json"].get("posts") or {},
        "changes": sorted(read_jsonl("changes.jsonl"), key=lambda c: c.get("at", ""), reverse=True)[:60],
        "health": d["health"],
        "points": {f["properties"]["id"]: f["geometry"]["coordinates"] for f in fc["features"]
                   if f["geometry"] and f["geometry"]["type"] == "Point" and f["properties"]["id"].startswith("cordon:advisory:")},
    }


def build() -> dict:
    d = data()
    fc = feed.build(d["advisories.json"], d["alerts.json"], d["czibs.json"], d["navarea.json"],
                    datetime.now(timezone.utc))
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SRC, OUT)
    (OUT / "data").mkdir(exist_ok=True)
    (OUT / "data" / "feed.geojson").write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")) + "\n",
                                               encoding="utf-8", newline="\n")
    (OUT / "data" / "map.json").write_text(json.dumps(map_data(d, fc), ensure_ascii=False, separators=(",", ":")) + "\n",
                                           encoding="utf-8", newline="\n")
    return fc


def check() -> list[str]:
    errs = [f"registers: {e}" for e in registers.check(ROOT / "doctrine")]
    d = data()
    fc = feed.build(d["advisories.json"], d["alerts.json"], d["czibs.json"], d["navarea.json"])
    errs += [f"dropped {x['id']}: {x['errors']}" for x in fc["dropped"]]
    regs = registers.ids(ROOT / "doctrine")
    for f in fc["features"]:
        errs += [f"{f['properties']['id']}: {m}" for _, sev, m in contract.check(f, regs) if sev == "error"]
    return errs


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or ["help"])[0]
    if cmd == "collect":
        for k, v in collect.run().items():
            print(f"{k}: {v}")
        return 0
    if cmd == "build":
        fc = build()
        print(f"site/ written: {len(fc['features'])} feed items, {len(fc['dropped'])} dropped")
        return 0
    if cmd == "check":
        errs = check()
        for e in errs[:50]:
            print("  -", e)
        print("Cordon check:", "PASS" if not errs else f"FAIL ({len(errs)} problems)")
        return 1 if errs else 0
    print(__doc__)
    return 0 if cmd == "help" else 2


if __name__ == "__main__":
    sys.exit(main())
