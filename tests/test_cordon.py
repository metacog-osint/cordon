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
from cordon import easa, embassy, faa, fcdo, feed, navarea, state, tfr  # noqa: E402
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


def nga_site(api=None, text=NGA_TEXT, down=()):
    """A stand-in for fetch_or_none: the API body (or HTTP 503), and one text file for every area (HTTP 404 for the
    file names in `down`)."""
    def fetch(url, timeout=40):
        if "apology_objects" in url:
            if text is None or any(url.endswith(f"DailyMem{n}.txt") for n in down):
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
        self.assertTrue({"security", "ice"} <= feed.NOTABLE, "both are on the feed")

    def test_each_bounded_area_is_its_own_polygon(self):
        two = ("NORTH ATLANTIC.\nFLORIDA.\n1. HAZARDOUS OPERATIONS, ROCKET LAUNCHING\n   IN AREAS BOUND BY:\n"
               "   A. 28-00.00N 080-00.00W, 29-00.00N 080-00.00W,\n      29-00.00N 079-00.00W, 28-00.00N 079-00.00W.\n"
               "   B. 43-00.00N 059-00.00W, 44-00.00N 059-00.00W,\n      44-00.00N 058-00.00W.\n"
               "2. CANCEL THIS MSG 191824Z NOV 26.\n3. REPORTS TO 10-00.00N 020-00.00W.")
        g = navarea.geometry(two, navarea.positions(two))
        self.assertEqual(g["type"], "MultiPolygon")
        self.assertEqual([len(p[0]) for p in g["coordinates"]], [5, 4], "closed rings; the later position is no corner")
        self.assertEqual(g["coordinates"][1][0][0], [-59.0, 43.0])
        one = "1. SPACE DEBRIS IN AREA BOUND BY\n   54-35.00N 038-33.00W, 54-25.00N 037-11.00W,\n   48-44.00N 039-10.00W."
        self.assertEqual(navarea.geometry(one, navarea.positions(one))["type"], "Polygon")
        paras = ("1. FIRING IN AREA BOUND BY\n   10-00.0N 020-00.0W, 11-00.0N 020-00.0W, 11-00.0N 021-00.0W.\n"
                 "2. FIRING IN AREA BOUND BY\n   30-00.0N 040-00.0W, 31-00.0N 040-00.0W, 31-00.0N 041-00.0W.")
        self.assertEqual(len(navarea.geometry(paras, navarea.positions(paras))["coordinates"]), 2)

    def test_tracklines_are_lines_and_radii_are_circles(self):
        """Wording seen in NGA's lists on 13 Nov 2026 (HYDROLANT 2088/24, NAVAREA IV 1091/26, HYDROLANT 237/26)."""
        one = ("CABLE OPERATIONS IN PROGRESS UNTIL FURTHER NOTICE\nALONG TRACKLINE JOINING\n"
               "10-40.23N 063-15.13W, 10-42.82N 063-15.05W.\nWIDE BERTH REQUESTED.")
        self.assertEqual(navarea.geometry(one, navarea.positions(one)),
                         {"type": "LineString", "coordinates": [[-63.252, 10.671], [-63.251, 10.714]]})
        lettered = ("1. DUE TO THE PRESENCE OF MINES, USE THE FOLLOWING TRACKS:\n"
                    "   A. PORT OF MANGALIA ALONG TRACKLINE JOINING\n      43-47.59N 028-50.86E, 43-47.50N 028-37.61E.\n"
                    "   B. PORT OF NAVODARI ALONG TRAKLINE JOINING\n      43-47.59N 028-50.86E, 44-11.33N 028-50.86E,\n"
                    "      44-15.52N 028-45.04E.\n2. REPORT MINES TO MRCC 44-10.00N 028-39.00E.")
        g = navarea.geometry(lettered, navarea.positions(lettered))
        self.assertEqual((g["type"], [len(x) for x in g["coordinates"]]), ("MultiLineString", [2, 3]),
                         "NGA's own misspelling counts; a position in a later paragraph is no vertex")
        corridor = ("1. SURVEY OPERATIONS BY M/V FUGRO DISCOVERY WITHIN 500 METERS OF\n   TRACKLINE JOINING "
                    "29-28.60N 081-01.60W,\n   29-27.60N 080-35.73W.\n2. CANCEL THIS MSG 270001Z NOV 26.")
        rec = navarea._record("4", 1091, 2026, None, "121000Z NOV 2026", "", corridor)
        self.assertEqual((rec["geometry"]["type"], rec["corridor_half_width_m"]), ("LineString", [500.0]))
        self.assertNotIn("radius_m", rec, "a corridor is not a circle")
        gunnery = "1. GUNNERY EXERCISES 171800Z TO 172200Z NOV\n   IN AREA WITHIN 12 MILES OF 14-35.00N 061-47.30W."
        rec = navarea._record("4", 1096, 2026, None, "121000Z NOV 2026", "", gunnery)
        ring = rec["geometry"]["coordinates"][0]
        self.assertEqual((rec["geometry"]["type"], len(ring), ring[0], rec["radius_m"]),
                         ("Polygon", navarea.CIRCLE_SIDES + 1, ring[-1], [22224.0]), "a closed ring; nautical miles")
        self.assertAlmostEqual(ring[0][1] - 14.583, 0.2, places=2, msg="12 nautical miles is 0.2 degree of latitude")
        mixed = ("1. MISSILE OPERATIONS IN AREAS:\n   A. BOUND BY\n      35-36.00N 024-07.00E, 36-18.00N 024-07.00E,\n"
                 "      36-18.00N 025-59.00E, 35-31.00N 024-11.00E.\n   B. WITHIN ONE MILE OF 35-32.00N 024-13.00E.\n"
                 "   C. WITHIN ONE MILE OF 35-36.33N 024-10.00E.\n2. CANCEL THIS MSG 010001Z JAN 27.")
        g = navarea.geometry(mixed, navarea.positions(mixed))
        self.assertEqual((g["type"], len(g["coordinates"])), ("MultiPolygon", 3), "the area and both circles")
        guam = "1. HAZARDOUS OPERATIONS IN AREAS WITHIN\n   THREE MILE OF:\n   A. 13-27.00N 145-08.00E.\n   B. 13-42.00N 144-36.00E."
        self.assertEqual(len(navarea.geometry(guam, navarea.positions(guam))["coordinates"]), 2)
        both = ("2. ROUTES:\n   A. ROUTE WITHIN THREE MILES OF\n      TRACKLINE JOINING\n      45-05.00N 030-03.00E, "
                "45-14.00N 030-01.00E.\n3. ANCHORAGE IN AREA BOUND BY\n   45-00N 030-00E, 45-10N 030-00E, 45-10N 030-10E.")
        g = navarea.geometry(both, navarea.positions(both))
        self.assertEqual([x["type"] for x in g["geometries"]], ["Polygon", "LineString"])
        self.assertEqual(navarea.distance_m("1.5", "NM"), 2778.0)
        dateline = "IN AREA BOUND BY\n   31-25N 179-58W, 31-25N 178-00E,\n   23-24N 178-00E, 23-24N 179-58W."
        ring = navarea.geometry(dateline, navarea.positions(dateline))["coordinates"][0]
        self.assertEqual([p[0] for p in ring], [-179.967, -182.0, -182.0, -179.967, -179.967],
                         "two degrees wide across 180, not 358 degrees the other way")
        self.assertIsNone(navarea.distance_m("SEVERAL", "MILES"))

    def test_long_text_is_kept_or_the_cut_is_marked(self):
        body = "1. SURVEY OPERATIONS IN 10-00.0N 020-00.0W.\n" + "   B. MORE DETAIL.\n" * 200
        rec = navarea._record("4", 1, 2026, None, "121000Z NOV 2026", "", body)
        self.assertEqual(rec["text"], body.strip(), "4,000 characters are kept whole")
        long_ = body * 3
        rec = navarea._record("4", 1, 2026, None, "121000Z NOV 2026", "", long_)
        self.assertTrue(rec["text"].endswith(f"[Cut by Cordon: {len(long_.strip()) - navarea.TEXT_MAX} more characters. "
                                             "Full text: NGA, msi.nga.mil/NavWarnings]"))

    def test_cancel_time(self):
        self.assertEqual(navarea.cancel_time("1. X.\n2. CANCEL THIS MSG 220300Z NOV 26."), "2026-11-22T03:00:00Z")
        self.assertEqual(navarea.cancel_time("1. X.\n2. CANCEL THIS\n   MSG 010001Z DEC 26."), "2026-12-01T00:01:00Z")
        self.assertIsNone(navarea.cancel_time("2. CANCEL HYDROPAC 3151/26."))
        w = navarea.parse_text(NGA_TEXT, "4")[0]
        self.assertEqual(w["cancel_at"], "2026-11-22T03:00:00Z")
        self.assertTrue(navarea.in_force(w, "2026-11-22T02:59:00Z"))
        self.assertFalse(navarea.in_force(w, "2026-11-22T03:00:00Z"))

    def test_staleness_is_judged_by_the_newest_warning(self):
        self.assertFalse(navarea.is_stale("2026-11-06T00:00:00Z", "2026-11-12T00:00:00Z"))
        self.assertTrue(navarea.is_stale("2024-05-10T15:15:00Z", "2026-10-31T21:22:31Z"))
        self.assertTrue(navarea.is_stale(None, "2026-11-12T00:00:00Z"))

    def test_collect_takes_a_fresh_api_answer(self):
        got, err, src, held = navarea.collect([], "2026-10-31T00:00:00Z", nga_site(api=NGA, text=None))
        self.assertEqual((len(got), err, src, held), (3, None, navarea.SOURCE_URL, {}))

    def test_collect_reads_the_daily_lists_when_the_api_is_down_or_frozen(self):
        frozen = {"broadcast-warn": [{**NGA["broadcast-warn"][1], "issueDate": "101515Z MAY 2024"}]}
        for api in (None, frozen):  # HTTP 503 since 31 Oct 2026; before that, a database frozen at 10 May 2024
            got, err, src, _ = navarea.collect([{"id": "old"}], "2026-11-12T17:00:00Z", nga_site(api=api))
            self.assertEqual((len(got), err), (15, None), "three warnings from each of five areas")
            self.assertIn("apology_objects", src)
            self.assertEqual(len({w["id"] for w in got}), 15)

    def test_collect_never_calls_a_stale_or_missing_list_good(self):
        frozen = {"broadcast-warn": [{**NGA["broadcast-warn"][1], "issueDate": "101515Z MAY 2024"}]}
        old = [{"id": "old"}]
        got, err, src, _ = navarea.collect(old, "2026-11-12T17:00:00Z", nga_site(api=frozen, text=None))
        self.assertEqual((got, src), (old, None), "the previous warnings are kept")
        self.assertEqual(err, "API: stale: newest warning 2024-05-10; daily lists: NAVAREA IV: HTTP 404")
        got, err, _, _ = navarea.collect(old, "2027-03-01T00:00:00Z", nga_site())
        self.assertEqual((got, err), (old, "API: HTTP 503; daily lists: stale: newest warning 2026-11-12"))

    def test_one_failed_file_keeps_that_area_and_takes_the_others(self):
        old = [{"id": "P-1-2026", "area": "HYDROPAC"}, {"id": "A-1-2026", "area": "HYDROLANT"}]
        got, err, src, held = navarea.collect(old, "2026-11-12T17:00:00Z", nga_site(down=("PAC",)))
        self.assertEqual((err, held), (None, {"HYDROPAC": "HTTP 404"}))
        ids = {w["id"] for w in got}
        self.assertEqual(len(ids), 13, "three from each of four areas, and HYDROPAC's one earlier warning")
        self.assertIn("P-1-2026", ids)
        self.assertNotIn("A-1-2026", ids, "an area that answered is replaced, not merged")
        self.assertEqual(navarea.held_too_long({"HYDROPAC": {"since": "2026-11-10T16:00:00Z"},
                                                "HYDROARC": {"since": "2026-11-12T10:00:00Z"}},
                                               "2026-11-12T17:00:00Z", 48), {"HYDROPAC"})


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

    def test_new_expired_and_alert_warnings(self):
        def w(num, issued, text):
            return {"msgYear": 2026, "msgNumber": num, "navArea": "P", "issueDate": issued, "authority": "", "text": text}
        hormuz = "STRAIT OF HORMUZ.\nOMAN.\nM/V X SUFFERED A SECURITY INCIDENT IN 26-24.07N 056-24.72E."
        nav = {"warnings": navarea.parse({"broadcast-warn": [
            w(1, "121000Z NOV 2026", hormuz), w(2, "011000Z NOV 2026", hormuz),
            w(3, "121000Z NOV 2026", "RED SEA.\n1. GUNNERY IN 15-00.0N 041-00.0E.\n2. CANCEL THIS MSG 131200Z NOV 26."),
            w(4, "121000Z NOV 2026", "RED SEA.\n1. GUNNERY IN 15-00.0N 041-00.0E.\n2. CANCEL THIS MSG 141200Z NOV 26.")]})}
        fc = feed.build({}, {}, {}, nav, datetime(2026, 11, 13, 17, tzinfo=timezone.utc))
        self.assertEqual(fc["dropped"], [])
        p = {f["properties"]["id"][-6:]: f["properties"] for f in fc["features"]}
        self.assertEqual(sorted(p), ["1-2026", "2-2026", "4-2026"], "a warning past its cancel time is left out")
        self.assertEqual(fc["health"]["nga-navwarnings"]["expired"], 1)
        self.assertEqual([(p[k]["tier"], p[k]["measures"]["new"]) for k in sorted(p)],
                         [("anomaly", True), ("routine", False), ("anomaly", True)],
                         "new security incident; old one; new military exercise")
        self.assertTrue({"launch", "military"} <= feed.NEW_ALERT)
        self.assertNotIn("wreck", feed.NEW_ALERT, "everyday kinds stay routine even when new")
        self.assertEqual(p["1-2026"]["baseline_ref"]["id"], "nga-warnings-in-force")
        self.assertEqual(p["4-2026"]["valid_until"], "2026-11-14T12:00:00Z")
        self.assertNotIn("valid_until", p["1-2026"])

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

    def test_an_area_held_for_two_days_is_withheld(self):
        now = datetime(2026, 11, 12, 17, tzinfo=timezone.utc)
        pac = NGA_TEXT.replace("NAVAREA IV", "HYDROPAC").replace("0100Z TO 0200Z", "0300Z TO 0400Z").replace(
            "10-05.05N", "11-05.05N")  # other times and places, so these are not rebroadcasts of the NAVAREA IV ones
        nav = {"warnings": navarea.parse_text(NGA_TEXT, "4") + navarea.parse_text(pac, "P")}
        ok = {"last_ok": "2026-11-12T16:00:00Z", "failures": 0, "detail": "6 warnings in force"}
        for since, shown, withheld in (("2026-11-12T10:00:00Z", 4, None), ("2026-11-10T16:00:00Z", 2, 2)):
            held = {"HYDROPAC": {"error": "HTTP 404", "since": since}}
            fc = feed.build({}, {}, {}, nav, now, {"nga-navwarnings": {**ok, "held_areas": held}})
            nga = fc["health"]["nga-navwarnings"]
            self.assertEqual((len(fc["features"]), nga["state"], nga.get("withheld")), (shown, "fresh", withheld))
            self.assertEqual(nga["held_areas"], held)


    def test_a_rebroadcast_is_one_item_listing_the_other(self):
        """NAVAREA XII 788/26 and HYDROPAC 3257/26, as NGA's daily lists carried them on 13 Nov 2026: one hazard."""
        now = datetime(2026, 11, 13, 17, tzinfo=timezone.utc)
        xii = navarea.parse_text(REBROADCAST.format(series="NAVAREA XII", num=788), "12")
        pac = navarea.parse_text(REBROADCAST.format(series="HYDROPAC", num=3257), "P")
        fc = feed.build({}, {}, {}, {"warnings": pac + xii}, now)
        self.assertEqual(fc["dropped"], [])
        self.assertEqual([f["properties"]["id"] for f in fc["features"]], ["cordon:navwarn:12-788-2026"],
                         "the NAVAREA copy leads; the HYDROPAC copy is not drawn again")
        p = fc["features"][0]["properties"]
        self.assertEqual(p["measures"]["rebroadcasts"], [{"id": "cordon:navwarn:P-3257-2026", "number": "HYDROPAC 3257/2026",
                                                          "issued": "2026-11-07T01:15:00Z", "vertex_differences": []}])
        self.assertTrue(p["title"].endswith("(also HYDROPAC 3257/2026)"))
        self.assertEqual(fc["health"]["nga-navwarnings"]["rebroadcasts_merged"], 1)

    def test_rebroadcast_matching_rules(self):
        xii = navarea.parse_text(REBROADCAST.format(series="NAVAREA XII", num=787), "12")
        # One position written differently (as NAVAREA XI 0507/26 wrote 178-12E where HYDROPAC 3256/26 has 178-21E).
        moved = navarea.parse_text(REBROADCAST.replace("31-10.00N 178-00.00E", "31-10.00N 178-09.00E")
                                   .format(series="HYDROPAC", num=3256), "P")
        leads, merged = navarea.rebroadcasts(moved + xii)
        self.assertEqual(merged, {"P-3256-2026": "12-787-2026"})
        self.assertEqual(leads["12-787-2026"][0]["vertex_differences"],
                         [{"position": 6, "lead": [178.0, 31.167], "rebroadcast": [178.15, 31.167]}],
                         "shown as each wrote it, not corrected")
        other_times = navarea.parse_text(REBROADCAST.replace("0130Z TO 0501Z", "0230Z TO 0601Z")
                                         .format(series="HYDROPAC", num=3258), "P")
        same_series = navarea.parse_text(REBROADCAST.format(series="NAVAREA XII", num=790), "12")
        self.assertEqual(navarea.rebroadcasts(other_times + same_series + xii), ({}, {}),
                         "other times, or a second warning in the same series, are separate hazards")
        far = REBROADCAST
        for a, b in (("23-56.00N", "22-56.00N"), ("26-09.00N", "25-09.00N"), ("27-46.00N", "26-46.00N"),
                     ("29-28.00N 165", "28-28.00N 165"), ("30-43.00N", "29-43.00N"), ("31-10.00N", "30-10.00N")):
            far = far.replace(a, b)
        self.assertEqual(navarea.rebroadcasts(navarea.parse_text(far.format(series="HYDROPAC", num=3259), "P") + xii),
                         ({}, {}), "more than a fifth of the positions differ: a different area")


