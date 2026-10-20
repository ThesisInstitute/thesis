"""Arch checks and the catalog curation resolver append proposals carry.

Chronicle's required "Arch checks" fails an append that needs catalog
curation: a concept's first period strip in a new identifier shape, or a
moved identity anchor. The resolver never awaited it, so appends merged red
and held the ledger branch red until a curation pull request landed
(chronicle#361/#363 and #369/#371). These tests pin the replacement:

* the merge invariant: an append merges only when every required gate
  passed on the proposal head, and Arch checks is either required (policy
  "refuse") or awaited and reported (policy "land");
* the strip proof: the resolver records a first strip as reviewed only when
  the stripped segment is the dataPointId segment after the row's
  registered series and spells the row's own period;
* the anchor move: only fresh-UUID mints and same-UUID placeholder
  enrichments of the append's own identities, and undoing them gives the
  base digest back;
* the fixture writer reproduces Chronicle's layout;
* catalog_curation end to end against a fake Chronicle base, including the
  dry run that drops curation the base's audit does not accept.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import event as hypothesis_event
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending as rp  # noqa: E402

REPO = "PolicyEngine/chronicle"
ARCH = rp.ARCH_CHECKS_GATE


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _run(run_id: int, name: str, status: str, conclusion: str | None) -> dict:
    return {
        "id": run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
    }


def _install_runs(monkeypatch, runs_at) -> None:
    """Serve ``runs_at(clock_now)`` as one complete check-runs page."""

    def api(*args: str, **_kwargs) -> str:
        runs = runs_at()
        return json.dumps({"total_count": len(runs), "check_runs": runs})

    monkeypatch.setattr(rp, "_gh_api", api)


def _green_append_gates() -> list[dict]:
    return [
        _run(1, "Append gate", "completed", "success"),
        _run(2, "Trusted base append gate", "completed", "success"),
        _run(11, "Append gate", "completed", "skipped"),
    ]


# --- The merge invariant ------------------------------------------------------


def test_red_arch_checks_is_returned_not_raised_when_advisory(monkeypatch) -> None:
    clock = _FakeClock()
    _install_runs(
        monkeypatch,
        lambda: [*_green_append_gates(), _run(3, ARCH, "completed", "failure")],
    )
    verdicts = rp.await_append_gates(
        REPO, "c" * 40, 7, timeout_seconds=60, advisory=(ARCH,),
        clock=clock, sleep=clock.sleep,
    )
    assert verdicts == {
        ARCH: ("failed", f"{ARCH}: failure (https://github.com/{REPO}/actions/runs/3)")
    }
    assert clock.now == 0


def test_arch_checks_is_awaited_after_the_append_gates_pass(monkeypatch) -> None:
    clock = _FakeClock()

    def runs() -> list[dict]:
        done = clock.now >= 6 * 60
        return [
            *_green_append_gates(),
            _run(3, ARCH, "completed" if done else "in_progress",
                 "success" if done else None),
        ]

    _install_runs(monkeypatch, runs)
    verdicts = rp.await_append_gates(
        REPO, "c" * 40, 7, timeout_seconds=150 * 60, advisory=(ARCH,),
        clock=clock, sleep=clock.sleep,
    )
    assert verdicts[ARCH][0] == "passed"
    assert 6 * 60 <= clock.now < 6 * 60 + rp.APPEND_GATE_MAX_POLL_SECONDS


def test_a_missing_arch_verdict_stops_the_wait_after_the_grace(monkeypatch) -> None:
    """Under "land" an absent Arch checks never holds a merge longer than the
    grace, and is reported as pending, not as a pass."""
    clock = _FakeClock()
    _install_runs(monkeypatch, _green_append_gates)
    verdicts = rp.await_append_gates(
        REPO, "c" * 40, 7, timeout_seconds=150 * 60, advisory=(ARCH,),
        clock=clock, sleep=clock.sleep,
    )
    assert verdicts == {ARCH: ("pending", f"{ARCH}: no check run yet")}
    grace = rp.ARCH_CHECKS_GRACE_SECONDS
    assert grace <= clock.now < grace + rp.APPEND_GATE_MAX_POLL_SECONDS


def test_required_arch_checks_refuses_a_red_verdict(monkeypatch) -> None:
    clock = _FakeClock()
    _install_runs(
        monkeypatch,
        lambda: [*_green_append_gates(), _run(3, ARCH, "completed", "failure")],
    )
    with pytest.raises(
        rp.LedgerProposalError, match=r"append gate failed .*Arch checks: failure"
    ):
        rp.await_append_gates(
            REPO, "c" * 40, 7, timeout_seconds=60,
            gates=(*rp.REQUIRED_APPEND_GATES, ARCH),
            clock=clock, sleep=clock.sleep,
        )


def test_a_gate_cannot_be_both_required_and_advisory() -> None:
    with pytest.raises(rp.LedgerProposalError, match="both required and advisory"):
        rp.await_append_gates(
            REPO, "c" * 40, 7, timeout_seconds=60,
            gates=(ARCH,), advisory=(ARCH,),
        )


def test_a_failed_read_while_awaiting_arch_checks_never_refuses(monkeypatch) -> None:
    """Once a read showed every required gate passed, the old code merged on
    it; waiting on an advisory verdict must not turn later read failures
    into a closed proposal."""
    clock = _FakeClock()
    reads = 0

    def api(*_args: str, **_kwargs) -> str:
        nonlocal reads
        reads += 1
        if reads > 1:
            raise RuntimeError("HTTP 502")
        runs = [*_green_append_gates(), _run(3, ARCH, "queued", None)]
        return json.dumps({"total_count": len(runs), "check_runs": runs})

    monkeypatch.setattr(rp, "_gh_api", api)
    verdicts = rp.await_append_gates(
        REPO, "c" * 40, 7, timeout_seconds=150 * 60, advisory=(ARCH,),
        clock=clock, sleep=clock.sleep,
    )
    assert verdicts[ARCH][0] == "pending" and reads == 2


def _issue_api(calls: list, pages: list[list[dict]]):
    def api(*args: str, input_body=None, **_kwargs) -> str:
        calls.append((args, input_body))
        joined = " ".join(args)
        if "/issues?state=open" in joined:
            page = int(joined.rsplit("page=", 1)[1])
            return json.dumps(pages[page - 1] if page <= len(pages) else [])
        return json.dumps({"number": 99, "html_url": "https://x/99", "id": 1})

    return api


def test_a_missing_verdict_is_filed_when_the_dry_run_predicts_red(
    monkeypatch,
) -> None:
    calls: list = []
    monkeypatch.setattr(rp, "_gh_api", _issue_api(calls, [[]]))
    predicted = rp.CatalogCuration(files={}, residual=("'x' on 'y': first strip",))
    rp.report_arch_checks_at_merge(
        REPO, 7, "d" * 40, state="pending", runs="Arch checks: no check run yet",
        curation=predicted, run_url=None,
    )
    created = [body for args, body in calls if args[-1] == f"repos/{REPO}/issues"]
    assert len(created) == 1
    assert "dry run predicts it red" in created[0]["body"]
    assert "'x' on 'y': first strip" in created[0]["body"]
    calls.clear()
    rp.report_arch_checks_at_merge(
        REPO, 7, "d" * 40, state="pending", runs="Arch checks: queued",
        curation=rp.CatalogCuration(files={}), run_url=None,
    )
    assert calls == []


def test_the_open_curation_issue_is_found_past_the_first_page(monkeypatch) -> None:
    calls: list = []
    filler = [
        {"number": n, "title": f"pr {n}", "pull_request": {}} for n in range(100)
    ]
    match = {"number": 512, "title": rp.LEDGER_CURATION_ISSUE_TITLE}
    monkeypatch.setattr(rp, "_gh_api", _issue_api(calls, [filler, [match]]))
    rp._file_ledger_curation_issue(REPO, "body")
    posts = [args[-1] for args, _ in calls if "POST" in args]
    assert posts == [f"repos/{REPO}/issues/512/comments"]


_SHAPES = [
    ("queued", None),
    ("in_progress", None),
    ("completed", "success"),
    ("completed", "skipped"),
    ("completed", "neutral"),
    ("completed", "failure"),
    ("completed", "cancelled"),
    ("completed", "timed_out"),
]
_GATE_NAMES = ["Append gate", "Trusted base append gate", ARCH, "Arch bundle drift"]


@settings(max_examples=400, deadline=None)
@given(
    runs=st.lists(
        st.tuples(st.sampled_from(_GATE_NAMES), st.sampled_from(_SHAPES)),
        max_size=8,
    ),
    refuse=st.booleans(),
)
def test_merge_happens_only_when_every_required_gate_passed(
    monkeypatch_session, runs, refuse
) -> None:
    """For any check-run listing on the head, under either policy:

    I1 await_append_gates returns (the caller merges) only when
       append_gate_state is "passed" for every required gate;
    I2 it raises a rejection exactly when a required gate's state is
       "failed", and a no-verdict timeout otherwise;
    I3 when it returns, the advisory verdict it reports is the advisory
       gate's own state, never upgraded to a pass;
    I4 under "refuse" Arch checks is required, so a red or missing Arch
       checks never merges.
    """
    listing = [
        _run(index + 1, name, status, conclusion)
        for index, (name, (status, conclusion)) in enumerate(runs)
    ]
    _install_runs(monkeypatch_session, lambda: listing)
    required = (
        (*rp.REQUIRED_APPEND_GATES, ARCH) if refuse else rp.REQUIRED_APPEND_GATES
    )
    advisory = () if refuse else (ARCH,)

    def state(gate: str) -> str:
        return rp.append_gate_state([r for r in listing if r["name"] == gate])

    clock = _FakeClock()
    try:
        verdicts = rp.await_append_gates(
            REPO, "c" * 40, 7, timeout_seconds=60, poll_attempts=1,
            gates=required, advisory=advisory, clock=clock, sleep=clock.sleep,
        )
    except rp.LedgerProposalError as exc:
        assert any(state(gate) != "passed" for gate in required)
        rejected = any(state(gate) == "failed" for gate in required)
        assert ("append gate failed" in str(exc)) == rejected
        assert ("did not complete" in str(exc)) == (not rejected)
        return
    assert all(state(gate) == "passed" for gate in required)
    assert {gate: verdict[0] for gate, verdict in verdicts.items()} == {
        gate: state(gate) for gate in advisory
    }


_REQUIRED_NAMES = ("Append gate", "Trusted base append gate")


_PASSING_SHAPES = [
    ("completed", "success"),
    ("completed", "skipped"),
    ("completed", "neutral"),
]
_ARCH_SETS = [
    [("completed", "success"), ("completed", "success")],
    [("completed", "success"), ("completed", "skipped")],
    [("completed", "success")],
    [("completed", "success"), ("queued", None)],
    [("completed", "failure"), ("completed", "success")],
    [],
]


@st.composite
def _listing_pool(draw):
    """Three distinct check-run listings for one head; a listing's run ids
    are fixed by its variant, so reading the same variant twice reads the
    same runs. About half the variants pass every required gate (a success
    beside skipped or neutral twins), so waits do end in merges; Arch checks
    takes one of the shapes the "refuse" rule must tell apart; some
    listings are padded past one page with unrelated runs."""
    pool = []
    for _variant in range(3):
        passing = draw(st.booleans())
        runs = []
        for gate in _REQUIRED_NAMES:
            if passing:
                runs.append((gate, "completed", "success"))
                runs += [
                    (gate, *shape)
                    for shape in draw(st.lists(st.sampled_from(_PASSING_SHAPES),
                                               max_size=1))
                ]
            else:
                runs += [
                    (gate, *draw(st.sampled_from(_SHAPES)))
                    for _ in range(draw(st.integers(0, 2)))
                ]
        runs += [(ARCH, *shape) for shape in draw(st.sampled_from(_ARCH_SETS))]
        pad = draw(st.sampled_from([0, 0, rp.APPEND_GATE_CHECK_RUN_PAGE_SIZE + 20]))
        pool.append((runs, pad))
    return pool


def _listing_runs(pool, variant: int) -> list[dict]:
    runs, pad = pool[variant]
    listing = [
        _run(variant * 10_000 + index, name, status, conclusion)
        for index, (name, status, conclusion) in enumerate(runs)
    ]
    listing += [
        _run(variant * 10_000 + 5_000 + index, "Other check", "completed", "success")
        for index in range(pad)
    ]
    return listing


@settings(max_examples=400, deadline=None)
@given(
    pool=_listing_pool(),
    script=st.lists(
        st.one_of(st.integers(0, 2), st.just("error")), min_size=1, max_size=12
    ),
    refuse=st.booleans(),
)
def test_every_merge_rests_on_a_confirmed_pass_in_the_latest_run_of_reads(
    monkeypatch_session, pool, script, refuse
) -> None:
    """Over any sequence of listings and failed reads (including listings
    longer than a page, required gates re-run mid-wait and the advisory
    grace and budget running out): when await_append_gates returns, the
    latest successful read shows every required gate passed, and the
    unbroken run of passing reads it ends holds a confirmed pass (one page,
    or the same runs as the passing read before it). The advisory verdict
    returned is the advisory gate's state in that latest read."""
    size = rp.APPEND_GATE_CHECK_RUN_PAGE_SIZE
    reads: list = []

    def api(*args: str, **_kwargs) -> str:
        endpoint = args[0]
        page = int(endpoint.rsplit("page=", 1)[1])
        if page == 1:
            step = script[min(len(reads), len(script) - 1)]
            reads.append(step)
            if step == "error":
                raise RuntimeError("HTTP 502")
        listing = _listing_runs(pool, reads[-1])
        return json.dumps(
            {
                "total_count": len(listing),
                "check_runs": listing[(page - 1) * size : page * size],
            }
        )

    monkeypatch_session.setattr(rp, "_gh_api", api)
    required = (*_REQUIRED_NAMES, ARCH) if refuse else _REQUIRED_NAMES
    advisory = () if refuse else (ARCH,)
    min_runs = {ARCH: 2} if refuse else {}

    def state(listing: list[dict], gate: str) -> str:
        runs = [r for r in listing if r["name"] == gate]
        verdict = rp.append_gate_state(runs)
        real = [
            r for r in runs
            if r["status"] == "completed" and r["conclusion"] != "skipped"
        ]
        if verdict == "passed" and len(real) < min_runs.get(gate, 0):
            return "pending"
        return verdict

    def passed(variant: int) -> bool:
        listing = _listing_runs(pool, variant)
        return all(state(listing, gate) == "passed" for gate in required)

    clock = _FakeClock()
    try:
        verdicts = rp.await_append_gates(
            REPO, "c" * 40, 7, timeout_seconds=600, advisory=advisory,
            gates=required, advisory_grace_seconds=120, min_runs=min_runs,
            clock=clock, sleep=clock.sleep,
        )
    except rp.LedgerProposalError:
        hypothesis_event("refused")
        return
    hypothesis_event("merged")
    good = [read for read in reads if read != "error"]
    assert good and passed(good[-1])
    run_start = len(good) - 1
    while run_start > 0 and passed(good[run_start - 1]):
        run_start -= 1
    assert any(
        len(_listing_runs(pool, good[k])) <= size
        or (k > run_start and good[k - 1] == good[k])
        for k in range(run_start, len(good))
    ), (reads, script)
    latest = _listing_runs(pool, good[-1])
    assert {gate: verdict[0] for gate, verdict in verdicts.items()} == {
        gate: state(latest, gate) for gate in advisory
    }


