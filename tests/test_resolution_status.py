"""`scripts/resolution_status.py` restates, per overdue target, what the
resolver said about it. The fixture is the resolver's real stdout from the
scheduled run of 2026-09-18 (Actions run 35372945335), which resolved five
cells and then died on an unpinned DigiCert responder.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolution_status as rs  # noqa: E402

REAL_LOG = (
    ROOT / "tests" / "fixtures" / "resolution_status" / "resolver-run-35372945335.log"
).read_text()
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


def test_a_completed_run_reports_a_resolved_cell_as_awaiting_record():
    text = "  resolve a.b.2026_07.first_print -> 4.2 percent\\nappended 1 row(s)\\n"
    row = _status(_log(("a.b.2026_07.first_print", "s", "2026-09-01")), text=text)
    assert (
        row["targets"]["a.b.2026_07.first_print"]["code"] == "RESOLVED_AWAITING_RECORD"
    )


def test_an_unknown_refusal_keeps_the_resolvers_own_words():
    text = (
        "  SOMETHING NEW (refusing): a.b.2026_07.first_print — because of ##[x]::y\\n"
    )
    row = _status(_log(("a.b.2026_07.first_print", "s", "2026-09-01")), text=text)
    row = row["targets"]["a.b.2026_07.first_print"]
    assert (row["state"], row["code"]) == ("refused", "UNCLASSIFIED")
    assert "SOMETHING NEW (refusing)" in row["detail"]
    for unsafe in ("#", "[", "]", ":"):
        assert unsafe not in row["detail"]


def test_every_code_the_rules_can_emit_has_a_reason():
    emitted = {code for _p, _s, code in rs._LINE_RULES} | {
        "RESOLVED_BUT_RUN_FAILED",
        "BINDING_MISMATCH_UNEXPLAINED",
        "NO_EXECUTOR_GENERIC_URL",
        "NO_EXECUTOR_UNREGISTERED",
        "NO_EXECUTOR_SERIES_NOT_COVERED",
        "NO_REPORT",
        "NO_RESOLVER_RUN",
    }
    assert emitted - {"UNCLASSIFIED"} <= set(rs.REASONS)


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
