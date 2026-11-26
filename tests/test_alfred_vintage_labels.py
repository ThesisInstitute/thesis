"""ALFRED's vintage label: which day's vintage a response holds, and who may use it.

``alfredgraph.csv?id=S&vintage_date=D`` sometimes answers with an earlier day's
vintage, named in its header (docs/alfred-vintage-labels.md). The fixtures in
tests/fixtures/alfred_vintage_labels/ are real ALFRED responses fetched
2026-10-18 (captures.json gives each request, its time and digest); the ICSA
2026-09-24 and 2026-09-25 responses are the claims leg's fixtures, the same
bytes.

Invariants tested here:

1. alfred_vintage_label returns the header's date exactly when the header is
   ``observation_date,<series>_<YYYYMMDD>``, in ASCII digits, with a real date
   no later than the day asked for; anything else raises AlfredVintageError.
2. read_alfred_vintage's rows are exactly the header's vintage's dated,
   non-missing observations; any other line is refused.
3. The generic ALFRED leg (read_alfred_vintage_of) returns rows only from a
   response labeled the day it asked for (ALFRED_VINTAGE_LABEL_LAG = 0); asks
   nothing for a day after alfred_today(); retries the reordered spelling
   only after an earlier label; and stops at a later label, invalid bytes or
   an HTTP error.
4. alfred_today never runs ahead of the date in US Central, US Eastern or UTC.
5. Custody, through verify_run, refuses a resolver fact whose own ALFRED
   archive is labeled other than its sourceVintage or archived under another
   series or day; it judges every ALFRED vintage header, and every real
   resolver run on this branch passes.
6. On a response labeled the day asked for, the new reader's rows equal the
   pre-label parser's; on a lagged one the old parser found no rows (the cell
   deferred as "not yet published") and the new reader refuses it by name.
   On ASCII headers the claims leg's header rule accepts and refuses exactly
   what #345's did; it refuses non-ASCII digits, which #345 took in the year.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import pathlib
import re
import sys
import zoneinfo
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolution_status  # noqa: E402
import resolve_pending  # noqa: E402
import verify_custody  # noqa: E402
from alfred_vintage import (  # noqa: E402
    ALFRED_VINTAGE_CSV,
    ALFRED_VINTAGE_CSV_REORDERED,
    AlfredVintageError,
    alfred_today,
    alfred_vintage_label,
    read_alfred_vintage,
)

FIXTURES = ROOT / "tests" / "fixtures"
LABELS = FIXTURES / "alfred_vintage_labels"
PAYROLL_REF = "bls.ces.total_nonfarm_payroll_change.2026_09.first_print"
PAYROLL_STEM = "bls.ces.total_nonfarm_payroll_change"
RELEASE = dt.date(2026, 10, 2)


def real(name: str) -> bytes:
    """A real ALFRED response from the label fixtures or the claims fixtures."""
    path = LABELS / f"{name}.csv.gz"
    if not path.exists():
        path = FIXTURES / f"alfred_{name}.csv.gz"
    return gzip.decompress(path.read_bytes())


def canonical(series: str, day: dt.date) -> str:
    return ALFRED_VINTAGE_CSV.format(series=series, vintage=day.isoformat())


def reordered(series: str, day: dt.date) -> str:
    return ALFRED_VINTAGE_CSV_REORDERED.format(series=series, vintage=day.isoformat())


def vintage_csv(series: str, label: dt.date, rows: list[tuple[str, str]]) -> bytes:
    lines = [f"observation_date,{series}_{label:%Y%m%d}"]
    lines += [f"{day},{value}" for day, value in rows]
    return ("\n".join(lines) + "\n").encode()


class FakeAlfred:
    """ALFRED as a URL -> body map; None is an HTTP error. Records each request."""

    def __init__(self, responses: dict[str, bytes | None]):
        self.responses = responses
        self.requested: list[str] = []

    def __call__(self, url: str) -> bytes | None:
        self.requested.append(url)
        if url not in self.responses:
            raise AssertionError(f"unexpected ALFRED request {url}")
        return self.responses[url]


def frozen_alfred_today(day: dt.date):
    return mock.patch.object(resolve_pending, "alfred_today", lambda: day)


# --- the fixtures are the bytes captures.json says they are -------------------


def test_fixtures_are_the_captured_bytes() -> None:
    captures = json.loads((LABELS / "captures.json").read_text())
    assert len(captures) == 10
    for capture in captures:
        raw = gzip.decompress((ROOT / capture["fixture"]).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == capture["sha256"]
        assert len(raw) == capture["bytes"]
        assert raw.split(b"\n", 1)[0].decode() == capture["header"]
        # Only the probe asked for a day after 2026-10-18, and on a spelling
        # no resolver reads.
        asked = re.search(r"vintage_date=(\d{4}-\d{2}-\d{2})", capture["url"])
        assert asked is not None
        if dt.date.fromisoformat(asked.group(1)) > dt.date(2026, 10, 18):
            assert "thesis_lag_probe=" in capture["url"]
    listed = {
        (ROOT / capture["fixture"]).name
        for capture in captures
        if (ROOT / capture["fixture"]).parent == LABELS
    }
    assert {path.name for path in LABELS.glob("*.csv.gz")} == listed


# --- invariant 1 and 2 on real bytes -------------------------------------------


@pytest.mark.parametrize(
    ("name", "series", "asked", "label"),
    [
        # The claims leg's finding: ICSA 2026-09-25 is its 2026-09-24 file.
        ("icsa_2026-09-25", "ICSA", "2026-09-25", "2026-09-24"),
        ("icsa_2026-09-24", "ICSA", "2026-09-24", "2026-09-24"),
        ("icsa_2026-09-25_reordered", "ICSA", "2026-09-25", "2026-09-25"),
        # PAYEMS lagged on the canonical spelling by one and two days.
        ("payems_2026-09-29", "PAYEMS", "2026-09-29", "2026-09-28"),
        ("payems_2026-10-01", "PAYEMS", "2026-10-01", "2026-09-29"),
        ("payems_2026-10-01_reordered", "PAYEMS", "2026-10-01", "2026-10-01"),
        ("payems_2026-10-02", "PAYEMS", "2026-10-02", "2026-10-02"),
        ("payems_2026-10-02_reordered", "PAYEMS", "2026-10-02", "2026-10-02"),
        ("payems_2026-10-18", "PAYEMS", "2026-10-18", "2026-10-17"),
        # A later date than ALFRED's current one: the current date's vintage.
        ("payems_2026-11-06_probe", "PAYEMS", "2026-11-06", "2026-10-18"),
    ],
)
def test_the_label_is_the_vintage_alfred_answered_with(
    name: str, series: str, asked: str, label: str
) -> None:
    raw = real(name)
    day = dt.date.fromisoformat(asked)
    assert alfred_vintage_label(raw, series, day) == dt.date.fromisoformat(label)
    read_label, rows = read_alfred_vintage(raw, series, day)
    assert read_label == dt.date.fromisoformat(label)
    body = raw.decode().rstrip("\n").split("\n")[1:]
    assert len(rows) == len(body)
    assert list(rows) == [line.split(",", 1)[0] for line in body]


def test_a_lagged_response_is_the_earlier_days_file() -> None:
    assert real("icsa_2026-09-25") == real("icsa_2026-09-24")
    # The reordered request for 2026-09-25 holds the same rows under its own
    # label: no claims release fell between the two days.
    assert (
        real("icsa_2026-09-25_reordered").split(b"\n", 1)[1]
        == real("icsa_2026-09-24").split(b"\n", 1)[1]
    )
    # PAYEMS asked for the release day's eve on the canonical spelling holds
    # the 2026-09-29 vintage: no September, and August before its revision.
    _label, lagged = read_alfred_vintage(real("payems_2026-10-01"), "PAYEMS", RELEASE)
    _label, release = read_alfred_vintage(real("payems_2026-10-02"), "PAYEMS", RELEASE)
    assert "2026-09-01" not in lagged
    assert (lagged["2026-08-01"], release["2026-08-01"]) == (159075.0, 159015.0)
    assert release["2026-09-01"] - release["2026-08-01"] == 29.0


def test_a_label_after_the_day_asked_for_is_refused() -> None:
    with pytest.raises(AlfredVintageError, match="a later vintage"):
        alfred_vintage_label(real("payems_2026-10-02"), "PAYEMS", dt.date(2026, 10, 1))


@pytest.mark.parametrize(
    ("raw", "series"),
    [
        (b"<!DOCTYPE html><html><body>Service unavailable</body></html>", "PAYEMS"),
        (real("icsa_2026-09-24"), "PAYEMS"),
        (b"observation_date,PAYEMS\n2026-09-01,1\n", "PAYEMS"),
        (b"DATE,PAYEMS_20261002\n2026-09-01,1\n", "PAYEMS"),
        (b"observation_date,PAYEMS_2026100\n2026-09-01,1\n", "PAYEMS"),
        (b"observation_date,PAYEMS_20260231\n2026-09-01,1\n", "PAYEMS"),
        (b"observation_date,PAYEMS_20261002_x\n2026-09-01,1\n", "PAYEMS"),
        (b"observation_date,PAYEMS_20261002,extra\n2026-09-01,1\n", "PAYEMS"),
        (b"", "PAYEMS"),
        (b"\xff\xfe", "PAYEMS"),
        # Digits from other scripts, which int() would read.
        ("observation_date,PAYEMS_2026100\u0662\n2026-09-01,1\n".encode(), "PAYEMS"),
        ("observation_date,PAYEMS_\uff12026\u0661002\n".encode(), "PAYEMS"),
        (b"\xef\xbb\xbfobservation_date,PAYEMS_20261002\n2026-09-01,1\n", "PAYEMS"),
    ],
)
def test_bytes_that_are_not_this_series_vintage_csv_are_refused(
    raw: bytes, series: str
) -> None:
    with pytest.raises(AlfredVintageError):
        alfred_vintage_label(raw, series, RELEASE)


@pytest.mark.parametrize(
    "body",
    [
        b"2026-09-01\n",  # no value
        b"2026-09-01,abc\n",
        b"2026-09-01,1e5\n",
        b"2026-09-01,inf\n",
        b"2026-08-01,1\n2026-08-01,2\n",  # repeated date
        b"2026-09-01,1\n2026-08-01,2\n",  # out of order
        b"20260901,1\n",
        b"2026-02-30,1\n",
        b"2026-09-01,1\n\n2026-10-01,2\n",  # a blank line inside
        b"2026-09-01,1,2\n",
        ("2026-09-01," + "9" * 400 + "\n").encode(),  # overflows a float
        "2026-09-01,\u0663\n".encode(),  # an Arabic-Indic digit
        "2026-0\u0669-01,3\n".encode(),
        b"2026-09-01,.\n2026-08-01,2\n",  # out of order after a missing mark
        b"2026-08-01,\n2026-08-01,2\n",  # repeated after a missing mark
    ],
)
def test_rows_that_are_not_dated_observations_are_refused(body: bytes) -> None:
    raw = b"observation_date,PAYEMS_20261002\n" + body
    with pytest.raises(AlfredVintageError):
        read_alfred_vintage(raw, "PAYEMS", RELEASE)


def test_a_header_with_trailing_carriage_returns_is_read() -> None:
    raw = b"observation_date,PAYEMS_20261002\r\r\n2026-09-01,1\n"
    assert alfred_vintage_label(raw, "PAYEMS", RELEASE) == RELEASE


def test_missing_marks_are_left_out_and_crlf_is_read() -> None:
    raw = b"observation_date,PAYEMS_20261002\r\n2026-07-01,.\r\n2026-08-01,\r\n"
    raw += b"2026-09-01,-1.5\r\n"
    assert read_alfred_vintage(raw, "PAYEMS", RELEASE) == (
        RELEASE,
        {"2026-09-01": -1.5},
    )


# --- invariant 3: the generic leg's read ---------------------------------------


def test_a_response_labeled_its_day_is_read_with_one_request() -> None:
    fake = FakeAlfred({canonical("PAYEMS", RELEASE): real("payems_2026-10-02")})
    with frozen_alfred_today(RELEASE):
        read = resolve_pending.read_alfred_vintage_of("PAYEMS", RELEASE, get=fake)
    assert fake.requested == [canonical("PAYEMS", RELEASE)]
    assert read.refusal is None
    assert read.source_url == canonical("PAYEMS", RELEASE)
    assert read.raw == real("payems_2026-10-02")
    assert read.rows["2026-09-01"] == 159044.0


def test_a_lagged_answer_is_retried_in_the_reordered_spelling() -> None:
    # ALFRED's real 2026-10-01 vintage stands in for a lagged answer to the
    # release day; the reordered spelling answers with the day asked for.
    fake = FakeAlfred(
        {
            canonical("PAYEMS", RELEASE): real("payems_2026-10-01_reordered"),
            reordered("PAYEMS", RELEASE): real("payems_2026-10-02_reordered"),
        }
    )
    with frozen_alfred_today(RELEASE):
        read = resolve_pending.read_alfred_vintage_of("PAYEMS", RELEASE, get=fake)
    assert fake.requested == [
        canonical("PAYEMS", RELEASE),
        reordered("PAYEMS", RELEASE),
    ]
    assert read.refusal is None
    assert read.source_url == reordered("PAYEMS", RELEASE)
    assert read.raw == real("payems_2026-10-02_reordered")
    assert read.rows["2026-09-01"] - read.rows["2026-08-01"] == 29.0


def test_lagged_in_every_spelling_is_refused_by_name() -> None:
    fake = FakeAlfred(
        {
            canonical("PAYEMS", RELEASE): real("payems_2026-10-01"),
            reordered("PAYEMS", RELEASE): real("payems_2026-10-01_reordered"),
        }
    )
    with frozen_alfred_today(RELEASE):
        read = resolve_pending.read_alfred_vintage_of("PAYEMS", RELEASE, get=fake)
    assert read.rows == {}
    assert read.refusal is not None
    head, detail = read.refusal
    assert head == resolve_pending.ALFRED_VINTAGE_LAGGED
    assert "its vintage of 2026-09-29" in detail
    assert "then its vintage of 2026-10-01" in detail


def test_a_lagged_answer_then_an_http_error_is_refused_as_lagged() -> None:
    fake = FakeAlfred(
        {
            canonical("PAYEMS", RELEASE): real("payems_2026-10-01"),
            reordered("PAYEMS", RELEASE): None,
        }
    )
    with frozen_alfred_today(RELEASE):
        read = resolve_pending.read_alfred_vintage_of("PAYEMS", RELEASE, get=fake)
    assert read.rows == {}
    assert read.refusal is not None
    assert read.refusal[0] == resolve_pending.ALFRED_VINTAGE_LAGGED
    assert "an HTTP error" in read.refusal[1]


def test_a_later_label_is_refused_without_retrying() -> None:
    day = dt.date(2026, 10, 1)
    fake = FakeAlfred({canonical("PAYEMS", day): real("payems_2026-10-02")})
    with frozen_alfred_today(RELEASE):
        read = resolve_pending.read_alfred_vintage_of("PAYEMS", day, get=fake)
    assert fake.requested == [canonical("PAYEMS", day)]
    assert read.rows == {}
    assert read.refusal is not None
    assert read.refusal[0] == resolve_pending.ALFRED_READ_FAILED


def test_an_http_error_first_is_left_for_not_yet_published() -> None:
    fake = FakeAlfred({canonical("PAYEMS", RELEASE): None})
    with frozen_alfred_today(RELEASE):
        read = resolve_pending.read_alfred_vintage_of("PAYEMS", RELEASE, get=fake)
    assert fake.requested == [canonical("PAYEMS", RELEASE)]
    assert (read.rows, read.raw, read.refusal) == ({}, None, None)


def test_a_day_after_alfred_today_is_never_requested() -> None:
    fake = FakeAlfred({})
    with frozen_alfred_today(RELEASE - dt.timedelta(days=1)):
        read = resolve_pending.read_alfred_vintage_of("PAYEMS", RELEASE, get=fake)
    assert fake.requested == []
    assert read.refusal is not None
    assert read.refusal[0] == resolve_pending.ALFRED_VINTAGE_NOT_REACHED


def test_alfred_today_is_us_central_standard_time() -> None:
    utc = dt.timezone.utc
    # 05:59 UTC on 2026-10-02 is still 2026-10-01 at UTC-6.
    assert alfred_today(dt.datetime(2026, 10, 2, 5, 59, tzinfo=utc)) == dt.date(
        2026, 10, 1
    )
    assert alfred_today(dt.datetime(2026, 10, 2, 6, 0, tzinfo=utc)) == RELEASE
    # The resolve workflow's 13:40 UTC run is on its UTC day.
    assert alfred_today(dt.datetime(2026, 10, 2, 13, 40, tzinfo=utc)) == RELEASE
    with pytest.raises(ValueError):
        alfred_today(dt.datetime(2026, 10, 2, 13, 40))


def test_alfred_today_reads_the_clock_when_given_no_time() -> None:
    # The resolver calls it with no argument. Bracketing the call keeps this
    # true across a midnight.
    before = dt.datetime.now(dt.timezone.utc)
    today = alfred_today()
    after = dt.datetime.now(dt.timezone.utc)
    assert alfred_today(before) <= today <= alfred_today(after)


dates = st.dates(min_value=dt.date(1990, 1, 1), max_value=dt.date(2035, 12, 31))


HTML = b"<!DOCTYPE html><html><body>Service unavailable</body></html>"


@settings(max_examples=300, deadline=None)
@given(
    day=dates,
    today_offset=st.integers(min_value=-3, max_value=3),
    answers=st.lists(
        st.one_of(st.none(), st.just("html"), st.integers(min_value=-4, max_value=2)),
        min_size=2,
        max_size=2,
    ),
)
def test_rows_come_only_from_a_response_labeled_the_day(
    day: dt.date, today_offset: int, answers: list[int | str | None]
) -> None:
    """Invariant 3 over every pattern of answers, per spelling: an HTTP error,
    bytes that are no vintage CSV, or a label ``offset`` days from the day
    asked for. Each body's one row is told apart by spelling and offset."""
    today = day + dt.timedelta(days=today_offset)
    urls = [canonical("TEST", day), reordered("TEST", day)]

    def body(index: int, offset: int | str | None) -> bytes | None:
        if offset is None:
            return None
        if offset == "html":
            return HTML
        value = str(10 * index + offset + 5)
        return vintage_csv(
            "TEST", day + dt.timedelta(days=offset), [("2000-01-01", value)]
        )

    bodies = {
        url: body(i, offset) for i, (url, offset) in enumerate(zip(urls, answers))
    }
    fake = FakeAlfred(bodies)
    with frozen_alfred_today(today):
        read = resolve_pending.read_alfred_vintage_of("TEST", day, get=fake)
    assert fake.requested == urls[: len(fake.requested)]
    if day > today:
        assert fake.requested == []
        assert read.refusal is not None
        assert read.refusal[0] == resolve_pending.ALFRED_VINTAGE_NOT_REACHED
        return

    def earlier(offset: int | str | None) -> bool:
        return isinstance(offset, int) and offset < 0

    # Requests stop at the first answer that is not an earlier label.
    expected_requests = 0
    for offset in answers:
        expected_requests += 1
        if not earlier(offset):
            break
    assert len(fake.requested) == expected_requests
    asked = list(enumerate(answers[:expected_requests]))
    exact = [i for i, offset in asked if offset == 0]
    if exact:
        assert read.refusal is None
        assert read.rows == {"2000-01-01": float(10 * exact[0] + 5)}
        assert read.source_url == urls[exact[0]]
        assert read.raw == bodies[urls[exact[0]]]
    else:
        assert read.rows == {}
    last = answers[expected_requests - 1]
    if last == "html" or (isinstance(last, int) and last > 0):
        assert read.refusal is not None
        assert read.refusal[0] == resolve_pending.ALFRED_READ_FAILED
    if all(earlier(offset) for offset in answers):
        assert read.refusal is not None
        assert read.refusal[0] == resolve_pending.ALFRED_VINTAGE_LAGGED
    if answers[0] is None:
        assert (read.refusal, read.raw) == (None, None)