def test_a_required_rerun_needs_a_fresh_confirmed_pass(monkeypatch) -> None:
    """A confirmed pass, then a required gate re-run (pending), then a pass
    on a listing longer than one page that no second read confirms: the
    earlier confirmation must not carry the merge past the re-run."""
    size = rp.APPEND_GATE_CHECK_RUN_PAGE_SIZE
    pad = [
        _run(9_000 + index, "Other check", "completed", "success")
        for index in range(size + 20)
    ]
    first = [*_green_append_gates(), _run(3, ARCH, "queued", None)]
    rerun = [
        _run(1, "Append gate", "in_progress", None),
        _run(2, "Trusted base append gate", "completed", "success"),
        _run(3, ARCH, "queued", None),
    ]
    reads = [first, rerun]
    served: list[int] = []

    def api(*args: str, **_kwargs) -> str:
        page = int(args[0].rsplit("page=", 1)[1])
        if page == 1:
            served.append(len(served))
        index = served[-1]
        if index < len(reads):
            listing = reads[index]
        else:
            # Every later read: passing again, multi-page, and each read
            # sees a new attempt id, so no two reads confirm each other.
            listing = [
                _run(100 + index, "Append gate", "completed", "success"),
                _run(2, "Trusted base append gate", "completed", "success"),
                _run(3, ARCH, "queued", None),
                *pad,
            ]
        return json.dumps({
            "total_count": len(listing),
            "check_runs": listing[(page - 1) * size: page * size],
        })

    monkeypatch.setattr(rp, "_gh_api", api)
    clock = _FakeClock()
    with pytest.raises(rp.LedgerProposalError, match="did not complete"):
        rp.await_append_gates(
            REPO, "c" * 40, 7, timeout_seconds=600, advisory=(ARCH,),
            advisory_grace_seconds=10_000, clock=clock, sleep=clock.sleep,
        )


