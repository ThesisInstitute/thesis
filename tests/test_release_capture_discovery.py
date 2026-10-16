"""Archive discovery is source-parametric while default A-19 stays unchanged.

All indexes are synthetic; the A-19 oracle reuses the existing June fixture.
The frozen implementation below is the five
pre-change functions/types from 81b57bd5, used as a differential oracle.
No test makes a network request or reads a target release capture.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import pathlib
import sys
import urllib.error
import urllib.parse
from dataclasses import asdict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import resolve_pending as rp  # noqa: E402
from test_a19_adapter import cdx, fixture  # noqa: E402

# Frozen before editing: compare full verdicts, bytes, witnesses, index rows,
# and the complete request sequence, rather than just the selected timestamp.
_PRE_CHANGE_SOURCE = r'''
@dataclass(frozen=True)
class A19Row:
    """One index row that could hold the page: HTTP 200, or without a status."""

    stamp: str
    status: str
    digest: str | None
    """The index's content digest, or None when it is not of the observed form."""
    original: str = A19_SOURCE_URL
    """The URL the Archive stored it under."""

    @property
    def exact(self) -> bool:
        """Stored under exactly the bound URL, so a capture this resolver reads."""
        return self.original == A19_SOURCE_URL

    @property
    def url(self) -> str:
        return f"https://web.archive.org/web/{self.stamp}/{A19_SOURCE_URL}"


@dataclass
class A19Index:
    """What the Archive's index lists for one registered window.

    Every count is disjoint: ``listed == len(captures) + len(revisits) +
    other_status + other_form``.
    """

    rows: list[A19Row]
    """Every row with status 200 or ``-``, under any form of the URL, oldest
    first: the rows that could hold the page."""
    listed: int
    """Every row dated inside the window."""
    other_status: int
    """Rows for the bound URL whose status is neither 200 nor ``-``."""
    other_form: int
    """Rows stored under another form of the URL (scheme, host), any status;
    never read."""

    @property
    def captures(self) -> list[str]:
        """HTTP 200 captures of exactly the bound URL, oldest first."""
        return [row.url for row in self.rows if row.exact and row.status == "200"]

    @property
    def revisits(self) -> list[A19Row]:
        """Rows for exactly the bound URL without a status, oldest first."""
        return [row for row in self.rows if row.exact and row.status == "-"]

    @property
    def other_form_rows(self) -> list[A19Row]:
        """Rows under another form of the URL with status 200 or ``-``."""
        return [row for row in self.rows if not row.exact]

    def describe(self, window: Any) -> str:
        text = (
            f"{self.listed} capture(s) dated inside the registered window "
            f"{window!r}, {len(self.captures)} of them HTTP 200 for this exact URL"
        )
        detail = [
            f"{count} {label}"
            for count, label in (
                (len(self.revisits), "without a status"),
                (self.other_status, "with another status"),
                (self.other_form, "under another form of the URL"),
            )
            if count
        ]
        return text + (f"; {', '.join(detail)}" if detail else "")


def a19_read_capture(
    capture_url: str,
    read: Callable[[str], tuple[bytes, str]] = _wayback_read,
    digest: str | None = None,
) -> bytes:
    """BLS's own bytes for exactly one capture of the A-19 page.

    With ``digest`` (the index's digest for the row), the stored bytes must
    hash to it, so what is read is exactly what the index lists: a truncated,
    spliced or substituted body refuses.

    Asked for a timestamp it holds no capture of, the Archive answers with
    the nearest capture and rewrites the path (observed 2026-09-20: a request
    for 20260901000000 returned the 20260904170006 capture with HTTP 200). A
    window check on the requested timestamp would then judge a date nothing
    served, so the final URL must name the same timestamp and page. The
    ``id_`` form returns the response the Archive stored, without its replay
    toolbar or link rewriting, so the hash recorded for the fact is one
    anybody can reproduce; the Archive passes BLS's gzip encoding through.
    """

    capture = a19_capture(capture_url)
    if capture is None or capture[1] != A19_SOURCE_URL:
        raise A19CaptureError(f"not a capture of {A19_SOURCE_URL}: {capture_url}")
    stamp = f"{capture[0]:%Y%m%d%H%M%S}"
    raw, final_url = read(f"https://web.archive.org/web/{stamp}id_/{A19_SOURCE_URL}")
    served = re.fullmatch(
        r"https?://web\.archive\.org/web/(\d{14})id_/(https://.+)", final_url
    )
    if not served or served.groups() != (stamp, A19_SOURCE_URL):
        raise A19CaptureError(
            f"asked the Archive for capture {stamp} and was served {final_url}"
        )
    if digest is not None and a19_digest(raw) != digest:
        raise A19CaptureError(
            f"capture {stamp} does not hash to its index digest {digest}"
        )
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error) as exc:
            raise A19CaptureError(f"capture {stamp} is not valid gzip") from exc
    return raw


