"""Netherlands travel advice (Ministry of Foreign Affairs, published on Nederland Wereldwijd), from its open data API.

Source: https://opendata.nederlandwereldwijd.nl/v2/sources/nederlandwereldwijd/infotypes/traveladvice (XML, no key;
the API serves 200 documents at most per request, so Cordon pages with `rows=200&offset=`: 226 destinations on
25 Nov 2026). Each document has the destination (`location`, `isocode`: ISO 3166-1 alpha-3, and BQ-BO, BQ-SA and
BQ-SE for the three Caribbean municipalities), the page's address, an introduction ("In het kort") in Dutch, and
`lastmodified` (UTC). The colour code is only in the introduction's sentences: "De kleurcode van het reisadvies voor
Oekraine is rood", and for a country with regional advice "De kleurcode van het reisadvies is oranje voor het
grensgebied ... Voor de rest van Zambia geldt kleurcode geel". Cordon reads every colour word in a sentence that says
"kleurcode"; the highest is the country's colour, and more than one means the colour differs by area.

The four colours (kleurcodes), lowest first, are the ministry's: groen (no special security risks), geel (special
security risks, travel with care), oranje (travel only if essential), rood (do not travel). The English words are
Cordon's fixed glossary, with the Dutch beside them: no machine translation, no paid service.

Licence: the dataset "Reisadviezen op nederlandwereldwijd.nl" on data.overheid.nl lists it as CC0 1.0 (read
25 Nov 2026); the API itself states no licence line. Cordon credits the ministry in any case.
"""
import re
import time
import xml.etree.ElementTree as ET
from html import unescape

from .common import country_name, fetch_or_none, now_utc

API = "https://opendata.nederlandwereldwijd.nl/v2/sources/nederlandwereldwijd/infotypes/traveladvice"
PAGE_SIZE = 200  # the API's own maximum
MAX_PAGES = 4
DATASET_URL = "https://data.overheid.nl/dataset/294e12a4-6d45-4d7b-b0d2-b91ae608b08d"
MIN_COUNTRIES = 150  # 227 listed; far fewer means a broken response
MAX_UNREAD_SHARE = 0.1  # destinations whose introduction names no colour; more than this and the wording changed
PAUSE_S = 0.2
# Colours, lowest first.
ORDER = ["groen", "geel", "oranje", "rood"]
LEVELS = {"groen": "Green: no special security risks (travel there)",
          "geel": "Yellow: special security risks, travel with care",
          "oranje": "Orange: travel only if essential",
          "rood": "Red: do not travel"}
