"""Offline tests for the Japan (MOFA open data) and Netherlands (Nederland Wereldwijd) travel advice lanes. Fixtures copy
the live formats read on 25 Nov 2026. Run as a plain script or with unittest."""
import json
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cordon import events, feed, japan, netherlands  # noqa: E402
from cordon.common import country_name  # noqa: E402
from tic_doctrine import contract, registers  # noqa: E402

NOW = datetime(2026, 11, 25, 19, 30, tzinfo=timezone.utc)
STAMP = "2026-11-25T19:30:00Z"


# ---- Japan -------------------------------------------------------------------------------------------------------
def mail(key, typ, leave, code, title, lead="lead", mission="在リヨン領事事務所", name="フランス"):
    ctry = (f'<country areaCd="42"><cd>{code}</cd><name>{name}</name></country><area><cd>42</cd><name>x</name></area>'
            if code else "")
    return (f"<mail><keyCd>{key}</keyCd><infoType>{typ}</infoType><leaveDate>{leave}</leaveDate>{ctry}"
            f"<title>{title}</title><lead>{lead}</lead>"
            f"<infoUrl>https://www.anzen.mofa.go.jp/od/ryojiMailDetail.html?keyCd={key}</infoUrl>"
            f"<koukanName>{mission}</koukanName></mail>")


def listing(mails, modified="2026/11/26 04:20:00"):
    return (f'<?xml version="1.0" encoding="UTF-8"?><opendata dataType="N" lastModified="{modified}" '
            f'mailCount="{len(mails)}" odType="02">' + "".join(mails) + "</opendata>").encode("utf-8")


def country_file(code, levels=(), title=None, key="2026T099", at="2026/11/16 00:00:00", infection=()):
    flags = "".join(f"<riskLevel{n}>{1 if n in levels else 0}</riskLevel{n}>" for n in (1, 2, 3, 4))
    flags += "".join(f"<infectionLevel{n}>{1 if n in infection else 0}</infectionLevel{n}>" for n in (1, 2, 3, 4))
    risk = (f'<riskLeaveDate keyCd="{key}">{at}</riskLeaveDate><riskTitle>{title}</riskTitle><riskLead>本文</riskLead>'
            f"<riskUrl>https://www.anzen.mofa.go.jp/info/pchazardspecificinfo_{key}.html</riskUrl>") if title else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><opendata dataType="L" lastModified="2026/11/26 04:00:53" '
            f'mailCount="0" odType="04"><area><cd>10</cd></area><country areaCd="10" countryCd="1"><cd>{code}</cd></country>'
            f"<infoUrl>https://www.anzen.mofa.go.jp/od/ryojiMail.html?countryCd=001</infoUrl>{flags}{risk}</opendata>"
            ).encode("utf-8")


LISTING = listing([
    mail("169220", "R10", "2026/11/26 02:51:05", "0033", "11月26日のデモ等に関する注意喚起"),
    mail("169214", "R10", "2026/11/26 00:01:15", "", "（注意喚起）マサチューセッツ州ノーウッドにおける発砲事件の発生について"),
    mail("169200", "R10", "2026/11/25 15:51:03", "0966", "ホーシー派の攻撃予告（紅海沿岸の港）に関する注意喚起",
         name="サウジアラビア"),
    mail("169100", "R20", "2026/11/20 10:00:00", "0033", "old urgent mail"),  # older than 72 hours
])