def a19_window_captures(
    window: Mapping[str, Any],
    read: Callable[[str], tuple[bytes, str]] = _wayback_read,
) -> A19Index:
    """Internet Archive captures of the A-19 page dated inside ``window``.

    The Archive's own index supplies the timestamps, so a registered target
    needs no per-period hand pin. A body that is not the index's requested
    table raises ValueError.
    """

    start = dt.date.fromisoformat(str(window["start"]))
    end = dt.date.fromisoformat(str(window["end"]))
    body, _ = read(
        WAYBACK_CDX_URL.format(
            url=urllib.parse.quote(A19_SOURCE_URL, safe=""),
            start=f"{start:%Y%m%d}000000",
            end=f"{end:%Y%m%d}235959",
        )
    )
    index = json.loads(body.decode())
    # The JSON list ``[]`` is an empty index (observed 2026-09-22 for a
    # window with no capture). Anything else must be exactly the requested
    # shape: an empty body, a malformed row, an impossible timestamp or a
    # non-numeric status is an index failure, never evidence that the window
    # holds no capture.
    if not isinstance(index, list) or (index and index[0] != _WAYBACK_CDX_HEADER):
        raise ValueError("the Archive index is not the requested table")
    # One row per (stamp, stored URL): a row listed both with a status and
    # without one is the capture with the status, and a digest fills in for
    # a "-". Two different statuses, or two different digests, for one row
    # make the index ambiguous, which is an index failure, not a choice. A
    # digest not of the observed form is kept as unknown: it verifies and
    # accounts for nothing.
    rows: dict[tuple[str, str], tuple[str, str]] = {}
    for row in index[1:]:
        if (
            not isinstance(row, list)
            or len(row) != 4
            or not all(isinstance(cell, str) for cell in row)
        ):
            raise ValueError(f"malformed Archive index row (shape): {row!r}")
        for field, ok in (
            ("timestamp", re.fullmatch(r"[0-9]{14}", row[0])),
            ("original", row[1]),
            ("status", re.fullmatch(r"[0-9]{3}|-", row[2])),
            ("digest", row[3]),
        ):
            if not ok:
                raise ValueError(f"malformed Archive index row ({field}): {row!r}")
        key = (row[0], row[1])
        status, digest = row[2], row[3]
        if key in rows:
            kept_status, kept_digest = rows[key]
            if "-" not in (status, kept_status) and status != kept_status:
                raise ValueError(
                    f"the Archive index lists {row[0]} with statuses "
                    f"{kept_status} and {status}"
                )
            if "-" not in (digest, kept_digest) and digest != kept_digest:
                raise ValueError(f"the Archive index lists {row[0]} with two digests")
            status = kept_status if status == "-" else status
            digest = kept_digest if digest == "-" else digest
        rows[key] = (status, digest)
    result = A19Index(rows=[], listed=0, other_status=0, other_form=0)
    for (stamp, original), (status, listed_digest) in sorted(rows.items()):
        digest = listed_digest if _A19_DIGEST.fullmatch(listed_digest) else None
        capture = a19_capture(f"https://web.archive.org/web/{stamp}/{A19_SOURCE_URL}")
        if capture is None:
            raise ValueError(f"impossible Archive index timestamp {stamp!r}")
        if not start <= capture[0].date() <= end:
            continue
        result.listed += 1
        if original != A19_SOURCE_URL:
            result.other_form += 1
        elif status not in ("200", "-"):
            result.other_status += 1
        if status in ("200", "-"):
            result.rows.append(A19Row(stamp, status, digest, original))
    return result