@settings(max_examples=300, deadline=None)
@given(label=dates, day=dates)
def test_a_label_is_accepted_exactly_when_no_later_than_the_day(
    label: dt.date, day: dt.date
) -> None:
    raw = vintage_csv("PAYEMS", label, [])
    if label <= day:
        assert alfred_vintage_label(raw, "PAYEMS", day) == label
    else:
        with pytest.raises(AlfredVintageError):
            alfred_vintage_label(raw, "PAYEMS", day)


@settings(max_examples=200, deadline=None)
@given(
    observations=st.dictionaries(
        dates,
        st.one_of(
            st.just("."),
            st.just(""),
            st.decimals(
                min_value=-(10**9),
                max_value=10**9,
                places=3,
                allow_nan=False,
                allow_infinity=False,
            ).map(lambda value: f"{value:f}"),
        ),
        max_size=40,
    ),
    label=dates,
)
def test_rows_round_trip(observations: dict[dt.date, str], label: dt.date) -> None:
    rows = sorted((day.isoformat(), value) for day, value in observations.items())
    raw = vintage_csv("PAYEMS", label, rows)
    read_label, read = read_alfred_vintage(raw, "PAYEMS", label)
    assert read_label == label
    assert read == {day: float(value) for day, value in rows if value not in ("", ".")}


