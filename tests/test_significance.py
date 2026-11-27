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
from cordon import common, nms, nmsarchive, significance as sg  # noqa: E402
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

    def test_wd_wh_wr_are_a_hazard_only_with_hazard_words(self):
        c = self.c(q="QWDLW", text="BOMB DISPOSAL: ALERT AREA RADIUS 300M (NAGOYA-SHI)")
        self.assertEqual((c["cause"], c["cause_group"]), ("demolition of explosives", "hazard_to_people"))
        self.assertEqual(c["cause_basis"], ["Q-code WD (demolition of explosives)", "text: BOMB"])
        self.assertEqual(self.c(q="QWHLW", text="DEMOLITION OF THE COOLING TOWERS")["cause_group"],
                         "hazard_to_people")
        self.assertEqual(self.c(q="QWRLW", text="TOXIC GAS LEAK. EVACUATION")["cause_group"], "hazard_to_people")

    def test_wd_wh_wr_without_hazard_words(self):
        c = self.c(q="QWHLW", text="BLASTING ACT WILL TAKE PLACE WITHIN RADIUS 1NM")
        self.assertEqual((c["cause_group"], c["cause_basis"][-1]), ("scheduled_and_routine", "no hazard words"))
        self.assertEqual(self.c(q="QWHLW", text="AVALANCHE CTL BLASTING ACT")["cause"], "avalanche control")
        self.assertEqual(self.c(q="QWHLW", text="QUARRY AND BLASTING")["cause"], "quarry or mine blasting")
        self.assertEqual(self.c(q="QWRLW", text="FOREST TREATMENT ACTIVITY")["cause_group"], "scheduled_and_routine")
        self.assertEqual(self.c(q="QWDLW", text="DEMOLITION OF EXPLOSIVES TRG(WITH FIRING)")["cause_group"],
                         "military_and_test")
        self.assertEqual(self.c(q="QWDLW", text="DEMOLITION OF EXPLOSIVES WILL TAKE PLACE")["cause_group"],
                         "military_and_test")
        self.assertEqual(self.c(q="QWRLW", text="ACTIVITY IN AREA")["cause_group"], "unknown")

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

    def test_a_medical_evacuation_in_a_military_area_is_military(self):
        # E4492/26 (YMMM, QRRCA), published as hazard to people on 27 Nov 2026 for "EVACUATION".
        text = ("TASMAN SEA AIRSPACE M440CDGHLM ACT DUE MIL FLYING AND NON-FLYING\r\nFOR SAR, MEDICAL EMERG EVACUATION "
                "(MEDEVAC) AND FLOOD OR FIRE RELIEF\r\nFIRE FIGHTING (FFR) ACFT CTC TEL: 02 9537 4652\r\n"
                "POINT OF CTC: FLEET EXERCISE COORDINATOR")
        c = self.c(q="QRRCA", text=text, fir="YMMM")
        self.assertEqual((c["cause"], c["cause_group"], c["cause_basis"][-1]),
                         ("military operation", "military_and_test", "text: MIL"))
        # A medical evacuation alone is no evacuation; an evacuation of people still is.
        self.assertNotEqual(self.c(text="AIRSPACE CLSD FOR MEDICAL EVACUATION FLT")["cause_group"], "hazard_to_people")
        self.assertNotEqual(self.c(text="AEROMEDICAL EVACUATION OPS")["cause_group"], "hazard_to_people")
        self.assertEqual(self.c(text="EVACUATION OF RESIDENTS DUE TO GAS LEAK")["cause_group"], "hazard_to_people")

    def test_a_military_word_before_the_hazard_word_wins_in_rt_rr_ra(self):
        # E4739/26 (RKRR, QRTCA): an explosive device carried by military aircraft, not a hazard to people.
        c = self.c(text="TEMPO RESTRICTED AREA ACT AS FLW : ... THIS NOTAM APPLIES ONLY TO THE MIL ACFT EQUIPPED WITH "
                        "EED (ELECTRO EXPLOSIVE DEVICE).", fir="RKRR")
        self.assertEqual(c["cause_group"], "military_and_test")
        self.assertEqual(self.c(q="QRRCA", text="MIL FLYING FOR FIRE FIGHTING")["cause_group"], "military_and_test")
        # The hazard word first still wins, and other subjects are unchanged.
        self.assertEqual(self.c(text="CONTROLLED DETONATION OF UXO BY MIL EOD TEAM")["cause_group"], "hazard_to_people")
        self.assertEqual(self.c(q="QWULW", text="MIL UAS IN SUPPORT OF EXPLOSIVE DEMOLITION")["cause_group"],
                         "hazard_to_people")

    def test_a_training_word_anywhere_keeps_wd_military(self):
        for t in ("TRG WITH LIVE AMMUNITION", "MIL TRG WITH LIVE AMMUNITION", "MILITARY EOD TRAINING"):
            self.assertEqual(self.c(q="QWDLW", text=t)["cause_group"], "military_and_test", t)

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
        self.assertEqual(self.b["counts"], {"UUWV|RT|unknown": {"0": 2}}, "per region, subject and cause group")
        sg.update(self.b, self.ch, [feat("A0003/26", text="VIP FLT")], DAY0 + timedelta(hours=8))
        self.assertEqual(self.b["counts"]["UUWV|RT|scheduled_and_routine"], {"0": 1})
        self.assertEqual(self.b["first"], {"UUWV": 0, "UU": 0})

    def test_a_notam_listed_per_location_counts_once(self):
        r = sg.update(self.b, self.ch, [feat("A0001/26", fir="LEXX", loc="LECB", nid="N1"),
                                        feat("A0001/26", fir="LEXX", loc="LECM", nid="N2")], DAY0)
        self.assertEqual((r["new"], r["other_location"]), (1, 1))
        self.assertEqual(len(self.ch), 2, "each location keeps its chain, for its replacements")
        store = {nms.key(f): f for f in (feat("A0001/26", fir="LEXX", loc="LECB", q="QWHLW", text="UXO DISPOSAL"),
                                         feat("A0001/26", fir="LEXX", loc="LECM", q="QWHLW", text="UXO DISPOSAL"))}
        out, tiers = sg.ranked(store, self.b, self.ch, DAY0, country=None)
        self.assertEqual((len(out), tiers["notable"]), (1, 1))

    def test_lost_chains_do_not_count_again(self):
        sg.update(self.b, self.ch, [feat("A0001/26")], DAY0)
        r = sg.update(self.b, {}, [feat("A0001/26"), feat("A0002/26", lu="2026-11-20T00:00:00.000Z")],
                      DAY0 + timedelta(days=1), counted_before=self.b["updated_at"])
        self.assertEqual((r["rechained"], r["new"]), (1, 1))
        self.assertEqual(self.b["counts"]["UUWV|RT|unknown"], {"0": 1, "1": 1})

    def test_rarity_waits_for_90_days_of_history(self):
        sg.update(self.b, self.ch, [feat("A0001/26", q="QFALC")], DAY0)       # any INTL NOTAM starts the history
        H = "hazard_to_people"
        lab, nums = sg.rarity(self.b, "UUWV", "WH", H, 10)
        self.assertEqual((lab, nums), ("history_short", ["UUWV", 0, 10]))
        self.assertIn("10 days held; rarity needs 90", sg.rarity_text(lab, nums, "WH", "UUWV", H))
        self.assertEqual(sg.rarity(self.b, "UUWV", "WH", H, 120)[0], "rare")
        self.b["counts"]["UUWV|WH|hazard_to_people"] = {"5": 1, "60": 1}
        self.b["counts"]["UUWV|WH|scheduled_and_routine"] = {"5": 9}
        self.assertEqual(sg.rarity(self.b, "UUWV", "WH", H, 120), ("uncommon", ["UUWV", 2, 120]))
        self.b["counts"]["UUWV|WH|hazard_to_people"]["100"] = 1
        self.assertEqual(sg.rarity(self.b, "UUWV", "WH", H, 120)[0], "common")
        self.assertEqual(sg.rarity(self.b, "UUWV", "WH", H, 500), ("rare", ["UUWV", 0, 365]), "a year's window")
        self.assertEqual(sg.rarity(self.b, "UUWV", "WH", "military_and_test", 120)[0], "rare", "per cause group")

    def test_rarity_falls_back_to_the_icao_prefix(self):
        self.b["first"] = {"UUWV": 0, "UU": 0, "UUEE": 80}
        self.b["counts"] = {"UUWV|WH|hazard_to_people": {"3": 1}}
        lab, nums = sg.rarity(self.b, "UUEE", "WH", "hazard_to_people", 100)
        self.assertEqual((lab, nums), ("uncommon", ["UU", 1, 100]))
        self.assertIn("ICAO prefix UU", sg.rarity_text(lab, nums, "WH", "UUEE"))

    def test_large_for_region_needs_30_and_90_days(self):
        for i in range(29):
            sg.update(self.b, self.ch, [feat(f"A{i:04d}/26", radius="2")], DAY0)
        big40 = sg.area_km2(feat("X", radius="40"))
        self.assertIsNone(sg.large(self.b, "UUWV", "RT", big40, 120)[0], "29 held")
        sg.update(self.b, self.ch, [feat("A0099/26", radius="2")], DAY0)
        self.assertIsNone(sg.large(self.b, "UUWV", "RT", big40, 30)[0], "30 days of history")
        big, nums = sg.large(self.b, "UUWV", "RT", big40, 90)
        self.assertTrue(big)
        self.assertIn("area", sg.large_text(big, nums, "RT", "UUWV"))
        self.assertFalse(sg.large(self.b, "UUWV", "RT", sg.area_km2(feat("X", radius="2")), 90)[0])

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
        self.assertEqual(self.b["counts"]["UUWV|RT|unknown"], {"0": 1}, "a chain counts once")
        sg.update(self.b, self.ch, [feat("A0004/26", typ="C", refers="A0003/26", start="2026-11-25T02:00:00.000Z",
                                         lu="2026-11-25T02:00:00.000Z")], DAY0 + timedelta(days=6))
        self.assertTrue(sg.dynamics(self.ch["A0003/26|UUWV|UUWV"])["cancelled_early"])
        # the ended chains leave once they are CHAIN_KEEP_DAYS past their end
        sg.prune(self.ch, DAY0 + timedelta(days=30))
        self.assertEqual(self.ch, {})
        self.assertEqual(self.b["counts"]["UUWV|RT|unknown"], {"0": 1}, "the baseline is never pruned")
        sg.prune(self.ch, DAY0 + timedelta(days=3000))
        self.assertEqual(self.b["counts"]["UUWV|RT|unknown"], {"0": 1})

    def test_a_daily_reactivation_is_not_a_slip(self):
        sg.update(self.b, self.ch, [feat("E0001/26", start="2026-11-19T08:00:00.000Z",
                                         end="2026-11-19T18:00:00.000Z")], DAY0)
        # re-issued on 19 Nov at 12:00, after the 08:00 start: tomorrow's activation, not a postponement
        sg.update(self.b, self.ch, [feat("E0002/26", typ="R", refers="E0001/26", start="2026-11-20T08:00:00.000Z",
                                         end="2026-11-20T18:00:00.000Z", lu="2026-11-19T12:00:00.000Z")],
                  DAY0 + timedelta(hours=1))
        self.assertEqual(sg.dynamics(self.ch["E0002/26|UUWV|UUWV"])["date_slips"], 0)

    def test_dumps_round_trips(self):
        sg.update(self.b, self.ch, [feat("A0001/26")], DAY0)
        text = sg.dumps(self.b)
        self.assertEqual(json.loads(text), self.b)
        self.assertIn('\n "UUWV|RT|unknown":{"0":1}', text, "one entry per line")


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
        f = feat("A0001/26", q="QWHLW", text="BLASTING TO DEMOLISH THE BRIDGE")
        sg.update(b, ch, [f], DAY0 + timedelta(days=8))
        s = sg.assess(f, b, ch, DAY0 + timedelta(days=8), country=lambda _f: "Russia")
        self.assertEqual((s["tier"], s["method"], s["rarity"]), ("notable", "tic-significance-0.1", "history_short"))
        self.assertEqual(s["basis"], "blasting notice, Russia (UUWV); history short (0 days)")
        self.assertEqual(sg.assess(feat("A0003/26", q="QWHLW", text="BLASTING ACT"), b, ch, DAY0)["tier"], "routine")
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
        bulk = {"INTERNATIONAL": [feat("A0001/26", q="QWHLW", text="UXO DISPOSAL, BLASTING"),
                                  feat("A0002/26", q="QWDLW", text="FIREWORK DISPLAY"),
                                  feat("A0003/26", q="QRDCA", text="SPACE DEBRIS RETURN"),
                                  feat("A0004/26", q="QFALC", text="AD CLSD")],
                "FDC": [], "MILITARY": [], "DOMESTIC": []}
        now = SEED + timedelta(hours=25)
        st, _ = self.run_lane(FakeFAA(bulk=bulk), now)
        self.assertEqual(st["significance"]["status"], "ok")
        self.assertEqual((st["significance"]["counts"]["new"], st["significance"]["counts"]["excluded"]), (2, 1))
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
        st, _ = self.run_lane(FakeFAA(delta=[feat("A0001/26", q="QWHLW", text="UXO DISPOSAL, BLASTING")]),
                              now + timedelta(hours=1))
        self.assertEqual((st["significance"]["counts"]["new"], st["significance"]["counts"]["repeat"]), (0, 1))


