from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import prospect_targets  # noqa: E402
import register_targets  # noqa: E402
from canonical_json import canonical_bytes  # noqa: E402

TODAY = dt.date(2030, 1, 10)


@pytest.fixture
def resolver_admits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the resolver's verdict for tests that use a fictional series.

    No resolver leg executes a fixture series, so the execution-plan gate
    would refuse it before the mechanics under test run. The gate is tested
    against the real resolver in tests/test_execution_plan_gate.py.
    """

    monkeypatch.setattr(
        prospect_targets, "execution_plan_refusal", lambda registration: None
    )


def empty_state(**overrides) -> prospect_targets.ValidationState:
    values = {
        "registry_series": frozenset(),
        "catalog_slugs": frozenset(),
        "denied": frozenset(),
        **overrides,
    }
    return prospect_targets.ValidationState(**values)


def codex_target(**overrides) -> dict:
    return {
        "series": "agency.test.rate",
        "period": "2030-01",
        "catalogSlug": "agency-test-rate-january-2030",
        "country": "US",
        "targetUnit": "percent",
        "expectedReleaseDate": "2030-01-20",
        "resolutionSourceUrl": "https://data.example.gov/releases/rate",
        "sourceSeriesId": "RATE",
        "sourceField": "rate",
        "sourceTable": "Agency rate table",
        "transform": {"operation": "identity", "factor": 1},
        **overrides,
    }


def ledger_gap_target(**overrides) -> dict:
    source_url = "https://data.example.gov/releases/rate"
    return {
        "series": "agency.ledger.rate",
        "period": "2030-01",
        "catalogSlug": "agency-ledger-rate-january-2030",
        "country": "US",
        "targetUnit": "percent",
        "resolutionSourceUrl": source_url,
        "previousTarget": {
            "period": "2029-12",
            "dataPointId": "agency.ledger.rate.2029_12.first_print",
            "country": "US",
            "unit": "percent",
            "resolutionDate": "2029-12-20",
            "resolutionSource": "Agency rate table",
            "resolutionSourceUrl": source_url,
            "sourceBinding": {
                "adapter": "generic-url",
                "sourceUrl": source_url,
                "sourceSeriesId": "RATE",
                "field": "rate",
                "table": "Agency rate table",
                "transform": {"operation": "identity", "factor": 1},
                "releasePolicy": "first_print",
            },
        },
        **overrides,
    }


def envelope(*entries: tuple[str, dict]) -> dict:
    return {
        "schemaVersion": prospect_targets.PROPOSAL_SCHEMA,
        "proposals": [
            {"origin": origin, "target": target} for origin, target in entries
        ],
    }


def validate(payload: dict, tmp_path: pathlib.Path, **kwargs):
    return prospect_targets.validate_proposals(
        payload,
        today=TODAY,
        root=tmp_path,
        state=kwargs.pop("state", empty_state()),
        strict=kwargs.pop("strict", True),
        **kwargs,
    )


@pytest.mark.usefixtures("resolver_admits")
def test_valid_origins_replay_to_batch_targets(tmp_path: pathlib.Path) -> None:
    codex = codex_target()
    ledger = ledger_gap_target()

    replayed, targets = validate(
        envelope(("ledger_gap", ledger), ("codex", codex)), tmp_path
    )

    assert [row["target"]["catalogSlug"] for row in replayed["proposals"]] == [
        ledger["catalogSlug"],
        codex["catalogSlug"],
    ]
    assert targets == {"targets": [ledger, codex]}


def test_empty_proposal_set_is_a_canonical_noop(tmp_path: pathlib.Path) -> None:
    payload = envelope()

    replayed, targets = validate(payload, tmp_path)

    assert replayed == payload
    assert targets == {"targets": []}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"period": "2030-13"}, "bad period"),
        ({"country": "ZZ"}, "bad country"),
        ({"targetUnit": "bananas"}, "bad unit"),
        (
            {"resolutionSourceUrl": "http://data.example.gov/rate"},
            "bad resolution source URL",
        ),
        ({"resolutionSourceUrl": "https://localhost/rate"}, "non-public"),
        ({"expectedReleaseDate": "2030-01-10"}, "release outside"),
        ({"expectedReleaseDate": "2030-03-27"}, "release outside"),
        ({"sourceField": ""}, "missing sourceField"),
        (
            {"transform": {"operation": "identity", "factor": True}},
            "bad transform factor",
        ),
        (
            {"transform": {"operation": "identity", "factor": float("inf")}},
            "bad transform factor",
        ),
    ],
)
def test_strict_validation_rejects_bad_target_fields(
    tmp_path: pathlib.Path, change: dict, message: str
) -> None:
    with pytest.raises(prospect_targets.ProspectValidationError, match=message):
        validate(envelope(("codex", codex_target(**change))), tmp_path)


def test_registration_owned_fields_are_forbidden(tmp_path: pathlib.Path) -> None:
    target = codex_target()
    target["dataPointId"] = "attacker.controls.grading"

    with pytest.raises(
        prospect_targets.ProspectValidationError,
        match="registration-owned fields are forbidden",
    ):
        validate(envelope(("codex", target)), tmp_path)


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (
            empty_state(registry_series=frozenset({"agency.test.rate"})),
            "series already in registry",
        ),
        (
            empty_state(
                catalog_slugs=frozenset({"agency-test-rate-january-2030"})
            ),
            "slug exists",
        ),
        (
            empty_state(denied=frozenset({("agency.test.rate", "2030-01")})),
            "target is denylisted",
        ),
    ],
)
def test_trusted_state_rejects_registry_catalog_and_denylist(
    tmp_path: pathlib.Path,
    state: prospect_targets.ValidationState,
    message: str,
) -> None:
    with pytest.raises(prospect_targets.ProspectValidationError, match=message):
        validate(envelope(("codex", codex_target())), tmp_path, state=state)


def test_local_catalog_loader_includes_json_quoted_generated_slugs(
    tmp_path: pathlib.Path,
) -> None:
    scripts = tmp_path / "scripts"
    examples = tmp_path / "site/src/data/forecast-examples"
    scripts.mkdir()
    examples.mkdir(parents=True)
    (scripts / "docket_series.json").write_text('{"series": []}\n')
    (scripts / "docket_denylist.json").write_text(
        '{"comment": "fixture", "targets": []}\n'
    )
    (tmp_path / "site/src/data/forecast-cells.ts").write_text(
        "export const cells = [];\n"
    )
    (examples / "generated.ts").write_text(
        'export const cells = [{"slug": "generated-catalog-slug"}];\n'
    )

    state = prospect_targets.load_validation_state(tmp_path)

    assert "generated-catalog-slug" in state.catalog_slugs


def test_codex_near_duplicate_is_rejected(tmp_path: pathlib.Path) -> None:
    state = empty_state(
        catalog_slugs=frozenset({"agency-test-rate-december-2029"})
    )

    with pytest.raises(
        prospect_targets.ProspectValidationError, match="same quantity as existing"
    ):
        validate(envelope(("codex", codex_target())), tmp_path, state=state)


@pytest.mark.usefixtures("resolver_admits")
def test_duplicate_proposals_fail_strict_replay_and_filter_to_one(
    tmp_path: pathlib.Path,
) -> None:
    payload = envelope(("codex", codex_target()), ("codex", codex_target()))

    with pytest.raises(prospect_targets.ProspectValidationError, match="slug exists"):
        validate(payload, tmp_path)

    filtered, targets = validate(payload, tmp_path, strict=False)
    assert len(filtered["proposals"]) == 1
    assert len(targets["targets"]) == 1


def test_noncanonical_artifact_is_rejected(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "proposals.json"
    path.write_text(json.dumps(envelope(("codex", codex_target())), indent=2))

    with pytest.raises(prospect_targets.ProspectValidationError, match="not canonical"):
        prospect_targets.load_envelope(path)


def git(repo: pathlib.Path, *args: str, env: dict | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )


def committed_registration(
    root: pathlib.Path,
    *,
    commit_lag: dt.timedelta,
    schema: str = register_targets.REGISTRATION_SCHEMA,
) -> dict:
    root.mkdir()
    git(root, "init")
    (root / "README.md").write_text("base\n")
    git(root, "add", "README.md")
    git(
        root,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "base",
    )
    target = codex_target()
    contract = register_targets.build_contract(target, TODAY)
    registered = dt.datetime(2030, 1, 10, 12, tzinfo=dt.timezone.utc)
    registered_at = registered.isoformat().replace("+00:00", "Z")
    snapshot = {
        "schemaVersion": schema,
        "registeredAtUtc": registered_at,
        "targets": [contract],
    }
    if schema == register_targets.REGISTRATION_SCHEMA:
        snapshot["ledgerPin"] = {
            "repo": "example/ledger",
            "branch": "main",
            "sha": "a" * 40,
            "jsonlSha256": "b" * 64,
            "lineCount": 1,
        }
    content_hash = register_targets.registration_content_hash(snapshot)
    relative = pathlib.Path("records/targets") / f"2030-01-10-{content_hash}.json"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(canonical_bytes(snapshot) + b"\n")
    git(root, "add", relative.as_posix())
    committed_at = (registered + commit_lag).isoformat()
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": committed_at,
        "GIT_COMMITTER_DATE": committed_at,
    }
    git(
        root,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-m",
        "register",
        env=env,
    )
    return target


def test_exact_contemporaneous_v3_registration_is_retryable(
    tmp_path: pathlib.Path,
) -> None:
    root = tmp_path / "repo"
    target = committed_registration(root, commit_lag=dt.timedelta(minutes=1))

    _, targets = prospect_targets.validate_proposals(
        envelope(("codex", target)),
        today=TODAY,
        root=root,
        state=empty_state(),
        strict=True,
    )

    assert targets == {"targets": [target]}


def test_pre_v3_registration_is_not_retryable(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "repo"
    target = committed_registration(
        root,
        commit_lag=dt.timedelta(minutes=1),
        schema=register_targets.V2_REGISTRATION_SCHEMA,
    )
    payload = envelope(("codex", target))

    with pytest.raises(
        prospect_targets.ProspectValidationError, match="not retryable"
    ):
        prospect_targets.validate_proposals(
            payload,
            today=TODAY,
            root=root,
            state=empty_state(),
            strict=True,
        )

    filtered, targets = prospect_targets.validate_proposals(
        payload,
        today=TODAY,
        root=root,
        state=empty_state(),
        strict=False,
    )
    assert filtered["proposals"] == []
    assert targets == {"targets": []}


def test_legacy_chronology_invalid_registration_is_filtered_not_grandfathered(
    tmp_path: pathlib.Path,
) -> None:
    root = tmp_path / "repo"
    target = committed_registration(root, commit_lag=dt.timedelta(minutes=19))
    payload = envelope(("codex", target))

    with pytest.raises(
        prospect_targets.ProspectValidationError, match="not contemporaneous"
    ):
        prospect_targets.validate_proposals(
            payload,
            today=TODAY,
            root=root,
            state=empty_state(),
            strict=True,
        )

    filtered, targets = prospect_targets.validate_proposals(
        payload,
        today=TODAY,
        root=root,
        state=empty_state(),
        strict=False,
    )
    assert filtered["proposals"] == []
    assert targets == {"targets": []}