@settings(max_examples=300, deadline=None)
@given(
    now=st.datetimes(
        min_value=dt.datetime(2000, 1, 1),
        max_value=dt.datetime(2035, 12, 31),
        timezones=st.just(dt.timezone.utc),
    )
)
def test_alfred_today_never_runs_ahead_of_central_eastern_or_utc(
    now: dt.datetime,
) -> None:
    today = alfred_today(now)
    for zone in ("America/Chicago", "America/New_York", "UTC"):
        assert today <= now.astimezone(zoneinfo.ZoneInfo(zone)).date()


# --- the leg end to end, and its status ----------------------------------------


def run_payroll_cell(monkeypatch, capsys, fake: FakeAlfred, today: dt.date) -> str:
    """One dry run of the resolver over the September 2026 payroll cell."""
    spec = resolve_pending.ALFRED_ADAPTERS[PAYROLL_STEM]
    forecast = {"resolutionDate": RELEASE.isoformat(), "unit": spec["unit"]}
    monkeypatch.setattr(
        resolve_pending,
        "load_thesis_log",
        lambda _url: {"entries": [], "resolutionLinks": []},
    )
    monkeypatch.setattr(resolve_pending, "pending_claims_refs", lambda _log: [])
    monkeypatch.setattr(
        resolve_pending,
        "pending_adapter_refs",
        lambda _log: [
            (
                PAYROLL_REF,
                "alfred",
                spec,
                "month",
                "2026-09",
                RELEASE.isoformat(),
                forecast,
            )
        ],
    )
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_args: ("", "blob", "a" * 40)
    )
    monkeypatch.setattr(resolve_pending, "registration_contracts", lambda: {})
    monkeypatch.setattr(resolve_pending, "alfred_http_get", fake)
    monkeypatch.setattr(resolve_pending, "alfred_today", lambda: today)
    monkeypatch.setattr(sys, "argv", ["resolve_pending.py", "--dry-run"])
    assert resolve_pending.main() == 0
    return capsys.readouterr().out


