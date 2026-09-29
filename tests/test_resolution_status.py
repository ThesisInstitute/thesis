"""`scripts/resolution_status.py` restates, per overdue target, what the
resolver said about it. The fixtures are the resolver's real stdout from two
scheduled runs: 2026-09-18 (Actions run 35372945335), which resolved five
cells and then died on an unpinned DigiCert responder, and 2026-09-27
(Actions run 36338749942), which printed the A-19 archive verdicts that put
the reference after a message with colons of its own, then died when
Chronicle's append gate refused the same responder.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import pathlib
import random
import re
import sys

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolution_status as rs  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "resolution_status"
REAL_LOG = (FIXTURES / "resolver-run-35372945335.log").read_text()
GATE_LOG = (FIXTURES / "resolver-run-36338749942.log").read_text()
AS_OF = dt.date(2026, 9, 19)


def _log(*targets: tuple[str, str, str]) -> dict:
    """A Thesis log with one pending link per (ref, slug, resolutionDate)."""
    return {
        "entries": [
            {"kind": "prediction_recorded", "forecastSlug": slug, "resolutionDate": due}
            for _ref, slug, due in targets
        ],
        "resolutionLinks": [
            {"status": "pending", "targetFactRef": ref, "forecastSlug": slug}
            for ref, slug, _due in targets
        ],
    }


def _status(log, text=REAL_LOG, *, claimed=(), registrations=None, as_of=AS_OF):
    resolver_targets, run = rs.parse_resolver_log(text)
    return rs.build_status(
        log,
        resolver_targets,
        run,
        claimed_refs=set(claimed),
        registrations=registrations or {},
        as_of=as_of,
    )


def test_the_real_run_is_read_as_failed_with_its_error():
    _targets, run = rs.parse_resolver_log(REAL_LOG)
    assert run["logAvailable"] and not run["completed"]
    assert "signer certificate is not pinned" in run["error"]


@pytest.mark.parametrize(
    "ref, state, code",
    [
        (
            "fed.g19.consumer_credit_total_annual_rate.2026_07.first_print",
            "resolved_this_run",
            "RESOLVED_BUT_RUN_FAILED",
        ),
        (
            "bls.jolts.hires_rate.2026_07.first_print",
            "recorded_awaiting_publish",
            "RECORDED_AWAITING_PUBLISH",
        ),
        (
            "bls.cps.employed_people_by_occupation.production.july_2026.first_print",
            "refused",
            "UNIT_MISMATCH",
        ),
        (
            "bea.pce.core_mom.june_2026.first_print",
            "refused",
            "REGISTERED_WITHOUT_EXECUTOR",
        ),
        (
            "abs.labour.unemployment_rate.australia.july_2026.first_print",
            "refused",
            "BINDING_MISMATCH",
        ),
        (
            "bls.qcew.aircraft_manufacturing.establishments.2026_q1.first_print",
            "refused",
            "FIRST_PRINT_WINDOW_MISSED",
        ),
        (
            "ssa.hearings.average_processing_time_days.2026-06.first_print",
            "refused",
            "SOURCE_DOES_NOT_PUBLISH_FIGURE",
        ),
    ],
)
def test_real_resolver_lines_classify(ref, state, code):
    row = _status(_log((ref, "a-slug", "2026-08-01")))["targets"][ref]
    assert (row["state"], row["code"]) == (state, code)
    assert row["reason"] == rs.REASONS[code]
    assert row["forecastSlug"] == "a-slug" and row["resolutionDate"] == "2026-08-01"


def test_a_mismatch_that_names_no_field_is_not_reported_as_a_difference():
    """The 2026-09-18 log says "registry drift?): statcan.cpi... — " and
    then nothing: the routing bug, not a real difference. The status must
    not claim the binding differs when the resolver named nothing."""
    ref = "statcan.cpi.allitems.yoy.2026_07.first_print"
    row = _status(_log((ref, "canada-cpi", "2026-08-17")))["targets"][ref]
    assert row["code"] == "BINDING_MISMATCH_UNEXPLAINED"
    assert "named no field" in row["reason"]
    listed = "abs.labour.unemployment_rate.australia.july_2026.first_print"
    row = _status(_log((listed, "au-ur", "2026-08-20")))["targets"][listed]
    assert row["code"] == "BINDING_MISMATCH" and "sourceUrl" in row["detail"]


def test_a_target_the_resolver_never_mentions_is_explained_by_its_registration():
    refs = {
        "treasury.mts.monthly_deficit.june_2026.first_print": (
            "NO_EXECUTOR_UNREGISTERED"
        ),
        "ons.cpi.annual_rate.june_2026.first_print": "NO_EXECUTOR_GENERIC_URL",
        "x.other.series.2026_06.first_print": "NO_EXECUTOR_SERIES_NOT_COVERED",
        "y.covered.series.2026_06.first_print": "NO_REPORT",
    }
    registrations = {
        "ons.cpi.annual_rate.june_2026.first_print": {
            "contract": {"sourceBinding": {"adapter": "generic-url"}}
        },
        "x.other.series.2026_06.first_print": {
            "contract": {"sourceBinding": {"adapter": "bls-api"}}
        },
    }
    status = _status(
        _log(*[(ref, f"slug-{i}", "2026-07-13") for i, ref in enumerate(refs)]),
        claimed=["y.covered.series.2026_06.first_print"],
        registrations=registrations,
    )
    assert {ref: row["code"] for ref, row in status["targets"].items()} == refs
    assert status["targets"]["x.other.series.2026_06.first_print"]["detail"] == (
        "registered adapter bls-api"
    )


def test_only_pending_targets_past_their_date_get_a_row():
    log = _log(
        ("a.b.2026_06.first_print", "overdue", "2026-09-18"),
        ("a.b.2026_07.first_print", "due-today", "2026-09-19"),
        ("a.b.2026_08.first_print", "future", "2026-10-01"),
    )
    log["resolutionLinks"].append(
        {
            "status": "linked",
            "targetFactRef": "a.b.2026_05.first_print",
            "forecastSlug": "done",
        }
    )
    log["entries"].append(
        {
            "kind": "prediction_recorded",
            "forecastSlug": "done",
            "resolutionDate": "2026-06-01",
        }
    )
    assert list(_status(log)["targets"]) == ["a.b.2026_06.first_print"]


def test_no_resolver_log_says_so_instead_of_guessing():
    ref = "treasury.mts.monthly_deficit.june_2026.first_print"
    row = _status(_log((ref, "s", "2026-07-13")), text="")["targets"][ref]
    assert (row["state"], row["code"]) == ("unknown", "NO_RESOLVER_RUN")


# resolve_pending.main's own line once the reviewed proposal has merged.
APPENDED = (
    "appended 1 observation(s) to PolicyEngine/chronicle@codex/thesis-ledger-facts:"
    "ledger/official_observations.jsonl via reviewed proposal (merged at "
    + "a" * 40
    + ")"
)


def test_a_run_that_appended_reports_the_figure_as_recorded():
    """R22 finding 1: after "appended N observation(s) ... via reviewed
    proposal", the rows the run resolved are in the ledger. Saying they
    are "not yet recorded" was false."""
    ref = "us.dol.initial_claims.sa.week_2026-09-05"
    text = f"  resolve {ref} -> 206.0 thousands\n{APPENDED}\n"
    row = _status(_log((ref, "s", "2026-09-10")), text=text)["targets"][ref]
    assert (row["state"], row["code"]) == (
        "recorded_awaiting_publish",
        "RECORDED_AWAITING_PUBLISH",
    )
    # Appended, then crashed on a later step: still recorded.
    crashed = text + "Traceback (most recent call last):\nValueError: later step\n"
    row = _status(_log((ref, "s", "2026-09-10")), text=crashed)["targets"][ref]
    assert row["code"] == "RECORDED_AWAITING_PUBLISH"


def test_a_resolved_row_the_run_refused_is_not_called_recorded():
    ref = "bls.cps.employed_people_by_occupation.production.august_2026.first_print"
    text = (
        f"  resolve {ref} -> 7.716 millions\n"
        f"  CATALOG REFUSED (excluded from append): {ref} — unit conflict\n"
        f"{APPENDED}\n"
    )
    row = _status(_log((ref, "s", "2026-09-05")), text=text)["targets"][ref]
    assert row["code"] == "LEDGER_CATALOG_REFUSED"


def test_without_append_evidence_the_status_does_not_claim_the_ledger_lacks_it():
    ref = "a.b.2026_07.first_print"
    text = f"  resolve {ref} -> 4.2 percent\nnothing new to record\n"
    row = _status(_log((ref, "s", "2026-09-01")), text=text)["targets"][ref]
    assert row["code"] == "RESOLVED_AWAITING_RECORD"
    assert "not yet recorded" not in row["reason"]
    assert "does not show" in row["reason"]


@pytest.mark.parametrize(
    "line, code, must_not_say, must_say",
    [
        # R22 finding 3: each line is the resolver's own format; the case
        # beside it is what the reviewer executed through the resolver.
        (
            # fred_advance_value on HTTP 503 prints "not yet published".
            "not yet published: {ref}",
            "NOT_YET_PUBLISHED",
            "had not published",
            "reported it as not yet published",
        ),
        (
            # bls_series_rows read an API error document: nothing unreachable.
            "BLS API fetch failed: {ref}",
            "SOURCE_UNREACHABLE",
            "could not be reached",
            "did not return usable data",
        ),
        (
            # The Colorado LAUS adapter emits thousands from persons.
            "UNIT MISMATCH (refusing): {ref} cell='persons' adapter='thousands'",
            "UNIT_MISMATCH",
            "official source publishes",
            "adapter",
        ),
        (
            # bls_annual_first_print: an incomplete 24-month history.
            "FIRST-PRINT WINDOW MISSED (refusing): {ref} — 2026 December is "
            "latest but the target/prior 24-month window is incomplete; "
            "refusing a partial annual average",
            "FIRST_PRINT_WINDOW_MISSED",
            "not captured inside its registered window",
            "first-print check",
        ),
        (
            # BEA: the registered window differs from the one required.
            "FORECAST/REGISTERED RELEASE DATE MISMATCH (refusing): {ref} — "
            "forecast 2026-07-30 is outside {{'start': '2026-07-01', "
            "'end': '2026-09-30'}}",
            "RELEASE_DATE_MISMATCH",
            "falls outside",
            "does not agree",
        ),
    ],
)
def test_reasons_claim_no_more_than_the_emitting_branch(
    line, code, must_not_say, must_say
):
    ref = "bls.test.2026_08.first_print"
    text = "  " + line.format(ref=ref) + "\n"
    row = _status(_log((ref, "s", "2026-09-01")), text=text)["targets"][ref]
    assert row["code"] == code
    assert must_not_say not in row["reason"]
    assert must_say in row["reason"]


def test_a_named_a19_binding_difference_is_kept():
    """R22 finding 2: a19_execution_spec's refusal names the difference
    before the reference."""
    ref = "bls.cps.employed_people_by_occupation.production.august_2026.first_print"
    text = (
        "  BINDING/ADAPTER MISMATCH (refusing, registered A-19 contract differs "
        f"in sourceBinding keys): {ref}\n"
    )
    row = _status(_log((ref, "s", "2026-09-05")), text=text)["targets"][ref]
    assert row["code"] == "BINDING_MISMATCH"
    assert "sourceBinding keys" in row["detail"]
    # "full seven-key registry drift?" names nothing: still unexplained.
    text = (
        "  BINDING/ADAPTER MISMATCH (refusing, full seven-key registry drift?): "
        f"{ref}\n"
    )
    row = _status(_log((ref, "s", "2026-09-05")), text=text)["targets"][ref]
    assert row["code"] == "BINDING_MISMATCH_UNEXPLAINED"


def test_an_unknown_refusal_keeps_the_resolvers_own_words():
    text = "  SOMETHING NEW (refusing): a.b.2026_07.first_print — because of ##[x]::y\n"
    row = _status(_log(("a.b.2026_07.first_print", "s", "2026-09-01")), text=text)
    row = row["targets"]["a.b.2026_07.first_print"]
    assert (row["state"], row["code"]) == ("refused", "UNCLASSIFIED")
    assert "SOMETHING NEW (refusing)" in row["detail"]
    for unsafe in ("#", "[", "]", ":"):
        assert unsafe not in row["detail"]


def test_every_code_the_rules_can_emit_has_a_reason():
    emitted = (
        {code for _p, _s, code in rs._LINE_RULES}
        | {code for _state, code in rs._SUMMARY_HEADS.values()}
        | {
            "RESOLVED_BUT_RUN_FAILED",
            "BINDING_MISMATCH_UNEXPLAINED",
            "NO_EXECUTOR_GENERIC_URL",
            "NO_EXECUTOR_UNREGISTERED",
            "NO_EXECUTOR_SERIES_NOT_COVERED",
            "NO_REPORT",
            "NO_RESOLVER_RUN",
        }
    )
    assert emitted - {"UNCLASSIFIED"} <= set(rs.REASONS)
    states = {state for _p, state, _c in rs._LINE_RULES}
    assert states - {"resolved_this_run", "recorded_awaiting_publish"} <= set(
        rs.UNCLASSIFIED_REASONS
    )


def test_an_unclassified_deferral_is_not_called_a_refusal():
    ref = "a.b.2026_07.first_print"
    text = f"  SOMETHING NEW (deferring): {ref} — archive slow\n"
    row = _status(_log((ref, "s", "2026-09-01")), text=text)["targets"][ref]
    assert (row["state"], row["code"]) == ("deferred", "UNCLASSIFIED")
    assert "deferred" in row["reason"] and "refused" not in row["reason"]


def test_rows_are_ordered_and_an_unchanged_backlog_rewrites_nothing(tmp_path):
    log = _log(
        ("z.late.2026_08.first_print", "late", "2026-08-30"),
        ("a.early.2026_06.first_print", "early", "2026-07-13"),
    )
    status = _status(log)
    assert list(status["targets"]) == [
        "a.early.2026_06.first_print",
        "z.late.2026_08.first_print",
    ]
    out = tmp_path / "status.json"
    out.write_text(json.dumps({**status, "generatedAtUtc": "x", "workflowRun": "1"}))
    assert rs._same_apart_from_stamp(
        out, {**status, "generatedAtUtc": "y", "workflowRun": "2"}
    )
    changed = json.loads(json.dumps(status))
    changed["targets"]["a.early.2026_06.first_print"]["code"] = "UNIT_MISMATCH"
    assert not rs._same_apart_from_stamp(out, changed)


# --- The 2026-09-27 run: references after a message with its own colons ---


@pytest.mark.parametrize(
    "ref, state, code, detail_has",
    [
        (
            # "A-19 WAYBACK INDEX FETCH FAILED (deferring): HTTPError: HTTP
            # Error 503: Service Unavailable: <ref>"
            "bls.cps.employed_people_by_occupation.computer_mathematical"
            ".august_2026.first_print",
            "fetch_failed",
            "SOURCE_UNREACHABLE",
            "HTTPError",
        ),
        (
            # "A-19 CAPTURE READ FAILED (deferring): https://web.archive.org/
            # ... could not be read (URLError: ...), and ...: <ref>"
            "bls.cps.employed_people_by_occupation.production.august_2026.first_print",
            "deferred",
            "UNCLASSIFIED",
            "A-19 CAPTURE READ FAILED (deferring)",
        ),
        (
            "bls.cps.employed_people_by_occupation.production.september_2026"
            ".first_print",
            "deferred",
            "WINDOW_NOT_OPEN",
            "",
        ),
        (
            "abs.labour.unemployment_rate.2026_08.first_print",
            "refused",
            "FIRST_PRINT_WINDOW_MISSED",
            "",
        ),
        (
            "us.dol.initial_claims.sa.week_2026-09-05",
            "resolved_this_run",
            "RESOLVED_BUT_RUN_FAILED",
            "",
        ),
        (
            "bls.jolts.quits_rate.2026-07.first_print",
            "refused",
            "REGISTERED_WITHOUT_EXECUTOR",
            "",
        ),
    ],
)
def test_the_gate_run_lines_classify(ref, state, code, detail_has):
    row = _status(_log((ref, "a-slug", "2026-08-01")), text=GATE_LOG)["targets"][ref]
    assert (row["state"], row["code"]) == (state, code)
    assert detail_has in row.get("detail", "")


def test_the_gate_run_is_read_as_failed_with_the_gate_error():
    _targets, run = rs.parse_resolver_log(GATE_LOG)
    assert run["logAvailable"] and not run["completed"]
    assert "append gate did not pass" in run["error"]


def test_no_target_line_of_either_real_run_is_dropped():
    """Every reference a real run printed a target line about is read back,
    with or without the pending set, and never as "printed nothing"."""
    for text in (REAL_LOG, GATE_LOG):
        printed = set()
        for line in text.splitlines():
            if line.startswith("  ") and not line.startswith("   "):
                printed |= {
                    token
                    for token in rs._REF_RE.findall(line)
                    if re.search(r"20[0-9]{2}", token) and "/" not in token
                }
        assert printed, "fixture has no target lines"
        for known in (None, printed):
            targets, _run = rs.parse_resolver_log(text, known)
            assert set(targets) == printed
            assert all(row["state"] != "unknown" for row in targets.values())


# --- Summary lines at the end of a run restate; they never overwrite ---


def test_an_end_of_run_refused_line_keeps_the_catalog_refusal():
    ref = "bls.cps.employed_people_by_occupation.production.august_2026.first_print"
    reason = "series catalog: unit millions conflicts with thousands"
    text = "\n".join(
        [
            f"  resolve {ref} -> 7.716 millions",
            f"  CATALOG REFUSED (excluded from append): {ref} — {reason}",
            "every fetched row was refused; nothing to append",
            f"  refused: {ref}: {reason}",
        ]
    )
    row = _status(_log((ref, "s", "2026-09-05")), text=text)["targets"][ref]
    assert (row["state"], row["code"]) == ("refused", "LEDGER_CATALOG_REFUSED")
    assert row["reason"] == rs.REASONS["LEDGER_CATALOG_REFUSED"]
    assert "unit millions conflicts with thousands" in row["detail"]


def test_a_summary_line_alone_still_reports_its_target():
    ref = "a.b.2026_07.first_print"
    text = (
        "environment failures left admitted references unresolvable (x):\n"
        f"  fatal: {ref}: parser missing\n"
    )
    targets, run = rs.parse_resolver_log(text)
    assert targets[ref]["code"] == "ENVIRONMENT_FAILURE"
    assert not run["completed"] and run["error"]


@pytest.mark.parametrize(
    "line, code",
    [
        (
            "LEDGER UNIT CONFLICT (refusing): {ref} — Chronicle already holds",
            "LEDGER_UNIT_CONFLICT",
        ),
        (
            "PROVENANCE REFUSED (excluded from append): {ref} — no projection",
            "PROVENANCE_REFUSED",
        ),
        ("BLS API fetch failed: {ref}", "SOURCE_UNREACHABLE"),
        (
            "USAspending fetch failed (HTTPError: HTTP Error 502: Bad Gateway): {ref}",
            "SOURCE_UNREACHABLE",
        ),
        (
            "A-19 FIRST-PRINT WINDOW MISSED (refusing): the Archive's index "
            "lists no capture: {ref}",
            "FIRST_PRINT_WINDOW_MISSED",
        ),
        (
            "fetch/parse failed (deferring): {ref} — ValueError: bad table",
            "UNCLASSIFIED",
        ),
    ],
)
def test_line_shapes_added_since_the_first_fixture(line, code):
    ref = "a.b.2026_07.first_print"
    targets, _run = rs.parse_resolver_log("  " + line.format(ref=ref) + "\n")
    assert targets[ref]["code"] == code


def test_a_dotted_word_in_a_message_is_not_taken_for_the_target():
    ref = "abs.cpi.all_groups.yoy.2026_08.first_print"
    line = f"  fetch/parse failed (deferring): {ref} — KeyError: pandas.core.frame\n"
    targets, _run = rs.parse_resolver_log(line, {ref})
    assert set(targets) == {ref}
    exc_first = f"  LookupError: see abs.cpi.docs: {ref}\n"
    targets, _run = rs.parse_resolver_log(exc_first, {ref})
    assert set(targets) == {ref}


# --- Differential: every line shape the resolver can print about a target ---

_RESOLVER = ROOT / "scripts" / "resolve_pending.py"


def _templates() -> tuple[
    list[tuple[tuple[str, str], ...]], list[tuple[tuple[str, str], ...]]
]:
    """(target-line f-strings, A-19 discovery verdicts) in resolve_pending.py.

    A target line is an f-string that starts with exactly two spaces and
    interpolates ``ref``, printed directly or returned for printing (the
    resolve-by window gate). Parts are ("text", s) or ("field", expr).
    """
    tree = ast.parse(_RESOLVER.read_text())

    def parts(node: ast.AST) -> tuple[tuple[str, str], ...] | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return (("text", node.value),)
        if not isinstance(node, ast.JoinedStr):
            return None
        out: list[tuple[str, str]] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                out.append(("text", value.value))
            else:
                out.append(("field", ast.unparse(value.value)))
        return tuple(out)

    lines, verdicts = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            shape = parts(node)
            first = shape[0] if shape else None
            if (
                first
                and first[0] == "text"
                and first[1].startswith("  ")
                and not first[1].startswith("   ")
                and ("field", "ref") in shape
            ):
                lines.append(shape)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "A19Discovery"
            and len(node.args) >= 3
        ):
            shape = parts(node.args[2])
            if shape and shape != (("text", ""),):
                verdicts.append(shape)
    return lines, verdicts


TARGET_TEMPLATES, A19_VERDICTS = _templates()

_REFS = st.from_regex(r"[a-z][a-z0-9_]{0,8}(\.[a-z0-9_\-]{1,10}){1,5}", fullmatch=True)
# Free text as the resolver interpolates it: exceptions, URLs, reasons.
# It never starts with whitespace: a line indented past two spaces is a
# traceback frame or a wrapped continuation, not a target line.
_FILLER = st.text(
    alphabet=st.sampled_from(list("abcXYZ019 .:,;/_-()<>'=—")), max_size=40
).filter(lambda s: "\n" not in s and not s[:1].isspace())


def _render(shape, ref, fill, rng) -> str:
    out = []
    for kind, value in shape:
        if kind == "text":
            out.append(value)
        elif value == "ref":
            out.append(ref)
        elif value == "discovery.verdict":
            out.append(_render(rng.choice(A19_VERDICTS), ref, fill, rng))
        else:
            out.append(fill)
    return "".join(out)


def _marker_states(prefix: str) -> set[str] | None:
    """States a line may be read as, from the words before its reference."""
    if "(fatal" in prefix:
        return {"fetch_failed"}
    if "(deferring" in prefix:
        return {"deferred", "fetch_failed"}
    if re.search(r"\((refusing|skipping|excluded from append)", prefix):
        return {"refused"}
    return None


def test_the_resolver_still_prints_the_shapes_this_file_reads():
    assert len(TARGET_TEMPLATES) >= 50
    assert len(A19_VERDICTS) >= 8
    heads = {shape[0][1].split(":")[0].strip() for shape in TARGET_TEMPLATES}
    for head in ("CATALOG REFUSED (excluded from append)", "already recorded"):
        assert head in heads


@settings(max_examples=300, deadline=None)
@given(ref=_REFS, fill=_FILLER, seed=st.integers(0, 2**16))
def test_every_resolver_target_line_is_read_back_with_its_reference(ref, fill, seed):
    """Differential against the resolver's own f-strings: whatever it
    interpolates, the parser finds the pending reference, and a line that
    says "(refusing", "(deferring" or "(fatal" before the reference is
    never read as another state."""
    rng = random.Random(seed)
    for shape in TARGET_TEMPLATES:
        line = _render(shape, ref, fill, rng)
        targets, _run = rs.parse_resolver_log(line + "\n", {ref})
        assert set(targets) == {ref}, line
        row = targets[ref]
        assert row["code"] == "UNCLASSIFIED" or row["code"] in rs.REASONS, line
        prefix = line[: line.index(ref)]
        allowed = _marker_states(prefix)
        if allowed and not line.lstrip().startswith(("refused:", "fatal:")):
            assert row["state"] in allowed, line


# --- Properties of the status file ---

_STATES_CODES = [(state, code) for _p, state, code in rs._LINE_RULES]


@st.composite
def _worlds(draw):
    n = draw(st.integers(0, 12))
    refs = draw(st.lists(_REFS, min_size=n, max_size=n, unique=True))
    as_of = dt.date(2026, 9, 15) + dt.timedelta(days=draw(st.integers(0, 30)))
    links, entries = [], []
    for i, ref in enumerate(refs):
        due = dt.date(2026, 7, 1) + dt.timedelta(days=draw(st.integers(0, 120)))
        status = draw(st.sampled_from(["pending", "pending", "linked"]))
        links.append({"status": status, "targetFactRef": ref, "forecastSlug": f"s{i}"})
        entries.append(
            {
                "kind": "prediction_recorded",
                "forecastSlug": f"s{i}",
                "resolutionDate": due.isoformat(),
            }
        )
    said = {}
    for ref in draw(st.lists(st.sampled_from(refs), unique=True)) if refs else []:
        state, code = draw(st.sampled_from(_STATES_CODES))
        said[ref] = {"state": state, "code": code, "detail": ""}
    run = {
        "logAvailable": draw(st.booleans()),
        "completed": draw(st.booleans()),
        "error": "",
    }
    claimed = set(draw(st.lists(st.sampled_from(refs), unique=True))) if refs else set()
    registrations = {
        ref: {
            "contract": {
                "sourceBinding": {
                    "adapter": draw(st.sampled_from(["generic-url", "bls-api", ""]))
                }
            }
        }
        for ref in (draw(st.lists(st.sampled_from(refs), unique=True)) if refs else [])
    }
    return (
        {"entries": entries, "resolutionLinks": links},
        said,
        run,
        claimed,
        registrations,
        as_of,
    )


@settings(max_examples=300, deadline=None)
@given(world=_worlds(), seed=st.integers(0, 2**16))
def test_the_status_file_has_one_explained_row_per_overdue_pending_target(world, seed):
    log, said, run, claimed, registrations, as_of = world
    status = rs.build_status(
        log, said, run, claimed_refs=claimed, registrations=registrations, as_of=as_of
    )
    due = {e["forecastSlug"]: e["resolutionDate"] for e in log["entries"]}
    expected = {
        link["targetFactRef"]
        for link in log["resolutionLinks"]
        if link["status"] == "pending" and due[link["forecastSlug"]] < as_of.isoformat()
    }
    # Completeness and nothing extra.
    assert set(status["targets"]) == expected
    for ref, row in status["targets"].items():
        # Every row is explained by exactly the reason its code (or, for a
        # line no rule knows, its state) names.
        assert row["reason"] == rs.reason_for(row["code"], row["state"])
        if row["code"] != "UNCLASSIFIED":
            assert row["reason"] == rs.REASONS[row["code"]]
        assert row["resolutionDate"] < status["asOf"]
        if (
            ref in said
            and said[ref]["state"] == "resolved_this_run"
            and not run["completed"]
        ):
            assert row["code"] == "RESOLVED_BUT_RUN_FAILED"
    # Ordered by (date, reference), and independent of input order.
    keys = [(row["resolutionDate"], ref) for ref, row in status["targets"].items()]
    assert keys == sorted(keys)
    rng = random.Random(seed)
    shuffled = {
        "entries": rng.sample(log["entries"], len(log["entries"])),
        "resolutionLinks": rng.sample(
            log["resolutionLinks"], len(log["resolutionLinks"])
        ),
    }
    again = rs.build_status(
        shuffled,
        said,
        run,
        claimed_refs=claimed,
        registrations=registrations,
        as_of=as_of,
    )
    assert json.dumps(again) == json.dumps(status)


@settings(max_examples=500, deadline=None)
@given(text=st.text(max_size=400), limit=st.integers(1, 300))
def test_reprinted_resolver_text_is_always_safe(text, limit):
    plain = rs._plain(text, limit)
    assert len(plain) <= limit
    assert not rs._UNSAFE_RE.search(plain)
    assert rs._plain(plain, limit) == plain


@settings(max_examples=300, deadline=None)
@given(
    lines=st.lists(
        st.one_of(
            # The resolver's own target lines (R22: noise alone never spells
            # a rule head, so it exercised only UNCLASSIFIED).
            st.tuples(
                st.sampled_from(TARGET_TEMPLATES), _REFS, _FILLER, st.integers(0, 99)
            ).map(lambda t: _render(t[0], t[1], t[2], random.Random(t[3]))),
            st.just(APPENDED),
            _FILLER.map(lambda s: "  " + s),
            st.tuples(_FILLER, _REFS, _FILLER).map(
                lambda t: f"  {t[0]}: {t[1]} — {t[2]}"
            ),
            st.tuples(_FILLER, _REFS).map(lambda t: f"  {t[0]}: {t[1]}"),
            _FILLER,
        ),
        max_size=20,
    )
)
def test_any_log_parses_to_known_states_and_explained_codes(lines):
    targets, run = rs.parse_resolver_log("\n".join(lines))
    for row in targets.values():
        assert row["state"] in {
            "resolved_this_run",
            "recorded_awaiting_publish",
            "deferred",
            "fetch_failed",
            "refused",
            "unknown",
        }
        assert row["code"] == "UNCLASSIFIED" or row["code"] in rs.REASONS
        assert not rs._UNSAFE_RE.search(row["detail"])


# --- Review R24 ---


def test_an_unregistered_target_is_not_said_to_predate_registration():
    """R24 finding 1: the check is "no registered contract"; the two
    Colorado forecasts were made after registration existed."""
    ref = "co.dor.individual_income_tax.net_collections.2026_07.first_print"
    row = _status(_log((ref, "s", "2026-08-31")), text="  x: y.z\n")["targets"][ref]
    assert row["code"] == "NO_EXECUTOR_UNREGISTERED"
    assert "predates" not in row["reason"]
    assert "no registered resolution contract" in row["reason"]


def test_a_named_adapter_family_mismatch_is_kept():
    """R24 finding 2: resolve_pending prints the registered adapter when
    it belongs to another family."""
    ref = "bls.wp.WPSFD4.2026-07.first_print"
    text = (
        "  BINDING/ADAPTER MISMATCH (skipping, registered adapter='bls-api' is "
        f"not a alfred family): {ref}\n"
    )
    row = _status(_log((ref, "s", "2026-08-13")), text=text)["targets"][ref]
    assert row["code"] == "BINDING_MISMATCH"
    assert "registered adapter='bls-api'" in row["detail"]


def test_a_target_with_no_line_naming_it_is_not_said_to_have_none_printed():
    """R24 finding 3: SBA refusals print no reference, so "printed nothing
    about this target" can be false; "no line naming it" is what is known."""
    ref = "sba.7a.loans.fy2026.first_print"
    text = (
        "  SBA CUSTODY ABSENT (refusing): no dedicated capture exists for "
        "sba.7a fiscal year 2026\n"
    )
    row = _status(_log((ref, "s", "2026-09-01")), text=text, claimed=[ref])["targets"][
        ref
    ]
    assert row["code"] == "NO_REPORT"
    assert "printed no line naming this target" in row["reason"]


