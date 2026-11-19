"""The permanent archive of every FAA NMS-API feature Cordon pulls (decided 18 Nov 2026: storage keeps everything; live
views may filter). The subsets in cordon/nms.py are the live view; this is the record.

What is kept: every feature of every pull, bulk and delta, all classifications, not only the subsets, trimmed as
nms.trim() trims (coreNOTAMData.notam, the ICAO translation, the geometry). One record per NOTAM version: the NMS id
(the API's unique NOTAM identifier, stable across pulls; the nmsId query returns one NOTAM, active or inactive) plus
lastUpdated. A version already archived is not written again, so each day's bulk adds only what the deltas missed.
Number plus FIR is not unique (measured on the staging bulk of 18 Nov 2026: 81,818 features, 68,122 number|FIR keys,
81,818 ids), so it is never the archive's key.

Where (durable and free): GitHub release assets on metacog-osint/cordon, one release per UTC month (tag
nms-archive-YYYY-MM) and one asset per UTC day (nms-YYYY-MM-DD.jsonl.gz, gzipped JSON Lines, one record a line:
{"id", "pulled_at", "pull", "feature"}), plus seen.json.gz, the dedupe index. The Actions cache (cache/nms/archive/)
is a working copy only: it evicts after 7 days unused, so nothing relies on it. Each run, today's asset is rebuilt
from the release's copy plus the cache's (a union by record id) and this run's new records, then replaced in the
release; a lost cache reads the asset and the index back from the release. A day whose upload failed stays pending
in the cache and is uploaded by a later run; until then the lane's delta pulls start from the last fully archived
time (archived_to), so a lost cache on top of a failed upload loses nothing a delta can still reach (24 h).
Measured: the staging bulk is 126.7 MB as trimmed JSON Lines, 23.2 MB gzipped (day one); a day of deltas is small.

Replacing an asset: upload as NAME.part, delete NAME, rename NAME.part to NAME, so the release never holds less than
the last good copy; a run that stops half way leaves NAME.part, which the next run reads as the day's copy.

Access: GITHUB_TOKEN (the workflow's own token, contents: write). Without it the archive is kept in the cache only
and every day stays pending.
"""
from __future__ import annotations

import gzip
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from . import nms

REPO = "metacog-osint/cordon"
API = "https://api.github.com"
FORMAT = "cordon-nms-archive/1"
SEEN = "seen.json.gz"
SEEN_KEEP_DAYS = 2        # a version no bulk has listed for this long has left the active set: out of the index
KEEP_LOCAL_DAYS = 3       # uploaded day files kept in the cache this long (the release holds them for good)
RELEASES = f"https://github.com/{REPO}/releases?q=nms-archive"


def tag(day: str) -> str:
    return "nms-archive-" + day[:7]


def asset(day: str) -> str:
    return f"nms-{day}.jsonl.gz"


def rid(f: dict) -> str:
    m = nms.meta(f)
    return f"{m.get('id') or nms.key(f)}|{m.get('lastUpdated') or ''}"


def notes(month: str) -> str:
    return (f"Cordon's permanent archive of FAA NMS-API NOTAMs, {month} (UTC). One asset per UTC day, "
            "nms-YYYY-MM-DD.jsonl.gz: gzipped JSON Lines, one record per NOTAM version (NMS id plus lastUpdated) "
            "first seen in that day's pulls, bulk or delta: {id, pulled_at, pull, feature}, the feature trimmed to "
            "coreNOTAMData.notam, the ICAO translation and the geometry. Every classification is kept, not only "
            "the subsets Cordon publishes. A version already archived is not repeated; today's asset is rebuilt "
            "during the day. seen.json.gz is the dedupe index (format " + FORMAT + ").\n\n"
            + nms.SOURCE_NOTE + "\n" + nms.TERMS + ".")


def about() -> dict:
    return {"where": RELEASES, "format": FORMAT, "release": "nms-archive-YYYY-MM", "asset": "nms-YYYY-MM-DD.jsonl.gz",
            "note": "Every NMS feature of every pull (bulk and delta, all classifications), one record per NOTAM "
                    "version, kept for good. The subset files here are the active set only."}


# ---------- GitHub releases ----------

