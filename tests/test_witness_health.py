from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import witness_health  # noqa: E402

# Real, immutable markers on either side of DigiCert's responder rotation.
BOTH_WITNESSED = ROOT / "records/2026-09-03/digest-33786852779-1.json"
DIGICERT_REFUSED = ROOT / "records/2026-09-18/digest-35372147258-1.json"
# The v1 -> v2 transition snapshot: DigiCert was a new authority then, so its
# marker carries a real supplemental outcome for the pending bundle.
V2_TRANSITION = ROOT / "records/2026-07-10/digest-29110005611-1.json"


def _marker(digest: pathlib.Path) -> dict:
    return json.loads(digest.with_suffix(".witness.json").read_text())


def test_every_anchor_witnessed_is_healthy() -> None:
    degraded, text = witness_health.report(BOTH_WITNESSED, _marker(BOTH_WITNESSED))
    assert degraded is False
    assert text.startswith("All 2 TSA anchors witnessed")


def test_responder_rotation_is_reported_with_the_runbook() -> None:
    marker = _marker(DIGICERT_REFUSED)
    # One anchor is enough for the snapshot to count, which is why this was
    # silent: the marker itself says "available".
    assert marker["status"] == "available"
    degraded, text = witness_health.report(DIGICERT_REFUSED, marker)
    assert degraded is True
    assert "1 of 2 TSA anchors did not witness" in text
    assert "`digicert-trusted-root-g4` (http://timestamp.digicert.com)" in text
    assert "token signer is not pinned" in text
    assert "replaced its responder certificate" in text
    assert witness_health.ROTATION_RUNBOOK in text
    assert (ROOT / witness_health.ROTATION_RUNBOOK).is_file()


def test_an_outage_is_reported_without_claiming_a_rotation() -> None:
    marker = _marker(DIGICERT_REFUSED)
    marker["anchorOutcomes"][1]["reason"] = "timestamp request failed: timed out"
    degraded, text = witness_health.report(DIGICERT_REFUSED, marker)
    assert degraded is True
    assert "timed out" in text
    assert "replaced its responder certificate" not in text


def test_a_snapshot_no_anchor_witnessed_is_reported_as_unwitnessed() -> None:
    marker = _marker(DIGICERT_REFUSED)
    marker["status"] = "unavailable"
    marker["reason"] = "all active-bundle TSA requests or verifications failed"
    for outcome in marker["anchorOutcomes"]:
        outcome["status"] = "unavailable"
        outcome.setdefault("reason", "timestamp request failed: timed out")
    degraded, text = witness_health.report(DIGICERT_REFUSED, marker)
    assert degraded is True
    assert text.startswith("No TSA anchor witnessed")
    assert "no external time proof" in text
    assert "stays pending" in text
    assert "of 2 TSA anchors did not witness" not in text


def test_a_verified_probe_of_a_pending_bundle_is_healthy() -> None:
    marker = _marker(V2_TRANSITION)
    assert [outcome["status"] for outcome in marker["supplementalOutcomes"]] == [
        "available"
    ]
    degraded, text = witness_health.report(V2_TRANSITION, marker)
    assert degraded is False
    assert text.startswith("All 1 TSA anchors witnessed")


def test_a_failed_probe_of_a_pending_bundle_is_reported() -> None:
    marker = _marker(V2_TRANSITION)
    probe = marker["supplementalOutcomes"][0]
    marker["supplementalOutcomes"][0] = {
        "role": probe["role"],
        "status": "unavailable",
        "tsa": probe["tsa"],
        "tsaAnchorId": probe["tsaAnchorId"],
        "trustBundleId": probe["trustBundleId"],
        "reason": "timestamp request failed: timed out",
    }
    degraded, text = witness_health.report(V2_TRANSITION, marker)
    assert degraded is True
    assert text.startswith("All 1 TSA anchors witnessed")
    assert "did not produce a verified token" in text
    assert "`digicert-trusted-root-g4`" in text
    assert "under `tsa-anchors-v2`" in text
    assert "does not stop the bundle activating" in text


def test_supplemental_outcomes_must_be_a_list() -> None:
    marker = _marker(BOTH_WITNESSED)
    marker["supplementalOutcomes"] = {"not": "a list"}
    with pytest.raises(ValueError, match="supplementalOutcomes is not a list"):
        witness_health.report(BOTH_WITNESSED, marker)


def test_a_marker_without_outcomes_is_an_error_not_a_clean_bill() -> None:
    with pytest.raises(ValueError, match="no anchorOutcomes"):
        witness_health.report(BOTH_WITNESSED, {"status": "unavailable"})


@pytest.mark.parametrize(
    ("digest", "status"),
    [(BOTH_WITNESSED, 0), (DIGICERT_REFUSED, witness_health.DEGRADED_EXIT_STATUS)],
)
def test_exit_status_tells_the_workflow_which_way_to_go(
    digest: pathlib.Path, status: int
) -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/witness_health.py"), "--digest", digest],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == status
    assert completed.stdout.strip()


def test_a_missing_marker_is_neither_healthy_nor_degraded(
    tmp_path: pathlib.Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/witness_health.py"),
            "--digest",
            tmp_path / "digest-absent.json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode not in {0, witness_health.DEGRADED_EXIT_STATUS}
    assert completed.stdout == ""


def test_recorder_workflow_reports_degraded_witnessing_after_the_push() -> None:
    workflow = (ROOT / ".github/workflows/record-forecasts.yml").read_text()
    start = workflow.index("- name: Report degraded witnessing")
    assert workflow.index("uses: ./.github/actions/attest-records-push") < start
    step = workflow[start : workflow.index("- name: Alert on failure")]
    assert "python3 scripts/witness_health.py" in step
    # The digest path reaches the script through env, not by interpolating an
    # expression into the shell body.
    assert "DIGEST: ${{ steps.snapshot.outputs.digest }}" in step
    assert '--digest "$DIGEST"' in step
    assert "${{" not in step.split("run: |", 1)[1]
    # A failed notice must never turn a pushed, attested recording red.
    assert "continue-on-error: true" in step
    assert "steps.snapshot_push.outputs.committed == '1'" in step
    assert "gh issue create" in step and "gh issue close" in step
