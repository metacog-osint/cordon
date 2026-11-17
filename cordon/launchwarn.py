"""Launch, space-debris and reentry warnings: the time windows, hazard and cancels in an NGA warning's own words.

Ported from Orbit's NGA parser (orbit/navwarn.py at 4cd3fdc, 17 Nov 2026) so that Cordon, NGA's only live reader in
the suite, publishes them and Launch reads them from Cordon's feed (Tom's decision, 17 Nov 2026: "Cordon publishes").
Cordon's `launch` category also holds missile firings; those carry no launch hazard here (`hazard` None), which is
how a reader tells them apart. Windows are UTC [start, end] pairs; a window whose date or time does not exist (a typo
in the warning) is left out and the rest are still read.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

HAZARD = re.compile(r"ROCKET LAUNCH\w*(?: SUSPENDED)?|SPACE DEBRIS|SPACE VEHICLE|SPACECRAFT|RE-?ENTRY")
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
MON = "(" + "|".join(MONTHS) + ")"
COORD = re.compile(r"(\d{1,2})-(\d{2}(?:\.\d+)?)\s?([NS])[,\s]+(\d{1,3})-(\d{2}(?:\.\d+)?)\s?([EW])")
SPAN = re.compile(r"\b(\d{2})(\d{2})(\d{2})Z TO (\d{2})(\d{2})(\d{2})Z\b")
DAILY = re.compile(r"\b(\d{2})(\d{2})Z TO (\d{2})(\d{2})Z (?:COMMENCING )?DAILY (\d{1,2})(?: " + MON + r")?"
                   r" (?:THRU|THR|TO) (\d{1,2}) " + MON)
DAILY_AND = re.compile(r"\b(\d{2})(\d{2})Z TO (\d{2})(\d{2})Z (?:COMMENCING )?DAILY ((?:\d{1,2}(?:, | AND ))+\d{1,2}) "
                       + MON)
CANCEL_THIS = re.compile(r"CANCEL THIS MSG (\d{2})(\d{2})(\d{2})Z " + MON + r"(?: (\d{2}))?")
CANCEL_OTHER = re.compile(r"CANCEL (?!THIS)((?:HYDROPAC|HYDROLANT|HYDROARC|NAVAREA [IVX]+) )?(\d{3,4})/(\d{2})")
AREA_LABEL = re.compile(r"(?m)^\s*([A-Z])\.\s+")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _year_for(month: int, issued: datetime) -> int:
    """A window's year: the warning's own year, or the next one for a January window issued in December."""
    return issued.year + 1 if month < issued.month - 6 else issued.year


def _clock_ok(hh: int, mm: int) -> bool:
    """A time of day as warnings write it: 0000-2359, or 2400 for the end of the day."""
    return (0 <= hh <= 23 and 0 <= mm <= 59) or (hh == 24 and mm == 0)


def _when(day: int, hh: int, mm: int, month: int, issued: datetime) -> datetime:
    """A day, time and month in a warning's text as UTC. 2400Z is midnight at the end of that day. Raises ValueError
    on a date or time that does not exist (a typo such as 1190Z, or the 31st of a 30-day month)."""
    if not _clock_ok(hh, mm):
        raise ValueError(f"no such time {hh:02d}{mm:02d}Z")
    return datetime(_year_for(month, issued), month, day, tzinfo=timezone.utc) + timedelta(hours=hh, minutes=mm)


def _next_month(month: int, step: int) -> int:
    return (month - 1 + step) % 12 + 1


SPAN_OWN_MON = re.compile(r"[ ,]*" + MON + r"\b")  # a month written straight after a window ("... TO 052400Z DEC")
NEXT_MON = re.compile(r"\b" + MON + r"\b")
MONTH_TURN_DAYS = 15  # a list's day number jumping by more than this is a month change (31 -> 01), not an alternate


def _span_months(t: str, spans: list) -> list[tuple[int, int] | None]:
    """The (start month, end month) of each DDHHMMZ TO DDHHMMZ window. A window followed by a month takes it as its
    end's month. A window without one takes the month of the window next to it, one month on (or back) only where
    the day number jumps by more than MONTH_TURN_DAYS (310104Z TO 310351Z, 010039Z TO 010326Z SEP: the first is
    31 Aug); alternates listed out of order a few days apart (252100Z TO 261100Z AUG, ALTERNATE 241200Z TO
    251100Z ...) stay in the month. With no month after any window, the next month named in the text anchors the
    last one. None where no month can be found."""
    days = [(int(m.group(1)), int(m.group(4))) for m in spans]
    out: list[tuple[int, int] | None] = [None] * len(spans)
    for i, m in enumerate(spans):
        own = SPAN_OWN_MON.match(t, m.end())
        if own:
            end = MONTHS.index(own.group(1)) + 1
            out[i] = (_next_month(end, -1) if days[i][0] > days[i][1] else end, end)
    if spans and not any(out):
        later = NEXT_MON.search(t, spans[-1].end())
        if later:
            end = MONTHS.index(later.group(1)) + 1
            out[-1] = (_next_month(end, -1) if days[-1][0] > days[-1][1] else end, end)
    for i in range(len(spans) - 2, -1, -1):  # back from each named month, over the windows listed before it
        if out[i] is None and out[i + 1] is not None:
            end = (_next_month(out[i + 1][0], -1) if days[i][1] > days[i + 1][0] + MONTH_TURN_DAYS
                   else out[i + 1][0])
            out[i] = (_next_month(end, -1) if days[i][0] > days[i][1] else end, end)
    for i in range(1, len(spans)):  # on from the last named month, over the windows listed after it
        if out[i] is None and out[i - 1] is not None:
            start = (_next_month(out[i - 1][1], 1) if days[i][0] < days[i - 1][1] - MONTH_TURN_DAYS
                     else out[i - 1][1])
            out[i] = (start, _next_month(start, 1) if days[i][1] < days[i][0] else start)
    return out


def parse_windows(text: str, issued: datetime) -> tuple[list[dict], str]:
    """Time windows in a warning's own words, as UTC [start, end] pairs, and how they were written:
    'single', 'alternates' (the first window, then the issuer's alternates), 'daily', or '' if none parsed."""
    t = re.sub(r"\s+", " ", text)
    out: list[dict] = []
    mode = ""
    # A window whose date or time does not exist (a typo in the warning) is left out; the rest are still read.
    for m in DAILY.finditer(t):
        h0, m0, h1, m1, d0, mon0, d1, mon1 = m.groups()
        h0, m0, h1, m1 = int(h0), int(m0), int(h1), int(m1)
        end_month = MONTHS.index(mon1) + 1
        start_month = MONTHS.index(mon0) + 1 if mon0 else end_month
        try:
            day = _when(int(d0), 0, 0, start_month, issued)
            last = _when(int(d1), 0, 0, end_month, issued)
        except ValueError:
            continue
        if not (_clock_ok(h0, m0) and _clock_ok(h1, m1)):
            continue
        while day <= last and len(out) < 62:
            s = day + timedelta(hours=h0, minutes=m0)
            e = day + timedelta(hours=h1, minutes=m1)
            if e <= s:
                e += timedelta(days=1)
            out.append({"start": _iso(s), "end": _iso(e)})
            day += timedelta(days=1)
        mode = "daily"
    for m in DAILY_AND.finditer(t):
        h0, m0, h1, m1, days, mon = m.groups()
        h0, m0, h1, m1 = int(h0), int(m0), int(h1), int(m1)
        if not (_clock_ok(h0, m0) and _clock_ok(h1, m1)):
            continue
        for d in re.findall(r"\d{1,2}", days):
            try:
                day = _when(int(d), 0, 0, MONTHS.index(mon) + 1, issued)
            except ValueError:
                continue
            s = day + timedelta(hours=h0, minutes=m0)
            e = day + timedelta(hours=h1, minutes=m1)
            if e <= s:
                e += timedelta(days=1)
            out.append({"start": _iso(s), "end": _iso(e)})
        mode = "daily"
    spans = list(SPAN.finditer(t))
    for m, months in zip(spans, _span_months(t, spans)):
        if not months:
            continue
        d0, h0, n0, d1, h1, n1 = (int(g) for g in m.groups())
        try:
            s = _when(d0, h0, n0, months[0], issued)
            e = _when(d1, h1, n1, months[1], issued)
        except ValueError:
            continue
        if e <= s:
            continue
        out.append({"start": _iso(s), "end": _iso(e)})
    if spans:
        mode = "alternates" if "ALTERNATE" in t else ("single" if len(spans) == 1 and mode != "daily" else mode or "list")
    out.sort(key=lambda w: w["start"])
    seen, uniq = set(), []
    for w in out:
        k = (w["start"], w["end"])
        if k not in seen:
            seen.add(k)
            uniq.append(w)
    return uniq, mode


def parse_coords(text: str) -> list[list[float]]:
    """Every vertex as [lon, lat], longitudes unwrapped so an area across 180 degrees stays one shape."""
    pts = []
    for m in COORD.finditer(text):
        la = int(m.group(1)) + float(m.group(2)) / 60
        lo = int(m.group(4)) + float(m.group(5)) / 60
        la = -la if m.group(3) == "S" else la
        lo = -lo if m.group(6) == "W" else lo
        if pts:
            while lo - pts[-1][0] > 180:
                lo -= 360
            while pts[-1][0] - lo > 180:
                lo += 360
        pts.append([round(lo, 4), round(la, 4)])
    return pts


def parse_body(text: str, issued: datetime) -> dict | None:
    """One warning's text -> hazard, regions, areas (each with its own windows when the text gives them), the
    message-level windows, its cancel time and the warnings it cancels. None if it is not about a launch."""
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    full = "\n".join(lines)
    hz = HAZARD.search(full)
    if not hz:
        return None
    regions = []
    for ln in lines:
        if not ln:
            continue
        if ln.startswith("1.") or HAZARD.search(ln) or re.match(r"\d{4}Z|\d{6}Z", ln):
            break
        regions.append(ln.rstrip("."))
    expires = None
    cm = CANCEL_THIS.search(full)
    if cm:
        d, h, n, mon, yy = cm.groups()
        exp_issued = issued.replace(year=2000 + int(yy)) if yy else issued
        try:
            expires = _iso(_when(int(d), int(h), int(n), MONTHS.index(mon) + 1, exp_issued))
        except ValueError:  # a cancel time that does not exist: no expiry rather than no warning
            expires = None
    cancels = [((m.group(1) or "").strip() + " " + m.group(2) + "/" + m.group(3)).strip()
               for m in CANCEL_OTHER.finditer(full)]
    # Body of the hazard paragraph: from the hazard words to the next numbered paragraph or the cancel line.
    start = hz.start()
    stop = re.compile(r"(?m)^\d\.\s|CANCEL ").search(full, hz.end())
    para = full[start: stop.start() if stop else len(full)]
    labels = list(AREA_LABEL.finditer(para))
    blocks = []
    if labels:
        head = para[: labels[0].start()]
        for i, lb in enumerate(labels):
            blocks.append((lb.group(1), para[lb.end(): labels[i + 1].start() if i + 1 < len(labels) else len(para)]))
    else:
        head, blocks = para, [("", para)]
    windows, mode = parse_windows(head, issued)
    areas = []
    for label, btxt in blocks:
        coords = parse_coords(btxt)
        own, own_mode = parse_windows(btxt, issued) if labels else ([], "")
        if not coords:
            continue
        area = {"label": label, "coords": coords}
        if own:
            area["windows"], area["window_mode"] = own, own_mode
        areas.append(area)
    if not windows:  # every area carries its own windows (NAVAREA XII style): the message's are their union
        by_start: dict[str, str] = {}  # areas opening together are one window; it ends when the last area closes
        for a in areas:
            for w in a.get("windows", []):
                by_start[w["start"]] = max(by_start.get(w["start"], ""), w["end"])
        windows = [{"start": k, "end": v} for k, v in sorted(by_start.items())]
        modes = {a.get("window_mode") for a in areas if a.get("window_mode")}
        mode = modes.pop() if len(modes) == 1 else ("alternates" if "ALTERNATE" in para else "list")
    window_text = re.split(r"\bIN AREAS? BOUND|\bAREAS? BOUNDED", re.sub(r"\s+", " ", head))[0].strip(" ,:")
    window_text = window_text[len(hz.group(0)):].strip(" ,.:") if window_text.startswith(hz.group(0)) else window_text
    return {"hazard": hz.group(0).lower().replace("re-entry", "reentry"),
            "regions": regions, "areas": areas, "windows": windows, "window_mode": mode,
            "window_text": window_text[:300], "expires": expires, "cancels": cancels}



SERIES_CODE = {"NAVAREA IV": "4", "NAVAREA XII": "12", "HYDROLANT": "A", "HYDROPAC": "P", "HYDROARC": "C"}


def measures(text: str, issued: str | None, series: str | None) -> dict:
    """The feed's launch fields for one warning in Cordon's `launch` category. `issued` is UTC ISO
    ('2026-11-13T11:05:00Z'), `series` the warning's own series ('HYDROPAC'), used for a cancel that names only a
    number. `hazard` is None for a missile firing or other wording with no launch, debris or reentry hazard.
    `cancels` names each warning this one cancels, with its Cordon id. `area_windows` is given only when lettered
    areas carry their own windows (NAVAREA XII style); `windows` is then their union."""
    when = datetime.strptime(issued, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if issued else None
    body = parse_body(text or "", when) if when else None
    if body is None:
        return {"hazard": None}
    cancels = []
    for c in body["cancels"]:
        m = re.match(r"(?:(.+) )?(\d{3,4})/(\d{2})$", c)
        name = (m.group(1) or series or "").strip()
        code = SERIES_CODE.get(name)
        cancels.append({"number": f"{name} {m.group(2)}/{m.group(3)}".strip(),
                        "id": f"cordon:navwarn:{code}-{m.group(2)}-20{m.group(3)}" if code else None})
    out = {"hazard": body["hazard"], "windows": body["windows"], "window_mode": body["window_mode"],
           "window_text": body["window_text"], "cancels": cancels}
    own = [{"label": a["label"], "windows": a["windows"], "window_mode": a.get("window_mode", "")}
           for a in body["areas"] if a.get("windows")]
    if own:
        out["area_windows"] = own
    return out
