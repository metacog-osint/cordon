"""Shared helpers: fetching, time, JSON files, health, and country codes. Standard library only."""
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))
from tic_doctrine import geo  # noqa: E402

USER_AGENT = "Cordon/0.1 (The Intelligence Company; https://github.com/metacog-osint/cordon)"
MAX_BYTES = 8 * 1024 * 1024


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_utc(value: str) -> str | None:
    """An ISO 8601 time with any offset, as UTC ending in Z."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, timeout: int = 40) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError(f"response over {MAX_BYTES} bytes")
    return body


def fetch_or_none(url: str, timeout: int = 40):
    """(body, None) or (None, short error): a failing source never stops the run."""
    try:
        return fetch(url, timeout), None
    except Exception as e:  # noqa: BLE001 - every failure is reported, none is fatal
        return None, describe(e)


def describe(e: Exception) -> str:
    """An error without the URL (none of ours carry secrets, but keep logs short)."""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"network: {type(e.reason).__name__}"
    return type(e).__name__ + (f": {e}" if str(e) else "")


def load(name: str, default=None):
    p = DATA / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save(name: str, obj) -> None:
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False) + "\n",
                             encoding="utf-8", newline="\n")


def append_jsonl(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    DATA.mkdir(exist_ok=True)
    with (DATA / name).open("a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_jsonl(name: str) -> list[dict]:
    p = DATA / name
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def health(source: str, ok: bool, detail: str = "", when: str | None = None) -> None:
    """Record a source's latest attempt in data/health.json: last_ok, last_error, consecutive failures."""
    when = when or now_utc()
    h = load("health.json", {})
    s = h.setdefault(source, {"last_ok": None, "last_error": None, "failures": 0})
    s["checked_at"] = when
    if ok:
        s.update({"last_ok": when, "failures": 0, "detail": detail})
    else:
        s.update({"last_error": when, "failures": s.get("failures", 0) + 1, "detail": detail})
    save("health.json", h)


_FIPS = None


def fips_to_iso(code: str) -> str | None:
    """GDELT/State FIPS 10-4 country code to ISO 3166-1 alpha-2 (data/fips_iso.json, from Natural Earth)."""
    global _FIPS
    if _FIPS is None:
        _FIPS = load("fips_iso.json", {}).get("codes", {})
    return (_FIPS.get(code) or {}).get("iso")


def point(iso: str):
    """GeoJSON Point at the kit's label point for a country, or None."""
    p = geo.point(iso)
    return {"type": "Point", "coordinates": [p[1], p[0]]} if p else None
