"""Japan's overseas safety information, from the Ministry of Foreign Affairs' open data (外務省 海外安全情報オープンデータ).

Source: https://www.ezairyu.mofa.go.jp/html/opendata/index.html (XML files, no key; the site says they refresh every 5
minutes). Two kinds of file are read:

  /opendata/area/newarrival.xml    the 24 newest notices of any kind (a day or two of them). Each carries an info type,
                                   the issuing embassy or consulate, a country code (some, such as multi-country
                                   consular mail for the United States, carry none), the ministry's Japanese headline
                                   and lead, and a link to its page.
  /opendata/country/{code}L.xml    one country: which danger levels (危険レベル 1-4) the ministry has in force for it,
                                   the headline and lead of its latest danger information, and its date. The "L"
                                   (light) file leaves out the mail bodies; it is still about 0.9 MB (50 KB gzipped).

The ministry's English is nowhere in these files. Cordon therefore keeps the Japanese text as published and adds an
English title built only from a fixed glossary (INFO_TYPES, LEVELS, country names from the kit): no machine
translation and no paid service. The level words are Cordon's rendering of the ministry's four levels, with the
ministry's Japanese beside them.

Times are Japan Standard Time (UTC+9, checked 25 Nov 2026 against the files' HTTP Last-Modified); Cordon stores UTC.

Country levels cost one file each, so a run reads only the countries that matter: those the newest notices name in a
danger notice (T40) dated after the danger notice Cordon holds for them, the countries never read (the first run reads
all 183), and the next READ_BATCH in a fixed rotation by the hour, so every country is read about once a day and a
danger notice that scrolled off the newest list is still caught. No read time is stored: data/japan.json changes only
when the ministry's data does.

Terms (terms.html, read in full 25 Nov 2026): free to copy, publicly transmit and adapt, commercial use allowed;
state the source ("出典：外務省 海外安全情報オープンデータ" with the page URL); say when the content was edited or processed,
and never present it as if the State had made it; the terms follow the Government Standard Terms 2.0 and are
compatible with CC BY 4.0; logos and symbol marks are excluded; the content may change or disappear without notice.
"""
import gzip
import hashlib
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .common import MAX_BYTES, USER_AGENT, country_name, describe, now_utc

SITE = "https://www.ezairyu.mofa.go.jp"
INDEX_URL = SITE + "/html/opendata/index.html"
TERMS_URL = SITE + "/html/opendata/support/terms.html"
NEW_URL = SITE + "/opendata/area/newarrival.xml"
COUNTRY_URL = SITE + "/opendata/country/{code}L.xml"
JST = timezone(timedelta(hours=9))
KEEP_DAYS = 14  # notices kept in data/japan.json; every notice is kept for good in ARCHIVE first
MAX_NOTICES = 400
ARCHIVE = "japan_notices.jsonl"  # in data/, committed, append-only (archive_notices)
ARCHIVE_FORMAT = "cordon-japan-notice/1"
LEAD_CHARS = 600
MIN_NEW = 3  # a listing with fewer notices than this is not the listing
MAX_LISTING_AGE_H = 6  # the listing is regenerated every 5 minutes; this old, it is frozen (the same rule as NGA's)
READ_BATCH = 8  # countries re-read each run beyond those with a new danger notice (185 / 8: all within a day)
MAX_READS = 200  # the first run reads every country
PAUSE_S = 0.2
STALE_HOURS = 12  # a source that refreshes every 5 minutes; the default 48 hours would hide a day of nothing new

# The ministry's info types (the infoType and infoName fields), in English by this glossary only.
INFO_TYPES = {"R10": "consular mail (general)", "R20": "consular mail (urgent)", "C30": "spot information",
              "C31": "spot information (infectious disease)", "C50": "wide-area information",
              "C51": "wide-area information (infectious disease)", "T40": "danger information",
              "T81": "infectious disease danger information"}
