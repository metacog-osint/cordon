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
from cordon import (canada, cdc, easa, embassy, faa, faaprn, fcdo, feed, launchwarn, navarea,  # noqa: E402
                    rev21, safetravel, state, tfr)
from cordon.common import digest  # noqa: E402
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
        self.assertEqual(rec["text"], long_.strip(), "C4: stored text is whole, however long")
        shown = navarea.display_text(rec["text"])   # the feed's short form keeps its 6,000-character cut and note
        self.assertTrue(shown.endswith(f"[Cut by Cordon: {len(long_.strip()) - navarea.TEXT_MAX} more characters. "
                                       "Full text: NGA, msi.nga.mil/NavWarnings]"))
        self.assertEqual(navarea.display_text(shown), shown, "text an older version already cut is not cut twice")

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
        nga = fc["health"]["nga-navwarnings"]
        self.assertEqual((nga["state"], nga["newest_item"], nga["data_as_of"]), ("fresh",) + ("2026-10-29T16:10:00Z",) * 2)
        self.assertEqual(contract.check_health(fc["health"], strict=True), [])

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

    def test_space_operations_left_to_launch(self):
        fetch, _ = self.fetcher()
        held = tfr.collect(None, self.STAMP, fetch, pause=0)[0]
        fc = self.build(held)
        ids = {f["properties"]["id"] for f in fc["features"]}
        self.assertNotIn("cordon:tfr:6-7131", ids)
        self.assertIn("6/7131", held)  # kept in data
        self.assertEqual(fc["health"]["faa-tfr"]["skipped"], 1)
        line = tfr.health_detail(held, 0, 0)
        self.assertIn("; 1 space operations TFR left to Launch;", line)
        self.assertTrue(line.endswith("; 0 detail files read"))
        saved, tfr.SKIP_TYPES = tfr.SKIP_TYPES, {}
        try:
            self.assertNotIn("left to", tfr.health_detail(held, 2, 1))
            self.assertTrue(tfr.health_detail(held, 2, 1).endswith("; 2 detail files read, 1 failed"))
        finally:
            tfr.SKIP_TYPES = saved

    def test_items_new_launches_statutory_no_shape_and_expired(self):
        fetch, _ = self.fetcher(fail={"6_7546"})
        held = tfr.collect(None, self.STAMP, fetch, pause=0)[0]
        saved, tfr.SKIP_TYPES = tfr.SKIP_TYPES, {}  # the anomaly rule still holds if the skip is lifted
        try:
            fc = self.build(held)
        finally:
            tfr.SKIP_TYPES = saved
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

    @staticmethod
    def square(lon, lat, half_deg):
        return {"type": "Polygon", "coordinates": [[[lon - half_deg, lat - half_deg], [lon + half_deg, lat - half_deg],
                                                    [lon + half_deg, lat + half_deg], [lon - half_deg, lat + half_deg],
                                                    [lon - half_deg, lat - half_deg]]]}

    def rec(self, nid, typ, state, geom, ceiling="5000 ft MSL", issued="2026-11-14T10:00:00Z", first_seen=None):
        return {"notam_id": nid, "type": typ, "facility": "ZLA", "state": state, "description": f"PLACE, {state}",
                "created": "11/14/2026", "first_seen": first_seen or issued,
                "detail": {"name": nid, "issued": issued, "effective": "2026-11-14T10:00:00Z",
                           "expires": "2026-11-16T10:00:00Z", "city": "PLACE", "floor": "surface", "ceiling": ceiling,
                           "statutory": False, "text": "x", "geometry": geom}}

    def test_impact_levels_weigh_size_height_and_the_busiest_airports(self):
        # Tom, 15 Nov 2026: a small volcano TFR in Hawaii is not one over a hub.
        volcano = tfr.impact(self.rec("6/1", "HAZARDS", "HI", self.square(-155.28, 19.41, 0.03), "4000 ft MSL"))
        self.assertEqual((volcano["impact"], volcano["nearest_core30"]["airport"], volcano["ceiling_ft"]),
                         ("low", "HNL", 4000))
        self.assertLess(volcano["area_km2"], 100)
        hub = tfr.impact(self.rec("6/2", "SECURITY", "IL", self.square(-87.90, 41.98, 0.05), "3000 ft MSL"))
        self.assertEqual((hub["impact"], hub["impact_basis"]), ("high", ["within 56 km of ORD (Core 30)"]))
        wide = tfr.impact(self.rec("6/3", "VIP", "AK", self.square(-149.9, 61.2, 0.5), "17999 ft MSL"))
        self.assertEqual(wide["impact"], "high")
        # Tom, 16 Nov 2026 UTC: a small column to unlimited (Santa Rosa Island munitions test, 29 km2) rates low;
        # reaching Class A counts from 100 km2.
        tall = tfr.impact(self.rec("6/4", "SECURITY", "FL", self.square(-86.6, 30.36, 0.03), "FL999"))
        self.assertEqual((tall["impact"], tall["ceiling_ft"], tall["impact_basis"]), ("low", 99900, []))
        self.assertLess(tall["area_km2"], 100)
        tall_wide = tfr.impact(self.rec("6/5", "SECURITY", "FL", self.square(-86.6, 30.36, 0.06), "FL999"))
        self.assertEqual(tall_wide["impact"], "moderate")
        self.assertTrue(100 <= tall_wide["area_km2"] < 250, tall_wide["area_km2"])
        self.assertEqual(tall_wide["impact_basis"], [f"reaches FL180 over {tall_wide['area_km2']:,.0f} km2"])
        self.assertEqual([tfr.feet(h) for h in ("surface", "FL180", "2500 ft AGL", None, "odd")], [0, 18000, 2500, None, None])

    def test_reissues_are_not_new_unless_larger(self):
        geom = self.square(-157.77, 21.45, 0.1)
        old = self.rec("6/10", "SECURITY", "HI", geom, issued="2026-11-10T00:00:00Z")
        new = self.rec("6/11", "SECURITY", "HI", geom, issued="2026-11-14T10:00:00Z")
        gone = tfr.remember({"6/10": old}, {"6/11": new}, {}, "2026-11-14T11:00:00Z")
        self.assertEqual((list(gone), gone["6/10"]["left_at"]), (["6/10"], "2026-11-14T11:00:00Z"))
        self.assertEqual(tfr.reissue("6/11", new, {"6/11": new}, gone), {"of": "6/10", "enlarged": False})
        bigger = self.rec("6/12", "SECURITY", "HI", self.square(-157.77, 21.45, 0.13), issued="2026-11-14T10:00:00Z")
        self.assertTrue(tfr.reissue("6/12", bigger, {"6/12": bigger}, gone)["enlarged"])
        other_type = self.rec("6/13", "HAZARDS", "HI", geom)
        self.assertIsNone(tfr.reissue("6/13", other_type, {"6/13": other_type}, gone))
        self.assertEqual(tfr.remember({}, {}, gone, "2026-11-29T00:00:00Z"), {})  # forgotten after 14 days
        # In the feed: the re-issue is routine and names the one it repeats; the enlarged one is new.
        data = {"tfrs": {"6/11": new, "6/12": bigger}, "gone": gone, "fetched_at": self.STAMP}
        items = {f["properties"]["id"]: f["properties"] for f in feed.tfr_items(data, self.NOW)[0]}
        self.assertEqual((items["cordon:tfr:6-11"]["tier"], items["cordon:tfr:6-11"]["measures"]["reissue_of"]),
                         ("routine", "6/10"))
        self.assertEqual(items["cordon:tfr:6-12"]["tier"], "anomaly")
        self.assertEqual(items["cordon:tfr:6-11"]["subdivisions"], ["US-HI"])

    def test_states_from_the_faa_or_the_shape(self):
        self.assertEqual(feed.us_subdivisions(["US"], None, "HI"), ["US-HI"])
        self.assertEqual(feed.us_subdivisions(["PR"], None, "PR"), [])
        dc = self.square(-77.04, 38.89, 0.3)  # the DC area TFR: the FAA's state is "USA"
        self.assertEqual(feed.us_subdivisions(["US"], dc, "USA"), ["US-DC", "US-MD", "US-VA"])
        self.assertEqual(feed.us_subdivisions(["US"], {"type": "Point", "coordinates": [-98.6, 39.8]}, None), ["US-KS"])
        self.assertEqual(feed.us_subdivisions(["CA"], dc, None), [])


