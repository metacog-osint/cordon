"""Offline tests for Cordon. Run as a plain script or with unittest. Fixtures copy the live formats seen on
31 Oct 2026, including the awkward cases (State's non-FIPS codes, "U.S." in sentences, consulates vs the embassy)."""
import json
import sys
import unittest
import unittest.mock
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
    {"msgYear": 2026, "msgNumber": 102, "navArea": "4", "issueDate": "291610Z OCT 2026", "authority": "Y",
     "text": "EASTERN CARIBBEAN SEA.\nMARTINIQUE.\n14 METER S/V SISYPHE TAKING ON WATER\nIN 14-51.78N 061-18.18W. VESSELS IN VICINITY\nREQUESTED TO KEEP A SHARP LOOKOUT."},
    {"msgYear": 2026, "msgNumber": 103, "navArea": "4", "issueDate": "291610Z OCT 2026", "authority": "Z",
     "text": "1. NAVAREA IV WARNINGS IN FORCE AS OF 031554Z MAY.\n   496/2024, 495/2024."},
    {"msgYear": 2026, "msgNumber": 104, "navArea": "12", "issueDate": "291610Z OCT 2026", "authority": "Z",
     "text": "CALIFORNIA.\nCANCEL NAVAREA XII 227/23 AND THIS MSG, OPERATIONS COMPLETED."},
    {"msgYear": 2026, "msgNumber": 105, "navArea": "A", "issueDate": "291610Z OCT 2026", "authority": "Z",
     "text": "EASTERN MEDITERRANEAN.\nGNSS INTERFERENCE REPORTED IN VICINITY 34-00.0S 033-00.0E."},
]}

# NGA's daily in-force list as plain text, in the form served on 12 Nov 2026 (msi.nga.mil/apology_objects/).
NGA_TEXT = """
NAVAREA IV IN FORCE AS OF 121615Z NOV.

To receive Broadcast Warning messages via email, go to
msi.nga.mil and click on the 'NAVIGATION WARNINGS' button.

120859Z NOV 26
NAVAREA IV 1090/26.
NORTH ATLANTIC.
1. HAZARDOUS OPERATIONS, SPACE DEBRIS
   0100Z TO 0200Z DAILY 14 THRU 22 NOV
   IN AREA BOUND BY
   54-35.00N 038-33.00W, 54-25.00N 037-11.00W,
   48-44.00N 039-10.00W, 48-52.00N 040-28.00W.
2. CANCEL THIS MSG 220300Z NOV 26.

120025Z NOV 26
NAVAREA IV 1089/26(24)
NORTH ATLANTIC.
TRINIDAD AND TOBAGO.
1. UNDERWATER OPERATIONS IN PROGRESS
   UNTIL 312200Z DEC BY M/V SEVEN NAVICA
   IN 10-05.05N 060-20.69W.

061615Z NOV 26
NAVAREA IV 1070/26.
1. NAVAREA IV WARNINGS IN FORCE AS OF 061615Z NOV.
   1069/26, 1068/26.

150429Z AUG 23
NAVAREA IV 163/23(15).
BEAUFORT SEA.
RACON AT PULLEN ISLAND LIGHT
69-46.60N 134-24.40W INOPERATIVE.
"""