def _scripted_reads(monkeypatch, listings) -> list[int]:
    """Serve ``listings(n)`` on the n-th read (pages included); returns the
    list of read numbers served, for assertions."""
    size = rp.APPEND_GATE_CHECK_RUN_PAGE_SIZE
    served: list[int] = []

    def api(*args: str, **_kwargs) -> str:
        page = int(args[0].rsplit("page=", 1)[1])
        if page == 1:
            served.append(len(served))
        listing = listings(served[-1])
        if listing is None:
            raise RuntimeError("HTTP 502")
        return json.dumps({
            "total_count": len(listing),
            "check_runs": listing[(page - 1) * size: page * size],
        })

    monkeypatch.setattr(rp, "_gh_api", api)
    return served


def _padded(runs: list[dict], base_id: int) -> list[dict]:
    return [*runs, *(
        _run(base_id + index, "Other check", "completed", "success")
        for index in range(rp.APPEND_GATE_CHECK_RUN_PAGE_SIZE + 20)
    )]


_ARCH_QUEUED = [_run(3, ARCH, "queued", None), _run(4, ARCH, "queued", None)]


def test_a_pass_never_confirms_across_a_broken_run(monkeypatch) -> None:
    """A multi-page pass, a read with a required gate not passed, then the
    same pass again: the two passes are not consecutive, so neither
    confirms the other (mutant: keeping passed_ids across the break)."""
    passing = _padded([*_green_append_gates(), *_ARCH_QUEUED], 9_000)
    broken = _padded([
        _run(1, "Append gate", "in_progress", None),
        _run(2, "Trusted base append gate", "completed", "success"),
        *_ARCH_QUEUED,
    ], 9_000)
    _scripted_reads(monkeypatch, lambda n: passing if n % 2 == 0 else broken)
    clock = _FakeClock()
    # No advisory grace: a (wrongly) confirmed pass would merge at once.
    with pytest.raises(rp.LedgerProposalError, match="did not complete"):
        rp.await_append_gates(
            REPO, "c" * 40, 7, timeout_seconds=600, advisory=(ARCH,),
            advisory_grace_seconds=0, min_runs={ARCH: 2},
            clock=clock, sleep=clock.sleep,
        )


def test_refuse_counts_a_skipped_twin_as_no_arch_checks_run(monkeypatch) -> None:
    """Under "refuse", one green Arch checks run beside a skipped twin is
    one run, not the two (push and pull request) the rule waits for."""
    runs = [
        *_green_append_gates(),
        _run(3, ARCH, "completed", "success"),
        _run(4, ARCH, "completed", "skipped"),
    ]
    _scripted_reads(monkeypatch, lambda _n: runs)
    clock = _FakeClock()
    with pytest.raises(rp.LedgerProposalError, match="did not complete"):
        rp.await_append_gates(
            REPO, "c" * 40, 7, timeout_seconds=600,
            gates=(*_REQUIRED_NAMES, ARCH), min_runs={ARCH: 2},
            clock=clock, sleep=clock.sleep,
        )


def test_land_merges_on_an_earlier_confirmation(monkeypatch) -> None:
    """Under "land", a confirmed pass followed by passing but unconfirmed
    reads (multi-page, new attempt ids) and then a failed read merges, as
    the code before advisory gates would have (round 3's P3-C)."""
    def listings(n: int):
        if n < 2:
            return _padded([*_green_append_gates(), *_ARCH_QUEUED], 9_000)
        if n % 3 == 2:
            return None
        return _padded([*_green_append_gates(), *_ARCH_QUEUED], 20_000 + n * 500)

    _scripted_reads(monkeypatch, listings)
    clock = _FakeClock()
    verdicts = rp.await_append_gates(
        REPO, "c" * 40, 7, timeout_seconds=600, advisory=(ARCH,),
        advisory_grace_seconds=10_000, min_runs={ARCH: 2},
        clock=clock, sleep=clock.sleep,
    )
    assert verdicts[ARCH][0] == "pending"


def test_a_required_rerun_restarts_the_advisory_grace(monkeypatch) -> None:
    """The advisory grace counts from the confirmed pass of the current run
    of passing reads, so a required re-run gives Arch checks a fresh grace
    (mutant: not resetting required_passed_at)."""
    passing = [*_green_append_gates(), *_ARCH_QUEUED]
    rerun = [
        _run(1, "Append gate", "in_progress", None),
        _run(2, "Trusted base append gate", "completed", "success"),
        *_ARCH_QUEUED,
    ]
    clock = _FakeClock()
    repassed_at: list[float] = []

    def listings(n: int):
        if n == 0:
            return passing
        if clock.now < 400:
            return rerun
        if not repassed_at:
            repassed_at.append(clock.now)
        return passing

    _scripted_reads(monkeypatch, listings)
    verdicts = rp.await_append_gates(
        REPO, "c" * 40, 7, timeout_seconds=150 * 60, advisory=(ARCH,),
        advisory_grace_seconds=300, min_runs={ARCH: 2},
        clock=clock, sleep=clock.sleep,
    )
    assert verdicts[ARCH][0] == "pending"
    assert clock.now >= repassed_at[0] + 300


@pytest.fixture(scope="module")
def monkeypatch_session():
    patch = pytest.MonkeyPatch()
    yield patch
    patch.undo()


# --- The strip proof ------------------------------------------------------------

SERIES = "usaspending.cdfi.assistance_transaction_obligations"
REF = f"{SERIES}.fy2026.registered_query_snapshot"
SHAPE = f"{SERIES}.{{P:fy9999}}.registered_query_snapshot"
KEY = (SERIES, "source_record_id", SHAPE, "fy2026")
CONTRACTS = {
    REF: {"contract": {"dataPointId": REF, "series": SERIES, "period": "FY2026"}}
}
GEO_US = {"level": "country", "id": "US", "vintage": "current"}
ECONOMY = {"name": "economy", "role": "aggregate"}
ROW = {
    "source_record_id": REF,
    "measure": {"concept": SERIES},
    "period": {"type": "fiscal_year", "value": "2026"},
    "geography": GEO_US,
    "entity": ECONOMY,
}
DERIVED = frozenset({"derived"})


