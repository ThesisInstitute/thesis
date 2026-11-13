"""Which vintage an ALFRED graph CSV response holds, and its rows.

``alfredgraph.csv?id=S&vintage_date=D`` answers with the header
``observation_date,S_<YYYYMMDD>``. The date in that header, its label, is not
always D, and the rows are those of the label's vintage. Observed on
2026-10-18 (docs/alfred-vintage-labels.md):

- ICSA asked for 2026-09-25 answered with label 2026-09-24, byte for byte the
  response for 2026-09-24. Seven of 291 daily ICSA dates in 2026 answered a
  day early. PAYEMS asked for 2026-10-01 answered with label 2026-09-29.
- The same query with its parameters reordered, ``?vintage_date=D&id=S``,
  answered with label D on each of those dates.
- A request for a day that has not begun in St. Louis is answered with that
  day's vintage under that day's label: PAYEMS asked for 2026-11-06 on
  2026-10-18 came back labeled 2026-10-18.

So a response is ALFRED's vintage of its label, whatever date was asked for.
This module reads the label and the rows; each reader decides what a label
earlier than the date it asked for can still show.
"""

from __future__ import annotations

import datetime as dt
import math
import re

ALFRED_VINTAGE_CSV = (
    "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
    "?id={series}&vintage_date={vintage}"
)
# The same query with its parameters in the other order. ALFRED answered it
# with the label asked for on every date the first spelling answered early.
ALFRED_VINTAGE_CSV_REORDERED = (
    "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
    "?vintage_date={vintage}&id={series}"
)
# St. Louis on standard time. Its date is never later than the date in St.
# Louis on daylight time, nor than the date in any zone east of it, so a day
# this clock has reached has begun there.
ST_LOUIS_STANDARD_TIME = dt.timezone(dt.timedelta(hours=-6))

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_VALUE = re.compile(r"-?\d+(?:\.\d+)?")
# ALFRED's marks for a date with no observation in a vintage.
_MISSING = ("", ".")


class AlfredVintageError(ValueError):
    """Bytes that are not ALFRED's vintage CSV of this series for this request."""


def alfred_today(now: dt.datetime | None = None) -> dt.date:
    """The latest vintage date it is safe to ask ALFRED for at ``now``.

    A request for a later day comes back as an earlier day's vintage. This is
    the date in St. Louis on standard time, which never runs ahead of the
    date there.
    """

    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("alfred_today needs an aware datetime")
    return current.astimezone(ST_LOUIS_STANDARD_TIME).date()


def alfred_vintage_label(raw: bytes, series_id: str, day: dt.date) -> dt.date:
    """The vintage date a response to a request for ``day`` names.

    The header must be exactly ``observation_date,<series_id>_<YYYYMMDD>``
    with a real date no later than ``day``. Anything else, including a label
    after ``day``, is not ALFRED's answer to that request: AlfredVintageError.
    """

    first = raw.split(b"\n", 1)[0]
    try:
        header = first.decode("utf-8").removesuffix("\r")
    except UnicodeDecodeError as exc:
        raise AlfredVintageError(
            f"ALFRED {series_id} {day}: the header is not UTF-8"
        ) from exc
    match = re.fullmatch(rf"observation_date,{re.escape(series_id)}_(\d{{8}})", header)
    label = None
    if match:
        token = match.group(1)
        try:
            label = dt.date(int(token[:4]), int(token[4:6]), int(token[6:]))
        except ValueError:
            label = None
    if label is None:
        raise AlfredVintageError(
            f"ALFRED {series_id} {day} is not a vintage CSV of {series_id} "
            f"(header {header[:60]!r})"
        )
    if label > day:
        raise AlfredVintageError(
            f"ALFRED {series_id} {day} is labeled {label}, a later vintage "
            "than the one asked for"
        )
    return label


def read_alfred_vintage(
    raw: bytes, series_id: str, day: dt.date
) -> tuple[dt.date, dict[str, float]]:
    """(label, {observation date: value}) from ALFRED's answer for ``day``.

    The label is alfred_vintage_label's. Every row after the header must be
    ``YYYY-MM-DD,<number>`` or a date with ALFRED's no-observation mark (an
    empty value or "."), in strictly increasing date order; a date with no
    observation is left out of the rows. Anything else is refused.
    """

    label = alfred_vintage_label(raw, series_id, day)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AlfredVintageError(f"ALFRED {series_id} {day} is not UTF-8") from exc
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    rows: dict[str, float] = {}
    previous = ""
    for number, line in enumerate(lines[1:], start=2):
        observation, separator, value = line.partition(",")
        if (
            not separator
            or not _DATE.fullmatch(observation)
            or observation <= previous
            or not (value in _MISSING or _VALUE.fullmatch(value))
        ):
            raise AlfredVintageError(
                f"ALFRED {series_id} {day} line {number} is not a dated "
                f"observation after {previous or 'the header'} ({line[:40]!r})"
            )
        try:
            dt.date.fromisoformat(observation)
        except ValueError as exc:
            raise AlfredVintageError(
                f"ALFRED {series_id} {day} line {number} names no real date "
                f"({line[:40]!r})"
            ) from exc
        previous = observation
        if value in _MISSING:
            continue
        parsed = float(value)
        if not math.isfinite(parsed):
            raise AlfredVintageError(
                f"ALFRED {series_id} {day} line {number} overflows a float "
                f"({line[:40]!r})"
            )
        rows[observation] = parsed
    return label, rows