class JapanParse(unittest.TestCase):
    def test_japan_time_is_read_as_utc_plus_nine(self):
        self.assertEqual(japan.jst_to_utc("2026/11/26 02:51:05"), "2026-11-25T17:51:05Z")
        self.assertEqual(japan.jst_to_utc("2026/11/16 00:00:00"), "2026-11-15T15:00:00Z")
        self.assertIsNone(japan.jst_to_utc("26 Nov 2026"))

    def test_listing(self):
        got, at = japan.parse_listing(LISTING)
        self.assertEqual(at, "2026-11-25T19:20:00Z")
        self.assertEqual(sorted(got), ["169100", "169200", "169214", "169220"])
        a = got["169220"]
        self.assertEqual((a["iso"], a["type"], a["at"], a["title_ja"], a["mission_ja"]),
                         ("FR", "R10", "2026-11-25T17:51:05Z", "11月26日のデモ等に関する注意喚起", "在リヨン領事事務所"))
        self.assertIsNone(got["169214"]["iso"], "a notice with no country code is held, not placed")
        self.assertEqual(got["169200"]["iso"], "SA")

    def test_a_maintenance_page_is_not_a_listing(self):
        with self.assertRaises(ValueError):
            japan.parse_listing("<html><body>メンテナンス中</body></html>".encode("utf-8"))
        with self.assertRaises(ValueError):
            japan.parse_listing(b"<other/>")

    def test_country_levels(self):
        r = japan.parse_country(country_file("0091", (1, 2, 3, 4), "インドの危険情報【一部地域の危険レベル引下げ】"))
        self.assertEqual((r["levels"], r["max_level"], r["risk_key"], r["risk_at"]),
                         ([1, 2, 3, 4], 4, "2026T099", "2026-11-15T15:00:00Z"))
        self.assertEqual(japan.declared_move(r), "lowered")
        none = japan.parse_country(country_file("0033"))
        self.assertEqual((none["levels"], none["max_level"], none["risk_title_ja"]), ([], 0, None))
        self.assertIsNone(japan.declared_move({"risk_title_ja": "ウクライナの危険情報【危険レベル継続】（内容の更新）"}))
        self.assertEqual(japan.declared_move({"risk_title_ja": "サウジアラビアの危険情報【一部地域の危険レベル引上げ】"}), "raised")
        with self.assertRaises(ValueError):
            japan.parse_country(LISTING)

    def test_every_ministry_code_has_one_iso_code_and_an_english_name(self):
        self.assertEqual(len(japan.COUNTRIES), len(japan.BY_ISO), "two ministry codes share an ISO code")
        for code, iso in japan.COUNTRIES.items():
            self.assertRegex(iso, r"^[A-Z]{2}$")
            self.assertNotEqual(country_name(iso), iso, f"{code}: no English name for {iso}")

    def test_the_diff_reads_the_highest_level_then_the_levels_in_some_areas(self):
        def rec(levels, name="x"):
            return {"iso": "ML", "name_ja": name, "levels": levels, "max_level": max(levels, default=0),
                    "link": "https://www.anzen.mofa.go.jp/x"}
        old = {"ML": rec([3]), "AF": rec([4]), "UA": rec([2, 4])}
        new = {"ML": rec([4]), "AF": rec([4]), "UA": rec([4]), "NEW": rec([2])}
        old["AF"]["iso"] = new["AF"]["iso"] = "AF"
        old["UA"]["iso"] = new["UA"]["iso"] = "UA"
        new["NEW"]["iso"] = "KE"
        got = {(c["key"], c["kind"]): (c["from"], c["to"]) for c in japan.diff(old, new, STAMP)}
        self.assertEqual(got, {("ML", "level"): (3, 4), ("UA", "regional"): ([2, 4], [4])})