# NAVAREA XII 788/26 as NGA's daily list carried it on 13 Nov 2026 (HYDROPAC 3257/26 is word for word the same).
REBROADCAST = """
070115Z NOV 26
{series} {num}/26.
NORTH PACIFIC.
MIDWAY ISLANDS.
1. HAZARDOUS OPERATIONS, SPACE DEBRIS
   0130Z TO 0501Z DAILY 14 THRU 20 NOV
   IN AREA BOUND BY
   23-56.00N 144-37.00E, 26-09.00N 151-14.00E,
   27-46.00N 156-36.00E, 29-28.00N 165-10.00E,
   30-43.00N 172-44.00E, 31-10.00N 178-00.00E,
   31-16.00N 175-01.00W, 31-21.00N 171-27.00W,
   30-33.00N 161-15.00W, 29-37.00N 155-40.00W,
   28-49.00N 151-35.00W, 26-53.00N 145-26.00W,
   26-50.00N 145-28.00W, 24-03.00N 154-32.00W,
   23-46.00N 156-11.00W, 24-52.00N 159-19.00W,
   27-38.00N 167-49.00W, 29-23.00N 175-00.00W,
   29-35.00N 176-36.00W, 29-37.00N 179-58.00W,
   29-28.00N 176-13.00E, 29-11.00N 170-10.00E,
   28-12.00N 163-45.00E, 26-39.00N 156-17.00E,
   23-27.00N 144-49.00E.
2. CANCEL THIS MSG 200601Z NOV 26.
"""


