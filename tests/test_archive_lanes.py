"""Private archive lanes (update.yml, step "Private archive (NMS days, data, history and site, to tic-archive)"):
every file a run leaves outside the tracked code that the public copies replace or keep only for a while lands in
the private archive (tools/tic_archive.py, metacog-osint/tic-archive) and restores byte for byte, and nothing the
archive holds is ever deleted, shortened or replaced.

The run tree is made in a temporary folder, never from the repository's own data/: the NMS archive's working copy
from real cordon/nmsarchive.py runs against a stand-in GitHub, data/ and site/ files, and data/history/ from the
doctrine kit's history command as the workflow calls it. The workflow's own tic_archive.py commands, read from
update.yml, then run against a local DirStore (GhStore replaced, any subprocess call fails the test), and the step's
own shell runs under bash with python and date replaced."""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from cordon import nmsarchive as na  # noqa: E402
from test_nms import feat  # noqa: E402
from test_nmsarchive import FakeGitHub  # noqa: E402

_spec = importlib.util.spec_from_file_location("tic_archive_lanes_tool", ROOT / "tools" / "tic_archive.py")
ta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ta)

WF = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8").replace("\r\n", "\n")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").replace("\r\n", "\n")
PROGRAM = "cordon"
LANES = {"nms", "data", "history", "site", "notams"}
STEP_NAME = "Private archive (NMS days, data, history and site, to tic-archive)"
TODAY = "2026-11-27"
FIRST = datetime(2026, 11, 27, 1, 10, tzinfo=timezone.utc)
SECOND = datetime(2026, 11, 29, 1, 10, tzinfo=timezone.utc)
UTC = timezone.utc


def steps() -> dict[str, str]:
    """The update job's steps by name (unnamed steps by their id, else their action)."""
    body = WF.split("\n  update:\n", 1)[1].split("\n    steps:\n", 1)[1]
    out = {}
    for chunk in re.split(r"(?m)^      - ", body)[1:]:
        m = re.match(r"name: (.+)|id: (\S+)|uses: (\S+)", chunk)
        out[(m.group(1) or m.group(2) or m.group(3)).strip()] = chunk
    return out


STEPS = steps()


def step(prefix: str) -> str:
    (name,) = [n for n in STEPS if n.startswith(prefix)]
    return STEPS[name]


def archive_calls(text: str, cmd: str) -> list[list[str]]:
    """Every `python tools/tic_archive.py <cmd> ...` in a text, as argv after the script name."""
    flat = re.sub(r"\\\n\s*", " ", text)
    return [[m.group(1), *shlex.split(m.group(2))]
            for m in re.finditer(r"python tools/tic_archive\.py (" + cmd + r")\b([^;|&\n]*)", flat)]


def arg(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, t in enumerate(argv) if t == flag]


def put_calls(today: str = TODAY) -> list[list[str]]:
    return [[t.replace("$today", today) for t in c] for c in archive_calls(step("Private archive"), "put")]


def lane_of(argv: list[str]) -> str:
    return arg(argv, "--lane")[0]


