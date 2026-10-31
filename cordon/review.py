"""The review queue: every embassy departure-status change Cordon reads from advisory text goes to a person.

Cordon has no field to read posture from, only State's wording, so each change becomes one GitHub issue (opened by
the hourly workflow, label cordon-review) quoting the sentence that matched and linking the advisory. The issue title
is the change's stable key, so a change is never filed twice.
"""
from datetime import datetime, timedelta, timezone

WORDS = {"normal": "normal operations", "authorized_departure": "authorized departure",
         "ordered_departure": "ordered departure", "suspended_operations": "suspended operations"}
WINDOW_DAYS = 30


def pending(changes: list[dict], now: datetime | None = None) -> list[dict]:
    """[{title, body}] for posture changes in the last WINDOW_DAYS days."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for c in changes:
        if c.get("lane") != "state" or c.get("kind") != "posture" or c.get("at", "") < cutoff:
            continue
        frm, to = WORDS.get(c.get("from"), c.get("from")), WORDS.get(c.get("to"), c.get("to"))
        title = f"Review: {c['name']} embassy status {frm} to {to} ({c['at'][:10]}, {c['key']})"
        body = "\n".join([
            f"Cordon read a change in the US embassy's status for **{c['name']}** from the travel advisory text:",
            "", f"- Was: {frm}", f"- Now: {to}", f"- Detected: {c['at']}", f"- Advisory: {c.get('link')}", "",
            "Sentence that matched:", "", f"> {c.get('sentence') or '(no sentence: the departure wording was removed)'}",
            "", "Please check the advisory and close this issue with a comment: **confirmed**, or **wrong match** with "
            "what it should have read. Until then the map shows this status as read from the text.",
        ])
        out.append({"title": title, "body": body + "\n"})
    return out