class JapanCollect(unittest.TestCase):
    def fetcher(self, calls, listing_body=LISTING, levels=None):
        levels = levels or {}

        def fetch(url, timeout=40):
            calls.append(url)
            if url == japan.NEW_URL:
                return listing_body, None
            code = url.rsplit("/", 1)[-1][:4]
            lv, title = levels.get(code, ((), None))
            return country_file(code, lv, title), None
        return fetch

    def test_the_first_run_reads_every_country_then_only_what_changed(self):
        calls = []
        held, changes, err, read, failed = japan.collect(None, STAMP, self.fetcher(calls), pause=0)
        self.assertEqual((err, read, failed, changes), (None, japan.READABLE, 0, []))
        self.assertEqual(len(calls), 1 + japan.READABLE)
        self.assertEqual(sorted(held["countries"]), sorted(i for c, i in japan.COUNTRIES.items() if c not in japan.NO_FILE))
        self.assertEqual(sorted(held["notices"]), ["169100", "169200", "169214", "169220"])
        self.assertEqual(held["countries"]["FR"]["name_ja"], "フランス")
        # Second run: a newer danger notice for Mali, and Mali's level has risen from 3 to 4.
        held["countries"]["ML"].update({"levels": [3], "max_level": 3})
        danger = listing([mail("169300", "T40", "2026/11/26 04:50:00", "0223", "マリの危険情報【危険レベル引上げ】", name="マリ"),
                          mail("169301", "R10", "2026/11/26 04:51:00", "0033", "a"), mail("169302", "R10", "2026/11/26 04:52:00", "0033", "b")],
                         modified="2026/11/26 04:55:00")
        calls2 = []
        later = "2026-11-25T19:56:00Z"
        held2, changes, err, read, failed = japan.collect(
            held, later, self.fetcher(calls2, danger, {"0223": ((4,), "マリの危険情報【危険レベル引上げ】")}), pause=0)
        self.assertEqual(err, None)
        self.assertEqual(read, len(calls2) - 1)
        self.assertIn(japan.COUNTRY_URL.format(code="0223"), calls2)
        self.assertTrue(japan.READ_BATCH <= read <= japan.READ_BATCH + 1, "the new danger notice and the hour's rotation")
        self.assertEqual(len({c for h in range(24) for c in japan.rotation(f"2026-11-25T{h:02d}:00:00Z")}), japan.READABLE,
                         "a day of hourly runs reads every country")
        self.assertEqual([(c["key"], c["kind"], c["from"], c["to"]) for c in changes], [("ML", "level", 3, 4)])
        self.assertEqual(held2["countries"]["ML"]["max_level"], 4)

    def test_a_bad_listing_keeps_the_old_data(self):
        kept = {"notices": {}, "countries": {"FR": {}}}
        err = lambda body: japan.collect(kept, STAMP, lambda u, t=40: (body, None), pause=0)  # noqa: E731
        self.assertIs(err(b"<html>maintenance</html>")[0], kept)
        self.assertIn("unreadable", err(b"<html>maintenance</html>")[2])
        self.assertIn("only 1 notices", japan.collect(
            kept, STAMP, lambda u, t=40: (listing([mail("1", "R10", "2026/11/26 02:51:05", "0033", "t")]), None),
            pause=0)[2])
        frozen = listing([mail(str(i), "R10", "2026/11/26 02:51:05", "0033", "t") for i in range(5)],
                         modified="2026/11/25 04:00:00")
        self.assertIn("frozen", japan.collect(kept, STAMP, lambda u, t=40: (frozen, None), pause=0)[2])
        self.assertIs(japan.collect(kept, STAMP, lambda u, t=40: (None, "HTTP 503"), pause=0)[0], kept)

    def test_a_country_file_that_fails_keeps_the_earlier_reading(self):
        def fetch(url, timeout=40):
            return (LISTING, None) if url == japan.NEW_URL else (None, "HTTP 500")
        held, changes, err, read, failed = japan.collect(None, STAMP, fetch, pause=0)
        self.assertEqual((err, read, failed), (None, 0, japan.READABLE))
        self.assertEqual(held["countries"], {})

    def test_every_notice_is_archived_before_the_prune(self):
        # japan.json keeps 14 days of notices; a notice naming no country reaches no other file, so the archive is
        # its only lasting copy.
        old_notice = {"key": "160000", "type": "R10", "at": "2026-11-01T00:00:00Z", "code": None, "iso": None,
                      "name_ja": None, "title_ja": "古い領事メール", "lead_ja": "本文", "link": japan.INDEX_URL,
                      "mission_ja": "在ニューヨーク日本国総領事館"}
        old = {"notices": {"160000": old_notice}, "countries": {}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / japan.ARCHIVE
            arch = lambda ns: japan.archive_notices(path, ns, STAMP)  # noqa: E731
            held = japan.collect(old, STAMP, self.fetcher([]), pause=0, archive=arch)[0]
            self.assertNotIn("160000", held["notices"], "over 14 days: out of japan.json")
            rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(sorted(r["key"] for r in rows), ["160000", "169100", "169200", "169214", "169220"])
            self.assertEqual(next(r for r in rows if r["key"] == "160000")["notice"], old_notice)
            # Run again: nothing is written twice; a notice whose text changed is written again.
            japan.collect(held, STAMP, self.fetcher([]), pause=0, archive=arch)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 5)
            changed = listing([mail("169220", "R10", "2026/11/26 02:51:05", "0033", "訂正版"),
                               mail("169200", "R10", "2026/11/25 15:51:03", "0966", "x"),
                               mail("169214", "R10", "2026/11/26 00:01:15", "", "y")])
            japan.collect(held, STAMP, self.fetcher([], changed), pause=0, archive=arch)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 8)
        # No archive, or a failing one: nothing is pruned.
        self.assertIn("160000", japan.collect(old, STAMP, self.fetcher([]), pause=0)[0]["notices"])

        def broken(ns):
            raise OSError("disk full")
        self.assertIn("160000", japan.collect(old, STAMP, self.fetcher([]), pause=0,
                                              archive=broken)[0]["notices"])


