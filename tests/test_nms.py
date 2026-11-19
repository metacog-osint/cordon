"""Offline tests for the NMS lane (cordon/nms.py): no network, a fake FAA and a fake published site."""
import gzip
import io
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cordon import common, nms  # noqa: E402

KEYS = {"NMS_CLIENT_ID": "id", "NMS_CLIENT_SECRET": "secret", "NMS_ENV": "prod"}
SEED = datetime.fromisoformat(nms.SEED_BULK_AT.replace("Z", "+00:00"))


def feat(number, q="QRDCA", typ="N", start="2026-11-20T00:00:00.000Z", end="2026-11-20T06:00:00.000Z", fl="999",
         text="E) ROCKET LAUNCH", fir="ZPKM", refers=None, loc=None, nid=None, lu="2026-11-19T00:00:00.000Z"):
    head = f"{number} NOTAM{typ}" + (f" {refers}" if refers else "")
    icao = f"{head}\nQ) {fir}/{q}/IV/BO/W/000/{fl}/\nA) {fir}\n{text}"
    n = {"id": nid or "NMS_" + number, "number": number, "icaoLocation": loc, "lastUpdated": lu, "type": typ, "affectedFir": fir, "selectionCode": q,
         "maximumFl": fl, "effectiveStart": start, "effectiveEnd": end, "text": text, "classification": "INTL"}
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]},
            "properties": {"coreNOTAMData": {"notamEvent": {"scenario": "1"}, "notam": n,
                                             "notamTranslation": [{"type": "ICAO", "formattedText": icao},
                                                                  {"type": "LOCAL_FORMAT", "simpleText": "x"}]}}}


class FakeFAA:
    """Answers the token call, classification content paths and files, and deltas."""

    def __init__(self, bulk=None, delta=None, fail=False):
        self.bulk, self.delta, self.fail, self.calls = bulk or {}, delta or [], fail, []

    def __call__(self, req, timeout=0):
        url = req.full_url
        self.calls.append(url)
        if self.fail:
            raise urllib.error.URLError("down")
        if url.endswith("/v1/auth/token"):
            body = {"access_token": "t", "expires_in": 1799}
        elif "/files/" in url:
            body = {"type": "FeatureCollection", "features": self.bulk.get(url.rsplit("/", 1)[1], [])}
        else:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if "classification" in qs:
                body = {"data": {"url": "/nmsapi/v1/files/" + qs["classification"][0]}}
            else:
                body = {"data": {"geojson": {"type": "FeatureCollection", "features": self.delta}}}
        return io.BytesIO(json.dumps(body).encode())