def test_the_chronicle_369_first_strip_is_provable() -> None:
    additions, refusals = rp.provable_strip_reviews(
        {KEY: DERIVED}, {}, [], [ROW], CONTRACTS
    )
    assert additions == {KEY: ("derived",)} and refusals == {}


@pytest.mark.parametrize(
    "case, live, base_rows, appended, contracts, reason",
    [
        ("overlap", {KEY: frozenset({"overlap"})}, [], [ROW], CONTRACTS,
         "does not spell the row's declared period"),
        ("unregistered", {KEY: DERIVED}, [], [ROW], {}, "no registered contract"),
        ("other dataPointId",
         {KEY: DERIVED}, [], [ROW],
         {REF: {"contract": {"dataPointId": "x", "series": SERIES}}},
         "no registered contract"),
        ("slot not after the series", {KEY: DERIVED}, [], [ROW],
         {REF: {"contract": {"dataPointId": REF, "series": "usaspending.cdfi"}}},
         "not the segment after"),
        ("already in the ledger", {KEY: DERIVED}, [ROW], [ROW], CONTRACTS,
         "already in the ledger"),
        ("not this append's", {KEY: DERIVED}, [], [], CONTRACTS,
         "no row in this append"),
        ("two slots",
         {(SERIES, "source_record_id", "a.{P:fy9999}.{P:fy9999}", "fy2026"): DERIVED},
         [], [ROW], CONTRACTS, "exactly one period slot"),
    ],
)
def test_unprovable_first_strips_are_left_to_a_curator(
    case, live, base_rows, appended, contracts, reason
) -> None:
    additions, refusals = rp.provable_strip_reviews(
        live, {}, base_rows, appended, contracts
    )
    assert additions == {}, case
    assert len(refusals) == 1 and reason in next(iter(refusals.values())), case


def test_a_shape_is_recorded_only_when_every_first_spelling_is_provable() -> None:
    """Chronicle reviews a shape as one decision, so recording fy2026 would
    turn an unproven fy2025 of the same shape into a continuation."""
    sibling = (SERIES, "source_record_id", SHAPE, "fy2025")
    additions, refusals = rp.provable_strip_reviews(
        {KEY: DERIVED, sibling: DERIVED}, {}, [], [ROW], CONTRACTS
    )
    assert additions == {}
    assert "no row in this append" in refusals[sibling]
    assert "reviewed as one" in refusals[KEY]


def test_a_measure_concept_strip_must_be_the_datapointid_period_segment() -> None:
    """The measure.concept spelling must also be the dataPointId segment
    after the registered series (the 2026-10-19 review's P3-4)."""
    key = (SERIES, "measure.concept", f"{SERIES}.{{P:fy9999}}", "fy2026")
    good_row = {**ROW, "measure": {"concept": f"{SERIES}.fy2026"}}
    additions, _ = rp.provable_strip_reviews(
        {key: DERIVED}, {}, [], [good_row], CONTRACTS
    )
    assert additions == {key: ("derived",)}
    elsewhere = f"{SERIES}.annual.fy2026.first_print"
    bad_row = {
        **ROW, "source_record_id": elsewhere,
        "measure": {"concept": f"{SERIES}.fy2026"},
    }
    contracts = {
        elsewhere: {"contract": {"dataPointId": elsewhere, "series": SERIES}}
    }
    additions, refusals = rp.provable_strip_reviews(
        {key: DERIVED}, {}, [], [bad_row], contracts
    )
    assert additions == {} and "not the segment after" in refusals[key]


def test_continuations_of_a_reviewed_shape_need_no_review() -> None:
    reviewed = {(SERIES, "source_record_id", SHAPE, "fy2025"): DERIVED}
    additions, refusals = rp.provable_strip_reviews(
        {KEY: frozenset({"overlap"})}, reviewed, [], [ROW], {}
    )
    assert additions == {} and refusals == {}


_CONCEPTS = ["a.x", "b.y"]
_FIELDS = ["source_record_id", "measure.concept"]


@st.composite
def _strip_world(draw):
    keys = []
    for concept in _CONCEPTS:
        for field in _FIELDS:
            tail = draw(st.sampled_from([".first_print", "", ".{P:fy9999}"]))
            shape = f"{concept}.{{P:fy9999}}{tail}"
            for spelling in draw(
                st.lists(st.sampled_from(["fy2025", "fy2026"]), max_size=2, unique=True)
            ):
                keys.append((concept, field, shape, spelling))
    live = {
        key: frozenset(draw(st.sets(st.sampled_from(["derived", "overlap"]),
                                    min_size=1)))
        for key in keys
    }
    reviewed = {key: live[key] for key in keys if draw(st.booleans())}
    rows = []
    for key in keys:
        concept, field, shape, spelling = key
        filled = rp.strip_slot_fill(shape, spelling) or shape
        where = draw(st.sampled_from(["none", "base", "appended", "both"]))
        row = {"source_record_id": filled if field == "source_record_id" else
               f"{filled}.id", "measure": {"concept": filled}}
        rows.append((where, row))
    contracts = {}
    for _where, row in rows:
        ref = row["source_record_id"]
        series = draw(st.sampled_from([*_CONCEPTS, "a", None]))
        if series is not None:
            contracts[ref] = {"contract": {"dataPointId": ref, "series": series}}
    base_rows = [row for where, row in rows if where in ("base", "both")]
    appended = [row for where, row in rows if where in ("appended", "both")]
    return live, reviewed, base_rows, appended, contracts


@settings(max_examples=500, deadline=None)
@given(world=_strip_world())
def test_strip_reviews_are_exactly_the_provable_first_strips(world) -> None:
    """Partition: every first strip (outside ``reviewed``, in a shape with
    no reviewed strip) is either recorded or refused with a reason, and
    nothing else is touched. Soundness: everything recorded is derived
    alone, spelled by an appended row and no ledger row, and every row
    spelling it has a contract whose series the period slot follows."""
    live, reviewed, base_rows, appended, contracts = world
    additions, refusals = rp.provable_strip_reviews(
        live, reviewed, base_rows, appended, contracts
    )
    shapes = {key[:3] for key in reviewed}
    first = {key for key in live if key not in reviewed and key[:3] not in shapes}
    assert set(additions) | set(refusals) == first
    assert not set(additions) & set(refusals)
    # A shape is recorded whole or not at all.
    assert not {key[:3] for key in additions} & {key[:3] for key in refusals}
    for key in additions:
        concept, field, shape, spelling = key
        assert live[key] == DERIVED
        filled = rp.strip_slot_fill(shape, spelling)
        assert filled is not None

        def spells(row, filled=filled, field=field):
            value = (row["source_record_id"] if field == "source_record_id"
                     else row["measure"]["concept"])
            return value == filled

        carriers = [row for row in appended if spells(row)]
        assert carriers and not any(spells(row) for row in base_rows)
        for row in carriers:
            contract = contracts[row["source_record_id"]]["contract"]
            assert contract["dataPointId"] == row["source_record_id"]
            assert shape.startswith(contract["series"] + ".{P:")
            depth = len(contract["series"].split("."))
            assert row["source_record_id"].split(".")[depth] == spelling


# --- The anchor move -------------------------------------------------------------


def _geo_key(geography):
    g = geography or {}
    return json.dumps([g.get("level"), g.get("id"), g.get("vintage")])


def _entity_key(entity):
    e = entity or {}
    return json.dumps([e.get("name"), e.get("role")])


def _identity(uuid, concept, geography, entity) -> dict:
    return {
        "uuid": uuid,
        "concept": concept,
        "geography": geography,
        "entity": entity,
        "line": json.dumps([uuid, concept, _geo_key(geography), _entity_key(entity)]),
    }