def a19_registered_capture(
    period: str,
    window: Any,
    today: dt.date,
    read: Callable[[str], tuple[bytes, str]] = _wayback_read,
    *,
    request_capture: bool = True,
) -> A19Discovery:
    """The capture a registered A-19 target resolves from, or why not yet.

    Takes the EARLIEST row dated inside the registered window that prints
    ``period``, walking the index in order. The index's digest is the SHA-1
    of a row's stored bytes (``a19_digest``), and every read is verified
    against it, so two rows with one digest hold the same bytes. Every row
    stored under exactly the bound URL is read at its own timestamp, unless
    a verified read of its digest already says what it holds; an HTTP 200
    capture that cannot be read, verified or identified stops the walk there
    (a later capture is the earliest only if this one is known not to print
    the month). A row without a status that cannot be read and verified at
    its own timestamp is not a stop, and a row under another form of the URL
    is never read: what either holds is known when a verified read carries
    the same digest. So a later read can account for an earlier unread row,
    and an earlier unread row whose digest a read capture of the month
    carries is the earliest print, with that capture supplying its bytes
    (``witness``). A row nobody accounts for that is dated before the first
    print defers the result. A row whose digest is not of the observed form
    is read without verification and accounts for nothing.

    ``FIRST-PRINT WINDOW MISSED`` is reserved for one finding: the window is
    closed, every row in it is accounted for, and each prints another month.
    Rows that were not read and are not accounted for make the outcome
    unknown, which defers. An index failure, an unreadable or unidentified
    HTTP 200 capture, or a scan that reached its cap without settling
    reports itself and asks for nothing. Only when the
    window is still open, every row read prints another month, and
    ``request_capture`` is set (once per run) does it ask the Archive to
    capture the page, and defer.
    """

    state = snapshot_window_state(today, window)
    if state == "invalid":
        return A19Discovery(None, None, "NO REGISTERED RELEASE WINDOW (refusing)")
    if state == "pending":
        return A19Discovery(
            None, None, f"release window opens {window['start']} (deferring)"
        )
    try:
        index = a19_window_captures(window, read)
    except (*_WAYBACK_READ_ERRORS, ValueError) as exc:
        return A19Discovery(
            None,
            None,
            (
                f"WAYBACK INDEX FETCH FAILED (deferring): {type(exc).__name__}: "
                f"{str(exc)[:200]}"
            ),
        )
    rows = index.rows
    # What each read capture printed, by stamp, and by digest once the
    # digest's read captures agree; raw bytes by stamp; why each unread row
    # is unread.
    table_by_stamp: dict[str, tuple[str, dict[str, float]]] = {}
    table_by_digest: dict[str, tuple[tuple[str, dict[str, float]], str]] = {}
    raw_by_stamp: dict[str, bytes] = {}
    unread: dict[str, str] = {
        row.stamp: "which is stored under another form of the URL and not read"
        for row in rows
        if not row.exact
    }

    def month_of(row: A19Row) -> str | None:
        if row.exact and row.stamp in table_by_stamp:
            return table_by_stamp[row.stamp][0]
        if row.digest is not None and row.digest in table_by_digest:
            return table_by_digest[row.digest][0][0]
        return None

    def settled() -> A19Discovery | None:
        # The first row known to print the month, once every row before it
        # is known to print another.
        for row in rows:
            month = month_of(row)
            if month is None:
                return None
            if month != period:
                continue
            if row.exact and row.stamp in raw_by_stamp:
                return A19Discovery(row.url, raw_by_stamp[row.stamp], "")
            source = table_by_digest[row.digest][1]
            return A19Discovery(
                f"https://web.archive.org/web/{source}/{A19_SOURCE_URL}",
                raw_by_stamp[source],
                "",
                witness=row.stamp,
                witness_reason=unread[row.stamp],
            )
        return None

    reads = 0
    capped = False
    for row in rows:
        found = settled()
        if found is not None:
            return found
        if not row.exact:
            continue
        if row.digest is not None and row.digest in table_by_digest:
            # A verified read of this digest already says what it holds.
            continue
        if reads == A19_MAX_WINDOW_CAPTURES:
            capped = True
            break
        reads += 1
        try:
            raw = a19_read_capture(row.url, read, row.digest)
        except (*_WAYBACK_READ_ERRORS, A19CaptureError) as exc:
            if row.status != "200":
                unread[row.stamp] = (
                    "which could not be read and verified at that timestamp"
                )
                continue
            return A19Discovery(
                None,
                None,
                (
                    f"CAPTURE READ FAILED (deferring): {row.url} could not be read "
                    f"({type(exc).__name__}: {str(exc)[:160]}), and an unread "
                    "earlier capture cannot be skipped"
                ),
            )
        table = a19_table(raw.decode(errors="replace"))
        if table is None:
            # Not "a different month": an error page, a changed layout or an
            # empty body says nothing about what the page printed.
            if row.status != "200":
                unread[row.stamp] = (
                    "which was served at that timestamp as something other than "
                    "this table"
                )
                continue
            return A19Discovery(
                None,
                None,
                (
                    f"CAPTURE UNIDENTIFIED (deferring): {row.url} does not parse as "
                    "Table A-19, and an unidentified earlier capture cannot be "
                    "skipped"
                ),
            )
        table_by_stamp[row.stamp] = table
        raw_by_stamp[row.stamp] = raw
        if row.digest is not None:
            table_by_digest.setdefault(row.digest, (table, row.stamp))
    found = settled()
    if found is not None:
        return found
    first = next((row for row in rows if month_of(row) == period), None)
    blocking = (
        [r.stamp for r in rows if r.stamp < first.stamp and month_of(r) is None]
        if first is not None
        else []
    )
    if capped:
        where = (
            f"{first.url} prints {period}, but {len(blocking)} earlier row(s) "
            f"({', '.join(blocking[:3])}) are not accounted for"
            if first is not None
            else f"none of the rows identified so far prints {period}"
        )
        return A19Discovery(
            None,
            None,
            (
                f"CAPTURE SCAN LIMIT REACHED (deferring): {reads} read attempt(s) "
                f"made, of {len(rows)} row(s) inside {window!r} that could hold the "
                f"page; the earliest print of {period} is not settled: {where}"
            ),
        )
    if first is not None:
        return A19Discovery(
            None,
            None,
            (
                f"EARLIER ROW UNREAD (deferring): {first.url} prints {period}, but "
                f"{len(blocking)} earlier row(s) ({', '.join(blocking[:3])}) were "
                "not read and identified at their own timestamp, and no read "
                "capture carries their digest, so it may not be the earliest"
            ),
        )
    revisits = index.revisits
    others = index.other_form_rows
    unknown = [row for row in rows if month_of(row) is None]
    notes = [
        f"all {len(index.captures)} HTTP 200 capture(s) were read or accounted "
        "for by a verified digest, and none "
        f"prints {period}"
    ]
    if revisits:
        served = sum(1 for row in revisits if row.stamp in table_by_stamp)
        missing = sum(1 for row in revisits if month_of(row) is None)
        notes.append(
            f"of {len(revisits)} row(s) without a status, {served} were served at "
            f"their own timestamp and read, {len(revisits) - served - missing} "
            f"share the digest of a read capture, {missing} remain unknown"
        )
    if index.other_form:
        missing = sum(1 for row in others if month_of(row) is None)
        notes.append(
            f"{index.other_form} row(s) under another form of the URL were not "
            f"read: {len(others) - missing} share the digest of a read capture, "
            f"{missing} remain unknown, {index.other_form - len(others)} have a "
            "status other than 200"
        )
    read_note = "; ".join(notes)
    if state == "missed" and unknown:
        # A row under another form of the URL, or without a status and
        # matched by nothing, may be a capture of this page that prints the
        # month. Unknown is not "missed": what was read prints another month,
        # and what was not read is not known.
        return A19Discovery(
            None,
            None,
            (
                "WINDOW OUTCOME UNKNOWN (deferring): the Archive's index lists "
                f"{index.describe(window)}; {read_note}"
            ),
        )
    if state == "missed":
        return A19Discovery(
            None,
            None,
            (
                "FIRST-PRINT WINDOW MISSED (refusing): the Archive's index lists "
                f"{index.describe(window)}; {read_note}"
            ),
        )
    if not request_capture:
        return A19Discovery(
            None,
            None,
            (
                f"none of the rows read inside the registered window prints "
                f"{period} yet: the Archive's index lists {index.describe(window)}; "
                f"{read_note} (deferring)"
            ),
        )
    # An error from the save endpoint does not mean no capture was made: on
    # 2026-09-21 three requests were each answered HTTP 500 and the index then
    # held a new capture (20260921154639) that read back through
    # a19_read_capture. So a failed request still counts as this run's one
    # request, and the verdict does not say the capture failed.
    try:
        read(WAYBACK_SAVE_URL.format(url=A19_SOURCE_URL))
        requested = A19_CAPTURE_REQUESTED
    except _WAYBACK_READ_ERRORS as exc:
        requested = (
            f"{A19_CAPTURE_REQUESTED}; the request returned "
            f"{type(exc).__name__}, outcome unknown"
        )
    return A19Discovery(
        None,
        None,
        (
            f"none of the rows read inside the registered window prints {period} "
            f"yet: the Archive's index lists {index.describe(window)}; {read_note}; "
            f"{requested} (deferring)"
        ),
    )
