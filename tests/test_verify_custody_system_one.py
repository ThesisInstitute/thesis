"""Custody verification for the system_one run mode."""

from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_system_one_forecast as system_one  # noqa: E402
import run_thesis_analyst as analyst  # noqa: E402
import verify_custody  # noqa: E402
from verify_custody import CustodyError, verify_run  # noqa: E402

from tests.test_run_system_one_forecast import (  # noqa: E402
    RUN_AT,
    SLUG,
    ledger_rows,
    primary_cell,
    repo,  # noqa: F401 - pytest fixture
    system_one_run,
)


def reseal(run_dir: pathlib.Path, mutate=None) -> None:
    """Rebuild a consistent custody chain after editing a sealed run.

    Tamper tests need runs whose hashes all agree but whose lane contract is
    wrong, so that the failure they prove comes from the system_one rules
    rather than from a broken digest.
    """

    manifest = json.loads((run_dir / "manifest.json").read_text())
    if mutate is not None:
        mutate(manifest)
    refs = [ref for ref in manifest["artifacts"] if ref["artifactType"] != "manifest"]
    for ref in refs:
        path = run_dir / pathlib.Path(ref["path"]).name
        raw = path.read_bytes()
        ref["sha256"] = analyst.sha256_bytes(raw)
        ref["bytes"] = len(raw)
    manifest.pop("custodyRootSha256", None)
    manifest["artifacts"] = refs
    system_one.seal(
        out_dir=run_dir,
        run_started_at=manifest["runStartedAt"],
        manifest=manifest,
        refs=refs,
    )


@pytest.fixture
def sealed_run(repo: pathlib.Path) -> pathlib.Path:  # noqa: F811
    _manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    assert verify_run(manifest_path.parent).run_succeeded is True
    return manifest_path.parent


@pytest.fixture
def failed_run(repo: pathlib.Path) -> pathlib.Path:  # noqa: F811
    manifest, manifest_path = system_one_run(
        repo, cell=primary_cell(history_count=2), ledger=None
    )
    assert manifest["error"]["phase"] == "state"
    return manifest_path.parent


def test_response_byte_edit_breaks_custody(sealed_run: pathlib.Path):
    response = sealed_run / "response.json"
    raw = response.read_text()
    response.write_text(raw.replace('"noul": 0.', '"noul": 1.', 1))
    with pytest.raises(CustodyError, match="raw SHA-256 mismatch"):
        verify_run(sealed_run)


def test_unregistered_extra_file_breaks_custody(sealed_run: pathlib.Path):
    (sealed_run / "notes.txt").write_text("stray\n")
    with pytest.raises(CustodyError, match="run directory inventory mismatch"):
        verify_run(sealed_run)


def test_registered_extra_artifact_is_not_the_lane_inventory(
    sealed_run: pathlib.Path,
):
    extra = sealed_run / "extra.json"
    extra.write_text(json.dumps({"stray": True}) + "\n")

    def mutate(manifest: dict) -> None:
        manifest["artifacts"].insert(
            -1,
            {
                "artifactType": "system_one_state",
                "path": analyst.repo_relative(extra),
                "sha256": "0" * 64,
                "bytes": 0,
                "createdAt": manifest["runStartedAt"],
            },
        )

    reseal(sealed_run, mutate)
    with pytest.raises(CustodyError, match="not the complete lane inventory"):
        verify_run(sealed_run)


def test_wrong_phase_inventory_is_refused(failed_run: pathlib.Path):
    error = json.loads((failed_run / "error.json").read_text())
    error["phase"] = "ladder"
    (failed_run / "error.json").write_text(json.dumps(error, indent=2) + "\n")

    def mutate(manifest: dict) -> None:
        manifest["error"] = error

    reseal(failed_run, mutate)
    with pytest.raises(CustodyError, match="ladder-failure inventory is invalid"):
        verify_run(failed_run)


def test_unknown_failure_phase_is_refused(failed_run: pathlib.Path):
    error = json.loads((failed_run / "error.json").read_text())
    error["phase"] = "seal"
    (failed_run / "error.json").write_text(json.dumps(error, indent=2) + "\n")
    reseal(failed_run, lambda manifest: manifest.update({"error": error}))
    with pytest.raises(CustodyError, match="unknown system_one failure phase"):
        verify_run(failed_run)


def test_error_phase_on_a_complete_run_is_refused(sealed_run: pathlib.Path):
    def mutate(manifest: dict) -> None:
        manifest["error"] = {"phase": "backend", "message": "forged", "detail": None}

    reseal(sealed_run, mutate)
    with pytest.raises(CustodyError, match="does not present as failed"):
        verify_run(sealed_run)


