"""The registered-window witness workflow cannot write records."""

from __future__ import annotations

import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ".github/workflows/witness-registered-windows.yml"
WORKFLOW = ROOT / WORKFLOW_PATH
sys.path.insert(0, str(ROOT / "scripts"))

import verify_records_attestations as provenance  # noqa: E402


def _workflow() -> dict:
    parsed = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(parsed, dict)
    return parsed


def test_the_witness_runs_twice_a_day_clear_of_the_utc_date_change() -> None:
    workflow = _workflow()
    trigger = workflow.get("on", workflow.get(True))
    crons = [item["cron"] for item in trigger["schedule"]]
    assert crons == ["40 19 * * *", "10 22 * * *"]
    assert trigger["workflow_dispatch"]["inputs"]["mode"]["options"] == [
        "capture",
        "dry-run",
        "audit",
    ]
    source = WORKFLOW.read_text()
    # Only the second pass skips what the index already shows, and its floor
    # sits before the first pass's start.
    assert source.count("--skip-captured-since 19:30") == 1
    assert '[ "$SCHEDULE" = "10 22 * * *" ]' in source


def test_the_witness_holds_a_read_only_token_and_publishes_nothing() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read", "issues": "write"}
    job = workflow["jobs"]["witness"]
    assert "permissions" not in job
    checkout = next(
        s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False
    source = WORKFLOW.read_text()
    for forbidden in (
        "git push",
        "git commit",
        "git add",
        "attest-records-push",
        "id-token",
        "contents: write",
    ):
        assert forbidden not in source, forbidden


def test_the_witness_is_not_an_attesting_workflow() -> None:
    # A workflow on this list may attest a records push. The witness writes
    # no records, so adding it would only widen who can.
    assert WORKFLOW_PATH not in provenance.ALLOWED_WORKFLOWS


def test_the_report_leaves_the_checkout_and_inputs_are_not_interpolated() -> None:
    source = WORKFLOW.read_text()
    assert 'REPORT="$RUNNER_TEMP/registered-window-witness/report.json"' in source
    run_step = next(
        s for s in _workflow()["jobs"]["witness"]["steps"] if s.get("id") == "witness"
    )
    assert "${{" not in run_step["run"]
    assert run_step["env"]["MODE"] == "${{ github.event.inputs.mode || 'capture' }}"
    assert (
        "uv run --locked python scripts/witness_registered_windows.py"
        in run_step["run"]
    )


def test_a_new_custody_alert_reddens_the_run_and_lands_in_an_issue() -> None:
    steps = _workflow()["jobs"]["witness"]["steps"]
    names = [s.get("name") for s in steps]
    flag = names.index("Flag custody alerts nobody has been told about")
    alert = names.index("Alert on failure")
    keep = names.index("Keep the run's report")
    assert keep < flag < alert
    script = steps[flag]["run"]
    # Every alert kind travels through one list, so a new kind cannot be
    # forgotten here: the unread-index case once left the run green.
    assert "(.alerts // [])[] | [.marker, .text] | @tsv" in script
    assert "custodyGaps" not in script
    assert "exit 1" in script
    assert "if" not in steps[flag]
    assert 'gh issue list --state all --search "\\"$marker\\""' in script
    assert "|| echo 0" in script  # a failed search raises the alert
    assert "${{" not in script
    assert steps[alert]["if"] == "failure()"
    assert steps[keep]["if"].startswith("always()")
    assert "gh issue create" in steps[alert]["run"]
    assert "gh issue comment" in steps[alert]["run"]
    assert "new-alerts.md" in steps[alert]["run"]