def _undo(candidate: list[dict], events: list[dict]) -> set[str]:
    """Chronicle's identity_anchor_problems reconstruction, independently."""
    prior = {identity["line"] for identity in candidate}
    for event in events:
        prior.discard(
            _identity(event["uuid"], event["concept"], event["geography"],
                      event["entity"])["line"]
        )
        if event["event"] == "enrich":
            prior.add(
                _identity(event["uuid"], event["concept"],
                          event["placeholder_geography"], None)["line"]
            )
    return prior


def test_the_chronicle_369_anchor_move_is_five_enrichments() -> None:
    concepts = [
        "usaspending.cdfi.assistance_transaction_obligations",
        "usaspending.dhs.title_vi.award_transaction_obligations",
        "usaspending.dod.prime_award_obligations",
        "usaspending.ntia.broadband_al11038_obligations",
        "usaspending.usfs.minnesota_place_of_performance_obligations",
    ]
    placeholder = {"level": "country", "id": "US", "vintage": None}
    base = [_identity(f"u{i}", c, placeholder, None) for i, c in enumerate(concepts)]
    candidate = [
        _identity(f"u{i}", c, GEO_US, ECONOMY) for i, c in enumerate(concepts)
    ]
    ids = [f"{c}.fy2026.registered_query_snapshot" for c in concepts]
    events, reason = rp.identity_anchor_move(base, candidate, ids)
    assert reason is None
    assert [(e["event"], e["concept"]) for e in events] == [
        ("enrich", c) for c in concepts
    ]
    assert _undo(candidate, events) == {i["line"] for i in base}


_A_CONCEPTS = ["a.series", "b.series", "c.series"]
_FULL_GEOS = [
    {"level": "country", "id": "US", "vintage": "current"},
    {"level": "country", "id": "US", "vintage": None},
    {"level": "state", "id": "MN", "vintage": "current"},
]
_ENTITIES = [ECONOMY, {"name": "person", "role": "civilian_labor_force"}]


def _admitted(placeholder):
    return [
        g for g in _FULL_GEOS
        if placeholder is None
        or ((placeholder["level"], placeholder["id"]) == (g["level"], g["id"])
            and placeholder["vintage"] in (None, g["vintage"]))
    ]


@st.composite
def _sanctioned_append(draw):
    """A catalog, the catalog one sanctioned append makes of it, and the row
    ids that name the touched concepts. As in a real catalog, every
    (concept, geography, entity) is held once."""

    def key(concept, geography, entity) -> str:
        return json.dumps([concept, _geo_key(geography), _entity_key(entity)])

    base, held = [], set()
    for index in range(draw(st.integers(0, 6))):
        placeholder = draw(st.booleans())
        concept = draw(st.sampled_from(_A_CONCEPTS))
        geography = draw(st.sampled_from(
            [None, *_FULL_GEOS] if placeholder else _FULL_GEOS))
        entity = None if placeholder else draw(st.sampled_from(_ENTITIES))
        if key(concept, geography, entity) in held:
            continue
        held.add(key(concept, geography, entity))
        base.append(_identity(f"u{index:02d}", concept, geography, entity))
    candidate, touched = [], []
    for identity in base:
        options = [
            (geography, entity)
            for geography in _admitted(identity["geography"])
            for entity in _ENTITIES
            if key(identity["concept"], geography, entity) not in held
        ]
        if identity["entity"] is None and options and draw(st.booleans()):
            geography, entity = draw(st.sampled_from(options))
            held.discard(key(identity["concept"], identity["geography"], None))
            held.add(key(identity["concept"], geography, entity))
            candidate.append(
                _identity(identity["uuid"], identity["concept"], geography, entity)
            )
            touched.append(identity["concept"])
        else:
            candidate.append(identity)
    for index in range(draw(st.integers(0, 3))):
        concept = draw(st.sampled_from(_A_CONCEPTS))
        geography = draw(st.sampled_from(_FULL_GEOS))
        entity = draw(st.sampled_from(_ENTITIES))
        if key(concept, geography, entity) in held:
            continue
        held.add(key(concept, geography, entity))
        candidate.append(_identity(f"m{index:02d}", concept, geography, entity))
        touched.append(concept)
    ids = [f"{concept}.fy2026.first_print" for concept in touched]
    return base, candidate, ids


@settings(max_examples=400, deadline=None)
@given(append=_sanctioned_append())
def test_a_sanctioned_append_yields_events_that_undo_to_the_base(append) -> None:
    base, candidate, ids = append
    events, reason = rp.identity_anchor_move(base, candidate, ids)
    assert reason is None and events is not None
    assert events == sorted(events, key=lambda e: (e["concept"], e["uuid"]))
    assert _undo(candidate, events) == {identity["line"] for identity in base}
    for event in events:
        assert event["entity"] is not None and event["geography"] is not None


_MOVE_MUTATIONS = [
    "remint", "entity_change", "concept_change", "unadmitted_geography",
    "placeholder_mint", "drop", "foreign_concept", "duplicate_uuid_row",
    "mint_existing_identity", "registry_revive",
]


@pytest.mark.parametrize("mutation", _MOVE_MUTATIONS)
@settings(max_examples=150, deadline=None,
          suppress_health_check=[HealthCheck.filter_too_much])
@given(append=_sanctioned_append(), data=st.data())
def test_no_other_binding_change_yields_an_anchor_move(
    mutation, append, data
) -> None:
    """Each way an append could change a binding other than a fresh mint or
    its own placeholder's enrichment is refused, with a reason.
    Parametrized, so Hypothesis fails a mutation it can never exercise."""
    base, candidate, ids = append
    registry_uuids: set[str] = set()
    full = [i for i in base if i["entity"] is not None and i in candidate]
    placeholders = [i for i in base if i["entity"] is None]
    if mutation == "remint":
        assume(full)
        old = data.draw(st.sampled_from(full))
        candidate = [i for i in candidate if i is not old]
        candidate.append(_identity("fresh", old["concept"], old["geography"],
                                   old["entity"]))
        ids = [*ids, f"{old['concept']}.2026"]
    elif mutation == "entity_change":
        assume(full)
        old = data.draw(st.sampled_from(full))
        other = next(e for e in _ENTITIES if e != old["entity"])
        candidate = [i for i in candidate if i is not old]
        candidate.append(_identity(old["uuid"], old["concept"], old["geography"],
                                   other))
        ids = [*ids, f"{old['concept']}.2026"]
    elif mutation == "concept_change":
        assume(placeholders)
        old = data.draw(st.sampled_from(placeholders))
        candidate = [i for i in candidate if i["uuid"] != old["uuid"]]
        candidate.append(_identity(old["uuid"], "z.renamed", _FULL_GEOS[0],
                                   ECONOMY))
        ids = [*ids, "z.renamed.2026"]
    elif mutation == "unadmitted_geography":
        assume(placeholders)
        old = data.draw(st.sampled_from(placeholders))
        assume(old["geography"] is not None)
        bad = [g for g in _FULL_GEOS if g not in _admitted(old["geography"])]
        candidate = [i for i in candidate if i["uuid"] != old["uuid"]]
        candidate.append(_identity(old["uuid"], old["concept"],
                                   data.draw(st.sampled_from(bad)), ECONOMY))
        ids = [*ids, f"{old['concept']}.2026"]
    elif mutation == "placeholder_mint":
        candidate = [*candidate, _identity("fresh", "a.series", None, None)]
        ids = [*ids, "a.series.2026"]
    elif mutation == "drop":
        assume(base)
        old = data.draw(st.sampled_from(base))
        candidate = [i for i in candidate if i["uuid"] != old["uuid"]]
    elif mutation == "foreign_concept":
        candidate = [*candidate, _identity("fresh", "q.other", _FULL_GEOS[0],
                                           ECONOMY)]
    elif mutation == "duplicate_uuid_row":
        assume(base)
        old = data.draw(st.sampled_from(base))
        assume(any(i["line"] == old["line"] for i in candidate))
        candidate = [*candidate, _identity(old["uuid"], "b.series", _FULL_GEOS[0],
                                           ECONOMY)]
        ids = [*ids, "b.series.2026"]
    elif mutation == "mint_existing_identity":
        # The same (concept, geography, entity) under a second, fresh UUID.
        assume(full)
        old = data.draw(st.sampled_from(full))
        candidate = [*candidate, _identity("fresh", old["concept"],
                                           old["geography"], old["entity"])]
        ids = [*ids, f"{old['concept']}.2026"]
    elif mutation == "registry_revive":
        # A mint of a UUID the base registry holds (a retired binding).
        candidate = [*candidate, _identity("retired", "a.series", _FULL_GEOS[0],
                                           ECONOMY)]
        ids = [*ids, "a.series.2026"]
        registry_uuids = {"retired"}
    events, reason = rp.identity_anchor_move(base, candidate, ids, registry_uuids)
    assert events is None and reason, mutation