class JapanFeed(unittest.TestCase):
    def countries(self):
        def c(iso, levels, title=None, at=None, name="x"):
            return {"iso": iso, "name_ja": name, "levels": levels, "max_level": max(levels, default=0),
                    "infection_levels": [], "risk_title_ja": title, "risk_lead_ja": "本文", "risk_key": "k",
                    "risk_at": at, "link": f"https://www.anzen.mofa.go.jp/info/{iso}.html"}
        return {"UA": c("UA", [4], "ウクライナの危険情報【危険レベル継続】（内容の更新）", "2026-01-18T15:00:00Z"),
                "FR": c("FR", [1]),  # level 1, no recent notice: not listed
                "IN": c("IN", [1, 2, 3, 4], "インドの危険情報【一部地域の危険レベル引下げ】", "2026-11-24T15:00:00Z"),
                "KE": c("KE", [1], "ケニアの危険情報【危険レベル継続】", "2026-11-24T15:00:00Z"),
                "SA": c("SA", [2]), "ML": c("ML", [4]), "CH": c("CH", [])}

    def build(self, data, changes=(), last_ok=None):
        h = {"jp-mofa-overseas-safety": {"last_ok": last_ok or STAMP, "failures": 0, "checked_at": STAMP}}
        with unittest.mock.patch.object(feed, "recent_changes", lambda now: list(changes)):
            return feed.build({}, {}, {}, {}, NOW, h, jp={**data, "fetched_at": STAMP})

    def data(self):
        notices, _ = japan.parse_listing(LISTING)
        return {"countries": self.countries(), "notices": notices}

    def test_levels_changes_declared_moves_and_notices(self):
        changes = [{"at": "2026-11-10T10:00:00Z", "lane": "japan", "kind": "level", "key": "ML", "from": 3, "to": 4},
                   {"at": "2026-11-11T10:00:00Z", "lane": "japan", "kind": "regional", "key": "SA", "from": [2], "to": [2, 3]}]
        fc = self.build(self.data(), changes)
        self.assertEqual(fc["dropped"], [])
        items = {f["properties"]["id"]: f["properties"] for f in fc["features"]}
        self.assertEqual(sorted(items), ["cordon:japan:IN", "cordon:japan:KE", "cordon:japan:ML", "cordon:japan:SA",
                                         "cordon:japan:UA", "cordon:japannotice:169200", "cordon:japannotice:169214".replace(
                                             "169214", "169220")])
        ua = items["cordon:japan:UA"]
        self.assertEqual((ua["title"], ua["tier"]), ("Japan, Ukraine: Level 4: Evacuate, do not travel (evacuation advisory)", "routine"))
        self.assertEqual(ua["measures"]["title_ja"], "ウクライナの危険情報【危険レベル継続】（内容の更新）")
        self.assertEqual(ua["measures"]["advice_ja"], japan.LEVELS_JA[4])
        self.assertEqual(ua["signal"]["value"], 4)
        ind = items["cordon:japan:IN"]
        self.assertEqual((ind["tier"], ind["measures"]["declared_move"], ind["last_change"]), ("anomaly", "lowered", "lowered"))
        self.assertIn("other levels apply in some areas", ind["title"])
        self.assertEqual(items["cordon:japan:KE"]["tier"], "routine", "'level continues' is not a move")
        ml = items["cordon:japan:ML"]
        self.assertEqual((ml["tier"], ml["baseline_ref"]["id"], ml["measures"]["from_advice"], ml["last_change"]),
                         ("anomaly", "previous-mofa-levels", japan.LEVELS[3], "raised"))
        sa = items["cordon:japan:SA"]
        self.assertEqual((sa["tier"], sa["measures"]["from_levels"], sa["last_change"]), ("anomaly", [2], "changed"))
        n = items["cordon:japannotice:169220"]
        self.assertEqual(n["title"], "Japan, France: consular mail (general): 11月26日のデモ等に関する注意喚起")
        self.assertEqual((n["tier"], n["data_as_of"], n["measures"]["mission_ja"]),
                         ("routine", "2026-11-25T17:51:05Z", "在リヨン領事事務所"))
        self.assertNotIn("cordon:japannotice:169214", items, "no country")
        self.assertNotIn("cordon:japannotice:169100", items, "older than 72 hours")
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([m for _, sev, m in contract.check(f, regs) if sev == "error"], [])
        self.assertIn("外務省 海外安全情報オープンデータ", fc["attribution"])
        self.assertIn("edited and processed", fc["attribution"])

    def test_a_stale_listing_is_withheld(self):
        fc = self.build(self.data(), last_ok="2026-11-25T01:00:00Z")  # 12 hours is the limit
        self.assertEqual(fc["features"], [])
        self.assertEqual(fc["health"]["jp-mofa-overseas-safety"]["state"], "stale")
        self.assertGreater(fc["health"]["jp-mofa-overseas-safety"]["withheld"], 0)

    def test_events_for_verdict(self):
        changes = [{"at": "2026-11-10T10:00:00Z", "lane": "japan", "kind": "level", "key": "ML", "iso": "ML", "name": "Mali",
                    "link": "https://www.anzen.mofa.go.jp/x", "from": 3, "to": 4},
                   {"at": "2026-11-11T10:00:00Z", "lane": "japan", "kind": "regional", "key": "SA", "iso": "SA",
                    "name": "Saudi Arabia", "link": "https://www.anzen.mofa.go.jp/y", "from": [2], "to": [2, 3]}]
        by = {e["id"]: e for e in events.build([], changes, NOW)["events"]}
        self.assertEqual(sorted(by), ["2026-11-10-japan-ml-level", "2026-11-11-japan-sa-regional"])
        self.assertIn("raised from", by["2026-11-10-japan-ml-level"]["title"])
        self.assertEqual(by["2026-11-10-japan-ml-level"]["countries"], ["ML"])
        self.assertIn("Ministry of Foreign Affairs of Japan", by["2026-11-10-japan-ml-level"]["source"]["publisher"])