class SelfBackfill(unittest.TestCase):
    """The lane builds the baseline from the archive's release day files itself (a fake releases API)."""

    def setUp(self):
        from test_nmsarchive import FakeGitHub
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = (common.DATA, nms.CACHE, nms.STORE, nms.OUT)
        common.DATA = t / "data"
        nms.CACHE, nms.STORE, nms.OUT = t / "cache", t / "cache" / "store.json.gz", t / "cache" / "out"
        self.fake = FakeGitHub()
        self.gh = nmsarchive.GitHub("token", opener=self.fake)
        # two archived days: a blasting chain on 19 Nov, replaced on 20 Nov (a postponement), and a VIP closure
        self.days = [(DAY0, [feat("A0001/26", q="QWHLW", text="UXO DISPOSAL", start="2026-11-21T00:00:00.000Z",
                                  end="2026-11-21T06:00:00.000Z")]),
                     (DAY0 + timedelta(days=1),
                      [feat("A0002/26", q="QWHLW", typ="R", refers="A0001/26", text="UXO DISPOSAL",
                            start="2026-11-23T00:00:00.000Z", end="2026-11-23T06:00:00.000Z",
                            lu="2026-11-20T12:00:00.000Z"), feat("A0003/26", text="VIP FLT")])]
        for when, feats in self.days:
            nmsarchive.run(feats, "delta", when, env={}, gh=self.gh, directory=t / "archive-work")

    def tearDown(self):
        common.DATA, nms.CACHE, nms.STORE, nms.OUT = self.saved
        self.tmp.cleanup()

    def test_missing_baseline_is_built_from_the_archive(self):
        now = DAY0 + timedelta(days=1, hours=2)
        out = nms.update_significance(self.days[1][1], now, env={}, gh=self.gh)
        self.assertEqual(out["backfill"]["status"], "done")
        self.assertEqual((out["backfill"]["from"], out["backfill"]["days"]), ("2026-11-19", 2))
        self.assertEqual(out["counts"]["new"], 0, "this pull is already in the archive")
        b, ch = nms.load_significance()
        self.assertEqual((b["start"], b["backfill"]["done"]), ("2026-11-19", True))
        self.assertEqual(b["counts"], {"UUWV|WH|hazard_to_people": {"0": 1}, "UUWV|RT|scheduled_and_routine": {"1": 1}})
        self.assertEqual(sg.dynamics(ch["A0002/26|UUWV|UUWV"])["date_slips"], 1)
        # done: the next run reads no release
        calls = len(self.fake.calls)
        out = nms.update_significance([], now + timedelta(hours=1), env={}, gh=self.gh)
        self.assertNotIn("backfill", out)
        self.assertEqual(len(self.fake.calls), calls)

    def test_a_baseline_started_without_the_archive_is_rebuilt(self):
        nms.update_significance(self.days[1][1], DAY0 + timedelta(days=1), env={})    # no token: starts today
        b, _ = nms.load_significance()
        self.assertEqual((b["start"], b.get("backfill")), ("2026-11-20", None))
        out = nms.update_significance([], DAY0 + timedelta(days=1, hours=1), env={}, gh=self.gh)
        self.assertEqual(out["backfill"]["status"], "done")
        self.assertEqual(nms.load_significance()[0]["start"], "2026-11-19")

    def test_the_backfill_is_bounded_and_resumes(self):
        b, ch, rep = nms.backfill(None, None, DAY0 + timedelta(days=1), self.gh, budget_s=0.0)
        self.assertEqual((rep["status"], rep["days"], rep["to"]), ("partial", 1, "2026-11-19"), "one day a run")
        b, ch, rep = nms.backfill(b, ch, DAY0 + timedelta(days=1), self.gh)
        self.assertEqual((rep["status"], rep["days"], b["backfill"]["to"]), ("done", 1, "2026-11-20"))

    def test_a_failing_archive_never_fails_the_lane(self):
        self.fake.releases.clear()
        self.fake.blobs.clear()
        out = nms.update_significance([], DAY0, env={}, gh=nmsarchive.GitHub("t", opener=lambda *a, **k: 1 / 0))
        self.assertEqual(out["status"], "failing")
        self.assertFalse((common.DATA / nms.SIG_BASELINE).exists(), "nothing half-built is saved")