def test_command_backend_must_match_the_manifest_agent(sealed_run: pathlib.Path):
    command = json.loads((sealed_run / "command.json").read_text())
    command["backend"] = "typesafe"
    (sealed_run / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    reseal(sealed_run)
    with pytest.raises(CustodyError, match="command backend disagrees"):
        verify_run(sealed_run)


def test_unknown_backend_is_refused(sealed_run: pathlib.Path):
    def mutate(manifest: dict) -> None:
        manifest["agent"]["backend"] = "smuggled"

    reseal(sealed_run, mutate)
    with pytest.raises(CustodyError, match="invalid backend"):
        verify_run(sealed_run)


def test_resolver_field_must_equal_the_trusted_target(sealed_run: pathlib.Path):
    cells_path = sealed_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    cells[0]["resolutionSourceUrl"] = "https://elsewhere.example/other"
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_run)
    with pytest.raises(
        CustodyError, match="resolutionSourceUrl differs from the trusted target"
    ):
        verify_run(sealed_run)


def test_non_monotone_ladder_is_refused(sealed_run: pathlib.Path):
    cells_path = sealed_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    probabilities = cells[0]["thresholdLadder"]["cumulativeProbabilities"]
    probabilities[5], probabilities[6] = probabilities[6], probabilities[5]
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_run)
    with pytest.raises(CustodyError, match="cumulative probabilities are not monotone"):
        verify_run(sealed_run)


def test_ladder_must_declare_its_monotonization(sealed_run: pathlib.Path):
    cells_path = sealed_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    cells[0]["thresholdLadder"].pop("monotonization")
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_run)
    with pytest.raises(CustodyError, match="lacks its monotonization version"):
        verify_run(sealed_run)


def test_cells_path_cannot_point_outside_the_run(
    sealed_run: pathlib.Path, repo: pathlib.Path  # noqa: F811
):
    def mutate(manifest: dict) -> None:
        manifest["cellsPath"] = (
            "records/thesis-analyst/2029-12-31/"
            f"2029-12-31t00-00-00z-primary-{SLUG}/cells.with_activity.json"
        )

    reseal(sealed_run, mutate)
    with pytest.raises(
        CustodyError, match="does not resolve inside run|cellsPath is outside its run"
    ):
        verify_run(sealed_run)


def test_run_mode_must_agree_between_manifest_and_custody_root(
    sealed_run: pathlib.Path,
):
    custody_path = sealed_run / "custody_root.json"
    custody = json.loads(custody_path.read_text())
    custody["runMode"] = "analyst"
    custody_path.write_text(json.dumps(custody, indent=2) + "\n")
    with pytest.raises(CustodyError, match="custody run mode mismatch"):
        verify_run(sealed_run)


def test_activity_log_must_expose_the_rooted_prefix(sealed_run: pathlib.Path):
    cells_path = sealed_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    cells[0]["activityLog"] = cells[0]["activityLog"][:-1]
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_run)
    with pytest.raises(CustodyError, match="complete rooted activity prefix"):
        verify_run(sealed_run)


def test_sealed_at_cannot_precede_the_run_start(sealed_run: pathlib.Path):
    reseal(
        sealed_run,
        lambda manifest: manifest.update({"sealedAt": "2029-01-01T00:00:00Z"}),
    )
    with pytest.raises(CustodyError, match="seal time predates"):
        verify_run(sealed_run)


def test_verification_reports_the_lane_as_not_headline_eligible(
    sealed_run: pathlib.Path,
):
    verification = verify_run(sealed_run)
    assert verification.run_mode == "system_one"
    assert verification.custody_inventory_version == 2
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is True
    assert verification.headline_eligible is False
    assert verification.artifact_count == len(system_one.SUCCESS_INVENTORY)
    assert RUN_AT[:10] in sealed_run.parent.name


def test_custody_verifier_never_imports_the_system_one_sdk():
    tree = ast.parse((ROOT / "scripts" / "verify_custody.py").read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"typesafe_sdk", "system_one_adapter", "msgspec"}


def test_runner_and_verifier_agree_on_every_inventory():
    # The verifier must not import the runner (which pulls in the analyst
    # module), so the two inventories are written twice. They must not drift.
    assert verify_custody.SYSTEM_ONE_SUCCESS_INVENTORY == [
        tuple(entry) for entry in system_one.SUCCESS_INVENTORY
    ]
    assert set(verify_custody.SYSTEM_ONE_FAILURE_INVENTORIES) == set(
        system_one.FAILURE_INVENTORIES
    )
    for phase, inventory in system_one.FAILURE_INVENTORIES.items():
        assert verify_custody.SYSTEM_ONE_FAILURE_INVENTORIES[phase] == [
            tuple(entry) for entry in inventory
        ]
    assert verify_custody.SYSTEM_ONE_BACKENDS == set(system_one.BACKENDS)
    assert verify_custody.SYSTEM_ONE_SCHEMA == system_one.MANIFEST_SCHEMA
    assert verify_custody.SYSTEM_ONE_AGENT == system_one.AGENT_NAME
    # One prompt mode per elicitation, each bound to the derivation it is
    # allowed to declare. The verifier writes this map out a second time
    # because it must not import the runner; the two may not drift.
    assert verify_custody.SYSTEM_ONE_PROMPT_MODES == {
        system_one.PROMPT_MODES[elicitation]: system_one.MONOTONIZATIONS[elicitation]
        for elicitation in system_one.ELICITATIONS
    }
    assert verify_custody.SYSTEM_ONE_BIN_MONOTONIZATION == (
        system_one.MONOTONIZATIONS["choice_bins"]
    )
    assert verify_custody.SYSTEM_ONE_BIN_SUM_TOLERANCE == (
        system_one.BIN_SUM_TOLERANCE
    )