# ---- Netherlands -------------------------------------------------------------------------------------------------
def doc(key, name, intro, modified="2026-10-20T10:00:00.000Z"):
    return (f"<document><id>{key}</id><type>reisadvies</type><canonical>https://www.nederlandwereldwijd.nl/reisadvies/{name.lower()}"
            f"</canonical><title><![CDATA[Reisadvies {name}]]></title><introduction><![CDATA[<h2>In het kort</h2>{intro}]]>"
            f"</introduction><location>{name}</location><locationkey>{name.lower()}</locationkey><isocode>{key}</isocode>"
            f"<lastmodified>{modified}</lastmodified></document>")


GREEN = "<p>De kleurcode van het reisadvies voor {} is groen. U kunt erheen reizen.</p>"
INTROS = {
    "UKR": "<ul><li>Rusland voert een oorlog. Lees meer onder Actueel.</li><li>De kleurcode van het reisadvies voor\n    Oekraïne is rood. Wat uw situatie ook is: reis er niet heen.</li></ul>"
           "<div>Bij een oranje of rood reisadvies passen veel Nederlandse verzekeraars de voorwaarden aan.</div>",
    "ZMB": "<p>De kleurcode van het reisadvies is oranje voor het grensgebied tussen Zambia en Congo. Lees meer onder "
           "Regionale risico’s. Voor de rest van Zambia geldt kleurcode geel. U kunt hierheen reizen.</p>",
    "SOM": "<p>De kleurcode van het reisadvies voor Somalië is rood (behalve voor de steden Hargeisa en Berbera). "
           "Voor de steden Berbera en Hargeisa geldt kleurcode oranje.</p>",
    "NLX": "<p>Er is niets over een kleur gezegd.</p>",
}


def nl_page(docs):
    return ('<?xml version="1.0" encoding="UTF-8"?><documents>' + "".join(docs) + "</documents>").encode("utf-8")


