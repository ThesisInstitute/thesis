"""Offline tests for the registered-window witness.

Every request goes through an injected fetcher; nothing here touches the
network, the Internet Archive, or the live Thesis log.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import types
import urllib.parse
from collections.abc import Callable
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import witness_registered_windows as witness  # noqa: E402

TODAY = dt.date(2026, 9, 20)
A19 = "https://www.bls.gov/web/empsit/cpseea19.htm"
SNAP = "https://www.fns.usda.gov/pd/supplemental-nutrition-assistance-program-snap"
SSA = "https://www.ssa.gov/policy/docs/statcomps/ssi_monthly/2026-07/table02.html"
STATCAN = (
    "https://www150.statcan.gc.ca/t1/wds/rest/"
    "getDataFromVectorByReferencePeriodRange?vectorIds=64549350"
)
CDX_HEADER = list(witness.CDX_FIELDS)


# ---------------------------------------------------------------------------
# Builders


def make_target(
    ref: str,
    url: str,
    start: str,
    end: str,
    *,
    file: str = "2026-09-14-" + "a" * 64 + ".json",
    hosts: tuple[str, ...] | None = None,
) -> witness.Target:
    host = urllib.parse.urlsplit(url).hostname or ""
    return witness.Target(
        data_point_id=ref,
        catalog_slug=ref.replace(".", "-"),
        source_url=url,
        window_start=dt.date.fromisoformat(start),
        window_end=dt.date.fromisoformat(end),
        registration_file=file,
        target_content_hash="a" * 64,
        no_plan_reason="sourceBinding.adapter is 'generic-url'",
        allowed_hosts=(host,) if hosts is None else hosts,
    )


def cdx_body(*rows: tuple[str, str], url: str = A19) -> bytes:
    """A CDX JSON response: (timestamp, statuscode) rows under the header."""

    body = [CDX_HEADER] + [
        [stamp, url, status, "text/html", f"DIGEST{stamp[-4:]}", "15839"]
        for stamp, status in rows
    ]
    return json.dumps(body).encode()


class FakeArchive:
    """Records every request and answers from per-URL scripts."""

    def __init__(
        self,
        *,
        save: Callable[[str], witness.Response] | None = None,
        index: Callable[[str, dict[str, str]], bytes] | None = None,
    ) -> None:
        self.requests: list[str] = []
        self._save = save
        self._index = index

    @property
    def saves(self) -> list[str]:
        prefix = "https://web.archive.org/save/"
        return [r[len(prefix) :] for r in self.requests if r.startswith(prefix)]

    @property
    def index_reads(self) -> list[dict[str, str]]:
        return [
            dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r).query))
            for r in self.requests
            if r.startswith(witness.WAYBACK_CDX_ENDPOINT)
        ]

    def __call__(self, url: str, timeout: float) -> witness.Response:
        self.requests.append(url)
        if url.startswith("https://web.archive.org/save/"):
            original = url[len("https://web.archive.org/save/") :]
            if self._save is not None:
                return self._save(original)
            return saved(original, "20260920194501")
        if url.startswith(witness.WAYBACK_CDX_ENDPOINT):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            body = self._index(query["url"], query) if self._index else b"[]"
            return witness.Response(200, url, {}, body)
        raise AssertionError(f"unexpected request: {url}")


def saved(
    original: str, stamp: str, *, archived: str | None = None
) -> witness.Response:
    final = f"https://web.archive.org/web/{stamp}/{archived or original}"
    return witness.Response(200, final, {}, b"<html>archived</html>")


def transport(fetch: Callable[..., Any], **kwargs: Any) -> witness.Transport:
    sleeps: list[float] = []
    built = witness.Transport(
        fetch=fetch,
        sleep=sleeps.append,
        clock=lambda: 0.0,
        today=kwargs.pop("today", lambda: TODAY),
        **kwargs,
    )
    built.sleeps = sleeps  # type: ignore[attr-defined]
    return built


def run(
    targets: list[witness.Target],
    fetch: Callable[..., Any],
    *,
    pending: set[str] | None | str = "all",
    today: dt.date = TODAY,
    mode: str = "capture",
    **options: Any,
) -> dict[str, Any]:
    refs = {t.data_point_id for t in targets} if pending == "all" else pending
    return witness.run(
        targets=targets,
        pending=refs,  # type: ignore[arg-type]
        today=today,
        transport=transport(fetch, today=lambda: today),
        options=witness.Options(mode=mode, **options),
    )


def no_network(url: str, timeout: float) -> witness.Response:
    raise AssertionError(f"this path must not touch the network: {url}")


# ---------------------------------------------------------------------------
# Selection: window and pending state


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ("2026-10-05", 0),  # the day before the window opens
        ("2026-10-06", 1),  # first day, inclusive
        ("2026-10-10", 1),
        ("2026-10-14", 1),  # last day, inclusive
        ("2026-10-15", 0),  # the day after it closes
    ],
)
def test_a_window_is_open_from_its_first_day_through_its_last(
    day: str, expected: int
) -> None:
    target = make_target("bls.a19.sept", A19, "2026-10-06", "2026-10-14")
    selection = witness.select([target], {"bls.a19.sept"}, dt.date.fromisoformat(day))
    assert len(selection.open_plans) == expected


def test_only_pending_forecasts_are_witnessed_and_the_rest_are_reported() -> None:
    pending = make_target("fns.snap.pending", SNAP, "2026-09-16", "2026-09-24")
    linked = make_target("bls.a19.linked", A19, "2026-09-16", "2026-09-24")
    never_forecast = make_target("ssa.unforecast", SSA, "2026-09-16", "2026-09-24")
    archive = FakeArchive()
    report = run(
        [pending, linked, never_forecast], archive, pending={"fns.snap.pending"}
    )
    assert archive.saves == [SNAP]
    assert report["counts"]["inWindowButNotPending"] == 2
    assert {r["dataPointId"] for r in report["inWindowButNotPending"]} == {
        "bls.a19.linked",
        "ssa.unforecast",
    }


def test_pending_refs_reads_only_pending_resolution_links() -> None:
    log = {
        "resolutionLinks": [
            {"status": "pending", "targetFactRef": "a"},
            {"status": "linked", "targetFactRef": "b"},
            {"status": "pending", "targetFactRef": ""},
            {"status": "pending"},
            "not a link",
        ]
    }
    assert witness.pending_refs(log) == {"a"}


def test_an_unreadable_log_keeps_every_open_target_rather_than_none() -> None:
    def broken() -> dict[str, Any]:
        raise OSError("log.json unreachable")

    pending, failure = witness.load_pending(None, broken)
    assert pending is None
    assert "log.json unreachable" in failure
    target = make_target("fns.snap", SNAP, "2026-09-16", "2026-09-24")
    archive = FakeArchive()
    report = run([target], archive, pending=None)
    assert archive.saves == [SNAP]
    assert report["pendingStateKnown"] is False


def test_a_log_without_resolution_links_is_an_unknown_state_not_an_empty_one() -> None:
    pending, failure = witness.load_pending(None, lambda: {"entries": []})
    assert pending is None
    assert "resolutionLinks" in failure


# ---------------------------------------------------------------------------
# De-duplication


def test_targets_sharing_a_page_cost_one_save_and_one_index_read() -> None:
    rows = [
        make_target(f"bls.a19.row{i}", A19, "2026-09-16", "2026-09-24")
        for i in range(6)
    ]
    archive = FakeArchive()
    report = run(rows, archive)
    assert archive.saves == [A19]
    assert len(archive.index_reads) == 1
    assert len(report["openWindows"]) == 1
    assert len(report["openWindows"][0]["registrations"]) == 6


def test_a_target_registered_in_two_snapshots_is_listed_once() -> None:
    first = make_target("fns.snap", SNAP, "2026-09-16", "2026-09-24")
    second = make_target(
        "fns.snap",
        SNAP,
        "2026-09-16",
        "2026-09-24",
        file="2026-09-15-" + "b" * 64 + ".json",
    )
    report = run([first, second], FakeArchive())
    assert len(report["openWindows"][0]["registrations"]) == 1


def test_one_page_with_two_windows_reads_the_index_from_the_earlier_start() -> None:
    august = make_target("fns.snap.may", SNAP, "2026-09-10", "2026-09-20")
    september = make_target("fns.snap.june", SNAP, "2026-09-18", "2026-09-26")
    archive = FakeArchive()
    run([august, september], archive)
    assert archive.saves == [SNAP]
    assert archive.index_reads[0]["from"] == "20260910000000"
    assert archive.index_reads[0]["to"] == "20260920235959"


def test_consecutive_requests_avoid_the_same_host_when_another_is_waiting() -> None:
    plans = witness._group(
        [
            make_target("a", "https://www.bls.gov/a.htm", "2026-09-16", "2026-09-21"),
            make_target("b", "https://www.bls.gov/b.htm", "2026-09-16", "2026-09-22"),
            make_target("c", "https://www.nbb.be/c", "2026-09-16", "2026-09-23"),
        ]
    )
    hosts = [p.host for p in witness._interleave_hosts(plans)]
    assert hosts == ["www.bls.gov", "www.nbb.be", "www.bls.gov"]


# ---------------------------------------------------------------------------
# No capture is ever requested outside a registered window


def test_no_save_is_requested_on_any_day_outside_every_window() -> None:
    targets = [
        make_target("bls.a19", A19, "2026-10-06", "2026-10-14"),
        make_target("fns.snap", SNAP, "2026-10-01", "2026-10-09"),
        make_target("ssa.ssi", SSA, "2026-10-12", "2026-10-12"),
    ]
    day = dt.date(2026, 9, 25)
    while day <= dt.date(2026, 10, 20):
        archive = FakeArchive(save=lambda original: saved(original, "20261001000000"))
        run(targets, archive, today=day)
        for url in archive.saves:
            owners = [t for t in targets if t.source_url == url]
            assert any(t.window_start <= day <= t.window_end for t in owners), (
                f"{url} was requested on {day}, outside every window that binds it"
            )
        expected = {
            t.source_url for t in targets if t.window_start <= day <= t.window_end
        }
        assert set(archive.saves) == expected
        day += dt.timedelta(days=1)


def test_a_run_crossing_midnight_asks_for_no_capture_dated_too_late() -> None:
    closing = make_target(
        "treasury.mts", "https://fiscaldata.treasury.gov/x/", "2026-09-13", "2026-09-20"
    )
    archive = FakeArchive()
    report = witness.run(
        targets=[closing],
        pending={"treasury.mts"},
        today=TODAY,
        transport=transport(archive, today=lambda: TODAY + dt.timedelta(days=1)),
        options=witness.Options(),
    )
    assert archive.saves == []
    save = report["openWindows"][0]["save"]
    assert save["requested"] is False
    assert "2026-09-21" in save["why"]


def test_closed_windows_are_read_from_the_index_and_never_saved() -> None:
    closed = make_target(
        "bls.cpi",
        "https://www.bls.gov/news.release/cpi.nr0.htm",
        "2026-09-08",
        "2026-09-16",
    )
    archive = FakeArchive()
    report = run([closed], archive)
    assert archive.saves == []
    assert archive.index_reads == [
        {
            "url": closed.source_url,
            "from": "20260908000000",
            "to": "20260916235959",
            "output": "json",
            "fl": ",".join(witness.CDX_FIELDS),
        }
    ]
    row = report["closedWindows"][0]["registrations"][0]
    assert row["http200CapturesInWindow"] == 0
    assert report["custodyGaps"]["closedWithoutCapture"][0]["dataPointId"] == "bls.cpi"
    assert "WINDOW CLOSED WITHOUT A CAPTURE" in witness.render_text(report)


def test_windows_closed_longer_ago_than_the_lookback_are_left_alone() -> None:
    old = make_target("bls.old", A19, "2026-08-01", "2026-08-09")
    archive = FakeArchive()
    report = run([old], archive)
    assert archive.requests == []
    assert report["closedWindows"] == []


# ---------------------------------------------------------------------------
# Dry run and audit


def test_dry_run_prints_the_plan_and_sends_nothing() -> None:
    targets = [
        make_target("bls.a19", A19, "2026-09-16", "2026-09-24"),
        make_target(
            "bls.cpi",
            "https://www.bls.gov/news.release/cpi.nr0.htm",
            "2026-09-08",
            "2026-09-16",
        ),
    ]
    report = run(targets, no_network, mode="dry-run")
    text = witness.render_text(report)
    assert f"WOULD REQUEST: https://web.archive.org/save/{A19}" in text
    assert "WOULD READ: https://web.archive.org/cdx/search/cdx?" in text
    assert "custodyGaps" not in report


def test_audit_reads_every_started_window_and_requests_no_capture() -> None:
    targets = [
        make_target("bls.open", A19, "2026-09-16", "2026-09-24"),
        make_target("bls.long_closed", SNAP, "2026-07-01", "2026-07-09"),
        make_target("bls.future", SSA, "2026-10-12", "2026-10-20"),
    ]
    archive = FakeArchive()
    report = run(targets, archive, mode="audit")
    assert archive.saves == []
    assert {q["url"] for q in archive.index_reads} == {A19, SNAP}
    assert report["openWindows"][0]["save"] == {
        "requested": False,
        "why": "index read only",
    }


# ---------------------------------------------------------------------------
# Failure paths never escape the run


def test_a_refused_save_is_reported_and_the_next_url_still_runs() -> None:
    def save(original: str) -> witness.Response:
        if "ssa.gov" in original:
            raise witness.FetchError("HTTP 520: Job failed", status=520)
        return saved(original, "20260920194501")

    targets = [
        make_target("ssa.ssi", SSA, "2026-09-16", "2026-09-21"),
        make_target("fns.snap", SNAP, "2026-09-16", "2026-09-24"),
    ]
    archive = FakeArchive(save=save)
    report = run(targets, archive)
    by_url = {e["sourceUrl"]: e for e in report["openWindows"]}
    assert archive.saves.count(SSA) == witness.DEFAULT_ATTEMPTS
    assert archive.saves.count(SNAP) == 1
    assert by_url[SSA]["verdict"]["code"] == "SAVE_FAILED"
    assert "HTTP 520: Job failed" in by_url[SSA]["verdict"]["text"]
    assert any("2026-08-23" in note for note in by_url[SSA]["knownLimits"])
    assert by_url[SNAP]["verdict"]["code"] == "SAVE_NOT_YET_INDEXED"
    gap = report["custodyGaps"]["closingWithoutCapture"]
    assert [g["dataPointId"] for g in gap] == ["ssa.ssi"]


def test_an_unexpected_exception_in_the_fetcher_is_one_url_s_failure() -> None:
    def explode(url: str, timeout: float) -> witness.Response:
        if "bls.gov" in url:
            raise RuntimeError("fetcher bug")
        return FakeArchive()(url, timeout)

    targets = [
        make_target("bls.a19", A19, "2026-09-16", "2026-09-24"),
        make_target("fns.snap", SNAP, "2026-09-16", "2026-09-24"),
    ]
    report = run(targets, explode)
    by_url = {e["sourceUrl"]: e for e in report["openWindows"]}
    assert "RuntimeError: fetcher bug" in by_url[A19]["verdict"]["text"]
    assert by_url[A19]["verdict"]["code"] == "INDEX_UNREAD"
    assert by_url[SNAP]["verdict"]["code"] == "SAVE_NOT_YET_INDEXED"


@pytest.mark.parametrize(
    "body",
    [
        b"<html>429 Too Many Requests</html>",
        b'{"error": "x"}',
        b"[[1, 2], 3]",
        b"\xff\xfe",
    ],
)
def test_an_unreadable_index_is_a_failure_to_look_not_a_finding(body: bytes) -> None:
    target = make_target("bls.a19", A19, "2026-09-16", "2026-09-21")
    archive = FakeArchive(index=lambda url, query: body)
    report = run([target], archive)
    entry = report["openWindows"][0]
    assert entry["index"]["ok"] is False
    assert entry["verdict"]["code"] == "INDEX_UNREAD"
    assert "named a capture at 2026-09-20T19:45:01Z" in entry["verdict"]["text"]
    assert report["custodyGaps"]["closingWithoutCapture"] == []


def test_rate_limits_are_retried_a_bounded_number_of_times_with_backoff() -> None:
    calls = {"n": 0}

    def fetch(url: str, timeout: float) -> witness.Response:
        calls["n"] += 1
        raise witness.FetchError(
            "HTTP 429: Too Many Requests", status=429, retry_after=7.0
        )

    carrier = transport(fetch, attempts=3)
    response, outcome = carrier.get("https://web.archive.org/save/x", 10.0)
    assert response is None
    assert calls["n"] == 3
    assert outcome["attempts"] == 3
    assert outcome["httpStatus"] == 429
    assert carrier.sleeps == [7.0, 7.0]  # type: ignore[attr-defined]


def test_a_retry_after_header_cannot_stall_the_run() -> None:
    def fetch(url: str, timeout: float) -> witness.Response:
        raise witness.FetchError("HTTP 429", status=429, retry_after=86_400.0)

    carrier = transport(fetch, attempts=2)
    carrier.get("https://web.archive.org/save/x", 10.0)
    assert carrier.sleeps == [witness.MAX_RETRY_AFTER]  # type: ignore[attr-defined]


def test_an_exhausted_time_budget_stops_asking_and_says_so() -> None:
    now = {"t": 0.0}

    def fetch(url: str, timeout: float) -> witness.Response:
        now["t"] += 400.0
        raise witness.FetchError("TimeoutError: timed out")

    carrier = witness.Transport(
        fetch=fetch,
        sleep=lambda seconds: None,
        clock=lambda: now["t"],
        today=lambda: TODAY,
        attempts=3,
        deadline_seconds=600.0,
    )
    targets = [
        make_target("a", "https://www.bls.gov/a.htm", "2026-09-16", "2026-09-24"),
        make_target("b", "https://www.nbb.be/b", "2026-09-16", "2026-09-24"),
    ]
    report = witness.run(
        targets=targets,
        pending={"a", "b"},
        today=TODAY,
        transport=carrier,
        options=witness.Options(),
    )
    texts = [e["verdict"]["text"] for e in report["openWindows"]]
    assert len(texts) == 2
    assert any("time budget exhausted" in text for text in texts)


def test_http_fetch_turns_every_transport_fault_into_a_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionResetError("peer reset")

    monkeypatch.setattr(witness.urllib.request, "urlopen", refuse)
    with pytest.raises(witness.FetchError, match="ConnectionResetError"):
        witness.http_fetch("https://web.archive.org/save/x", 1.0)


# ---------------------------------------------------------------------------
# What the index says


def test_a_capture_the_index_lists_today_is_reported_with_its_timestamp() -> None:
    target = make_target("bls.a19", A19, "2026-09-16", "2026-09-24")
    archive = FakeArchive(
        index=lambda url, query: cdx_body(
            ("20260917031500", "200"), ("20260920194501", "200")
        )
    )
    entry = run([target], archive)["openWindows"][0]
    assert entry["verdict"]["code"] == "CAPTURED"
    assert entry["verdict"]["capturedAt"] == "2026-09-20T19:45:01Z"
    assert (
        entry["verdict"]["link"] == f"https://web.archive.org/web/20260920194501/{A19}"
    )
    row = entry["registrations"][0]
    assert row["http200CapturesInWindow"] == 2
    assert row["firstCaptureInWindow"] == "2026-09-17T03:15:00Z"
    assert row["distinctDigestsInWindow"] == 2


def test_the_archive_s_own_crawl_counts_when_the_save_was_refused() -> None:
    def save(original: str) -> witness.Response:
        raise witness.FetchError("HTTP 520: Job failed", status=520)

    target = make_target("ssa.ssi", SSA, "2026-09-16", "2026-09-21")
    archive = FakeArchive(
        save=save, index=lambda url, query: cdx_body(("20260920060000", "200"), url=SSA)
    )
    report = run([target], archive)
    verdict = report["openWindows"][0]["verdict"]
    assert verdict["code"] == "CAPTURED"
    assert "the save request failed: HTTP 520" in verdict["text"]
    assert report["custodyGaps"]["closingWithoutCapture"] == []


def test_a_refused_capture_is_listed_but_is_not_custody() -> None:
    target = make_target("bls.a19", A19, "2026-09-16", "2026-09-21")
    archive = FakeArchive(index=lambda url, query: cdx_body(("20260920194501", "403")))
    report = run([target], archive)
    entry = report["openWindows"][0]
    assert entry["verdict"]["code"] == "CAPTURED_NOT_AS_PAGE"
    assert "403" in entry["verdict"]["text"]
    assert entry["registrations"][0]["http200CapturesInWindow"] == 0
    assert len(report["custodyGaps"]["closingWithoutCapture"]) == 1


def test_captures_outside_the_window_never_count_toward_it() -> None:
    target = make_target("bls.a19", A19, "2026-09-16", "2026-09-24")
    rows = witness.parse_cdx(
        cdx_body(
            ("20260915235959", "200"),
            ("20260916000000", "200"),
            ("20260925000000", "200"),
        ),
        target.window_start,
        target.window_end,
    )
    assert [r["timestamp"] for r in rows] == ["20260916000000"]


def test_the_recorded_archive_index_fixture_parses() -> None:
    fixture = (
        ROOT / "tests" / "fixtures" / "ssa_official" / "cdx_stat_snapshot_2026-06.json"
    )
    rows = witness.parse_cdx(
        fixture.read_bytes(), dt.date(2026, 7, 1), dt.date(2026, 8, 31)
    )
    assert [r["timestamp"] for r in rows] == [
        "20260711204033",
        "20260802032502",
        "20260806225812",
    ]
    assert all(witness._is_page_capture(r) for r in rows)


def test_a_redirecting_page_is_reported_under_the_url_it_went_to() -> None:
    registered = "https://www.bea.gov/data/pce-price-index-excluding-food-and-energy"
    landed = "https://www.bea.gov/data/personal-consumption-expenditures-price-index-excluding-food-and-energy"
    target = make_target("bea.core_pce", registered, "2026-09-16", "2026-09-21")

    def index(url: str, query: dict[str, str]) -> bytes:
        if url == registered:
            return cdx_body(("20260920194501", "301"), url=registered)
        return cdx_body(("20260920194502", "200"), url=landed)

    archive = FakeArchive(
        save=lambda original: saved(original, "20260920194502", archived=landed),
        index=index,
    )
    report = run([target], archive)
    entry = report["openWindows"][0]
    assert entry["verdict"]["code"] == "CAPTURED_UNDER_REDIRECT_TARGET"
    assert landed in entry["verdict"]["text"]
    assert entry["registrations"][0]["http200CapturesInWindow"] == 0
    assert report["custodyGaps"]["closingWithoutCapture"] == []


def test_a_window_on_its_last_days_waiting_on_the_index_is_kept_apart() -> None:
    target = make_target(
        "treasury.mts", "https://fiscaldata.treasury.gov/x/", "2026-09-13", "2026-09-21"
    )
    report = run([target], FakeArchive())
    gaps = report["custodyGaps"]
    assert gaps["closingWithoutCapture"] == []
    assert [g["dataPointId"] for g in gaps["closingAwaitingIndex"]] == ["treasury.mts"]


def test_a_second_pass_leaves_alone_what_the_index_already_shows() -> None:
    done = make_target("bls.a19", A19, "2026-09-16", "2026-09-24")
    early_only = make_target("fns.snap", SNAP, "2026-09-16", "2026-09-24")

    def index(url: str, query: dict[str, str]) -> bytes:
        if url == A19:
            return cdx_body(("20260920194501", "200"))
        return cdx_body(("20260920021500", "200"), url=SNAP)

    archive = FakeArchive(index=index)
    report = run([done, early_only], archive, skip_since=dt.time(19, 30))
    assert archive.saves == [SNAP]
    by_url = {e["sourceUrl"]: e for e in report["openWindows"]}
    assert by_url[A19]["save"]["requested"] is False
    assert "2026-09-20T19:45:01Z" in by_url[A19]["save"]["why"]


def test_a_second_pass_still_asks_when_the_index_cannot_be_read() -> None:
    target = make_target("bls.a19", A19, "2026-09-16", "2026-09-24")
    archive = FakeArchive(index=lambda url, query: b"<html>429</html>")
    run([target], archive, skip_since=dt.time(19, 30))
    assert archive.saves == [A19]


# ---------------------------------------------------------------------------
# The daily cap is loud


def test_the_daily_cap_keeps_the_windows_that_close_first_and_names_the_rest() -> None:
    targets = [
        make_target(
            f"t{i}", f"https://host{i}.example.gov/p", "2026-09-16", f"2026-09-2{i}"
        )
        for i in range(1, 6)
    ]
    archive = FakeArchive()
    report = run(targets, archive, max_urls=2)
    assert sorted(archive.saves) == [
        "https://host1.example.gov/p",
        "https://host2.example.gov/p",
    ]
    assert [d["sourceUrl"] for d in report["droppedByCap"]] == [
        f"https://host{i}.example.gov/p" for i in (3, 4, 5)
    ]
    assert witness.render_text(report).count("DROPPED BY DAILY CAP") == 3


def test_the_known_population_fits_under_the_default_cap() -> None:
    no_plan, _ = witness.plan_predicate(None)
    targets, _ = witness.scan_registrations(ROOT / "records" / "targets", no_plan, None)
    day = dt.date(2026, 9, 20)
    while day <= dt.date(2027, 3, 1):
        selection = witness.select(targets, None, day)
        assert selection.dropped_open == [], day
        day += dt.timedelta(days=1)


# ---------------------------------------------------------------------------
# Reading registrations


def write_registration(
    directory: pathlib.Path, name_hash: str, targets: list[dict[str, Any]]
) -> pathlib.Path:
    path = directory / f"2026-09-14-{name_hash}.json"
    path.write_text(
        json.dumps(
            {"schemaVersion": "thesis_target_registration_v3", "targets": targets}
        )
    )
    return path


def binding(adapter: str, url: str, window: dict[str, str] | None) -> dict[str, Any]:
    host = urllib.parse.urlsplit(url).hostname
    out: dict[str, Any] = {"adapter": adapter, "sourceUrl": url, "allowedHosts": [host]}
    if window is not None:
        out["expectedReleaseWindow"] = window
    return out


def test_scan_keeps_generic_url_targets_and_explains_what_it_skips(
    tmp_path: pathlib.Path,
) -> None:
    window = {"start": "2026-09-16", "end": "2026-09-24"}
    write_registration(
        tmp_path,
        "a" * 64,
        [
            {
                "dataPointId": "keep",
                "sourceBinding": binding("generic-url", A19, window),
            },
            {
                "dataPointId": "executable",
                "sourceBinding": binding("alfred-fred", A19, window),
            },
            {
                "dataPointId": "no_window",
                "sourceBinding": binding("generic-url", A19, None),
            },
            {
                "dataPointId": "archive_url",
                "sourceBinding": binding(
                    "generic-url",
                    "https://web.archive.org/web/2026/https://x.gov/",
                    window,
                ),
            },
            {
                "dataPointId": "ftp",
                "sourceBinding": binding(
                    "generic-url", "ftp://ftp.bls.gov/pub/x.txt", window
                ),
            },
        ],
    )
    (tmp_path / "README.md").write_text("not a registration")
    (tmp_path / f"2026-09-14-{'c' * 64}.json").write_text("{not json")
    no_plan, rule = witness.plan_predicate(None)
    targets, problems = witness.scan_registrations(tmp_path, no_plan, None)
    assert rule == 'sourceBinding.adapter == "generic-url"'
    assert [t.data_point_id for t in targets] == ["keep"]
    texts = " | ".join(p.text for p in problems)
    assert "no_window has no dated expectedReleaseWindow" in texts
    assert "already an Internet Archive URL" in texts
    assert "scheme 'ftp'" in texts
    assert "unreadable" in texts
    assert "executable" not in texts


def test_a_registration_whose_hash_does_not_match_its_name_is_not_witnessed(
    tmp_path: pathlib.Path,
) -> None:
    window = {"start": "2026-09-16", "end": "2026-09-24"}
    write_registration(
        tmp_path,
        "a" * 64,
        [
            {
                "dataPointId": "forged",
                "sourceBinding": binding("generic-url", A19, window),
            }
        ],
    )
    no_plan, _ = witness.plan_predicate(None)
    targets, problems = witness.scan_registrations(
        tmp_path, no_plan, lambda snap: "b" * 64
    )
    assert targets == []
    assert "content hash does not match its name" in problems[0].text
    assert problems[0].data_point_id is None


def test_every_committed_registration_authenticates_and_reads() -> None:
    content_hash, failure = witness._load_content_hash()
    assert failure is None
    no_plan, _ = witness.plan_predicate(None)
    targets, problems = witness.scan_registrations(
        ROOT / "records" / "targets", no_plan, content_hash
    )
    assert [p.text for p in problems if p.data_point_id is None] == []
    assert targets, "the generic-url population this witness exists for is gone"
    assert all(t.window_start <= t.window_end for t in targets)


def test_stale_target_problems_are_not_repeated_forever() -> None:
    problem = witness.Problem(
        "x: archive url", data_point_id="old", window_end=dt.date(2026, 7, 1)
    )
    assert problem.matters({"old"}, TODAY, 7) is False
    assert problem.matters({"old"}, dt.date(2026, 7, 5), 7) is True
    assert problem.matters(set(), dt.date(2026, 7, 5), 7) is False
    assert witness.Problem("file unreadable").matters(set(), TODAY, 7) is True


# ---------------------------------------------------------------------------
# The plan rule follows the executor gate once it exists


def test_the_executor_gate_replaces_the_adapter_name_rule_when_present() -> None:
    resolver = types.SimpleNamespace(
        execution_plan_refusal=lambda registration: (
            None
            if registration["contract"]["dataPointId"] == "executable"
            else "no resolver family routes it"
        )
    )
    no_plan, rule = witness.plan_predicate(resolver)
    assert rule == "resolve_pending.execution_plan_refusal"
    assert no_plan({"contract": {"dataPointId": "executable"}}) is None
    assert (
        no_plan({"contract": {"dataPointId": "stuck"}})
        == "no resolver family routes it"
    )


def test_a_gate_that_raises_witnesses_the_target_rather_than_dropping_it() -> None:
    def gate(registration: dict[str, Any]) -> str | None:
        raise KeyError("sourceBinding")

    no_plan, _ = witness.plan_predicate(
        types.SimpleNamespace(execution_plan_refusal=gate)
    )
    assert "witnessing anyway" in no_plan({"contract": {}})


def test_the_resolver_s_save_template_is_reused_once_it_exists() -> None:
    resolver = types.SimpleNamespace(
        WAYBACK_SAVE_URL="https://web.archive.org/save/{url}"
    )
    assert witness.save_url_template(resolver) == resolver.WAYBACK_SAVE_URL
    assert witness.save_url_template(None) == witness.WAYBACK_SAVE_URL
    assert witness.save_url_template(types.SimpleNamespace(WAYBACK_SAVE_URL=3)) == (
        witness.WAYBACK_SAVE_URL
    )


# ---------------------------------------------------------------------------
# Known limits are said, not hidden


def test_known_limits_name_the_api_payload_and_bot_wall_cases() -> None:
    assert any("payload, not a release" in n for n in witness.known_limits(STATCAN))
    assert any("HTTP 403" in n for n in witness.known_limits(A19))
    assert any("HTTP 520" in n for n in witness.known_limits(SSA))
    assert witness.known_limits("https://www.nbb.be/en/statistics/x") == []


def test_a_host_outside_the_registered_allowed_hosts_is_flagged() -> None:
    target = make_target("odd", A19, "2026-09-16", "2026-09-24", hosts=("api.bls.gov",))
    entry = run([target], FakeArchive())["openWindows"][0]
    assert any("outside the registered allowedHosts" in n for n in entry["knownLimits"])


# ---------------------------------------------------------------------------
# The command line


def cli(tmp_path: pathlib.Path, *argv: str, archive: Any = no_network) -> int:
    window = {"start": "2026-09-16", "end": "2026-09-24"}
    targets_dir = tmp_path / "targets"
    targets_dir.mkdir(exist_ok=True)
    write_registration(
        targets_dir,
        "a" * 64,
        [{"dataPointId": "keep", "sourceBinding": binding("generic-url", A19, window)}],
    )
    return witness.main(
        ["--targets-dir", str(targets_dir), *argv],
        fetch=archive,
        sleep=lambda seconds: None,
        log_loader=lambda: {
            "resolutionLinks": [{"status": "pending", "targetFactRef": "keep"}]
        },
    )


def test_cli_dry_run_is_offline_and_writes_the_report_and_summary(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        witness, "_load_content_hash", lambda: (None, "skipped in test")
    )
    report = tmp_path / "out" / "report.json"
    summary = tmp_path / "summary.md"
    code = cli(
        tmp_path,
        "--dry-run",
        "--date",
        "2026-09-20",
        "--report",
        str(report),
        "--summary",
        str(summary),
    )
    assert code == 0
    assert (
        f"WOULD REQUEST: https://web.archive.org/save/{A19}" in capsys.readouterr().out
    )
    written = json.loads(report.read_text())
    assert written["schemaVersion"] == witness.REPORT_SCHEMA
    assert written["mode"] == "dry-run"
    assert "would request" in summary.read_text()


def test_cli_capture_run_reports_a_capture(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        witness, "_load_content_hash", lambda: (None, "skipped in test")
    )
    today = dt.datetime.now(dt.timezone.utc).date()
    window = {
        "start": (today - dt.timedelta(days=1)).isoformat(),
        "end": (today + dt.timedelta(days=5)).isoformat(),
    }
    targets_dir = tmp_path / "targets"
    targets_dir.mkdir()
    write_registration(
        targets_dir,
        "a" * 64,
        [{"dataPointId": "keep", "sourceBinding": binding("generic-url", A19, window)}],
    )
    stamp = f"{today:%Y%m%d}194501"
    archive = FakeArchive(
        save=lambda original: saved(original, stamp),
        index=lambda url, query: cdx_body((stamp, "200")),
    )
    code = witness.main(
        ["--targets-dir", str(targets_dir)],
        fetch=archive,
        sleep=lambda seconds: None,
        log_loader=lambda: {
            "resolutionLinks": [{"status": "pending", "targetFactRef": "keep"}]
        },
    )
    assert code == 0
    assert archive.saves == [A19]
    assert "CAPTURED: the index lists an HTTP 200 capture" in capsys.readouterr().out


def test_cli_refuses_a_date_outside_a_dry_run(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit):
        cli(tmp_path, "--date", "2026-09-20")


@pytest.mark.parametrize("flag", ["--report", "--summary"])
def test_cli_refuses_to_write_under_records(tmp_path: pathlib.Path, flag: str) -> None:
    with pytest.raises(SystemExit, match="writes nothing under records"):
        cli(
            tmp_path,
            "--dry-run",
            flag,
            str(ROOT / "records" / "witness" / "report.json"),
        )
    assert not (ROOT / "records" / "witness").exists()


def test_cli_fails_only_when_it_could_not_look_at_all(tmp_path: pathlib.Path) -> None:
    code = witness.main(
        ["--dry-run", "--targets-dir", str(tmp_path / "missing")],
        fetch=no_network,
        log_loader=lambda: {"resolutionLinks": []},
    )
    assert code == 1


def test_the_witness_names_itself_to_the_archive() -> None:
    assert "thesis-witness/1.0" in witness.WITNESS_USER_AGENT
    assert "+https://app.thesisinstitute.org" in witness.WITNESS_USER_AGENT


def test_a_slow_archive_cannot_spend_the_time_the_index_reads_need() -> None:
    now = {"t": 0.0}
    seen: list[str] = []

    def fetch(url: str, timeout: float) -> witness.Response:
        seen.append(url)
        if "/save/" in url:
            now["t"] += timeout  # the Archive hangs for the whole timeout
            raise witness.FetchError("TimeoutError: timed out")
        return witness.Response(200, url, {}, cdx_body(("20260920194501", "200")))

    carrier = witness.Transport(
        fetch=fetch,
        sleep=lambda seconds: None,
        clock=lambda: now["t"],
        today=lambda: TODAY,
        attempts=1,
        deadline_seconds=1000.0,
    )
    targets = [
        make_target(
            f"t{i}", f"https://host{i}.example.gov/p", "2026-09-16", "2026-09-24"
        )
        for i in range(4)
    ]
    report = witness.run(
        targets=targets,
        pending={t.data_point_id for t in targets},
        today=TODAY,
        transport=carrier,
        options=witness.Options(save_timeout=400.0),
    )
    assert sum("/save/" in url for url in seen) == 2
    assert now["t"] == 750.0  # a quarter of the budget is left for the index
    assert all(e["index"]["ok"] for e in report["openWindows"])
    assert [e["verdict"]["code"] for e in report["openWindows"]] == ["CAPTURED"] * 4


# ---------------------------------------------------------------------------
# Regressions found by the first live run (2026-09-20)


def test_an_unread_index_never_prints_a_count_or_a_missing_capture() -> None:
    # The Archive answered HTTP 429 to everything. The first report printed
    # "0 HTTP 200 capture(s)" and "WINDOW CLOSED WITHOUT A CAPTURE" beside
    # "INDEX UNREAD": a failure to look, presented as a finding of absence.
    def fetch(url: str, timeout: float) -> witness.Response:
        raise witness.FetchError("HTTP 429: Too Many Requests", status=429)

    targets = [
        make_target("open", A19, "2026-09-16", "2026-09-21"),
        make_target("closed", SNAP, "2026-09-08", "2026-09-16"),
    ]
    report = run(targets, fetch)
    text = witness.render_text(report)
    markdown = witness.render_markdown(report)
    assert "INDEX_UNREAD" in text and "INDEX UNREAD" in text
    assert "WITHOUT A CAPTURE" not in text
    assert "capture(s) in window" not in text
    assert "CUSTODY GAP" not in text
    assert "| index unread |" in markdown
    for entry in report["openWindows"] + report["closedWindows"]:
        assert entry["index"]["ok"] is False
        for row in entry["registrations"]:
            assert "http200CapturesInWindow" not in row
    assert report["custodyGaps"] == {
        "closingWithoutCapture": [],
        "closingAwaitingIndex": [],
        "closedWithoutCapture": [],
    }


def test_a_rate_limited_endpoint_is_left_alone_for_the_rest_of_the_run() -> None:
    asked: list[str] = []

    def fetch(url: str, timeout: float) -> witness.Response:
        asked.append(url)
        if "/save/" in url:
            raise witness.FetchError("HTTP 429: Too Many Requests", status=429)
        return witness.Response(200, url, {}, b"[]")

    targets = [
        make_target(
            f"t{i}", f"https://host{i}.example.gov/p", "2026-09-16", "2026-09-24"
        )
        for i in range(6)
    ]
    report = run(targets, fetch)
    saves = [u for u in asked if "/save/" in u]
    assert len(saves) == witness.RATE_LIMIT_BREAKER
    # The index is a separate endpoint and is still read for every URL.
    assert len([u for u in asked if "/cdx/" in u]) == 6
    texts = [e["verdict"]["text"] for e in report["openWindows"]]
    # The first URL spends three attempts, the second trips the breaker on
    # its first, and neither it nor the four after it is asked again.
    assert sum("not asked: the Archive answered HTTP 429" in t for t in texts) == 5
    assert all(e["verdict"]["code"] == "SAVE_FAILED" for e in report["openWindows"])


def test_one_success_clears_a_rate_limit_streak() -> None:
    answers = iter([429, 429, 429, 200, 429, 429, 429, 200])

    def fetch(url: str, timeout: float) -> witness.Response:
        if next(answers) == 429:
            raise witness.FetchError("HTTP 429", status=429, retry_after=1.0)
        return witness.Response(200, url, {}, b"")

    carrier = transport(fetch, attempts=4)
    first, _ = carrier.get("https://web.archive.org/save/a", 10.0)
    second, outcome = carrier.get("https://web.archive.org/save/b", 10.0)
    assert first is not None and second is not None
    assert outcome["earlierFailures"] == ["HTTP 429 (x3)"]


def test_repeated_failures_are_reported_once_with_a_count() -> None:
    assert witness._collapse(["a", "a", "a", "b", "a"]) == ["a (x3)", "b", "a"]
    assert witness._collapse([]) == []