class _StripAuthRedirect(urllib.request.HTTPRedirectHandler):
    """An asset download redirects to signed storage, which refuses a second credential."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.remove_header("Authorization")
        return new


class GitHub:
    def __init__(self, token: str, opener=None):
        self.token = token
        self.open = opener or urllib.request.build_opener(_StripAuthRedirect()).open
        self.requests = 0

    def _call(self, method: str, url: str, data: bytes | None = None, ctype: str | None = None,
              accept: str = "application/vnd.github+json") -> bytes:
        h = {"User-Agent": nms.UA, "Accept": accept, "Authorization": "Bearer " + self.token,
             "X-GitHub-Api-Version": "2022-11-28"}
        if ctype:
            h["Content-Type"] = ctype
        self.requests += 1
        with self.open(urllib.request.Request(url, data=data, method=method, headers=h), timeout=600) as r:
            return r.read()

    def _json(self, method: str, url: str, body: dict | None = None):
        out = self._call(method, url, json.dumps(body).encode() if body is not None else None,
                         "application/json" if body is not None else None)
        return json.loads(out) if out else None

    def release(self, t: str) -> dict | None:
        try:
            return self._json("GET", f"{API}/repos/{REPO}/releases/tags/{t}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def create(self, t: str) -> dict:
        return self._json("POST", f"{API}/repos/{REPO}/releases",
                          {"tag_name": t, "name": f"NMS NOTAM archive {t[-7:]}", "body": notes(t[-7:]),
                           "make_latest": "false"})

    def download(self, a: dict) -> bytes:
        return self._call("GET", a["url"], accept="application/octet-stream")

    def upload(self, rel: dict, name: str, data: bytes) -> dict:
        base = rel["upload_url"].split("{", 1)[0]
        return json.loads(self._call("POST", f"{base}?name={name}", data, "application/gzip"))

    def delete(self, a: dict) -> None:
        self._call("DELETE", f"{API}/repos/{REPO}/releases/assets/{a['id']}")

    def rename(self, a: dict, name: str) -> dict:
        return self._json("PATCH", f"{API}/repos/{REPO}/releases/assets/{a['id']}", {"name": name})


def current(rel: dict | None, name: str) -> dict | None:
    """The release's copy of an asset: NAME, else the NAME.part a stopped run left."""
    assets = {a["name"]: a for a in (rel or {}).get("assets") or []}
    return assets.get(name) or assets.get(name + ".part")


def replace(gh: GitHub, rel: dict, name: str, data: bytes) -> dict:
    assets = {a["name"]: a for a in rel.get("assets") or []}
    if name + ".part" in assets:
        gh.delete(assets[name + ".part"])
    new = gh.upload(rel, name + ".part", data)
    if name in assets:
        gh.delete(assets[name])
    new = gh.rename(new, name) or {**new, "name": name}
    rel["assets"] = [a for a in rel.get("assets") or [] if a["name"] not in (name, name + ".part")] + [new]
    return new


# ---------- local working copy ----------

def _read_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except ValueError:
        return default


def _records(data: bytes) -> list[dict]:
    out = []
    for line in gzip.decompress(data).decode("utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _encode(recs: list[dict]) -> bytes:
    body = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in recs)
    return gzip.compress(body.encode("utf-8"), 6)


def _union(*sets: list[dict]) -> list[dict]:
    seen, out = set(), []
    for recs in sets:
        for r in recs:
            if r.get("id") not in seen:
                seen.add(r.get("id"))
                out.append(r)
    return sorted(out, key=lambda r: (r.get("pulled_at") or "", r.get("id") or ""))