def many(n, skip=()):
    keys = [k for k in sorted(netherlands.ISO) if k not in skip and "-" not in k][:n]
    return [doc(k, k.title(), GREEN.format(k)) for k in keys]


class NetherlandsParse(unittest.TestCase):
    def test_colours_are_read_from_the_sentences_that_say_kleurcode(self):
        got = {k: netherlands.colours(v) for k, v in INTROS.items()}
        self.assertEqual(got, {"UKR": ["rood"], "ZMB": ["geel", "oranje"], "SOM": ["oranje", "rood"], "NLX": []})
        self.assertIn("Oekraïne is rood", netherlands.first_sentence(INTROS["UKR"]))

    def test_documents(self):
        docs = netherlands.parse(nl_page([doc("UKR", "Oekraine", INTROS["UKR"]), doc("ZMB", "Zambia", INTROS["ZMB"]),
                                          doc("BQ-BO", "Bonaire", GREEN.format("Bonaire"))]))
        by = {d["key"]: d for d in docs}
        self.assertEqual((by["UKR"]["colour"], by["UKR"]["regional"], by["UKR"]["iso"]), ("rood", False, "UA"))
        self.assertEqual((by["ZMB"]["colour"], by["ZMB"]["colours"], by["ZMB"]["regional"]), ("oranje", ["geel", "oranje"], True))
        self.assertEqual((by["BQ-BO"]["iso"], by["BQ-BO"]["colour"]), ("BQ", "groen"))
        self.assertEqual(by["UKR"]["updated"], "2026-10-20T10:00:00.000Z")
        with self.assertRaises(ValueError):
            netherlands.parse(b"<html/>")

    def test_every_listed_id_has_an_iso_code(self):
        for key, iso in netherlands.ISO.items():
            self.assertRegex(iso, r"^[A-Z]{2}$")
            if key != iso and "-" not in key:
                self.assertEqual(key[:2], iso[:2] if key[:2] == iso[:2] else key[:2])  # alpha-3 and alpha-2 differ freely


