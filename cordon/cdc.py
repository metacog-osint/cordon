"""CDC travel health notices (Travelers' Health), from CDC's RSS feed.

Source: https://wwwnc.cdc.gov/travel/rss/notices.xml (no key). Checked live 14 Nov 2026: 22 notices, each with a title
"Level N - <disease> in <place>", a description (for multi-country notices it ends with "Country List : A, B, ..."),
the notice's page as link and guid, and a publication date (midnight US Eastern, given in GMT). The level is also in
the link path (/notices/level2/yellow-fever-colombia); a notice keeps its slug when CDC moves it to another level.
CDC's four levels, as its notices page names them: 1 Practice Usual Precautions, 2 Practice Enhanced Precautions,
3 Reconsider Nonessential Travel, 4 Avoid All Travel.

Terms: CDC website content is in the public domain unless noted. CDC asks that reuse credit CDC, carry a disclaimer
that it implies no endorsement by CDC, HHS or the US Government, not alter the substance, and note that the material
is available free on CDC's site (cdc.gov/other/agencymaterials.html). Cordon quotes CDC's title and summary as given
and links each notice.

Places: from the Country List when CDC gives one, otherwise from the title, matched against the doctrine kit's country
names and ALIASES. A notice whose place matches no country (a region, "Sub-Saharan Africa" without a list) is kept
with no countries and drawn at no point.
"""
import html
import re
import unicodedata
from datetime import timedelta, timezone
from email.utils import parsedate_to_datetime

from .common import fetch_or_none, now_utc
from tic_doctrine import geo

SOURCE_URL = "https://wwwnc.cdc.gov/travel/rss/notices.xml"
PAGE_URL = "https://wwwnc.cdc.gov/travel/notices"
TERMS_URL = "https://www.cdc.gov/other/agencymaterials.html"
LEVELS = {1: "Practice Usual Precautions", 2: "Practice Enhanced Precautions", 3: "Reconsider Nonessential Travel",
          4: "Avoid All Travel"}
MIN_NOTICES = 3  # CDC listed 22; an empty or near-empty feed is more likely broken than all-clear
# CDC's names that differ from the kit's (lower case, accents stripped, parentheses removed).
ALIASES = {"democratic republic of the congo": "CD", "drc": "CD", "republic of the congo": "CG", "congo": "CG",
           "cote d'ivoire": "CI", "ivory coast": "CI", "burma": "MM", "myanmar": "MM", "cabo verde": "CV",
           "cape verde": "CV", "eswatini": "SZ", "swaziland": "SZ", "the gambia": "GM", "gambia": "GM",
           "laos": "LA", "north korea": "KP", "south korea": "KR", "russia": "RU", "syria": "SY", "tanzania": "TZ",
           "united states": "US", "vietnam": "VN", "turkey": "TR", "turkiye": "TR", "micronesia": "FM",
           "sao tome and principe": "ST", "timor-leste": "TL", "east timor": "TL", "mayotte": "YT",
           "french guiana": "GF", "reunion": "RE", "guadeloupe": "GP", "martinique": "MQ", "bolivia": "BO",
           "iran": "IR", "moldova": "MD", "brunei": "BN", "palestinian territories": "PS", "west bank": "PS",
           "gaza": "PS", "kosovo": "XK", "marshall islands": "MH", "solomon islands": "SB",
           "republic of south sudan": "SS", "west bank and gaza": "PS", "u.k": "GB", "uk": "GB",
           "u.s": "US", "us": "US", "u.s. virgin islands": "VI", "macau": "MO", "wake island": "UM",
           "bonaire": "BQ", "saba": "BQ", "sint eustatius": "BQ", "federated states of micronesia": "FM"}
LEVEL_RE = re.compile(r"^\s*Level\s+([1-4])\s*[-–—]\s*(.+)$", re.I)
SLUG_RE = re.compile(r"/notices/(?:level[1-4]/)?([a-z0-9-]+)/?$")
LIST_RE = re.compile(r"Country List\s*:\s*(.*?)(?=Country List\s*:|$)", re.S)
_NAMES = None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"\([^)]*\)", " ", s.replace("’", "'")).lower()
    return re.sub(r"\s+", " ", s).strip(" .,;")


def _names() -> dict:
    """{normalized name: ISO alpha-2}, kit names first, CDC's aliases over them."""
    global _NAMES
    if _NAMES is None:
        _NAMES = {_norm(n): cc for cc, n in geo._names().items() if n}
        _NAMES.update(ALIASES)
    return _NAMES


def iso_for(name: str) -> str | None:
    n = _norm(name)
    return _names().get(n) or _names().get(re.sub(r"^the ", "", n))