# The FAA's airport-events JSON as served on 13 Nov 2026 (nasstatus.faa.gov/api/airport-events), trimmed. BDL's
# freeForm entry (closed to non-scheduled international carriers) is not a closure program and stays out.
FAA_EVENTS = [
    {"airportId": "BDL", "groundStop": None, "groundDelay": None, "airportClosure": None,
     "freeForm": {"simpleText": "!BDL 11/082 BDL AD AP CLSD TO NON SKED INTL AIR CARRIERS EXC 6HR PPR",
                  "startTime": "2026-11-13T21:39:00Z", "endTime": "2026-11-14T05:00:00Z"},
     "airportLongName": "Bradley International", "latitude": "41.9390", "longitude": "-72.6869"},
    {"airportId": "BOS", "groundStop": None, "groundDelay": {
        "airportId": "BOS", "sourceTimeStamp": "2026-11-13T16:30:57Z", "updatedAt": "2026-11-13T16:31:37Z",
        "impactingCondition": "airport volume", "avgDelay": 26.0, "maxDelay": 103, "startTime": "2026-11-13T18:00:00Z",
        "endTime": "2026-11-14T02:59:00Z", "center": "ZBW", "includedFacilities": ["ZLA", "ZAU"],
        "includedFlights": ": ALL CONTIGUOUS US DEP",
        "advisoryUrl": "https://www.fly.faa.gov/adv/adv_otherdis.jsp?advn=79&adv_date=11132026&facId=BOS"},
     "airportClosure": None, "freeForm": None,
     "airportLongName": "General Edward Lawrence Logan International", "latitude": "42.3656", "longitude": "-71.0096"},
    {"airportId": "SNA", "groundStop": None, "groundDelay": None, "airportClosure": {
        "airportId": "SNA", "updatedAt": "2026-11-07T17:18:37Z", "startTime": "2026-11-10T07:30:00Z",
        "endTime": "2026-11-21T14:15:00Z", "simpleText": "!SNA 11/008 SNA AD AP CLSD DLY 0730-1415 2611100730-2611211415",
        "issuedDate": "2026-11-07T17:16:00Z"},
     "airportLongName": "John Wayne Airport-Orange County", "latitude": "33.6763", "longitude": "-117.8674"},
    {"airportId": "YUL", "groundStop": {
        "airportId": "YUL", "sourceTimeStamp": "2026-11-13T22:28:13Z", "updatedAt": "2026-11-13T22:29:45Z",
        "impactingCondition": "other", "startTime": "2026-11-13T22:15:00Z", "endTime": "2026-11-13T23:30:00Z",
        "center": "CZU", "advisoryUrl": None, "includedFacilities": ["ZAN", "ZLA"], "probabilityOfExtension": None},
     "airportLongName": "Montréal-Pierre Elliott Trudeau International Airport", "latitude": "45.4657", "longitude": "-73.7455"},
]