DANGER_TYPES = ("T40", "T81")  # the levels, not notices; only T40 says a country file moved
# Danger levels (危険レベル), lowest first; the English is Cordon's rendering of the ministry's own wording.
LEVELS = {1: "Level 1: Exercise caution", 2: "Level 2: Avoid non-essential travel",
          3: "Level 3: Do not travel (travel warning)", 4: "Level 4: Evacuate, do not travel (evacuation advisory)"}
LEVELS_JA = {1: "レベル1：十分注意してください", 2: "レベル2：不要不急の渡航は止めてください",
             3: "レベル3：渡航は止めてください（渡航中止勧告）", 4: "レベル4：退避してください。渡航は止めてください（退避勧告）"}

# MOFA country code -> ISO 3166-1 alpha-2, from the 185 codes in the ministry's full list of 25 Nov 2026
# (area/00.xml). The codes are the ministry's own: mostly telephone codes, not always (0213 is the Democratic Republic
# of the Congo in one notice). Names are the ministry's Japanese.
COUNTRIES = {
    "0007": "KZ", "0020": "EG", "0027": "ZA", "0030": "GR", "0031": "NL", "0032": "BE", "0033": "FR", "0034": "ES",
    "0036": "HU", "0039": "IT", "0040": "RO", "0041": "CH", "0043": "AT", "0044": "GB", "0045": "DK", "0046": "SE",
    "0047": "NO", "0048": "PL", "0049": "DE", "0051": "PE", "0052": "MX", "0053": "CU", "0054": "AR", "0055": "BR",
    "0056": "CL", "0057": "CO", "0058": "VE", "0060": "MY", "0061": "AU", "0062": "ID", "0063": "PH", "0064": "NZ",
    "0065": "SG", "0066": "TH", "0082": "KR", "0084": "VN", "0086": "CN", "0090": "TR", "0091": "IN", "0092": "PK",
    "0093": "AF", "0094": "LK", "0095": "MM", "0098": "IR", "0211": "SS", "0212": "MA", "0213": "DZ", "0216": "TN",
    "0218": "LY", "0220": "GM", "0221": "SN", "0222": "MR", "0223": "ML", "0224": "GN", "0225": "CI", "0226": "BF",
    "0227": "NE", "0228": "TG", "0229": "BJ", "0230": "MU", "0231": "LR", "0232": "SL", "0233": "GH", "0234": "NG",
    "0235": "TD", "0236": "CF", "0237": "CM", "0238": "CV", "0239": "ST", "0240": "GQ", "0241": "GA", "0242": "CG",
    "0243": "CD", "0244": "AO", "0245": "GW", "0248": "SC", "0249": "SD", "0250": "RW", "0251": "ET", "0252": "SO",
    "0253": "DJ", "0254": "KE", "0255": "TZ", "0256": "UG", "0257": "BI", "0258": "MZ", "0260": "ZM", "0261": "MG",
    "0263": "ZW", "0264": "NA", "0265": "MW", "0266": "LS", "0267": "BW", "0268": "SZ", "0269": "KM", "0291": "ER",
    "0297": "AW", "0351": "PT", "0352": "LU", "0353": "IE", "0354": "IS", "0355": "AL", "0356": "MT", "0357": "CY",
    "0358": "FI", "0359": "BG", "0370": "LT", "0371": "LV", "0372": "EE", "0373": "MD", "0374": "AM", "0375": "BY",
    "0380": "UA", "0381": "RS", "0385": "HR", "0387": "BA", "0389": "MK", "0420": "CZ", "0421": "SK", "0501": "BZ",
    "0502": "GT", "0503": "SV", "0504": "HN", "0505": "NI", "0506": "CR", "0507": "PA", "0509": "HT", "0591": "BO",
    "0592": "GY", "0593": "EC", "0595": "PY", "0598": "UY", "0670": "TL", "0673": "BN", "0675": "PG", "0676": "TO",
    "0677": "SB", "0678": "VU", "0679": "FJ", "0680": "PW", "0682": "CK", "0683": "NU", "0685": "WS", "0686": "KI",
    "0687": "NC", "0688": "TV", "0691": "FM", "0692": "MH", "0809": "DO", "0852": "HK", "0855": "KH", "0856": "LA",
    "0868": "TT", "0876": "JM", "0880": "BD", "0886": "TW", "0960": "MV", "0961": "LB", "0962": "JO", "0963": "SY",
    "0964": "IQ", "0965": "KW", "0966": "SA", "0967": "YE", "0968": "OM", "0971": "AE", "0972": "IL", "0973": "BH",
    "0974": "QA", "0975": "BT", "0976": "MN", "0977": "NP", "0992": "TJ", "0993": "TM", "0994": "AZ", "0995": "GE",
    "0996": "KG", "0998": "UZ", "1000": "US", "1001": "MP", "1340": "VI", "9001": "CA", "9007": "RU", "9212": "EH",
    "9381": "XK"}