class Lane(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = (common.DATA, nms.CACHE, nms.STORE, nms.OUT, nms.PAUSE_S)
        common.DATA = t / "data"
        nms.CACHE, nms.STORE, nms.OUT = t / "cache", t / "cache" / "store.json.gz", t / "cache" / "out"

    def tearDown(self):
        common.DATA, nms.CACHE, nms.STORE, nms.OUT, nms.PAUSE_S = self.saved
        self.tmp.cleanup()

    def no_site(self, url):
        raise urllib.error.URLError("not published")

    def run_lane(self, faa, now, fetch=None, env=KEYS):
        client_open = faa
        orig = nms.Client.__init__

        def init(c, env=None, opener=None, pause=0):
            orig(c, env, opener=client_open, pause=0)
        nms.Client.__init__ = init
        try:
            return nms.collect(now, env=env, fetch=fetch or self.no_site)
        finally:
            nms.Client.__init__ = orig

    def index(self):
        return json.loads((nms.OUT / "index.json").read_text(encoding="utf-8"))

    def test_no_keys_waits_without_requests(self):
        st, asked = nms.collect(SEED + timedelta(hours=30), env={}, fetch=self.no_site)
        self.assertEqual((st["status"], asked), ("waiting", False))
        self.assertFalse((nms.OUT / "index.json").exists())

    def test_bulk_window_kept_from_launch_seed(self):
        faa = FakeFAA()
        st, asked = self.run_lane(faa, SEED + timedelta(hours=23, minutes=45))   # past a delta's reach
        self.assertEqual((st["status"], st["mode"], asked), ("window", "window", False))
        self.assertEqual(faa.calls, [])
        self.assertIn("2026-11-19T23:26:20Z", st["note"])

    def test_before_first_bulk_deltas_go_to_the_archive_only(self):
        faa = FakeFAA(delta=[feat("A0001/26"), feat("A0002/26", q="QFALC", text="E) AD CLSD")])
        st, asked = self.run_lane(faa, SEED + timedelta(hours=20))
        self.assertEqual((st["status"], st["mode"], asked), ("ok", "archive-delta", True))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(faa.calls[-1]).query)
        self.assertEqual(q["lastUpdatedDate"], [nms.iso(SEED - timedelta(seconds=nms.OVERLAP_S))])
        self.assertEqual(st["archive"]["added"], 2)
        self.assertFalse(nms.STORE.exists())
        self.assertFalse((nms.OUT / "index.json").exists(), "no subsets until the bulk")
        # the next run starts where the archive got to (no token here: archived_to stays unset, so from SEED)
        st, _ = self.run_lane(FakeFAA(delta=[]), SEED + timedelta(hours=21))
        self.assertEqual(st["mode"], "archive-delta")

    def test_bulk_then_delta(self):
        bulk = {"INTERNATIONAL": [feat("A0001/26"), feat("A0002/26", q="QPICH", text="E) RNAV (GNSS) RWY 18"),
                                  feat("A0003/26", q="QFALC", text="E) AD CLSD")],
                "FDC": [], "MILITARY": [feat("M0001/26", end="PERM")], "DOMESTIC": []}
        now = SEED + timedelta(hours=25)
        st, asked = self.run_lane(FakeFAA(bulk=bulk), now)
        self.assertEqual((st["status"], st["mode"], asked), ("ok", "bulk", True))
        self.assertEqual(st["counts"]["by_class"], {"INTERNATIONAL": 3, "FDC": 0, "MILITARY": 1, "DOMESTIC": 0})
        self.assertEqual(st["subsets"], {"launch-areas": 1, "gnss": 1})
        launch = json.loads((nms.OUT / "launch-areas.json").read_text(encoding="utf-8"))
        tr = launch["features"][0]["properties"]["coreNOTAMData"]
        self.assertEqual([t["type"] for t in tr["notamTranslation"]], ["ICAO"])
        self.assertNotIn("notamEvent", tr)
        self.assertIn("Not FAA data", launch["source_note"])
        # an hour later: a delta replaces A0001 with A0004 and cancels the GNSS notice
        later = now + timedelta(hours=1)
        delta = [feat("A0004/26", typ="R", refers="A0001/26"),
                 feat("A0005/26", typ="C", refers="A0002/26", q="QPICH", text="E) RNAV (GNSS) RWY 18 CNL")]
        faa = FakeFAA(delta=delta)
        st, _ = self.run_lane(faa, later)
        self.assertEqual(st["mode"], "delta")
        self.assertEqual(st["subsets"], {"launch-areas": 1, "gnss": 1})     # the GNSS notice gone, its cancel listed
        g = json.loads((nms.OUT / "gnss.json").read_text(encoding="utf-8"))["features"]
        self.assertEqual([nms.meta(f)["number"] for f in g], ["A0005/26"])
        nums = [f["properties"]["coreNOTAMData"]["notam"]["number"]
                for f in json.loads((nms.OUT / "launch-areas.json").read_text(encoding="utf-8"))["features"]]
        self.assertEqual(nums, ["A0004/26"])
        q = urllib.parse.parse_qs(urllib.parse.urlparse(faa.calls[-1]).query)
        self.assertEqual(q["lastUpdatedDate"], [nms.iso(now - timedelta(seconds=nms.OVERLAP_S))])

    def test_lost_cache_rebuilds_from_published_then_deltas(self):
        pulled = SEED + timedelta(hours=2)
        site = {nms.PUBLISHED + "index.json": {"bulk_at": nms.SEED_BULK_AT, "pulled_to": nms.iso(pulled),
                                               "subsets": [{"name": "launch-areas", "file": "launch-areas.json"}]},
                nms.PUBLISHED + "launch-areas.json": {"type": "FeatureCollection", "features": [feat("A0009/26")]}}
        faa = FakeFAA(delta=[])
        st, asked = self.run_lane(faa, SEED + timedelta(hours=10), fetch=lambda u: site[u])
        self.assertEqual((st["mode"], st["rebuilt_from_published"], asked), ("delta", True, True))
        self.assertFalse(any("classification" in c for c in faa.calls), "no second bulk inside the day")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(faa.calls[-1]).query)
        self.assertEqual(q["lastUpdatedDate"], [nms.iso(pulled - timedelta(seconds=nms.OVERLAP_S))])
        self.assertEqual(self.index()["subsets"][0]["n"], 1)

    def test_published_bulk_time_holds_the_window(self):
        recent = SEED + timedelta(hours=30)          # a bulk Cordon made, known only from its published index
        site = {nms.PUBLISHED + "index.json": {"bulk_at": nms.iso(recent), "pulled_to": nms.iso(recent),
                                               "subsets": []}}
        faa = FakeFAA()
        st, _ = self.run_lane(faa, recent + timedelta(hours=2), fetch=lambda u: site[u])
        self.assertNotEqual(st["mode"], "bulk")
        self.assertFalse(any("classification" in c for c in faa.calls))

    def test_failure_keeps_last_set_published(self):
        bulk = {"INTERNATIONAL": [feat("A0001/26")], "FDC": [], "MILITARY": [], "DOMESTIC": []}
        now = SEED + timedelta(hours=25)
        self.run_lane(FakeFAA(bulk=bulk), now)
        st, asked = self.run_lane(FakeFAA(fail=True), now + timedelta(hours=1))
        self.assertEqual((st["status"], asked), ("failing", True))
        self.assertEqual(self.index()["lane_status"], "failing")
        self.assertEqual(self.index()["subsets"][0]["n"], 1)

    def test_store_is_gzip_and_cache_only(self):
        bulk = {"INTERNATIONAL": [feat("A0001/26")], "FDC": [], "MILITARY": [], "DOMESTIC": []}
        self.run_lane(FakeFAA(bulk=bulk), SEED + timedelta(hours=25))
        self.assertEqual(len(json.loads(gzip.decompress(nms.STORE.read_bytes()))), 1)
        self.assertFalse((common.DATA / "store.json.gz").exists())