COLOURS_EN = {"groen": "green", "geel": "yellow", "oranje": "orange", "rood": "red"}
# ISO 3166-1 alpha-3 (the API's ids) to alpha-2, for the 226 on 25 Nov 2026.
ISO = {
    "ABW": "AW", "AFG": "AF", "AGO": "AO", "AIA": "AI", "ALB": "AL", "AND": "AD", "ARE": "AE", "ARG": "AR", "ARM": "AM",
    "ASM": "AS", "ATA": "AQ", "ATG": "AG", "AUS": "AU", "AUT": "AT", "AZE": "AZ", "BDI": "BI", "BEL": "BE", "BEN": "BJ",
    "BFA": "BF", "BGD": "BD", "BGR": "BG", "BHR": "BH", "BHS": "BS", "BIH": "BA", "BLR": "BY", "BLZ": "BZ", "BOL": "BO",
    "BRA": "BR", "BRB": "BB", "BRN": "BN", "BTN": "BT", "BWA": "BW", "CAF": "CF", "CAN": "CA", "CHE": "CH", "CHL": "CL",
    "CHN": "CN", "CIV": "CI", "CMR": "CM", "COD": "CD", "COG": "CG", "COK": "CK", "COL": "CO", "COM": "KM", "CPV": "CV",
    "CRI": "CR", "CUB": "CU", "CUW": "CW", "CYM": "KY", "CYP": "CY", "CZE": "CZ", "DEU": "DE", "DJI": "DJ", "DMA": "DM",
    "DNK": "DK", "DOM": "DO", "DZA": "DZ", "ECU": "EC", "EGY": "EG", "ERI": "ER", "ESP": "ES", "EST": "EE", "ETH": "ET",
    "FIN": "FI", "FJI": "FJ", "FRA": "FR", "FRO": "FO", "FSM": "FM", "GAB": "GA", "GBR": "GB", "GEO": "GE", "GHA": "GH",
    "GIN": "GN", "GLP": "GP", "GMB": "GM", "GNB": "GW", "GNQ": "GQ", "GRC": "GR", "GRD": "GD", "GRL": "GL", "GTM": "GT",
    "GUF": "GF", "GUY": "GY", "HKG": "HK", "HND": "HN", "HRV": "HR", "HTI": "HT", "HUN": "HU", "IDN": "ID", "IND": "IN",
    "IRL": "IE", "IRN": "IR", "IRQ": "IQ", "ISL": "IS", "ISR": "IL", "ITA": "IT", "JAM": "JM", "JOR": "JO", "JPN": "JP",
    "KAZ": "KZ", "KEN": "KE", "KGZ": "KG", "KHM": "KH", "KIR": "KI", "KNA": "KN", "KOR": "KR", "KWT": "KW", "LAO": "LA",
    "LBN": "LB", "LBR": "LR", "LBY": "LY", "LCA": "LC", "LIE": "LI", "LKA": "LK", "LSO": "LS", "LTU": "LT", "LUX": "LU",
    "LVA": "LV", "MAC": "MO", "MAR": "MA", "MCO": "MC", "MDA": "MD", "MDG": "MG", "MDV": "MV", "MEX": "MX", "MHL": "MH",
    "MKD": "MK", "MLI": "ML", "MLT": "MT", "MMR": "MM", "MNE": "ME", "MNG": "MN", "MOZ": "MZ", "MRT": "MR", "MSR": "MS",
    "MTQ": "MQ", "MUS": "MU", "MWI": "MW", "MYS": "MY", "NAM": "NA", "NCL": "NC", "NER": "NE", "NGA": "NG", "NIC": "NI",
    "NIU": "NU", "NOR": "NO", "NPL": "NP", "NRU": "NR", "NZL": "NZ", "OMN": "OM", "PAK": "PK", "PAN": "PA", "PCN": "PN",
    "PER": "PE", "PHL": "PH", "PLW": "PW", "PNG": "PG", "POL": "PL", "PRI": "PR", "PRK": "KP", "PRT": "PT", "PRY": "PY",
    "PSE": "PS", "PYF": "PF", "QAT": "QA", "REU": "RE", "ROU": "RO", "RUS": "RU", "RWA": "RW", "SAU": "SA", "SDN": "SD",
    "SEN": "SN", "SGP": "SG", "SJM": "SJ", "SLB": "SB", "SLE": "SL", "SLV": "SV", "SMR": "SM", "SOM": "SO", "SRB": "RS",
    "SSD": "SS", "STP": "ST", "SUR": "SR", "SVK": "SK", "SVN": "SI", "SWE": "SE", "SWZ": "SZ", "SXM": "SX", "SYC": "SC",
    "SYR": "SY", "TCA": "TC", "TCD": "TD", "TGO": "TG", "THA": "TH", "TJK": "TJ", "TKL": "TK", "TKM": "TM", "TLS": "TL",
    "TON": "TO", "TTO": "TT", "TUN": "TN", "TUR": "TR", "TUV": "TV", "TWN": "TW", "TZA": "TZ", "UGA": "UG", "UKR": "UA",
    "URY": "UY", "USA": "US", "UZB": "UZ", "VCT": "VC", "VEN": "VE", "VGB": "VG", "VIR": "VI", "VNM": "VN", "VUT": "VU",
    "WLF": "WF", "WSM": "WS", "XKX": "XK", "YEM": "YE", "ZAF": "ZA", "ZMB": "ZM", "ZWE": "ZW",
    "BQ-BO": "BQ", "BQ-SA": "BQ", "BQ-SE": "BQ"}
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
COLOUR_RE = re.compile(r"\b(groen|geel|oranje|rood)\b", re.I)


def level_rank(colour: str | None) -> int:
    """0 groen ... 3 rood; -1 for none."""
    return ORDER.index(colour) if colour in ORDER else -1