# --- The fixture writer ----------------------------------------------------------

_text = st.text(
    alphabet=st.characters(codec="ascii", exclude_categories=("Cs",)), max_size=8
)
_fixture_values = st.recursive(
    st.one_of(_text, st.lists(_text, max_size=3), st.none(), st.integers()),
    lambda inner: st.dictionaries(_text, inner, max_size=3),
    max_leaves=12,
)


def _stdlib_layout(value) -> str:
    # The layout Chronicle's fixture was verified against on 2026-10-19:
    # json.dumps(indent=2) with every list of scalars pulled onto one line.
    text = json.dumps(value, indent=2, ensure_ascii=False)

    def inline(match: re.Match) -> str:
        items = [line.strip().rstrip(",") for line in match.group(1).splitlines()]
        return "[" + ", ".join(item for item in items if item) + "]"

    return re.sub(r"\[\n((?:\s*(?:\"(?:[^\"\\]|\\.)*\"|-?\d+|null),?\n)+)\s*\]",
                  inline, text) + "\n"


@settings(max_examples=400, deadline=None)
@given(value=st.dictionaries(_text, _fixture_values, max_size=4))
def test_the_fixture_writer_round_trips_and_matches_the_reference_layout(
    value,
) -> None:
    rendered = rp.render_catalog_fixture(value)
    assert json.loads(rendered) == value
    assert rp.render_catalog_fixture(json.loads(rendered)) == rendered
    assert rendered.decode() == _stdlib_layout(value)


# An excerpt of tests/fixtures/series_catalog/reviewed_stripped_segments.json at
# chronicle 53ffa243 (2026-10-19): two of its strip entries verbatim, its
# comment and notes shortened, in the file's own layout.
_REAL_FIXTURE_EXCERPT = b"""{
  "comment": "Period strips a curator has reviewed.",
  "reviewed_catalog_commit": "55bbf3d",
  "notes": {
    "2026_08": "Reviewed 2026-10-12.",
    "fy2026": "Reviewed 2026-10-18."
  },
  "strips": {
    "usaspending.dod.new_prime_awards": {
      "source_record_id": {
        "usaspending.dod.new_prime_awards.{P:fy9999}.registered_query_snapshot": {
          "fy2026": ["derived"]
        }
      }
    },
    "va.vba.mmwr.claims_inventory": {
      "measure.concept": {
        "va.vba.mmwr.claims_inventory.{P:week_9999-99-99}": {
          "week_2026-07-13": ["overlap"]
        }
      }
    }
  }
}
"""


def test_the_writer_reproduces_chronicle_s_fixture_byte_for_byte() -> None:
    assert rp.render_catalog_fixture(json.loads(_REAL_FIXTURE_EXCERPT)) == (
        _REAL_FIXTURE_EXCERPT
    )


def test_curated_strips_keep_every_decision_and_note_and_stay_sorted() -> None:
    fixture = json.loads(_REAL_FIXTURE_EXCERPT)
    curated = rp.curated_strips_fixture(
        fixture, {KEY: ("derived",)}, "Recorded for {concepts} ({spelling})."
    )
    strips = curated["strips"]
    assert strips[SERIES]["source_record_id"][SHAPE] == {"fy2026": ["derived"]}
    for concept, by_field in fixture["strips"].items():
        assert strips[concept] == by_field
    assert list(strips) == sorted(strips)
    assert curated["notes"]["fy2026"] == (
        f"Reviewed 2026-10-18. Recorded for {SERIES} (fy2026)."
    )
    assert curated["notes"]["2026_08"] == fixture["notes"]["2026_08"]
    assert curated["comment"] == fixture["comment"]
    rendered = rp.render_catalog_fixture(curated).decode()
    assert rendered.count('"fy2026": ["derived"]') == 2
    # The input fixture is not modified in place.
    assert SERIES not in fixture["strips"]


def test_workflow_run_url_only_names_a_github_actions_run() -> None:
    env = {"GITHUB_SERVER_URL": "https://github.com",
           "GITHUB_REPOSITORY": "ThesisInstitute/thesis", "GITHUB_RUN_ID": "42"}
    assert rp._workflow_run_url(env) == (
        "https://github.com/ThesisInstitute/thesis/actions/runs/42"
    )
    assert rp._workflow_run_url({**env, "GITHUB_RUN_ID": "x"}) is None
    assert rp._workflow_run_url({**env, "GITHUB_SERVER_URL": "http://e"}) is None
    assert rp._workflow_run_url({}) is None


# --- catalog_curation end to end, against a fake Chronicle base ----------------

# A stand-in for Chronicle's scripts/build_series_catalog.py with the surface
# the resolver's probe uses. Its period strips are fyNNNN segments of
# source_record_id, and like the real generator it mints a new identity under
# a random UUID. A REJECT_CURATION file makes its audit report every strip,
# reviewed or not; a CLEAR_UNRELATED file makes it report nothing once any
# strip is reviewed. It refuses to run when it can read the resolver's
# credentials in its environment.
_FAKE_CATALOG_MODULE = r'''
import hashlib
import json
import os
import pathlib
import re
import sys
import uuid as uuid_module

if "GH_TOKEN" in os.environ or "LEDGER_PRODUCER_SIGNING_KEY" in os.environ:
    sys.exit(9)

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG = ROOT / "ledger" / "series_catalog.json"
OBSERVATIONS = ROOT / "ledger" / "official_observations.jsonl"
DOCKET_SEED = ROOT / "ledger" / "seeds" / "thesis_docket_series.json"
UUID_REGISTRY = ROOT / "ledger" / "series_uuid_registry.jsonl"
IDENTIFIER_FIELDS = ("measure.concept", "source_record_id")
IDENTITY_ANCHOR_MOVERS = ("thesis-resolver",)


def _geo_key(g):
    g = g or {}
    return json.dumps([g.get("level"), g.get("id"), g.get("vintage")])


def _entity_key(e):
    e = e or {}
    return json.dumps([e.get("name"), e.get("role")])


class ExistingCatalog:
    def __init__(self, path):
        self.path = path


class UuidRegistry:
    @staticmethod
    def load(path):
        return None


def build_catalog(observations, docket, existing, registry, *rest):
    committed = json.loads(CATALOG.read_text())
    series = {row["concept"]: dict(row) for row in committed["series"]}
    strips, stripped = {}, {}
    for line in OBSERVATIONS.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        concept = row["measure"]["concept"]
        segments = row["source_record_id"].split(".")
        hits = [i for i, s in enumerate(segments) if re.fullmatch(r"fy\d{4}", s)]
        if len(hits) == 1:
            spelling = segments[hits[0]]
            segments[hits[0]] = "{P:fy9999}"
            shape = ".".join(segments)
            strips.setdefault(concept, {}).setdefault("source_record_id", {})
            strips[concept]["source_record_id"].setdefault(shape, {})[spelling] = [
                "derived"
            ]
            stripped.setdefault(spelling, set()).add(concept)
        known = series.get(concept)
        uuid = known["uuid"] if known else str(uuid_module.uuid4())
        series[concept] = {"uuid": uuid, "concept": concept,
                           "geography": row["geography"], "entity": row["entity"]}
    catalog = {
        "series": [series[c] for c in sorted(series)],
        "stripped_segments": {s: sorted(c) for s, c in sorted(stripped.items())},
    }
    return catalog, {"strips": strips}


def strip_records(strips):
    return {
        (c, f, s, sp): set(k)
        for c, by_f in strips.items()
        for f, by_s in by_f.items()
        for s, by_sp in by_s.items()
        for sp, k in by_sp.items()
    }


def stripped_segment_review_problems(stripped_segments, strips, reviewed):
    live, decided = strip_records(strips), strip_records(reviewed)
    shapes = {key[:3] for key in decided}
    reject = (ROOT / "REJECT_CURATION").exists()
    if decided and (ROOT / "CLEAR_UNRELATED").exists():
        return []
    problems = []
    for concept, field, shape, spelling in live:
        if not reject and ((concept, field, shape, spelling) in decided
                           or (concept, field, shape) in shapes):
            continue
        problems.append(f"{spelling!r} on {concept!r}: first strip in {field} "
                        f"shape {shape!r} for this concept")
    return sorted(problems)


def identity_anchor_lines(series):
    return sorted(json.dumps([r["uuid"], r["concept"], _geo_key(r.get("geography")),
                              _entity_key(r.get("entity"))]) for r in series)


def identity_anchor_digest(lines):
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


def identity_anchor_problems(series, anchor):
    digest = identity_anchor_digest(identity_anchor_lines(series))
    if (ROOT / "REJECT_ANCHOR").exists() and anchor.get("move"):
        return ["identity anchor move: rejected by the fake audit"]
    if digest == anchor["sha256"]:
        return []
    return [f"identity anchor moved: {digest} != {anchor['sha256']}"]


if __name__ == "__main__":
    catalog, _plan = build_catalog(None, None, None, None)
    CATALOG.write_text(json.dumps(catalog, indent=2) + "\n")
'''