def gs(apt, lat, lon, reason="thunderstorms", start="2026-11-13T21:00:00Z", end="2026-11-13T23:00:00Z"):
    return {"airportId": apt, "latitude": str(lat), "longitude": str(lon), "airportLongName": apt + " Airport",
            "groundStop": {"impactingCondition": reason, "startTime": start, "endTime": end,
                           "updatedAt": "2026-11-13T21:01:00Z", "includedFacilities": []}}


class Faa(unittest.TestCase):
    NOW = datetime(2026, 11, 13, 22, 30, tzinfo=timezone.utc)
    STAMP = "2026-11-13T22:30:00Z"

    def nas(self, rows):
        progs, apts = faa.parse(rows)
        return {"programs": progs, "airports": apts, "fetched_at": self.STAMP}

    def health(self, last_ok=None):
        return {"faa-nas-status": {"last_ok": last_ok or self.STAMP, "failures": 0, "checked_at": self.STAMP}}

    def build(self, rows, counts=(), last_ok=None):
        return feed.build({}, {}, {}, {}, self.NOW, self.health(last_ok), self.nas(rows), faa_counts=list(counts))

    def items(self, fc):
        return {f["properties"]["id"]: f for f in fc["features"] if f["properties"]["id"].startswith("cordon:faa:")}

    def test_parse_keeps_the_three_programs_and_the_faas_coordinates(self):
        progs, apts = faa.parse(FAA_EVENTS)
        self.assertEqual([(p["kind"], p["airport"]) for p in progs],
                         [("closure", "SNA"), ("ground_delay", "BOS"), ("ground_stop", "YUL")])
        self.assertEqual(apts["BOS"][:2], [-71.0096, 42.3656])
        bos = progs[1]
        self.assertEqual((bos["reason"], bos["avg_delay_min"], bos["max_delay_min"], bos["included_flights"]),
                         ("airport volume", 26.0, 103.0, "ALL CONTIGUOUS US DEP"))
        self.assertEqual(progs[0]["end"], "2026-11-21T14:15:00Z")
        self.assertRaises(ValueError, faa.parse, {"error": "x"})

    def test_items_pass_the_linter_and_report_the_faas_words(self):
        fc = self.build(FAA_EVENTS)
        self.assertEqual(fc["dropped"], [])
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([p for p in contract.check(f, regs) if p[1] == "error"], [], f["properties"]["id"])
        it = self.items(fc)
        yul = it["cordon:faa:ground_stop:YUL:20261113T2215"]["properties"]
        self.assertEqual(yul["tier"], "routine", "one ground stop on a normal day is routine")
        self.assertEqual(yul["countries"], ["CA"])
        self.assertIn("reason as listed: other", yul["title"])
        self.assertEqual(yul["valid_until"], "2026-11-13T23:30:00Z")
        self.assertEqual(it["cordon:faa:ground_delay:BOS:20261113T1800"]["geometry"]["coordinates"], [-71.0096, 42.3656])
        self.assertIn("cordon:faa:closure:SNA:20261110T0730", it)
        self.assertEqual(len(it), 3)

    def test_baseline_prior_then_measured(self):
        b = faa.baseline([], self.NOW)
        self.assertEqual((b["threshold"], b["basis"]), (faa.PRIOR_THRESHOLD, "prior"))
        rows = [{"at": f"2026-11-{d:02d}T{h:02d}:00:00Z", "ground_stop": 2 if h == 20 else 0}
                for d in range(1, 13) for h in range(24)]
        b = faa.baseline(rows, self.NOW)
        self.assertEqual((b["basis"], b["samples"], b["p99"], b["threshold"]), ("measured", 288, 2, 3))
        quiet = [{**r, "ground_stop": 0} for r in rows]
        self.assertEqual(faa.baseline(quiet, self.NOW)["threshold"], faa.FLOOR, "never below the floor")
        late = [{"at": "2026-11-13T23:00:00Z", "ground_stop": 50}] * 100
        self.assertEqual(faa.baseline(late, self.NOW)["basis"], "prior", "counts from after now are not baseline")

    def test_many_ground_stops_at_once_are_an_anomaly(self):
        rows = [gs("ATL", 33.64, -84.43), gs("ORD", 41.98, -87.90), gs("DFW", 32.90, -97.04), gs("DEN", 39.86, -104.67)]
        it = self.items(self.build(rows))
        self.assertEqual({f["properties"]["tier"] for f in it.values()}, {"anomaly"})
        p = it["cordon:faa:ground_stop:ATL:20261113T2100"]["properties"]
        self.assertEqual(p["baseline_ref"]["id"], "faa-concurrent-ground-stops")
        self.assertEqual((p["measures"]["ground_stops_in_effect"], p["measures"]["unusual_at"]), (4, 4))
        self.assertEqual({f["properties"]["tier"] for f in self.items(self.build(rows[:3])).values()}, {"routine"})

    def test_a_ground_stop_for_a_center_or_the_system_is_an_anomaly_at_country_level(self):
        rows = [{"airportId": "ZNY", "groundStop": {"impactingCondition": "equipment / outage",
                                                    "startTime": "2026-11-13T20:45:00Z"}}]
        f = self.items(self.build(rows))["cordon:faa:ground_stop:ZNY:20261113T2045"]
        self.assertEqual(f["properties"]["tier"], "anomaly")
        self.assertEqual(f["properties"]["baseline_ref"]["id"], "faa-ground-stop-scope")
        self.assertEqual((f["properties"]["countries"], f["properties"]["precision_class"]), (["US"], "country"))
        self.assertEqual(f["geometry"]["type"], "Point")
        self.assertEqual([p for p in contract.check(f, registers.ids(ROOT / "doctrine")) if p[1] == "error"], [])

    def test_a_held_list_drops_ended_programs_and_a_stale_one_is_withheld(self):
        rows = [gs("ATL", 33.64, -84.43, end="2026-11-13T22:00:00Z"), gs("ORD", 41.98, -87.90, end="2026-11-14T01:00:00Z")]
        fresh = self.items(self.build(rows))
        self.assertEqual(len(fresh), 2, "a fresh list is the FAA's word, even past a listed end time")
        h = {"faa-nas-status": {"last_ok": "2026-11-13T21:30:00Z", "last_error": self.STAMP, "failures": 1}}
        held = feed.build({}, {}, {}, {}, self.NOW, h, self.nas(rows), faa_counts=[])
        self.assertEqual(held["health"]["faa-nas-status"]["state"], "failing")
        self.assertEqual(list(self.items(held)), ["cordon:faa:ground_stop:ORD:20261113T2100"])
        stale = self.build(rows, last_ok="2026-11-13T19:00:00Z")
        self.assertEqual(stale["health"]["faa-nas-status"]["state"], "stale", "three hours without a good fetch")
        self.assertEqual((self.items(stale), stale["health"]["faa-nas-status"]["withheld"]), ({}, 2))
        never = feed.build({}, {}, {}, {}, self.NOW, {}, self.nas(rows), faa_counts=[])
        self.assertEqual(never["health"]["faa-nas-status"]["state"], "never")
        self.assertEqual(self.items(never), {})

    def test_collect_reports_failures_without_data(self):
        self.assertEqual(faa.collect(fetch=lambda u, t: (None, "HTTP 503"))[2], "HTTP 503")
        self.assertIn("unreadable", faa.collect(fetch=lambda u, t: (b"<html>", None))[2])
        progs, apts, err = faa.collect(fetch=lambda u, t: (json.dumps(FAA_EVENTS).encode(), None))
        self.assertEqual((len(progs), err), (3, None))
        self.assertEqual(faa.collect(fetch=lambda u, t: (b"[]", None))[:2], ([], {}), "an empty list is a quiet NAS")