# Each ISO code above appears once, so it is the key of a country in Cordon's data.
BY_ISO = {iso: code for code, iso in COUNTRIES.items()}
# Aruba and the US Virgin Islands are in the ministry's list of places, but their country files do not exist (the
# server answers 200 with its maintenance page, 25 Nov 2026): notices naming them are placed, their levels are not read.
NO_FILE = {"0297", "1340"}
READABLE = len(COUNTRIES) - len(NO_FILE)
# The tag in a danger notice's headline: 【一部地域の危険レベル引下げ】 (levels lowered in some areas),
# 【危険レベル継続】 (level continues). Only a raise or a lowering is the ministry saying the levels moved.
TAG_RE = re.compile(r"【([^】]*)】")
RAISED_RE = re.compile(r"引上げ|引き上げ|引上|引き上")
LOWERED_RE = re.compile(r"引下げ|引き下げ|引下|引き下")


def jst_to_utc(text: str | None) -> str | None:
    """'2026/11/26 02:51:05' (Japan time) -> '2026-11-25T17:51:05Z'."""
    try:
        dt = datetime.strptime((text or "").strip(), "%Y/%m/%d %H:%M:%S").replace(tzinfo=JST)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_gz(url: str, timeout: int = 40):
    """(body, None) or (None, error). Asks for gzip, as the ministry's files are large; undone here."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(MAX_BYTES + 1)
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
        if len(body) > MAX_BYTES:
            raise ValueError(f"response over {MAX_BYTES} bytes")
        return body, None
    except Exception as e:  # noqa: BLE001 - every failure is reported, none is fatal
        return None, describe(e)


def _text(el, tag: str) -> str:
    return re.sub(r"[ \t]+\n", "\n", (el.findtext(tag) or "").strip())


def parse_listing(body: bytes) -> tuple[dict, str | None]:
    """({keyCd: notice}, listing time in UTC). Notice: key, type, at (UTC), code, iso, name_ja, title_ja, lead_ja, link,
    mission_ja. Raises ValueError when the file is not the ministry's list (a maintenance page is HTML)."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise ValueError(f"not XML: {e}") from e
    if root.tag != "opendata":
        raise ValueError("not an opendata file")
    out = {}
    for m in root.findall("mail"):
        key, typ = _text(m, "keyCd"), _text(m, "infoType")
        at = jst_to_utc(_text(m, "leaveDate"))
        if not key.isdigit() or not typ or not at:
            continue
        c = m.find("country")
        code = _text(c, "cd") if c is not None else ""
        link = _text(m, "infoUrl")
        out[key] = {"key": key, "type": typ, "at": at, "code": code or None, "iso": COUNTRIES.get(code),
                    "name_ja": _text(c, "name") if c is not None else None, "title_ja": _text(m, "title"),
                    "lead_ja": _text(m, "lead")[:LEAD_CHARS],
                    "link": link if link.startswith("https://www.anzen.mofa.go.jp/") else INDEX_URL,
                    "mission_ja": _text(m, "koukanName") or None}
    return out, jst_to_utc(root.get("lastModified"))