def tree(root: Path) -> dict[str, str]:
    """{posix path relative to root: sha256} for every file."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def fixed_clock(now: datetime):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.astimezone(tz)
    return Clock


def run_archive(argv: list[str], cwd: Path, store: Path, now: datetime = FIRST) -> int:
    """One tic_archive.py command as the workflow gives it, in cwd, against a DirStore at store."""
    def no_subprocess(*a, **k):
        raise AssertionError("an archive command tried to run a subprocess (gh): nothing may leave the test")

    old = os.getcwd()
    os.chdir(cwd)
    try:
        with mock.patch.object(ta, "GhStore", lambda *a, **k: ta.DirStore(store)), \
                mock.patch.object(ta, "datetime", fixed_clock(now)), \
                mock.patch.object(subprocess, "run", no_subprocess):
            return ta.main(argv)
    finally:
        os.chdir(old)


def put_all(run_root: Path, store: Path, now: datetime, today: str, lanes=LANES) -> dict[str, int]:
    return {lane_of(c): run_archive(c, run_root, store, now) for c in put_calls(today) if lane_of(c) in lanes}


def store_files(store: Path) -> dict[str, str]:
    """Every asset the archive holds: {tag/name: sha256}."""
    return tree(store) if store.exists() else {}


# ---------- the run tree ----------

def nms_runs(directory: Path, gh: FakeGitHub, runs) -> None:
    for now, mode, feats in runs:
        out = na.run(feats, mode, now, env={}, gh=na.GitHub("t", opener=gh), directory=directory)
        assert out["status"] == "ok", out


RUNS_TO_27 = [
    (datetime(2026, 11, 25, 23, 30, tzinfo=UTC), "bulk", [feat("A1/26"), feat("A2/26"), feat("A3/26")]),
    (datetime(2026, 11, 26, 6, 0, tzinfo=UTC), "delta", [feat("A2/26"), feat("A4/26")]),
    (datetime(2026, 11, 26, 18, 0, tzinfo=UTC), "delta", [feat("A1/26", lu="2026-11-26T17:00:00.000Z"),
                                                          feat("A5/26")]),
    (datetime(2026, 11, 27, 1, 0, tzinfo=UTC), "delta", [feat("A6/26")]),
]
RUNS_TO_29 = [
    (datetime(2026, 11, 27, 23, 0, tzinfo=UTC), "bulk", [feat("A6/26"), feat("A7/26")]),
    (datetime(2026, 11, 28, 12, 0, tzinfo=UTC), "delta", [feat("A8/26")]),
    (datetime(2026, 11, 29, 1, 0, tzinfo=UTC), "delta", [feat("A9/26")]),
]

FEED = {"type": "FeatureCollection", "generated_at": "2026-11-27T01:00:00Z",
        "health": {"navwarn": {"state": "fresh", "last_ok": "2026-11-27T01:00:00Z",
                               "checked_at": "2026-11-27T01:00:00Z"}},
        "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [56.3, 26.6]},
                      "properties": {"id": "cordon:navwarn:hydropac-1", "lane": "navwarn", "source": "navwarn",
                                     "title": "HYDROPAC 1/26", "published_at": "2026-11-27T00:30:00Z",
                                     "tier": "routine"}}]}


def write(root: Path, rel: str, data: bytes) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def make_run_tree(root: Path, gh: FakeGitHub) -> None:
    """One run's tree as the workflow leaves it before the archive step."""
    nms_runs(root / "cache" / "nms" / "archive", gh, RUNS_TO_27)
    write(root, "cache/nms/store.json.gz", gzip.compress(b'{"notams": {}}', 6, mtime=0))
    for rel, body in {"data/advisories.json": b'{"advisories": []}\n', "data/navarea.json": b'{"warnings": []}\n',
                      "data/health.json": b'{"navwarn": {"state": "fresh"}}\n',
                      "data/nms_state.json": b'{"status": "ok", "mode": "delta"}\n',
                      "data/faa_counts.jsonl": b'{"at": "2026-11-27T01:00:00Z", "stops": 0}\n',
                      "data/nms_significance.json": b'{"start": "2026-11-19"}\n',
                      "data/history/dropped.jsonl": b'{"id": "cordon:x"}\n',
                      "site/index.html": b"<!doctype html>\n",
                      "site/data/map.json": b'{"advisories": []}\n', "site/data/events.json": b'{"events": []}\n',
                      "site/data/notams/index.json": b'{"subsets": []}\n',
                      "site/data/notams/launch-areas.json": b'{"features": []}\n',
                      "site/data/notams/gnss.json": b'{"features": []}\n',
                      "site/data/notams/significant.json": b'{"features": []}\n'}.items():
        write(root, rel, body)
    # A closed day of the history log, as an earlier run left it, and this run's log through the kit.
    write(root, "data/history/log/2026/11/26.jsonl.gz",
          gzip.compress(b'{"format":"tic-history/1","change":"new","id":"cordon:old"}\n', 9, mtime=0))
    write(root, "site/data/feed.geojson", json.dumps(FEED).encode())
    (kit,) = re.findall(r"python (doctrine/kit/tic\.py history .*?)\s+\|\|", step("History").replace("\\\n", " "))
    argv = [t.replace("$built", FEED["generated_at"]) for t in shlex.split(kit)]
    argv[0] = str(ROOT / argv[0])                          # the repository's kit, run in the run tree
    r = subprocess.run([sys.executable, *argv], cwd=root, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"kit history failed: {r.stderr[-400:]}")