def fcdo_index(n=160, overrides=None):
    """A GOV.UK travel-advice index shaped like the live one (14 Nov 2026): n countries, slug c<i>, plus overrides."""
    kids = []
    rows = {f"c{i:03d}": ("Country " + str(i), "2026-10-01T09:00:00Z", "Latest update.") for i in range(n)}
    rows.update(overrides or {})
    for slug, (name, at, change) in rows.items():
        kids.append({"base_path": f"/foreign-travel-advice/{slug}", "public_updated_at": at,
                     "web_url": f"https://www.gov.uk/foreign-travel-advice/{slug}", "title": f"{name} travel advice",
                     "details": {"change_description": change, "country": {"name": name, "slug": slug, "synonyms": []}}})
    return json.dumps({"links": {"children": kids}}).encode()


def fcdo_page(statuses):
    return json.dumps({"details": {"alert_status": statuses}}).encode()


class Fcdo(unittest.TestCase):
    NOW = datetime(2026, 11, 14, 14, 30, tzinfo=timezone.utc)
    STAMP = "2026-11-14T14:30:00Z"

    def fetcher(self, index, pages, fail=()):
        calls = []

        def fetch(url, timeout=40):
            calls.append(url)
            if url == fcdo.SOURCE_URL:
                return index, None
            slug = url.rsplit("/", 1)[-1]
            if slug in fail:
                return None, "HTTP 429"
            return fcdo_page(pages.get(slug, [])), None
        return fetch, calls

    def test_words_put_the_whole_country_first(self):
        self.assertEqual(fcdo.words(["avoid_all_but_essential_travel_to_parts", "avoid_all_travel_to_parts"]),
                         "advises against all travel to parts and all but essential travel to parts")
        self.assertEqual(fcdo.words([]), "no advice against travel")
        self.assertEqual(fcdo.words(None), "advice status not yet read")

    def test_collect_reads_a_page_only_when_the_fcdo_updates_it(self):
        ua = {"ukraine": ("Ukraine", "2026-10-02T08:30:25Z", "Updated information about the Russian invasion.")}
        fetch, calls = self.fetcher(fcdo_index(overrides=ua), {"ukraine": ["avoid_all_travel_to_parts"]})
        first, changes, err, read, failed = fcdo.collect(None, self.STAMP, fetch, pause=0)
        self.assertIsNone(err)
        self.assertEqual((len(first), read, failed, changes), (161, 161, 0, []))
        self.assertEqual(first["ukraine"]["alert_status"], ["avoid_all_travel_to_parts"])
        self.assertEqual(first["ukraine"]["iso"], "UA")
        # Nothing updated: only the index is asked for.
        fetch, calls = self.fetcher(fcdo_index(overrides=ua), {})
        same, changes, err, read, failed = fcdo.collect(first, self.STAMP, fetch, pause=0)
        self.assertEqual((calls, read, changes), ([fcdo.SOURCE_URL], 0, []))
        # The FCDO updates Ukraine and widens its advice: one page read, one change.
        ua2 = {"ukraine": ("Ukraine", "2026-11-14T12:00:00Z", "Change to advice for the whole country.")}
        fetch, calls = self.fetcher(fcdo_index(overrides=ua2), {"ukraine": ["avoid_all_travel_to_whole_country"]})
        new, changes, err, read, failed = fcdo.collect(same, self.STAMP, fetch, pause=0)
        self.assertEqual(read, 1)
        self.assertEqual([(c["key"], c["kind"], c["from"], c["to"]) for c in changes],
                         [("ukraine", "alert", ["avoid_all_travel_to_parts"], ["avoid_all_travel_to_whole_country"])])

    def test_a_failed_page_keeps_its_last_status_and_is_asked_again(self):
        ua = {"ukraine": ("Ukraine", "2026-10-02T08:30:25Z", "x")}
        fetch, _ = self.fetcher(fcdo_index(overrides=ua), {"ukraine": ["avoid_all_travel_to_parts"]})
        first = fcdo.collect(None, self.STAMP, fetch, pause=0)[0]
        ua2 = {"ukraine": ("Ukraine", "2026-11-14T12:00:00Z", "y")}
        fetch, _ = self.fetcher(fcdo_index(overrides=ua2), {}, fail={"ukraine"})
        held, changes, err, read, failed = fcdo.collect(first, self.STAMP, fetch, pause=0)
        self.assertEqual((failed, changes), (1, []))
        self.assertEqual(held["ukraine"]["alert_status"], ["avoid_all_travel_to_parts"])
        fetch, calls = self.fetcher(fcdo_index(overrides=ua2), {"ukraine": ["avoid_all_travel_to_parts"]})
        fcdo.collect(held, self.STAMP, fetch, pause=0)
        self.assertEqual(calls, [fcdo.SOURCE_URL, fcdo.COUNTRY_API.format(slug="ukraine")])

    def test_a_short_or_broken_index_is_an_error(self):
        fetch, _ = self.fetcher(fcdo_index(n=20), {})
        self.assertIn("only 20 countries", fcdo.collect({}, self.STAMP, fetch, pause=0)[2])
        fetch, _ = self.fetcher(b"<html>", {})
        self.assertIn("unreadable", fcdo.collect({}, self.STAMP, fetch, pause=0)[2])

    def build(self, countries, changes=(), last_ok=None):
        h = {"uk-fcdo-travel-advice": {"last_ok": last_ok or self.STAMP, "failures": 0, "checked_at": self.STAMP}}
        uk = {"countries": countries, "fetched_at": self.STAMP}
        with unittest.mock.patch.object(feed, "recent_changes", lambda now: list(changes)):
            return feed.build({}, {}, {}, {}, self.NOW, h, uk=uk)

    def rec(self, slug, iso, statuses, updated="2026-10-01T09:00:00Z", change="Latest update."):
        return {"slug": slug, "name": slug.title(), "iso": iso, "alert_status": statuses, "updated": updated,
                "change": change, "link": f"https://www.gov.uk/foreign-travel-advice/{slug}", "status_for": updated}

    def test_items_list_advice_against_travel_recent_updates_and_changes(self):
        countries = {"ukraine": self.rec("ukraine", "UA", ["avoid_all_travel_to_parts"]),
                     "france": self.rec("france", "FR", []),
                     "usa": self.rec("usa", "US", [], "2026-11-14T02:26:03Z", "Updated information on air traffic."),
                     "poland": self.rec("poland", "PL", [])}
        changes = [{"at": "2026-11-10T10:00:00Z", "lane": "fcdo", "kind": "alert", "key": "poland", "iso": "PL",
                    "from": ["avoid_all_but_essential_travel_to_parts"], "to": []}]
        fc = self.build(countries, changes)
        self.assertEqual(fc["dropped"], [])
        items = {f["properties"]["id"]: f["properties"] for f in fc["features"]}
        self.assertEqual(sorted(items), ["cordon:fcdo:poland", "cordon:fcdo:ukraine", "cordon:fcdo:usa"])
        self.assertEqual(items["cordon:fcdo:ukraine"]["title"], "UK FCDO, Ukraine: advises against all travel to parts")
        self.assertEqual(items["cordon:fcdo:usa"]["title"],
                         "UK FCDO, Usa: no advice against travel (updated: Updated information on air traffic.)")
        self.assertEqual(items["cordon:fcdo:poland"]["tier"], "anomaly")
        self.assertEqual(items["cordon:fcdo:poland"]["baseline_ref"]["id"], "previous-fcdo-alert-status")
        self.assertEqual(items["cordon:fcdo:poland"]["measures"]["from_advice"],
                         "advises against all but essential travel to parts")
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([m for _, sev, m in contract.check(f, regs) if sev == "error"], [])
        self.assertIn("Open Government Licence v3.0", fc["attribution"])

    def test_a_stale_list_is_withheld(self):
        countries = {"ukraine": self.rec("ukraine", "UA", ["avoid_all_travel_to_parts"])}
        fc = self.build(countries, last_ok="2026-11-11T00:00:00Z")
        self.assertEqual(fc["features"], [])
        self.assertEqual(fc["health"]["uk-fcdo-travel-advice"]["state"], "stale")
        self.assertEqual(fc["health"]["uk-fcdo-travel-advice"]["withheld"], 1)


