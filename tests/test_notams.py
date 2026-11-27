"""Offline tests for Cordon's reading of NOTAMs (cordon/notamtext.py), its NOTAM feed items (feed.notam_items, method
cordon-feed-1.3) and the space-operations file for Launch (cordon/notamlaunch.py, /data/notams/launch.json): no
network. tests/fixtures/notams-2026-11-25.json holds real NMS-API features cut from the archive pull of 25 Nov 2026."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from cordon import common, feed, nms, notamlaunch, notamtext as nt, significance as sg  # noqa: E402
from tic_doctrine import CONTRACT_REV, contract, registers  # noqa: E402
from test_significance import feat  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "notams-2026-11-25.json").read_text(encoding="utf-8"))
STORE = {nms.key(f): f for f in FIXTURE["features"]}
NOW = datetime(2026, 11, 26, 0, 0, tzinfo=timezone.utc)


def real(number: str) -> dict:
    return copy.deepcopy(next(f for f in FIXTURE["features"] if nms.meta(f)["number"] == number))


def w(start, end, d):
    return nt.windows(start, end, d)


class Schedule(unittest.TestCase):
    def test_no_schedule_is_one_window_and_no_end_is_none(self):
        self.assertEqual(w("2026-11-26T01:00:00Z", "2026-11-26T02:00:00Z", None),
                         ([{"start": "2026-11-26T01:00:00Z", "end": "2026-11-26T02:00:00Z"}], "single"))
        self.assertEqual(w("2026-11-26T01:00:00Z", None, "0100-0200"), ([], ""))

    def test_overnight_daily_time_is_clipped_to_b_and_c(self):
        ws, mode = w("2026-11-20T22:00:00Z", "2026-11-23T10:00:00Z", "2200-1000")
        self.assertEqual(mode, "daily")
        self.assertEqual([(x["start"], x["end"]) for x in ws], [
            ("2026-11-20T22:00:00Z", "2026-11-21T10:00:00Z"), ("2026-11-21T22:00:00Z", "2026-11-22T10:00:00Z"),
            ("2026-11-22T22:00:00Z", "2026-11-23T10:00:00Z")])

    def test_slash_and_trailing_dly(self):
        self.assertEqual(len(w("2026-11-20T00:00:00Z", "2026-11-23T07:00:00Z", "0000/0700")[0]), 4)
        self.assertEqual(w("2026-11-20T11:00:00Z", "2026-11-22T23:00:00Z", "1100-2300 DLY")[1], "daily")

    def test_week_days_and_exc(self):
        ws, mode = w("2026-11-24T07:00:00Z", "2026-11-28T23:59:00Z", "TUE-FRI 0700-2359, SAT 1300-2359")
        self.assertEqual((mode, len(ws), ws[-1]["start"]), ("daily", 5, "2026-11-28T13:00:00Z"))
        ws, _ = w("2026-11-23T05:00:00Z", "2026-11-30T14:00:00Z", "0500-1400 EXC SAT SUN")
        self.assertNotIn("2026-11-28T05:00:00Z", [x["start"] for x in ws])
        self.assertEqual(len(ws), 6)
        ws, _ = w("2026-11-23T05:00:00Z", "2026-11-30T14:00:00Z", "DLY 0500-1400 EXC 25-26")
        self.assertEqual([x["start"][:10] for x in ws][:3], ["2026-11-23", "2026-11-24", "2026-11-27"])

    def test_sun_times_and_misreads_are_span(self):
        self.assertEqual(w("2026-11-23T05:00:00Z", "2026-11-30T14:00:00Z", "SR-SS")[1], "span")
        # named days whose windows would fall outside B) to C): read wrong, so not used
        ws, mode = w("2026-11-23T05:00:00Z", "2026-11-24T14:00:00Z", "23 24 25 0500-1400")
        self.assertEqual((mode, ws), ("span", [{"start": "2026-11-23T05:00:00Z", "end": "2026-11-24T14:00:00Z"}]))

    def test_days_across_a_month_and_groups_after_a_time(self):
        ws, mode = w("2026-11-29T01:00:00Z", "2026-12-02T03:00:00Z", "29 30 01 02 0100-0300")
        self.assertEqual((mode, ws[-1]["start"]), ("schedule", "2026-12-02T01:00:00Z"))
        ws, mode = w("2026-11-23T05:00:00Z", "2026-11-29T16:00:00Z", "23 24 26-29 0500-1600, 25 1000-1600")
        self.assertEqual((mode, len(ws)), ("schedule", 7))
        self.assertIn({"start": "2026-11-25T10:00:00Z", "end": "2026-11-25T16:00:00Z"}, ws)

    def test_written_out_windows(self):
        ws, mode = w("2026-11-24T23:30:00Z", "2026-11-26T08:00:00Z",
                     "2611242330 TO 2611250800\n2611252330 TO 2611260800")
        self.assertEqual((mode, [x["start"] for x in ws]),
                         ("schedule", ["2026-11-24T23:30:00Z", "2026-11-25T23:30:00Z"]))

    def test_real_schedules(self):
        m = nms.meta(real("A1517/26"))
        ws, mode = w(m["effectiveStart"], m["effectiveEnd"], m["schedule"])
        self.assertEqual((mode, len(ws)), ("schedule", 7))
        self.assertEqual(ws[0], {"start": "2026-11-29T16:46:00Z", "end": "2026-11-29T17:37:00Z"})
        self.assertEqual(ws[-1], {"start": "2026-12-05T14:24:00Z", "end": "2026-12-05T15:16:00Z"})
        m = nms.meta(real("B4735/26"))       # month names: NOV 28 ..., DEC 01 ...
        ws, mode = w(m["effectiveStart"], m["effectiveEnd"], m["schedule"])
        self.assertEqual((mode, len(ws), ws[3]["start"]), ("schedule", 7, "2026-12-01T02:13:00Z"))
        m = nms.meta(real("A4551/26"))
        self.assertEqual(len(w(m["effectiveStart"], m["effectiveEnd"], m["schedule"])[0]), 11)


class Shape(unittest.TestCase):
    def geom(self, number):
        f = real(number)
        return nt.geometry(f, nms.icao_text(f))

    def test_q_line(self):
        q = nt.qline(nms.icao_text(real("M1563/26")))
        self.assertEqual((q["fir"], q["code"], q["radius_nm"]), ("RJJJ", "QWDLW", 5))

    def test_text_circle_in_metres(self):
        g, basis, pc = self.geom("M1563/26")             # RADIUS 300M CENTER 351020N1365524E
        self.assertEqual((g["type"], basis, pc), ("Polygon", "text", "area"))
        lon, lat = 136 + 55 / 60 + 24 / 3600, 35 + 10 / 60 + 20 / 3600
        for p in g["coordinates"][0]:
            self.assertAlmostEqual(nt._dist(lon, lat, p[0], p[1]), 300, delta=3)

    def test_text_polygon_over_nms_polygon_elsewhere(self):
        # UIII: NMS's polygon is near Irkutsk, 900 km from the area the text gives; UWWW: 65 km from the text's circle
        for number in ("L5283/26", "N0750/26"):
            f = real(number)
            q = nt.qline(nms.icao_text(f))
            own = [g["coordinates"][0] for g in f["geometry"]["geometries"] if g["type"] == "Polygon"]
            self.assertFalse(nt._agrees(own, q, True), number)
            self.assertEqual(self.geom(number)[1], "text", number)

    def test_arc_and_excluded_circle_fall_back_to_the_q_line(self):
        g, basis, pc = self.geom("E4739/26")             # a semicircle (an arc), minus an EXC circle
        self.assertEqual((basis, pc, len(g["coordinates"][0])), ("q-line circle", "approximate", 33))

    def test_polygon_from_text(self):
        g, basis, _ = self.geom("A4429/26")
        self.assertEqual((g["type"], basis), ("Polygon", "text"))
        self.assertGreaterEqual(len(g["coordinates"][0]), 6)

    def test_lines_are_not_areas(self):
        self.assertEqual(nt.shape("ALONG LINE 553000N0373000E-554000N0374000E-555000N0375000E"), [])
        self.assertEqual(len(nt.shape("WI 553000N0373000E-554000N0374000E-555000N0373000E-553000N0373000E")), 1)

    def test_nms_polygon_used_when_it_agrees(self):
        f = feat("A0001/26", text="AIRSPACE CLSD")
        ring = [[37.5, 55.5], [37.6, 55.5], [37.6, 55.6], [37.5, 55.6], [37.5, 55.5]]
        f["geometry"]["geometries"].append({"type": "Polygon", "coordinates": [ring]})
        self.assertEqual(nt.geometry(f, nms.icao_text(f))[1:], ("nms", "area"))
        far = [[[p[0] + 10, p[1]] for p in ring]]
        f["geometry"]["geometries"][-1]["coordinates"] = far
        self.assertEqual(nt.geometry(f, nms.icao_text(f))[1:], ("q-line circle", "approximate"))


class ChainFirst(unittest.TestCase):
    def test_a_replacement_keeps_the_first_number(self):
        b, chains = sg.new_baseline("2026-11-19"), {}
        t = "BOMB DISPOSAL WILL TAKE PLACE"
        a = feat("A0100/26", q="QWDLW", text=t, lu="2026-11-19T01:00:00.000Z")
        r1 = feat("A0105/26", q="QWDLW", typ="R", refers="A0100/26", text=t, lu="2026-11-19T02:00:00.000Z")
        r2 = feat("A0110/26", q="QWDLW", typ="R", refers="A0105/26", text=t, lu="2026-11-19T03:00:00.000Z")
        sg.update(b, chains, [a, r1, r2], datetime(2026, 11, 19, 4, tzinfo=timezone.utc))
        now = datetime(2026, 11, 19, 5, tzinfo=timezone.utc)
        self.assertEqual(sg.assess(r2, b, chains, now, country=None)["chain_first"], "A0100/26")
        self.assertEqual(sg.assess(a, b, chains, now, country=None)["chain_first"], "A0100/26")
        # not seen through the chains: the NOTAM it names
        self.assertEqual(sg.assess(r2, b, {}, now, country=None)["chain_first"], "A0105/26")


def sig_doc(numbers, tier=None):
    b = sg.new_baseline("2026-11-19")
    feats = []
    for n in numbers:
        f = real(n)
        s = sg.assess(f, b, {}, NOW, country=None)
        if tier:
            s["tier"] = tier
        f["properties"]["significance"] = s
        feats.append(f)
    return {"pulled_to": FIXTURE["pulled_to"], "generated_at": "2026-11-25T23:45:00Z", "features": feats,
            "tiers": {"significant": 0, "notable": len(feats), "routine": 0, "excluded": 0}}


class FeedItems(unittest.TestCase):
    NOTABLE = ["M1563/26", "A4429/26", "A4551/26", "E4739/26", "A0923/26"]

    def lint(self, f):
        regs = registers.ids(ROOT / "doctrine")
        return [m for _, sev, m in contract.check(f, regs, rev=CONTRACT_REV) if sev == "error"]

    def test_items_pass_the_linter(self):
        items, n = feed.notam_items(sig_doc(self.NOTABLE, "notable"), NOW)
        self.assertEqual((len(items), n["notable"]), (5, 5))
        feed.rev21.finish(items, {})
        for f in items:
            for k in ("published_at",):
                f["properties"][k] = "2026-11-26T00:00:00Z"
            self.assertEqual(self.lint(f), [], f["properties"]["id"])
            p = f["properties"]
            self.assertEqual((p["tier"], p["place_basis"], p["sources"][0]["grade"]), ("routine", "location", "A2"))
            self.assertNotIn("response_stage", p)
            self.assertNotIn("signal", p)                # rarity is history_short: no count to stand on yet

    def test_fields(self):
        items, _ = feed.notam_items(sig_doc(["M1563/26", "A4551/26"], "notable"), NOW)
        p = {f["properties"]["measures"]["number"]: f["properties"] for f in items}
        m = p["M1563/26"]
        self.assertEqual((m["id"], m["subject_id"]), ("cordon:notam:RJJJ:M1563-26", "cordon:notam:RJJJ:M1563-26"))
        self.assertEqual((m["event_start"], m["event_end"], m["countries"]),
                         ("2026-12-06T00:30:00Z", "2026-12-06T05:00:00Z", ["JP"]))
        self.assertTrue(" ".join(m["measures"]["text"].split()).startswith("BOMB DISPOSAL: ALERT AREA: RADIUS 300M"))
        self.assertTrue(m["title"].startswith("NOTAM M1563/26 RJNA (RJJJ), demolition of explosives: BOMB DISPOSAL"))
        e = p["A4551/26"]
        self.assertEqual((e["measures"]["window_mode"], e["measures"]["windows_total"]), ("schedule", 11))
        self.assertEqual(e["measures"]["geometry_basis"], "text")

    def test_new_significant_is_an_anomaly_with_its_baseline(self):
        doc = sig_doc(["M1563/26"], "significant")
        nms.meta(doc["features"][0])["issued"] = "2026-11-25T12:00:00.000Z"
        f = feed.notam_items(doc, NOW)[0][0]
        p = f["properties"]
        self.assertEqual((p["tier"], p["last_change"], p["baseline_ref"]["id"]),
                         ("anomaly", "new", "cordon-notam-history"))
        nms.meta(doc["features"][0])["issued"] = "2026-11-01T12:00:00.000Z"
        self.assertEqual(feed.notam_items(doc, NOW)[0][0]["properties"]["tier"], "routine")
        doc = sig_doc(["M1563/26"], "notable")
        nms.meta(doc["features"][0])["issued"] = "2026-11-25T12:00:00.000Z"
        self.assertEqual(feed.notam_items(doc, NOW)[0][0]["properties"]["tier"], "routine")

    def test_build_adds_items_and_health_or_withholds(self):
        fresh = {"faa-nms": {"last_ok": "2026-11-25T23:10:00Z", "failures": 0}}
        index = {"launch": {"status": "ok", "n": 3}}
        fc = feed.build({}, {}, {}, {}, NOW, fresh, notams=sig_doc(self.NOTABLE, "notable"), notam_index=index)
        ids = [f["properties"]["id"] for f in fc["features"] if f["properties"]["id"].startswith("cordon:notam:")]
        self.assertEqual((len(ids), fc["dropped"]), (5, []))
        h = fc["health"]["faa-nms"]
        self.assertEqual((h["state"], h["items"], h["launch_areas"], h["data_as_of"]),
                         ("fresh", 5, 3, FIXTURE["pulled_to"]))
        stale = {"faa-nms": {"last_ok": "2026-11-20T00:00:00Z", "failures": 3}}
        fc = feed.build({}, {}, {}, {}, NOW, stale, notams=sig_doc(self.NOTABLE, "notable"))
        self.assertFalse([f for f in fc["features"] if f["properties"]["id"].startswith("cordon:notam:")])
        self.assertEqual(fc["health"]["faa-nms"]["withheld"], 5)
        self.assertEqual(feed.METHOD, "cordon-feed-1.3")


class LaunchFile(unittest.TestCase):
    def test_selection(self):
        got = {f["properties"]["launch"]["number"]: f["properties"]["launch"]
               for f in notamlaunch.collection(STORE, NOW)}
        self.assertEqual(sorted(got), ["A1517/26", "A3590/26", "B4735/26"])
        self.assertNotIn("G5051/26", got)                # an aerospace exhibition: Q-code subject F
        self.assertEqual(got["A1517/26"]["hazard"], "reentry")
        self.assertEqual(got["A3590/26"]["hazard"], "debris fall")
        self.assertEqual((got["A1517/26"]["window_mode"], len(got["A1517/26"]["windows"])), ("schedule", 7))
        self.assertEqual(got["A1517/26"]["geometry_basis"], "text")
        self.assertIn("SPACE DEBRIS", got["A1517/26"]["hazard_words"])
        self.assertTrue(got["A3590/26"]["text"].startswith("UNBURNED DEBRIS EXPECTED TO FALL"))
        # ended over a day ago: dropped, as Launch drops a closure a day after it ends
        late = datetime(2026, 12, 3, 12, tzinfo=timezone.utc)
        self.assertNotIn("A3590/26", {f["properties"]["launch"]["number"] for f in notamlaunch.collection(STORE, late)})

    def test_written_and_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = (common.DATA, nms.CACHE, nms.STORE, nms.OUT)
            t = Path(tmp)
            common.DATA = t / "data"
            nms.CACHE, nms.STORE, nms.OUT = t / "cache", t / "cache" / "store.json.gz", t / "cache" / "out"
            try:
                idx = nms.write_out(STORE, {"pulled_to": FIXTURE["pulled_to"], "status": "ok"}, NOW)
                doc = json.loads((nms.OUT / "launch.json").read_text(encoding="utf-8"))
            finally:
                common.DATA, nms.CACHE, nms.STORE, nms.OUT = saved
        la = idx["launch"]
        self.assertEqual((la["status"], la["n"], la["url"], la["method"]),
                         ("ok", 3, "https://cordon.theintelligence.company/data/notams/launch.json",
                          "cordon-notam-launch-1.0"))
        self.assertNotIn("launch", [s["name"] for s in idx["subsets"]])
        self.assertEqual((doc["dataset"], doc["terms"], len(doc["features"])), ("launch", nms.TERMS, 3))
        for f in doc["features"]:
            self.assertIn(f["geometry"]["type"], ("Polygon", "MultiPolygon", "Point"))
            self.assertIn("coreNOTAMData", f["properties"])


if __name__ == "__main__":
    unittest.main()