_LEDGER = "ledger/official_observations.jsonl"
_BASE_ROW = {
    "source_record_id": "other.series.level",
    "measure": {"concept": "other.series"},
    "geography": GEO_US,
    "entity": ECONOMY,
}
_PLACEHOLDER = {
    "uuid": "placeholder-uuid",
    "concept": SERIES,
    "geography": {"level": "country", "id": "US", "vintage": None},
    "entity": None,
}


def _anchor_digest(series: list[dict]) -> str:
    lines = sorted(
        json.dumps([r["uuid"], r["concept"], _geo_key(r["geography"]),
                    _entity_key(r["entity"])])
        for r in series
    )
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _fake_base(
    *,
    module: str = _FAKE_CATALOG_MODULE,
    reviewed_bytes: bytes | None = None,
    anchor_pin: str | None = None,
    fixtures: bool = True,
    extra: dict[str, bytes] | None = None,
    base_rows: tuple[dict, ...] = (_BASE_ROW,),
) -> rp.RepositoryTree:
    base_series = [
        {"uuid": hashlib.sha256(b"other.series").hexdigest()[:12],
         "concept": "other.series", "geography": GEO_US, "entity": ECONOMY},
        _PLACEHOLDER,
    ]
    files = {
        _LEDGER: "".join(json.dumps(row) + "\n" for row in base_rows).encode(),
        "ledger/series_catalog.json": json.dumps(
            {"series": sorted(base_series, key=lambda r: r["concept"]),
             "stripped_segments": {}}
        ).encode(),
        "scripts/build_series_catalog.py": module.encode(),
    }
    if fixtures:
        files[rp.CATALOG_REVIEWED_STRIPS] = reviewed_bytes or rp.render_catalog_fixture(
            {"comment": "c", "reviewed_catalog_commit": "x", "notes": {},
             "strips": {}}
        )
        files[rp.CATALOG_IDENTITY_ANCHOR] = rp.render_catalog_fixture(
            {"comment": "anchor comment",
             "sha256": anchor_pin or _anchor_digest(base_series), "move": None}
        )
    files.update(extra or {})
    return rp.RepositoryTree(
        tree_sha="1" * 40,
        files=files,
        modes={relative: "100644" for relative in files},
        blob_shas={relative: "a" * 40 for relative in files},
    )


def _regenerated(tree: rp.RepositoryTree, candidate: bytes) -> bytes:
    """The catalog the (fake) base generator writes for ``candidate``, as
    _prepare_release_files would ship it."""
    with tempfile.TemporaryDirectory() as name:
        stage = pathlib.Path(name)
        rp._materialize_repository_tree(stage, tree)
        (stage / _LEDGER).write_bytes(candidate)
        subprocess.run(
            [sys.executable, "scripts/build_series_catalog.py"],
            cwd=stage,
            check=True,
            env=rp._staged_subprocess_env(),
        )
        return (stage / "ledger" / "series_catalog.json").read_bytes()


def _candidate(tree: rp.RepositoryTree, *rows: dict) -> bytes:
    return tree.files[_LEDGER] + "".join(json.dumps(r) + "\n" for r in rows).encode()


def _curate(tree: rp.RepositoryTree, contracts=CONTRACTS, row=ROW, catalog=None):
    candidate = _candidate(tree, row)
    return rp.catalog_curation(
        tree,
        path=_LEDGER,
        candidate_ledger=candidate,
        catalog=catalog if catalog is not None else _regenerated(tree, candidate),
        registry=None,
        target_contracts=contracts,
        run_url="https://github.com/ThesisInstitute/thesis/actions/runs/9",
    )


def test_catalog_curation_carries_both_fixtures_and_the_dry_run_is_green() -> None:
    curation = _curate(_fake_base())
    assert curation.strips == (KEY,)
    assert [(e["event"], e["uuid"]) for e in curation.anchor_events] == [
        ("enrich", "placeholder-uuid")
    ]
    assert curation.residual == () and curation.notes == ()
    strips = json.loads(curation.files[rp.CATALOG_REVIEWED_STRIPS])
    assert strips["strips"][SERIES]["source_record_id"][SHAPE] == {
        "fy2026": ["derived"]
    }
    assert "actions/runs/9" in strips["notes"]["fy2026"]
    anchor = json.loads(curation.files[rp.CATALOG_IDENTITY_ANCHOR])
    assert anchor["comment"] == "anchor comment"
    assert anchor["move"]["by"] == rp.IDENTITY_ANCHOR_MOVER
    assert anchor["move"]["from_sha256"] != anchor["sha256"]


def test_the_dry_run_drops_only_the_part_it_rejects() -> None:
    """Strips and anchor are judged apart (the 2026-10-19 review's P3-5): a
    rejected strip record keeps a sound anchor move, and the reverse."""
    curation = _curate(_fake_base(extra={"REJECT_CURATION": b""}))
    assert rp.CATALOG_REVIEWED_STRIPS not in curation.files
    assert rp.CATALOG_IDENTITY_ANCHOR in curation.files
    assert curation.strips == () and curation.anchor_events
    assert any("rejected the recorded strips" in n for n in curation.notes)
    assert any("first strip" in line for line in curation.residual)
    curation = _curate(_fake_base(extra={"REJECT_ANCHOR": b""}))
    assert rp.CATALOG_REVIEWED_STRIPS in curation.files
    assert rp.CATALOG_IDENTITY_ANCHOR not in curation.files
    assert curation.strips == (KEY,) and curation.anchor_events == ()
    assert any("rejected the anchor move" in n for n in curation.notes)
    assert sum("identity anchor moved" in line for line in curation.residual) == 1


def test_catalog_curation_leaves_unprovable_strips_to_a_curator() -> None:
    curation = _curate(_fake_base(), contracts={})
    assert curation.strips == ()
    assert rp.CATALOG_REVIEWED_STRIPS not in curation.files
    # The enrichment is provable without the registration, so it ships.
    assert rp.CATALOG_IDENTITY_ANCHOR in curation.files
    assert any("no registered contract" in note for note in curation.notes)
    assert curation.residual == (
        f"'fy2026' on '{SERIES}': first strip in source_record_id shape "
        f"'{SHAPE}' for this concept",
    )