def canada_row(iso, name, level, ts=1791975710, kind="Regular text update", note="Safety and security - updated.",
               regional=0):
    """One entry of Canada's index as published (ts 1791975710 = 2026-10-14T11:01:50Z)."""
    slug = name.lower().replace(" ", "-")
    return {"country-iso": iso, "country-eng": name, "advisory-state": level,
            "date-published": {"timestamp": ts, "date": "x", "asp": "x"}, "has-advisory-warning": int(level >= 2),
            "has-regional-advisory": regional, "recent-updates-type": kind,
            "eng": {"name": name, "url-slug": slug, "advisory-text": canada.LEVELS[level], "recent-updates": note}}


def canada_index(n=160, rows=()):
    keys = [chr(65 + i // 26) + chr(65 + i % 26) for i in range(n)]  # AA, AB ... (n < 676)
    data = {k: canada_row(k, f"Place {k}", 0) for k in keys}
    for r in rows:
        data[r["country-iso"]] = r
    return json.dumps({"metadata": {"generated": {"timestamp": 1794624016}}, "data": data}).encode()


class Canada(unittest.TestCase):
    NOW = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)
    STAMP = "2026-11-14T17:00:00Z"

    def test_parse_reads_levels_times_and_regional_places(self):
        doc = json.loads(canada_index(rows=[canada_row("AF", "Afghanistan", 3),
                                            canada_row("PT-20", "Azores", 0, kind="Editorial change"),
                                            {**canada_row("ZZ", "Nowhere", 0), "advisory-state": 7}]))
        got = canada.parse(doc)
        self.assertEqual(got["AF"]["updated"], "2026-10-14T11:01:50Z")
        self.assertEqual((got["AF"]["level"], got["AF"]["advisory"], got["AF"]["link"]),
                         (3, "Avoid all travel", "https://travel.gc.ca/destinations/afghanistan"))
        self.assertEqual((got["PT-20"]["iso"], got["PT-20"]["name"]), ("PT", "Azores"))
        self.assertNotIn("ZZ", got)  # a level Canada does not define is left out

    def test_collect_finds_level_and_regional_changes(self):
        def fetcher(body):
            return lambda url, timeout=40: (body, None)
        first, changes, generated, err = canada.collect(None, self.STAMP, fetcher(canada_index(
            rows=[canada_row("ML", "Mali", 2, regional=1), canada_row("PE", "Peru", 1)])))
        self.assertIsNone(err)
        self.assertEqual((len(first), changes, generated), (162, [], "2026-11-14T02:40:16Z"))
        new, changes, _, err = canada.collect(first, self.STAMP, fetcher(canada_index(
            rows=[canada_row("ML", "Mali", 3, regional=1), canada_row("PE", "Peru", 1, regional=1)])))
        self.assertEqual(sorted((c["key"], c["kind"], c["from"], c["to"]) for c in changes),
                         [("ML", "level", 2, 3), ("PE", "regional", False, True)])

    def test_a_short_or_broken_index_is_an_error(self):
        self.assertIn("only 20 places", canada.collect({}, self.STAMP, lambda u, t=40: (canada_index(n=20), None))[3])
        self.assertIn("unreadable", canada.collect({}, self.STAMP, lambda u, t=40: (b"<html>", None))[3])
        kept = {"AF": {"level": 3}}
        self.assertIs(canada.collect(kept, self.STAMP, lambda u, t=40: (None, "HTTP 503"))[0], kept)

    def build(self, rows, changes=(), last_ok=None):
        h = {"gac-travel-advisories": {"last_ok": last_ok or self.STAMP, "failures": 0, "checked_at": self.STAMP}}
        ca = {"countries": canada.parse(json.loads(canada_index(n=0, rows=rows))), "fetched_at": self.STAMP}
        with unittest.mock.patch.object(feed, "recent_changes", lambda now: list(changes)):
            return feed.build({}, {}, {}, {}, self.NOW, h, ca=ca)

    def test_items_list_raised_levels_regional_changes_and_fresh_updates(self):
        recent = 1794584290  # 2026-11-13T15:38:10Z, inside 72 hours
        rows = [canada_row("AF", "Afghanistan", 3),
                canada_row("FR", "France", 0),  # level 0, old update: not listed
                canada_row("PT-20", "Azores", 0, ts=recent, kind="Editorial change"),  # editorial: not listed
                canada_row("BB", "Barbados", 0, ts=recent, note="Need help? section \u2013 updated mission coordinates"),
                canada_row("MX", "Mexico", 1, regional=1, ts=recent, note="Risk levels section \u2013 removed advisory to "
                           "avoid non-essential travel to the west-central coast; Natural disasters and climate section"),
                canada_row("US", "United States", 0, ts=recent, note="Updated information on a nationwide ground stop"),
                canada_row("TH", "Thailand", 1, regional=1, ts=recent, kind="Regional advisory modified",
                           note="Regional advisory for the border updated"),
                canada_row("ML", "Mali", 3)]
        changes = [{"at": "2026-11-10T10:00:00Z", "lane": "canada", "kind": "level", "key": "ML", "from": 2, "to": 3},
                   {"at": "2026-11-10T10:00:00Z", "lane": "fcdo", "kind": "alert", "key": "AF", "from": [], "to": []}]
        fc = self.build(rows, changes)
        self.assertEqual(fc["dropped"], [])
        items = {f["properties"]["id"]: f["properties"] for f in fc["features"]}
        self.assertEqual(sorted(items), ["cordon:canada:AF", "cordon:canada:ML", "cordon:canada:MX", "cordon:canada:TH",
                                         "cordon:canada:US"])
        self.assertEqual(items["cordon:canada:MX"]["tier"], "anomaly")  # the note, not the kind, says so
        self.assertEqual(items["cordon:canada:AF"]["title"], "Canada, Afghanistan: Avoid all travel")
        self.assertEqual(items["cordon:canada:AF"]["tier"], "routine")
        self.assertEqual(items["cordon:canada:US"]["title"], "Canada, United States: Exercise normal security "
                         "precautions (updated: Updated information on a nationwide ground stop)")
        self.assertEqual(items["cordon:canada:US"]["tier"], "routine")
        self.assertEqual((items["cordon:canada:TH"]["tier"], items["cordon:canada:TH"]["baseline_ref"]["id"]),
                         ("anomaly", "gac-declared-advisory-change"))
        ml = items["cordon:canada:ML"]
        self.assertEqual((ml["tier"], ml["baseline_ref"]["id"], ml["measures"]["from_advice"]),
                         ("anomaly", "previous-gac-advisory", "Avoid non-essential travel"))
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([m for _, sev, m in contract.check(f, regs) if sev == "error"], [])
        self.assertIn("Open Government Licence - Canada", fc["attribution"])

    def test_a_stale_index_is_withheld(self):
        fc = self.build([canada_row("AF", "Afghanistan", 3), canada_row("FR", "France", 0)],
                        last_ok="2026-11-11T00:00:00Z")
        self.assertEqual(fc["features"], [])
        self.assertEqual((fc["health"]["gac-travel-advisories"]["state"], fc["health"]["gac-travel-advisories"]["withheld"]),
                         ("stale", 1))


def nz_row(code, name, level, updated="2 November 2025", slug=None):
    return {"code": code.lower(), "link": {"title": name, "href": f"/destinations/{slug or name.lower().replace(' ', '-')}"},
            "region": "Somewhere", "adviceLevel": level, "nearestOffices": [], "updatedDate": updated}


def nz_listing(n=160, rows=()):
    """The destinations page as MFAT publishes it: the list HTML-escaped in a data-content attribute."""
    import html as _html
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    filler = [nz_row(a + b, f"Place {a}{b}", "low" if a in "QR" else "normal")
              for a in "JQRWXYZ" for b in letters if a + b != "XK"]
    data = {"data": filler[:n] + list(rows), "countries": [],
            "adviceLevels": [{"title": w, "value": k} for k, w in safetravel.LEVELS.items()]}
    return (f'<html><body><div id="js-country-listing" data-content="{_html.escape(json.dumps(data), quote=True)}">'
            f'</div></body></html>').encode()


def nz_page(headline, note=None, updated="2 November 2025"):
    extra = f"\n    <span>{note}</span>" if note else ""
    return (f'<p class="text-off-black-100">\n Page updated {updated}\n</p><h1>X</h1>'
            f'<div class="rounded-b-2xl px-6 py-3 bg-caution-light-two">\n<p class="flex flex-col">\n'
            f'<strong class="flex gap-2">\n<span class="material-symbols-sharp" aria-hidden="true">error</span>\n'
            f'<span>{headline}</span>\n</strong>{extra}\n</p></div>').encode()


class SafeTravel(unittest.TestCase):
    NOW = datetime(2026, 11, 14, 21, 0, tzinfo=timezone.utc)
    STAMP = "2026-11-14T21:00:00Z"

    def fetcher(self, listing, pages, calls=None):
        def fetch(url, timeout=40):
            if calls is not None:
                calls.append(url)
            if url == safetravel.SOURCE_URL:
                return listing, None
            slug = url.rsplit("/", 1)[-1]
            return (pages[slug], None) if slug in pages else (nz_page("Exercise normal safety and security precautions"), None)
        return fetch

    def test_parse_listing_and_page(self):
        body = nz_listing(n=0, rows=[nz_row("MX", "Mexico", "medium", "21 May 2026"),
                                     {**nz_row("", "Kosovo", "medium"), "code": ""},
                                     nz_row("VI", "Virgin Islands, US", "low", slug="virgin-islands,-u-s"),
                                     nz_row("ZZ", "Nowhere", "extreme")]).decode()
        got, words = safetravel.parse_listing(body)
        self.assertEqual(sorted(got), ["MX", "VI", "XK"])  # Kosovo by hand; an unknown level is left out
        self.assertEqual((got["MX"]["advice"], got["MX"]["updated"], got["MX"]["link"]),
                         ("Exercise increased caution", "2026-05-21", "https://www.safetravel.govt.nz/destinations/mexico"))
        self.assertEqual(got["VI"]["link"], "https://www.safetravel.govt.nz/destinations/virgin-islands,-u-s")
        self.assertEqual(safetravel.parse_page(nz_page("Exercise increased caution", "with higher advice levels in some areas",
                                                       "21 May 2026").decode()),
                         {"headline": "Exercise increased caution", "regional_note": "with higher advice levels in some areas",
                          "page_updated": "2026-05-21"})
        self.assertIsNone(safetravel.parse_page(nz_page("Do not travel").decode())["regional_note"])
        with self.assertRaises(ValueError):
            safetravel.parse_page("<html></html>")

    def test_collect_reads_pages_only_when_the_day_moves_and_finds_changes(self):
        rows = [nz_row("MX", "Mexico", "medium", "21 May 2026"), nz_row("PE", "Peru", "medium")]
        pages = {"mexico": nz_page("Exercise increased caution", "with higher advice levels in some areas"),
                 "peru": nz_page("Exercise increased caution")}
        calls = []
        first, changes, err, read, failed = safetravel.collect(None, self.STAMP, self.fetcher(nz_listing(rows=rows), pages, calls), pause=0)
        self.assertEqual((err, changes, read, failed, len(first)), (None, [], 162, 0, 162))
        self.assertEqual(first["MX"]["regional_note"], "with higher advice levels in some areas")
        rows = [nz_row("MX", "Mexico", "high", "21 May 2026"), nz_row("PE", "Peru", "medium", "13 November 2026")]
        pages["peru"] = nz_page("Exercise increased caution", "with higher advice levels in some areas")
        calls = []
        new, changes, err, read, failed = safetravel.collect(first, self.STAMP, self.fetcher(nz_listing(rows=rows), pages, calls), pause=0)
        self.assertEqual((read, calls), (1, [safetravel.SOURCE_URL, "https://www.safetravel.govt.nz/destinations/peru"]))
        self.assertEqual(sorted((c["key"], c["kind"], c["from"], c["to"]) for c in changes),
                         [("MX", "level", "medium", "high"), ("PE", "regional", None, "with higher advice levels in some areas")])

    def test_a_short_or_broken_list_is_an_error(self):
        self.assertIn("only 20", safetravel.collect({}, self.STAMP, lambda u, t=40: (nz_listing(n=20), None), pause=0)[2])
        self.assertIn("unreadable", safetravel.collect({}, self.STAMP, lambda u, t=40: (b"<html>", None), pause=0)[2])
        kept = {"AF": {"level": "avoid"}}
        self.assertIs(safetravel.collect(kept, self.STAMP, lambda u, t=40: (None, "HTTP 503"), pause=0)[0], kept)

    def build(self, recs, changes=(), last_ok=None):
        h = {"nz-mfat-safetravel": {"last_ok": last_ok or self.STAMP, "failures": 0, "checked_at": self.STAMP}}
        nz = {"countries": recs, "fetched_at": self.STAMP}
        with unittest.mock.patch.object(feed, "recent_changes", lambda now: list(changes)):
            return feed.build({}, {}, {}, {}, self.NOW, h, nz=nz)

    def rec(self, key, name, level, updated="2025-11-02", note=None):
        return {"key": key, "iso": key, "name": name, "slug": name.lower(), "region": "R", "level": level,
                "advice": safetravel.LEVELS[level], "updated": updated, "link": f"https://www.safetravel.govt.nz/destinations/{name.lower()}",
                "regional_note": note, "page_for": updated}

    def test_items_list_levels_regional_notes_changes_and_fresh_updates(self):
        recs = {"AF": self.rec("AF", "Afghanistan", "avoid"),
                "FR": self.rec("FR", "France", "low"),  # low, old update, no note: not listed
                "DZ": self.rec("DZ", "Algeria", "low", note="with higher advice levels in some areas"),
                "DE": self.rec("DE", "Germany", "low", updated="2026-11-12"),  # inside 72 hours
                "ML": self.rec("ML", "Mali", "avoid"),
                "MX": self.rec("MX", "Mexico", "medium", note="with higher advice levels in some areas")}
        changes = [{"at": "2026-11-10T10:00:00Z", "lane": "safetravel", "kind": "level", "key": "ML", "from": "high", "to": "avoid"},
                   {"at": "2026-11-11T10:00:00Z", "lane": "safetravel", "kind": "regional", "key": "MX", "from": None,
                    "to": "with higher advice levels in some areas"},
                   {"at": "2026-11-10T10:00:00Z", "lane": "canada", "kind": "level", "key": "AF", "from": 2, "to": 3}]
        fc = self.build(recs, changes)
        self.assertEqual(fc["dropped"], [])
        items = {f["properties"]["id"]: f["properties"] for f in fc["features"]}
        self.assertEqual(sorted(items), ["cordon:safetravel:AF", "cordon:safetravel:DE", "cordon:safetravel:DZ",
                                         "cordon:safetravel:ML", "cordon:safetravel:MX"])
        self.assertEqual((items["cordon:safetravel:AF"]["title"], items["cordon:safetravel:AF"]["tier"]),
                         ("New Zealand, Afghanistan: Do not travel", "routine"))
        self.assertTrue(items["cordon:safetravel:DE"]["measures"]["new"])
        self.assertEqual(items["cordon:safetravel:DZ"]["title"],
                         "New Zealand, Algeria: Exercise normal safety and security precautions (other levels apply in some areas)")
        ml = items["cordon:safetravel:ML"]
        self.assertEqual((ml["tier"], ml["baseline_ref"]["id"], ml["measures"]["from_advice"]),
                         ("anomaly", "previous-mfat-advice", "Avoid non-essential travel"))
        self.assertEqual((items["cordon:safetravel:MX"]["tier"], items["cordon:safetravel:MX"]["measures"]["from_regional_note"]),
                         ("anomaly", None))
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([m for _, sev, m in contract.check(f, regs) if sev == "error"], [])
        self.assertIn("CC BY 4.0", fc["attribution"])

    def test_a_stale_list_is_withheld(self):
        fc = self.build({"AF": self.rec("AF", "Afghanistan", "avoid"), "FR": self.rec("FR", "France", "low")},
                        last_ok="2026-11-11T00:00:00Z")
        self.assertEqual(fc["features"], [])
        self.assertEqual((fc["health"]["nz-mfat-safetravel"]["state"], fc["health"]["nz-mfat-safetravel"]["withheld"]),
                         ("stale", 1))


def cdc_item(level, slug, what, desc, pub="Mon, 09 Nov 2026 05:00:00 GMT"):
    return (f"<item><title>Level {level} - {what}</title><description><![CDATA[{desc}]]></description>"
            f"<link>https://wwwnc.cdc.gov/travel/notices/level{level}/{slug}</link><pubDate>{pub}</pubDate>"
            f"<guid>https://wwwnc.cdc.gov/travel/notices/level{level}/{slug}</guid></item>")


def cdc_feed(*items):
    return ('<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>Travel Notices</title>'
            + "".join(items) + "</channel></rss>").encode()


CDC_BASE = [
    cdc_item(2, "yellow-fever-ghana", "Yellow Fever in Burkina Faso, C&#244;te d’Ivoire, and Ghana",
             "There are outbreaks. Country List : Ghana, Burkina Faso, Côte d'Ivoire (Ivory Coast) "
             "Country List : Ghana, Burkina Faso, Côte d'Ivoire (Ivory Coast)"),
    cdc_item(4, "ebola-drc-provinces", "Ebola Bundibugyo Virus Disease in Ituri and Nord-Kivu Provinces of the "
             "Democratic Republic of the Congo", "CDC recommends avoiding all travel to Ituri and Nord-Kivu.",
             "Tue, 04 Aug 2026 04:00:00 GMT"),
    cdc_item(2, "global-polio", "Global Polio", "Some destinations have poliovirus. Country List : Germany, United "
             "Kingdom, including England, Scotland, Wales, and Northern Ireland, Tanzania, including Zanzibar, "
             "the West Bank and Gaza, Gibraltar (U.K.), Republic of South Sudan, Atlantis",
             "Wed, 23 Sep 2026 04:00:00 GMT"),
]


# Live texts, 17 Nov 2026 (NGA daily memoranda, US public domain), trimmed to a few vertices.
VSFB_801 = ("NORTH PACIFIC.\nCALIFORNIA.\n1. HAZARDOUS OPERATIONS, ROCKET LAUNCHING:\n"
            "   A. 180314Z TO 180737Z NOV, ALTERNATE\n      190300Z TO 190723Z, 200246Z TO 200709Z,\n"
            "      210232Z TO 210655Z, 220218Z TO 220641Z,\n      230400Z TO 230628Z AND\n"
            "      240346Z TO 240614Z NOV IN AREA BOUND BY\n      32-05.00N 119-08.00W, 32-30.00N 119-18.00W,\n"
            "      33-15.00N 119-38.00W, 32-05.00N 119-09.00W.\n"
            "   B. 180314Z TO 180738Z NOV, ALTERNATE\n      190300Z TO 190724Z, 200246Z TO 200710Z,\n"
            "      210232Z TO 210656Z, 220218Z TO 220642Z,\n      230400Z TO 230629Z AND\n"
            "      240346Z TO 240615Z NOV IN AREA BOUND BY\n      30-46.00N 118-15.00W, 31-23.00N 118-47.00W,\n"
            "      29-48.00N 117-39.00W.\n"
            "2. CANCEL NAVAREA XII 785/26.\n3. CANCEL THIS MSG 240734Z NOV 26.")
DEBRIS_1081 = ("GULF OF AMERICA.\nTEXAS.\n1. HAZARDOUS OPERATIONS, SPACE DEBRIS\n   142108Z TO 150014Z NOV, ALTERNATE\n"
               "   2108Z TO 0014Z DAILY 15 THRU 20 NOV\n   IN AREA BOUND BY\n   25-56.00N 097-09.00W, 25-56.00N 097-05.00W,\n"
               "   26-46.00N 097-28.00W, 25-58.00N 097-12.00W.\n2. CANCEL THIS MSG 210114Z NOV 26.")


class LaunchWarn(unittest.TestCase):
    """Windows, hazard and cancels for Cordon's launch category (ported from Orbit, Tom's decision 17 Nov 2026)."""

    def test_lettered_areas_alternates_and_cancel(self):
        m = launchwarn.measures(VSFB_801, "2026-11-13T00:14:00Z", "NAVAREA XII")
        self.assertEqual(m["hazard"], "rocket launching")
        self.assertEqual(len(m["windows"]), 7, "areas opening together are one window")
        self.assertEqual(m["windows"][0], {"start": "2026-11-18T03:14:00Z", "end": "2026-11-18T07:38:00Z"},
                         "the union ends when the last area closes")
        self.assertEqual(m["window_mode"], "alternates")
        self.assertEqual([a["label"] for a in m["area_windows"]], ["A", "B"])
        self.assertEqual(m["area_windows"][0]["windows"][0]["end"], "2026-11-18T07:37:00Z")
        self.assertEqual(m["cancels"], [{"number": "NAVAREA XII 785/26", "id": "cordon:navwarn:12-785-2026"}])

    def test_daily_alternates_and_bare_cancel(self):
        m = launchwarn.measures(DEBRIS_1081.replace("2. CANCEL THIS", "2. CANCEL 1070/26.\n3. CANCEL THIS"),
                                "2026-11-06T22:58:00Z", "NAVAREA IV")
        self.assertEqual(m["hazard"], "space debris")
        self.assertEqual(len(m["windows"]), 7)
        self.assertEqual(m["windows"][-1], {"start": "2026-11-20T21:08:00Z", "end": "2026-11-21T00:14:00Z"})
        self.assertNotIn("area_windows", m)
        self.assertEqual(m["cancels"], [{"number": "NAVAREA IV 1070/26", "id": "cordon:navwarn:4-1070-2026"}],
                         "a cancel naming only a number is in the warning's own series")

    def test_missile_firing_has_no_launch_hazard(self):
        text = ("AEGEAN SEA.\n1. MISSILE OPERATIONS 0530Z TO SUNSET DAILY IN AREA BOUND BY\n"
                "   38-00.0N 024-00.0E, 38-10.0N 024-10.0E, 38-00.0N 024-20.0E.")
        self.assertEqual(launchwarn.measures(text, "2026-11-01T10:00:00Z", "HYDROLANT"), {"hazard": None})

    def test_feed_carries_launch_measures(self):
        def w(num, text):
            return {"msgYear": 2026, "msgNumber": num, "navArea": "4", "issueDate": "062258Z NOV 2026",
                    "authority": "", "text": text}
        nav = {"warnings": navarea.parse({"broadcast-warn": [
            w(1081, DEBRIS_1081),
            w(5, "GULF OF AMERICA.\n1. GUNNERY IN 25-00.0N 090-00.0W.\n2. CANCEL THIS MSG 210114Z NOV 26.")]})}
        fc = feed.build({}, {}, {}, nav, datetime(2026, 11, 10, 17, tzinfo=timezone.utc))
        p = {f["properties"]["id"]: f["properties"]["measures"] for f in fc["features"]}
        m = p["cordon:navwarn:4-1081-2026"]
        self.assertEqual((m["category"], m["hazard"], len(m["windows"]), m["cancels"]),
                         ("launch", "space debris", 7, []))
        self.assertNotIn("windows", p["cordon:navwarn:4-5-2026"], "only the launch category gets the fields")

class Cdc(unittest.TestCase):
    NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    STAMP = "2026-11-10T12:00:00Z"

    def test_parse_reads_levels_places_and_dates(self):
        got = cdc.parse(cdc_feed(*CDC_BASE))
        self.assertEqual(sorted(got), ["ebola-drc-provinces", "global-polio", "yellow-fever-ghana"])
        yf = got["yellow-fever-ghana"]
        self.assertEqual((yf["level"], yf["level_text"], yf["countries"], yf["published"]),
                         (2, "Practice Enhanced Precautions", ["BF", "CI", "GH"], "2026-11-09T05:00:00Z"))
        self.assertEqual(yf["summary"], "There are outbreaks.")
        self.assertEqual((yf["date"], got["ebola-drc-provinces"]["date"]), ("2026-11-09", "2026-08-04"))
        self.assertEqual(got["ebola-drc-provinces"]["countries"], ["CD"])  # from the title
        self.assertEqual(got["ebola-drc-provinces"]["level_text"], "Avoid All Travel")
        polio = got["global-polio"]
        self.assertEqual(polio["countries"], ["DE", "GB", "PS", "SS", "TZ"])  # "including ..." pieces are parts
        self.assertEqual(polio["unplaced"], ["Atlantis"])

    def test_collect_finds_new_raised_and_removed_notices(self):
        first, changes, err = cdc.collect(None, self.STAMP, lambda u, t=30: (cdc_feed(*CDC_BASE), None))
        self.assertEqual((err, len(first), changes), (None, 3, []))
        later = [CDC_BASE[0].replace("Level 2", "Level 3").replace("level2", "level3"), CDC_BASE[1],
                 cdc_item(1, "ebola-kenya", "Ebola Bundibugyo Virus Disease in Kenya", "Imported case.")]
        new, changes, err = cdc.collect(first, self.STAMP, lambda u, t=30: (cdc_feed(*later), None))
        self.assertEqual(sorted((c["key"], c["kind"], c["from"], c["to"]) for c in changes),
                         [("ebola-kenya", "new", None, 1), ("global-polio", "removed", 2, None),
                          ("yellow-fever-ghana", "level", 2, 3)])

    def test_a_broken_or_empty_feed_is_an_error(self):
        self.assertIn("unreadable", cdc.collect({}, self.STAMP, lambda u, t=30: (b"<html>", None))[2])
        self.assertIn("only 0 notices", cdc.collect({}, self.STAMP, lambda u, t=30: (cdc_feed(), None))[2])

    def build(self, changes=(), last_ok=None):
        h = {"cdc-travel-notices": {"last_ok": last_ok or self.STAMP, "failures": 0, "checked_at": self.STAMP}}
        hn = {"notices": cdc.parse(cdc_feed(*CDC_BASE)), "fetched_at": self.STAMP}
        with unittest.mock.patch.object(feed, "recent_changes", lambda now: list(changes)):
            return feed.build({}, {}, {}, {}, self.NOW, h, health_notices=hn)

    def test_items_carry_level_places_and_changes(self):
        changes = [{"at": "2026-11-09T12:00:00Z", "lane": "cdc", "kind": "level", "key": "ebola-drc-provinces",
                    "from": 3, "to": 4}]
        fc = self.build(changes)
        self.assertEqual(fc["dropped"], [])
        items = {f["properties"]["id"]: f for f in fc["features"]}
        self.assertEqual(len(items), 3)
        yf = items["cordon:cdc:yellow-fever-ghana"]
        self.assertEqual(yf["properties"]["title"], "CDC Level 2 (Practice Enhanced Precautions): Yellow Fever in "
                         "Burkina Faso, Côte d’Ivoire, and Ghana")
        self.assertEqual((yf["properties"]["tier"], yf["properties"]["measures"]["new"], yf["geometry"]["type"]),
                         ("routine", True, "MultiPoint"))
        eb = items["cordon:cdc:ebola-drc-provinces"]["properties"]
        self.assertEqual((eb["tier"], eb["measures"]["from_level"], eb["baseline_ref"]["id"]),
                         ("anomaly", 3, "previous-cdc-notices"))
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([m for _, sev, m in contract.check(f, regs) if sev == "error"], [])
        self.assertIn("does not imply endorsement by CDC", fc["attribution"])

    def test_a_change_older_than_72_hours_is_routine_but_kept(self):
        def tier(at):
            ch = [{"at": at, "lane": "cdc", "kind": "level", "key": "ebola-drc-provinces", "from": 3, "to": 4}]
            items = {f["properties"]["id"]: f["properties"] for f in self.build(ch)["features"]}
            return items["cordon:cdc:ebola-drc-provinces"]
        # NOW is 2026-11-10T12:00Z: exactly 72 h earlier still counts, one second older does not
        edge = tier("2026-11-07T12:00:00Z")
        self.assertEqual(edge["tier"], "anomaly")
        old = tier("2026-11-07T11:59:59Z")
        self.assertEqual(old["tier"], "routine")
        self.assertEqual((old["measures"]["from_level"], old["measures"]["changed_at"], old["last_change_at"]),
                         (3, "2026-11-07T11:59:59Z", "2026-11-07T11:59:59Z"))

    def test_a_stale_feed_is_withheld(self):
        fc = self.build(last_ok="2026-11-07T00:00:00Z")
        self.assertEqual(fc["features"], [])
        self.assertEqual((fc["health"]["cdc-travel-notices"]["state"], fc["health"]["cdc-travel-notices"]["withheld"]),
                         ("stale", 3))



PRN_US = ['<a href="/media/82381">Federal Aviation Administration (FAA) Flight Routing Authorization Requirements for '
          'China in United States Territorial Airspace</a>']
PRN_AF = ['<a href="/x/SFAR-119.pdf">Special Federal Aviation Regulation (<abbr>SFAR</abbr>) 119 -&nbsp;Prohibitions '
          'Against Certain Flights in the Kabul Flight Information Region (<abbr>FIR</abbr>) (<abbr>OAKX</abbr>)</a>',
          '<a href="/x/A0007-25.pdf">KICZ NOTAM A0007/25 Kabul Pointer</a>']
PRN_BY = ['<a href="media/KICZ_A0003-22.pdf"><abbr>KICZ</abbr> <abbr>NOTAM</abbr> A0003/22 \u2014 Security \u2014 United States '
          'of America Prohibition Against Certain Flights in the Minsk Flight Information Region (<abbr>FIR</abbr>) '
          '(<abbr>UMMV</abbr>)</a> <small>(</small><abbr><small>PDF</small></abbr><small>)</small>']
PRN_CO = ['<a href="/x/A0050_26_SKED.pdf">KICZ NOTAM A0050/26 Security - United States of America Advisory for '
          'Potentially Hazardous Situation in the Overwater Areas Above the Pacific Ocean in the Bogota Flight '
          'Information Region (SKED)</a>',
          '<a href="/x/Background.pdf">FAA Background Information Regarding Airspace Risks Within the Eastern Pacific '
          'Ocean Region</a>']
PRN_KP = ['<a href="/x/SFAR79.pdf">Special Federal Aviation Regulation (SFAR) 79 \u2013 Prohibition Against Certain Flights '
          'in the Pyongyang Flight Information Region (FIR) (ZKKP)</a>']
PRN_PO = ['<a href="/x/A0052_26_XX01.pdf">KICZ NOTAM A0052/26 Security - United States of America Advisory for '
          'Potentially Hazardous Situation in the Specified Portion of the No FIR Flight Information Region</a>']


def prn_page(colombia=None, drop=()):
    """A cut-down copy of the FAA page as served on 15 Nov 2026: an index and an acronyms heading with no anchor,
    then one h2 with a ck-anchor per section, and a footer list after </main>."""
    secs = [("United States", "US", PRN_US), ("Afghanistan", "Afghanistan", PRN_AF), ("Belarus", "Belarus", PRN_BY),
            ("Colombia", "colombia", PRN_CO if colombia is None else colombia), ("Korea, North", "NKorea", PRN_KP),
            ("Pacific Ocean", "pacific-ocean", PRN_PO), ("Saudi Arabia", "saudi_arabia", [])]
    secs += [(n, n, []) for n in ("Bahamas", "Canada", "Cuba", "Panama")]
    body = "".join(f'<h2 id="restrict{a}">{n}<a class="ck-anchor" id="{a}"></a></h2><ul>'
                   + "".join(f"<li>{x}</li>" for x in lis) + '</ul><p><a class="anchorUp" href="#content">Back to top</a></p>'
                   for n, a, lis in secs if n not in drop)
    return ('<main><h2>Alphabetical List by Country</h2><ul><li><a href="#US">United States</a></li></ul>'
            '<h2>The following acronyms are used to identify sources of information:</h2>' + body
            + '</main><footer><ul><li><a href="/about">About FAA</a></li></ul></footer>').encode()


class FaaPrn(unittest.TestCase):
    NOW = datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc)
    STAMP = "2026-11-15T03:00:00Z"

    def test_parse_entries_kinds_firs_and_places(self):
        s = faaprn.parse(prn_page())
        self.assertEqual(len(s), 11)
        af = s["afghanistan"]["entries"]
        self.assertEqual(sorted(af), ["KICZ-A0007-25", "SFAR-119"])
        self.assertEqual((af["SFAR-119"]["kind"], af["SFAR-119"]["label"], af["SFAR-119"]["firs"]),
                         ("prohibition", "SFAR 119", ["OAKX"]))  # "(<abbr>SFAR</abbr>) 119" read; SFAR is no FIR
        self.assertEqual(af["KICZ-A0007-25"]["kind"], "pointer")
        by = s["belarus"]["entries"]["KICZ-A0003-22"]
        self.assertEqual((by["kind"], by["firs"], by["url"]),
                         ("prohibition", ["UMMV"], faaprn.PAGE_URL + "/media/KICZ_A0003-22.pdf"))
        co = s["colombia"]
        self.assertEqual((co["entries"]["KICZ-A0050-26"]["kind"], co["entries"]["KICZ-A0050-26"]["firs"]),
                         ("advisory", ["SKED"]))
        self.assertEqual(co["background"][0]["url"], "https://www.faa.gov/x/Background.pdf")
        self.assertEqual((s["korea-north"]["iso"], s["pacific-ocean"]["iso"], s["colombia"]["iso"]), ("KP", None, "CO"))
        self.assertEqual((s["united-states"]["entries"], s["united-states"]["other"]), ({}, 1))
        self.assertEqual(s["panama"]["other"], 0, "the footer after </main> is not part of the last section")
        self.assertEqual(faaprn.summary(s), "5 of 11 sections with an SFAR or KICZ NOTAM: 2 SFARs, 4 KICZ NOTAMs; "
                                            "3 prohibitions, 2 advisories, 1 pointers")

    def test_collect_logs_entries_listed_and_withdrawn(self):
        first, ch, err = faaprn.collect(None, self.STAMP, lambda u, t=40: (prn_page(), None))
        self.assertEqual((ch, err), ([], None))
        co = [PRN_CO[0].replace("A0050/26", "A0060/26").replace("A0050_26", "A0060_26"), PRN_CO[1]]
        _, ch, err = faaprn.collect(first, self.STAMP, lambda u, t=40: (prn_page(colombia=co, drop=("Belarus",)), None))
        self.assertIsNone(err)
        self.assertEqual(sorted((c["section"], c["key"], c["kind"], c["entry_kind"]) for c in ch),
                         [("belarus", "KICZ-A0003-22", "removed", "prohibition"),
                          ("colombia", "KICZ-A0050-26", "removed", "advisory"),
                          ("colombia", "KICZ-A0060-26", "new", "advisory")])
        new = next(c for c in ch if c["kind"] == "new")
        self.assertEqual((new["iso"], new["name"], new["link"]), ("CO", "Colombia", faaprn.PAGE_URL + "#colombia"))
        few = prn_page(drop=("Bahamas", "Canada", "Cuba"))
        self.assertIn("only 8 sections", faaprn.collect(first, self.STAMP, lambda u, t=40: (few, None))[2])
        self.assertIs(faaprn.collect(first, self.STAMP, lambda u, t=40: (None, "HTTP 503"))[0], first)

    def build(self, changes=(), last_ok=None):
        h = {"faa-prohibitions-notices": {"last_ok": last_ok or self.STAMP, "failures": 0, "checked_at": self.STAMP}}
        prn = {"sections": faaprn.parse(prn_page()), "fetched_at": self.STAMP}
        with unittest.mock.patch.object(feed, "recent_changes", lambda now: list(changes)):
            return feed.build({}, {}, {}, {}, self.NOW, h, prn=prn)

    def test_items_titles_tiers_and_places(self):
        changes = [{"at": "2026-11-14T10:00:00Z", "lane": "faaprn", "kind": "new", "section": "colombia",
                    "key": "KICZ-A0050-26", "label": "KICZ NOTAM A0050/26", "entry_kind": "advisory", "name": "Colombia",
                    "iso": "CO", "link": faaprn.PAGE_URL + "#colombia", "from": None, "to": "advisory"}]
        fc = self.build(changes)
        self.assertEqual(fc["dropped"], [])
        items = {f["properties"]["id"]: f for f in fc["features"]}
        self.assertEqual(sorted(items), ["cordon:faaprn:afghanistan", "cordon:faaprn:belarus", "cordon:faaprn:colombia",
                                         "cordon:faaprn:korea-north", "cordon:faaprn:pacific-ocean"])
        af = items["cordon:faaprn:afghanistan"]
        self.assertEqual(af["properties"]["title"], "FAA, Afghanistan: US flight prohibition (SFAR 119, KICZ NOTAM A0007/25)")
        self.assertEqual((af["properties"]["tier"], af["properties"]["countries"], af["geometry"]["type"]),
                         ("routine", ["AF"], "Point"))
        co = items["cordon:faaprn:colombia"]["properties"]
        self.assertEqual((co["tier"], co["measures"]["added"], co["measures"]["new"], co["baseline_ref"]["id"]),
                         ("anomaly", ["KICZ NOTAM A0050/26"], True, "previous-faa-prohibitions"))
        self.assertTrue(co["title"].startswith("FAA, Colombia: US advisory for potentially hazardous airspace"))
        po = items["cordon:faaprn:pacific-ocean"]
        self.assertEqual((po["geometry"], po["properties"]["countries"], po["properties"]["precision_class"],
                          po["properties"]["visual"]["url"]), (None, [], "none", faaprn.PAGE_URL + "#pacific-ocean"))
        self.assertEqual(fc["health"]["faa-prohibitions-notices"]["state"], "fresh")

    def test_a_stale_page_is_withheld(self):
        fc = self.build(last_ok="2026-11-12T00:00:00Z")
        self.assertEqual(fc["features"], [])
        self.assertEqual((fc["health"]["faa-prohibitions-notices"]["state"],
                          fc["health"]["faa-prohibitions-notices"]["withheld"]), ("stale", 5))

    def test_verdict_event_for_a_listed_notice(self):
        from cordon import events
        c = {"at": "2026-11-14T10:00:00Z", "lane": "faaprn", "kind": "new", "section": "colombia",
             "key": "KICZ-A0050-26", "label": "KICZ NOTAM A0050/26", "entry_kind": "advisory", "name": "Colombia",
             "iso": "CO", "link": faaprn.PAGE_URL + "#colombia", "from": None, "to": "advisory"}
        ev = events.build([], [c], self.NOW)["events"]
        self.assertEqual([(e["id"], e["title"], e["countries"], e["source"]["publisher"]) for e in ev],
                         [("2026-11-14-faaprn-kicz-a0050-26-new",
                           "Colombia: FAA listed KICZ NOTAM A0050/26 (advisory) for US operators", ["CO"],
                           "US Federal Aviation Administration (FAA)")])


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

    def test_travel_advice_lanes_and_canada_declared_changes(self):
        from cordon import events
        now = datetime(2026, 11, 15, 1, tzinfo=timezone.utc)
        ab, ap = "avoid_all_but_essential_travel_to_parts", "avoid_all_travel_to_parts"
        changes = [
            {"lane": "fcdo", "kind": "alert", "at": "2026-11-10T03:00:00Z", "key": "mexico", "iso": "MX",
             "name": "Mexico", "link": LINK, "from": [ab], "to": [ap, ab], "change": "Updated advice"},
            {"lane": "fcdo", "kind": "alert", "at": "2026-10-01T00:00:00Z", "key": "chad", "iso": "TD",
             "name": "Chad", "from": [], "to": [ab]},  # older than 30 days
            {"lane": "canada", "kind": "regional", "at": "2026-11-03T18:10:00Z", "key": "NP", "iso": "NP",
             "name": "Nepal", "link": LINK, "from": False, "to": True,
             "change": "Risk levels section \u2013 avoid non-essential travel to parts of the Trishuli River corridor; "
                       "Natural disasters"},
            {"lane": "canada", "kind": "level", "at": "2026-11-08T05:00:00Z", "key": "PT-20", "iso": "PT",
             "name": "Azores", "link": LINK, "from": 0, "to": 1, "change": None},
            {"lane": "safetravel", "kind": "level", "at": "2026-11-12T09:00:00Z", "key": "HT", "iso": "HT",
             "name": "Haiti", "link": LINK, "from": "high", "to": "medium"},
            {"lane": "safetravel", "kind": "level", "at": "2026-11-12T21:00:00Z", "key": "HT", "iso": "HT",
             "name": "Haiti", "link": LINK, "from": "medium", "to": "avoid"},  # same day: the later wins
            {"lane": "safetravel", "kind": "regional", "at": "2026-11-13T09:00:00Z", "key": "BO",
             "iso": "BO", "name": "Bolivia", "link": LINK, "from": None,
             "to": "with higher advice levels in some areas"},
            {"lane": "cdc", "kind": "new", "at": "2026-11-11T13:00:00Z", "key": "measles-global",
             "name": "Global Measles", "link": LINK, "countries": ["US", "CA"], "from": None, "to": 1},
            {"lane": "cdc", "kind": "removed", "at": "2026-11-12T13:00:00Z", "key": "polio-global",
             "name": "Global Polio", "link": LINK, "countries": ["PK"], "from": 2, "to": None},
            {"lane": "cdc", "kind": "text", "at": "2026-11-12T13:00:00Z", "key": "x", "name": "X"},
        ]
        places = {
            "JP": {"key": "JP", "iso": "JP", "name": "Japan", "link": LINK, "updated": "2026-10-26T14:39:17Z",
                   "update_type": "Regional advisory removed",
                   "update": "Risk levels section \u2013 removed advisory to avoid non-essential travel to the Ryukyu "
                             "Islands; Natural disaster"},
            "ET": {"key": "ET", "iso": "ET", "name": "Ethiopia", "link": LINK, "updated": "2026-10-29T19:40:16Z",
                   "update_type": "Regular text update", "update": "Risk level \u2013 updated information"},
            "NP": {"key": "NP", "iso": "NP", "name": "Nepal", "link": LINK, "updated": "2026-11-03T16:56:03Z",
                   "update_type": "Regional advisory modified", "update": "Risk levels section \u2013 avoid ..."},
            "MX": {"key": "MX", "iso": "MX", "name": "Mexico", "link": LINK, "updated": "2026-11-12T12:31:31Z",
                   "update_type": "Regular text update",
                   "update": "Risk levels section \u2013 removed advisory to avoid non-essential travel to the "
                             "west-central coast; Natural disasters and climate"},
            "BR": {"key": "BR", "iso": "BR", "name": "Brazil", "link": LINK, "updated": "2026-09-30T00:00:00Z",
                   "update_type": "Regional advisory modified", "update": "Risk levels section"},  # too old
        }
        ev = events.build([], changes, now, canada=places)["events"]
        by = {e["id"]: e for e in ev}
        self.assertEqual(sorted(by), sorted([
            "2026-10-26-canada-jp-update", "2026-11-03-canada-np-regional", "2026-11-08-canada-pt-20-level",
            "2026-11-10-fcdo-mexico-alert", "2026-11-11-cdc-measles-global-new", "2026-11-12-canada-mx-update",
            "2026-11-12-cdc-polio-global-removed", "2026-11-12-safetravel-ht-level",
            "2026-11-13-safetravel-bo-regional"]))
        self.assertTrue(all(e["kind"] == "advisory_change" and e["occurred"] and e["source"]["url"] for e in ev))
        self.assertEqual(by["2026-11-10-fcdo-mexico-alert"]["title"],
                         'Mexico: UK FCDO advice changed from "advises against all but essential travel to parts" to '
                         '"advises against all travel to parts and all but essential travel to parts"')
        self.assertIn("(Canada's note: Risk levels section \u2013 avoid non-essential travel to parts of the Trishuli "
                      "River corridor)", by["2026-11-03-canada-np-regional"]["title"])
        self.assertIn('raised from "Exercise normal security precautions" to "Exercise a high degree of caution"',
                      by["2026-11-08-canada-pt-20-level"]["title"])
        self.assertEqual(by["2026-11-08-canada-pt-20-level"]["countries"], ["PT"])
        self.assertIn('raised from "Exercise increased caution" to "Do not travel"',
                      by["2026-11-12-safetravel-ht-level"]["title"])
        self.assertIn("added a note on other levels", by["2026-11-13-safetravel-bo-regional"]["title"])
        self.assertEqual(by["2026-11-11-cdc-measles-global-new"]["countries"], ["US", "CA"])
        self.assertIn("CDC removed its level 2 travel health notice", by["2026-11-12-cdc-polio-global-removed"]["title"])
        self.assertEqual(by["2026-11-12-canada-mx-update"]["title"],
                         "Mexico: Canada's travel advice: Risk levels section \u2013 removed advisory to avoid "
                         "non-essential travel to the west-central coast")
        self.assertIn("Canada's travel advice, Regional advisory removed: ", by["2026-10-26-canada-jp-update"]["title"])
        self.assertEqual(by["2026-10-26-canada-jp-update"]["date"], "2026-10-26")
        self.assertFalse(canada.names_advisory_change(places["ET"]), "a risk-level note naming no advisory")
        self.assertTrue(canada.declares_change(places["ET"]), "the feed's looser rule is unchanged")


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


