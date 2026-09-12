"""Closed, source-specific publication-field semantics.

Transport Date/Last-Modified and file-generation metadata are never publication
evidence. In particular, the BEA calendar parser reads DTSTART, not DTSTAMP.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from html import unescape

from .parsers import _bea_release_title

BEA_CALENDAR_URL = (
    "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
)
BEA_CALENDAR_PARSER = "bea-gdp-advance-calendar-v1"
BEA_RELEASE_PARSER = "bea-gdp-advance-embargo-v1"
STATCAN_PUBLICATION_PARSER = "statcan-wds-release-time-v1"


def quarter_start(period: str) -> str:
    match = re.fullmatch(r"(\d{4})-Q([1-4])", period)
    if not match:
        raise ValueError("BEA measurement period must be YYYY-Q1 through YYYY-Q4")
    return f"{match[1]}-{(int(match[2]) - 1) * 3 + 1:02d}"


def bea_calendar_publication(raw: bytes, period: str) -> str:
    """Find exactly this quarter's advance GDP release in the official ICS."""
    text = raw.decode("utf-8")
    text = re.sub(r"\r?\n[ \t]", "", text)
    if (
        not text.startswith("BEGIN:VCALENDAR")
        or "PRODID://BEA-Release-Calendar-Subscription//" not in text
    ):
        raise ValueError("not a BEA release-subscription calendar")
    expected = _bea_release_title(quarter_start(period))
    matches = []
    for event in re.findall(r"BEGIN:VEVENT\r?\n(.*?)END:VEVENT", text, re.S):
        fields: dict[str, str] = {}
        for line in event.splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            name = key.split(";", 1)[0]
            if name in fields:
                raise ValueError("duplicate calendar event field")
            fields[name] = value.replace(r"\,", ",").replace(r"\;", ";")
        if fields.get("SUMMARY") != expected:
            continue
        if fields.get("STATUS") == "CANCELLED":
            raise ValueError("registered BEA release has been cancelled")
        start = fields.get("DTSTART", "")
        if not re.fullmatch(r"\d{8}T\d{6}Z", start):
            raise ValueError("BEA DTSTART lacks an explicit UTC release instant")
        matches.append(
            dt.datetime.strptime(start, "%Y%m%dT%H%M%SZ").replace(
                tzinfo=dt.timezone.utc
            )
        )
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {expected!r} advance release, found {len(matches)}"
        )
    return matches[0].isoformat().replace("+00:00", "Z")


def bea_embargo_publication(raw: bytes, period: str) -> str:
    text = raw.decode("utf-8")
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    visible = " ".join(unescape(re.sub(r"<[^>]+>", " ", text)).split())
    if _bea_release_title(quarter_start(period)) not in visible:
        raise ValueError("BEA page does not name the exact advance-release period")
    matches = re.findall(
        r"EMBARGOED UNTIL RELEASE AT (\d{1,2}:\d{2})\s+([ap])\.m\.\s+(EDT|EST),\s+"
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
        r"([A-Z][a-z]+ \d{1,2}, \d{4})",
        visible,
    )
    if len(matches) != 1:
        raise ValueError("BEA page lacks one supported explicit embargo timestamp")
    clock, meridiem, zone, date = matches[0]
    local = dt.datetime.strptime(
        f"{date} {clock} {meridiem.upper()}M", "%B %d, %Y %I:%M %p"
    )
    from zoneinfo import ZoneInfo

    aware = local.replace(tzinfo=ZoneInfo("America/New_York"))
    if aware.tzname() != zone:
        raise ValueError("BEA embargo zone contradicts its date")
    return aware.isoformat()


def statcan_publication(raw: bytes, vector: int, period: str) -> str | None:
    payload = json.loads(raw)
    if (
        not isinstance(payload, list)
        or len(payload) != 1
        or payload[0].get("status") != "SUCCESS"
    ):
        raise ValueError("invalid StatCan WDS response")
    obj = payload[0].get("object") or {}
    if obj.get("vectorId") != vector:
        raise ValueError("wrong StatCan vector")
    rows = [
        row
        for row in obj.get("vectorDataPoint", [])
        if str(row.get("refPer", ""))[:7] == period
    ]
    if len(rows) != 1:
        raise ValueError("expected one StatCan observation for period")
    value = rows[0].get("releaseTime")
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?", value
    ):
        raise ValueError("unsupported StatCan publication value")
    return value