def test_a_snapshot_shaped_target_still_binds_the_unit(sealed_run: pathlib.Path):
    # A trusted selection target spells the scoring unit targetUnit; a
    # registration snapshot spells it unit, and the runner reads either. The
    # resolver check has to read either too, or it silently checks nothing.
    cells_path = sealed_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    cells[0]["unit"] = "index_points"
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")

    def to_snapshot_shape(manifest: dict) -> None:
        target = manifest["targetContext"]
        target["unit"] = target.pop("targetUnit")

    reseal(sealed_run, to_snapshot_shape)

    with pytest.raises(CustodyError, match="unit differs from the trusted target"):
        verify_run(sealed_run)


def test_a_failed_typesafe_run_may_record_no_answering_model(
    sealed_run: pathlib.Path,
):
    # A run that failed before the service answered names no model; a
    # successful one always must.
    def clear_model(manifest: dict) -> None:
        manifest["agent"]["model"] = None

    reseal(sealed_run, clear_model)
    with pytest.raises(CustodyError, match="agent lacks a model string"):
        verify_run(sealed_run)


@pytest.fixture
def sealed_bins_run(repo: pathlib.Path) -> pathlib.Path:  # noqa: F811
    _manifest, manifest_path = system_one_run(
        repo, ledger=ledger_rows(), elicitation="choice_bins"
    )
    assert verify_run(manifest_path.parent).run_succeeded is True
    return manifest_path.parent


def test_custody_accepts_the_bins_prompt_mode(sealed_bins_run: pathlib.Path):
    manifest = json.loads((sealed_bins_run / "manifest.json").read_text())
    assert manifest["promptMode"] == "system_one_choice_bins"
    cell = json.loads((sealed_bins_run / "cells.with_activity.json").read_text())[0]
    assert cell["thresholdLadder"]["monotonization"] == "cumulative_sum_v1"

    verification = verify_run(sealed_bins_run)
    assert verification.run_mode == "system_one"
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is True
    assert verification.headline_eligible is False


def test_bins_run_may_not_declare_the_pooled_monotonization(
    sealed_bins_run: pathlib.Path,
):
    cells_path = sealed_bins_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    cells[0]["thresholdLadder"]["monotonization"] = "pav_v1"
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_bins_run)
    with pytest.raises(CustodyError, match="lacks its monotonization version"):
        verify_run(sealed_bins_run)


def test_ladder_run_may_not_declare_the_bin_monotonization(
    sealed_run: pathlib.Path,
):
    cells_path = sealed_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    cells[0]["thresholdLadder"]["monotonization"] = "cumulative_sum_v1"
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_run)
    with pytest.raises(CustodyError, match="lacks its monotonization version"):
        verify_run(sealed_run)


def test_bins_cumulative_vector_must_be_the_running_sum(
    sealed_bins_run: pathlib.Path,
):
    cells_path = sealed_bins_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    cumulative = cells[0]["thresholdLadder"]["cumulativeProbabilities"]
    # Still non-decreasing, still in [0, 1]: only the recomputation catches it.
    cumulative[7] = min(cumulative[8], cumulative[7] + 0.05)
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_bins_run)
    with pytest.raises(
        CustodyError, match="cumulative probabilities are not the bin sums"
    ):
        verify_run(sealed_bins_run)


def test_bins_masses_must_sum_to_one(sealed_bins_run: pathlib.Path):
    cells_path = sealed_bins_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    ladder = cells[0]["thresholdLadder"]
    masses = ladder["binProbabilities"]
    last = list(masses)[-1]
    masses[last] = round(masses[last] + 0.2, 10)
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_bins_run)
    with pytest.raises(CustodyError, match="bin probabilities do not sum to 1"):
        verify_run(sealed_bins_run)


def test_bins_choice_must_be_one_of_the_labels(sealed_bins_run: pathlib.Path):
    cells_path = sealed_bins_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    cells[0]["thresholdLadder"]["choice"] = "somewhere_else"
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_bins_run)
    with pytest.raises(CustodyError, match="choice is not one of the bin labels"):
        verify_run(sealed_bins_run)


def test_bins_masses_are_required_by_the_declared_derivation(
    sealed_bins_run: pathlib.Path,
):
    cells_path = sealed_bins_run / "cells.with_activity.json"
    cells = json.loads(cells_path.read_text())
    cells[0]["thresholdLadder"].pop("binProbabilities")
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")
    reseal(sealed_bins_run)
    with pytest.raises(CustodyError, match="bin probabilities are malformed"):
        verify_run(sealed_bins_run)


def test_a_failed_run_with_no_model_verifies(failed_run: pathlib.Path):
    def clear_model(manifest: dict) -> None:
        manifest["agent"]["model"] = None
        manifest["agent"]["backend"] = "typesafe"

    reseal(failed_run, clear_model)

    verification = verify_run(failed_run)
    assert verification.run_mode == "system_one"
    assert verification.run_succeeded is False