def parse_country(body: bytes) -> dict:
    """The country file's danger levels: {code, levels, max_level, infection_levels, risk_title, risk_lead, risk_key,
    risk_at, link}. `levels` are the danger levels (1-4) the ministry has in force somewhere in the country; max_level
    is the highest, 0 when none."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise ValueError(f"not XML: {e}") from e
    c = root.find("country")
    if root.tag != "opendata" or c is None or not _text(c, "cd"):
        raise ValueError("not a country file")
    flag = lambda tag: _text(root, tag) == "1"  # noqa: E731
    levels = [n for n in (1, 2, 3, 4) if flag(f"riskLevel{n}")]
    risk = root.find("riskLeaveDate")
    link = _text(root, "riskUrl")
    return {"code": _text(c, "cd"), "levels": levels, "max_level": max(levels, default=0),
            "infection_levels": [n for n in (1, 2, 3, 4) if flag(f"infectionLevel{n}")],
            "risk_title_ja": _text(root, "riskTitle") or None, "risk_lead_ja": _text(root, "riskLead")[:LEAD_CHARS] or None,
            "risk_key": risk.get("keyCd") if risk is not None else None,
            "risk_at": jst_to_utc(risk.text) if risk is not None and risk.text else None,
            "link": link if link.startswith("https://www.anzen.mofa.go.jp/") else _text(root, "infoUrl") or INDEX_URL}


def declared_move(rec: dict) -> str | None:
    """'raised', 'lowered' or None: the ministry's own tag on its latest danger headline (a level raised or lowered, in
    all or part of the country). A 'level continues' tag is not a move."""
    tags = " ".join(TAG_RE.findall(rec.get("risk_title_ja") or ""))
    return "raised" if RAISED_RE.search(tags) else "lowered" if LOWERED_RE.search(tags) else None


def jst_date(utc: str) -> str:
    """The Japan-time calendar day of a UTC time: the ministry dates a danger notice by that day."""
    return (datetime.strptime(utc, "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=9)).strftime("%Y-%m-%d")


def english_title(rec: dict) -> str:
    return country_name(rec["iso"], rec.get("name_ja") or "")


def diff(old: dict, new: dict, when: str) -> list[dict]:
    """A change of a country's highest level, or of the set of levels in force (levels added or removed in some areas
    with the highest unchanged), against what Cordon held. A country read for the first time is no change."""
    out = []
    for key, rec in new.items():
        prev = old.get(key)
        if not prev or prev.get("max_level") is None:
            continue
        base = {"at": when, "key": key, "iso": rec["iso"], "name": english_title(rec), "link": rec["link"]}
        if prev["max_level"] != rec["max_level"]:
            out.append({**base, "kind": "level", "from": prev["max_level"], "to": rec["max_level"]})
        elif sorted(prev.get("levels") or []) != sorted(rec["levels"]):
            out.append({**base, "kind": "regional", "from": sorted(prev.get("levels") or []), "to": sorted(rec["levels"])})
    return out


def rotation(when: str, batch: int = READ_BATCH) -> list[str]:
    """The next `batch` readable MOFA codes in a fixed rotation by the hour (a run an hour reads each about once a day)."""
    codes = sorted(c for c in COUNTRIES if c not in NO_FILE)
    hour = int(datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() // 3600)
    return [codes[(hour * batch + i) % len(codes)] for i in range(batch)]


def pick_reads(listing: dict, countries: dict, when: str, batch: int = READ_BATCH, limit: int = MAX_READS) -> list[str]:
    """MOFA codes to read this run, in order: never read, then those with a danger notice (T40) dated after the one held
    for the country, then the hour's rotation. At most `limit` in all."""
    never = [c for c, iso in COUNTRIES.items() if iso not in countries and c not in NO_FILE]
    pending = sorted({n["code"] for n in listing.values() if n["type"] == "T40" and n["code"] in COUNTRIES
                      and COUNTRIES[n["code"]] in countries
                      and n["at"] > (countries[COUNTRIES[n["code"]]].get("risk_at") or "")})
    return list(dict.fromkeys(never + pending + rotation(when, batch)))[:limit]