def nga_site(api=None, text=NGA_TEXT):
    """A stand-in for fetch_or_none: the API body (or HTTP 503), and one text file for every area."""
    def fetch(url, timeout=40):
        if "apology_objects" in url:
            if text is None:
                return None, "HTTP 404"
            area = next(a for a, n in navarea.TEXT_FILES.items() if url.endswith(f"DailyMem{n}.txt"))
            return text.replace("NAVAREA IV", navarea.AREAS[area]).encode(), None
        return (json.dumps(api).encode(), None) if api else (None, "HTTP 503")
    return fetch


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

    def test_daily_text_list(self):
        w = {x["id"]: x for x in navarea.parse_text(NGA_TEXT, "4")}
        self.assertEqual(sorted(w), ["4-1089-2026", "4-1090-2026", "4-163-2023"], "the in-force index is not a warning")
        debris, ops, racon = w["4-1090-2026"], w["4-1089-2026"], w["4-163-2023"]
        self.assertEqual((debris["number"], debris["issued"], debris["category"], debris["geometry"]["type"]),
                         ("NAVAREA IV 1090/2026", "120859Z NOV 2026", "launch", "Polygon"))
        self.assertIn("CANCEL THIS MSG 220300Z", debris["text"], "a timed self-cancel is still a warning in force")
        self.assertEqual((ops["subregion"], ops["sea"], ops["place"]), ("24", "North Atlantic", "Trinidad And Tobago"))
        self.assertEqual(ops["geometry"], {"type": "Point", "coordinates": [-60.345, 10.084]})
        self.assertEqual((racon["subregion"], racon["category"]), ("15", "aids_to_navigation"))
        self.assertEqual(navarea.newest(w.values()), "2026-11-12T08:59:00Z")
        self.assertEqual(navarea.parse_text(NGA_TEXT, "P"), [], "another area's file holds none of these")

    def test_header_lines_are_not_the_headline(self):
        """Seas, a country, and a chart reference come first; the headline is the warning's own first sentence."""
        cases = {
            "BLACK SEA.\nROMANIA.\nDNC 10.\nMINES REPORTED IN AREA WITHIN FIVE MILES OF 45-07.10N 030-09.70E.":
                ("Black Sea", "Romania", "MINES REPORTED IN AREA WITHIN FIVE MILES OF 45-07.10N 030-09.70E."),
            "ARABIAN SEA.\nGULF OF OMAN.\nSTRAIT OF HORMUZ.\nU.A.E.\nDNC 10.\nGPS INTERFERENCE REPORTED.\nMORE.":
                ("Arabian Sea", "U.A.E", "GPS INTERFERENCE REPORTED."),
            "BALTIC SEA\nLITHUANIA\n1. HAZARDOUS OPERATIONS 1000Z TO 1600Z DAILY.\n2. CANCEL THIS MSG 121900Z NOV 26.":
                ("Baltic Sea", "Lithuania", "HAZARDOUS OPERATIONS 1000Z TO 1600Z DAILY."),
            "CARIBBEAN SEA.\nHONDURAS.\n1. LIGHTS UNLIT:\n   A. PUNTA IZOPO 15-50.90N 087-22.50W.\n   B. X 16-07.30N 086-00.00W.":
                ("Caribbean Sea", "Honduras", "LIGHTS UNLIT"),
            "NGA MARITIME DISSEMINATION ADVISORY\n1. NGA IS EXPERIENCING WEBSITE OUTAGES.\n2. CANCEL HYDROARC 325/26.":
                (None, None, "NGA MARITIME DISSEMINATION ADVISORY"),
            "LM BUOY 09-25.99N 079-49.78W\nMISSING.": (None, None, "LM BUOY 09-25.99N 079-49.78W MISSING."),
            "PERSIAN GULF.\nKUWAIT.": ("Persian Gulf", None, "KUWAIT."),
        }
        for text, want in cases.items():
            self.assertEqual(navarea.header(text), want, text)

    def test_categories_from_the_wording_seen_in_november_2026(self):
        cases = {
            "STRAIT OF HORMUZ.\nOMAN.\nM/V RITI SUFFERED A SECURITY INCIDENT,\nIS ON FIRE AND ANCHORED IN 26-24.07N 056-24.72E.": "security",
            "ARABIAN SEA.\nINDIA.\nF/V VARDANI MAULI SANK IN 18-25.90N 072-41.57E.": "wreck",
            "1. NORTH AMERICAN ICE SERVICE (NAIS)\n   ICEBERG BULLETIN 130001Z NOV.": "ice",
            "CANCELLED ELECTRONIC NAVIGATIONAL CHART (ENC)\nADVISORY.": "radio_service",
            "NAVAREA X AND JRCC AUSTRALIA PRIMARY EMAIL\nUNUSABLE UNTIL FURTHER NOTICE.": "radio_service",
            "PERSIAN GULF.\nKUWAIT.\nNAVIGATION PROHIBITED UNTIL FURTHER NOTICE IN AREA WITHIN 600 METERS OF X.": "restricted_area",
            "SCIENTIFIC MOORING, AT DEPTH SEVEN METERS, ESTABLISHED IN 66-19.59N 168-57.01W.": "hazard",
            "9 METER DEPTHS REPORTED IN BOROUGE CHANNEL 24-09.00N 052-45.20E.": "shoal",
            "VESSELS REPORT TO MRCC BY E-MAIL: X@Y.Z. REEF UNCHARTED.": "hazard",
        }
        for text, want in cases.items():
            self.assertEqual(navarea.category(text), want, text)
        self.assertIn("security", feed.NOTABLE)

    def test_staleness_is_judged_by_the_newest_warning(self):
        self.assertFalse(navarea.is_stale("2026-11-06T00:00:00Z", "2026-11-12T00:00:00Z"))
        self.assertTrue(navarea.is_stale("2024-05-10T15:15:00Z", "2026-10-31T21:22:31Z"))
        self.assertTrue(navarea.is_stale(None, "2026-11-12T00:00:00Z"))

    def test_collect_takes_a_fresh_api_answer(self):
        got, err, src = navarea.collect([], "2026-10-31T00:00:00Z", nga_site(api=NGA, text=None))
        self.assertEqual((len(got), err, src), (3, None, navarea.SOURCE_URL))

    def test_collect_reads_the_daily_lists_when_the_api_is_down_or_frozen(self):
        frozen = {"broadcast-warn": [{**NGA["broadcast-warn"][1], "issueDate": "101515Z MAY 2024"}]}
        for api in (None, frozen):  # HTTP 503 since 31 Oct 2026; before that, a database frozen at 10 May 2024
            got, err, src = navarea.collect([{"id": "old"}], "2026-11-12T17:00:00Z", nga_site(api=api))
            self.assertEqual((len(got), err), (15, None), "three warnings from each of five areas")
            self.assertIn("apology_objects", src)
            self.assertEqual(len({w["id"] for w in got}), 15)

    def test_collect_never_calls_a_stale_or_missing_list_good(self):
        frozen = {"broadcast-warn": [{**NGA["broadcast-warn"][1], "issueDate": "101515Z MAY 2024"}]}
        old = [{"id": "old"}]
        got, err, src = navarea.collect(old, "2026-11-12T17:00:00Z", nga_site(api=frozen, text=None))
        self.assertEqual((got, src), (old, None), "the previous warnings are kept")
        self.assertEqual(err, "API: stale: newest warning 2024-05-10; daily lists: NAVAREA IV: HTTP 404")
        got, err, _ = navarea.collect(old, "2027-03-01T00:00:00Z", nga_site())
        self.assertEqual((got, err), (old, "API: HTTP 503; daily lists: stale: newest warning 2026-11-12"))