def run(feats: list[dict], mode: str | None, now: datetime, env: dict | None = None, gh: GitHub | None = None,
        directory=None) -> dict:
    """Archive one pull's features (none for a run that made no pull: pending days are still uploaded). Never
    raises; returns the archive's part of the lane state."""
    env = os.environ if env is None else env
    d = directory or nms.CACHE / "archive"   # read late: nms imports this module
    days_dir = d / "days"
    days_dir.mkdir(parents=True, exist_ok=True)
    meta = _read_json(d / "meta.json", {}) or {}
    meta.setdefault("assets", {})
    pending = set(meta.get("pending") or [])
    day, t = now.strftime("%Y-%m-%d"), nms.iso(now)
    token = env.get("GITHUB_TOKEN")
    if gh is None and token:
        gh = GitHub(token)
    out = {"format": FORMAT, "day": day, "added": 0, "uploaded": [], "status": "ok"}
    rels: dict[str, dict | None] = {}

    def rel_for(dy: str, make: bool = False):
        tg = tag(dy)
        if tg not in rels or (rels[tg] is None and make):
            rels[tg] = gh.release(tg)
            if rels[tg] is None and make:
                rels[tg] = gh.create(tg)
        return rels[tg]

    try:
        # the dedupe index: the cache's, else the release's (this month, then last month), else empty
        seen = None
        sp = d / SEEN
        if sp.exists():
            try:
                seen = json.loads(gzip.decompress(sp.read_bytes()))
            except (OSError, ValueError):
                seen = None
        seen_from = "cache"
        if seen is None and gh is not None:
            seen_from = "none"
            for dy in (day, (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m-%d")):
                a = current(rel_for(dy), SEEN)
                if a:
                    seen, seen_from = json.loads(gzip.decompress(gh.download(a))), "release " + tag(dy)
                    break
        seen = seen if isinstance(seen, dict) else {}
        out["seen_from"] = seen_from

        new = []
        for f in feats or []:
            r = rid(f)
            if r not in seen:
                new.append({"id": r, "pulled_at": t, "pull": mode, "feature": nms.trim(f)})
            seen[r] = day
        if mode == "bulk":                 # a bulk lists the whole active set: what it left out ended
            cut = (now - timedelta(days=SEEN_KEEP_DAYS)).strftime("%Y-%m-%d")
            seen = {k: v for k, v in seen.items() if v >= cut}
        out["added"], out["seen"] = len(new), len(seen)

        # today's file: the cache's copy, unioned with the release's when the release holds a copy the cache
        # did not write (a lost cache, or a run whose cache was never saved)
        lp = days_dir / (day + ".jsonl.gz")
        name = asset(day)
        remote = current(rel_for(day), name) if gh is not None else None
        known = (meta["assets"].get(name) or {}).get("id")
        if remote and (not lp.exists() or remote.get("id") != known):
            base = _records(gh.download(remote))
            local = _records(lp.read_bytes()) if lp.exists() else []
            lp.write_bytes(_encode(_union(base, local, new)))
            pending.add(day)
            out["merged_release_copy"] = len(base)
        elif new:
            with open(lp, "ab") as fh:    # a gzip file may hold several members; readers see one stream
                fh.write(_encode(new))
            pending.add(day)
        sp.write_bytes(gzip.compress(json.dumps(seen, separators=(",", ":")).encode("utf-8"), 6))
        if new or mode == "bulk":
            meta["seen_dirty"] = True
        meta["pending"] = sorted(pending)
        (d / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")

        if gh is None:
            out["status"] = "no-token"
            out["note"] = "GITHUB_TOKEN is not set: archived in the cache only, uploads pending"
        else:
            for dy in sorted(pending):
                p = days_dir / (dy + ".jsonl.gz")
                if not p.exists():
                    pending.discard(dy)
                    continue
                data = p.read_bytes()
                a = replace(gh, rel_for(dy, make=True), asset(dy), data)
                meta["assets"][asset(dy)] = {"id": a.get("id"), "bytes": len(data), "at": t}
                pending.discard(dy)
                out["uploaded"].append(asset(dy))
            if meta.get("seen_dirty"):
                replace(gh, rel_for(day, make=True), SEEN, sp.read_bytes())
                meta["seen_dirty"] = False
            meta["archived_to"] = t
    except Exception as e:  # noqa: BLE001 - the archive never fails the lane; what is not uploaded stays pending
        out["status"] = "failing"
        out["error"] = nms.describe(e)
    meta["pending"] = sorted(pending)
    for p in days_dir.glob("*.jsonl.gz"):       # uploaded days leave the cache after KEEP_LOCAL_DAYS
        if p.name[:10] not in pending and p.name[:10] < (now - timedelta(days=KEEP_LOCAL_DAYS)).strftime("%Y-%m-%d"):
            p.unlink()
    (d / "meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")
    lp = days_dir / (day + ".jsonl.gz")
    out.update(pending=meta["pending"], archived_to=meta.get("archived_to"),
               day_bytes=lp.stat().st_size if lp.exists() else 0, requests=gh.requests if gh else 0)
    return out
