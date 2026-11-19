"""Items the doctrine kit's linter drops from the feed, kept (retention fix C5, 18 Nov 2026).

feed.build() lists each dropped item's id and errors in the feed's `dropped` block, but the item itself never reached
the history log, which is built from the feed. This appends the whole item, once, to data/history/dropped.jsonl (a
committed, append-only file in the history folder that the workflow's History step already commits). An item is
written again only when its content or its errors change."""
import hashlib
import json
from pathlib import Path

FORMAT = "cordon-dropped/1"


def _digest(item: dict, errors: list) -> str:
    return hashlib.sha1(json.dumps([item, errors], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def append(path, dropped: list, items: dict, at: str) -> list:
    """Append the dropped items not already in the file. `dropped` is the feed's [{id, errors}], `items` maps an id to
    the full feature. Returns the lines written."""
    path = Path(path)
    seen = set()
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for ln in fh:
                try:
                    seen.add(json.loads(ln)["digest"])
                except (ValueError, KeyError, TypeError):
                    continue
    out = []
    for x in dropped:
        item = items.get(x["id"])
        dg = _digest(item, x["errors"])
        if dg in seen:
            continue
        seen.add(dg)
        out.append({"format": FORMAT, "at": at, "id": x["id"], "errors": x["errors"], "digest": dg, "item": item})
    if out:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            for line in out:
                fh.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
    return out
