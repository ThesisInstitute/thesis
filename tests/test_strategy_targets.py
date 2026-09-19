from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_ledger_targets import generated_entry_for  # noqa: E402
from strategy_targets import (  # noqa: E402
    StrategyTargetError,
    ensure_open,
    registrations_by_slug,
    select_targets,
    selection_hash,
    stamp_artifact,
    verify_artifact,
    verify_selection,
)

OPEN_SLUG = "australia-cpi-annual-rate-july-2026"
OPEN_DATA_POINT = "abs.cpi.all_groups.yoy.2026-07.first_print"


def head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def empty_ledger(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "official_observations.jsonl"
    path.write_text("")
    return path


def selection(
    tmp_path: pathlib.Path,
    *,
    slug: str = OPEN_SLUG,
    selected_at: str = "2026-07-10T07:00:00Z",
    ledger: pathlib.Path | None = None,
) -> dict:
    return select_targets(
        root=ROOT,
        source_sha=head(),
        selected_at_utc=selected_at,
        checked_at_utc=selected_at,
        workflow={"repository": "example/thesis", "runId": 123, "runAttempt": 1},
        requested_slugs=[slug],
        auto_select=False,
        max_targets=1,
        suite="both",
        ledger_path=ledger or empty_ledger(tmp_path),
        ledger_repository="PolicyEngine/chronicle",
        ledger_branch="codex/thesis-ledger-facts",
        ledger_logical_path="ledger/official_observations.jsonl",
        ledger_repository_commit="a" * 40,
        ledger_blob_sha="b" * 40,
    )


def test_selector_resolves_one_published_v2_target_and_replays(
    tmp_path: pathlib.Path,
) -> None:
    ledger = empty_ledger(tmp_path)
    payload = selection(tmp_path, ledger=ledger)

    assert payload["schemaVersion"] == "thesis_strategy_selection_v1"
    assert payload["sourceSha"] == head()
    assert payload["targets"][0]["catalogSlug"] == OPEN_SLUG
    assert payload["targets"][0]["comparisonTarget"] is True
    assert payload["targets"][0]["registrationCommit"] == (
        "f2738042716881427217caa9c3c13aa4ca8783e5"
    )
    assert payload["targets"][0]["resolutionDate"] == "2026-08-26"
    assert payload["targets"][0]["targetRegistrationPath"].startswith(
        "records/targets/"
    )
    assert payload["localResolutionEvidence"]["resolvedDataPointIds"] == []
    assert payload["ledgerEvidence"]["resolvedDataPointIds"] == []
    assert payload["selectionSetHash"] == selection_hash(payload)

    stamped = stamp_artifact(
        payload,
        artifact_id=456,
        artifact_name="strategy-selection-probe-123-1",
        artifact_digest="c" * 64,
        artifact_created_at_utc="2026-07-10T07:01:00Z",
    )
    verify_selection(stamped, root=ROOT, ledger_path=ledger)


def test_selector_rejects_unknown_unpublished_resolved_and_release_day(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(StrategyTargetError, match="unknown catalog slug"):
        selection(tmp_path, slug="definitely-not-a-catalog-target")

    with pytest.raises(StrategyTargetError, match="not contemporaneous"):
        selection(tmp_path, slug="ons-cpi-annual-rate-june-2026")

    resolved = tmp_path / "resolved.jsonl"
    resolved.write_text(json.dumps({"source_record_id": OPEN_DATA_POINT}) + "\n")
    with pytest.raises(StrategyTargetError, match="pinned official ledger"):
        selection(tmp_path, ledger=resolved)

    with pytest.raises(StrategyTargetError, match="release day"):
        selection(tmp_path, selected_at="2026-08-26T00:00:00Z")


def test_selector_rejects_registered_but_unpublished_targets(
    tmp_path: pathlib.Path,
) -> None:
    # Pick a registered-but-unpublished slug from live state: hardcoding one
    # broke the moment that target published (the data-state-literal trap).
    # Split from the combined rejection test so its skip cannot swallow the
    # other cases (Sol review P2-10).
    registrations = registrations_by_slug(ROOT)
    generated = ROOT.joinpath(
        "site/src/data/ledger-targets.generated.ts"
    ).read_text()

    def is_preregistered(data_point_id: str) -> bool:
        match = generated_entry_for(generated, data_point_id)
        entry = match.group(0) if match else ""
        return 'registrationState: "preregistered"' in entry

    unpublished = next(
        (
            slug
            for slug, rows in sorted(registrations.items())
            if len(rows) == 1
            and is_preregistered(rows[0]["contract"]["dataPointId"])
        ),
        None,
    )
    if unpublished is None:
        pytest.skip("every registered target is currently published")
    with pytest.raises(StrategyTargetError, match="not published"):
        selection(tmp_path, slug=unpublished)


def test_selector_requires_registration_commit_strictly_before_selection(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(StrategyTargetError, match="strictly predate"):
        selection(tmp_path, selected_at="2026-07-10T05:03:57Z")


def test_selector_artifact_witness_and_latest_open_checks(
    tmp_path: pathlib.Path,
) -> None:
    payload = stamp_artifact(
        selection(tmp_path),
        artifact_id=456,
        artifact_name="strategy-selection-probe-123-1",
        artifact_digest="d" * 64,
        artifact_created_at_utc="2026-07-10T07:01:00Z",
    )
    artifact = {
        "id": 456,
        "name": "strategy-selection-probe-123-1",
        "digest": f"sha256:{'d' * 64}",
        "created_at": "2026-07-10T07:01:00Z",
        "expired": False,
        "workflow_run": {"id": 123},
    }
    verify_artifact(payload, artifact)

    tampered = json.loads(json.dumps(artifact))
    tampered["workflow_run"]["id"] = 999
    with pytest.raises(StrategyTargetError, match="different workflow run"):
        verify_artifact(payload, tampered)

    missing_expiry = json.loads(json.dumps(artifact))
    missing_expiry.pop("expired")
    with pytest.raises(StrategyTargetError, match="unexpired status"):
        verify_artifact(payload, missing_expiry)

    resolved = tmp_path / "latest-resolved.jsonl"
    resolved.write_text(json.dumps({"source_record_id": OPEN_DATA_POINT}) + "\n")
    with pytest.raises(StrategyTargetError, match="became resolved"):
        ensure_open(
            payload,
            root=ROOT,
            ledger_path=resolved,
            checked_at_utc="2026-07-10T07:02:00Z",
        )


def test_selection_hash_rejects_boolean_number_substitution(
    tmp_path: pathlib.Path,
) -> None:
    payload = selection(tmp_path)
    payload["request"]["maxTargets"] = True
    assert selection_hash(payload) != payload["selectionSetHash"]


def test_require_pre_cutover_commit_semantics(tmp_path: pathlib.Path) -> None:
    import strategy_targets as module
    from strategy_targets import require_pre_cutover_commit

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.com",
                *args,
            ],
            cwd=repo,
            text=True,
        ).strip()

    git("init")
    (repo / "a").write_text("a\n")
    git("add", "a")
    git("commit", "-m", "first")
    first = git("rev-parse", "HEAD")
    (repo / "b").write_text("b\n")
    git("add", "b")
    git("commit", "-m", "cutover")
    cutover = git("rev-parse", "HEAD")

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(module, "V3_REGISTRATION_CUTOVER_COMMIT", cutover)
        require_pre_cutover_commit(repo, first)
        with pytest.raises(StrategyTargetError, match="strictly predate"):
            require_pre_cutover_commit(repo, cutover)
        monkey.setattr(module, "V3_REGISTRATION_CUTOVER_COMMIT", first)
        with pytest.raises(StrategyTargetError, match="strictly predate"):
            require_pre_cutover_commit(repo, cutover)
    finally:
        monkey.undo()


def test_selection_binds_ladder_prompt_mode_sparsely(
    tmp_path: pathlib.Path,
) -> None:
    ledger = empty_ledger(tmp_path)

    # Default selections stay byte-identical to the pre-ladder_v2 shape so
    # historical selections keep re-verifying.
    default = selection(tmp_path, ledger=ledger)
    assert "ladderPromptMode" not in default["request"]

    v2 = select_targets(
        root=ROOT,
        source_sha=head(),
        selected_at_utc="2026-07-10T07:00:00Z",
        checked_at_utc="2026-07-10T07:00:00Z",
        workflow={"repository": "example/thesis", "runId": 124, "runAttempt": 1},
        requested_slugs=[OPEN_SLUG],
        auto_select=False,
        max_targets=1,
        suite="both",
        ladder_prompt_mode="ladder_v2",
        ledger_path=ledger,
        ledger_repository="PolicyEngine/chronicle",
        ledger_branch="codex/thesis-ledger-facts",
        ledger_logical_path="ledger/official_observations.jsonl",
        ledger_repository_commit="a" * 40,
        ledger_blob_sha="b" * 40,
    )
    assert v2["request"]["ladderPromptMode"] == "ladder_v2"
    assert v2["selectionSetHash"] == selection_hash(v2)

    # The trusted verify path replays the mode.
    stamped = stamp_artifact(
        v2,
        artifact_id=457,
        artifact_name="strategy-selection-probe-124-1",
        artifact_digest="d" * 64,
        artifact_created_at_utc="2026-07-10T07:01:00Z",
    )
    verify_selection(stamped, root=ROOT, ledger_path=ledger)

    with pytest.raises(StrategyTargetError, match="ladder prompt mode"):
        select_targets(
            root=ROOT,
            source_sha=head(),
            selected_at_utc="2026-07-10T07:00:00Z",
            checked_at_utc="2026-07-10T07:00:00Z",
            workflow={
                "repository": "example/thesis",
                "runId": 125,
                "runAttempt": 1,
            },
            requested_slugs=[OPEN_SLUG],
            auto_select=False,
            max_targets=1,
            suite="both",
            ladder_prompt_mode="ladder_v3",
            ledger_path=ledger,
            ledger_repository="PolicyEngine/chronicle",
            ledger_branch="codex/thesis-ledger-facts",
            ledger_logical_path="ledger/official_observations.jsonl",
            ledger_repository_commit="a" * 40,
            ledger_blob_sha="b" * 40,
        )


def system_one_selection(
    ledger: pathlib.Path,
    *,
    run_id: int,
    suite: str = "system_one",
    backend: str = "adapter",
    model: str = "",
    elicitation: str | None = None,
) -> dict:
    return select_targets(
        root=ROOT,
        source_sha=head(),
        selected_at_utc="2026-07-10T07:00:00Z",
        checked_at_utc="2026-07-10T07:00:00Z",
        workflow={"repository": "example/thesis", "runId": run_id, "runAttempt": 1},
        requested_slugs=[OPEN_SLUG],
        auto_select=False,
        max_targets=1,
        suite=suite,
        system_one_backend=backend,
        system_one_model=model,
        system_one_elicitation=elicitation,
        ledger_path=ledger,
        ledger_repository="PolicyEngine/chronicle",
        ledger_branch="codex/thesis-ledger-facts",
        ledger_logical_path="ledger/official_observations.jsonl",
        ledger_repository_commit="a" * 40,
        ledger_blob_sha="b" * 40,
    )


def test_selection_binds_the_system_one_forecaster_sparsely(
    tmp_path: pathlib.Path,
) -> None:
    ledger = empty_ledger(tmp_path)

    # Codex suites never bind a System One forecaster, so every selection
    # minted before this lane still re-verifies byte-identically.
    codex = system_one_selection(ledger, run_id=130, suite="both", backend="typesafe")
    assert "systemOneBackend" not in codex["request"]
    assert "systemOneElicitation" not in codex["request"]
    assert "systemOneModel" not in codex["request"]

    lane = system_one_selection(ledger, run_id=131, backend="typesafe", model="jev-1")
    assert lane["request"]["suite"] == "system_one"
    assert lane["request"]["systemOneBackend"] == "typesafe"
    assert lane["request"]["systemOneModel"] == "jev-1"
    assert lane["selectionSetHash"] == selection_hash(lane)

    # The trusted verify path replays the forecaster from the request alone.
    stamped = stamp_artifact(
        lane,
        artifact_id=470,
        artifact_name="strategy-selection-probe-131-1",
        artifact_digest="e" * 64,
        artifact_created_at_utc="2026-07-10T07:01:00Z",
    )
    verify_selection(stamped, root=ROOT, ledger_path=ledger)

    # An empty model is recorded as null: the runner default for the backend.
    default_model = system_one_selection(ledger, run_id=132)
    assert default_model["request"]["systemOneBackend"] == "adapter"
    assert default_model["request"]["systemOneModel"] is None
    assert default_model["selectionSetHash"] == selection_hash(default_model)

    with pytest.raises(StrategyTargetError, match="system_one backend"):
        system_one_selection(ledger, run_id=133, backend="openai")

    # The model reaches the runner as one argv element; anything that could
    # be read as another flag is refused at selection time.
    with pytest.raises(StrategyTargetError, match="system_one model"):
        system_one_selection(ledger, run_id=134, model="--records-root")

    # Swapping the forecaster after the fact breaks the selection hash.
    # The canonical replay itself reads the forecaster back out of the
    # request, exactly as it does for ladderPromptMode, so the hash and
    # the GitHub artifact witness are what bind it.
    tampered = json.loads(json.dumps(stamped))
    tampered["request"]["systemOneModel"] = "jev-2"
    with pytest.raises(StrategyTargetError, match="selectionSetHash mismatch"):
        verify_selection(tampered, root=ROOT, ledger_path=ledger)


def test_selection_pins_the_system_one_elicitation(tmp_path: pathlib.Path) -> None:
    ledger = empty_ledger(tmp_path)

    # An omitted elicitation is recorded as the resolved default for the
    # trusted backend, never as the omission, so the generate job reads a
    # decision rather than making one.
    real_model = system_one_selection(ledger, run_id=140, backend="typesafe")
    assert real_model["request"]["systemOneElicitation"] == "choice_bins"
    control = system_one_selection(ledger, run_id=141, backend="adapter", elicitation="")
    assert control["request"]["systemOneElicitation"] == "noul_ladder"

    # Either elicitation may be asked of either backend.
    pinned = system_one_selection(
        ledger, run_id=142, backend="adapter", elicitation="choice_bins"
    )
    assert pinned["request"]["systemOneElicitation"] == "choice_bins"
    assert pinned["selectionSetHash"] == selection_hash(pinned)

    with pytest.raises(StrategyTargetError, match="system_one elicitation"):
        system_one_selection(ledger, run_id=143, elicitation="score_ladder")

    # The trusted verify path replays the elicitation from the request, and
    # swapping it after the fact breaks the selection hash.
    stamped = stamp_artifact(
        pinned,
        artifact_id=471,
        artifact_name="strategy-selection-probe-142-1",
        artifact_digest="f" * 64,
        artifact_created_at_utc="2026-07-10T07:01:00Z",
    )
    verify_selection(stamped, root=ROOT, ledger_path=ledger)
    tampered = json.loads(json.dumps(stamped))
    tampered["request"]["systemOneElicitation"] = "noul_ladder"
    with pytest.raises(StrategyTargetError, match="selectionSetHash mismatch"):
        verify_selection(tampered, root=ROOT, ledger_path=ledger)
