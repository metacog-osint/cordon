"""Offline tests for the permanent NMS archive (cordon/nmsarchive.py): a fake GitHub releases API, no network."""
import gzip
import io
import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from cordon import common, nms, nmsarchive as na  # noqa: E402
from test_nms import KEYS, SEED, FakeFAA, feat  # noqa: E402

NOW = datetime(2026, 11, 19, 23, 30, tzinfo=timezone.utc)


class FakeGitHub:
    """Releases by tag, assets by id; uploads, deletes, renames and downloads, as the REST API answers them."""

    def __init__(self):
        self.releases, self.blobs, self.next, self.calls = {}, {}, 1, []
        self.fail_uploads = False

    def _id(self):
        self.next += 1
        return self.next

    def __call__(self, req, timeout=0):
        url, method = req.full_url, req.get_method()
        self.calls.append((method, url))
        u = urllib.parse.urlparse(url)
        path = u.path
        if method == "GET" and "/releases/tags/" in path:
            t = path.rsplit("/", 1)[1]
            if t not in self.releases:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return self._out(self.releases[t])
        if method == "POST" and path.endswith("/releases"):
            body = json.loads(req.data)
            rid = self._id()
            rel = {"id": rid, "tag_name": body["tag_name"], "body": body["body"], "assets": [],
                   "upload_url": f"https://uploads.github.com/repos/{na.REPO}/releases/{rid}/assets{{?name,label}}"}
            self.releases[body["tag_name"]] = rel
            return self._out(rel)
        if method == "POST" and u.netloc == "uploads.github.com":
            if self.fail_uploads:
                raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)
            rid = int(path.split("/releases/")[1].split("/")[0])
            rel = next(r for r in self.releases.values() if r["id"] == rid)
            name = urllib.parse.parse_qs(u.query)["name"][0]
            aid = self._id()
            self.blobs[aid] = req.data
            a = {"id": aid, "name": name, "size": len(req.data),
                 "url": f"https://api.github.com/repos/{na.REPO}/releases/assets/{aid}"}
            rel["assets"].append(a)
            return self._out(a)
        if "/releases/assets/" in path:
            aid = int(path.rsplit("/", 1)[1])
            rel, a = next((r, a) for r in self.releases.values() for a in r["assets"] if a["id"] == aid)
            if method == "DELETE":
                rel["assets"].remove(a)
                del self.blobs[aid]
                return io.BytesIO(b"")
            if method == "PATCH":
                a["name"] = json.loads(req.data)["name"]
                return self._out(a)
            return io.BytesIO(self.blobs[aid])
        raise AssertionError(f"unexpected {method} {url}")

    @staticmethod
    def _out(j):
        return io.BytesIO(json.dumps(j).encode())

    def records(self, tag, name):
        a = next(a for a in self.releases[tag]["assets"] if a["name"] == name)
        return [json.loads(x) for x in gzip.decompress(self.blobs[a["id"]]).decode().splitlines() if x]

    def names(self, tag):
        return sorted(a["name"] for a in self.releases[tag]["assets"])