def tfr_xml(nid="7131", issued="2026-11-14T10:00:00", effective="2026-11-14T20:53:00", expire="2026-11-15T00:14:00",
            area="merged", text="!FDC 6/7131 ZHU TX..AIRSPACE STARBASE, TX..TEMPORARY FLIGHT RESTRICTIONS.",
            name="261114 SpaceX Recovery Starship 15", city="STARBASE"):
    """A detail file in the FAA's XNOTAM shape (from detail_6_7131.xml and detail_6_7546.xml, 14 Nov 2026)."""
    shapes = {
        "merged": "<abdMergedArea>" + "".join(
            f"<Avx><codeDatum>WGE</codeDatum><codeType>GRC</codeType><geoLat>{la}</geoLat><geoLong>{lo}</geoLong></Avx>"
            for la, lo in [("25.93333333N", "097.16666667W"), ("26.01666667N", "097.2W"), ("26.1N", "096.91666667W"),
                           ("25.93333333N", "097.16666667W")]) + "</abdMergedArea>",
        "circle": "<aseShapes><Abd><Avx><codeDatum>WGE</codeDatum><codeType>CIR</codeType><geoLat>39.52833333N</geoLat>"
                  "<geoLong>078.31472222W</geoLong><valRadiusArc>10.0</valRadiusArc><uomRadiusArc>NM</uomRadiusArc>"
                  "</Avx></Abd></aseShapes>",
        "none": ""}[area]
    return (f'<XNOTAM-Update version="0.1"><Group><Add><Not><NotUid><txtNameAcctFac>FDC</txtNameAcctFac>'
            f"<dateIndexYear>2026</dateIndexYear><noSeqNo>{nid}</noSeqNo><dateIssued>{issued}</dateIssued>"
            f"<txtLocalName>{name}</txtLocalName></NotUid><dateEffective>{effective}</dateEffective>"
            + (f"<dateExpire>{expire}</dateExpire>" if expire else "")
            + f"<codeTimeZone>CST</codeTimeZone><AffLocGroup><txtNameCity>{city}</txtNameCity>"
            f"<txtNameUSState>TEXAS</txtNameUSState></AffLocGroup><TfrNot><codeType>91.143</codeType><TFRAreaGroup>"
            f"<aseTFRArea><txtName>Area A</txtName><codeDistVerUpper>ALT</codeDistVerUpper><valDistVerUpper>999"
            f"</valDistVerUpper><uomDistVerUpper>FL</uomDistVerUpper><codeDistVerLower>HEI</codeDistVerLower>"
            f"<valDistVerLower>0</valDistVerLower><uomDistVerLower>FT</uomDistVerLower></aseTFRArea>{shapes}"
            f"</TFRAreaGroup><txtDescrUSNS>{text}</txtDescrUSNS></TfrNot></Not></Add></Group></XNOTAM-Update>").encode()