class Rev21(unittest.TestCase):
    """Feed contract revision 2.1 (kit 0.6.2): subjects, change flags, event times and the rest (18 Nov 2026)."""
    NOW = datetime(2026, 11, 18, 21, 40, tzinfo=timezone.utc)
    STAMP = "2026-11-18T21:40:00Z"

    def test_the_date_is_cut_from_alert_titles_in_every_form_seen(self):
        cut = rev21.cut_date
        self.assertEqual(cut("Security Alert – U.S. Embassy Jerusalem – November 18, 2026"),
                         "Security Alert – U.S. Embassy Jerusalem")
        self.assertEqual(cut("Health Alert: U.S. Embassy Abuja, Nigeria (October 27, 2026)"),
                         "Health Alert: U.S. Embassy Abuja, Nigeria")
        self.assertEqual(cut("Security Alert: U.S. Embassy Beirut: October 28, 2026"), "Security Alert: U.S. Embassy Beirut")
        self.assertEqual(cut("Demonstration Alert (November 11–16, 2026)"), "Demonstration Alert")
        self.assertEqual(cut("Security Alert (November 4, 2026"), "Security Alert")  # the unclosed bracket seen live
        self.assertEqual(cut("Security Alert - U.S. Embassy Abu Dhabi - https://ae.usembassy.gov/"),
                         "Security Alert - U.S. Embassy Abu Dhabi")
        self.assertEqual(cut("Security Alert: October 28, 2026 – Mission Nigeria"), "Security Alert: Mission Nigeria")
        # Kept: a date inside the headline. A month with no day in brackets at the end is the post's date.
        self.assertEqual(cut("Security Alert: Protests on Friday, October 30 in Mexico City"),
                         "Security Alert: Protests on Friday, October 30 in Mexico City")
        self.assertEqual(cut("ASEAN Summit Disruptions in Metro Manila (November 2026)"),
                         "ASEAN Summit Disruptions in Metro Manila")
        # Punctuation folded: a dash or a colon after "Alert" is one subject; the country keeps them apart.
        a = rev21.alert_subject("ET", "Security Alert – U.S. Embassy Addis Ababa, Ethiopia (November 12, 2026)")
        b = rev21.alert_subject("ET", "Security Alert: U.S. Embassy Addis Ababa, Ethiopia – November 17, 2026")
        self.assertEqual(a, b)
        self.assertRegex(a, r"^cordon:alert:ET:[0-9a-f]{12}$")
        self.assertNotEqual(a, rev21.alert_subject("KE", "Security Alert: U.S. Embassy Addis Ababa, Ethiopia"))

    def alerts(self, posts):
        return feed.build({"advisories": {}, "fetched_at": self.STAMP}, {"posts": posts, "fetched_at": self.STAMP},
                          {"bulletins": [], "fetched_at": self.STAMP}, {"warnings": [], "fetched_at": self.STAMP},
                          self.NOW)

    def post(self, title, day, n):
        return {"iso": "IL", "title": title, "link": f"https://il.usembassy.gov/alert-{n}/",
                "published_at": f"2026-11-{day:02d}T12:00:00Z", "type": "security"}

    def test_one_item_per_alert_subject_the_newest_post_with_the_earlier_ones(self):
        posts = {"IL": [self.post("Security Alert – U.S. Embassy Jerusalem – November 6, 2026", 6, 1),
                        self.post("Security Alert: U.S. Embassy Jerusalem (November 12, 2026)", 12, 2),
                        self.post("Security Alert – U.S. Embassy Jerusalem – November 9, 2026", 9, 3),
                        self.post("Demonstration Alert: Tel Aviv", 10, 4)]}
        fc = self.alerts(posts)
        items = [f["properties"] for f in fc["features"] if f["properties"]["id"].startswith("cordon:alert:")]
        self.assertEqual(len(items), 2)
        p = next(i for i in items if "Jerusalem" in i["title"])
        self.assertEqual(p["id"], f"cordon:alert:IL:{digest('https://il.usembassy.gov/alert-2/')[7:19]}")
        self.assertEqual(p["subject_id"], rev21.alert_subject("IL", "Security Alert – U.S. Embassy Jerusalem"))
        self.assertEqual([e["link"] for e in p["measures"]["earlier"]],
                         ["https://il.usembassy.gov/alert-3/", "https://il.usembassy.gov/alert-1/"])
        self.assertEqual((p["last_change"], p["last_change_at"], p["event_start"]),
                         ("changed", "2026-11-12T12:00:00Z", "2026-11-12T12:00:00Z"))
        c = p["corroboration"]
        self.assertEqual((c["state"], c["basis"], c["official"], c["origins"], c["first_reported_at"]),
                         ("corroborated", "official", "usembassy-il", 1, "2026-11-06T12:00:00Z"))
        self.assertEqual((p["place_basis"], p["sources"][0]["lane"], p["sources"][0]["grade"]),
                         ("location", "us-embassy-alerts", "A2"))
        lone = next(i for i in items if "Tel Aviv" in i["title"])
        self.assertEqual((lone["last_change"], "earlier" in lone["measures"]), ("new", False))
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([x for x in contract.check(f, regs, rev="2.1") if x[1] == "error"], [])

    def test_a_reissue_takes_the_subject_of_the_tfr_it_replaced_once_that_one_has_left(self):
        t = Tfr()
        geom = Tfr.square(-157.77, 21.45, 0.1)
        old = t.rec("6/10", "SECURITY", "HI", geom, issued="2026-11-10T00:00:00Z")
        new = t.rec("6/11", "SECURITY", "HI", geom, issued="2026-11-14T10:00:00Z")
        split = t.rec("6/12", "SECURITY", "HI", geom, issued="2026-11-14T10:30:00Z")
        gone = tfr.remember({"6/10": old}, {"6/11": new, "6/12": split}, {}, "2026-11-14T11:00:00Z")
        # The first re-issue of a split takes the subject; the second keeps its own; both are stamped for good.
        self.assertEqual((new["subject"], split["subject"]), ("6/10", "6/12"))
        self.assertIsNone(gone["6/10"].get("subject"))
        # A chain: a re-issue follows the newest TFR it matches. After 6/11 and 6/12 both leave, 6/13 follows 6/12
        # (the newer) and its subject; when 6/11 is the newer match, 6/13 carries 6/11's subject on, 6/10's.
        nxt = t.rec("6/13", "SECURITY", "HI", geom, issued="2026-11-15T10:00:00Z")
        gone = tfr.remember({"6/11": new, "6/12": split}, {"6/13": nxt}, gone, "2026-11-15T11:00:00Z")
        self.assertEqual(nxt["subject"], "6/12")
        nxt = t.rec("6/13", "SECURITY", "HI", geom, issued="2026-11-15T10:00:00Z")
        split_gone = {**gone, "6/12": {**gone["6/12"], "first_seen": "2026-11-13T00:00:00Z"}}
        gone = tfr.remember({"6/11": new}, {"6/13": nxt}, split_gone, "2026-11-15T11:00:00Z")
        self.assertEqual((gone["6/11"]["subject"], nxt["subject"]), ("6/10", "6/10"))
        # Listed alongside its predecessor: two restrictions in force, two subjects.
        twin = t.rec("6/14", "SECURITY", "HI", geom, issued="2026-11-15T12:00:00Z")
        tfr.remember({"6/13": nxt}, {"6/13": nxt, "6/14": twin}, gone, "2026-11-15T13:00:00Z")
        self.assertEqual(twin["subject"], "6/14")
        # Stamps survive the next read of the FAA's list.
        self.assertEqual(tfr.memory_entry(nxt, "x")["subject"], "6/10")
        # A data file from before 2.1 (nothing stamped) gets what the stamp would give, without being changed.
        bare = {"6/13": {k: v for k, v in nxt.items() if k != "subject"}}
        bare_gone = {k: {x: v for x, v in r.items() if x != "subject"} for k, r in gone.items()}
        self.assertEqual(tfr.subjects(bare, bare_gone), {"6/13": "6/11"})
        self.assertNotIn("subject", bare["6/13"])
        data = {"tfrs": {"6/13": nxt, "6/14": twin}, "gone": gone, "fetched_at": "2026-11-15T13:00:00Z"}
        items = {f["properties"]["id"]: f["properties"]
                 for f in feed.tfr_items(data, datetime(2026, 11, 15, 13, tzinfo=timezone.utc))[0]}
        p = items["cordon:tfr:6-13"]
        self.assertEqual((p["subject_id"], p["last_change"], p["last_change_at"]),
                         ("cordon:tfr:6-10", "changed", "2026-11-15T10:00:00Z"))
        self.assertEqual((p["event_start"], p["event_end"]), ("2026-11-14T10:00:00Z", "2026-11-16T10:00:00Z"))
        self.assertEqual((items["cordon:tfr:6-14"]["subject_id"], items["cordon:tfr:6-14"]["last_change"]),
                         ("cordon:tfr:6-14", "new"))

    def test_an_airport_program_is_one_subject_whatever_its_start(self):
        f = Faa()
        a = f.items(f.build([gs("ORD", 41.98, -87.90)]))
        b = f.items(f.build([gs("ORD", 41.98, -87.90, start="2026-11-13T22:00:00Z")]))
        (ia, pa), (ib, pb) = next(iter(a.items())), next(iter(b.items()))
        self.assertNotEqual(ia, ib)
        self.assertEqual(pa["properties"]["subject_id"], "cordon:faa:ground_stop:ORD")
        self.assertEqual(pa["properties"]["subject_id"], pb["properties"]["subject_id"])
        self.assertEqual((pa["properties"]["event_start"], pa["properties"]["event_end"]),
                         ("2026-11-13T21:00:00Z", "2026-11-13T23:00:00Z"))
        self.assertEqual(pa["properties"]["place_basis"], "location")

    def test_the_built_feed_states_revision_2_1_and_lints_clean(self):
        recs = state.parse(STATE)
        fc = feed.build({"advisories": recs, "fetched_at": "2026-10-31T21:00:00Z"},
                        {"posts": {"SA": embassy.parse_rss(RSS, "SA")}, "fetched_at": "2026-10-31T21:00:00Z"},
                        {"bulletins": easa.parse(EASA_CSV), "fetched_at": "2026-10-31T21:00:00Z"},
                        {"warnings": navarea.parse(NGA), "fetched_at": "2026-10-31T20:55:00Z"},
                        datetime(2026, 10, 31, 21, 1, tzinfo=timezone.utc))
        self.assertEqual((fc["contract_rev"], fc["kit"], fc["generated_at"]), ("2.1", "0.6.12", "2026-10-31T21:01:00Z"))
        self.assertEqual([p for p in contract.check_header({k: v for k, v in fc.items() if k != "features"})
                          if p[1] == "error"], [])
        props = [f["properties"] for f in fc["features"]]
        self.assertTrue(all(p["published_at"] == fc["generated_at"] and p["subject_id"] for p in props))
        self.assertTrue(all(s["grade"] == "A2" for p in props for s in p["sources"]))
        adv = next(p for p in props if p["id"] == "cordon:advisory:SA")
        self.assertEqual((adv["place_basis"], adv["signal"]["name"], adv["sea_areas"]),
                         ("subject", "State Dept advisory level 1-4", []))
        nav = [p for p in props if p["id"].startswith("cordon:navwarn:")]
        self.assertTrue(nav and all("sea_areas" in p and "event_start" in p and "place_basis" not in p for p in nav))