def test_the_leg_resolves_from_the_reordered_spelling(monkeypatch, capsys) -> None:
    built: list[str] = []
    generic_fact = resolve_pending.generic_fact

    def recording_generic_fact(*args, **kwargs):
        row = generic_fact(*args, **kwargs)
        built.append(row["source"]["url"])
        return row

    monkeypatch.setattr(resolve_pending, "generic_fact", recording_generic_fact)
    fake = FakeAlfred(
        {
            canonical("PAYEMS", RELEASE): real("payems_2026-10-01_reordered"),
            reordered("PAYEMS", RELEASE): real("payems_2026-10-02_reordered"),
        }
    )
    out = run_payroll_cell(monkeypatch, capsys, fake, RELEASE)
    assert f"  resolve {PAYROLL_REF} -> 29.0 thousands" in out
    assert "dry-run: would append 1 row(s)" in out
    assert fake.requested == [
        canonical("PAYEMS", RELEASE),
        reordered("PAYEMS", RELEASE),
    ]
    # The fact names the request ALFRED answered with the release day.
    assert built == [reordered("PAYEMS", RELEASE)]


def test_the_leg_defers_a_lagged_vintage_by_name(monkeypatch, capsys) -> None:
    fake = FakeAlfred(
        {
            canonical("PAYEMS", RELEASE): real("payems_2026-10-01"),
            reordered("PAYEMS", RELEASE): real("payems_2026-10-01_reordered"),
        }
    )
    out = run_payroll_cell(monkeypatch, capsys, fake, RELEASE)
    assert f"  {resolve_pending.ALFRED_VINTAGE_LAGGED}: {PAYROLL_REF} — " in out
    assert "nothing new to record" in out
    targets, _run = resolution_status.parse_resolver_log(out)
    assert targets[PAYROLL_REF]["state"] == "deferred"
    assert targets[PAYROLL_REF]["code"] == "ALFRED_VINTAGE_LAGGED"