class Archive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "archive"
        self.gh = FakeGitHub()

    def tearDown(self):
        self.tmp.cleanup()

    def run_(self, feats, mode, now=NOW):
        return na.run(feats, mode, now, env={}, gh=na.GitHub("t", opener=self.gh), directory=self.dir)

    def test_every_feature_once_per_version(self):
        bulk = [feat("A1/26"), feat("A2/26", q="QFALC", text="E) AD CLSD"), feat("A3/26", end="PERM")]
        out = self.run_(bulk, "bulk")
        self.assertEqual((out["status"], out["added"], out["pending"]), ("ok", 3, []))
        tag = "nms-archive-2026-11"
        self.assertEqual(self.gh.names(tag), ["nms-2026-11-19.jsonl.gz", "seen.json.gz"])
        self.assertIn("Not FAA data", self.gh.releases[tag]["body"])
        # a delta: one repeat, one new version of A1 (lastUpdated moved), one new NOTAM
        delta = [feat("A2/26", q="QFALC", text="E) AD CLSD"), feat("A1/26", lu="2026-11-19T23:40:00.000Z"),
                 feat("A4/26")]
        out = self.run_(delta, "delta", NOW + timedelta(minutes=20))
        self.assertEqual(out["added"], 2)
        recs = self.gh.records(tag, "nms-2026-11-19.jsonl.gz")
        self.assertEqual([r["id"] for r in recs], ["NMS_A1/26|2026-11-19T00:00:00.000Z",
                                                    "NMS_A2/26|2026-11-19T00:00:00.000Z",
                                                    "NMS_A3/26|2026-11-19T00:00:00.000Z",
                                                    "NMS_A1/26|2026-11-19T23:40:00.000Z",
                                                    "NMS_A4/26|2026-11-19T00:00:00.000Z"])
        f = recs[0]["feature"]["properties"]["coreNOTAMData"]
        self.assertEqual([t["type"] for t in f["notamTranslation"]], ["ICAO"])
        self.assertNotIn("notamEvent", f)
        self.assertEqual(recs[0]["pull"], "bulk")
        self.assertEqual(out["archived_to"], nms.iso(NOW + timedelta(minutes=20)))

    def test_lost_cache_reads_the_release_back(self):
        self.run_([feat("A1/26"), feat("A2/26")], "bulk")
        shutil.rmtree(self.dir)
        out = self.run_([feat("A2/26"), feat("A5/26")], "delta", NOW + timedelta(minutes=20))
        self.assertEqual((out["added"], out["seen_from"]), (1, "release nms-archive-2026-11"))
        ids = [r["id"][:9] for r in self.gh.records("nms-archive-2026-11", "nms-2026-11-19.jsonl.gz")]
        self.assertEqual(ids, ["NMS_A1/26", "NMS_A2/26", "NMS_A5/26"])

    def test_failed_upload_stays_pending_then_uploads(self):
        self.gh.fail_uploads = True
        out = self.run_([feat("A1/26")], "bulk")
        self.assertEqual((out["status"], out["pending"], out["archived_to"]), ("failing", ["2026-11-19"], None))
        self.gh.fail_uploads = False
        out = self.run_([], None, NOW + timedelta(minutes=20))
        self.assertEqual((out["status"], out["pending"], out["uploaded"]), ("ok", [], ["nms-2026-11-19.jsonl.gz"]))
        self.assertEqual(len(self.gh.records("nms-archive-2026-11", "nms-2026-11-19.jsonl.gz")), 1)

    def test_part_left_by_a_stopped_run_is_the_days_copy(self):
        self.run_([feat("A1/26")], "bulk")
        rel = self.gh.releases["nms-archive-2026-11"]
        a = next(a for a in rel["assets"] if a["name"] == "nms-2026-11-19.jsonl.gz")
        a["name"] += ".part"                      # upload done, delete and rename never ran
        shutil.rmtree(self.dir)
        self.run_([feat("A6/26")], "delta", NOW + timedelta(minutes=20))
        self.assertEqual(self.gh.names("nms-archive-2026-11"), ["nms-2026-11-19.jsonl.gz", "seen.json.gz"])
        self.assertEqual(len(self.gh.records("nms-archive-2026-11", "nms-2026-11-19.jsonl.gz")), 2)

    def test_day_and_month_roll_over(self):
        self.run_([feat("A1/26")], "bulk", datetime(2026, 11, 30, 23, 50, tzinfo=timezone.utc))
        out = self.run_([feat("A1/26"), feat("A7/26")], "delta", datetime(2026, 12, 1, 0, 10, tzinfo=timezone.utc))
        self.assertEqual(out["added"], 1)
        self.assertEqual(self.gh.names("nms-archive-2026-12"), ["nms-2026-12-01.jsonl.gz", "seen.json.gz"])
        self.assertEqual(len(self.gh.records("nms-archive-2026-11", "nms-2026-11-30.jsonl.gz")), 1)
        # a lost cache in December finds November's index
        shutil.rmtree(self.dir)
        self.gh.releases["nms-archive-2026-12"]["assets"] = [
            a for a in self.gh.releases["nms-archive-2026-12"]["assets"] if a["name"] != "seen.json.gz"]
        out = self.run_([feat("A1/26")], "delta", datetime(2026, 12, 1, 0, 40, tzinfo=timezone.utc))
        self.assertEqual((out["added"], out["seen_from"]), (0, "release nms-archive-2026-11"))

    def test_bulk_drops_ended_versions_from_the_index_only(self):
        self.run_([feat("A1/26"), feat("A2/26")], "bulk", NOW)
        out = self.run_([feat("A1/26")], "bulk", NOW + timedelta(days=3))
        self.assertEqual(out["seen"], 1)
        self.assertEqual(len(self.gh.records("nms-archive-2026-11", "nms-2026-11-19.jsonl.gz")), 2)

    def test_no_token_keeps_it_in_the_cache(self):
        out = na.run([feat("A1/26")], "bulk", NOW, env={}, directory=self.dir)
        self.assertEqual((out["status"], out["pending"]), ("no-token", ["2026-11-19"]))
        self.assertTrue((self.dir / "days" / "2026-11-19.jsonl.gz").exists())