NOT_ARCHIVED = {f"cache/nms/archive/days/{TODAY}.jsonl.gz",     # today's: goes up once the day closes
                "cache/nms/archive/seen.json.gz", "cache/nms/archive/meta.json", "cache/nms/store.json.gz"}


class TestWorkflowLanes(unittest.TestCase):
    def test_lanes_and_their_folders(self):
        lanes = {lane_of(c): c for c in put_calls("$today")}
        self.assertEqual(set(lanes), LANES)
        self.assertEqual(len(put_calls()), len(LANES))
        for c in lanes.values():
            self.assertEqual(arg(c, "--program"), [PROGRAM])
            self.assertFalse([t for t in c if t.startswith("--redact")])     # public data: archived as it is
        self.assertEqual(arg(lanes["nms"], "--src"), ["cache/nms/archive/days"])
        self.assertEqual(arg(lanes["nms"], "--exclude"), ["$today.jsonl.gz"])
        self.assertEqual(arg(lanes["data"], "--src"), ["data"])
        self.assertEqual(arg(lanes["data"], "--exclude"), ["history/*"])            # lane history
        self.assertEqual(arg(lanes["history"], "--src"), ["data/history"])
        self.assertEqual(arg(lanes["site"], "--src"), ["site"])
        self.assertEqual(arg(lanes["site"], "--exclude"), ["data/notams/*"])       # lane notams
        self.assertEqual(arg(lanes["notams"], "--src"), ["site/data/notams"])
        self.assertEqual(arg(lanes["notams"], "--min-interval-hours"), ["6"])
        for c in lanes.values():
            if lane_of(c) != "notams":
                self.assertEqual(arg(c, "--min-interval-hours"), [], lane_of(c))
        # No lane name is another's with a hyphen after it, so no lane can read another's releases.
        for a in LANES:
            for b in LANES - {a}:
                self.assertFalse(b.startswith(a + "-"), (a, b))

    def test_today_is_the_days_utc_date(self):
        self.assertIn("today=$(date -u +%Y-%m-%d)", step("Private archive"))

    def test_step_after_the_deploy_and_loud_on_failure(self):
        names = list(STEPS)
        at = names.index(STEP_NAME)
        self.assertGreater(at, names.index("deployment"))
        self.assertGreater(at, names.index("deployment_retry"))
        self.assertLess(at, names.index("Fail the run when history or a push failed"))
        text = STEPS[STEP_NAME]
        self.assertIn("if: ${{ !cancelled() }}", text)
        self.assertIn("GH_TOKEN: ${{ secrets.TIC_ARCHIVE_TOKEN }}", text)
        self.assertNotIn("github.token", text)
        self.assertNotIn("|| true", text)
        self.assertNotIn("continue-on-error", text)
        self.assertIn('[ -z "$GH_TOKEN" ]', text)
        self.assertEqual(text.count("exit 1"), 2)            # token missing; any lane failed
        self.assertEqual(text.count("|| failed=1"), len(LANES))
        # Bounded in time, inside the job's own limit, so a hung upload fails this step instead of the job.
        (limit,) = re.findall(r"(?m)^        timeout-minutes: (\d+)$", text)
        (job,) = re.findall(r"(?m)^    timeout-minutes: (\d+)$", WF.split("\n  update:\n", 1)[1].split("\n    steps:", 1)[0])
        self.assertLess(int(limit), int(job))

    def test_each_lane_only_after_the_step_that_writes_it(self):
        text = STEPS[STEP_NAME]
        for line in ("COLLECTED: ${{ steps.collect.outcome }}", "HISTORY: ${{ steps.history.outcome }}",
                     "HISTORY_FAILED: ${{ steps.history.outputs.failed }}",
                     "DEPLOYED: ${{ steps.deployment.outcome == 'success' || "
                     "steps.deployment_retry.outcome == 'success' }}"):
            self.assertIn(line, text)
        self.assertIn("id: collect", step("Collect"))
        self.assertIn("id: history", step("History"))
        # The History step ends 0 when the kit failed and says so in its output `failed`.
        self.assertIn('echo "failed=yes" >> "$GITHUB_OUTPUT"; exit 0', step("History"))
        self.assertIn("continue-on-error: true", STEPS["deployment"])

    def test_the_folders_are_what_the_workflow_replaces_or_keeps_for_a_while(self):
        self.assertIn("cache/nms/archive\n", step("Restore the NMS store"))     # the cached working copy
        self.assertIn("git add data\n", step("Commit data"))
        self.assertIn("git add data/history\n", step("History"))
        self.assertIn("--dir data/history", step("History"))
        self.assertIn("with: { path: site }", step("actions/upload-pages-artifact"))
        self.assertEqual(na.KEEP_LOCAL_DAYS, 3)    # the comment in update.yml says 3 days
        self.assertIn("leaves the cache after 3 days", WF)

    def test_nothing_reads_the_archive_back(self):
        # No step restores from tic-archive, so no run can put an older archived copy over newer data.
        self.assertEqual(archive_calls(WF, "restore"), [])
        self.assertNotIn("tic_archive.py restore", WF)
        for name, text in STEPS.items():
            if name != STEP_NAME:
                self.assertNotIn("TIC_ARCHIVE_TOKEN", text, name)
                self.assertNotIn("tic_archive", text, name)
        for p in (ROOT / "cordon").glob("*.py"):
            src = p.read_text(encoding="utf-8")
            self.assertNotIn("tic-archive", src, p.name)
            self.assertNotIn("tic_archive", src, p.name)

    def test_ci_runs_every_test_file(self):
        self.assertIn('python -m unittest discover -s tests -p "test_*.py"', CI)
        self.assertTrue(Path(__file__).name.startswith("test_") and Path(__file__).suffix == ".py")


