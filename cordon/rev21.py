"""Feed contract revision 2.1 (kit 0.6.2) for Cordon: subjects, change flags, event times, place basis, sea areas,
signals and corroboration. The builders in feed.py state what they know per lane (event times, last_change from
Cordon's own change record, signals); finish() then fills what follows from the lane alone.

Decisions (Tom, 18 Nov 2026): an embassy alert's subject is its title with the date cut and punctuation folded, one
item per subject (the newest post, earlier posts in measures.earlier); alerts are placed by location; NGA security
warnings are reported by one origin, corroboration left to COP. Every source is graded A2: a reliable source that
nothing else has confirmed (credibility 1 needs a second independence group, kit 0.6.2).
"""
import json
import re

from .common import digest
from tic_doctrine import geo  # noqa: E402  (common puts the kit on sys.path)

GRADE = "A2"
RULE = "corroborate-1: two independent origins, or one official source within its remit"

# Embassy alert subject (D:\Projects\_ideas\drafts\2026-11-18-cordon-alert-subject.py, tested on the 55 alerts of
# 18 Nov 2026 21:40 UTC: 45 subjects).
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DAY = r"\d{1,2}(?:\s*[–-]\s*\d{1,2})?"                      # 7, or a range 11–16
DATE = rf"{MONTH}\s+(?:{DAY},?\s+)?\d{{4}}"                    # November 7, 2026 / November 11–16, 2026 / November 2026
URL_TAIL = re.compile(r"\s+-\s+https?://\S+\s*$")              # Google News appends " - https://site/"
TRAILING_DATE = re.compile(
    rf"(?:\s*[–\-:,]\s*|\s+)\(?{DATE}\)?\s*$"                   # "– November 18, 2026", ", November 7, 2026"
    rf"|\s*\({DATE}\)?\s*$"                                    # "(November 17, 2026)" and the unclosed "(November 4, 2026"
)
LEADING_DATE = re.compile(rf"^([^:–]*Alert):\s*{DATE}\s*[–-]\s*")   # "Security Alert: October 28, 2026 – Mission Nigeria"


def cut_date(title: str) -> str:
    """An alert title with its own date cut: trailing, in brackets, or after "Alert:" (Nigeria). Dates inside the
    headline ("on Friday, October 30") are kept."""
    t = URL_TAIL.sub("", title.strip())
    t = TRAILING_DATE.sub("", t)
    t = LEADING_DATE.sub(lambda m: m.group(1) + ": ", t)
    return t.strip(" –-:,")


def subject_key(cut: str) -> str:
    """Casefolded, every run of punctuation and spaces one space: "Alert – U.S. Embassy" = "Alert: U.S. Embassy"."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", cut.casefold()).split())


def alert_subject(iso: str, title: str) -> str:
    return f"cordon:alert:{iso}:{digest(subject_key(cut_date(title)))[7:19]}"


# Ladders. last_change is raised or lowered when the level moves on the issuer's own ladder.
POSTURE_RANK = {"normal": 0, "authorized_departure": 1, "ordered_departure": 2, "suspended_operations": 3}


def moved(old, new) -> str:
    """raised or lowered from two ranks; changed when either is unknown or they are equal."""
    if isinstance(old, (int, float)) and isinstance(new, (int, float)) and old != new:
        return "raised" if new > old else "lowered"
    return "changed"


def stamp(props: dict, change: str, at: str | None) -> None:
    """State last_change and when it happened (finish() keeps the time no later than publication)."""
    if at:
        props["last_change"], props["last_change_at"] = change, at


def event(props: dict, start: str | None, end: str | None = None, precision: str | None = None) -> None:
    if not start:
        return
    props["event_start"] = start
    if end and end >= start:
        props["event_end"] = end
    if precision:
        props["event_time_precision"] = precision


def day(s: str | None) -> str | None:
    """A date or a time as midnight UTC of its day, for day precision."""
    return f"{s[:10]}T00:00:00Z" if s and re.match(r"\d{4}-\d{2}-\d{2}", s) else None


def signal(props: dict, name: str, value, unit: str) -> None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        props["signal"] = {"name": name, "value": value, "unit": unit}


def corroboration(state: str, basis: str | None, official: str | None, first: str | None) -> dict:
    return {"state": state, "basis": basis, "origins": 1, "official": official, "party_claim": False,
            "first_reported_at": first, "corroborated_at": first if state == "corroborated" else None, "rule": RULE}


# Why an item names its countries: an advisory is about the country wherever you are; a TFR, an airport program, an
# outbreak, a bulletin's airspace and an embassy alert are there. NGA warnings name no countries.
PLACE_BASIS = {"advisory": "subject", "posture": "subject", "canada": "subject", "safetravel": "subject",
               "fcdo": "subject", "faaprn": "location", "tfr": "location", "faa": "location", "cdc": "location",
               "czib": "location", "alert": "location"}


def lane(props: dict) -> str:
    return props["id"].split(":")[1]


def finish(feats: list[dict], health: dict) -> None:
    """The fields that follow from the lane: subject_id (the id, where the builder set none), place_basis, sea_areas,
    the A2 grade, sources[].lane for embassy posts, and each health lane's data_as_of (its newest item)."""
    newest, seas = {}, {}
    for f in feats:
        p = f["properties"]
        p.setdefault("subject_id", p["id"])
        if p.get("last_change_at") and p["last_change_at"] > p["published_at"]:
            p["last_change_at"] = p["published_at"]  # a source date ahead of the build: never after publication
        pb = PLACE_BASIS.get(lane(p))
        if pb and p.get("countries"):
            p["place_basis"] = pb
        if f.get("geometry") and p.get("precision_class") == "country":
            p["sea_areas"] = []  # a country's label point stands for the country, not a footprint at sea
        elif f.get("geometry"):
            # Several lanes place an item at the same country point: work each geometry out once.
            g = json.dumps(f["geometry"], sort_keys=True)
            if g not in seas:
                seas[g] = geo.sea_areas_for_geometry(f["geometry"])
            p["sea_areas"] = list(seas[g])
        for s in p.get("sources") or []:
            s["grade"] = GRADE
            if s.get("id", "").startswith("usembassy-"):
                s["lane"] = "us-embassy-alerts"
            key = s.get("lane") or s.get("id")
            if p.get("data_as_of") and p["data_as_of"] > newest.get(key, ""):
                newest[key] = p["data_as_of"]
    for key, e in health.items():
        when = e.get("newest_item") or newest.get(key)
        if when and not e.get("data_as_of"):
            e["data_as_of"] = when