class Lane(unittest.TestCase):
    """The archive inside nms.collect: every pull archived; deltas restart from archived_to."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = (common.DATA, nms.CACHE, nms.STORE, nms.OUT, na.GitHub)
        common.DATA = t / "data"
        nms.CACHE, nms.STORE, nms.OUT = t / "cache", t / "cache" / "store.json.gz", t / "cache" / "out"
        self.gh = FakeGitHub()
        real = self.saved[4]
        na.GitHub = lambda token, opener=None: real(token, opener=self.gh)

    def tearDown(self):
        common.DATA, nms.CACHE, nms.STORE, nms.OUT, na.GitHub = self.saved
        self.tmp.cleanup()

    def lane(self, faa, now):
        orig = nms.Client.__init__

        def init(c, env=None, opener=None, pause=0):
            orig(c, env, opener=faa, pause=0)
        nms.Client.__init__ = init
        try:
            return nms.collect(now, env={**KEYS, "GITHUB_TOKEN": "t"},
                               fetch=lambda u: (_ for _ in ()).throw(urllib.error.URLError("not published")))
        finally:
            nms.Client.__init__ = orig

    def test_archive_deltas_before_the_first_bulk_chain_on(self):
        t0 = SEED + timedelta(hours=18)
        st, _ = self.lane(FakeFAA(delta=[feat("A1/26")]), t0)
        self.assertEqual((st["mode"], st["archived_to"]), ("archive-delta", nms.iso(t0)))
        faa = FakeFAA(delta=[feat("A1/26"), feat("A2/26")])
        st, _ = self.lane(faa, t0 + timedelta(hours=1))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(faa.calls[-1]).query)
        self.assertEqual(q["lastUpdatedDate"], [nms.iso(t0 - timedelta(seconds=nms.OVERLAP_S))])
        self.assertEqual(st["archive"]["added"], 1)
        # the bulk at 24 h: the store and subsets begin; the archive adds only versions it lacks
        bulk = {"INTERNATIONAL": [feat("A1/26"), feat("A3/26")], "FDC": [], "MILITARY": [], "DOMESTIC": []}
        st, _ = self.lane(FakeFAA(bulk=bulk), SEED + timedelta(hours=24, minutes=5))
        self.assertEqual((st["mode"], st["archive"]["added"]), ("bulk", 1))

    def test_every_class_archived_and_delta_restarts_at_archived_to(self):
        bulk = {"INTERNATIONAL": [feat("A1/26")], "FDC": [feat("F1/26", q="QFALC", text="E) AD CLSD")],
                "MILITARY": [], "DOMESTIC": [feat("D1/26", q="QMRLC", text="E) RWY CLSD")]}
        t0 = SEED + timedelta(hours=25)
        st, _ = self.lane(FakeFAA(bulk=bulk), t0)
        self.assertEqual((st["archive"]["status"], st["archive"]["added"]), ("ok", 3))
        self.assertEqual(st["archived_to"], nms.iso(t0))
        idx = json.loads((nms.OUT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual((idx["archive"]["status"], idx["archive"]["where"]), ("ok", na.RELEASES))
        self.gh.fail_uploads = True
        t1 = t0 + timedelta(hours=1)
        st, _ = self.lane(FakeFAA(delta=[feat("A2/26")]), t1)
        self.assertEqual((st["status"], st["archive"]["status"], st["archived_to"]), ("ok", "failing", nms.iso(t0)))
        self.gh.fail_uploads = False
        faa = FakeFAA(delta=[feat("A2/26"), feat("A3/26")])
        st, _ = self.lane(faa, t1 + timedelta(hours=1))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(faa.calls[-1]).query)
        self.assertEqual(q["lastUpdatedDate"], [nms.iso(t0 - timedelta(seconds=nms.OVERLAP_S))])
        self.assertEqual(st["archive"]["pending"], [])
        day = t0.strftime("%Y-%m-%d")
        ids = sorted(r["id"][:9] for r in self.gh.records(na.tag(day), na.asset(day)))
        self.assertEqual(ids, ["NMS_A1/26", "NMS_A2/26", "NMS_A3/26", "NMS_D1/26", "NMS_F1/26"])


if __name__ == "__main__":
    unittest.main()