def test_the_leg_asks_nothing_before_alfreds_day(monkeypatch, capsys) -> None:
    # 03:00 UTC on the release day is the eve in US Central standard time.
    eve = alfred_today(dt.datetime(2026, 10, 2, 3, 0, tzinfo=dt.timezone.utc))
    assert eve == RELEASE - dt.timedelta(days=1)
    fake = FakeAlfred({})
    out = run_payroll_cell(monkeypatch, capsys, fake, eve)
    assert fake.requested == []
    assert f"  {resolve_pending.ALFRED_VINTAGE_NOT_REACHED}: {PAYROLL_REF} — " in out
    targets, _run = resolution_status.parse_resolver_log(out)
    assert targets[PAYROLL_REF]["state"] == "deferred"
    assert targets[PAYROLL_REF]["code"] == "RELEASE_DAY_NOT_REACHED"


@pytest.mark.parametrize(
    ("head", "state", "code"),
    [
        (resolve_pending.ALFRED_VINTAGE_LAGGED, "deferred", "ALFRED_VINTAGE_LAGGED"),
        (
            resolve_pending.ALFRED_VINTAGE_NOT_REACHED,
            "deferred",
            "RELEASE_DAY_NOT_REACHED",
        ),
        (resolve_pending.ALFRED_READ_FAILED, "fetch_failed", "SOURCE_UNREACHABLE"),
    ],
)
def test_each_verdict_has_its_status(head: str, state: str, code: str) -> None:
    out = f"  {head}: {PAYROLL_REF} — detail\n"
    targets, _run = resolution_status.parse_resolver_log(out)
    assert targets[PAYROLL_REF]["state"] == state
    assert targets[PAYROLL_REF]["code"] == code
    assert code in resolution_status.REASONS