'''


def _pre_change_namespace() -> dict:
    namespace = dict(vars(rp))
    exec(compile(_PRE_CHANGE_SOURCE, "<pre-change A-19 discovery>", "exec"), namespace)
    return namespace


OLD = _pre_change_namespace()
WINDOW = {"start": "2020-07-01", "end": "2020-07-10"}
CLOSED = dt.date(2020, 7, 11)
SOURCE_URLS = (
    "https://www.bls.gov/news.release/cpi.nr0.htm",
    "https://www.bls.gov/news.release/empsit.nr0.htm",
    "https://www.bls.gov/news.release/jolts.nr0.htm",
    "https://www.bls.gov/news.release/jolts.t04.htm",
    "https://www.bls.gov/web/empsit/cpseea41.htm",
)


def _stamp(day: int) -> str:
    return f"202007{day:02d}120000"


def _url(stamp: str, source_url: str) -> str:
    return f"https://web.archive.org/web/{stamp}/{source_url}"


def _page(period: str, value: int = 17) -> bytes:
    return json.dumps([period, value]).encode()


def _parser(html: str) -> tuple[str, float] | None:
    try:
        period, value = json.loads(html)
        return period, float(value)
    except (ValueError, TypeError):
        return None


def _reader(index: bytes, pages: dict[str, bytes], calls: list[str], source_url: str):
    def read(url: str) -> tuple[bytes, str]:
        calls.append(url)
        if url.startswith("https://web.archive.org/cdx/"):
            assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["url"] == [
                source_url
            ]
            return index, url
        if url.startswith("https://web.archive.org/save/"):
            assert url.endswith(source_url)
            return b"saved", url
        for stamp, raw in pages.items():
            if url == f"https://web.archive.org/web/{stamp}id_/{source_url}":
                return raw, url
        raise urllib.error.HTTPError(url, 404, "no capture", None, None)

    return read


def _index(pages: dict[str, bytes], source_url: str, order: list[str]) -> bytes:
    return cdx(
        *[(stamp, "200", source_url, rp.a19_digest(pages[stamp])) for stamp in order]
    )


def _discover(index: bytes, pages: dict[str, bytes], source_url: str, **kwargs):
    calls: list[str] = []
    found = rp.a19_registered_capture(
        "2020-06",
        WINDOW,
        CLOSED,
        _reader(index, pages, calls, source_url),
        source_url=source_url,
        parser=_parser,
        parser_name="synthetic release table",
        request_capture=False,
        require_digest=True,
        **kwargs,
    )
    assert not any("/save/" in url for url in calls)
    return found, calls


@settings(max_examples=50, deadline=None)
@given(
    source_url=st.sampled_from(SOURCE_URLS),
    matching_days=st.sets(st.integers(min_value=1, max_value=10), min_size=1),
    order=st.permutations(list(range(1, 11))),
)
def test_earliest_print_wins_regardless_of_index_order(
    source_url: str, matching_days: set[int], order: list[int]
) -> None:
    pages = {
        _stamp(day): _page("2020-06" if day in matching_days else "2020-05", day)
        for day in order
    }
    found, calls = _discover(_index(pages, source_url, list(pages)), pages, source_url)
    earliest = _stamp(min(matching_days))
    assert found.url == _url(earliest, source_url)
    assert found.raw == pages[earliest]
    assert found.verdict == ""
    assert len(calls) == min(matching_days) + 1


@settings(max_examples=25, deadline=None)
@given(
    source_url=st.sampled_from(SOURCE_URLS),
    day=st.integers(min_value=1, max_value=9),
)
def test_unreadable_earlier_http_200_defers(source_url: str, day: int) -> None:
    pages = {_stamp(day + 1): _page("2020-06")}
    index = cdx(
        (_stamp(day + 1), "200", source_url, rp.a19_digest(pages[_stamp(day + 1)])),
        (_stamp(day), "200", source_url, rp.a19_digest(b"not served")),
    )
    found, calls = _discover(index, pages, source_url)
    assert found.url is None
    assert found.verdict.startswith("CAPTURE READ FAILED (deferring)")
    assert not any(f"/{_stamp(day + 1)}id_/" in url for url in calls)


@settings(max_examples=25, deadline=None)
@given(source_url=st.sampled_from(SOURCE_URLS), body=st.binary(min_size=1))
def test_digest_mismatch_refuses(source_url: str, body: bytes) -> None:
    actual = _page("2020-06")
    if rp.a19_digest(body) == rp.a19_digest(actual):
        body += b"wrong digest"
    index = cdx((_stamp(1), "200", source_url, rp.a19_digest(body)))
    found, _ = _discover(index, {_stamp(1): actual}, source_url)
    assert found.url is None
    assert "does not hash to its index digest" in found.verdict


@settings(max_examples=25, deadline=None)
@given(
    source_url=st.sampled_from(SOURCE_URLS),
    days=st.sets(st.integers(min_value=1, max_value=10), min_size=1),
)
def test_closed_fully_accounted_window_of_other_months_is_missed(
    source_url: str, days: set[int]
) -> None:
    pages = {_stamp(day): _page("2020-05", day) for day in days}
    found, _ = _discover(_index(pages, source_url, list(pages)), pages, source_url)
    assert found.url is None
    assert found.verdict.startswith("FIRST-PRINT WINDOW MISSED (refusing)")


@pytest.mark.parametrize("source_url", SOURCE_URLS)
def test_unidentified_http_200_stops_the_walk(source_url: str) -> None:
    pages = {_stamp(1): b"<html>error</html>", _stamp(2): _page("2020-06")}
    found, calls = _discover(_index(pages, source_url, list(pages)), pages, source_url)
    assert found.url is None
    assert "does not parse as synthetic release table" in found.verdict
    assert not any(f"/{_stamp(2)}id_/" in url for url in calls)


@pytest.mark.parametrize("source_url", SOURCE_URLS)
def test_unknown_digest_is_never_read_in_strict_mode(source_url: str) -> None:
    pages = {_stamp(1): _page("2020-06")}
    index = cdx((_stamp(1), "200", source_url, "-"))
    found, calls = _discover(index, pages, source_url)
    assert found.url is None
    assert "no verifiable index digest" in found.verdict
    assert len(calls) == 1  # index only; never fetch unverifiable bytes


@pytest.mark.parametrize("source_url", SOURCE_URLS)
def test_revisit_can_witness_later_verified_bytes(source_url: str) -> None:
    pages = {_stamp(2): _page("2020-06")}
    digest = rp.a19_digest(pages[_stamp(2)])
    index = cdx(
        (_stamp(2), "200", source_url, digest),
        (_stamp(1), "-", source_url, digest),
    )
    found, _ = _discover(index, pages, source_url)
    assert found.url == _url(_stamp(2), source_url)
    assert found.witness == _stamp(1)
    assert found.raw == pages[_stamp(2)]


@pytest.mark.parametrize("source_url", SOURCE_URLS)
def test_source_url_is_bound_for_digest_and_identity_reads(source_url: str) -> None:
    raw = _page("2020-06")
    stored = gzip.compress(raw)
    url = _url(_stamp(1), source_url)
    calls: list[str] = []
    read = _reader(b"[]", {_stamp(1): stored}, calls, source_url)
    assert (
        rp.a19_read_capture(url, read, rp.a19_digest(stored), source_url=source_url)
        == raw
    )
    assert calls == [f"https://web.archive.org/web/{_stamp(1)}id_/{source_url}"]
    with pytest.raises(rp.A19CaptureError, match="not a capture of"):
        rp.a19_read_capture(url, read, rp.a19_digest(stored))
    with pytest.raises(rp.A19CaptureError, match="was served"):
        rp.a19_read_capture(
            url,
            lambda requested: (raw, requested.replace(source_url, rp.A19_SOURCE_URL)),
            rp.a19_digest(raw),
            source_url=source_url,
        )


@st.composite
def _legacy_cases(draw):
    states = draw(
        st.lists(
            st.tuples(
                st.sampled_from(("200", "-", "403")),
                st.sampled_from(("june", "july", "unidentified", "unreadable")),
                st.booleans(),  # URL alternate form
                st.sampled_from(("valid", "unknown", "wrong")),
            ),
            min_size=0,
            max_size=10,
        )
    )
    june = fixture("2026-06").encode()
    pages_by_kind = {
        "june": june,
        "july": june.replace(b"June", b"July"),
        "unidentified": b"<html>not Table A-19</html>",
        "unreadable": b"no captured body",
    }
    rows = []
    pages = {}
    for day, (status, kind, alternate, digest_mode) in enumerate(states, 1):
        stamp = _stamp(day)
        body = pages_by_kind[kind]
        original = (
            rp.A19_SOURCE_URL.replace("https://", "http://")
            if alternate
            else rp.A19_SOURCE_URL
        )
        digest = (
            "-"
            if digest_mode == "unknown"
            else rp.a19_digest(body if digest_mode == "valid" else b"other digest")
        )
        rows.append((stamp, status, original, digest))
        if kind != "unreadable":
            pages[stamp] = body
    rows = draw(st.permutations(rows))
    return cdx(*rows), pages


@settings(max_examples=75, deadline=None)
@given(
    case=_legacy_cases(),
    today=st.sampled_from((dt.date(2020, 6, 30), dt.date(2020, 7, 5), CLOSED)),
    request_capture=st.booleans(),
    cap=st.integers(min_value=0, max_value=5),
)
def test_default_a19_matches_frozen_prechange_discovery(
    case, today: dt.date, request_capture: bool, cap: int
) -> None:
    index, pages = case
    previous_cap = rp.A19_MAX_WINDOW_CAPTURES
    rp.A19_MAX_WINDOW_CAPTURES = cap
    OLD["A19_MAX_WINDOW_CAPTURES"] = cap
    try:
        expected_calls: list[str] = []
        actual_calls: list[str] = []
        expected = OLD["a19_registered_capture"](
            "2026-07",
            WINDOW,
            today,
            _reader(index, pages, expected_calls, rp.A19_SOURCE_URL),
            request_capture=request_capture,
        )
        actual = rp.a19_registered_capture(
            "2026-07",
            WINDOW,
            today,
            _reader(index, pages, actual_calls, rp.A19_SOURCE_URL),
            request_capture=request_capture,
            source_url=rp.A19_SOURCE_URL,
            parser=rp.a19_table,
        )
        actual_result = asdict(actual)
        actual_result.pop("digest")
        expected_result = asdict(expected)
        expected_result.pop("digest", None)
        assert actual_result == expected_result
        assert actual_calls == expected_calls

        expected_index = OLD["a19_window_captures"](
            WINDOW, _reader(index, pages, [], rp.A19_SOURCE_URL)
        )
        actual_index = rp.a19_window_captures(
            WINDOW,
            _reader(index, pages, [], rp.A19_SOURCE_URL),
            source_url=rp.A19_SOURCE_URL,
        )
        actual_rows = [asdict(row) for row in actual_index.rows]
        for row in actual_rows:
            assert row.pop("source_url") == rp.A19_SOURCE_URL
        assert actual_rows == [asdict(row) for row in expected_index.rows]
        for attribute in ("listed", "other_status", "other_form", "captures"):
            assert getattr(actual_index, attribute) == getattr(
                expected_index, attribute
            )
        assert actual_index.describe(WINDOW) == expected_index.describe(WINDOW)
    finally:
        rp.A19_MAX_WINDOW_CAPTURES = previous_cap