class RetentionC4C5(unittest.TestCase):
    def test_tfr_text_is_stored_whole_and_shown_cut(self):
        text = "TEMPORARY FLIGHT RESTRICTIONS. " * 400
        d = tfr.parse_detail(tfr_xml(text=text))
        self.assertEqual(d["text"], text.strip())
        shown = tfr.display_text(d["text"])
        self.assertEqual(len(shown) - len(shown.split(" [Cut by Cordon")[0]), len(f" [Cut by Cordon: {len(d['text']) - tfr.TEXT_MAX} more characters in the FAA's text]"))
        self.assertEqual(tfr.display_text("short"), "short")

    def test_dropped_items_are_appended_once(self):
        import tempfile
        from cordon import dropped as dropped_store
        path = Path(tempfile.mkdtemp()) / "history" / "dropped.jsonl"
        item = {"type": "Feature", "properties": {"id": "cordon:x:1", "title": "a body"}}
        drop = [{"id": "cordon:x:1", "errors": ["bad"]}]
        first = dropped_store.append(path, drop, {"cordon:x:1": item}, "2026-11-18T10:00:00Z")
        self.assertEqual(len(first), 1)
        self.assertEqual(dropped_store.append(path, drop, {"cordon:x:1": item}, "2026-11-18T11:00:00Z"), [])
        changed = {"type": "Feature", "properties": {"id": "cordon:x:1", "title": "edited"}}
        self.assertEqual(len(dropped_store.append(path, drop, {"cordon:x:1": changed}, "2026-11-18T12:00:00Z")), 1)
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["item"]["properties"]["title"] for r in rows], ["a body", "edited"])
        self.assertEqual(rows[0]["errors"], ["bad"])

    def test_feed_build_logs_what_the_linter_drops_and_the_feed_is_unchanged(self):
        import tempfile
        args = ({"advisories": state.parse(STATE), "fetched_at": "2026-10-31T21:00:00Z"},
                {"posts": {"SA": embassy.parse_rss(RSS, "SA")}, "fetched_at": "2026-10-31T21:00:00Z"},
                {"bulletins": easa.parse(EASA_CSV), "fetched_at": "2026-10-31T21:00:00Z"},
                {"warnings": navarea.parse(NGA), "fetched_at": "2026-10-31T21:00:00Z"},
                datetime(2026, 10, 31, 21, tzinfo=timezone.utc))
        plain = feed.build(*args)
        victim = plain["features"][0]["properties"]["id"]
        real = contract.check
        fake = lambda f, regs, **kw: ([("x", "error", "forced")] if f["properties"]["id"] == victim else real(f, regs, **kw))
        path = Path(tempfile.mkdtemp()) / "dropped.jsonl"
        with unittest.mock.patch.object(contract, "check", fake):
            fc = feed.build(*args, dropped_log=path)
            feed.build(*args, dropped_log=path)   # a second run writes nothing new
        self.assertEqual([x["id"] for x in fc["dropped"]], [victim])
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["item"]["properties"]["id"], victim)
        self.assertEqual(len(plain["features"]), len(fc["features"]) + 1)
        self.assertEqual(plain["features"][1:], fc["features"])


if __name__ == "__main__":
    unittest.main()