def test_a_reordered_url_passes_the_registered_host_check() -> None:
    # The registered ALFRED binding names the canonical URL without a
    # vintage; resolver provenance compares only its host. (The site's check,
    # site/src/data/thesis-log.ts, is host-only too, but is not tested here.)
    stem = "fed.g17.industrial_production.total_index_mom"
    spec = resolve_pending.ALFRED_ADAPTERS[stem]
    url = reordered(spec["fred"], RELEASE)
    row = resolve_pending.generic_fact(
        f"{stem}.2026_09.first_print",
        spec,
        "month",
        "2026-09",
        0.1,
        RELEASE,
        url,
        "alfredgraph.csv",
    )
    registration = {
        "contract": {
            "unit": spec["unit"],
            "series": row["measure"]["concept"],
            "period": "2026-09",
            "sourceBinding": {
                "adapter": "alfred-fred",
                "sourceUrl": (
                    "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
                    f"?id={spec['fred']}"
                ),
                "allowedHosts": ["alfred.stlouisfed.org"],
                "releasePolicy": "first_print",
            },
        }
    }
    projection = resolve_pending.source_binding_projection(registration, row, b"x")
    assert projection["sourceUrl"] == url


# --- invariant 5: custody ------------------------------------------------------


def custody_run(
    tmp_path: pathlib.Path,
    series: str,
    vintage: str,
    raw: bytes,
    *,
    record: str = PAYROLL_REF,
    archive_day: str | None = None,
    fact: dict | None = None,
):
    run_dir = tmp_path / "records" / "resolutions" / vintage / "run"
    responses = run_dir / "responses"
    responses.mkdir(parents=True)
    day = archive_day or vintage
    name = f"{series.lower()}-{day}-{hashlib.sha256(raw).hexdigest()[:16]}.csv.gz"
    (responses / name).write_bytes(gzip.compress(raw, mtime=0))
    row = {
        "dataPointId": record,
        "sourceVintage": vintage,
        "responseArchive": {"path": f"responses/{name}"},
    }
    if fact is not None:
        row = {**row, **fact}
        row = {key: value for key, value in row.items() if value is not ABSENT}
    return run_dir, {"facts": [row]}


ABSENT = object()


def test_custody_keeps_a_fact_labeled_its_vintage(tmp_path) -> None:
    run_dir, manifest = custody_run(
        tmp_path, "PAYEMS", "2026-10-02", real("payems_2026-10-02_reordered")
    )
    assert verify_custody._verify_resolver_alfred_labels(run_dir, manifest) == 1


LAGGED_PRS = b"observation_date,PRS85006112_20261104\n2026-07-01,2.4\n"
LAGGED_CRLF = b"observation_date,PAYEMS_20261001\r\n2026-08-01,159015\r\n"


@pytest.mark.parametrize(
    ("series", "vintage", "raw", "kwargs", "message"),
    [
        (
            "PAYEMS",
            "2026-10-02",
            real("payems_2026-10-01_reordered"),
            {},
            "keeps ALFRED's PAYEMS vintage of 2026-10-01 as its vintage of 2026-10-02",
        ),
        ("PAYEMS", "2026-10-01", real("payems_2026-10-02"), {}, "a later vintage"),
        (
            "ICSA",
            "2026-10-02",
            real("payems_2026-10-02"),
            {},
            "archives ALFRED PAYEMS of 2026-10-02",
        ),
        # A series id with digits, and a CRLF answer, are judged too.
        (
            "PRS85006112",
            "2026-11-05",
            LAGGED_PRS,
            {},
            "keeps ALFRED's PRS85006112 vintage of 2026-11-04",
        ),
        (
            "PAYEMS",
            "2026-10-02",
            LAGGED_CRLF,
            {},
            "keeps ALFRED's PAYEMS vintage of 2026-10-01",
        ),
        # The archive must be named for the fact's own day.
        (
            "PAYEMS",
            "2026-10-02",
            real("payems_2026-10-02"),
            {"archive_day": "2026-10-01"},
            "archives ALFRED PAYEMS of 2026-10-02",
        ),
        # A weekly claims fact's own response is its release-day read, lag 0.
        (
            "ICSA",
            "2026-09-25",
            real("icsa_2026-09-25"),
            {"record": "us.dol.initial_claims.sa.week_2026-09-19"},
            "keeps ALFRED's ICSA vintage of 2026-09-24 as its vintage of 2026-09-25",
        ),
    ],
)
def test_custody_refuses_a_fact_labeled_otherwise(
    tmp_path, series: str, vintage: str, raw: bytes, kwargs: dict, message: str
) -> None:
    run_dir, manifest = custody_run(tmp_path, series, vintage, raw, **kwargs)
    with pytest.raises(verify_custody.CustodyError, match=re.escape(message)):
        verify_custody._verify_resolver_alfred_labels(run_dir, manifest)