def test_catalog_curation_never_moves_an_already_stale_anchor() -> None:
    curation = _curate(_fake_base(anchor_pin="0" * 64))
    assert rp.CATALOG_IDENTITY_ANCHOR not in curation.files
    assert any("already stale" in note for note in curation.notes)
    assert sum("identity anchor moved" in line for line in curation.residual) == 1


def test_catalog_curation_without_curation_fixtures_does_nothing() -> None:
    # Not even the probe runs (this module would fail).
    tree = _fake_base(module="raise SystemExit(5)\n", fixtures=False)
    assert _curate(tree, catalog=b"{}") == rp.CatalogCuration(files={})
    # Nor without a shipped catalog (a base before the witnessed release chain).
    tree = _fake_base(module="raise SystemExit(5)\n")
    curation = rp.catalog_curation(
        tree, path=_LEDGER, candidate_ledger=_candidate(tree, ROW), catalog=None,
        registry=None, target_contracts=CONTRACTS,
    )
    assert curation == rp.CatalogCuration(files={})


def test_catalog_curation_survives_a_probe_that_cannot_run() -> None:
    module = _FAKE_CATALOG_MODULE + (
        "\nif __name__ != '__main__':\n    raise RuntimeError('probe boom')\n"
    )
    curation = _curate(_fake_base(module=module))
    assert curation.files == {}
    assert any("catalog probe exit" in note for note in curation.notes)


def test_catalog_curation_only_writes_a_fixture_in_chronicle_s_layout() -> None:
    odd = json.dumps({"comment": "c", "reviewed_catalog_commit": "x", "notes": {},
                      "strips": {}}, indent=4).encode()
    curation = _curate(_fake_base(reviewed_bytes=odd))
    assert rp.CATALOG_REVIEWED_STRIPS not in curation.files
    assert any("not in the layout" in note for note in curation.notes)


def test_staged_code_is_not_handed_the_resolver_s_credentials(monkeypatch) -> None:
    # The fake module exits 9 when its environment holds GH_TOKEN or the
    # producer key. (Hygiene: the staged base code runs as the same user.)
    tree = _fake_base()
    catalog = _regenerated(tree, _candidate(tree, ROW))
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv(rp.PRODUCER_SIGNING_KEY_ENV, "key")
    assert _curate(tree, catalog=catalog).strips == (KEY,)


NEW_SERIES = "usaspending.new.series_obligations"
NEW_REF = f"{NEW_SERIES}.fy2026.registered_query_snapshot"
NEW_ROW = {**ROW, "source_record_id": NEW_REF, "measure": {"concept": NEW_SERIES}}
NEW_CONTRACTS = {
    NEW_REF: {"contract": {"dataPointId": NEW_REF, "series": NEW_SERIES}}
}


def test_a_fresh_mint_keeps_its_curation_because_the_shipped_catalog_is_used(
) -> None:
    """Chronicle mints a new identity under a random UUID, so two generator
    runs describe two catalogs. Curation must come from the bytes that ship
    (the 2026-10-19 review's P2: a second run dropped it every time)."""
    tree = _fake_base()
    candidate = _candidate(tree, NEW_ROW)
    first, second = _regenerated(tree, candidate), _regenerated(tree, candidate)
    assert first != second
    curation = _curate(tree, contracts=NEW_CONTRACTS, row=NEW_ROW, catalog=first)
    shipped = {
        row["concept"]: row["uuid"] for row in json.loads(first)["series"]
    }
    assert [(e["event"], e["uuid"]) for e in curation.anchor_events] == [
        ("mint", shipped[NEW_SERIES])
    ]
    anchor = json.loads(curation.files[rp.CATALOG_IDENTITY_ANCHOR])
    assert anchor["sha256"] == _anchor_digest(json.loads(first)["series"])
    assert curation.strips == (
        (NEW_SERIES, "source_record_id",
         f"{NEW_SERIES}.{{P:fy9999}}.registered_query_snapshot", "fy2026"),
    )
    assert curation.residual == ()


def test_curation_may_not_clear_a_report_it_did_not_answer() -> None:
    """A base strip left to a curator must still be reported after the
    resolver records its own; an audit that stops reporting it means the
    curation reached beyond what was proven, so none ships."""
    unrelated = {
        "source_record_id": "other.flow.fy2025.first_print",
        "measure": {"concept": "other.flow"},
        "geography": GEO_US,
        "entity": ECONOMY,
    }
    tree = _fake_base(
        base_rows=(_BASE_ROW, unrelated), extra={"CLEAR_UNRELATED": b""}
    )
    curation = _curate(tree)
    assert curation.files == {}
    assert any("dry run rejected" in note for note in curation.notes)
    assert any("'fy2025' on 'other.flow'" in line for line in curation.residual)


def test_a_proposal_ships_curation_derived_from_its_own_catalog(monkeypatch) -> None:
    """End to end through propose_ledger_append: the fixtures in the
    proposal commit describe exactly the catalog that commit ships, even
    when the append mints an identity under a random UUID."""
    tree = _fake_base()
    candidate = _candidate(tree, NEW_ROW)

    def prepare(*_args, **_kwargs) -> dict[str, bytes]:
        return {"ledger/series_catalog.json": _regenerated(tree, candidate)}

    published: list[dict[str, bytes]] = []

    def publish(*_args, changes, **_kwargs) -> str:
        published.append(dict(changes))
        return "c" * 40

    merged = False

    def api(*args: str, input_body=None, **_kwargs) -> str:
        nonlocal merged
        joined = " ".join(args)
        if "/check-runs" in joined:
            runs = [*_green_append_gates(), _run(3, ARCH, "completed", "success")]
            return json.dumps({"total_count": len(runs), "check_runs": runs})
        if joined.endswith("/pulls") and "POST" in args:
            return json.dumps({"number": 7})
        if "/merge" in joined:
            merged = True
            return json.dumps({"merged": True, "sha": "d" * 40})
        if joined.endswith("/pulls/7"):
            return json.dumps({
                "merged": merged, "merge_commit_sha": "d" * 40 if merged else None,
                "head": {"sha": "c" * 40},
                "base": {"ref": "codex/thesis-ledger-facts", "sha": "b" * 40},
            })
        return "{}"

    monkeypatch.setattr(rp, "_fetch_repository_tree", lambda *_: tree)
    monkeypatch.setattr(rp, "_prepare_release_files", prepare)
    monkeypatch.setattr(rp, "_publish_proposal_commit", publish)
    monkeypatch.setattr(rp, "_branch_head", lambda *_: "b" * 40)
    monkeypatch.setattr(rp, "_verify_remote_proposal_state", lambda *_a, **_k: None)
    monkeypatch.setattr(rp, "_gh_api", api)
    merged_sha = rp.propose_ledger_append(
        REPO, "codex/thesis-ledger-facts", _LEDGER, candidate.decode(),
        "a" * 40, "b" * 40, 1, poll_seconds=0, poll_attempts=1,
        target_contracts=NEW_CONTRACTS,
    )
    assert merged_sha == "d" * 40
    (changes,) = published
    catalog = json.loads(changes["ledger/series_catalog.json"])
    anchor = json.loads(changes[rp.CATALOG_IDENTITY_ANCHOR])
    assert anchor["sha256"] == _anchor_digest(catalog["series"])
    (event,) = anchor["move"]["events"]
    assert event["event"] == "mint"
    assert event["uuid"] == next(
        row["uuid"] for row in catalog["series"] if row["concept"] == NEW_SERIES
    )
    assert NEW_SERIES in json.loads(changes[rp.CATALOG_REVIEWED_STRIPS])["strips"]
