"""Closed, source-specific publication-field semantics.

Transport Date/Last-Modified and file-generation metadata are never publication
evidence. In particular, the BEA calendar parser reads DTSTART, not DTSTAMP.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from html import unescape
from html.parser import HTMLParser

from .parsers import _bea_release_title

BEA_CALENDAR_URL = (
    "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
)
BEA_CALENDAR_PARSER = "bea-gdp-advance-calendar-v1"
BEA_RELEASE_PARSER = "bea-gdp-advance-embargo-v1"
STATCAN_PUBLICATION_PARSER = "statcan-wds-release-time-v1"
STATCAN_CPI_PORTAL_URL = (
    "https://www.statcan.gc.ca/en/subjects-start/prices_and_price_indexes/"
    "consumer_price_indexes"
)
STATCAN_CPI_RELEASE_PARSER = "statcan-cpi-portal-next-release-v1"


class _Element:
    def __init__(self, tag, attributes=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attributes), parent
        self.children = []

    def text(self):
        return " ".join(
            child.text() if isinstance(child, _Element) else child
            for child in self.children
        )

    def elements(self):
        yield self
        for child in self.children:
            if isinstance(child, _Element):
                yield from child.elements()


class _Portal(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.current = _Element("root")

    def handle_starttag(self, tag, attrs):
        element = _Element(tag, attrs, self.current)
        self.current.children.append(element)
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            self.current = element

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(_Element(tag, attrs, self.current))

    def handle_endtag(self, tag):
        element = self.current
        while element.parent is not None:
            if element.tag == tag:
                self.current = element.parent
                break
            element = element.parent

    def handle_data(self, data):
        if self.current.tag not in {"script", "style"}:
            self.current.children.append(data)


def statcan_cpi_next_release(raw: bytes, period: str) -> str:
    """Parse one dated CPI portal notice; ambiguous year rollovers refuse.

    The requested period and release day come from explicit source text. The
    year is bound to the exact current CPI indicator and dated document context,
    never the collector clock. This version supports same-year notices only.
    """
    if not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", period):
        raise ValueError("StatCan CPI measurement period must be YYYY-MM")
    document = _Portal()
    document.feed(raw.decode("utf-8"))
    elements = list(document.root.elements())
    indicators = [
        element
        for element in elements
        if element.attrs.get("id") == "indicator-box-geo-0-ind-3665-1"
    ]
    if len(indicators) != 1:
        raise ValueError("expected exactly one Canada CPI indicator")
    titles = [
        " ".join(element.text().split())
        for element in indicators[0].elements()
        if "indicator-title" in element.attrs.get("class", "").split()
    ]
    periods = [
        " ".join(element.text().split())
        for element in indicators[0].elements()
        if "indicator-refper" in element.attrs.get("class", "").split()
    ]
    if titles != ["Consumer Price Index - Canada"] or len(periods) != 1:
        raise ValueError("wrong or ambiguous Canada CPI indicator")
    try:
        current = dt.datetime.strptime(periods[0], "(%B %Y)").date()
    except ValueError as exc:
        raise ValueError("CPI indicator lacks an explicit month and year") from exc
    requested = dt.date.fromisoformat(period + "-01")
    if requested.year != current.year or requested.month != current.month + 1:
        raise ValueError("stale or ambiguous cross-year CPI announcement")
    headings = [
        element
        for element in elements
        if element.tag == "h3" and " ".join(element.text().split()) == "Next release"
    ]
    if len(headings) != 1:
        raise ValueError("expected exactly one CPI next-release announcement")
    heading = headings[0]
    siblings = [
        child for child in heading.parent.children if isinstance(child, _Element)
    ]
    index = siblings.index(heading) + 1
    if index >= len(siblings) or siblings[index].tag != "p":
        raise ValueError("CPI next-release paragraph is missing")
    announcement = " ".join(siblings[index].text().split())
    match = re.fullmatch(
        r"The CPI for ([A-Z][a-z]+) will be released on "
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
        r"([A-Z][a-z]+) (\d{1,2})\.",
        announcement,
    )
    if not match or match[1] != requested.strftime("%B"):
        raise ValueError("CPI notice does not name the requested measurement month")
    try:
        release = dt.datetime.strptime(
            f"{match[3]} {match[4]} {requested.year}", "%B %d %Y"
        ).date()
    except ValueError as exc:
        raise ValueError("invalid CPI release day") from exc
    if release <= requested or release.strftime("%A") != match[2]:
        raise ValueError("CPI release date/weekday or year contradicts its context")
    modified = [
        element.attrs["content"]
        for element in elements
        if element.tag == "meta"
        and element.attrs.get("name") == "dcterms.modified"
        and "content" in element.attrs
    ]
    modified += [
        " ".join(element.text().split())
        for element in elements
        if element.tag == "time" and element.attrs.get("property") == "dateModified"
    ]
    if not modified or len(set(modified)) != 1:
        raise ValueError("CPI document date is missing or conflicting")
    dated = dt.date.fromisoformat(modified[0])
    if dated.year != current.year or not current <= dated < release:
        raise ValueError("CPI document date does not authenticate the indicator year")
    return release.isoformat()


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