@pytest.mark.parametrize("source_vintage", [ABSENT, None, "2026-10", "20261002"])
def test_custody_refuses_an_alfred_fact_with_no_source_vintage(
    tmp_path, source_vintage
) -> None:
    run_dir, manifest = custody_run(
        tmp_path,
        "PAYEMS",
        "2026-10-02",
        real("payems_2026-10-02"),
        fact={"sourceVintage": source_vintage},
    )
    with pytest.raises(verify_custody.CustodyError, match="has no sourceVintage date"):
        verify_custody._verify_resolver_alfred_labels(run_dir, manifest)


def test_custody_leaves_other_adapters_responses_alone(tmp_path) -> None:
    run_dir, manifest = custody_run(
        tmp_path, "PAYEMS", "2026-10-02", b'{"Results": {"series": []}}'
    )
    assert verify_custody._verify_resolver_alfred_labels(run_dir, manifest) == 0


def test_the_claims_and_generic_release_day_lags_agree() -> None:
    # Custody picks the lag by fact; both are 0, as the resolver reads them.
    assert verify_custody.ALFRED_VINTAGE_LABEL_LAG == 0
    assert verify_custody.CLAIMS_LABEL_LAG["release_day"][0] == 0


def sealed_payroll_run(tmp_path, monkeypatch, raw: bytes):
    """A generic-leg resolver run for the payroll cell, sealed by the resolver."""

    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    spec = resolve_pending.ALFRED_ADAPTERS[PAYROLL_STEM]
    url = reordered("PAYEMS", RELEASE)
    row = resolve_pending.generic_fact(
        PAYROLL_REF, spec, "month", "2026-09", 29.0, RELEASE, url, "alfredgraph.csv"
    )
    run_dir = resolve_pending.resolution_run_dir("2026-10-02T13:40:00Z")
    run_dir.mkdir(parents=True)
    attached = resolve_pending.attach_resolution_provenance(
        row,
        run_dir=run_dir,
        series_id="PAYEMS",
        vintage=RELEASE.isoformat(),
        raw=raw,
        retrieved_at="2026-10-02T13:40:00Z",
        ledger_repo_sha="a" * 40,
        target_contracts={},
    )
    manifest = {
        "schemaVersion": "thesis_resolution_run_v1",
        "retrievedAt": "2026-10-02T13:40:00Z",
        "ledgerRepo": "PolicyEngine/chronicle",
        "ledgerBranch": "facts",
        "ledgerRepoSha": "a" * 40,
        "facts": [
            {
                "dataPointId": PAYROLL_REF,
                "sourceVintage": attached["sourceVintage"],
                "retrievedAt": attached["retrievedAt"],
                "targetContentHash": None,
                "responseArchive": attached["responseArchive"],
            }
        ],
    }
    return run_dir, resolve_pending.finalize_resolution_manifest(run_dir, manifest)


def test_a_sealed_run_labeled_its_day_verifies(tmp_path, monkeypatch) -> None:
    run_dir, _manifest = sealed_payroll_run(
        tmp_path, monkeypatch, real("payems_2026-10-02_reordered")
    )
    assert verify_custody.verify_run(run_dir).run_mode == "resolver"


def test_sealing_a_run_with_a_lagged_archive_is_refused(tmp_path, monkeypatch) -> None:
    # finalize_resolution_manifest seals the run and then calls verify_run,
    # which must reach the label check: a hash-only check passes these bytes.
    with pytest.raises(
        verify_custody.CustodyError,
        match=re.escape("keeps ALFRED's PAYEMS vintage of 2026-10-01"),
    ):
        sealed_payroll_run(tmp_path, monkeypatch, real("payems_2026-10-01_reordered"))


def test_every_real_resolver_run_keeps_alfreds_vintage_of_its_day() -> None:
    runs = sorted((ROOT / "records" / "resolutions").glob("*/*/manifest.json"))
    if not runs:
        pytest.skip("records/ is not checked out")
    judged = vintage_headers = 0
    for manifest_path in runs:
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("runMode") != "resolver":
            continue
        judged += verify_custody._verify_resolver_alfred_labels(
            manifest_path.parent, manifest
        )
        for fact in manifest["facts"]:
            path = ROOT / fact["responseArchive"]["path"]
            if gzip.decompress(path.read_bytes()).startswith(b"observation_date,"):
                vintage_headers += 1
    # Custody judged every archive with an ALFRED-style header: 65 across
    # the resolver runs on main on 2026-11-18, every one a vintage.
    assert judged == vintage_headers
    assert judged >= 65


# --- invariant 6: against the parsers it replaces ------------------------------


def pre_label_parse(raw: bytes, series_id: str, vintage: str) -> dict[str, float]:
    """resolve_pending.parse_fred_vintage_csv as it stood before this change."""
    rows: dict[str, float] = {}
    for row in csv.DictReader(io.StringIO(raw.decode())):
        date = row.get("observation_date") or row.get("DATE")
        value = row.get(f"{series_id}_{vintage.replace('-', '')}") or row.get(series_id)
        if date and value not in (None, "", "."):
            rows[date] = float(value)
    return rows