class TestTheToolNeverDeletesOrReplaces(unittest.TestCase):
    """Every gh call tic_archive.py makes, recorded through a stand-in gh that answers as GitHub does: release list,
    create, upload (no --clobber: an existing name is refused) and download, and GET API reads. Nothing else."""

    ALLOWED = {("api",), ("release", "create"), ("release", "upload"), ("release", "download")}

    class FakeGh:
        def __init__(self):
            self.rel, self.calls = {}, []

        def __call__(self, args):
            self.calls.append(list(args))
            if args[0] == "api":
                rest = [a for a in args[1:] if a not in ("--paginate",)]
                path = rest[0]
                assert all(a not in args for a in ("-X", "--method", "-f", "-F", "--field", "--raw-field",
                                                    "--input")), args
                if path.startswith("repos/") and path.endswith("/releases?per_page=100"):
                    return "\n".join(self.rel) + "\n"
                m = re.match(r"repos/[^/]+/[^/]+/releases/tags/(.+)$", path)
                if m:
                    if m.group(1) not in self.rel:
                        raise ta.ArchiveError("404")
                    return str(list(self.rel).index(m.group(1)) + 1) + "\n"
                m = re.match(r"repos/[^/]+/[^/]+/releases/(\d+)/assets\?per_page=100$", path)
                if m:
                    tag = list(self.rel)[int(m.group(1)) - 1]
                    return "".join(f"{len(b)} {n}\n" for n, b in self.rel[tag].items())
                raise AssertionError(f"unexpected api call {args}")
            if args[:2] == ["release", "create"]:
                self.rel.setdefault(args[2], {})
                return ""
            if args[:2] == ["release", "upload"]:
                assert "--clobber" not in args, args
                tag, files = args[2], [Path(a) for a in args[5:]]
                for f in files:
                    if f.name in self.rel[tag]:
                        raise ta.ArchiveError("asset already exists")
                    self.rel[tag][f.name] = f.read_bytes()
                return ""
            if args[:2] == ["release", "download"]:
                tag, name, dest = args[2], args[args.index("-p") + 1], Path(args[args.index("-D") + 1])
                (dest / name).write_bytes(self.rel[tag][name])
                return ""
            raise AssertionError(f"unexpected gh call {args}")

    def test_put_and_restore_only_create_upload_download_and_read(self):
        gh = self.FakeGh()
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            write(src, "2026-11-25.jsonl.gz", b"day one")
            arch = ta.Archive(ta.GhStore(runner=gh), PROGRAM, "nms")
            arch.put(src, now=FIRST)
            before = {t: dict(a) for t, a in gh.rel.items()}
            write(src, "2026-11-26.jsonl.gz", b"day two")
            (src / "2026-11-25.jsonl.gz").unlink()             # a day left the cache
            arch.put(src, now=SECOND)
            arch.restore(Path(td) / "out")
        kinds = {tuple(c[:1]) if c[0] == "api" else tuple(c[:2]) for c in gh.calls}
        self.assertLessEqual(kinds, self.ALLOWED)
        for tag, assets in before.items():                    # every earlier asset still there, same bytes
            for name, data in assets.items():
                self.assertEqual(gh.rel[tag][name], data)

    def test_the_source_has_no_delete_edit_or_clobber(self):
        src = (ROOT / "tools" / "tic_archive.py").read_text(encoding="utf-8")
        for word in ('"delete"', "'delete'", '"edit"', "--clobber\"", "\"--clobber", "DELETE", "PATCH", '"-X"',
                     "unlink(", "rmtree("):
            self.assertNotIn(word, src, word)
        # The upload is refused for a name that exists, as gh refuses it without --clobber.
        with tempfile.TemporaryDirectory() as td:
            store = ta.DirStore(Path(td) / "s")
            store.create("t")
            write(Path(td), "a", b"1")
            store.upload("t", [Path(td) / "a"])
            with self.assertRaises(ta.ArchiveError):
                store.upload("t", [Path(td) / "a"])