def split_list(text: str) -> list[str]:
    """CDC's Country List split at commas outside parentheses ("United Kingdom (including England, Wales)" is one)."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")" and depth > 0
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return [x.strip() for x in out + [cur] if x.strip()]


def list_iso(name: str) -> str | None:
    """A Country List entry: its own name, else the country in its parentheses ("Azores (Portugal)" -> PT)."""
    code = iso_for(name)
    if code:
        return code
    inner = re.findall(r"\(([^()]*)\)", name)
    return iso_for(inner[-1]) if inner else None


def places(title: str, description: str) -> tuple[list[str], list[str]]:
    """(ISO codes, names that matched no country). The Country List when given, else names found in the title."""
    lists = [m.group(1) for m in LIST_RE.finditer(description or "")]
    if lists:
        codes, unplaced, sub = set(), [], False
        for x in split_list(lists[0]):
            # "United Kingdom, including England, Scotland, Wales, and Northern Ireland": the pieces after "including"
            # are parts of the country before them, until the next entry that is a country itself.
            if re.match(r"(including|includes)\b", x, re.I):
                sub = True
                continue
            code = list_iso(x)
            if code:
                codes.add(code)
                sub = False
            elif not sub:
                unplaced.append(x)
        return sorted(codes), unplaced
    t = " " + _norm(title) + " "
    found, taken = set(), t
    for n in sorted(_names(), key=len, reverse=True):  # longest first: "democratic republic of the congo" before "congo"
        if len(n) > 3 and f" {n} " in taken:
            found.add(_names()[n])
            taken = taken.replace(f" {n} ", " | ")
    return sorted(found), []


def _text(item: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
    v = re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1)) if m else ""
    return re.sub(r"\s+", " ", html.unescape(v)).strip()


def parse(body: bytes) -> dict:
    """{slug: {slug, level, level_text, title, disease_place, summary, countries, unplaced, published, link}}."""
    s = body.decode("utf-8-sig")
    if "<rss" not in s[:500]:
        raise ValueError("not an RSS feed")
    out = {}
    for item in re.findall(r"<item>(.*?)</item>", s, re.S):
        title, link = _text(item, "title"), _text(item, "link")
        m, sm = LEVEL_RE.match(title), SLUG_RE.search(link)
        if not m or not sm:
            continue
        level, what = int(m.group(1)), m.group(2).strip()
        desc = _text(item, "description")
        codes, unplaced = places(what, desc)
        try:
            when = parsedate_to_datetime(_text(item, "pubDate")).astimezone(timezone.utc)
            pub = when.strftime("%Y-%m-%dT%H:%M:%SZ")
            # CDC dates a notice, it does not time it: the pubDate is midnight US Eastern (04:00 or 05:00 GMT), so
            # the date CDC means is the GMT time less 4 hours.
            day = (when - timedelta(hours=4)).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pub = day = None
        summary = LIST_RE.sub("", desc).replace("Country List :", "").strip()
        out[sm.group(1)] = {"slug": sm.group(1), "level": level, "level_text": LEVELS[level], "title": title,
                            "disease_place": what, "summary": summary[:600], "countries": codes, "unplaced": unplaced,
                            "published": pub, "date": day, "link": link}
    return out


def diff(old: dict, new: dict, when: str) -> list[dict]:
    """New notices, level changes and removed notices, against the set Cordon held before (none on the first run)."""
    if not old:
        return []
    out = []
    for slug, rec in new.items():
        prev = old.get(slug)
        base = {"at": when, "key": slug, "name": rec["disease_place"], "link": rec["link"], "countries": rec["countries"]}
        if not prev:
            out.append({**base, "kind": "new", "from": None, "to": rec["level"]})
        elif prev.get("level") != rec["level"]:
            out.append({**base, "kind": "level", "from": prev.get("level"), "to": rec["level"]})
    for slug, prev in old.items():
        if slug not in new:
            out.append({"at": when, "key": slug, "name": prev.get("disease_place"), "link": prev.get("link"),
                        "countries": prev.get("countries") or [], "kind": "removed", "from": prev.get("level"), "to": None})
    return out


def collect(old: dict | None, when: str | None = None, fetch=fetch_or_none):
    """(notices, changes, error). On error the caller keeps the old set."""
    when = when or now_utc()
    old = old or {}
    body, err = fetch(SOURCE_URL, 30)
    if body is None:
        return old, [], err
    try:
        new = parse(body)
    except (ValueError, UnicodeDecodeError) as e:
        return old, [], f"unreadable: {type(e).__name__}"
    if len(new) < MIN_NOTICES:
        return old, [], f"only {len(new)} notices listed"
    return dict(sorted(new.items())), diff(old, new, when), None