class NetherlandsCollect(unittest.TestCase):
    def fetcher(self, docs, calls):
        def fetch(url, timeout=40):
            calls.append(url)
            offset = int(url.rsplit("offset=", 1)[1])
            return nl_page(docs[offset:offset + netherlands.PAGE_SIZE]), None
        return fetch

    def test_pages_until_a_short_page_and_diffs(self):
        docs = many(210)
        docs[0] = doc(docs[0].split("<id>")[1][:3], "Aa", INTROS["UKR"])  # one red destination
        calls = []
        first, changes, err = netherlands.collect(None, STAMP, self.fetcher(docs, calls), pause=0)
        self.assertEqual((err, changes), (None, []))
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].endswith("?rows=200&offset=0") and calls[1].endswith("?rows=200&offset=200"))
        self.assertEqual(len(first), 210)
        key = docs[0].split("<id>")[1][:3]
        self.assertEqual(first[key]["colour"], "rood")
        # The red one becomes orange with a yellow part; another goes green to orange.
        other = docs[1].split("<id>")[1][:3]
        docs2 = list(docs)
        docs2[0] = doc(key, "Aa", INTROS["ZMB"])
        docs2[1] = doc(other, "Bb", INTROS["SOM"].replace("rood", "oranje"))
        second, changes, err = netherlands.collect(first, STAMP, self.fetcher(docs2, []), pause=0)
        got = {(c["key"], c["kind"]): (c["from"], c["to"]) for c in changes}
        self.assertEqual(got, {(key, "level"): ("rood", "oranje"), (other, "level"): ("groen", "oranje")})

    def test_a_broken_response_keeps_the_old_data(self):
        kept = {"UKR": {}}
        self.assertIs(netherlands.collect(kept, STAMP, lambda u, t=40: (None, "HTTP 503"), pause=0)[0], kept)
        self.assertIn("unreadable", netherlands.collect(kept, STAMP, lambda u, t=40: (b"<html/>", None), pause=0)[2])
        self.assertIn("only 20", netherlands.collect(kept, STAMP, lambda u, t=40: (nl_page(many(20)), None), pause=0)[2])
        keys = [k for k in sorted(netherlands.ISO) if "-" not in k][:190]
        docs = [doc(k, k.title(), GREEN.format(k)) for k in keys[:160]] + [doc(k, k.title(), INTROS["NLX"]) for k in keys[160:]]
        self.assertIn("name no colour", netherlands.collect(kept, STAMP, lambda u, t=40: (nl_page(docs), None), pause=0)[2])

    def test_paging_counts_the_documents_the_api_returned(self):
        # A document with no isocode on the first page left 199 parsed of 200 returned: paging stopped there and the
        # destinations on the next page were lost with no error.
        docs = many(222)
        docs.insert(5, doc("", "Nergens", GREEN.format("Nergens")))
        calls = []
        got, changes, err = netherlands.collect(None, STAMP, self.fetcher(docs, calls), pause=0)
        self.assertEqual((err, len(calls), len(got)), (None, 2, 222))
        self.assertEqual(netherlands.parse_page(nl_page(docs[:200]))[1], 200)

    def test_an_unreadable_colour_keeps_the_last_reading(self):
        yellow = "<p>De kleurcode van het reisadvies voor Oekraïne is geel.</p>"
        base = many(170)
        first, _, err = netherlands.collect(None, STAMP, self.fetcher(base + [doc("UKR", "Oekraine", yellow)], []), pause=0)
        self.assertEqual((err, first["UKR"]["colour"]), (None, "geel"))
        # Its introduction names no colour this run: the yellow reading stays, marked, and no change is recorded.
        later = "2026-11-26T19:30:00Z"
        second, changes, err = netherlands.collect(
            first, later, self.fetcher(base + [doc("UKR", "Oekraine", INTROS["NLX"])], []), pause=0)
        self.assertEqual((err, changes), (None, []))
        self.assertEqual((second["UKR"]["colour"], second["UKR"]["unread_since"]), ("geel", later))
        # Next run it reads red: the change from yellow is seen, and the mark is gone.
        third, changes, err = netherlands.collect(
            second, "2026-11-27T19:30:00Z", self.fetcher(base + [doc("UKR", "Oekraine", INTROS["UKR"])], []), pause=0)
        self.assertEqual([(c["key"], c["kind"], c["from"], c["to"]) for c in changes], [("UKR", "level", "geel", "rood")])
        self.assertNotIn("unread_since", third["UKR"])
        # A destination never read, and one with no country code, are kept, not dropped.
        fourth, _, err = netherlands.collect(
            third, STAMP, self.fetcher(base + [doc("UKR", "Oekraine", INTROS["UKR"]), doc("SXX", "Nieuwland", GREEN.format("x")),
                                               doc("ZWE", "Zimbabwe", INTROS["NLX"])], []), pause=0)
        self.assertEqual((fourth["SXX"]["iso"], fourth["SXX"]["colour"]), (None, "groen"))
        self.assertEqual((fourth["ZWE"]["colour"], fourth["ZWE"]["unread_since"]), (None, STAMP))
        fc = NetherlandsFeed.build(self, fourth)
        self.assertEqual(fc["dropped"], [])
        ids = {f["properties"]["id"] for f in fc["features"]}
        self.assertNotIn("cordon:netherlands:SXX", ids)
        self.assertNotIn("cordon:netherlands:ZWE", ids)
        self.assertIn("cordon:netherlands:UKR", ids)
        # A kept reading says since when the colour could not be read.
        held = {**fourth, "UKR": {**fourth["UKR"], "unread_since": STAMP}}
        f = next(f for f in NetherlandsFeed.build(self, held)["features"] if f["properties"]["id"] == "cordon:netherlands:UKR")
        self.assertEqual(f["properties"]["measures"]["unread_since"], STAMP)
        regs = registers.ids(ROOT / "doctrine")
        self.assertEqual([m for _, sev, m in contract.check(f, regs) if sev == "error"], [])


