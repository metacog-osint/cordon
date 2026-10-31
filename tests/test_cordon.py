"""Offline tests for Cordon. Run as a plain script or with unittest. Fixtures copy the live formats seen on
31 Oct 2026, including the awkward cases (State's non-FIPS codes, "U.S." in sentences, consulates vs the embassy)."""
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cordon import easa, embassy, feed, navarea, state  # noqa: E402
from tic_doctrine import contract, registers  # noqa: E402

LINK = "https://travel.state.gov/content/travel/en/traveladvisories/x.html"


def adv(title, cat, text):
    return {"Title": title, "Category": cat, "Summary": text, "Link": LINK, "Published": "2026-10-22T20:00:00-04:00",
            "Updated": "2026-10-22T20:00:00-04:00", "id": LINK}


STATE = [
    adv("Saudi Arabia - Level 3: Reconsider Travel", ["SA"],
        "<p>Reconsider travel.</p><p>On October 23, 2026, the Department of State ordered non-emergency U.S. government "
        "employees and U.S. government employee family members to leave Saudi Arabia due to safety risks.</p>"),
    adv("Russia - Level 4: Do Not Travel", ["RS"],
        "<p>Do not travel. The U.S. consulates in Russia have suspended operations, including consular services.</p>"),
    adv("Belarus - Level 4: Do Not Travel", ["BO"],
        "<p>Do not travel. It also suspended operations at U.S. Embassy Minsk on February 28, 2022.</p>"),
    adv("Switzerland\xa0 - Level 1: Exercise Normal Precautions", ["SR"], "<p>Exercise normal precautions.</p>"),
    adv("Gaza - Level 4: Do Not Travel", ["IS"], "<p>Do not travel to Gaza.</p>"),
    adv("Israel - Level 3: Reconsider Travel", ["IS"], "<p>Reconsider travel.</p>"),
    adv("French Saint Martin - Level 1: Exercise Normal Precautions", ["MF"], "<p>Exercise normal precautions.</p>"),
    adv("Germany - Level 2: Exercise Increased Caution", "['GM']", "<p>Exercise increased caution.</p>"),
    adv("Mexico Travel Advisory - Level 2: Exercise Increased Caution", ["MX"],
        "<p>The Department authorized the voluntary departure of family members.</p>"),
]

EASA_CSV = ('Subject,"CZIB number","Issue date","Valid until","Valid until description",Status,Revision,'
            '"Affected Airspace","Affected Country",Applicability,"Applicability description",Description,'
            'Recommendation(s),"Referenced publication(s)"\n'
            '"Airspace of the Persian Gulf and Gulf of Oman",CZIB-2026-07R3,14/07/2026,16/11/2026,"x",Active,"30/09/2026 rev",'
            '"FIRs","Bahrain, Kuwait, Qatar, Oman, United Arab Emirates",a,b,c,"Avoid the waters",d\n'
            '"Airspace of Iran",CZIB-2026-04-R2,08/07/2026,16/11/2026,"x",Active,"30/09/2026 rev","FIR Tehran","Iran",a,b,c,"Do not operate",d\n'
            '"Airspace of North Korea",CZIB-2017-06R2,01/01/2017,,"x",Withdrawn,"","FIR","Democratic People\'s Republic of Korea ",a,b,c,"",d\n'
            '"Airspace of Russia",2025-01 R3,01/01/2025,31/01/2027,"x",Active,"","all","Russia",a,b,c,"Do not operate",d\n'
            '"Airspace of Sudan",CZIB-2023-01R8,01/01/2023,31/01/2027,"x",Active,"","all","Sudan",a,b,c,"Do not operate",d\n')

