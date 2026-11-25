"""Offline tests for the significance of international NOTAMs (cordon/significance.py, method tic-significance-0.1)
and its place in the NMS lane: no network."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from cordon import common, nms, significance as sg  # noqa: E402
from test_nms import KEYS, SEED, FakeFAA  # noqa: E402

DAY0 = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def feat(number, q="QRTCA", typ="N", text="AIRSPACE CLSD", fir="UUWV", start="2026-11-20T00:00:00.000Z",
         end="2026-11-20T06:00:00.000Z", radius="5", fl="100", refers=None, nid=None, lu="2026-11-19T00:00:00.000Z",
         cls="INTL", loc=None, point=(37.6, 55.7)):
    head = f"{number} NOTAM{typ}" + (f" {refers}" if refers else "")
    icao = f"{head}\nQ) {fir}/{q}/IV/BO/W/000/{fl}/5530N03730E{int(radius):03d}\nA) {loc or fir}\nE) {text}"
    n = {"id": nid or "NMS_" + number, "number": number, "type": typ, "classification": cls, "selectionCode": q,
         "affectedFir": fir, "location": loc or fir, "icaoLocation": loc or fir, "issued": lu, "lastUpdated": lu,
         "effectiveStart": start, "effectiveEnd": end, "minimumFl": "000", "maximumFl": fl, "radius": radius,
         "text": text}
    return {"type": "Feature", "geometry": {"type": "GeometryCollection",
                                            "geometries": [{"type": "Point", "coordinates": list(point)}]},
            "properties": {"coreNOTAMData": {"notam": n, "notamTranslation": [{"type": "ICAO",
                                                                               "formattedText": icao}]}}}


class Cause(unittest.TestCase):
    def c(self, **kw):
        return sg.cause(feat("A0001/26", **kw))

    def test_fireworks_under_wd_or_wh_are_scheduled(self):
        for q in ("QWDLW", "QWHLW"):
            c = self.c(q=q, text="FIREWORK DISPLAY WILL TAKE PLACE AT 050127N 1181916E")
            self.assertEqual((c["cause"], c["cause_group"]), ("fireworks", "scheduled_and_routine"))
            self.assertIn("text: FIREWORK", c["cause_basis"])

    def test_demolition_under_wd_is_a_hazard_to_people(self):
        c = self.c(q="QWDLW", text="DEMOLITION OF EXPLOSIVES WILL TAKE PLACE")
        self.assertEqual((c["cause"], c["cause_group"]), ("demolition of explosives", "hazard_to_people"))
        self.assertEqual(c["cause_basis"], ["Q-code WD (demolition of explosives)", "text: DEMOLITION"])

    def test_wr_and_wh_by_code(self):
        self.assertEqual(self.c(q="QWRLW", text="FOREST TREATMENT ACTIVITY")["cause_group"], "hazard_to_people")
        self.assertEqual(self.c(q="QWHLW", text="BLASTING ACT")["cause"], "blasting")

    def test_words_never_override_the_code(self):
        c = self.c(q="QWMLW", text="MISSILE FIRING. SECURITY ZONE")
        self.assertEqual(c["cause_group"], "military_and_test")
        self.assertIsNone(c["excluded"], "a missile firing is military, not space")

    def test_rt_takes_its_cause_from_the_words(self):
        self.assertEqual(self.c(text="AIRSPACE CLSD FOR SECURITY REASONS")["cause_group"],
                         "security_and_law_enforcement")
        self.assertEqual(self.c(text="POLICE OPERATION")["cause"], "law enforcement operation")
        self.assertEqual(self.c(text="VIP FLT. SECURITY AREA")["cause"], "VIP movement")
        self.assertEqual(self.c(text="CONTROLLED DETONATION")["cause_group"], "hazard_to_people")
        c = self.c(text="AIRSPACE CLSD WI AREA 5530N03730E")
        self.assertEqual((c["cause"], c["cause_group"], c["cause_basis"][-1]), ("unknown", "unknown",
                                                                                 "no cause words"))

    def test_space_words_are_launchs(self):
        for t in ("TEMPORARY DANGER AREA DUE TO SPACE DEBRIS RETURN", "AEROSPACE FLT ACT BY CHINA",
                  "DANGEROUS AREA FOR ROCKET LAUNCH STAGE 1"):
            c = self.c(q="QRDCA", text=t)
            self.assertEqual((c["cause_group"], c["excluded"]), ("space_operations", "launch"), t)
        for t in ("MISSILE, ROCKET FIRING", "INTENSIVE LAUNCH OF MODEL ROCKETS", "AIRSPACE FLT OPS RESTRICTED"):
            self.assertIsNone(self.c(q="QRDCA", text=t)["excluded"], t)

    def test_gnss_is_excluded(self):
        c = self.c(q="QGAXX", text="GNSS UNRELIABLE")
        self.assertEqual((c["cause_group"], c["excluded"]), ("gnss", "noisefloor"))
        self.assertFalse(sg.candidate(feat("A0001/26", q="QGAXX")), "not a ranked subject either")

    def test_candidates(self):
        self.assertTrue(sg.candidate(feat("A0001/26")))
        self.assertFalse(sg.candidate(feat("A0001/26", cls="DOMESTIC")))
        self.assertFalse(sg.candidate(feat("A0001/26", q="QFALC")))
        self.assertFalse(sg.candidate(feat("A0001/26", typ="C", refers="A0000/26")))


class Baseline(unittest.TestCase):
    def setUp(self):
        self.b, self.ch = sg.new_baseline("2026-11-19"), {}

    def test_a_version_counts_once(self):
        f = feat("A0001/26")
        r = sg.update(self.b, self.ch, [f, f], DAY0)
        self.assertEqual((r["new"], r["repeat"]), (1, 1))
        later = feat("A0001/26", lu="2026-11-19T05:00:00.000Z")      # a later version of the same NOTAM
        self.assertEqual(sg.update(self.b, self.ch, [later], DAY0 + timedelta(hours=6))["new"], 0)
        self.assertEqual(sg.update(self.b, self.ch, [feat("A0002/26")], DAY0 + timedelta(hours=7))["new"], 1)
        self.assertEqual(self.b["counts"], {"UUWV|RT": {"0": 2}})
        self.assertEqual(self.b["first"], {"UUWV": 0, "UU": 0})

    def test_a_notam_listed_per_location_counts_once(self):
        r = sg.update(self.b, self.ch, [feat("A0001/26", fir="LEXX", loc="LECB", nid="N1"),
                                        feat("A0001/26", fir="LEXX", loc="LECM", nid="N2")], DAY0)
        self.assertEqual((r["new"], r["other_location"]), (1, 1))
        self.assertEqual(len(self.ch), 2, "each location keeps its chain, for its replacements")
        store = {nms.key(f): f for f in (feat("A0001/26", fir="LEXX", loc="LECB", q="QWHLW", text="BLASTING"),
                                         feat("A0001/26", fir="LEXX", loc="LECM", q="QWHLW", text="BLASTING"))}
        out, tiers = sg.ranked(store, self.b, self.ch, DAY0, country=None)
        self.assertEqual((len(out), tiers["notable"]), (1, 1))

    def test_lost_chains_do_not_count_again(self):
        sg.update(self.b, self.ch, [feat("A0001/26")], DAY0)
        r = sg.update(self.b, {}, [feat("A0001/26"), feat("A0002/26", lu="2026-11-20T00:00:00.000Z")],
                      DAY0 + timedelta(days=1), counted_before=self.b["updated_at"])
        self.assertEqual((r["rechained"], r["new"]), (1, 1))
        self.assertEqual(self.b["counts"]["UUWV|RT"], {"0": 1, "1": 1})

    def test_rarity_waits_for_90_days_of_history(self):
        sg.update(self.b, self.ch, [feat("A0001/26", q="QFALC")], DAY0)       # any INTL NOTAM starts the history
        lab, nums = sg.rarity(self.b, "UUWV", "WH", 10)
        self.assertEqual((lab, nums), ("history_short", ["UUWV", 0, 10]))
        self.assertIn("10 days held; rarity needs 90", sg.rarity_text(lab, nums, "WH", "UUWV"))
        self.assertEqual(sg.rarity(self.b, "UUWV", "WH", 120)[0], "rare")
        self.b["counts"]["UUWV|WH"] = {"5": 1, "60": 1}
        self.assertEqual(sg.rarity(self.b, "UUWV", "WH", 120), ("uncommon", ["UUWV", 2, 120]))
        self.b["counts"]["UUWV|WH"]["100"] = 1
        self.assertEqual(sg.rarity(self.b, "UUWV", "WH", 120)[0], "common")
        self.assertEqual(sg.rarity(self.b, "UUWV", "WH", 500), ("rare", ["UUWV", 0, 365]), "a year's window")

    def test_rarity_falls_back_to_the_icao_prefix(self):
        self.b["first"] = {"UUWV": 0, "UU": 0, "UUEE": 80}
        self.b["counts"] = {"UUWV|WH": {"3": 1}}
        lab, nums = sg.rarity(self.b, "UUEE", "WH", 100)
        self.assertEqual((lab, nums), ("uncommon", ["UU", 1, 100]))
        self.assertIn("ICAO prefix UU", sg.rarity_text(lab, nums, "WH", "UUEE"))

    def test_large_for_region_needs_30(self):
        for i in range(29):
            sg.update(self.b, self.ch, [feat(f"A{i:04d}/26", radius="2")], DAY0)
        self.assertIsNone(sg.large(self.b, "UUWV", "RT", 500.0, 1.0)[0])
        sg.update(self.b, self.ch, [feat("A0099/26", radius="2")], DAY0)
        big, nums = sg.large(self.b, "UUWV", "RT", sg.area_km2(feat("X", radius="40")), 6.0)
        self.assertTrue(big)
        self.assertEqual(nums[0][0], "area")
        self.assertFalse(sg.large(self.b, "UUWV", "RT", sg.area_km2(feat("X", radius="2")), 6.0)[0])

    def test_dynamics_along_a_replacement_chain(self):
        sg.update(self.b, self.ch, [feat("A0001/26", start="2026-11-20T00:00:00.000Z",
                                         end="2026-11-20T06:00:00.000Z", radius="4")], DAY0)
        r = sg.update(self.b, self.ch, [feat("A0002/26", typ="R", refers="A0001/26", start="2026-11-23T00:00:00.000Z",
                                             end="2026-11-23T06:00:00.000Z", radius="4",
                                             lu="2026-11-19T06:00:00.000Z")], DAY0 + timedelta(hours=6))
        self.assertEqual((r["replaced"], r["new"]), (1, 0))
        sg.update(self.b, self.ch, [feat("A0003/26", typ="R", refers="A0002/26", start="2026-11-25T00:00:00.000Z",
                                         end="2026-11-26T06:00:00.000Z", radius="6",
                                         lu="2026-11-19T08:00:00.000Z")], DAY0 + timedelta(hours=8))
        d = sg.dynamics(self.ch["A0003/26|UUWV|UUWV"])
        self.assertEqual(d, {"date_slips": 2, "extended": True, "enlarged": True, "cancelled_early": False,
                             "notams": 3})
        self.assertEqual(self.b["counts"]["UUWV|RT"], {"0": 1}, "a chain counts once")
        sg.update(self.b, self.ch, [feat("A0004/26", typ="C", refers="A0003/26", start="2026-11-25T02:00:00.000Z",
                                         lu="2026-11-25T02:00:00.000Z")], DAY0 + timedelta(days=6))
        self.assertTrue(sg.dynamics(self.ch["A0003/26|UUWV|UUWV"])["cancelled_early"])
        # the ended chains leave once they are CHAIN_KEEP_DAYS past their end
        sg.prune(self.b, self.ch, DAY0 + timedelta(days=30))
        self.assertEqual(self.ch, {})

    def test_dumps_round_trips(self):
        sg.update(self.b, self.ch, [feat("A0001/26")], DAY0)
        text = sg.dumps(self.b)
        self.assertEqual(json.loads(text), self.b)
        self.assertIn('\n "UUWV|RT":{"0":1}', text, "one entry per line")


class Tier(unittest.TestCase):
    NONE = {"date_slips": 0, "enlarged": False}

    def test_rules(self):
        t = sg.tier
        self.assertEqual(t("hazard_to_people", "rare", self.NONE, None, "WH")[0], "significant")
        self.assertEqual(t("disaster_response", "rare", self.NONE, None, "RT")[0], "significant")
        self.assertEqual(t("hazard_to_people", "history_short", self.NONE, None, "WH")[0], "notable")
        self.assertEqual(t("disaster_response", "common", self.NONE, None, "RT")[0], "routine")
        self.assertEqual(t("security_and_law_enforcement", "rare", self.NONE, None, "RT")[0], "notable")
        self.assertEqual(t("military_and_test", "common", {"date_slips": 2, "enlarged": False}, None, "RD")[0],
                         "notable")
        self.assertEqual(t("military_and_test", "common", {"date_slips": 1, "enlarged": False}, None, "RD")[0],
                         "routine")
        self.assertEqual(t("military_and_test", "common", {"date_slips": 0, "enlarged": True}, None, "RD")[0],
                         "notable")
        self.assertEqual(t("unknown", "common", self.NONE, True, "RT")[0], "notable")
        self.assertEqual(t("unknown", "common", self.NONE, True, "WU")[0], "routine", "large lifts RT, RP, RD only")

    def test_caps(self):
        self.assertEqual(sg.tier("scheduled_and_routine", "rare", self.NONE, True, "RT")[0], "notable")
        self.assertEqual(sg.tier("unknown", "rare", {"date_slips": 3, "enlarged": True}, True, "RP")[0], "notable")

    def test_assess_and_basis(self):
        b, ch = sg.new_baseline("2026-11-19"), {}
        f = feat("A0001/26", q="QWHLW", text="BLASTING ACT")
        sg.update(b, ch, [f], DAY0 + timedelta(days=8))
        s = sg.assess(f, b, ch, DAY0 + timedelta(days=8), country=lambda _f: "Russia")
        self.assertEqual((s["tier"], s["method"], s["rarity"]), ("notable", "tic-significance-0.1", "history_short"))
        self.assertEqual(s["basis"], "blasting notice, Russia (UUWV); history short (0 days)")
        self.assertIsNone(sg.assess(feat("A0002/26", q="QRDCA", text="SPACE DEBRIS"), b, ch, DAY0))

    def test_country_from_the_point(self):
        self.assertEqual(sg.country_of(feat("A0001/26", point=(37.6, 55.7))), "Russia")
        self.assertIsNone(sg.country_of(feat("A0001/26", point=(-30.0, 30.0))), "at sea")


class Lane(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = (common.DATA, nms.CACHE, nms.STORE, nms.OUT)
        common.DATA = t / "data"
        nms.CACHE, nms.STORE, nms.OUT = t / "cache", t / "cache" / "store.json.gz", t / "cache" / "out"

    def tearDown(self):
        common.DATA, nms.CACHE, nms.STORE, nms.OUT = self.saved
        self.tmp.cleanup()

    def run_lane(self, faa, now):
        orig = nms.Client.__init__

        def init(c, env=None, opener=None, pause=0):
            orig(c, env, opener=faa, pause=0)
        nms.Client.__init__ = init
        try:
            return nms.collect(now, env=KEYS, fetch=lambda url: (_ for _ in ()).throw(OSError("offline")))
        finally:
            nms.Client.__init__ = orig

    def test_bulk_publishes_significant_json(self):
        bulk = {"INTERNATIONAL": [feat("A0001/26", q="QWHLW", text="BLASTING ACT"),
                                  feat("A0002/26", q="QWDLW", text="FIREWORK DISPLAY"),
                                  feat("A0003/26", q="QRDCA", text="SPACE DEBRIS RETURN"),
                                  feat("A0004/26", q="QFALC", text="AD CLSD")],
                "FDC": [], "MILITARY": [], "DOMESTIC": []}
        now = SEED + timedelta(hours=25)
        st, _ = self.run_lane(FakeFAA(bulk=bulk), now)
        self.assertEqual(st["significance"]["status"], "ok")
        self.assertEqual(st["significance"]["counts"]["new"], 3)
        self.assertEqual(st["significance"]["tiers"], {"significant": 0, "notable": 1, "routine": 1, "excluded": 1})
        sig = json.loads((nms.OUT / "significant.json").read_text(encoding="utf-8"))
        self.assertEqual([nms.meta(f)["number"] for f in sig["features"]], ["A0001/26"])
        self.assertEqual(sig["features"][0]["properties"]["significance"]["cause"], "blasting")
        self.assertIn("Not FAA data", sig["source_note"])
        idx = json.loads((nms.OUT / "index.json").read_text(encoding="utf-8"))
        self.assertEqual((idx["significance"]["file"], idx["significance"]["n"]), ("significant.json", 1))
        self.assertNotIn("significant", [s["name"] for s in idx["subsets"]], "not a subset a reader rebuilds from")
        b = json.loads((common.DATA / nms.SIG_BASELINE).read_text(encoding="utf-8"))
        self.assertEqual(b["start"], now.strftime("%Y-%m-%d"))
        self.assertTrue(nms.chains_path().exists())
        # the next run's delta repeats A0001: no second count
        st, _ = self.run_lane(FakeFAA(delta=[feat("A0001/26", q="QWHLW", text="BLASTING ACT")]),
                              now + timedelta(hours=1))
        self.assertEqual((st["significance"]["counts"]["new"], st["significance"]["counts"]["repeat"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