TFR_LIST = [
    {"notam_id": "6/7131", "type": "SPACE OPERATIONS", "facility": "ZHU", "state": "TX",
     "description": "STARBASE, TX, Saturday, November 14, 2026 Local", "creation_date": "11/14/2026"},
    {"notam_id": "6/7546", "type": "HAZARDS", "facility": "ZDC", "state": "WV",
     "description": "W MARTINSBURG, WV, Saturday, November 14, 2026 UTC", "creation_date": "11/14/2026"},
    {"notam_id": "6/6924", "type": "SECURITY", "facility": "ZJX", "state": "FL",
     "description": "DISNEY WORLD THEME PARK, ORLANDO, FL", "creation_date": "11/13/2026"},
    {"notam_id": "1/5060", "type": "SPECIAL", "facility": "FDC", "state": "USA",
     "description": "  USA, Wednesday, September 29, 2021 UTC", "creation_date": "01/27/2024"},
    {"notam_id": "6/2698", "type": "HAZARDS", "facility": "ZSU", "state": "PR",
     "description": "VIEQUES, PR", "creation_date": "01/13/2026"},
    {"notam_id": "6/0001", "type": "VIP", "facility": "ZDC", "state": "VA",
     "description": "Sterling, VA, Sunday, November 1, 2026 Local", "creation_date": "10/30/2026"},
]
TFR_DETAILS = {
    "6_7131": tfr_xml(),
    "6_7546": tfr_xml("7546", area="circle", name="6/7546", city="W MARTINSBURG"),
    "6_6924": tfr_xml("6924", issued="2026-11-13T09:00:00", expire=None, city="ORLANDO", name="6/6924",
                      text="!FDC 6/6924 ... PURSUANT TO SECTION 352 OF PUBLIC LAW 108-7 ..."),
    "1_5060": tfr_xml("5060", issued="2024-01-27T08:23:00", expire=None, area="none", name="1/5060", city=""),
    "6_2698": tfr_xml("2698", issued="2026-01-13T14:45:00", expire="2026-12-18T21:00:00", city="VIEQUES", name="6/2698"),
    "6_0001": tfr_xml("0001", issued="2026-10-30T12:00:00", effective="2026-11-01T12:00:00",
                      expire="2026-11-01T20:00:00", name="6/0001", city="Sterling"),
}