class NetherlandsFeed(unittest.TestCase):
    def rec(self, key, iso, name, colours, updated="2026-10-20T10:00:00.000Z"):
        return {"key": key, "iso": iso, "name": name, "name_nl": name, "link": f"https://www.nederlandwereldwijd.nl/reisadvies/{name.lower()}",
                "updated": updated, "colours": colours, "colour": colours[-1], "regional": len(colours) > 1,
                "intro_nl": "De kleurcode van het reisadvies is oranje.", "advice": netherlands.LEVELS[colours[-1]]}

    def build(self, recs, changes=(), last_ok=None):
        h = {"nl-minbuza-travel-advice": {"last_ok": last_ok or STAMP, "failures": 0, "checked_at": STAMP}}
        with unittest.mock.patch.object(feed, "recent_changes", lambda now: list(changes)):
            return feed.build({}, {}, {}, {}, NOW, h, nl={"countries": recs, "fetched_at": STAMP})

    def test_items(self):
        recs = {"UKR": self.rec("UKR", "UA", "Ukraine", ["rood"]),
                "FRA": self.rec("FRA", "FR", "France", ["groen"]),  # green, old: not listed
                "ZMB": self.rec("ZMB", "ZM", "Zambia", ["geel", "oranje"]),
                "DEU": self.rec("DEU", "DE", "Germany", ["groen"], updated="2026-11-24T08:00:00.000Z"),  # inside 72 hours
                "MLI": self.rec("MLI", "ML", "Mali", ["rood"]),
                "BQ-SA": self.rec("BQ-SA", "BQ", "Saba", ["geel"])}
        changes = [{"at": "2026-11-10T10:00:00Z", "lane": "netherlands", "kind": "level", "key": "MLI", "from": "oranje", "to": "rood"},
                   {"at": "2026-11-11T10:00:00Z", "lane": "netherlands", "kind": "regional", "key": "BQ-SA", "from": ["geel"], "to": ["groen", "geel"]}]
        fc = self.build(recs, changes)
        self.assertEqual(fc["dropped"], [])
        items = {f["properties"]["id"]: f["properties"] for f in fc["features"]}
        self.assertEqual(sorted(items), ["cordon:netherlands:BQ-SA", "cordon:netherlands:DEU", "cordon:netherlands:MLI",
                                         "cordon:netherlands:UKR", "cordon:netherlands:ZMB"])
        self.assertEqual((items["cordon:netherlands:UKR"]["title"], items["cordon:netherlands:UKR"]["tier"]),
                         ("Netherlands, Ukraine: Red: do not travel", "routine"))
        self.assertIn("other colours apply in some areas", items["cordon:netherlands:ZMB"]["title"])
        self.assertEqual(items["cordon:netherlands:ZMB"]["signal"], {"name": "Netherlands colour code 1-4", "value": 3, "unit": "colour 1-4"})
        ml = items["cordon:netherlands:MLI"]
        self.assertEqual((ml["tier"], ml["last_change"], ml["measures"]["from_colour"]), ("anomaly", "raised", "orange"))
        self.assertEqual(items["cordon:netherlands:BQ-SA"]["tier"], "anomaly")
        self.assertTrue(items["cordon:netherlands:DEU"]["measures"]["new"])
        regs = registers.ids(ROOT / "doctrine")
        for f in fc["features"]:
            self.assertEqual([m for _, sev, m in contract.check(f, regs) if sev == "error"], [])
        self.assertIn("Nederland Wereldwijd", fc["attribution"])

    def test_a_stale_set_is_withheld_and_events(self):
        fc = self.build({"UKR": self.rec("UKR", "UA", "Ukraine", ["rood"]), "FRA": self.rec("FRA", "FR", "France", ["groen"])},
                        last_ok="2026-11-20T00:00:00Z")
        self.assertEqual(fc["features"], [])
        self.assertEqual((fc["health"]["nl-minbuza-travel-advice"]["state"], fc["health"]["nl-minbuza-travel-advice"]["withheld"]),
                         ("stale", 1))
        changes = [{"at": "2026-11-10T10:00:00Z", "lane": "netherlands", "kind": "level", "key": "MLI", "iso": "ML", "name": "Mali",
                    "link": "https://www.nederlandwereldwijd.nl/reisadvies/mali", "from": "oranje", "to": "rood"}]
        ev = events.build([], changes, NOW)["events"]
        self.assertEqual([e["id"] for e in ev], ["2026-11-10-netherlands-mli-level"])
        self.assertIn('raised from "Orange: travel only if essential" to "Red: do not travel"', ev[0]["title"])


if __name__ == "__main__":
    unittest.main()
