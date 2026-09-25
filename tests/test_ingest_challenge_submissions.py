from __future__ import annotations

import json
import logging
import pathlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ingest_challenge_submissions as ingest  # noqa: E402
from record_forecast_snapshot import build_snapshot_predictions  # noqa: E402


def write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def git(repo: pathlib.Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def commit_all(repo: pathlib.Path, message: str) -> str:
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Challenge Adapter Test",
        "-c",
        "user.email=challenge-adapter@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        message,
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def submission_repo(tmp_path: pathlib.Path) -> dict[str, Any]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")

    target = {
        "schemaVersion": "thesis_target_registration_v3",
        "registeredAtUtc": "2030-01-01T00:00:00Z",
        "targets": [
            {
                "catalogSlug": "fixture-rate-january-2030",
                "country": "US",
                "dataPointId": "agency.fixture.rate.2030_01.first_print",
                "period": "2030-01",
                "series": "agency.fixture.rate",
                "sourceBinding": {
                    "adapter": "fixture",
                    "expectedReleaseWindow": {
                        "start": "2030-02-01",
                        "end": "2030-02-01",
                    },
                },
                "unit": "percent",
                "valueScale": 1,
            }
        ],
    }
    quantiles = [
        {"p": 0.05, "value": 2.7},
        {"p": 0.1, "value": 2.8},
        {"p": 0.25, "value": 2.9},
        {"p": 0.5, "value": 3.0},
        {"p": 0.75, "value": 3.1},
        {"p": 0.9, "value": 3.2},
        {"p": 0.95, "value": 3.3},
    ]
    submission = {
        "schemaVersion": "thesis_challenge_submission_v1",
        "challenger": "github:fixture-user",
        "systemType": "ai",
        "systemName": "Fixture Forecaster 1",
        "dataPointId": "agency.fixture.rate.2030_01.first_print",
        "pointEstimate": 3.0,
        "ciLow": 2.8,
        "ciHigh": 3.2,
        "quantiles": quantiles,
        "generatedAtUtc": "2030-01-31T12:00:00Z",
        "notes": "Fixture notes are retained.",
    }
    targets_dir = repo / "records" / "targets"
    inbox_dir = repo / "challenge" / "inbox"
    submission_path = inbox_dir / "fixture-user" / "fixture-rate.json"
    write_json(targets_dir / "2030-01-01-fixture.json", target)
    write_json(submission_path, submission)
    # The adapter refuses ids on the shared expired-registration ratchet
    # and fails closed when the file is absent, so the fixture repo
    # carries a minimal real-shaped copy with one expired fixture id.
    ratchet = repo / "site" / "src" / "data" / "expired-unforecast-registrations.ts"
    ratchet.parent.mkdir(parents=True, exist_ok=True)
    ratchet.write_text(
        "export const EXPIRED_UNFORECAST_REGISTRATIONS = [\n"
        '  "agency.fixture.expired.2029_12.first_print",\n'
        "] as const;\n"
    )
    head = commit_all(repo, "Add registered target and challenge submission")
    return {
        "repo": repo,
        "targets_dir": targets_dir,
        "inbox_dir": inbox_dir,
        "submission_path": submission_path,
        "submission": submission,
        "quantiles": quantiles,
        "head": head,
    }


def run_ingest(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    return ingest.ingest_challenge_submissions(
        inbox_dir=fixture["inbox_dir"],
        targets_dir=fixture["targets_dir"],
        repo_root=fixture["repo"],
    )


def rewrite_and_commit(
    fixture: dict[str, Any], payload: dict[str, Any], message: str
) -> None:
    write_json(fixture["submission_path"], payload)
    fixture["head"] = commit_all(fixture["repo"], message)


def test_valid_submission_is_included_with_verbatim_quantiles_and_provenance(
    submission_repo: dict[str, Any],
) -> None:
    records = run_ingest(submission_repo)

    assert len(records) == 1
    record = records[0]
    assert record["forecastSlug"] == "fixture-rate-january-2030"
    assert record["dataPointId"] == "agency.fixture.rate.2030_01.first_print"
    assert record["forecasterId"] == ("github:fixture-user::Fixture Forecaster 1")
    assert record["pointEstimate"] == 3.0
    assert record["interval80"] == {"lower": 2.8, "upper": 3.2}
    assert record["quantiles"] == submission_repo["quantiles"]
    assert record["generatedAtUtc"] == "2030-01-31T12:00:00Z"
    assert record["recordedAt"] == "2030-01-31T12:00:00Z"
    assert record["resolutionDate"] == "2030-02-01"
    assert record["notes"] == "Fixture notes are retained."
    assert record["provenance"] == {
        "submissionPath": "challenge/inbox/fixture-user/fixture-rate.json",
        "mergeCommit": submission_repo["head"],
        "schemaVersion": "thesis_challenge_submission_v1",
    }


def test_second_shot_rejects_while_first_accepted_survives(
    submission_repo: dict[str, Any],
) -> None:
    # One shot per (challenger, target): git history orders acceptance,
    # so the first accepted content IS the forecast; a later divergent
    # file rejects while the original and rival challengers survive.
    duplicate = dict(submission_repo["submission"])
    duplicate["pointEstimate"] = 3.1
    write_json(
        submission_repo["inbox_dir"] / "fixture-user" / "second-shot.json",
        duplicate,
    )
    other = dict(submission_repo["submission"])
    other["challenger"] = "github:other-user"
    other["systemName"] = "Other Forecaster"
    write_json(
        submission_repo["inbox_dir"] / "other-user" / "fixture-rate.json",
        other,
    )
    commit_all(submission_repo["repo"], "Add duplicate and rival submissions")

    records = run_ingest(submission_repo)

    challengers = sorted(record["challenger"] for record in records)
    assert challengers == ["github:fixture-user", "github:other-user"]
    fixture_rows = [
        record for record in records if record["challenger"] == "github:fixture-user"
    ]
    assert len(fixture_rows) == 1
    assert fixture_rows[0]["pointEstimate"] == 3.0


def test_case_variant_challenger_cannot_double_enter(
    submission_repo: dict[str, Any],
) -> None:
    # GitHub logins are case-insensitive: GITHUB:FIXTURE-USER is the same
    # challenger, so the variant rejects against the first accepted
    # content while the original forecast survives.
    variant = dict(submission_repo["submission"])
    variant["challenger"] = "github:FIXTURE-USER"
    write_json(
        submission_repo["inbox_dir"] / "fixture-user-alias" / "same-target.json",
        variant,
    )
    commit_all(submission_repo["repo"], "Add case-variant duplicate")

    records = run_ingest(submission_repo)
    assert [record["challenger"] for record in records] == ["github:fixture-user"]


def test_rename_plus_edit_cannot_replace_the_forecast(
    submission_repo: dict[str, Any],
) -> None:
    # The round-3 bypass: delete the accepted file and re-add it under a
    # new name with a changed forecast. Canonical content is keyed to
    # (challenger, dataPointId) across history, so the replacement
    # rejects and nothing survives for the key until the challenger's PR
    # restores the accepted content.
    edited = dict(submission_repo["submission"])
    edited["pointEstimate"] = 3.2
    submission_repo["submission_path"].unlink()
    write_json(
        submission_repo["inbox_dir"] / "fixture-user" / "renamed-shot.json",
        edited,
    )
    commit_all(submission_repo["repo"], "Rename and edit the submission")

    assert run_ingest(submission_repo) == []


def test_merge_introduced_forecast_is_canonical_and_immutable(
    submission_repo: dict[str, Any],
) -> None:
    # A forecast accepted via a merge commit (branch -> mainline) must
    # enter the canonical map at the merge, so a later rename-plus-edit
    # still rejects.
    repo = submission_repo["repo"]
    git(repo, "checkout", "-q", "-b", "side")
    other = dict(submission_repo["submission"])
    other["challenger"] = "github:merge-user"
    path = submission_repo["inbox_dir"] / "merge-user" / "fixture-rate.json"
    write_json(path, other)
    commit_all(repo, "Side-branch submission")
    git(repo, "checkout", "-q", "-")
    git(
        repo,
        "-c",
        "user.name=Challenge Adapter Test",
        "-c",
        "user.email=challenge-adapter@example.com",
        "-c",
        "commit.gpgsign=false",
        "merge",
        "--no-ff",
        "-q",
        "-m",
        "Accept side submission",
        "side",
    )
    records = run_ingest(submission_repo)
    assert sorted(record["challenger"] for record in records) == [
        "github:fixture-user",
        "github:merge-user",
    ]

    edited = dict(other)
    edited["pointEstimate"] = 3.3
    path.unlink()
    write_json(submission_repo["inbox_dir"] / "merge-user" / "renamed.json", edited)
    commit_all(repo, "Rename and edit the merged submission")
    records = run_ingest(submission_repo)
    assert sorted(record["challenger"] for record in records) == ["github:fixture-user"]


def test_stale_branch_merged_later_cannot_predate_the_first_forecast(
    submission_repo: dict[str, Any],
) -> None:
    # Acceptance order is the first-parent chain: a divergent draft
    # committed on an old side branch and merged AFTER the real
    # submission landed must not become canonical.
    repo = submission_repo["repo"]
    # The side branch forks from the CURRENT tip and carries a divergent
    # draft for the fixture challenger's target at a different path.
    git(repo, "checkout", "-q", "-b", "stale")
    draft = dict(submission_repo["submission"])
    draft["pointEstimate"] = 9.9
    write_json(submission_repo["inbox_dir"] / "fixture-user" / "draft.json", draft)
    commit_all(repo, "Stale divergent draft")
    git(repo, "checkout", "-q", "-")
    git(
        repo,
        "-c",
        "user.name=Challenge Adapter Test",
        "-c",
        "user.email=challenge-adapter@example.com",
        "-c",
        "commit.gpgsign=false",
        "merge",
        "--no-ff",
        "-q",
        "-m",
        "Merge stale draft later",
        "stale",
    )
    records = run_ingest(submission_repo)
    # The mainline submission stays canonical; the draft is a divergent
    # surplus and rejects.
    assert [record["challenger"] for record in records] == ["github:fixture-user"]
    assert records[0]["pointEstimate"] == 3.0


def test_fixed_in_place_file_canonicalizes_and_then_locks(
    submission_repo: dict[str, Any],
) -> None:
    # Round-5 finding: an undecodable ADD followed by a valid
    # modification must canonicalize the first valid content — the key
    # must not stay fail-open. The fixed content survives, and a later
    # rewrite rejects against it.
    repo = submission_repo["repo"]
    path = submission_repo["inbox_dir"] / "fix-user" / "fixture-rate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe{ not json")
    commit_all(repo, "Add undecodable submission")

    fixed = dict(submission_repo["submission"])
    fixed["challenger"] = "github:fix-user"
    write_json(path, fixed)
    commit_all(repo, "Fix the submission in place")

    records = run_ingest(submission_repo)
    assert sorted(record["challenger"] for record in records) == [
        "github:fix-user",
        "github:fixture-user",
    ]

    rewritten = dict(fixed)
    rewritten["pointEstimate"] = 3.4
    write_json(path, rewritten)
    commit_all(repo, "Rewrite after acceptance")

    records = run_ingest(submission_repo)
    assert sorted(record["challenger"] for record in records) == ["github:fixture-user"]


def test_undecodable_history_does_not_abort_the_batch(
    submission_repo: dict[str, Any],
) -> None:
    bad = submission_repo["inbox_dir"] / "fixture-user" / "garbled.json"
    bad.write_bytes(b"\xff\xfe{ not json")
    commit_all(submission_repo["repo"], "Add undecodable file")
    bad.unlink()
    commit_all(submission_repo["repo"], "Remove undecodable file")

    records = run_ingest(submission_repo)
    assert [record["challenger"] for record in records] == ["github:fixture-user"]


def test_pure_rename_of_accepted_content_survives(
    submission_repo: dict[str, Any],
) -> None:
    # A byte-identical file at a new path is the same forecast.
    original_bytes = submission_repo["submission_path"].read_bytes()
    submission_repo["submission_path"].unlink()
    new_path = submission_repo["inbox_dir"] / "fixture-user" / "renamed.json"
    new_path.write_bytes(original_bytes)
    commit_all(submission_repo["repo"], "Rename the submission unchanged")

    records = run_ingest(submission_repo)
    assert [record["challenger"] for record in records] == ["github:fixture-user"]
    assert records[0]["pointEstimate"] == 3.0


def test_edited_accepted_submission_is_refused(
    submission_repo: dict[str, Any],
) -> None:
    # One shot per target includes the content: editing the accepted file
    # in a later commit must not replace the forecast.
    edited = dict(submission_repo["submission"])
    edited["pointEstimate"] = 3.05
    rewrite_and_commit(submission_repo, edited, "Nudge the point estimate")

    assert run_ingest(submission_repo) == []


def test_interval_must_equal_q10_and_q90(
    submission_repo: dict[str, Any],
) -> None:
    inconsistent = dict(submission_repo["submission"])
    inconsistent["ciLow"] = 2.75
    write_json(
        submission_repo["inbox_dir"] / "other-user" / "inconsistent.json",
        {**inconsistent, "challenger": "github:other-user"},
    )
    commit_all(submission_repo["repo"], "Add interval-inconsistent submission")

    records = run_ingest(submission_repo)
    challengers = sorted(record["challenger"] for record in records)
    assert challengers == ["github:fixture-user"]


def test_non_registered_submission_is_skipped(
    submission_repo: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = deepcopy(submission_repo["submission"])
    payload["dataPointId"] = "agency.fixture.missing.2030_01.first_print"
    rewrite_and_commit(submission_repo, payload, "Make target unregistered")

    with caplog.at_level(logging.WARNING, logger=ingest.__name__):
        records = run_ingest(submission_repo)

    assert records == []
    assert "challenge/inbox/fixture-user/fixture-rate.json" in caplog.text
    assert "unregistered dataPointId" in caplog.text


def test_post_release_submission_is_skipped_at_release_day_floor(
    submission_repo: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = deepcopy(submission_repo["submission"])
    payload["generatedAtUtc"] = "2030-02-01T00:00:00Z"
    rewrite_and_commit(submission_repo, payload, "Move submission to release")

    with caplog.at_level(logging.WARNING, logger=ingest.__name__):
        records = run_ingest(submission_repo)

    assert records == []
    assert "does not precede release 2030-02-01T00:00:00Z" in caplog.text


def test_non_monotone_quantiles_are_skipped(
    submission_repo: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = deepcopy(submission_repo["submission"])
    payload["quantiles"][3]["value"] = payload["quantiles"][2]["value"]
    rewrite_and_commit(submission_repo, payload, "Make quantiles non-monotone")

    with caplog.at_level(logging.WARNING, logger=ingest.__name__):
        records = run_ingest(submission_repo)

    assert records == []
    assert "quantile values must be strictly increasing" in caplog.text


def test_quantile_probability_grid_must_match_exactly(
    submission_repo: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = deepcopy(submission_repo["submission"])
    payload["quantiles"][2]["p"] = 0.2
    rewrite_and_commit(submission_repo, payload, "Change quantile grid")

    with caplog.at_level(logging.WARNING, logger=ingest.__name__):
        records = run_ingest(submission_repo)

    assert records == []
    assert "quantile probabilities must be exactly" in caplog.text


def test_invalid_submissions_do_not_block_valid_batch_member(
    submission_repo: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    valid = submission_repo["submission"]

    unknown = deepcopy(valid)
    unknown["dataPointId"] = "agency.fixture.unknown.2030_01.first_print"
    write_json(
        submission_repo["inbox_dir"] / "other" / "unknown.json",
        unknown,
    )

    late = deepcopy(valid)
    late["generatedAtUtc"] = "2030-02-02T12:00:00Z"
    write_json(
        submission_repo["inbox_dir"] / "other" / "late.json",
        late,
    )

    non_monotone = deepcopy(valid)
    non_monotone["quantiles"][4]["value"] = non_monotone["quantiles"][3]["value"]
    write_json(
        submission_repo["inbox_dir"] / "other" / "non-monotone.json",
        non_monotone,
    )
    commit_all(submission_repo["repo"], "Add invalid batch members")

    with caplog.at_level(logging.WARNING, logger=ingest.__name__):
        records = run_ingest(submission_repo)

    assert [record["forecastSlug"] for record in records] == [
        "fixture-rate-january-2030"
    ]
    assert caplog.text.count("Skipping challenge submission") == 3
    assert "unregistered dataPointId" in caplog.text
    assert "does not precede release" in caplog.text
    assert "strictly increasing" in caplog.text


def test_timestamp_normalization_overflow_does_not_block_valid_sibling(
    submission_repo: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    overflow = deepcopy(submission_repo["submission"])
    overflow["generatedAtUtc"] = "0001-01-01T00:00:00+23:59"
    write_json(
        submission_repo["inbox_dir"] / "other" / "overflow.json",
        overflow,
    )
    commit_all(submission_repo["repo"], "Add overflowing timestamp")

    with caplog.at_level(logging.WARNING, logger=ingest.__name__):
        records = run_ingest(submission_repo)

    assert [record["forecastSlug"] for record in records] == [
        "fixture-rate-january-2030"
    ]
    assert "outside the supported UTC datetime range" in caplog.text


def test_recorder_projection_appends_challenges_without_reshaping_models() -> None:
    recorded = [
        {
            "kind": "prediction_recorded",
            "forecastSlug": "model-forecast",
            "pointEstimate": 4.2,
            "interval80": {"lower": 4.0, "upper": 4.4},
            "resolutionDate": "2030-02-01",
            "recordedAt": "2030-01-01T00:00:00Z",
            "agent": "thesis.analyst",
        }
    ]
    challenge = [
        {
            "forecastSlug": "model-forecast",
            "forecasterId": "github:fixture::Fixture Forecaster",
            "quantiles": [{"p": 0.05, "value": 3.9}],
            "provenance": {
                "submissionPath": "challenge/inbox/fixture/cell.json",
                "mergeCommit": "a" * 40,
                "schemaVersion": "thesis_challenge_submission_v1",
            },
        }
    ]

    predictions = build_snapshot_predictions(recorded, challenge)

    assert predictions[0] == {
        "forecastSlug": "model-forecast",
        "pointEstimate": 4.2,
        "interval80": {"lower": 4.0, "upper": 4.4},
        "resolutionDate": "2030-02-01",
        "recordedAt": "2030-01-01T00:00:00Z",
    }
    assert predictions[1] == challenge[0]
    assert len(predictions) == len(recorded) + len(challenge)


def test_recorder_workflow_wires_challenge_inputs() -> None:
    workflow = (ROOT / ".github/workflows/record-forecasts.yml").read_text()

    assert "--challenge-inbox challenge/inbox" in workflow
    assert "--target-registrations records/targets" in workflow


def test_expired_ratcheted_registration_refuses_challenge_rows(
    submission_repo: dict[str, Any],
) -> None:
    # Review of the ONS expiry ratchet: the challenge adapter accepted
    # any registered target with a pre-release timestamp, so a
    # post-grace submission could still be recorded for a terminally
    # expired id (the recorder commits without the site suite). The
    # adapter now consults the shared ratchet file itself.
    fixture = submission_repo
    expired_target = {
        "schemaVersion": "thesis_target_registration_v3",
        "registeredAtUtc": "2029-12-01T00:00:00Z",
        "targets": [
            {
                "catalogSlug": "fixture-expired-december-2029",
                "country": "US",
                "dataPointId": "agency.fixture.expired.2029_12.first_print",
                "period": "2029-12",
                "series": "agency.fixture.expired",
                "sourceBinding": {
                    "adapter": "fixture",
                    "expectedReleaseWindow": {
                        "start": "2030-02-01",
                        "end": "2030-02-01",
                    },
                },
                "unit": "percent",
                "valueScale": 1,
            }
        ],
    }
    write_json(
        fixture["targets_dir"] / "2029-12-01-fixture-expired.json", expired_target
    )
    expired_submission = dict(fixture["submission"])
    expired_submission["dataPointId"] = "agency.fixture.expired.2029_12.first_print"
    write_json(
        fixture["inbox_dir"] / "fixture-user" / "expired-rate.json",
        expired_submission,
    )
    fixture["head"] = commit_all(fixture["repo"], "Add expired-target submission")

    records = run_ingest(fixture)

    # The expired id is refused; the healthy sibling still lands.
    ids = [record["dataPointId"] for record in records]
    assert "agency.fixture.expired.2029_12.first_print" not in ids
    assert "agency.fixture.rate.2030_01.first_print" in ids


def test_missing_ratchet_file_fails_closed(
    submission_repo: dict[str, Any],
) -> None:
    fixture = submission_repo
    ratchet = (
        fixture["repo"]
        / "site"
        / "src"
        / "data"
        / "expired-unforecast-registrations.ts"
    )
    ratchet.unlink()
    fixture["head"] = commit_all(fixture["repo"], "Drop the ratchet file")
    # Without the ratchet the adapter cannot prove any id is admissible;
    # the whole ingest aborts loudly rather than admitting rows.
    with pytest.raises(ingest.ChallengeSubmissionError, match="cannot read"):
        run_ingest(fixture)


def test_quoted_comments_do_not_expire_ids(
    submission_repo: dict[str, Any],
) -> None:
    ratchet = (
        submission_repo["repo"]
        / "site"
        / "src"
        / "data"
        / "expired-unforecast-registrations.ts"
    )
    ratchet.write_text(
        "export const EXPIRED_UNFORECAST_REGISTRATIONS = [\n"
        '  // replacement is "agency.fixture.rate.2030_01.first_print"\n'
        '  "agency.fixture.expired.2029_12.first_print",\n'
        "] as const;\n"
    )
    submission_repo["head"] = commit_all(
        submission_repo["repo"], "Quoted comment in ratchet"
    )
    records = run_ingest(submission_repo)
    # The commented id is NOT expired; the healthy submission still lands.
    assert [r["dataPointId"] for r in records] == [
        "agency.fixture.rate.2030_01.first_print"
    ]


def test_comment_only_ratchet_array_fails_closed(
    submission_repo: dict[str, Any],
) -> None:
    ratchet = (
        submission_repo["repo"]
        / "site"
        / "src"
        / "data"
        / "expired-unforecast-registrations.ts"
    )
    ratchet.write_text(
        "export const EXPIRED_UNFORECAST_REGISTRATIONS = [\n"
        '  // only prose here, including a quoted "not.an.entry"\n'
        "] as const;\n"
    )
    submission_repo["head"] = commit_all(
        submission_repo["repo"], "Comment-only ratchet"
    )
    with pytest.raises(ingest.ChallengeSubmissionError, match="empty expired set"):
        run_ingest(submission_repo)


def test_partially_malformed_ratchet_array_fails_closed(
    submission_repo: dict[str, Any],
) -> None:
    ratchet = (
        submission_repo["repo"]
        / "site"
        / "src"
        / "data"
        / "expired-unforecast-registrations.ts"
    )
    ratchet.write_text(
        "export const EXPIRED_UNFORECAST_REGISTRATIONS = [\n"
        '  "agency.fixture.expired.2029_12.first_print",\n'
        '  "agency.fixture.silently-dropped.2029_12.first_print"\n'
        "] as const;\n"
    )
    submission_repo["head"] = commit_all(
        submission_repo["repo"], "Partially malformed ratchet"
    )
    with pytest.raises(ingest.ChallengeSubmissionError, match="invalid expired entry"):
        run_ingest(submission_repo)


def test_expired_list_refuses_escape_spelled_entries(tmp_path: pathlib.Path) -> None:
    # The 2026-08-14 review reproduction: this parser reads raw characters
    # while the TypeScript runtime decodes string escapes, so an entry
    # spelled "fixture…" means one id to the site and a different
    # literal to Python — a terminal candidate slipped the roll's seed
    # guard. Any entry that is not plain unescaped id text refuses.
    site_data = tmp_path / "site" / "src" / "data"
    site_data.mkdir(parents=True)
    escaped = "\\u0066ixture.seed.expired.2026_07.first_print"
    (site_data / "expired-unforecast-registrations.ts").write_text(
        "export const EXPIRED_UNFORECAST_REGISTRATIONS = [\n"
        f'  "{escaped}",\n'
        "] as const;\n"
    )
    with pytest.raises(
        ingest.ChallengeSubmissionError, match="not plain unescaped id text"
    ):
        ingest.expired_unforecast_registrations(tmp_path)


def test_expired_list_admits_the_uppercase_ppi_id_lineage(
    tmp_path: pathlib.Path,
) -> None:
    # bls.wp.WPSFD4.<period>.first_print is a real registered id shape
    # (records/targets/2026-07-25-7753f0f1…), and the non-native roll
    # path preserves the stem for successors — a lowercase-only
    # allowlist would wedge both the ingest and the roll if that
    # lineage ever needed the terminal ratchet.
    site_data = tmp_path / "site" / "src" / "data"
    site_data.mkdir(parents=True)
    (site_data / "expired-unforecast-registrations.ts").write_text(
        "export const EXPIRED_UNFORECAST_REGISTRATIONS = [\n"
        '  "bls.wp.WPSFD4.2026-08.first_print",\n'
        "] as const;\n"
    )
    assert ingest.expired_unforecast_registrations(tmp_path) == frozenset(
        {"bls.wp.WPSFD4.2026-08.first_print"}
    )


def merge_no_ff(repo: pathlib.Path, branch: str, message: str) -> None:
    git(
        repo,
        "-c",
        "user.name=Challenge Adapter Test",
        "-c",
        "user.email=challenge-adapter@example.com",
        "-c",
        "commit.gpgsign=false",
        "merge",
        "--no-ff",
        "-q",
        "-m",
        message,
        branch,
    )


def challengers_of(records: list[dict[str, Any]]) -> list[str]:
    return sorted(record["challenger"] for record in records)


def payload_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def _replace_point_estimate(payload: dict[str, Any], literal: bytes) -> bytes:
    raw = payload_bytes(payload)
    marker = b'"pointEstimate": ' + json.dumps(payload["pointEstimate"]).encode()
    assert raw.count(marker) == 1
    return raw.replace(marker, b'"pointEstimate": ' + literal)


def _with(**changes: Any) -> Callable[[dict[str, Any]], bytes]:
    return lambda payload: payload_bytes({**payload, **changes})


def _nested(payload: dict[str, Any]) -> bytes:
    raw = payload_bytes(payload)
    assert raw.endswith(b"}\n")
    return raw[:-2] + b', "x": ' + b"[" * 100_000 + b"]" * 100_000 + b"}\n"


# Every way a first shot can parse (or nearly parse) yet fail the
# intake's content-intrinsic checks. The 2026-09-24 adversarial review
# (verify-s4-thesis oneshot_probe) found the history walk canonicalized
# the first PARSEABLE file for a key, so any of these merged first
# locked the challenger out of the target forever. The encoding rows are
# the parse-path split the same review flagged: json.loads(bytes)
# auto-detects UTF-16 and strips a UTF-8 BOM, while the adapter's text
# read refused both. The last two rows aborted the whole batch instead:
# pathological nesting raised RecursionError in the walk, and an integer
# past CPython's 4300-digit limit raised a bare ValueError that neither
# parse path caught.
FIRST_SHOT_DEFECTS: dict[str, Callable[[dict[str, Any]], bytes]] = {
    "non-monotone quantiles": lambda payload: payload_bytes(
        {
            **payload,
            "quantiles": [
                *payload["quantiles"][:3],
                {"p": 0.5, "value": payload["quantiles"][2]["value"]},
                *payload["quantiles"][4:],
            ],
        }
    ),
    "misordered probability grid": lambda payload: payload_bytes(
        {**payload, "quantiles": list(reversed(payload["quantiles"]))}
    ),
    "ciLow off the 0.1 rung": _with(ciLow=2.75),
    "missing systemName": lambda payload: payload_bytes(
        {key: value for key, value in payload.items() if key != "systemName"}
    ),
    "unknown systemType": _with(systemType="oracle"),
    "offset-less generatedAtUtc": _with(generatedAtUtc="2030-01-31T12:00:00"),
    "non-string notes": _with(notes=["not", "a", "string"]),
    "stale schemaVersion": _with(schemaVersion="thesis_challenge_submission_v0"),
    "non-finite pointEstimate": lambda payload: _replace_point_estimate(
        payload, b"1e400"
    ),
    "UTF-16 encoding": lambda payload: json.dumps(payload, indent=2).encode("utf-16"),
    "UTF-8 byte-order mark": lambda payload: b"\xef\xbb\xbf" + payload_bytes(payload),
    "pathological nesting": _nested,
    "integer past the digit limit": lambda payload: _replace_point_estimate(
        payload, b"1" + b"0" * 5000
    ),
}


@pytest.mark.parametrize("defect", sorted(FIRST_SHOT_DEFECTS))
def test_content_invalid_first_shot_does_not_lock_out_the_fix(
    submission_repo: dict[str, Any],
    defect: str,
) -> None:
    # A first shot the intake refuses on its bytes was never an accepted
    # forecast, so the corrected file is the challenger's one shot — and
    # it then locks exactly like any other first-accepted content.
    repo = submission_repo["repo"]
    path = submission_repo["inbox_dir"] / "fix-user" / "fixture-rate.json"
    fixed = {**submission_repo["submission"], "challenger": "github:fix-user"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(FIRST_SHOT_DEFECTS[defect](fixed))
    commit_all(repo, f"Add a submission with {defect}")
    assert challengers_of(run_ingest(submission_repo)) == ["github:fixture-user"]

    write_json(path, fixed)
    commit_all(repo, "Fix the submission in place")
    assert challengers_of(run_ingest(submission_repo)) == [
        "github:fix-user",
        "github:fixture-user",
    ]

    write_json(path, {**fixed, "pointEstimate": 3.1})
    commit_all(repo, "Rewrite after the first valid shot")
    assert challengers_of(run_ingest(submission_repo)) == ["github:fixture-user"]


@pytest.mark.parametrize("shape", ["rename", "delete-and-readd"])
def test_content_invalid_first_shot_fix_may_land_at_any_path(
    submission_repo: dict[str, Any],
    shape: str,
) -> None:
    repo = submission_repo["repo"]
    first = submission_repo["inbox_dir"] / "fix-user" / "fixture-rate.json"
    fixed = {**submission_repo["submission"], "challenger": "github:fix-user"}
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_bytes(FIRST_SHOT_DEFECTS["non-monotone quantiles"](fixed))
    commit_all(repo, "Add a non-monotone submission")

    first.unlink()
    if shape == "rename":
        second = first.with_name("fixed-rate.json")
    else:
        commit_all(repo, "Withdraw the non-monotone submission")
        second = first
    write_json(second, fixed)
    commit_all(repo, f"Re-submit via {shape}")

    records = run_ingest(submission_repo)
    assert challengers_of(records) == ["github:fix-user", "github:fixture-user"]
    fix_row = next(r for r in records if r["challenger"] == "github:fix-user")
    assert fix_row["provenance"]["submissionPath"] == (
        second.relative_to(repo).as_posix()
    )

    write_json(second, {**fixed, "pointEstimate": 3.1})
    commit_all(repo, "Rewrite after the first valid shot")
    assert challengers_of(run_ingest(submission_repo)) == ["github:fixture-user"]


def test_invalid_edit_between_valid_shots_does_not_reopen_the_target(
    submission_repo: dict[str, Any],
) -> None:
    # Skipping invalid content must not let an invalid interlude reset
    # the key: the first VALID content stays canonical, so a different
    # valid edit still rejects and restoring the original bytes revives it.
    original = submission_repo["submission_path"].read_bytes()
    broken = deepcopy(submission_repo["submission"])
    broken["quantiles"][3]["value"] = broken["quantiles"][2]["value"]
    rewrite_and_commit(submission_repo, broken, "Break the accepted submission")
    assert run_ingest(submission_repo) == []

    revised = {**submission_repo["submission"], "pointEstimate": 3.05}
    rewrite_and_commit(submission_repo, revised, "Re-submit a different forecast")
    assert run_ingest(submission_repo) == []

    submission_repo["submission_path"].write_bytes(original)
    commit_all(submission_repo["repo"], "Restore the first accepted bytes")
    records = run_ingest(submission_repo)
    assert challengers_of(records) == ["github:fixture-user"]
    assert records[0]["pointEstimate"] == 3.0


@pytest.mark.parametrize(
    "defect", ["pathological nesting", "integer past the digit limit"]
)
def test_unreadable_history_does_not_abort_the_batch(
    submission_repo: dict[str, Any],
    defect: str,
) -> None:
    # The history walk alone (the file is gone from the tree) must not
    # raise out of the recorder: RecursionError and the int-digit
    # ValueError both escaped the walk's JSONDecodeError-only guard.
    bad = submission_repo["inbox_dir"] / "fixture-user" / "hostile.json"
    bad.write_bytes(FIRST_SHOT_DEFECTS[defect](submission_repo["submission"]))
    commit_all(submission_repo["repo"], f"Add {defect}")
    bad.unlink()
    commit_all(submission_repo["repo"], f"Remove {defect}")

    records = run_ingest(submission_repo)
    assert challengers_of(records) == ["github:fixture-user"]


@pytest.mark.parametrize(
    "relative",
    [
        "josé/fixture-rate.json",
        'quote-user/q"uote.json',
        "slash-user/back\\slash.json",
    ],
)
def test_git_quoted_paths_still_bind_one_shot(
    submission_repo: dict[str, Any],
    relative: str,
) -> None:
    # git log quotes non-ASCII, '"' and '\\' paths ("jos\303\251...")
    # unless -z is used; the walk read the quoted form, which never ended
    # in .json, so such files never became canonical and every later
    # edit was accepted — one shot failed open.
    repo = submission_repo["repo"]
    path = submission_repo["inbox_dir"] / relative
    payload = {**submission_repo["submission"], "challenger": "github:quoted-user"}
    write_json(path, payload)
    commit_all(repo, "Add a submission at a quoted path")
    records = run_ingest(submission_repo)
    assert challengers_of(records) == ["github:fixture-user", "github:quoted-user"]

    write_json(path, {**payload, "pointEstimate": 3.1})
    commit_all(repo, "Edit the quoted-path submission")
    assert challengers_of(run_ingest(submission_repo)) == ["github:fixture-user"]


@pytest.mark.parametrize(
    "stray", ["fix-user/drafts/fixture-rate.json", "fixture-rate.json"]
)
def test_paths_the_intake_never_reads_do_not_define_canonical_content(
    submission_repo: dict[str, Any],
    stray: str,
) -> None:
    # The intake reads exactly inbox/<dir>/<name>.json; a draft nested
    # deeper (or dropped at the inbox root) is never ingested, so it was
    # never an accepted forecast and must not pre-empt the real shot.
    repo = submission_repo["repo"]
    draft = {**submission_repo["submission"], "challenger": "github:fix-user"}
    write_json(submission_repo["inbox_dir"] / stray, draft)
    commit_all(repo, "Add a stray draft the intake never reads")
    assert challengers_of(run_ingest(submission_repo)) == ["github:fixture-user"]

    shot = {**draft, "pointEstimate": 3.1}
    write_json(submission_repo["inbox_dir"] / "fix-user" / "fixture-rate.json", shot)
    commit_all(repo, "Submit the real shot")
    records = run_ingest(submission_repo)
    assert challengers_of(records) == ["github:fix-user", "github:fixture-user"]
    fix_row = next(r for r in records if r["challenger"] == "github:fix-user")
    assert fix_row["pointEstimate"] == 3.1


def test_repo_root_below_the_git_toplevel_keeps_one_shot(
    submission_repo: dict[str, Any],
) -> None:
    # git log prints paths relative to the toplevel, while provenance
    # paths are relative to repo_root; with repo_root one level down the
    # first-accepted PATH never matched a record, so a byte-identical
    # surplus copy that sorts first displaced the original.
    repo = submission_repo["repo"]
    outer = repo.parent
    (repo / ".git").rename(outer / ".git")
    commit_all(outer, "Move the project one level below the toplevel")
    copy = submission_repo["inbox_dir"] / "fixture-user" / "a-copy.json"
    copy.write_bytes(submission_repo["submission_path"].read_bytes())
    commit_all(outer, "Add a byte-identical surplus copy")

    records = run_ingest(submission_repo)
    assert [r["provenance"]["submissionPath"] for r in records] == [
        "challenge/inbox/fixture-user/fixture-rate.json"
    ]

    edited = {**submission_repo["submission"], "pointEstimate": 3.1}
    write_json(submission_repo["submission_path"], edited)
    copy.unlink()
    commit_all(outer, "Edit below the toplevel")
    assert run_ingest(submission_repo) == []


@pytest.mark.parametrize(
    "raw",
    [
        b"\xef\xbb\xbf{}",
        "{}".encode("utf-16"),
        b'{"a": "\xff"}',
        b"[" * 100_000 + b"]" * 100_000,
        b'{"n": 1' + b"0" * 5000 + b"}",
        b"{",
    ],
    ids=["bom", "utf-16", "invalid-utf-8", "nesting", "digit-limit", "truncated"],
)
def test_parse_submission_bytes_refuses_unreadable_json(raw: bytes) -> None:
    with pytest.raises(ingest.ChallengeSubmissionError, match="not readable JSON"):
        ingest.parse_submission_bytes(raw)


def test_validate_submission_content_ignores_repository_state() -> None:
    # Registration and release checks are state-dependent and stay in
    # adapt_submission; content validity is a pure function of the bytes.
    payload = model_payload("github:Alice", "valid")
    unregistered_late = {
        **payload,
        "dataPointId": MODEL_UNREGISTERED,
        "generatedAtUtc": "2099-01-01T00:00:00+00:00",
    }
    content = ingest.validate_submission_content(unregistered_late)
    assert content.key == ("github:alice", MODEL_UNREGISTERED)
    with pytest.raises(ingest.ChallengeSubmissionError, match="strictly increasing"):
        ingest.validate_submission_content(model_payload("github:Alice", "bad"))


# Reference model for the one-shot ledger. It restates the contract
# independently of the implementation: per (challenger.lower(),
# dataPointId), the canonical content is the first content-intrinsically
# valid bytes to land on the first-parent chain at a path the intake
# reads; the accepted set is every current file holding its key's
# canonical bytes that also passes the state checks (registration,
# release), one per key — the first-accepted path if present, else the
# lexicographically first. Contents are pure functions of
# (challenger, kind) so later writes reproduce earlier bytes exactly.
MODEL_TARGET = "agency.fixture.rate.2030_01.first_print"
MODEL_UNREGISTERED = "agency.fixture.missing.2030_01.first_print"
# kind -> (valid on its bytes alone, also passes the state checks)
MODEL_KINDS: dict[str, tuple[bool, bool]] = {
    "valid": (True, True),
    "revised": (True, True),
    "post-release": (True, False),
    "unregistered": (True, False),
    "bad": (False, False),
    "unparseable": (False, False),
}
MODEL_CHALLENGERS = ("github:alice", "github:Alice", "github:bob")
# Inbox-relative paths: the non-ASCII name exercises git's quoted path
# output, and the nested draft and the sidecar are shapes the intake
# glob never reads.
MODEL_PATHS = (
    "alice/a.json",
    "alice/b.json",
    "bob/a.json",
    "bob/josé.json",
    "alice/drafts/c.json",
    "alice/a.sigstore.json",
)


def model_payload(challenger: str, kind: str) -> dict[str, Any]:
    quantiles = [
        {"p": p, "value": value}
        for p, value in zip(
            (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95),
            (2.7, 2.8, 2.9, 3.0, 3.1, 3.2, 3.3),
        )
    ]
    payload: dict[str, Any] = {
        "schemaVersion": "thesis_challenge_submission_v1",
        "challenger": challenger,
        "systemType": "ai",
        "systemName": "Model Forecaster",
        "dataPointId": MODEL_TARGET,
        "pointEstimate": 3.0,
        "ciLow": 2.8,
        "ciHigh": 3.2,
        "quantiles": quantiles,
        "generatedAtUtc": "2030-01-31T12:00:00Z",
    }
    if kind == "revised":
        payload["pointEstimate"] = 3.05
    elif kind == "post-release":
        payload["generatedAtUtc"] = "2030-02-01T00:00:00Z"
    elif kind == "unregistered":
        payload["dataPointId"] = MODEL_UNREGISTERED
    elif kind == "bad":
        quantiles[3]["value"] = quantiles[2]["value"]
    return payload


def model_content(challenger: str, kind: str) -> bytes:
    if kind == "unparseable":
        return b"{ not json\n"
    return payload_bytes(model_payload(challenger, kind))


def model_reads(relative: str) -> bool:
    parts = pathlib.PurePosixPath(relative).parts
    return (
        len(parts) == 2
        and relative.endswith(".json")
        and not relative.endswith(".sigstore.json")
    )


class OneShotLedgerMachine(RuleBasedStateMachine):
    """Drive real git histories and diff the intake against the model."""

    def __init__(self) -> None:
        super().__init__()
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="one-shot-model-"))
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "--quiet")
        self.targets_dir = self.repo / "records" / "targets"
        self.inbox = self.repo / "challenge" / "inbox"
        write_json(
            self.targets_dir / "2030-01-01-fixture.json",
            {
                "schemaVersion": "thesis_target_registration_v3",
                "registeredAtUtc": "2030-01-01T00:00:00Z",
                "targets": [
                    {
                        "catalogSlug": "fixture-rate-january-2030",
                        "dataPointId": MODEL_TARGET,
                        "sourceBinding": {
                            "expectedReleaseWindow": {
                                "start": "2030-02-01",
                                "end": "2030-02-01",
                            },
                        },
                    }
                ],
            },
        )
        ratchet = self.repo / ingest.EXPIRED_REGISTRATIONS_TS
        ratchet.parent.mkdir(parents=True, exist_ok=True)
        ratchet.write_text(
            "export const EXPIRED_UNFORECAST_REGISTRATIONS = [\n"
            '  "agency.fixture.expired.2029_12.first_print",\n'
            "] as const;\n"
        )
        # A tracked non-submission keeps the inbox directory alive
        # across branch switches that empty it.
        self.inbox.mkdir(parents=True)
        (self.inbox / "README.md").write_text("inbox\n")
        commit_all(self.repo, "Registry, ratchet and empty inbox")
        self.tree: dict[str, bytes] = {}
        self.specs: dict[bytes, tuple[str, str]] = {}
        self.canonical: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.side_branches = 0

    def teardown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _content(self, challenger: str, kind: str) -> bytes:
        content = model_content(challenger, kind)
        self.specs.setdefault(content, (challenger, kind))
        return content

    def _put(self, relative: str, content: bytes) -> None:
        path = self.inbox / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _land(self, tree: dict[str, bytes]) -> None:
        # Every rule changes at most one path's bytes per mainline
        # commit, so within-commit ordering never decides canonicity.
        for relative in sorted(tree):
            content = tree[relative]
            if self.tree.get(relative) == content or not model_reads(relative):
                continue
            spec = self.specs.get(content)
            if spec is None or not MODEL_KINDS[spec[1]][0]:
                continue
            key = (spec[0].lower(), model_payload(*spec)["dataPointId"])
            self.canonical.setdefault(key, (content, f"challenge/inbox/{relative}"))
        self.tree = tree

    def _commit(self, message: str, tree: dict[str, bytes]) -> None:
        if tree == self.tree:
            return
        commit_all(self.repo, message)
        self._land(tree)

    def _existing(self, data: st.DataObject) -> str:
        return data.draw(st.sampled_from(sorted(self.tree)))

    @rule(
        path=st.sampled_from(MODEL_PATHS),
        challenger=st.sampled_from(MODEL_CHALLENGERS),
        kind=st.sampled_from(sorted(MODEL_KINDS)),
    )
    def write(self, path: str, challenger: str, kind: str) -> None:
        """Add, edit, or re-add one file in a direct mainline commit."""
        content = self._content(challenger, kind)
        self._put(path, content)
        self._commit(f"Write {path}", {**self.tree, path: content})

    @precondition(lambda self: bool(self.tree))
    @rule(data=st.data())
    def delete(self, data: st.DataObject) -> None:
        path = self._existing(data)
        (self.inbox / path).unlink()
        self._commit(
            f"Delete {path}", {k: v for k, v in self.tree.items() if k != path}
        )

    @precondition(lambda self: bool(self.tree))
    @rule(
        data=st.data(),
        destination=st.sampled_from(MODEL_PATHS),
        edit=st.none()
        | st.tuples(
            st.sampled_from(MODEL_CHALLENGERS), st.sampled_from(sorted(MODEL_KINDS))
        ),
    )
    def move(
        self,
        data: st.DataObject,
        destination: str,
        edit: tuple[str, str] | None,
    ) -> None:
        """Rename, optionally rewriting the content in the same commit."""
        source = self._existing(data)
        if source == destination:
            return
        content = self.tree[source] if edit is None else self._content(*edit)
        (self.inbox / source).unlink()
        self._put(destination, content)
        tree = {k: v for k, v in self.tree.items() if k != source}
        self._commit(f"Move {source} to {destination}", {**tree, destination: content})

    @precondition(lambda self: bool(self.tree))
    @rule(data=st.data(), destination=st.sampled_from(MODEL_PATHS))
    def copy(self, data: st.DataObject, destination: str) -> None:
        source = self._existing(data)
        content = self.tree[source]
        self._put(destination, content)
        self._commit(
            f"Copy {source} to {destination}", {**self.tree, destination: content}
        )

    @rule(
        path=st.sampled_from(MODEL_PATHS),
        challenger=st.sampled_from(MODEL_CHALLENGERS),
        kind=st.sampled_from(sorted(MODEL_KINDS)),
    )
    def merge_write(self, path: str, challenger: str, kind: str) -> None:
        """Land a write through a --no-ff merge of a side branch."""
        content = self._content(challenger, kind)
        if self.tree.get(path) == content:
            return
        mainline = git(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        self.side_branches += 1
        side = f"side-{self.side_branches}"
        git(self.repo, "checkout", "-q", "-b", side)
        self._put(path, content)
        commit_all(self.repo, f"Side-branch write of {path}")
        git(self.repo, "checkout", "-q", mainline)
        merge_no_ff(self.repo, side, f"Accept {side}")
        self._land({**self.tree, path: content})

    def _expected(self) -> list[str]:
        survivors: dict[tuple[str, str], list[str]] = {}
        for relative, content in self.tree.items():
            spec = self.specs.get(content)
            if not model_reads(relative) or spec is None:
                continue
            if not all(MODEL_KINDS[spec[1]]):
                continue
            key = (spec[0].lower(), model_payload(*spec)["dataPointId"])
            if self.canonical[key][0] == content:
                survivors.setdefault(key, []).append(f"challenge/inbox/{relative}")
        return sorted(
            self.canonical[key][1] if self.canonical[key][1] in paths else min(paths)
            for key, paths in survivors.items()
        )

    @invariant()
    def intake_matches_model(self) -> None:
        records = ingest.ingest_challenge_submissions(
            inbox_dir=self.inbox,
            targets_dir=self.targets_dir,
            repo_root=self.repo,
        )
        accepted = [record["provenance"]["submissionPath"] for record in records]
        assert accepted == self._expected()


def test_one_shot_ledger_matches_the_reference_model() -> None:
    # Stateful fuzzing over real git repositories: adds, edits, renames
    # (with and without rewrites), deletes, re-adds, surplus copies,
    # merge-borne writes, case-variant challengers, invalid and
    # unparseable shots. Before the 2026-09-24 fix it shrank to an
    # invalid first shot followed by its correction.
    run_state_machine_as_test(
        OneShotLedgerMachine,
        settings=settings(
            max_examples=50,
            stateful_step_count=8,
            deadline=None,
            database=None,
            print_blob=True,
            suppress_health_check=[HealthCheck.too_slow],
        ),
    )
