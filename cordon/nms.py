"""The FAA NOTAM Management Service API (NMS-API): the suite's one NOTAM reader (decided 18 Nov 2026).

Cordon holds the suite's only NMS keys and makes every request; other programs read the subset files Cordon
publishes at https://cordon.theintelligence.company/data/notams/ (index.json lists them), never the FAA. Launch
read NMS itself from 16 to 19 Nov 2026; this module is its client, moved here.

Access: OAuth2 client credentials from the environment (NMS_CLIENT_ID, NMS_CLIENT_SECRET, repo secrets set by
hand; never in this repository). NMS_ENV picks the host, "prod" (the default) or "staging". Without both keys the
lane says "waiting" and makes no request.

What it reads (the FAA's limits, onboarding email of 18 Nov 2026 and the NMS-API FAQ: one bulk pull every 24 hours
at most, one delta pull every 3 minutes at most; more needs FAA approval):
  - bulk, at most once in BULK_HOURS: every active NOTAM of each classification in CLASSES (GeoJSON);
  - otherwise a delta: every NOTAM created, replaced or cancelled since the last pull (lastUpdatedDate, at most
    24 h back), applied to the store;
  - with no store and no bulk allowed yet (the first day), a delta from the newest bulk known (SEED_BULK_AT, Launch's)
    or the last archived time, for the archive alone, so nothing since Launch's last bulk is missed.
The 24 h rule is kept against the newest bulk time Cordon knows of: its committed state (data/nms_state.json), its
published index, and SEED_BULK_AT (Launch's last bulk on the same account), so a lost cache never means a second
bulk inside a day.

The store (cache/nms/store.json.gz, the private Actions cache, never committed) holds only NOTAMs some subset
keeps, and the international NOTAMs cordon/significance.py ranks, keyed by number and FIR: a replacing (NOTAMR) or
cancelling (NOTAMC) notice removes the one it names; a
notice ended over ENDED_KEEP_DAYS ago is dropped. Lost cache: the store is rebuilt from Cordon's own published subset files,
then a delta from the time those files were pulled to (the ranked NOTAMs come back with the next bulk).

Significance (method tic-significance-0.1, cordon/significance.py): each pull's features update the baseline
(data/nms_significance.json, committed, never pruned: daily counts of new NOTAMs per FIR, Q-code subject and
cause group, and size histograms; built by the lane from the archive's release day files when missing)
and the chains (one entry per ranked NOTAM held, for dedupe and dynamics: working state, in the Actions cache beside
the archive's working copy, cache/nms/archive/, so the cache's path list is unchanged). significant.json holds the
active international NOTAMs ranked notable or significant.

Every feature of every pull is also kept for good in cordon/nmsarchive.py (GitHub release assets, one per UTC day;
the store and subsets are the live view only). Subsets are the active set at the last pull, each a GeoJSON FeatureCollection of NMS's own features, trimmed to
coreNOTAMData.notam and the ICAO translation. Their rules use NMS's structured fields (selectionCode, maximumFl,
effectiveStart/End), so a reader applies its own rules on top. Measured on the staging bulk of 18 Nov 2026 (81,818
NOTAMs, 142 MB raw): launch-areas 6,648 (13.8 MB), gnss 3,836 (4.8 MB, 3,194 of them procedure notices).

Terms (FAA NMS-API terms of service, 7 Oct 2026, and FAQ): redistribution allowed; not to be called FAA data; NMS
is not the authoritative source for NOTAMs issued outside the United States. SOURCE_NOTE says so in every file.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import common, nmsarchive, significance
from .common import DATA, ROOT, describe, load, save

HOSTS = {"staging": "https://api-staging.cgifederal-aim.com", "prod": "https://api-nms.aim.faa.gov"}
UA = "tic-cordon (+https://cordon.theintelligence.company)"
CLASSES = ("INTERNATIONAL", "FDC", "MILITARY", "DOMESTIC")
BULK_HOURS = 24          # one bulk pull a day at most (FAA production limit)
DELTA_MAX_HOURS = 23.5   # lastUpdatedDate reaches 24 h back at most
OVERLAP_S = 60           # each delta starts a minute before the last one ended (FAA's advice)
PAUSE_S = 1.2            # between requests (pre-production: one a second)
SEED_BULK_AT = "2026-11-18T23:26:20Z"   # Launch's last bulk pull on this account, before the keys moved here
STATE = "nms_state.json"
CACHE = ROOT / "cache" / "nms"
STORE = CACHE / "store.json.gz"
OUT = CACHE / "out"
PUBLISHED = "https://cordon.theintelligence.company/data/notams/"
SOURCE_NOTE = ("NOTAMs read through the FAA NOTAM Management Service API (NMS-API) by Cordon. Not FAA data as "
               "published by Cordon, and not the authoritative source for NOTAMs issued outside the United States.")
TERMS = "FAA NMS-API terms of service (7 Oct 2026): redistribution allowed; not to be called FAA data"
ENDED_KEEP_DAYS = 16     # an ended notice stays this long (the FAA lists some well past their end; Launch's GNSS
                         # history keeps 14 days plus 2); readers apply their own end rules
MAX_DAYS = 62            # launch-areas: a window over 62 days is a standing notice, not a closure
MIN_UPPER_FL = 100       # launch-areas: a launch closure reaches at least FL100
GNSS_WORDS = re.compile(r"\b(?:GPS|GNSS|GLONASS|GALILEO|BEIDOU|RAIM|WAAS|EGNOS|SBAS|GBAS|MSAS|GAGAN|SDCM|NAVSTAR|"
                        r"SATELLITE NAV\w*)\b", re.I)
REFERS = re.compile(r"\bNOTAM[RC]\s+([A-Z]\d{4}/\d{2})\b")


class Waiting(Exception):
    """No keys in the environment: the lane waits."""


# ---------- the client ----------

class Client:
    def __init__(self, env: dict | None = None, opener=None, pause: float = PAUSE_S):
        env = os.environ if env is None else env
        self.cid, self.secret = env.get("NMS_CLIENT_ID"), env.get("NMS_CLIENT_SECRET")
        if not (self.cid and self.secret):
            raise Waiting("NMS_CLIENT_ID and NMS_CLIENT_SECRET are not set")
        self.env_name = env.get("NMS_ENV") or "prod"
        self.host = HOSTS[self.env_name]
        self.open = opener or urllib.request.urlopen
        self.pause = pause
        self.token, self.token_until, self.requests, self._last = None, 0.0, 0, 0.0

    def _call(self, req: urllib.request.Request, timeout: int = 120) -> bytes:
        wait = self.pause - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        with self.open(req, timeout=timeout) as r:
            body = r.read()
        return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body

    def _auth(self) -> str:
        if self.token and time.monotonic() < self.token_until:
            return self.token
        basic = base64.b64encode(f"{self.cid}:{self.secret}".encode()).decode()
        req = urllib.request.Request(self.host + "/v1/auth/token", data=b"grant_type=client_credentials",
                                     method="POST", headers={"User-Agent": UA, "Authorization": "Basic " + basic,
                                                             "Content-Type": "application/x-www-form-urlencoded"})
        j = json.loads(self._call(req, 60))
        self.token = j["access_token"]
        self.token_until = time.monotonic() + int(j.get("expires_in") or 1799) - 120
        return self.token

    def get(self, path: str, params: dict | None = None, fmt: str | None = "GEOJSON", timeout: int = 300) -> bytes:
        url = self.host + path + ("?" + urllib.parse.urlencode(params) if params else "")
        h = {"User-Agent": UA, "Authorization": "Bearer " + self._auth(), "Accept": "application/json"}
        if fmt:
            h["nmsResponseFormat"] = fmt
        return self._call(urllib.request.Request(url, headers=h), timeout)

    def classification(self, name: str) -> list[dict]:
        """Every active NOTAM of one classification: a content path, then the file it points to."""
        j = json.loads(self.get("/nmsapi/v1/notams", {"classification": name, "allowRedirect": "false"}))
        path = (j.get("data") or {}).get("url")
        if not path:
            raise ValueError(f"no content path for {name}: {str(j)[:160]}")
        body = self.get(path if path.startswith("/") else urllib.parse.urlparse(path).path, fmt=None)
        return features(json.loads(body))

    def delta(self, since: datetime) -> list[dict]:
        return features(json.loads(self.get("/nmsapi/v1/notams", {"lastUpdatedDate": iso(since)})))


def features(j) -> list[dict]:
    """The GeoJSON features of a response, a classification file or a FeatureCollection."""
    if isinstance(j, list):
        return j
    g = j.get("data", {}).get("geojson") if isinstance(j.get("data"), dict) else None
    if g is None:
        g = j
    return g if isinstance(g, list) else g.get("features") or []


def iso(d: datetime | None) -> str | None:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def _dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    except ValueError:
        return None


# ---------- one NOTAM ----------

def meta(f: dict) -> dict:
    return ((f.get("properties") or {}).get("coreNOTAMData") or {}).get("notam") or {}


def icao_text(f: dict) -> str | None:
    core = (f.get("properties") or {}).get("coreNOTAMData") or {}
    for t in core.get("notamTranslation") or []:
        if t.get("type") == "ICAO" and t.get("formattedText"):
            return t["formattedText"]
    return None


def _loc(m: dict) -> str:
    return m.get("icaoLocation") or m.get("location") or ""


def key(f: dict) -> str:
    """Number, FIR and location. Number and FIR alone are not unique: a multi-FIR NOTAM (LFXX, CZEG) comes once
    per location (staging bulk of 18 Nov 2026: 7,593 subset features, 7,338 number|FIR keys, 255 lost that way)."""
    m = meta(f)
    return f"{m.get('number')}|{m.get('affectedFir') or ''}|{_loc(m)}"


def refers(f: dict) -> str | None:
    """The store key of the NOTAM a replacing or cancelling one names, from its ICAO text."""
    m = meta(f)
    if m.get("type") not in ("R", "C"):
        return None
    hit = REFERS.search(icao_text(f) or "")
    return f"{hit.group(1)}|{m.get('affectedFir') or ''}|{_loc(m)}" if hit else None


def trim(f: dict) -> dict:
    core = (f.get("properties") or {}).get("coreNOTAMData") or {}
    tr = [t for t in core.get("notamTranslation") or [] if t.get("type") == "ICAO"]
    return {"type": "Feature", "geometry": f.get("geometry"),
            "properties": {"coreNOTAMData": {"notam": core.get("notam") or {}, "notamTranslation": tr}}}


def _fl(v, default: int = 999) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _permanent(m: dict) -> bool:
    return str(m.get("effectiveEnd") or "").upper().startswith("PERM")


# Launch's launch words (Launch's launch/notam.py LAUNCH_WORDS, 19 Nov 2026): a notice with them is a candidate
# whatever its Q-code or limits, because Launch's parser reads some texts (three-letter military FIRs) as having no
# Q) line at all.
LAUNCH_WORDS = re.compile(
    r"AEROSPACE|ROCKET|SPACE ?(?:DEBRIS|LAUNCH|VEHICLE|CRAFT|OPERATIONS|FLIGHT|FLT)|RE-?ENTRY|SPLASH ?DOWN|"
    r"UNBURNED DEBRIS|FALLING (?:DEBRIS|OBJECTS|PARTS)|DEBRIS RETURN|LAUNCH VEHICLE|STAGE|MISSILE")
QLINE = re.compile(r"Q\)\s*[A-Z0-9]{3,4}/(Q[A-Z]{4})/[^/\n]*/[^/\n]*/[^/\n]*/(\d{3})/(\d{3})")


def launch_area(f: dict) -> bool:
    """launch-areas: a restricted, danger or prohibited area, a warning, an "other" notice (Q-code subject R, W or X)
    or one whose ICAO text has no Q) line; not a cancellation or a permanent notice; open at most MAX_DAYS; with a
    Q) line, reaching at least MIN_UPPER_FL. The Q-code and limits are read from the ICAO text, as Launch reads them
    (NMS's selectionCode can carry a code the text does not); Launch's own rules (launch/nms.py keep()) then choose
    the closures. Measured 19 Nov 2026 on the staging bulk: none of Launch's closures lost this way."""
    m, text = meta(f), icao_text(f)
    if not text or m.get("type") == "C" or _permanent(m):
        return False
    hit = QLINE.search(text)
    if hit and (hit.group(1)[1:2] not in ("R", "W", "X") or int(hit.group(3)) < MIN_UPPER_FL) \
            and not LAUNCH_WORDS.search(text):
        return False
    a, b = _dt(m.get("effectiveStart")), _dt(m.get("effectiveEnd"))
    return not (a and b and (b - a) > timedelta(days=MAX_DAYS))


def gnss(f: dict) -> bool:
    """gnss: a Q-code of subject G (GNSS services), in NMS's selectionCode or the ICAO text's Q) line, or a GNSS
    word anywhere in the text; cancellations included, so a reader sees them. Launch's gnss-1.0 rule (signal words,
    procedure names taken out) chooses the GNSS NOTAMs from these."""
    m, text = meta(f), icao_text(f) or ""
    hit = QLINE.search(text)
    return ((m.get("selectionCode") or "")[1:2] == "G" or bool(hit and hit.group(1)[1:2] == "G")
            or bool(GNSS_WORDS.search(text or m.get("text") or "")))


SUBSETS = {"launch-areas": launch_area, "gnss": gnss}


def wanted(f: dict) -> list[str]:
    return [name for name, rule in SUBSETS.items() if rule(f)]


# ---------- the store ----------

def apply(store: dict, feats: list[dict], now: datetime, replace_all: bool = False) -> dict:
    """Bulk (replace_all) or delta features -> the store. Returns counts."""
    if replace_all:
        store.clear()
    counts = {"features": len(feats), "added": 0, "removed": 0}
    for f in feats:
        ref = refers(f)
        if ref and store.pop(ref, None) is not None:
            counts["removed"] += 1
        if wanted(f) or significance.candidate(f):
            store[key(f)] = trim(f)
            counts["added"] += 1
    cut = now - timedelta(days=ENDED_KEEP_DAYS)
    for k in [k for k, v in store.items() if (_dt(meta(v).get("effectiveEnd")) or now) < cut]:
        del store[k]
        counts["removed"] += 1
    counts["held"] = len(store)
    return counts


def load_store() -> dict | None:
    if not STORE.exists():
        return None
    try:
        return json.loads(gzip.decompress(STORE.read_bytes()))
    except (OSError, ValueError):
        return None


def save_store(store: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    STORE.write_bytes(gzip.compress(json.dumps(store, separators=(",", ":")).encode("utf-8"), 6))


def from_published(fetch=None) -> tuple[dict | None, dict | None]:
    """(store, index) rebuilt from Cordon's own published files, or (None, index or None): the subsets, and the
    ranked international NOTAMs in significant.json (their significance block dropped; it is judged again), so the
    ranked list does not read empty until the next bulk pull. Routine international NOTAMs return with that bulk."""
    fetch = fetch or _get_json
    try:
        index = fetch(PUBLISHED + "index.json")
    except Exception:  # noqa: BLE001 - nothing published yet, or the site is down: no rebuild
        return None, None
    store = {}
    try:
        for s in index.get("subsets") or []:
            for f in features(fetch(PUBLISHED + s["file"])):
                store[key(f)] = f
        sig = index.get("significance") or {}
        if sig.get("file") and sig.get("status") == "ok":
            for f in features(fetch(PUBLISHED + sig["file"])):
                props = {k: v for k, v in (f.get("properties") or {}).items() if k != "significance"}
                store.setdefault(key(f), {**f, "properties": props})
    except Exception:  # noqa: BLE001 - a partial rebuild would publish a partial set: none
        return None, index
    return store, index


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


# ---------- one run ----------

def newest_bulk(*times: str | None) -> datetime | None:
    ds = [d for d in (_dt(t) for t in times) if d]
    return max(ds) if ds else None


def pull(client: Client, state: dict, store: dict | None, now: datetime, published: dict | None = None,
         pulled_to: str | None = None) -> tuple[dict, dict | None, list[dict]]:
    """One run's requests. A bulk pull when the newest known bulk is BULK_HOURS old; else a delta when there is a
    store and its last pull (pulled_to, else the state's) is under DELTA_MAX_HOURS old; else no request ("window":
    wait for the bulk window). A delta starts at the archive's archived_to when that is earlier and still in reach,
    so what a failed archive upload held is pulled again. Returns (the lane's new state, the store, the features)."""
    bulk_at = newest_bulk(state.get("bulk_at"), (published or {}).get("bulk_at"), SEED_BULK_AT)
    last = _dt(pulled_to or state.get("pulled_to")) if store is not None else None
    out = {"env": client.env_name, "bulk_at": iso(bulk_at), "pulled_to": iso(last)}
    feats: list[dict] = []
    if now - bulk_at >= timedelta(hours=BULK_HOURS):
        feats, by_class = [], {}
        for c in CLASSES:
            got = client.classification(c)
            by_class[c] = len(got)
            feats += got
        store = {}
        counts = apply(store, feats, now, replace_all=True)
        counts["by_class"] = by_class
        out.update(mode="bulk", bulk_at=iso(now), pulled_to=iso(now), counts=counts)
    elif store is not None and last and now - last < timedelta(hours=DELTA_MAX_HOURS):
        arch = _dt(state.get("archived_to"))
        since = arch if arch and arch < last and now - arch < timedelta(hours=DELTA_MAX_HOURS) else last
        feats = client.delta(since - timedelta(seconds=OVERLAP_S))
        out.update(mode="delta", pulled_to=iso(now), delta_from=iso(since), counts=apply(store, feats, now))
    else:
        # No store and no bulk allowed yet (Cordon's first day, or a lost cache with nothing published): pull deltas
        # for the archive alone, from the newest bulk known or the last archived time, while that is in reach, so
        # nothing changed since Launch's last bulk on this account is missed. No subsets until the bulk.
        arch = _dt(state.get("archived_to"))
        since = max(d for d in (arch, bulk_at) if d)
        nxt = iso(bulk_at + timedelta(hours=BULK_HOURS))
        if now - since < timedelta(hours=DELTA_MAX_HOURS):
            feats = client.delta(since - timedelta(seconds=OVERLAP_S))
            out.update(mode="archive-delta", delta_from=iso(since), counts={"features": len(feats)},
                       note="no store yet: this delta goes to the archive only; the bulk pull is allowed from " + nxt)
        else:
            out.update(mode="window", note="no store to update; the next bulk pull is allowed from " + nxt)
    out["requests"] = client.requests
    return out, store, feats


def write_out(store: dict, state: dict, now: datetime) -> dict:
    """The subset files and index.json into cache/nms/out/, for build to publish. Returns the index."""
    OUT.mkdir(parents=True, exist_ok=True)
    subsets = []
    for name in SUBSETS:
        feats = [f for k, f in sorted(store.items()) if name in wanted(f)]
        body = json.dumps({"type": "FeatureCollection", "subset": name, "source_note": SOURCE_NOTE,
                           "pulled_to": state.get("pulled_to"), "features": feats},
                          ensure_ascii=False, separators=(",", ":")) + "\n"
        (OUT / f"{name}.json").write_text(body, encoding="utf-8", newline="\n")
        subsets.append({"name": name, "file": f"{name}.json", "url": PUBLISHED + f"{name}.json", "n": len(feats),
                        "bytes": len(body.encode("utf-8")), "rule": " ".join((SUBSETS[name].__doc__ or "").split())})
    index = {"program": "cordon", "dataset": "notams", "source": "FAA NMS-API", "source_note": SOURCE_NOTE,
             "terms": TERMS, "env": state.get("env"), "lane_status": state.get("status"),
             "lane_note": state.get("note") or state.get("error"), "mode": state.get("mode"),
             "bulk_at": state.get("bulk_at"), "pulled_to": state.get("pulled_to"), "generated_at": iso(now),
             "held": len(store), "subsets": subsets, "significance": write_significant(store, state, now),
             "archive": {**nmsarchive.about(), **{
                 k: (state.get("archive") or {}).get(k) for k in ("status", "archived_to", "pending")}},
             "about": "The active set at the last pull. Read these files, never the FAA: Cordon holds the suite's "
                      "only NMS keys, and the FAA allows one bulk pull a day."}
    (OUT / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                                    newline="\n")
    return index


# ---------- significance (cordon/significance.py) ----------

SIG_BASELINE = "nms_significance.json"   # in data/, committed
SIG_FILE = "significant.json"
BACKFILL_BUDGET_S = 240   # a run spends at most this on the backfill, then carries on next run
ARCHIVE_FIRST_MONTH = "2026-11"   # the archive's first release (nms-archive-2026-11)
SIG_ABOUT = ("International NOTAMs (classification INTL) of the restriction and warning Q-code subjects, ranked by "
             "what Cordon alone knows: cause (Q-code subject, then the NOTAM's own words), rarity against Cordon's own "
             "history of new NOTAMs per FIR, subject and cause group (labels need 90 days of history; before that, history_short), "
             "the chain's dynamics, and size against the FIR's own. Not a warning and not a prediction. Coincidence "
             "and consequence come later from COP. Space operations (Launch's) and GNSS (Noisefloor's) are left out.")


def chains_path() -> Path:
    """The chains' working copy: inside the archive's cached directory, so the cache's path list is unchanged."""
    return CACHE / "archive" / "significance-chains.json.gz"


def stamp_path() -> Path:
    """The baseline time the chains were saved with, beside them in the cache."""
    return CACHE / "archive" / "significance-chains.stamp"


def load_significance() -> tuple[dict | None, dict | None]:
    """(baseline or None, chains or None) from data/ and the cache. Chains saved with another baseline time than the
    committed baseline's are treated as lost: the cache and the data commit are saved apart (a failed data push, or a
    cache save that did not land), and chains ahead of the baseline would take the NOTAMs the baseline never counted
    for repeats, never to be counted."""
    b = load(SIG_BASELINE, None)
    chains = None
    p = chains_path()
    if p.exists():
        try:
            chains = json.loads(gzip.decompress(p.read_bytes()))
        except (OSError, ValueError):
            chains = None
    st = stamp_path()
    if chains is not None and b is not None and st.exists():
        if st.read_text(encoding="utf-8").strip() != (b.get("updated_at") or ""):
            chains = None
    return b, chains


def save_significance(b: dict, chains: dict) -> None:
    common.DATA.mkdir(parents=True, exist_ok=True)
    (common.DATA / SIG_BASELINE).write_text(significance.dumps(b), encoding="utf-8", newline="\n")
    p = chains_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gzip.compress(json.dumps(chains, separators=(",", ":")).encode("utf-8"), 6))
    stamp_path().write_text(b.get("updated_at") or "", encoding="utf-8")


def archive_pulls(data: bytes):
    """(pulled_at, features) for each pull in one archive day file's bytes, in time order (its records are sorted by
    pulled_at), streamed."""
    import io
    import itertools
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        recs = (json.loads(line) for line in io.TextIOWrapper(gz, encoding="utf-8") if line.strip())
        for t, grp in itertools.groupby(recs, key=lambda r: r["pulled_at"]):
            yield t, [r["feature"] for r in grp]


def archive_days(gh, now: datetime) -> list[tuple[str, dict]]:
    """(day, asset) for every day file in the archive's releases, oldest first, from ARCHIVE_FIRST_MONTH to now's
    month (a NAME.part a stopped run left stands in for a missing NAME, as nmsarchive.current() reads it)."""
    out, mo = [], datetime.fromisoformat(ARCHIVE_FIRST_MONTH + "-01")
    while mo.strftime("%Y-%m") <= now.strftime("%Y-%m"):
        rel = gh.release(nmsarchive.tag(mo.strftime("%Y-%m-%d")))
        names = {a["name"] for a in (rel or {}).get("assets") or []}
        for name in sorted(names):
            hit = re.fullmatch(r"nms-(\d{4}-\d{2}-\d{2})\.jsonl\.gz(\.part)?", name)
            if hit and not (hit.group(2) and name[:-5] in names):
                out.append((hit.group(1), nmsarchive.current(rel, nmsarchive.asset(hit.group(1)))))
        mo = (mo + timedelta(days=32)).replace(day=1)
    return out


def backfill(b: dict | None, chains: dict | None, now: datetime, gh, budget_s: float = BACKFILL_BUDGET_S
             ) -> tuple[dict | None, dict, dict]:
    """The baseline built from the archive's release day files, oldest first, resumable: each run processes days
    until budget_s is spent and records how far it got (baseline backfill.to); the next run carries on. A baseline
    that does not start at the archive's first day, or lost chains mid-way, starts over. Returns (baseline,
    chains, report)."""
    t0 = time.monotonic()
    days = archive_days(gh, now)
    if not days:
        return b, chains or {}, {"status": "no archive days"}
    first = days[0][0]
    bf = (b or {}).get("backfill") or {}
    if b is None or bf.get("from") != first or chains is None:
        b, chains, bf = None, {}, {"from": first, "to": None, "done": False}
    done_days = 0
    for day, a in days:
        if bf.get("to") and day <= bf["to"]:
            continue
        if done_days and time.monotonic() - t0 > budget_s:
            break                                       # at least one day a run, so it always moves on
        b, chains, _ = significance.replay(archive_pulls(gh.download(a)), b, chains)
        bf["to"] = day
        done_days += 1
    bf["done"] = bf.get("to") == days[-1][0]
    if b is not None:
        b["backfill"] = {**bf, "at": iso(now)}
    return b, chains, {"status": "done" if bf["done"] else "partial", "days": done_days, "from": first,
                       "to": bf.get("to"), "of": len(days), "seconds": round(time.monotonic() - t0, 1)}


def update_significance(feats: list[dict], now: datetime, env: dict | None = None, gh=None,
                        mode: str | None = None) -> dict:
    """This pull's features into the baseline and the chains; saves both. Never raises.

    Until the baseline holds the whole archive (its backfill block done), the lane builds it from the archive's
    release day files itself (backfill(), bounded by BACKFILL_BUDGET_S a run, resumed next run), with the workflow's
    GITHUB_TOKEN; this pull is already in today's day file, so it is counted there. Without a token a missing
    baseline starts today, and a later run with one rebuilds it. Missing chains (a lost cache) after the backfill
    are rebuilt without counting again what the baseline already counted: the baseline keeps that time as
    rechain_before until a bulk pull (mode "bulk") has brought every held NOTAM back into the chains, since the runs
    between see only deltas and the NOTAMs held from before come back unchained with the bulk."""
    try:
        env = os.environ if env is None else env
        b, chains = load_significance()
        out = {"status": "ok"}
        if gh is None and env.get("GITHUB_TOKEN"):
            gh = nmsarchive.GitHub(env["GITHUB_TOKEN"])
        if not ((b or {}).get("backfill") or {}).get("done") and gh is not None:
            b, chains, out["backfill"] = backfill(b, chains, now, gh)
            if b is None:
                return {"status": "waiting", "backfill": out["backfill"]}
            if not b["backfill"]["done"]:
                save_significance(b, chains)
                out.update(status="backfilling", start=b["start"], updated_at=b["updated_at"], chains=len(chains))
                return out
        if b is None:
            b = significance.new_baseline(now.strftime("%Y-%m-%d"))
            out["note"] = "baseline started " + b["start"] + " without a GITHUB_TOKEN; a run with one backfills it"
        counted_before = b.get("rechain_before")
        if chains is None:
            chains = {}
            counted_before = b.get("updated_at") or counted_before
            if counted_before:
                b["rechain_before"] = counted_before
            out["chains_rebuilt"] = True
        if feats:
            out["counts"] = significance.update(b, chains, feats, now, counted_before=counted_before)
            if mode == "bulk":
                b.pop("rechain_before", None)               # every held NOTAM is chained again
        if b.get("rechain_before"):
            out["rechain_before"] = b["rechain_before"]
        out["pruned"] = significance.prune(chains, now)
        save_significance(b, chains)
        out.update(start=b["start"], updated_at=b["updated_at"], chains=len(chains))
        return out
    except Exception as e:  # noqa: BLE001 - significance never fails the lane; nothing half-built is saved
        return {"status": "failing", "error": describe(e)}


def write_significant(store: dict, state: dict, now: datetime) -> dict:
    """significant.json into cache/nms/out/: the active international NOTAMs ranked notable or significant. Returns
    its index entry."""
    entry = {"name": "significant", "file": SIG_FILE, "url": PUBLISHED + SIG_FILE, "method": significance.METHOD,
             "rule": "International NOTAMs ranked by tic-significance-0.1 (cause, rarity, dynamics; no coincidence or "
                     "consequence yet): notable and significant only, active or still to come."}
    try:
        b, chains = load_significance()
        if b is None:
            return {**entry, "status": "no baseline"}
        feats, tiers = significance.ranked(store, b, chains or {}, now)
        body = json.dumps({"type": "FeatureCollection", "dataset": "significant", "method": significance.METHOD,
                           "source_note": SOURCE_NOTE, "pulled_to": state.get("pulled_to"), "generated_at": iso(now),
                           "baseline": {"start": b.get("start"), "updated_at": b.get("updated_at"),
                                        "history_days": significance.day_of(b, now),
                                        "min_history_days": significance.MIN_HISTORY_DAYS},
                           "tiers": tiers, "about": SIG_ABOUT, "features": feats},
                          ensure_ascii=False, separators=(",", ":")) + "\n"
        (OUT / SIG_FILE).write_text(body, encoding="utf-8", newline="\n")
        return {**entry, "n": len(feats), "bytes": len(body.encode("utf-8")), "tiers": tiers, "status": "ok"}
    except Exception as e:  # noqa: BLE001 - never fails the lane; the index says why
        return {**entry, "status": "failing", "error": describe(e)}


def collect(now: datetime | None = None, env: dict | None = None, opener=None, fetch=None) -> tuple[dict, bool]:
    """The lane: (state saved to data/nms_state.json, whether a request was made). Never raises."""
    now = now or datetime.now(timezone.utc)
    prev = load(STATE, {}) or {}
    try:
        client = Client(env, opener=opener)
    except Waiting as w:
        state = {**prev, "status": "waiting", "note": str(w), "checked_at": iso(now)}
        save(STATE, state)
        held = load_store()
        if held is not None:                # keys gone after a good run: the last set stays published, marked
            write_out(held, state, now)
        return state, False
    store = load_store()
    rebuilt, since = False, None
    if store is None:                       # lost cache: rebuild from the published files, delta from their time
        store, published = from_published(fetch)
        rebuilt = store is not None
        since = (published or {}).get("pulled_to") if rebuilt else None
    else:
        try:
            published = (fetch or _get_json)(PUBLISHED + "index.json")
        except Exception:  # noqa: BLE001 - only read for its bulk time
            published = None
    try:
        res, store, feats = pull(client, prev, store, now, published, pulled_to=since)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        state = {**{k: v for k, v in prev.items() if k != "note"}, "status": "failing", "error": describe(e),
                 "checked_at": iso(now), "requests": client.requests}
        if rebuilt:
            state["pulled_to"] = since
        save(STATE, state)
        if store is not None:               # the last good set stays published, marked failing
            write_out(store, state, now)
        return state, True
    state = {**res, "status": "window" if res["mode"] == "window" else "ok", "checked_at": iso(now),
             "rebuilt_from_published": rebuilt}
    # every feature of this pull into the permanent archive (also uploads days a failed run left pending)
    arch = nmsarchive.run(feats, res["mode"] if feats else None, now, env, directory=CACHE / "archive")
    state["archive"] = {k: arch.get(k) for k in ("status", "error", "note", "day", "added", "uploaded", "pending",
                                                 "archived_to", "day_bytes", "seen", "seen_from")}
    state["archived_to"] = arch.get("archived_to") or prev.get("archived_to")
    state["significance"] = update_significance(feats, now, env, mode=res["mode"])
    if res["mode"] in ("bulk", "delta"):
        save_store(store)
    if store is not None:
        index = write_out(store, state, now)
        state["subsets"] = {s["name"]: s["n"] for s in index["subsets"]}
        state["significance"]["tiers"] = index["significance"].get("tiers")
    save(STATE, state)
    return state, client.requests > 0