class NeverItsOwnBaseline(unittest.TestCase):
    """A NOTAM is never judged against its own count: several locations, lost chains, the bulk after a lost cache,
    and chains saved apart from the committed baseline."""
    BOMB = {"q": "QWDLW", "text": "BOMB DISPOSAL: ALERT AREA RADIUS 300M", "fir": "RJJJ", "point": (139.8, 35.6)}

    def setUp(self):
        self.b, self.ch = sg.new_baseline("2026-08-01"), {}
        self.b["first"] = {"RJJJ": 0, "RJ": 0}              # 110 days of history at DAY0, none of these before
        self.now = DAY0

    def bomb(self, loc, **kw):
        return feat("A0001/26", loc=loc, nid="N" + loc, **{**self.BOMB, **kw})

    def test_every_location_takes_the_first_judgement(self):
        r = sg.update(self.b, self.ch, [self.bomb("RJTT"), self.bomb("RJAA")], self.now)
        self.assertEqual((r["new"], r["other_location"]), (1, 1))
        self.assertEqual({c["ra"] for c in self.ch.values()}, {"rare"}, "the second location is the same NOTAM")
        store = {nms.key(f): f for f in (self.bomb("RJTT"), self.bomb("RJAA"))}
        out, tiers = sg.ranked(store, self.b, self.ch, self.now, country=None)
        self.assertEqual(tiers["significant"], 1)
        self.assertIn("0 earlier", out[0]["properties"]["significance"]["rarity_basis"])

    def test_rechained_after_lost_chains_keeps_its_rarity(self):
        f = self.bomb("RJTT")
        sg.update(self.b, self.ch, [f], self.now)
        self.assertEqual(sg.assess(f, self.b, self.ch, self.now, country=None)["tier"], "significant")
        lost = {}
        r = sg.update(self.b, lost, [f], self.now + timedelta(hours=2), counted_before=self.b["updated_at"])
        self.assertEqual(r["rechained"], 1)
        self.assertEqual(sg.assess(f, self.b, lost, self.now + timedelta(hours=2), country=None)["tier"],
                         "significant")
        # an older count of the same kind still counts: the NOTAM takes only its own count off
        self.b["counts"]["RJJJ|WD|hazard_to_people"]["50"] = 1
        self.assertEqual(sg.rarity(self.b, "RJJJ", "WD", "hazard_to_people", 110, own_day=110)[1][1], 1)

    def test_unchained_after_lost_chains_is_judged_without_itself(self):
        f = self.bomb("RJTT")
        sg.update(self.b, self.ch, [f], self.now)
        self.b["rechain_before"] = self.b["updated_at"]
        s = sg.assess(f, self.b, {}, self.now + timedelta(hours=2), country=None)
        self.assertEqual((s["rarity"], s["tier"]), ("rare", "significant"))


