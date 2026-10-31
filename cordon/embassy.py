"""US embassy alerts: each post's WordPress RSS feed, <cc>.usembassy.gov/category/alert/feed/ (no combined feed).

Polled for the posts that matter most: every country at advisory level 3 or 4, plus a fixed list. The alert type is
only in the title prefix ("Security Alert: ...", "Demonstration Alert - ..."). A post whose site fails is recorded
in health and skipped; on 31 Oct 2026 every post site served a "Technical Difficulties" page (HTTP 403).
"""
import html
import re
from datetime import timezone
from email.utils import parsedate_to_datetime

from .common import fetch_or_none, now_utc

# ISO code -> post host where it isn't <iso>.usembassy.gov
HOST = {"GB": "uk.usembassy.gov"}
EXTRA_POSTS = ["UA", "IL", "PS", "LB", "IQ", "JO", "SA", "AE", "QA", "KW", "BH", "OM", "EG", "TR", "PK", "IN",
               "TW", "KR", "PH", "VN", "MX", "VE", "CO", "CU", "HT", "NG", "ET", "SO", "KE", "CD", "SD"]
NO_POST = {"KP", "IR", "SY"}   # no US embassy (protecting-power or virtual sites only)
TYPE_RE = re.compile(r"^\s*([A-Za-z ]{3,40}?)\s+(?:Alert|Message)\s*[:\-–—]", re.I)


def posts(advisories: dict) -> list[str]:
    hot = {r["iso"] for r in advisories.values() if r["level"] >= 3 and r["iso"]}
    return sorted((hot | set(EXTRA_POSTS)) - NO_POST)


def feed_url(iso: str) -> str:
    host = HOST.get(iso, f"{iso.lower()}.usembassy.gov")
    return f"https://{host}/category/alert/feed/"


def parse_rss(xml: str, iso: str) -> list[dict]:
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def tag(name):
            m = re.search(rf"<{name}>(.*?)</{name}>", item, re.S)
            if not m:
                return ""
            v = m.group(1).strip()
            if v.startswith("<![CDATA[") and v.endswith("]]>"):
                v = v[9:-3]
            return html.unescape(re.sub(r"<[^>]+>", " ", v)).strip()
        title, link, pub = tag("title"), tag("link"), tag("pubDate")
        if not title or not link.startswith(("http://", "https://")):
            continue
        try:
            when = parsedate_to_datetime(pub).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if pub else None
        except (TypeError, ValueError):
            when = None
        m = TYPE_RE.match(title)
        out.append({"iso": iso, "title": re.sub(r"\s+", " ", title), "link": link, "published_at": when,
                    "type": (m.group(1).strip().lower() if m else "alert")})
    return out


def collect(advisories: dict, previous: dict | None = None, when: str | None = None, fetch=fetch_or_none):
    """({iso: [alerts]}, {iso: error}). A failing post keeps its previous alerts."""
    when = when or now_utc()
    out, errors = dict(previous or {}), {}
    for iso in posts(advisories):
        body, err = fetch(feed_url(iso), 25)
        if body is None:
            errors[iso] = err
            continue
        try:
            out[iso] = parse_rss(body.decode("utf-8", "replace"), iso)[:10]
        except Exception as e:  # noqa: BLE001
            errors[iso] = f"parse: {type(e).__name__}"
    return out, errors