class TestEveryRunFileIsArchived(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="cordon-lanes-"))
        cls.root, cls.store, cls.gh = cls.work / "run", cls.work / "store", FakeGitHub()
        make_run_tree(cls.root, cls.gh)
        cls.before = tree(cls.root)
        cls.results = put_all(cls.root, cls.store, FIRST, TODAY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def snapshot_names(self, when: datetime) -> dict[str, str]:
        stamp = ta.utc_stamp(when)
        return {tag.name[len(PROGRAM) + 1:].rsplit("-", 2)[0]: p.name
                for tag in self.store.iterdir() for p in tag.iterdir()
                if p.name.startswith(stamp) and p.name.endswith(".files.json")}

    def restore_all(self, dest: Path, snapshots: dict[str, str] | None = None) -> dict[str, str]:
        """Every lane restored, mapped back to run-tree paths: {path: sha256}."""
        got = {}
        for c in put_calls():
            lane, (src,) = lane_of(c), arg(c, "--src")
            cmd = ["restore", "--program", PROGRAM, "--lane", lane, "--dest", str(dest / lane)]
            if snapshots is not None:
                if lane not in snapshots:
                    continue
                cmd += ["--snapshot", snapshots[lane]]
            self.assertEqual(run_archive(cmd, self.root, self.store), 0, lane)
            for rel, sha in tree(dest / lane).items():
                self.assertNotIn(f"{src}/{rel}", got, "two lanes hold the same file")
                got[f"{src}/{rel}"] = sha
        return got

    def test_every_put_succeeded(self):
        self.assertEqual(self.results, {lane: 0 for lane in LANES})

    def test_the_run_tree_has_what_a_run_writes(self):
        for p in ("data/history/state.json", "data/history/log/2026/11/27.jsonl", "site/data/ended.geojson",
                  "cache/nms/archive/days/2026-11-25.jsonl.gz", "cache/nms/archive/days/2026-11-26.jsonl.gz",
                  f"cache/nms/archive/days/{TODAY}.jsonl.gz", "cache/nms/archive/seen.json.gz"):
            self.assertIn(p, self.before)

    def test_every_file_of_the_run_restores_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            got = self.restore_all(Path(td))
        want = {p: s for p, s in self.before.items() if p not in NOT_ARCHIVED}
        self.assertEqual(sorted(set(want) - set(got)), [], "files of the run missing from the archive")
        self.assertEqual(sorted(set(got) - set(want)), [], "the archive holds files it should not")
        self.assertEqual({p: s for p, s in got.items() if want[p] != s}, {}, "restored bytes differ")
        self.assertEqual(sorted(set(self.before) - set(want)), sorted(NOT_ARCHIVED))

    def test_closed_days_match_the_public_release_by_hash(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(run_archive(["restore", "--program", PROGRAM, "--lane", "nms", "--dest", td],
                                         self.root, self.store), 0)
            got = tree(Path(td))
        self.assertEqual(sorted(got), ["2026-11-25.jsonl.gz", "2026-11-26.jsonl.gz"])
        for name, sha in got.items():
            (a,) = [a for a in self.gh.releases[na.tag(name[:10])]["assets"] if a["name"] == na.asset(name[:10])]
            self.assertEqual(hashlib.sha256(self.gh.blobs[a["id"]]).hexdigest(), sha, name)

    def test_the_archive_step_changes_nothing_it_reads(self):
        self.assertEqual(tree(self.root), self.before)


class TestNothingArchivedIsLostLater(unittest.TestCase):
    """A later run: a closed NMS day left the cache, a log day left data/history, state and site files were
    replaced. The archive keeps every asset it held, byte for byte, and the earlier snapshot still restores the
    earlier files; the newest snapshot stays the newest when an older one is restored."""

    def test_two_runs(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            root, store, gh = td / "run", td / "store", FakeGitHub()
            make_run_tree(root, gh)
            self.assertEqual(put_all(root, store, FIRST, TODAY), {lane: 0 for lane in LANES})
            first_tree, held = tree(root), store_files(store)
            first = {lane_of(c): sorted(p.name for p in (store / f"cordon-{lane_of(c)}-2026-11").iterdir()
                                        if p.name.endswith(".files.json"))[-1] for c in put_calls()}
            # The next runs: two more days of NMS pulls (2026-11-25 leaves the cache, 2026-11-27 closes), the
            # state replaced, a log day gone (as a cap would remove it), a new feed deployed.
            nms_runs(root / "cache" / "nms" / "archive", gh, RUNS_TO_29)
            self.assertFalse((root / "cache/nms/archive/days/2026-11-25.jsonl.gz").exists())
            (root / "data/history/log/2026/11/26.jsonl.gz").unlink()
            write(root, "data/history/state.json", b'{"open": {}}\n')
            write(root, "data/health.json", b'{"navwarn": {"state": "failing"}}\n')
            write(root, "site/data/feed.geojson", b'{"features": []}\n')
            write(root, "site/data/notams/gnss.json", b'{"features": [1]}\n')
            self.assertEqual(put_all(root, store, SECOND, "2026-11-29"), {lane: 0 for lane in LANES})

            now = store_files(store)
            self.assertEqual({k: v for k, v in held.items() if now.get(k) != v}, {}, "an archived asset changed")
            self.assertGreater(len(now), len(held))

            def restored(lane, snapshot=None):
                d = td / f"r-{lane}-{snapshot or 'newest'}"
                cmd = ["restore", "--program", PROGRAM, "--lane", lane, "--dest", str(d)]
                self.assertEqual(run_archive(cmd + (["--snapshot", snapshot] if snapshot else []), root, store), 0)
                return tree(d)

            then_nms = restored("nms", first["nms"])
            self.assertEqual(then_nms["2026-11-25.jsonl.gz"],
                             first_tree["cache/nms/archive/days/2026-11-25.jsonl.gz"])
            newest_nms = restored("nms")
            self.assertEqual(sorted(newest_nms), ["2026-11-26.jsonl.gz", "2026-11-27.jsonl.gz", "2026-11-28.jsonl.gz"])
            self.assertEqual(newest_nms["2026-11-26.jsonl.gz"], then_nms["2026-11-26.jsonl.gz"])   # closed: same bytes
            then_hist = restored("history", first["history"])
            self.assertEqual(then_hist["log/2026/11/26.jsonl.gz"], first_tree["data/history/log/2026/11/26.jsonl.gz"])
            self.assertEqual(then_hist["state.json"], first_tree["data/history/state.json"])
            self.assertNotIn("log/2026/11/26.jsonl.gz", restored("history"))
            self.assertEqual(restored("data", first["data"])["health.json"], first_tree["data/health.json"])
            self.assertEqual(restored("site", first["site"])["data/feed.geojson"], first_tree["site/data/feed.geojson"])
            self.assertEqual(restored("notams", first["notams"])["gnss.json"],
                             first_tree["site/data/notams/gnss.json"])
            # Restoring an older snapshot wrote only to its own folder: the archive is unchanged and the default
            # restore still gives the newest snapshot.
            self.assertEqual(store_files(store), now)
            self.assertEqual(restored("history")["state.json"], hashlib.sha256(b'{"open": {}}\n').hexdigest())

    def test_notams_at_most_one_snapshot_in_six_hours_and_nothing_removed(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            root, store = td / "run", td / "store"
            make_run_tree(root, FakeGitHub())
            (notams,) = [c for c in put_calls() if lane_of(c) == "notams"]
            self.assertEqual(run_archive(notams, root, store, FIRST), 0)
            held = store_files(store)
            write(root, "site/data/notams/gnss.json", b'{"features": [2]}\n')
            self.assertEqual(run_archive(notams, root, store, FIRST + timedelta(hours=1)), 0)
            self.assertEqual(store_files(store), held)                     # too soon: nothing uploaded
            self.assertEqual(run_archive(notams, root, store, FIRST + timedelta(hours=6, minutes=1)), 0)
            self.assertLessEqual(held.items(), store_files(store).items())
            self.assertGreater(len(store_files(store)), len(held))


class TestClosedDayHoldsEveryRecord(unittest.TestCase):
    """Lane nms keeps closed days only. Every copy of a day's asset that the public release held during the day
    holds no record the closed day lacks (cordon/nmsarchive.py rebuilds the day as a union), also across a lost
    cache, so leaving today's file out loses nothing."""

    def records(self, data: bytes) -> set[str]:
        return {json.loads(x)["id"] for x in gzip.decompress(data).decode().splitlines() if x.strip()}

    def test_every_intermediate_copy_is_inside_the_closed_day(self):
        gh, seen = FakeGitHub(), []
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "archive"
            day = "2026-11-26"
            pulls = [(datetime(2026, 11, 26, 1, 0, tzinfo=UTC), "bulk", [feat("B1/26"), feat("B2/26")]),
                     (datetime(2026, 11, 26, 6, 0, tzinfo=UTC), "delta", [feat("B3/26")]),
                     (datetime(2026, 11, 26, 12, 0, tzinfo=UTC), "delta",
                      [feat("B1/26", lu="2026-11-26T11:00:00.000Z")]),
                     ("lose the cache", None, None),
                     (datetime(2026, 11, 26, 18, 0, tzinfo=UTC), "delta", [feat("B4/26")]),
                     (datetime(2026, 11, 26, 23, 50, tzinfo=UTC), "delta", [feat("B5/26"), feat("B2/26")]),
                     (datetime(2026, 11, 27, 0, 10, tzinfo=UTC), "delta", [feat("B6/26")])]
            for now, mode, feats in pulls:
                if now == "lose the cache":
                    shutil.rmtree(d)
                    continue
                nms_runs(d, gh, [(now, mode, feats)])
                if now.strftime("%Y-%m-%d") == day:
                    (a,) = [a for a in gh.releases[na.tag(day)]["assets"] if a["name"] == na.asset(day)]
                    seen.append(self.records(gh.blobs[a["id"]]))
            closed = (d / "days" / f"{day}.jsonl.gz").read_bytes()
            (a,) = [a for a in gh.releases[na.tag(day)]["assets"] if a["name"] == na.asset(day)]
            self.assertEqual(closed, gh.blobs[a["id"]])             # the lane's copy is the public copy
        final = self.records(closed)
        self.assertEqual(len(seen), 5)
        for i, copy in enumerate(seen):
            self.assertLessEqual(copy, final, f"copy {i} holds records the closed day lacks")
        self.assertEqual(len(final), 6)                              # B1 twice (two versions), B2-B5


def _bash() -> str | None:
    git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
    if os.name == "nt":
        return str(git_bash) if git_bash.exists() else None     # not WSL's bash, which cannot see this folder
    return shutil.which("bash")


BASH = _bash()


def run_script(text: str) -> str:
    """The `run: |` block of a step, as the runner gets it."""
    body = []
    for line in text.split("run: |\n", 1)[1].split("\n"):
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


@unittest.skipUnless(BASH, "needs bash, as the runner has")
class TestArchiveStepShell(unittest.TestCase):
    """The step's own script under bash (-eo pipefail, as the runner runs it), python and date replaced: which lanes
    it puts in each case, that it fails loudly, and that it changes nothing in the work tree."""

    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="cordon-step-"))
        cls.root = cls.work / "run"
        make_run_tree(cls.root, FakeGitHub())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    GOOD = {"GH_TOKEN": "token", "COLLECTED": "success", "HISTORY": "success", "HISTORY_FAILED": "",
            "DEPLOYED": "true"}

    def run_case(self, env: dict, root: Path | None = None, fail_lane: str = "") -> tuple[int, list[list[str]], str]:
        root = root or self.root
        calls = self.work / "calls"
        calls.unlink(missing_ok=True)
        stubs = ('python() { echo "$*" >> "$CALLS"; case " $* " in *" --lane $FAIL_LANE "*) return 1;; esac; '
                 'return 0; }\ndate() { echo "$TODAY"; }\n')
        full = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME")}
        full.update(env, CALLS=calls.as_posix(), TODAY=TODAY, FAIL_LANE=fail_lane or "none")
        before = tree(root)
        r = subprocess.run([BASH, "--noprofile", "--norc", "-eo", "pipefail", "-c",
                            stubs + run_script(STEPS[STEP_NAME])],
                           cwd=root, env=full, capture_output=True, text=True, timeout=60)
        self.assertEqual(tree(root), before, "the step changed the work tree")
        got = [shlex.split(x) for x in calls.read_text().splitlines()] if calls.exists() else []
        return r.returncode, got, r.stdout + r.stderr

    def lanes(self, calls):
        return [arg(c, "--lane")[0] for c in calls]

    def test_every_lane_after_a_good_run(self):
        rc, calls, _ = self.run_case(self.GOOD)
        self.assertEqual((rc, self.lanes(calls)), (0, ["nms", "data", "history", "site", "notams"]))
        (nms_call,) = [c for c in calls if arg(c, "--lane") == ["nms"]]
        self.assertEqual(arg(nms_call, "--exclude"), [f"{TODAY}.jsonl.gz"])
        self.assertEqual([c[:2] for c in calls], [["tools/tic_archive.py", "put"]] * 5)

    def test_no_token_fails_loudly_and_puts_nothing(self):
        rc, calls, out = self.run_case({**self.GOOD, "GH_TOKEN": ""})
        self.assertEqual((rc, calls), (1, []))
        self.assertIn("::error::secret TIC_ARCHIVE_TOKEN is not set", out)

    def test_an_unreachable_archive_fails_the_run_after_every_lane_was_tried(self):
        for lane in ("nms", "data", "notams"):
            rc, calls, out = self.run_case(self.GOOD, fail_lane=lane)
            self.assertEqual((rc, self.lanes(calls)), (1, ["nms", "data", "history", "site", "notams"]), lane)
            self.assertIn("::error::a lane did not reach the private archive", out)

    def test_each_lane_waits_for_its_step(self):
        cases = {("COLLECTED", "failure"): ["nms", "history", "site", "notams"],
                 ("COLLECTED", "skipped"): ["nms", "history", "site", "notams"],
                 ("HISTORY", "skipped"): ["nms", "data", "site", "notams"],
                 ("HISTORY_FAILED", "yes"): ["nms", "data", "site", "notams"],
                 ("DEPLOYED", "false"): ["nms", "data", "history"]}
        for (k, v), want in cases.items():
            rc, calls, _ = self.run_case({**self.GOOD, k: v})
            self.assertEqual((rc, self.lanes(calls)), (0, want), (k, v))

    def test_no_closed_day_and_no_subsets_are_said_not_failed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            shutil.copytree(self.root, root)
            for p in (root / "cache/nms/archive/days").iterdir():
                if p.name != f"{TODAY}.jsonl.gz":
                    p.unlink()                          # a lost cache: only today's copy, rebuilt from the release
            shutil.rmtree(root / "site/data/notams")
            rc, calls, out = self.run_case(self.GOOD, root)
            self.assertEqual((rc, self.lanes(calls)), (0, ["data", "history", "site"]))
            self.assertIn("nms: no closed NMS archive day in the cache this run", out)
            self.assertIn("notams: no NOTAM subsets in site/ this run", out)
            shutil.rmtree(root / "cache")
            rc, calls, _ = self.run_case(self.GOOD, root)
            self.assertEqual((rc, self.lanes(calls)), (0, ["data", "history", "site"]))


if __name__ == "__main__":
    unittest.main()
