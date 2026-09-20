from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import docket_publication  # noqa: E402
import register_targets  # noqa: E402
from generate_ledger_targets import generated_entry_for  # noqa: E402
from strategy_targets import (  # noqa: E402
    GENERATED_TARGETS_RELATIVE,
    StrategyTargetError,
    ensure_open,
    published_resolution_date,
    published_target,
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
    target = payload["targets"][0]
    # The published forecast's resolver date rides separately; the trusted
    # target mirrors the registration's date fields with exact presence, and
    # this v2 release-calendar contract binds no resolutionDate.
    assert target["publishedResolutionDate"] == "2026-08-26"
    assert "resolutionDate" not in target
    assert "resolutionDateBasis" not in target
    assert target["expectedReleaseWindow"] == {
        "start": "2026-08-25",
        "end": "2026-09-02",
    }
    assert target["expectedReleaseWindow"] == (
        target["sourceBinding"]["expectedReleaseWindow"]
    )
    assert target["targetRegistrationPath"].startswith("records/targets/")
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


def _published(slug: str, selected_at: str) -> dict:
    import datetime as dt

    generated = ROOT.joinpath(*GENERATED_TARGETS_RELATIVE.parts).read_text()
    return published_target(
        ROOT,
        slug,
        registrations_by_slug(ROOT),
        generated,
        head(),
        dt.datetime.fromisoformat(selected_at.replace("Z", "+00:00")),
    )


@pytest.mark.parametrize(
    ("slug", "registration_kind"),
    [
        # v3 release-calendar contract: no resolutionDate in the snapshot.
        # Actions run 35524670779 (2026-09-20) was blocked on exactly this
        # target because the selector copied the published date into
        # resolutionDate.
        ("unemployment-rate-september-2026", "release-calendar"),
        # v3 resolve-by-bound contract: resolutionDate is the registered
        # bound. Actions run 35525381224 was blocked on this one because the
        # target lacked the top-level expectedReleaseWindow.
        ("us-natural-gas-vented-flared-2025", "resolve-by-bound"),
    ],
)
def test_selected_target_passes_publisher_registration_projection(
    slug: str, registration_kind: str
) -> None:
    target = _published(slug, "2026-09-21T00:00:00Z")
    registration = registrations_by_slug(ROOT)[slug][0]
    contract = registration["contract"]

    assert target["comparisonTarget"] is True
    assert target["publishedResolutionDate"]
    assert published_resolution_date(target).isoformat() == (
        target["publishedResolutionDate"]
    )
    assert target["expectedReleaseWindow"] == (
        contract["sourceBinding"]["expectedReleaseWindow"]
    )
    if registration_kind == "release-calendar":
        assert "resolutionDate" not in contract
        assert "resolutionDate" not in target
        assert "resolutionDateBasis" not in target
    else:
        assert contract["resolutionDateBasis"] == "resolve-by-bound"
        assert target["resolutionDateBasis"] == "resolve-by-bound"
        assert target["resolutionDate"] == contract["resolutionDate"]
        assert target["publishedResolutionDate"] == contract["resolutionDate"]

    # The exact checks the strategy publisher applies to a batch target.
    register_targets.validate_target_resolution_projection(
        contract, target, label=registration["relative"]
    )
    docket_publication.validate_target_registration(ROOT, target)


def test_selector_refuses_published_date_that_contradicts_a_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import strategy_targets as module

    slug = "us-natural-gas-vented-flared-2025"
    original = module.block_value

    def contradicting(block: str, key: str):
        value = original(block, key)
        if key == "resolutionDate" and value == "2026-10-31":
            return "2026-10-30"
        return value

    monkeypatch.setattr(module, "block_value", contradicting)
    with pytest.raises(StrategyTargetError, match="resolutionDate"):
        _published(slug, "2026-09-21T00:00:00Z")


def test_published_resolution_date_requires_the_published_field() -> None:
    with pytest.raises(StrategyTargetError, match="lacks publishedResolutionDate"):
        published_resolution_date({"catalogSlug": "x", "resolutionDate": "2030-01-01"})
    with pytest.raises(StrategyTargetError, match="invalid publishedResolutionDate"):
        published_resolution_date(
            {"catalogSlug": "x", "publishedResolutionDate": "2030-13-01"}
        )