NGA = {"broadcast-warn": [
    {"msgYear": 2026, "msgNumber": 101, "navArea": "12", "issueDate": "081653Z MAY 2026", "authority": "X",
     "text": "NORTH PACIFIC.\n1. HAZARDOUS OPERATIONS, ROCKET LAUNCHING\n   IN AREA BOUND BY\n   30-00.0N 150-00.0W, 31-00.0N 150-00.0W,\n   31-00.0N 151-00.0W, 30-00.0N 151-00.0W."},
    {"msgYear": 2026, "msgNumber": 102, "navArea": "4", "issueDate": "011610Z OCT 2026", "authority": "Y",
     "text": "EASTERN CARIBBEAN SEA.\nMARTINIQUE.\n14 METER S/V SISYPHE TAKING ON WATER\nIN 14-51.78N 061-18.18W. VESSELS IN VICINITY\nREQUESTED TO KEEP A SHARP LOOKOUT."},
    {"msgYear": 2026, "msgNumber": 103, "navArea": "4", "issueDate": "011610Z OCT 2026", "authority": "Z",
     "text": "1. NAVAREA IV WARNINGS IN FORCE AS OF 031554Z MAY.\n   496/2024, 495/2024."},
    {"msgYear": 2026, "msgNumber": 104, "navArea": "12", "issueDate": "011610Z OCT 2026", "authority": "Z",
     "text": "CALIFORNIA.\nCANCEL NAVAREA XII 227/23 AND THIS MSG, OPERATIONS COMPLETED."},
    {"msgYear": 2026, "msgNumber": 105, "navArea": "A", "issueDate": "011610Z OCT 2026", "authority": "Z",
     "text": "EASTERN MEDITERRANEAN.\nGNSS INTERFERENCE REPORTED IN VICINITY 34-00.0S 033-00.0E."},
]}

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Security Alert: U.S. Embassy Riyadh, October 23, 2026</title><link>https://sa.usembassy.gov/security-alert-1/</link>
<pubDate>Fri, 23 Oct 2026 14:00:00 +0000</pubDate></item>
<item><title><![CDATA[Demonstration Alert - Jeddah]]></title><link>https://sa.usembassy.gov/demo-alert/</link>
<pubDate>Thu, 22 Oct 2026 09:30:00 +0300</pubDate></item>
<item><title>No link</title><link>javascript:x</link></item>
</channel></rss>"""


class State(unittest.TestCase):
    def setUp(self):
        self.recs = state.parse(STATE)

    def test_codes_follow_the_title_where_state_is_not_fips(self):
        r = self.recs
        self.assertEqual((r["CH"]["name"], r["CH"]["level"]), ("Switzerland", 1))      # State's "SR"
        self.assertEqual((r["MF"]["iso"], r["DE"]["iso"]), ("MF", "DE"))               # MF is ISO here; GM is FIPS
        self.assertEqual((r["PS-GZ"]["iso"], r["PS-GZ"]["level"], r["IL"]["level"]), ("PS", 4, 3))
        self.assertEqual(r["RU"]["iso"], "RU")                                        # FIPS RS -> ISO RU

    def test_departure_status(self):
        r = self.recs
        self.assertEqual(r["SA"]["posture"]["state"], "ordered_departure")
        self.assertIn("ordered non-emergency US government employees", r["SA"]["posture"]["sentence"])
        self.assertEqual(r["RU"]["posture"]["state"], "normal", "consulates suspending is not the embassy")
        self.assertEqual(r["BY"]["posture"]["state"], "suspended_operations")
        self.assertEqual(r["MX"]["posture"]["state"], "authorized_departure")

    def test_diff_flags_posture_changes_for_review(self):
        old = state.parse(STATE)
        new = state.parse([adv("Saudi Arabia - Level 4: Do Not Travel", ["SA"], "<p>Do not travel.</p>")] + STATE[1:])
        ch = {(c["key"], c["kind"]): c for c in state.diff(old, new, "2026-11-01T00:00:00Z")}
        self.assertEqual((ch[("SA", "level")]["from"], ch[("SA", "level")]["to"]), (3, 4))
        self.assertTrue(ch[("SA", "posture")]["needs_review"])
        self.assertEqual(state.diff({}, new, "t"), [], "the first run records no changes")

    def test_a_broken_response_keeps_the_old_snapshot(self):
        old = {"SA": self.recs["SA"]}
        snap, changes, err = state.collect(old, fetch=lambda u, t=40: (json.dumps(STATE[:2]).encode(), None))
        self.assertEqual((snap, changes), (old, []))
        self.assertIn("advisories parsed", err)


class Easa(unittest.TestCase):
    def test_parse_and_countries(self):
        b = {x["id"]: x for x in easa.parse(EASA_CSV)}
        self.assertEqual(b["CZIB-2026-07"]["countries"], ["BH", "KW", "QA", "OM", "AE"])
        self.assertEqual((b["CZIB-2026-04"]["valid_until"], b["CZIB-2026-04"]["status"]), ("2026-11-16", "active"))
        self.assertEqual(b["CZIB-2017-06"]["countries"], ["KP"])
        self.assertEqual(b["CZIB-2025-01"]["number"], "2025-01 R3")

    def test_diff_sees_a_renewal(self):
        old = easa.parse(EASA_CSV)
        new = easa.parse(EASA_CSV.replace("CZIB-2026-04-R2,08/07/2026,16/11/2026", "CZIB-2026-04-R3,08/07/2026,16/12/2026"))
        ch = easa.diff(old, new, "t")
        self.assertEqual([(c["id"], c["kind"]) for c in ch], [("CZIB-2026-04", "revised")])


class Navarea(unittest.TestCase):
    def setUp(self):
        self.w = {x["id"]: x for x in navarea.parse(NGA)}

    def test_index_lists_and_self_cancels_are_skipped(self):
        self.assertEqual(sorted(self.w), ["12-101-2026", "4-102-2026", "A-105-2026"])

    def test_categories_places_and_geometry(self):
        launch, sar, gnss = self.w["12-101-2026"], self.w["4-102-2026"], self.w["A-105-2026"]
        self.assertEqual((launch["category"], launch["geometry"]["type"]), ("launch", "Polygon"))
        self.assertEqual(launch["geometry"]["coordinates"][0][0], [-150.0, 30.0])
        self.assertEqual((sar["category"], sar["place"], sar["sea"]), ("search_and_rescue", "Martinique", "Eastern Caribbean Sea"))
        self.assertEqual(sar["geometry"], {"type": "Point", "coordinates": [-61.303, 14.863]})
        self.assertEqual((gnss["category"], gnss["geometry"]["coordinates"]), ("gnss", [33.0, -34.0]))

    def test_issue_time(self):
        self.assertEqual(feed.nga_time("081653Z MAY 2026"), "2026-05-08T16:53:00Z")
        self.assertIsNone(feed.nga_time("garbage"))


class Embassy(unittest.TestCase):
    def test_rss(self):
        a = embassy.parse_rss(RSS, "SA")
        self.assertEqual([x["type"] for x in a], ["security", "demonstration"])
        self.assertEqual(a[1]["published_at"], "2026-10-22T06:30:00Z")
        self.assertEqual(embassy.feed_url("GB"), "https://uk.usembassy.gov/category/alert/feed/")
        self.assertNotIn("IR", embassy.posts({"IR": {"iso": "IR", "level": 4}}))


class Feed(unittest.TestCase):
    def test_every_item_passes_the_kit_linter(self):
        recs = state.parse(STATE)
        fc = feed.build({"advisories": recs, "fetched_at": "2026-10-31T21:00:00Z"},
                        {"posts": {"SA": embassy.parse_rss(RSS, "SA")}, "fetched_at": "2026-10-31T21:00:00Z"},
                        {"bulletins": easa.parse(EASA_CSV), "fetched_at": "2026-10-31T21:00:00Z"},
                        {"warnings": navarea.parse(NGA), "fetched_at": "2026-10-31T21:00:00Z"},
                        datetime(2026, 10, 31, 21, tzinfo=timezone.utc))
        self.assertEqual(fc["dropped"], [])
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([p for p in contract.check(f, regs) if p[1] == "error"], [], f["properties"]["id"])
        ids = {f["properties"]["id"]: f for f in fc["features"]}
        self.assertEqual(ids["cordon:posture:SA"]["properties"]["response_stage"], "state_post_posture:ordered_departure")
        self.assertEqual(ids["cordon:advisory:PS-GZ"]["geometry"]["coordinates"], [34.38, 31.42])
        self.assertIn("cordon:czib:CZIB-2026-07", ids)
        self.assertNotIn("cordon:czib:CZIB-2017-06", ids, "withdrawn bulletins stay off the feed")
        self.assertEqual(sum(1 for i in ids if i.startswith("cordon:alert:SA:")), 2)


class Events(unittest.TestCase):
    def test_bulletin_expiries_and_recent_changes(self):
        from cordon import events
        now = datetime(2026, 10, 31, 21, tzinfo=timezone.utc)
        changes = [
            {"lane": "state", "kind": "posture", "at": "2026-10-23T14:00:00Z", "key": "SA", "iso": "SA",
             "name": "Saudi Arabia", "from": "normal", "to": "ordered_departure", "link": LINK},
            {"lane": "state", "kind": "level", "at": "2026-09-01T00:00:00Z", "key": "LB", "iso": "LB",
             "name": "Lebanon", "from": 3, "to": 4, "link": LINK},   # older than 30 days
            {"lane": "state", "kind": "text", "at": "2026-10-30T00:00:00Z", "key": "MX", "iso": "MX", "name": "Mexico"},
        ]
        ev = events.build(easa.parse(EASA_CSV), changes, now)["events"]
        ids = [e["id"] for e in ev]
        self.assertIn("2026-11-16-easa-czib-2026-04", ids)
        self.assertNotIn("2027-01-31-easa-czib-2017-06", ids, "withdrawn bulletins have no expiry to watch")
        gulf = next(e for e in ev if e["ref"] == "CZIB-2026-07")
        self.assertEqual((gulf["date"], gulf["countries"][:2]), ("2026-11-16", ["BH", "KW"]))
        sa = next(e for e in ev if e["kind"] == "advisory_change")
        self.assertEqual(sa["id"], "2026-10-23-state-sa-posture")
        self.assertIn("normal operations to ordered departure", sa["title"])
        self.assertEqual(sum(e["kind"] == "advisory_change" for e in ev), 1, "old and text-only changes stay out")
        self.assertEqual(ev, sorted(ev, key=lambda e: (e["date"], e["id"])))


if __name__ == "__main__":
    unittest.main()