class Rules(unittest.TestCase):
    def test_launch_area_rule(self):
        self.assertTrue(nms.launch_area(feat("A1/26")))
        self.assertTrue(nms.launch_area(feat("A1/26", q="")))
        self.assertFalse(nms.launch_area(feat("A1/26", q="QFALC", text="E) AD CLSD")))   # aerodrome: not an area
        self.assertTrue(nms.launch_area(feat("A1/26", q="QFALC")))             # ... unless it has launch words
        self.assertFalse(nms.launch_area(feat("A1/26", end="PERM")))
        self.assertFalse(nms.launch_area(feat("A1/26", fl="050", text="E) GUN FIRING")))  # below FL100
        self.assertFalse(nms.launch_area(feat("A1/26", typ="C")))
        self.assertFalse(nms.launch_area(feat("A1/26", end="2027-03-01T00:00:00.000Z")))   # over 62 days

    def test_gnss_rule(self):
        self.assertTrue(nms.gnss(feat("A1/26", q="QGWXX", text="E) NIL")))
        self.assertTrue(nms.gnss(feat("A1/26", q="QXXXX", text="E) GPS JAMMING")))
        self.assertFalse(nms.gnss(feat("A1/26", q="QXXXX", text="E) RWY CLSD")))
        self.assertTrue(nms.gnss(feat("A1/26", q="QGWXX", typ="C")))           # cancellations are listed

    def test_q_code_read_from_icao_text(self):
        f = feat("M1/26", q="QFAXX")
        f["properties"]["coreNOTAMData"]["notamTranslation"][0]["formattedText"] = "M1/26 NOTAMN\nE) ROCKET LAUNCH"
        self.assertTrue(nms.launch_area(f), "no Q) line in the text: Launch sees no Q-code, so it is a candidate")
        g = feat("A1/26", q="", text="E) NIL")
        g["properties"]["coreNOTAMData"]["notamTranslation"][0]["formattedText"] = "A1/26 NOTAMN\nQ) LECM/QGWAU/IV/BO/E/000/999/\nE) NIL"
        self.assertTrue(nms.gnss(g))

    def test_refers_uses_icao_text_and_fir(self):
        self.assertEqual(nms.refers(feat("A2/26", typ="R", refers="A0001/26")), "A0001/26|ZPKM|")
        self.assertEqual(nms.refers(feat("A2/26", typ="R", refers="A0001/26", loc="LFEE")), "A0001/26|ZPKM|LFEE")
        self.assertIsNone(nms.refers(feat("A2/26")))

    def test_multi_fir_copies_all_kept(self):
        """One NOTAM listed once per location (LFXX) keeps every copy; a replacement takes only its own."""
        store = {}
        copies = [feat("F2347/26", fir="LFXX", loc=loc, nid="N" + loc) for loc in ("LFEE", "LFRR", "LFMM")]
        nms.apply(store, copies, SEED)
        self.assertEqual(len(store), 3)
        nms.apply(store, [feat("F2400/26", typ="R", refers="F2347/26", fir="LFXX", loc="LFRR", nid="R1")], SEED)
        self.assertEqual(sorted(store), ["F2347/26|LFXX|LFEE", "F2347/26|LFXX|LFMM", "F2400/26|LFXX|LFRR"])


if __name__ == "__main__":
    unittest.main()