class Embassy(unittest.TestCase):
    def test_rss(self):
        a = embassy.parse_rss(RSS, "SA")
        self.assertEqual([x["type"] for x in a], ["security", "demonstration"])
        self.assertEqual(a[1]["published_at"], "2026-10-22T06:30:00Z")
        self.assertEqual(embassy.feed_url("GB"), "https://uk.usembassy.gov/category/alert/feed/")
        self.assertNotIn("IR", embassy.posts({"IR": {"iso": "IR", "level": 4}}))

    GN_RSS = """<?xml version="1.0"?><rss><channel>
        <item><title>Alerts Archives - U.S. Embassy in Ukraine</title>
        <link>https://news.google.com/rss/articles/CBMiArchive?oc=5</link>
        <pubDate>Fri, 03 Feb 2017 08:00:00 GMT</pubDate></item>
        <item><title>Security Alert: U.S. Embassy Kyiv - U.S. Embassy in Ukraine</title>
        <link>https://news.google.com/rss/articles/CBMiKyiv1?oc=5</link>
        <pubDate>Sat, 31 Oct 2026 10:00:00 GMT</pubDate></item>
        <item><title>Demonstration Alert &#8211; U.S. Embassy Kyiv (November 4, 2026) - U.S. Embassy in Ukraine</title>
        <link>https://news.google.com/rss/articles/CBMiKyiv2?oc=5</link>
        <pubDate>Wed, 04 Nov 2026 09:00:00 GMT</pubDate></item>
        <item><title>Security Alert: U.S. Embassy Kyiv - U.S. Embassy in Ukraine</title>
        <link>https://news.google.com/rss/articles/CBMiKyiv1dup?oc=5</link>
        <pubDate>Sat, 31 Oct 2026 10:05:00 GMT</pubDate></item>
        <item><title>Health Alert: Measles - U.S. Embassy in Ukraine</title>
        <link>https://news.google.com/rss/articles/CBMiOld?oc=5</link>
        <pubDate>Mon, 15 Jan 2024 09:00:00 GMT</pubDate></item>
        </channel></rss>"""

    @staticmethod
    def _fetch(direct=b"<html><body>Technical Difficulties</body></html>", search=None):
        def fake(url, timeout=25):
            if url.endswith("/category/alert/feed/"):
                return direct, None
            if "news.google.com/rss/search" in url:
                return (search, None) if search is not None else (None, "HTTP 503")
            return None, "HTTP 404"
        return fake

    def test_direct_feed_titles_are_left_whole(self):
        rss = """<rss><channel><item><title>Demonstration Alert - U.S. Embassy Mexico City</title>
        <link>https://mx.usembassy.gov/demonstration-alert/</link><pubDate>Sat, 31 Oct 2026 10:00:00 GMT</pubDate>
        </item></channel></rss>"""
        a = embassy.parse_rss(rss, "MX")[0]
        self.assertEqual((a["title"], a["type"]), ("Demonstration Alert - U.S. Embassy Mexico City", "demonstration"))

    def test_html_error_page_falls_back_to_recent_search_alerts(self):
        with unittest.mock.patch.object(embassy, "posts", lambda adv: ["UA"]):
            out, errs, via = embassy.collect({}, when="2026-11-08T18:00:00Z",
                                             fetch=self._fetch(search=self.GN_RSS.encode("utf-8")))
        self.assertEqual((errs, via), ({}, {"UA": "google-news"}))
        got = [(a["title"], a["type"], a["published_at"][:10]) for a in out["UA"]]
        self.assertEqual(got, [
            ("Demonstration Alert – U.S. Embassy Kyiv (November 4, 2026)", "demonstration", "2026-11-04"),
            ("Security Alert: U.S. Embassy Kyiv", "security", "2026-10-31"),
        ], "newest first; archive pages, old alerts and duplicates dropped; the site name trimmed")
        self.assertEqual(out["UA"][0]["post_url"], "https://ua.usembassy.gov/category/alert/")

    def test_a_search_with_nothing_recent_keeps_previous_alerts(self):
        stale = b"<rss><channel><item><title>Alerts Archives - U.S. Embassy</title><link>https://news.google.com/x</link>" \
                b"<pubDate>Fri, 03 Feb 2017 08:00:00 GMT</pubDate></item></channel></rss>"
        with unittest.mock.patch.object(embassy, "posts", lambda adv: ["UA", "SA"]):
            out, errs, via = embassy.collect({}, previous={"UA": [{"title": "kept UA"}], "SA": [{"title": "kept SA"}]},
                                             when="2026-11-08T18:00:00Z", fetch=self._fetch(search=stale))
        self.assertEqual((out["UA"], out["SA"]), ([{"title": "kept UA"}], [{"title": "kept SA"}]))
        self.assertIn("no alert in the last 30 days", errs["UA"])
        self.assertEqual(via, {})
        with unittest.mock.patch.object(embassy, "posts", lambda adv: ["SA"]):
            out, errs, _ = embassy.collect({}, previous={"SA": [{"title": "kept"}]}, fetch=self._fetch())
        self.assertEqual(out["SA"], [{"title": "kept"}], "when both fail, previous alerts are kept")
        self.assertIn("HTTP 503", errs["SA"])

    def test_search_alerts_cite_the_posts_own_page(self):
        found = embassy.search_results(embassy.parse_rss(self.GN_RSS, "UA", search=True), "UA", "2026-11-08T18:00:00Z")
        fc = feed.build({"advisories": [], "fetched_at": "2026-11-08T18:00:00Z"},
                        {"posts": {"UA": found}, "fetched_at": "2026-11-08T18:00:00Z"},
                        {"bulletins": [], "fetched_at": "2026-11-08T18:00:00Z"},
                        {"warnings": [], "fetched_at": "2026-11-08T18:00:00Z"},
                        datetime(2026, 11, 8, 18, tzinfo=timezone.utc))
        alerts = [f["properties"] for f in fc["features"] if f["properties"]["id"].startswith("cordon:alert:UA:")]
        self.assertEqual(len(alerts), 2)
        for p in alerts:
            self.assertEqual(p["sources"][0]["url"], "https://ua.usembassy.gov/category/alert/")
            self.assertIn("Google News", p["sources"][0]["descriptor"])
            self.assertTrue(p["link"].startswith("https://news.google.com/"))
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([p for p in contract.check(f, regs) if p[1] == "error"], [], f["properties"]["id"])


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
        self.assertEqual(fc["health"]["nga-navwarnings"], {"state": "fresh", "newest_item": "2026-10-29T16:10:00Z"})

    def test_a_frozen_warning_list_is_stale_and_withheld(self):
        """What happened from 31 Oct 2026: one good fetch, of a list whose newest warning was from May 2024."""
        frozen = {"broadcast-warn": [{**w, "issueDate": "101515Z MAY 2024"} for w in NGA["broadcast-warn"]]}
        nav = {"warnings": navarea.parse(frozen), "fetched_at": "2026-10-31T21:22:31Z"}
        ok = {"last_ok": "2026-10-31T21:22:31Z", "last_error": None, "failures": 0,
              "checked_at": "2026-10-31T21:22:31Z", "detail": "3 warnings in force"}
        now = datetime(2026, 10, 31, 22, tzinfo=timezone.utc)
        fc = feed.build({}, {}, {}, nav, now, {"nga-navwarnings": ok, "easa-czib": {**ok, "detail": "16 active"}})
        nga = fc["health"]["nga-navwarnings"]
        self.assertEqual((nga["state"], nga["newest_item"], nga["withheld"]), ("stale", "2024-05-10T15:15:00Z", 3))
        self.assertEqual(fc["features"], [], "a frozen list reads as no data, never as warnings in force")
        self.assertEqual(fc["health"]["easa-czib"]["state"], "fresh")

    def test_health_states(self):
        now = datetime(2026, 11, 12, 17, tzinfo=timezone.utc)
        nav = {"warnings": navarea.parse_text(NGA_TEXT, "4")}
        h = {"nga-navwarnings": {"last_ok": "2026-11-12T10:00:00Z", "failures": 3, "detail": "HTTP 503"},
             "easa-czib": {"last_ok": "2026-11-09T10:00:00Z", "failures": 70, "detail": "HTTP 500"},
             "us-embassy-alerts": {"last_ok": None, "failures": 1}}
        got = {k: v["state"] for k, v in feed.source_health(h, nav, now).items()}
        self.assertEqual(got, {"nga-navwarnings": "failing", "easa-czib": "stale", "us-embassy-alerts": "never"})
        fc = feed.build({}, {}, {}, nav, now, h)
        self.assertEqual(len(fc["features"]), 2, "failing for a few hours: the warnings still stand")


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


class Review(unittest.TestCase):
    def test_posture_changes_become_reviews(self):
        from cordon import review
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        changes = [
            {"lane": "state", "kind": "posture", "at": "2026-11-01T15:25:00Z", "key": "LB", "iso": "LB", "name": "Lebanon",
             "from": "normal", "to": "ordered_departure", "sentence": "The Department ordered the departure of family members.",
             "link": LINK},
            {"lane": "state", "kind": "level", "at": "2026-11-01T15:25:00Z", "key": "LB", "name": "Lebanon", "from": 3, "to": 4},
            {"lane": "state", "kind": "posture", "at": "2026-09-01T00:00:00Z", "key": "ET", "name": "Ethiopia",
             "from": "normal", "to": "authorized_departure"},
        ]
        r = review.pending(changes, now)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["title"], "Review: Lebanon embassy status normal operations to ordered departure (2026-11-01, LB)")
        self.assertIn("> The Department ordered the departure of family members.", r[0]["body"])
        self.assertIn(LINK, r[0]["body"])


if __name__ == "__main__":
    unittest.main()