class Tfr(unittest.TestCase):
    NOW = datetime(2026, 11, 14, 14, 30, tzinfo=timezone.utc)
    STAMP = "2026-11-14T14:30:00Z"

    def fetcher(self, details=None, fail=()):
        calls = []
        details = TFR_DETAILS if details is None else details

        def fetch(url, timeout=30):
            calls.append(url)
            if url == tfr.LIST_URL:
                return json.dumps(TFR_LIST).encode(), None
            fid = url.rsplit("detail_", 1)[-1][:-4]
            return (None, "HTTP 500") if fid in fail else (details[fid], None)
        return fetch, calls

    def test_parse_detail_keeps_the_faas_outline_utc_times_and_heights(self):
        d = tfr.parse_detail(TFR_DETAILS["6_7131"])
        self.assertEqual((d["effective"], d["expires"], d["issued"]),
                         ("2026-11-14T20:53:00Z", "2026-11-15T00:14:00Z", "2026-11-14T10:00:00Z"))
        self.assertEqual(d["geometry"]["type"], "Polygon")
        self.assertEqual(d["geometry"]["coordinates"][0][:2], [[-97.16667, 25.93333], [-97.2, 26.01667]])
        self.assertEqual((d["floor"], d["ceiling"], d["regulation"], d["city"]), ("surface", "FL999", "91.143", "STARBASE"))
        circle = tfr.parse_detail(TFR_DETAILS["6_7546"])["geometry"]
        self.assertEqual((circle["type"], len(circle["coordinates"][0])), ("Polygon", 33))
        self.assertIsNone(tfr.parse_detail(TFR_DETAILS["1_5060"])["geometry"])
        self.assertTrue(tfr.parse_detail(TFR_DETAILS["6_6924"])["statutory"])
        self.assertEqual(tfr.coord("097.2W"), -97.2)

    def test_collect_reads_each_detail_once_and_retries_a_failure(self):
        fetch, calls = self.fetcher(fail={"6_7546"})
        first, err, read, failed = tfr.collect(None, self.STAMP, fetch, pause=0)
        self.assertEqual((err, read, failed, len(first)), (None, 5, 1, 6))
        self.assertIsNone(first["6/7546"]["detail"])
        fetch, calls = self.fetcher()
        again, err, read, failed = tfr.collect(first, self.STAMP, fetch, pause=0)
        self.assertEqual((read, calls), (1, [tfr.LIST_URL, tfr.DETAIL_URL.format(id="6_7546")]))
        fetch, _ = self.fetcher()
        self.assertEqual(tfr.collect(again, self.STAMP, lambda u, t=30: (None, "HTTP 503"))[1], "HTTP 503")

    def build(self, held, last_ok=None):
        h = {"faa-tfr": {"last_ok": last_ok or self.STAMP, "failures": 0, "checked_at": self.STAMP}}
        return feed.build({}, {}, {}, {}, self.NOW, h, tfrs={"tfrs": held, "fetched_at": self.STAMP})

    def test_items_new_launches_statutory_no_shape_and_expired(self):
        fetch, _ = self.fetcher(fail={"6_7546"})
        held = tfr.collect(None, self.STAMP, fetch, pause=0)[0]
        fc = self.build(held)
        self.assertEqual(fc["dropped"], [])
        items = {f["properties"]["id"]: f for f in fc["features"]}
        self.assertEqual(sorted(items), ["cordon:tfr:6-2698", "cordon:tfr:6-6924", "cordon:tfr:6-7131", "cordon:tfr:6-7546"])
        launch = items["cordon:tfr:6-7131"]["properties"]
        self.assertEqual(launch["title"], "FAA TFR 6/7131 (space operations): STARBASE, TX (261114 SpaceX Recovery Starship 15)")
        self.assertEqual((launch["tier"], launch["baseline_ref"]["id"], launch["valid_until"]),
                         ("anomaly", "faa-tfrs-in-force", "2026-11-15T00:14:00Z"))
        self.assertEqual(launch["countries"], ["US"])  # Starbase touches Mexico on the coarse outlines; not tagged MX
        self.assertEqual(items["cordon:tfr:6-6924"]["properties"]["tier"], "routine")  # statutory: never new
        self.assertEqual(items["cordon:tfr:6-2698"]["properties"]["countries"], ["PR"])
        pending = items["cordon:tfr:6-7546"]
        self.assertIsNone(pending["geometry"])
        self.assertEqual(pending["properties"]["visual"]["url"], "https://tfr.faa.gov/tfr3/?page=detail_6_7546")
        hl = fc["health"]["faa-tfr"]
        self.assertEqual((hl["no_shape"], hl["expired"]), (1, 1))
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([m for _, sev, m in contract.check(f, regs) if sev == "error"], [])

    def test_a_list_unread_for_six_hours_is_withheld(self):
        fetch, _ = self.fetcher()
        held = tfr.collect(None, self.STAMP, fetch, pause=0)[0]
        fc = self.build(held, last_ok="2026-11-14T08:00:00Z")
        self.assertEqual(fc["features"], [])
        self.assertEqual((fc["health"]["faa-tfr"]["state"], fc["health"]["faa-tfr"]["withheld"]), ("stale", 6))


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