def archive_notices(path, notices: dict, at: str) -> list:
    """Append to the archive (ARCHIVE, append-only JSONL) every notice not already in it as it is now: a notice is
    written when first seen and again only if the ministry's text for it changes. Returns the lines written. The
    archive is the permanent copy; data/japan.json holds only the last KEEP_DAYS."""
    path = Path(path)
    seen = set()
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for ln in fh:
                try:
                    seen.add(json.loads(ln)["digest"])
                except (ValueError, KeyError, TypeError):
                    continue
    out = []
    for key, n in sorted(notices.items(), key=lambda kv: (kv[1].get("at") or "", kv[0])):
        dg = hashlib.sha1(json.dumps(n, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        if dg in seen:
            continue
        seen.add(dg)
        out.append({"format": ARCHIVE_FORMAT, "archived_at": at, "key": key, "digest": dg, "notice": n})
    if out:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            for line in out:
                fh.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
    return out


def collect(old: dict | None, when: str | None = None, fetch=fetch_gz, pause: float = PAUSE_S, archive=None):
    """(held, changes, error, read, failed). `held` is {"notices", "countries"}; on error the caller keeps
    the old one. `archive`: called with every notice held this run before any is pruned (archive_notices); without
    it, or when it raises OSError, nothing is pruned."""
    when = when or now_utc()
    old = old or {}
    body, err = fetch(NEW_URL, 40)
    if body is None:
        return old, [], err, 0, 0
    try:
        listing, listing_at = parse_listing(body)
    except (ValueError, UnicodeDecodeError) as e:
        return old, [], f"unreadable: {e}"[:120], 0, 0
    if len(listing) < MIN_NEW:
        return old, [], f"only {len(listing)} notices listed", 0, 0
    if not listing_at or listing_at < (datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ")
                                       - timedelta(hours=MAX_LISTING_AGE_H)).strftime("%Y-%m-%dT%H:%M:%SZ"):
        return old, [], f"the listing is dated {listing_at}: frozen", 0, 0
    held = dict(old.get("countries") or {})
    notices = dict(old.get("notices") or {})
    notices.update(listing)
    # Every notice goes to the append-only archive first; only an archived set is pruned (no archive given, or the
    # archive failed: nothing is pruned this run).
    try:
        archived = archive is not None and archive(notices) is not None
    except OSError:
        archived = False
    if archived:
        cutoff = (datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ")
                  - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        notices = dict(sorted(((k, n) for k, n in notices.items() if n["at"] >= cutoff), key=lambda kv: kv[1]["at"],
                              reverse=True)[:MAX_NOTICES])
    read = failed = 0
    fresh = {}
    for code in pick_reads(listing, held, when):
        cb, cerr = fetch(COUNTRY_URL.format(code=code), 60)
        if pause:
            time.sleep(pause)
        try:
            if cb is None:
                raise ValueError(cerr)
            rec = parse_country(cb)
            iso = COUNTRIES.get(rec["code"])
            if iso is None or rec["code"] != code:
                raise ValueError("a different country")
            fresh[iso] = {**rec, "iso": iso, "name_ja": (held.get(iso) or {}).get("name_ja")}
            read += 1
        except (ValueError, UnicodeDecodeError):
            failed += 1  # the earlier reading stays; asked for again next run
    for iso, rec in fresh.items():  # the ministry's name for the country, from the newest notice that carries it
        names = [n["name_ja"] for n in notices.values() if n["iso"] == iso and n.get("name_ja")]
        rec["name_ja"] = names[0] if names else rec.get("name_ja")
    changes = diff(held, fresh, when)
    held.update(fresh)
    return {"notices": notices, "countries": dict(sorted(held.items()))}, changes, None, read, failed