def test_release_day_not_reached_says_only_that_the_run_came_first():
    ref = "a.b.2026_08.first_print"
    text = f"  release 2026-09-30 not reached: {ref}\n"
    row = _status(_log((ref, "s", "2026-09-01")), text=text)["targets"][ref]
    assert row["code"] == "RELEASE_DAY_NOT_REACHED"
    assert "later than the date shown" not in row["reason"]
    assert "came before the release day" in row["reason"]


def test_a_line_with_no_marker_is_neither_a_refusal_nor_a_deferral():
    """R24 finding 5: the intl adapters print "  <exception>: <ref>" for a
    KeyError, e.g. "'data': <ref>", with no refusing or deferring marker."""
    ref = "abs.cpi.all_groups.yoy.2026_08.first_print"
    row = _status(_log((ref, "s", "2026-09-01")), text=f"  'data': {ref}\n")
    row = row["targets"][ref]
    assert (row["state"], row["code"]) == ("unknown", "UNCLASSIFIED")
    assert row["reason"] == rs.UNCLASSIFIED_REASONS["unknown"]


def test_the_verdicts_own_marker_beats_text_interpolated_after_it():
    """R24 finding 6: an exception after the verdict cannot overrule it."""
    ref = "bls.cps.employed_people_by_occupation.production.july_2026.first_print"
    text = (
        "  A-19 WAYBACK INDEX FETCH FAILED (deferring): ConnectionError: peer "
        f"(refusing connections): {ref}\n"
    )
    row = _status(_log((ref, "s", "2026-08-06")), text=text)["targets"][ref]
    assert (row["state"], row["code"]) == ("fetch_failed", "SOURCE_UNREACHABLE")
    # A verdict whose marker comes only at its end still reads as its marker.
    text = (
        "  A-19 none of the rows read inside the registered window prints "
        "2026-07 yet: the Archive's index lists 2 rows; 1 unread (deferring): "
        f"{ref}\n"
    )
    row = _status(_log((ref, "s", "2026-08-06")), text=text)["targets"][ref]
    assert row["state"] == "deferred"