def pre_shared_claims_label(raw: bytes, series_id: str, day: str) -> dt.date:
    """verify_custody.read_alfred_claims_vintage's header rule before it moved."""
    lines = [line.rstrip("\r") for line in raw.decode("utf-8").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    header = lines[0] if lines else ""
    match = re.fullmatch(rf"observation_date,{re.escape(series_id)}_(\d{{8}})", header)
    label = None
    if match:
        try:
            label = dt.datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            label = None
    if label is None or label > dt.date.fromisoformat(day):
        raise ValueError(header)
    return label


@pytest.mark.parametrize(
    ("name", "series", "asked"),
    [
        ("icsa_2026-09-24", "ICSA", "2026-09-24"),
        ("icsa_2026-09-25_reordered", "ICSA", "2026-09-25"),
        ("payems_2026-10-01_reordered", "PAYEMS", "2026-10-01"),
        ("payems_2026-10-02", "PAYEMS", "2026-10-02"),
    ],
)
def test_rows_match_the_pre_label_parser_on_an_exact_label(
    name: str, series: str, asked: str
) -> None:
    raw = real(name)
    label, rows = read_alfred_vintage(raw, series, dt.date.fromisoformat(asked))
    assert label == dt.date.fromisoformat(asked)
    assert rows == pre_label_parse(raw, series, asked)


@pytest.mark.parametrize(
    ("name", "series", "asked"),
    [
        ("icsa_2026-09-25", "ICSA", "2026-09-25"),
        ("payems_2026-10-01", "PAYEMS", "2026-10-01"),
        ("payems_2026-10-18", "PAYEMS", "2026-10-18"),
    ],
)
def test_a_lagged_response_gave_the_pre_label_parser_no_rows(
    name: str, series: str, asked: str
) -> None:
    # The old leg never took a wrong value from a lagged answer: it found no
    # column for the day asked for and deferred as "not yet published".
    raw = real(name)
    assert pre_label_parse(raw, series, asked) == {}
    day = dt.date.fromisoformat(asked)
    assert alfred_vintage_label(raw, series, day) < day


@settings(max_examples=300, deadline=None)
@given(
    rows=st.dictionaries(
        dates,
        st.integers(min_value=-(10**7), max_value=10**7).map(str),
        min_size=1,
        max_size=30,
    ),
    day=dates,
)
def test_rows_match_the_pre_label_parser_on_any_exact_label(
    rows: dict[dt.date, str], day: dt.date
) -> None:
    ordered = sorted((date.isoformat(), value) for date, value in rows.items())
    raw = vintage_csv("PAYEMS", day, ordered)
    _label, read = read_alfred_vintage(raw, "PAYEMS", day)
    assert read == pre_label_parse(raw, "PAYEMS", day.isoformat())


headers = st.builds(
    lambda prefix, series, token, suffix: f"{prefix},{series}_{token}{suffix}",
    st.sampled_from(["observation_date", "DATE", "observation_date "]),
    st.sampled_from(["ICSA", "CCSA", "ICSA_X"]),
    st.one_of(
        st.dates(min_value=dt.date(1967, 1, 1), max_value=dt.date(2035, 12, 31)).map(
            lambda day: f"{day:%Y%m%d}"
        ),
        st.text(alphabet="0123456789", min_size=7, max_size=9),
    ),
    st.sampled_from(["", "\r", "\r\r", "\r\r\r", "_x", ",ICSA"]),
)


@settings(max_examples=400, deadline=None)
@given(header=headers, day=dates)
def test_the_claims_leg_reads_labels_as_before(header: str, day: dt.date) -> None:
    """On ASCII headers, the header rule read_alfred_claims_vintage now takes
    from alfred_vintage_label accepts and refuses exactly what its own did."""
    raw = (header + "\n1967-01-07,1\n").encode()
    try:
        before = pre_shared_claims_label(raw, "ICSA", day.isoformat())
    except ValueError:
        before = None
    try:
        now = alfred_vintage_label(raw, "ICSA", day)
    except AlfredVintageError:
        now = None
    assert now == before


@pytest.mark.parametrize("digit", ["\u0662", "\uff12", "\u096a"])
@pytest.mark.parametrize("position", [0, 3, 5, 7])
def test_a_label_in_another_scripts_digits_is_refused(
    digit: str, position: int
) -> None:
    # #345's strptime took such digits in the year only; the shared rule,
    # like custody's bytes pattern, takes ASCII digits alone.
    token = list("20260924")
    token[position] = digit
    raw = f"observation_date,ICSA_{''.join(token)}\n1967-01-07,1\n".encode()
    with pytest.raises(AlfredVintageError):
        alfred_vintage_label(raw, "ICSA", dt.date(2026, 9, 30))


def test_the_claims_leg_reads_its_label_through_the_shared_reader() -> None:
    raw = real("icsa_2026-09-25")
    label, rows = verify_custody.read_alfred_claims_vintage(raw, "ICSA", "2026-09-25")
    assert label == alfred_vintage_label(raw, "ICSA", dt.date(2026, 9, 25))
    assert rows["2026-09-19"] == 197000.0
    with pytest.raises(AlfredVintageError, match="a later vintage"):
        verify_custody.read_alfred_claims_vintage(raw, "ICSA", "2026-09-23")