def strip(html: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def colours(intro: str | None) -> list[str]:
    """The distinct colours, lowest first, named in the introduction's sentences that say kleurcode. A sentence about
    insurers ("Bij een oranje of rood reisadvies ...") does not say it, and is not read."""
    found = set()
    for s in SENTENCE_RE.split(strip(intro)):
        if re.search(r"kleurcode", s, re.I):
            found.update(c.lower() for c in COLOUR_RE.findall(s))
    return sorted(found, key=ORDER.index)


def first_sentence(intro: str | None) -> str | None:
    """The introduction's sentence that states the colour, in the ministry's Dutch."""
    for s in SENTENCE_RE.split(strip(intro)):
        if re.search(r"kleurcode", s, re.I):
            return s[:300]
    return None


def parse(body: bytes) -> list[dict]:
    """The page's documents as {key, iso, name_nl, link, updated, colours, colour, regional, intro_nl, api_url}."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise ValueError(f"not XML: {e}") from e
    if root.tag != "documents":
        raise ValueError("not a documents list")
    out = []
    for d in root.findall("document"):
        key = (d.findtext("isocode") or "").strip().upper()
        iso = ISO.get(key)
        if not key or d.findtext("type") != "reisadvies":
            continue
        intro = d.findtext("introduction")
        cols = colours(intro)
        link = (d.findtext("canonical") or "").strip()
        out.append({"key": key, "iso": iso, "name_nl": (d.findtext("location") or key).strip(),
                    "link": link if link.startswith("https://www.nederlandwereldwijd.nl/") else
                    "https://www.nederlandwereldwijd.nl/reisadvies",
                    "updated": (d.findtext("lastmodified") or "").strip() or None, "colours": cols,
                    "colour": cols[-1] if cols else None, "regional": len(cols) > 1, "intro_nl": first_sentence(intro)})
    return out


def diff(old: dict, new: dict, when: str) -> list[dict]:
    """A change of a destination's colour (its highest), or of the set of colours in force, against what Cordon held."""
    out = []
    for key, rec in new.items():
        prev = old.get(key)
        if not prev or not prev.get("colour") or not rec.get("colour"):
            continue
        base = {"at": when, "key": key, "iso": rec["iso"], "name": rec["name"], "link": rec["link"]}
        if prev["colour"] != rec["colour"]:
            out.append({**base, "kind": "level", "from": prev["colour"], "to": rec["colour"]})
        elif list(prev.get("colours") or []) != rec["colours"]:
            out.append({**base, "kind": "regional", "from": list(prev.get("colours") or []), "to": rec["colours"]})
    return out


def collect(old: dict | None, when: str | None = None, fetch=fetch_or_none, pause: float = PAUSE_S):
    """(destinations, changes, error). On error the caller keeps the old set."""
    when = when or now_utc()
    old = old or {}
    docs = []
    for page in range(MAX_PAGES):
        body, err = fetch(f"{API}?rows={PAGE_SIZE}&offset={page * PAGE_SIZE}", 40)
        if body is None:
            return old, [], err
        try:
            got = parse(body)
        except (ValueError, UnicodeDecodeError) as e:
            return old, [], f"unreadable: {e}"[:120]
        docs += got
        if len(got) < PAGE_SIZE:
            break
        if pause:
            time.sleep(pause)
    new = {}
    unread = 0
    for r in docs:
        if not r["iso"]:
            continue  # a destination Cordon has no code for is left out, not guessed
        if not r["colour"]:
            unread += 1
            continue
        # The three Caribbean municipalities share BQ: each keeps the ministry's own name.
        name = r["name_nl"] if "-" in r["key"] else country_name(r["iso"], r["name_nl"])
        new[r["key"]] = {**r, "name": name, "advice": LEVELS[r["colour"]]}
    if len(new) < MIN_COUNTRIES:
        return old, [], f"only {len(new)} destinations listed"
    if unread > MAX_UNREAD_SHARE * len(docs):
        return old, [], f"{unread} of {len(docs)} introductions name no colour"
    return dict(sorted(new.items())), diff(old, new, when), None