class LostCacheLane(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.saved = (common.DATA, nms.CACHE, nms.STORE, nms.OUT)
        common.DATA = t / "data"
        nms.CACHE, nms.STORE, nms.OUT = t / "cache", t / "cache" / "store.json.gz", t / "cache" / "out"

    def tearDown(self):
        common.DATA, nms.CACHE, nms.STORE, nms.OUT = self.saved
        self.tmp.cleanup()

    def test_the_bulk_after_a_lost_cache_counts_nothing_twice(self):
        a, b2 = feat("A0001/26"), feat("A0002/26", lu="2026-11-19T13:00:00.000Z")
        nms.update_significance([a], DAY0, env={}, mode="bulk")
        nms.chains_path().unlink()                                      # the Actions cache is lost
        out = nms.update_significance([b2], DAY0 + timedelta(hours=2), env={}, mode="delta")
        self.assertTrue(out["chains_rebuilt"])
        out = nms.update_significance([a, b2], DAY0 + timedelta(hours=26), env={}, mode="bulk")
        self.assertEqual((out["counts"]["rechained"], out["counts"]["new"]), (1, 0))
        b, _ = nms.load_significance()
        self.assertEqual(b["counts"]["UUWV|RT|unknown"], {"0": 2}, "A0001 and A0002 once each")
        self.assertNotIn("rechain_before", b, "the bulk chained every held NOTAM again")

    def test_chains_saved_apart_from_the_baseline_are_lost_chains(self):
        a = feat("A0001/26")
        nms.update_significance([a], DAY0, env={}, mode="bulk")
        old = (common.DATA / nms.SIG_BASELINE).read_text(encoding="utf-8")
        out = nms.update_significance([feat("A0002/26", lu="2026-11-19T13:00:00.000Z")], DAY0 + timedelta(hours=1),
                                      env={}, mode="delta")
        self.assertNotIn("chains_rebuilt", out)
        (common.DATA / nms.SIG_BASELINE).write_text(old, encoding="utf-8")   # the data push failed; the cache saved
        self.assertIsNone(nms.load_significance()[1])
        out = nms.update_significance([feat("A0002/26", lu="2026-11-19T13:00:00.000Z")], DAY0 + timedelta(hours=2),
                                      env={}, mode="delta")
        self.assertTrue(out["chains_rebuilt"])
        self.assertEqual(out["counts"]["new"], 1, "A0002 counted now, where the failed push lost its count")

    def test_rebuild_from_published_keeps_the_ranked_notams(self):
        ranked = feat("A0009/26", q="QWHLW", text="UXO DISPOSAL")
        ranked["properties"]["significance"] = {"tier": "notable"}
        files = {"index.json": {"subsets": [{"name": "launch-areas", "file": "launch-areas.json"}],
                                "significance": {"file": "significant.json", "status": "ok"}},
                 "launch-areas.json": {"type": "FeatureCollection", "features": []},
                 "significant.json": {"type": "FeatureCollection", "features": [ranked]}}
        store, _ = nms.from_published(lambda url: files[url[len(nms.PUBLISHED):]])
        self.assertEqual(list(store), [nms.key(ranked)])
        self.assertNotIn("significance", store[nms.key(ranked)]["properties"], "judged again, not copied")


if __name__ == "__main__":
    unittest.main()
