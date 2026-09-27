from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import adopt_proven_series  # noqa: E402
import generate_ledger_targets  # noqa: E402
import generation_tickets  # noqa: E402
import register_targets  # noqa: E402
import register_wave  # noqa: E402
import run_thesis_analyst as analyst_runner  # noqa: E402
from canonical_json import canonical_bytes, canonical_sha256  # noqa: E402


@pytest.fixture
def resolver_admits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the resolver's verdict for tests about snapshot mechanics.

    These tests drive retry, bind, supersede and pair atomicity with a
    fictional series (or the deliberately unarmed Census SPM pair), which no
    resolver leg executes. The execution-plan gate has its own tests against
    the real resolver in tests/test_execution_plan_gate.py.
    """

    monkeypatch.setattr(
        register_targets, "execution_plan_refusal", lambda registration: None
    )


def _alfred_docket_entries() -> list[dict]:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    return [
        entry
        for entry in docket["series"]
        if (entry.get("extras") or {}).get("sourceBinding", {}).get("adapter")
        == "alfred-fred"
    ]


def sample_target() -> dict:
    return {
        "series": "agency.test.rate",
        "period": "2030-01",
        "catalogSlug": "agency-test-rate-january-2030",
        "targetUnit": "percent",
        "valueScale": 1,
        "previousTarget": {
            "period": "2029-12",
            "dataPointId": "agency.test.rate.2029_12.first_print",
            "country": "US",
            "unit": "percent",
            "resolutionDate": "2030-01-15",
            "resolutionSource": "Agency table A",
            "resolutionSourceUrl": "https://data.example.gov/table-a",
        },
    }


def configure_registration_root(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> pathlib.Path:
    generated = tmp_path / "ledger-targets.generated.ts"
    generated.write_text(
        'import type { TargetRegisteredLedgerEntry } from "./ledger-targets";\n'
        "export const GENERATED_FORECAST_TARGETS = [\n"
        "] satisfies TargetRegisteredLedgerEntry[];\n"
    )
    monkeypatch.setattr(register_targets, "ROOT", tmp_path)
    monkeypatch.setattr(register_targets, "GENERATED_TARGETS", generated)
    return generated


def configure_generator_root(
    tmp_path: pathlib.Path,
    generated: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hand_authored = tmp_path / "ledger-targets.ts"
    hand_authored.write_text("export const TARGETS = [];\n")
    monkeypatch.setattr(generate_ledger_targets, "ROOT", tmp_path)
    monkeypatch.setattr(generate_ledger_targets, "GENERATED", generated)
    monkeypatch.setattr(generate_ledger_targets, "HAND_AUTHORED", hand_authored)


@pytest.mark.usefixtures("resolver_admits")
def test_registration_snapshot_round_trip_and_hash_stability(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)

    registration_date = dt.date(2030, 1, 10)
    registered_at_utc = "2030-01-10T14:32:05Z"
    target = sample_target()
    reordered = dict(reversed(list(target.items())))
    snapshot = register_targets.build_snapshot(
        [target], registration_date, registered_at_utc
    )
    reordered_snapshot = register_targets.build_snapshot(
        [reordered], registration_date, registered_at_utc
    )
    later_snapshot = register_targets.build_snapshot(
        [target], registration_date, "2030-01-10T23:59:59Z"
    )
    content_hash = register_targets.registration_content_hash(snapshot)
    assert content_hash == register_targets.registration_content_hash(
        reordered_snapshot
    )
    assert content_hash == register_targets.registration_content_hash(later_snapshot)
    assert canonical_sha256(snapshot) != canonical_sha256(later_snapshot)
    with pytest.raises(
        register_targets.RegistrationError, match="top-level fields do not match"
    ):
        register_targets.registration_content_hash({**snapshot, "backdatedBy": "agent"})

    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [target]}))
    registrations = register_targets.register(
        targets_path, registration_date, registered_at_utc
    )
    assert len(registrations) == 1
    registration = registrations[0]
    snapshot_path = registration["path"]
    snapshot = registration["snapshot"]

    assert registration["existing"] is False
    assert registration["registeredAtUtc"] == registered_at_utc
    assert registration["targetContentHash"] == content_hash
    assert snapshot_path.name == f"2030-01-10-{content_hash}.json"
    assert snapshot_path.read_bytes() == canonical_bytes(snapshot) + b"\n"
    assert snapshot["registeredAtUtc"] == registered_at_utc
    assert (
        register_targets.registration_content_hash(
            json.loads(snapshot_path.read_text())
        )
        == content_hash
    )
    round_trip = json.loads(targets_path.read_text())["targets"][0]
    contract = snapshot["targets"][0]
    assert contract["dataPointId"] == "agency.test.rate.2030_01.first_print"
    assert round_trip["dataPointId"] == contract["dataPointId"]
    assert round_trip["sourceBinding"] == contract["sourceBinding"]
    assert (
        round_trip["expectedReleaseWindow"]
        == contract["sourceBinding"]["expectedReleaseWindow"]
    )
    assert round_trip["registeredAt"] == registered_at_utc
    assert round_trip["registeredAtUtc"] == registered_at_utc
    assert round_trip["targetContentHash"] == content_hash
    assert round_trip["targetRegistrationPath"].startswith("records/targets/")
    generated_text = generated.read_text()
    assert 'registrationState: "preregistered"' in generated_text
    assert f'registeredAt: "{registered_at_utc}"' in generated_text
    assert f'targetContentHash: "{content_hash}"' in generated_text
    preregistration = generate_ledger_targets.preregistration_for(
        generated_text, contract["dataPointId"]
    )
    assert preregistration is not None
    _, registration = preregistration
    cell = {
        "dataPointId": contract["dataPointId"],
        "unit": "percent",
        "resolutionSourceUrl": "https://data.example.gov/releases/january",
        "country": "US",
        "resolutionDate": "2030-02-15",
        "resolutionSource": "Agency table A",
        "resolutionRule": "First published January 2030 value.",
        "title": "Agency test rate",
    }
    generate_ledger_targets.validate_preregistered_contract(cell, registration)
    assert (
        generate_ledger_targets.entry_for(cell, registration)["registrationState"]
        == "published"
    )


def test_resolution_date_basis_defaults_without_churning_legacy_contracts() -> None:
    target = sample_target()

    assert register_targets.resolution_date_basis(target) == "release-calendar"
    contract = register_targets.build_contract(target, dt.date(2030, 1, 10))
    assert "resolutionDateBasis" not in contract

    explicit = {**target, "resolutionDateBasis": "release-calendar"}
    assert (
        register_targets.build_contract(explicit, dt.date(2030, 1, 10))[
            "resolutionDateBasis"
        ]
        == "release-calendar"
    )


def test_bounded_contract_requires_exact_window_and_matching_bound() -> None:
    target = {
        **sample_target(),
        "resolutionDateBasis": "resolve-by-bound",
        "resolutionDate": "2030-03-31",
        "expectedReleaseWindow": {
            "start": "2030-02-01",
            "end": "2030-03-31",
        },
    }

    contract = register_targets.build_contract(target, dt.date(2030, 1, 10))
    assert contract["resolutionDateBasis"] == "resolve-by-bound"
    assert contract["resolutionDate"] == "2030-03-31"
    assert contract["sourceBinding"]["expectedReleaseWindow"] == {
        "start": "2030-02-01",
        "end": "2030-03-31",
    }
    entry = register_targets._entry_for(
        contract,
        "a" * 64,
        "2030-01-10T00:00:00Z",
        _pin("0" * 40, 0),
    )
    assert entry["resolutionDateBasis"] == "resolve-by-bound"
    assert entry["resolutionDate"] == "2030-03-31"
    assert entry["resolutionRule"] == (
        "Preregistered resolve-by resolver binding. The resolutionDate and "
        "expectedReleaseWindow are Thesis lab commitments. The registered "
        "source URL authenticates methodology identity only; it does not "
        "establish either timing value. The analyst must supply the precise "
        "first-print rule without changing the methodology source, "
        "field/table, transform, or release policy."
    )
    match, registration = generate_ledger_targets.preregistration_for(
        register_targets.ts_literal(entry), contract["dataPointId"]
    ) or (None, None)
    assert match is not None
    assert registration["resolutionDateBasis"] == "resolve-by-bound"
    published = generate_ledger_targets.entry_for(
        {
            "dataPointId": contract["dataPointId"],
            "country": "US",
            "unit": "percent",
            "resolutionDate": "2030-03-31",
            "resolutionSource": "Agency table A",
            "resolutionSourceUrl": contract["sourceBinding"]["sourceUrl"],
            "resolutionRule": "First published bounded value.",
            "title": "Agency test rate",
        },
        registration,
    )
    assert published["resolutionDateBasis"] == "resolve-by-bound"

    invalid_targets = [
        (
            {**target, "resolutionDateBasis": "deadline-ish"},
            "resolutionDateBasis must be one of ['release-calendar', "
            "'resolve-by-bound'], got 'deadline-ish' "
            "(agency-test-rate-january-2030)",
        ),
        (
            {**target, "resolutionDateBasis": None},
            "resolutionDateBasis must be one of ['release-calendar', "
            "'resolve-by-bound'], got None (agency-test-rate-january-2030)",
        ),
        (
            {
                key: value
                for key, value in target.items()
                if key != "expectedReleaseWindow"
            },
            "resolve-by-bound target requires an exact expectedReleaseWindow",
        ),
        (
            {
                **target,
                "expectedReleaseWindow": {
                    "start": "2030-02-01",
                    "end": "2030-03-31",
                    "timezone": "UTC",
                },
            },
            "resolve-by-bound target requires an exact expectedReleaseWindow",
        ),
        (
            {
                **target,
                "expectedReleaseWindow": {"start": None, "end": None},
            },
            "resolve-by-bound expectedReleaseWindow dates must be canonical ISO dates",
        ),
        (
            {
                **target,
                "expectedReleaseWindow": {"start": "", "end": ""},
            },
            "invalid ISO date ''",
        ),
        (
            {
                **target,
                "expectedReleaseWindow": {
                    "start": "2030-04-01",
                    "end": "2030-03-31",
                },
            },
            "expected release window ends before it starts",
        ),
        (
            {key: value for key, value in target.items() if key != "resolutionDate"},
            "resolve-by-bound target requires resolutionDate to equal "
            "expectedReleaseWindow.end",
        ),
        (
            {**target, "resolutionDate": "2030-03-30"},
            "resolve-by-bound target requires resolutionDate to equal "
            "expectedReleaseWindow.end",
        ),
    ]
    for invalid, message in invalid_targets:
        with pytest.raises(register_targets.RegistrationError) as error:
            register_targets.build_contract(invalid, dt.date(2030, 1, 10))
        assert str(error.value) == message


def test_registration_hash_revalidates_bounded_snapshot_semantics() -> None:
    target = {
        **sample_target(),
        "resolutionDateBasis": "resolve-by-bound",
        "resolutionDate": "2030-03-31",
        "expectedReleaseWindow": {
            "start": "2030-02-01",
            "end": "2030-03-31",
        },
    }
    snapshot = register_targets.build_snapshot(
        [target],
        dt.date(2030, 1, 10),
        "2030-01-10T00:00:00Z",
        _pin("0" * 40, 0),
    )
    assert register_targets.registration_content_hash(snapshot)

    invalid_snapshots = []
    for mutate, message in (
        (
            lambda contract: contract["sourceBinding"].pop("expectedReleaseWindow"),
            "resolve-by-bound target requires an exact expectedReleaseWindow",
        ),
        (
            lambda contract: contract["sourceBinding"].update(
                expectedReleaseWindow={
                    "start": "2030-02-01",
                    "end": "2030-03-31",
                    "timezone": "UTC",
                }
            ),
            "resolve-by-bound target requires an exact expectedReleaseWindow",
        ),
        (
            lambda contract: contract.update(resolutionDate="2030-03-30"),
            "resolve-by-bound target requires resolutionDate to equal "
            "expectedReleaseWindow.end",
        ),
        (
            lambda contract: contract.update(resolutionDateBasis="deadline-ish"),
            "resolutionDateBasis must be one of ['release-calendar', "
            "'resolve-by-bound'], got 'deadline-ish' (registration target 0)",
        ),
    ):
        invalid = json.loads(json.dumps(snapshot))
        mutate(invalid["targets"][0])
        invalid_snapshots.append((invalid, message))

    for invalid, message in invalid_snapshots:
        with pytest.raises(register_targets.RegistrationError) as error:
            register_targets.registration_content_hash(invalid)
        assert str(error.value) == message


def test_resolution_projection_preserves_absent_basis_spelling() -> None:
    contract = register_targets.build_contract(sample_target(), dt.date(2030, 1, 10))
    window = contract["sourceBinding"]["expectedReleaseWindow"]
    target = {
        "expectedReleaseWindow": window,
        "sourceBinding": contract["sourceBinding"],
    }
    register_targets.validate_target_resolution_projection(
        contract, target, label="absent-default"
    )

    with pytest.raises(register_targets.RegistrationError) as error:
        register_targets.validate_target_resolution_projection(
            contract,
            {**target, "resolutionDateBasis": "release-calendar"},
            label="explicit-default",
        )
    assert str(error.value) == (
        "target registration contract mismatch for resolutionDateBasis: "
        "explicit-default"
    )


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda target: target.pop("resolutionDateBasis"), "resolutionDateBasis"),
        (
            lambda target: target.update(resolutionDateBasis="release-calendar"),
            "resolutionDateBasis",
        ),
        (lambda target: target.pop("resolutionDate"), "resolutionDate"),
        (
            lambda target: target.update(resolutionDate="2030-03-30"),
            "resolutionDate",
        ),
        (lambda target: target.pop("expectedReleaseWindow"), "expectedReleaseWindow"),
        (
            lambda target: target["expectedReleaseWindow"].update(start="2030-02-02"),
            "expectedReleaseWindow",
        ),
        (
            lambda target: target["sourceBinding"].pop("expectedReleaseWindow"),
            "sourceBinding.expectedReleaseWindow",
        ),
        (
            lambda target: target["sourceBinding"]["expectedReleaseWindow"].update(
                start="2030-02-02"
            ),
            "sourceBinding.expectedReleaseWindow",
        ),
    ],
)
def test_bounded_resolution_projection_refusals_are_presence_sensitive_and_literal(
    mutate,
    field: str,
) -> None:
    source = {
        **sample_target(),
        "resolutionDateBasis": "resolve-by-bound",
        "resolutionDate": "2030-03-31",
        "expectedReleaseWindow": {
            "start": "2030-02-01",
            "end": "2030-03-31",
        },
    }
    contract = register_targets.build_contract(source, dt.date(2030, 1, 10))
    target = {
        "resolutionDateBasis": contract["resolutionDateBasis"],
        "resolutionDate": contract["resolutionDate"],
        "expectedReleaseWindow": json.loads(
            json.dumps(contract["sourceBinding"]["expectedReleaseWindow"])
        ),
        "sourceBinding": json.loads(json.dumps(contract["sourceBinding"])),
    }
    register_targets.validate_target_resolution_projection(
        contract, target, label="bounded-projection"
    )
    mutate(target)

    with pytest.raises(register_targets.RegistrationError) as error:
        register_targets.validate_target_resolution_projection(
            contract, target, label="bounded-projection"
        )

    assert str(error.value) == (
        f"target registration contract mismatch for {field}: bounded-projection"
    )


@pytest.mark.usefixtures("resolver_admits")
def test_registration_retry_reuses_immutable_snapshot_and_generated_target(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [sample_target()]}))

    [original] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 10),
        "2030-01-10T14:32:05Z",
    )
    original_path = original["path"]
    original_snapshot_bytes = original_path.read_bytes()
    original_generated_bytes = generated.read_bytes()

    # A later workflow retry receives the unregistered docket target again.
    targets_path.write_text(json.dumps({"targets": [sample_target()]}))
    [retry] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 11),
        "2030-01-11T09:08:07Z",
    )

    assert retry["existing"] is True
    assert retry["path"] == original_path
    assert retry["registeredAtUtc"] == "2030-01-10T14:32:05Z"
    assert retry["targetContentHash"] == original["targetContentHash"]
    assert original_path.read_bytes() == original_snapshot_bytes
    assert generated.read_bytes() == original_generated_bytes
    round_trip = json.loads(targets_path.read_text())["targets"][0]
    assert round_trip["registeredAt"] == "2030-01-10T14:32:05Z"
    assert round_trip["registeredAtUtc"] == "2030-01-10T14:32:05Z"
    assert (
        round_trip["targetRegistrationPath"]
        == original_path.relative_to(tmp_path).as_posix()
    )


@pytest.mark.usefixtures("resolver_admits")
def test_reuse_existing_only_hydrates_without_rewriting_registration(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    raw_targets = json.dumps({"targets": [sample_target()]})
    targets_path.write_text(raw_targets)

    [original] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 10),
        "2030-01-10T14:32:05Z",
    )
    snapshot_bytes = original["path"].read_bytes()
    generated_bytes = generated.read_bytes()

    targets_path.write_text(raw_targets)
    [reused] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 11),
        "2030-01-11T09:08:07Z",
        reuse_existing_only=True,
    )

    assert reused["existing"] is True
    assert reused["path"] == original["path"]
    assert reused["path"].read_bytes() == snapshot_bytes
    assert generated.read_bytes() == generated_bytes
    [hydrated] = json.loads(targets_path.read_text())["targets"]
    assert hydrated["registeredAtUtc"] == "2030-01-10T14:32:05Z"
    assert hydrated["targetContentHash"] == original["targetContentHash"]
    assert (
        hydrated["targetRegistrationPath"]
        == original["path"].relative_to(tmp_path).as_posix()
    )


@pytest.mark.usefixtures("resolver_admits")
def test_reuse_existing_only_refuses_generated_rewrite_before_any_write(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    raw_targets = json.dumps({"targets": [sample_target()]})
    targets_path.write_text(raw_targets)
    [original] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 10),
        "2030-01-10T14:32:05Z",
    )
    snapshot_bytes = original["path"].read_bytes()
    generated_bytes = generated.read_bytes()
    targets_path.write_text(raw_targets)

    monkeypatch.setattr(
        register_targets,
        "render_generated_targets",
        lambda *_args, **_kwargs: generated.read_text() + "// forbidden rewrite\n",
    )

    with pytest.raises(
        register_targets.RegistrationError,
        match=(
            r"^--reuse-existing-only refused because generated targets "
            r"would be rewritten$"
        ),
    ):
        register_targets.register(
            targets_path,
            dt.date(2030, 1, 11),
            "2030-01-11T09:08:07Z",
            reuse_existing_only=True,
        )

    assert original["path"].read_bytes() == snapshot_bytes
    assert generated.read_bytes() == generated_bytes
    assert targets_path.read_text() == raw_targets


@pytest.mark.usefixtures("resolver_admits")
def test_reuse_existing_only_refuses_whole_set_before_any_write(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [sample_target()]}))
    [original] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 10),
        "2030-01-10T14:32:05Z",
    )

    unregistered = sample_target()
    unregistered.update(
        {
            "period": "2030-02",
            "catalogSlug": "agency-test-rate-february-2030",
        }
    )
    raw_targets = json.dumps({"targets": [sample_target(), unregistered]})
    targets_path.write_text(raw_targets)
    before_records = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (tmp_path / "records").rglob("*")
        if path.is_file()
    }
    generated_bytes = generated.read_bytes()

    with pytest.raises(
        register_targets.RegistrationError,
        match=(
            r"^--reuse-existing-only refused target\(s\) without an existing "
            r"immutable registration: agency-test-rate-february-2030$"
        ),
    ):
        register_targets.register(
            targets_path,
            dt.date(2030, 1, 11),
            "2030-01-11T09:08:07Z",
            reuse_existing_only=True,
        )

    after_records = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (tmp_path / "records").rglob("*")
        if path.is_file()
    }
    assert after_records == before_records
    assert original["path"].is_file()
    assert generated.read_bytes() == generated_bytes
    assert targets_path.read_text() == raw_targets


@pytest.mark.parametrize(
    ("incompatible_flag", "reason"),
    [
        (
            "--bind-registration-commits",
            "--reuse-existing-only cannot be combined with --bind-registration-commits",
        ),
        (
            "--skip-unbindable",
            "--reuse-existing-only cannot be combined with --skip-unbindable",
        ),
    ],
)
def test_reuse_existing_only_cli_combinations_refuse_before_writing(
    tmp_path: pathlib.Path,
    monkeypatch,
    capsys,
    incompatible_flag: str,
    reason: str,
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    targets_path.write_text('{"targets": []}\n')
    targets_bytes = targets_path.read_bytes()
    generated_bytes = generated.read_bytes()
    metadata_path = tmp_path / "metadata.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_targets.py",
            "--targets-file",
            str(targets_path),
            "--reuse-existing-only",
            incompatible_flag,
            "--metadata-out",
            str(metadata_path),
        ],
    )

    assert register_targets.main() == 1

    assert capsys.readouterr().err == f"target registration failed: {reason}\n"
    assert targets_path.read_bytes() == targets_bytes
    assert generated.read_bytes() == generated_bytes
    assert not metadata_path.exists()
    assert not (tmp_path / "records").exists()


@pytest.mark.usefixtures("resolver_admits")
def test_registration_retry_fails_closed_on_generated_target_mismatch(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    targets_path = tmp_path / "targets.json"
    raw_targets = json.dumps({"targets": [sample_target()]})
    targets_path.write_text(raw_targets)
    [original] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 10),
        "2030-01-10T14:32:05Z",
    )
    snapshot_bytes = original["path"].read_bytes()

    generated.write_text(
        generated.read_text().replace(
            'registeredAt: "2030-01-10T14:32:05Z"',
            'registeredAt: "1999-12-31T23:59:59Z"',
            1,
        )
    )
    mismatched_generated_bytes = generated.read_bytes()
    targets_path.write_text(raw_targets)

    with pytest.raises(
        register_targets.RegistrationError,
        match="not the exact immutable preregistration",
    ):
        register_targets.register(
            targets_path,
            dt.date(2030, 1, 11),
            "2030-01-11T09:08:07Z",
        )

    assert original["path"].read_bytes() == snapshot_bytes
    assert generated.read_bytes() == mismatched_generated_bytes
    assert targets_path.read_text() == raw_targets


def test_empty_registration_is_a_byte_identical_no_op(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    generated_bytes = generated.read_bytes()
    targets_path = tmp_path / "targets.json"
    targets_path.write_text('{"targets": []}\n')
    targets_bytes = targets_path.read_bytes()

    assert (
        register_targets.register(
            targets_path,
            dt.date(2030, 1, 10),
            "2030-01-10T14:32:05Z",
        )
        == []
    )

    assert targets_path.read_bytes() == targets_bytes
    assert generated.read_bytes() == generated_bytes
    assert not (tmp_path / "records" / "targets").exists()


@pytest.mark.usefixtures("resolver_admits")
def test_reuse_existing_only_then_bind_uses_snapshot_introducing_commit(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    docket = _write_docket(tmp_path, [])
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", generated.name, docket.relative_to(tmp_path).as_posix()],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    commit_args = [
        "git",
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
    ]
    subprocess.run(
        [*commit_args, "-m", "base"], cwd=tmp_path, check=True, capture_output=True
    )
    targets_path = tmp_path / "targets.json"
    raw_targets = json.dumps({"targets": [sample_target()]})
    targets_path.write_text(raw_targets)
    register_targets.register(
        targets_path,
        dt.date(2030, 1, 10),
        "2030-01-10T14:32:05Z",
    )
    subprocess.run(
        ["git", "add", "records/targets", generated.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [*commit_args, "-m", "register"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()

    targets_path.write_text(raw_targets)
    [reused] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 11),
        "2030-01-11T09:08:07Z",
        reuse_existing_only=True,
    )
    metadata = register_targets.bind_registration_commits(targets_path, head)

    target = json.loads(targets_path.read_text())["targets"][0]
    assert reused["existing"] is True
    assert target["registrationCommit"] == head
    assert metadata["sourceCommit"] == head
    assert metadata["registrationCommits"] == [head]


@pytest.mark.usefixtures("resolver_admits")
def test_publisher_regenerates_typescript_from_canonical_snapshot(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    empty_module = generated.read_bytes()
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [sample_target()]}))
    [registration] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 10),
        "2030-01-10T14:32:05Z",
    )
    expected = generated.read_bytes()

    generated.write_bytes(empty_module)
    register_targets.materialize_registration_snapshots([registration["path"]])

    assert generated.read_bytes() == expected


def test_wave_install_is_append_only(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(register_wave, "ROOT", tmp_path)
    module = tmp_path / "site/src/data/forecast-examples/auto-full-hash.ts"
    candidate = tmp_path / "candidate.ts"
    candidate.write_text("trusted candidate\n")

    register_wave.install_wave_candidate(candidate, module)
    register_wave.install_wave_candidate(candidate, module)
    assert module.read_bytes() == candidate.read_bytes()

    candidate.write_text("different candidate\n")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        register_wave.install_wave_candidate(candidate, module)
    assert module.read_text() == "trusted candidate\n"


def provenance_replay_cell() -> dict:
    return {
        "slug": "register-wave-provenance-probe",
        "country": "US",
        "type": "data",
        "title": "Register-wave provenance probe",
        "question": "What will the synthetic agency test rate be?",
        "unit": "percent",
        "pointEstimate": 1.0,
        "ciLow": 0.5,
        "ciHigh": 1.5,
        "confidence": 0.8,
        "resolutionDate": "2030-02-01",
        "resolutionSource": "Synthetic agency release",
        "resolutionSourceUrl": "https://agency.example/releases",
        "resolutionRule": "Use the first published synthetic agency value.",
        "dataPointId": "agency.synthetic.rate.2030_01.first_print",
        "historicalContext": [
            {
                "period": {"type": "month", "value": f"2029-{month:02d}"},
                "label": f"2029-{month:02d}",
                "value": value,
            }
            for month, value in enumerate(
                [0.8, 1.0, 0.9, 1.0, 0.9, 1.1],
                start=7,
            )
        ],
        "drivers": ["recent level", "release volatility"],
        "sourceContext": [
            "https://agency.example/history",
            "https://agency.example/calendar",
        ],
        "runAt": "2026-07-01T12:00:00Z",
        "reasoning": [
            {"kind": "heading", "text": "Synthetic agency rate"},
            {
                "kind": "tool",
                "tool": "agency.history",
                "call": "fetch 2029-11",
                "result": "2029-11 value: 0.9 percent",
            },
            {
                "kind": "tool",
                "tool": "agency.history",
                "call": "fetch 2029-12",
                "result": "2029-12 value: 1.1 percent",
            },
            {
                "kind": "text",
                "text": "The base rate across the last 2 releases centers on 1.0.",
            },
            {
                "kind": "math",
                "text": "The historical range is 0.9 to 1.1; widen to 0.5 to 1.5.",
            },
            {
                "kind": "text",
                "text": "An upside risk surprise would land outside the interval.",
            },
            {"kind": "forecast", "point": 1.0, "ciLow": 0.5, "ciHigh": 1.5},
        ],
    }


def convert_provenance_replay_candidate(
    tmp_path: pathlib.Path,
    module: pathlib.Path,
    candidate_name: str,
    provenance: str | None,
) -> pathlib.Path:
    # Reuse one deterministic run path so replayed activity paths remain
    # byte-identical while the fixture satisfies the current custody contract.
    run_dir = tmp_path / "run-provenance-replay"
    run_dir.mkdir(exist_ok=True)
    cell = provenance_replay_cell()
    created_at = cell["runAt"]
    raw_cells = json.dumps([cell], indent=2) + "\n"
    refs = [
        analyst_runner.write_artifact(
            run_dir, "prompt", "prompt.md", "forecast prompt\n", created_at
        ),
        analyst_runner.write_artifact(
            run_dir,
            "command",
            "command.json",
            json.dumps({"backend": "external_command", "argv": ["agent"]}),
            created_at,
        ),
        analyst_runner.write_artifact(
            run_dir, "stdout", "stdout.txt", "model output\n", created_at
        ),
        analyst_runner.write_artifact(run_dir, "stderr", "stderr.txt", "", created_at),
        analyst_runner.write_artifact(
            run_dir,
            "raw_response",
            "raw_response.txt",
            raw_cells,
            created_at,
        ),
        analyst_runner.write_artifact(
            run_dir,
            "parsed_cell",
            "parsed_cells.json",
            raw_cells,
            created_at,
        ),
        analyst_runner.write_artifact(
            run_dir,
            "normalized_cell",
            "normalized_cells.json",
            raw_cells,
            created_at,
        ),
        analyst_runner.write_artifact(
            run_dir,
            "run_distribution",
            "distribution.json",
            json.dumps(analyst_runner.interval_distribution(cell), indent=2) + "\n",
            created_at,
        ),
        analyst_runner.write_artifact(
            run_dir,
            "validation_report",
            "validation.json",
            json.dumps({"ok": True, "cells": [{"ok": True, "errors": []}]}),
            created_at,
        ),
    ]
    cell["activityLog"] = list(refs)
    cells_path = run_dir / "cells.with_activity.json"
    refs.append(
        analyst_runner.write_artifact(
            run_dir,
            "cells_with_activity",
            cells_path.name,
            json.dumps([cell], indent=2) + "\n",
            created_at,
        )
    )
    manifest = {
        "schemaVersion": "thesis_analyst_run_manifest_v1",
        "createdAt": created_at,
        "ok": True,
        "agent": {
            "agent": "thesis.analyst",
            "agentVersion": "2.5.10",
            "promptHash": "a" * 64,
            "toolPolicyHash": "b" * 64,
        },
        "preSubmitReview": None,
        "cellsPath": str(cells_path),
        "artifacts": refs,
        "validation": {"ok": True, "cells": [{"ok": True, "errors": []}]},
    }
    analyst_runner.finalize_manifest(run_dir, created_at, manifest, refs)
    batch_path = tmp_path / "batch.json"
    batch_path.write_text("{}\n")
    candidate = tmp_path / candidate_name
    subprocess.run(
        register_wave.converter_command(
            candidate,
            "PROVENANCE_REPLAY_WAVE",
            [str(cells_path)],
            [str(batch_path)],
            module,
            provenance,
        ),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return candidate


def test_register_wave_derives_explicit_provenance_from_validated_batches() -> None:
    ordinary = {"results": []}
    attested = {
        "results": [],
        "generationTicket": {
            "ticketId": "2030-01-11-deadbeef",
            "ticketPath": ("records/tickets/2030-01-11/2030-01-11-deadbeef.json"),
            "nonceSha256": "a" * 64,
        },
    }

    assert register_wave.derive_batch_provenance([ordinary]) == "ci"
    assert register_wave.derive_batch_provenance([attested]) == (
        "local_operator_attested"
    )
    with pytest.raises(
        ValueError,
        match="batch manifests mix ticketed and ordinary publication provenance",
    ):
        register_wave.derive_batch_provenance([ordinary, attested])
    command = register_wave.converter_command(
        pathlib.Path("candidate.ts"),
        "TEST_WAVE",
        ["cells.json"],
        ["batch.json"],
        pathlib.Path("module.ts"),
        "ci",
    )
    assert command[-2:] == ["--provenance", "ci"]
    unlabeled_command = register_wave.converter_command(
        pathlib.Path("candidate.ts"),
        "TEST_WAVE",
        ["cells.json"],
        ["batch.json"],
        pathlib.Path("module.ts"),
        None,
    )
    assert "--provenance" not in unlabeled_command


def test_register_wave_new_module_uses_derived_provenance(
    tmp_path: pathlib.Path,
) -> None:
    module = tmp_path / "new-wave.ts"

    assert register_wave.replay_provenance_for_module(module, "ci") == "ci"


def test_register_wave_unlabeled_legacy_replay_is_byte_identical(
    tmp_path: pathlib.Path,
) -> None:
    module = tmp_path / "legacy-wave.ts"
    initial = convert_provenance_replay_candidate(
        tmp_path, module, "initial-legacy.ts", None
    )
    register_wave.install_wave_candidate(initial, module)

    replay_provenance = register_wave.replay_provenance_for_module(module, "ci")
    assert replay_provenance is None
    replay = convert_provenance_replay_candidate(
        tmp_path, module, "replayed-legacy.ts", replay_provenance
    )

    assert replay.read_bytes() == module.read_bytes()
    register_wave.install_wave_candidate(replay, module)


def test_register_wave_labeled_replay_preserves_matching_label(
    tmp_path: pathlib.Path,
) -> None:
    module = tmp_path / "labeled-wave.ts"
    initial = convert_provenance_replay_candidate(
        tmp_path, module, "initial-labeled.ts", "ci"
    )
    register_wave.install_wave_candidate(initial, module)

    replay_provenance = register_wave.replay_provenance_for_module(module, "ci")
    assert replay_provenance == "ci"
    replay = convert_provenance_replay_candidate(
        tmp_path, module, "replayed-labeled.ts", replay_provenance
    )

    assert replay.read_bytes() == module.read_bytes()
    register_wave.install_wave_candidate(replay, module)


def test_register_wave_refuses_existing_provenance_mismatch(
    tmp_path: pathlib.Path,
) -> None:
    module = tmp_path / "mismatched-wave.ts"
    labeled = convert_provenance_replay_candidate(
        tmp_path, module, "mismatched-labeled.ts", "ci"
    )
    register_wave.install_wave_candidate(labeled, module)

    with pytest.raises(
        ValueError,
        match=(
            "existing wave predictionRun provenance differs from derived batch "
            "provenance: ci != local_operator_attested"
        ),
    ):
        register_wave.replay_provenance_for_module(module, "local_operator_attested")


@pytest.mark.usefixtures("resolver_admits")
def test_published_target_is_exactly_regenerated_and_retry_safe(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    configure_generator_root(tmp_path, generated, monkeypatch)
    raw_target_payload = json.dumps({"targets": [sample_target()]})
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(raw_target_payload)
    [registration] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 10),
        "2030-01-10T14:32:05Z",
    )
    target = json.loads(targets_path.read_text())["targets"][0]
    cell = {
        "slug": target["catalogSlug"],
        "dataPointId": target["dataPointId"],
        "unit": target["targetUnit"],
        "country": target["country"],
        "resolutionDate": "2030-02-15",
        "resolutionSource": "Agency table A",
        "resolutionSourceUrl": "https://data.example.gov/releases/january",
        "resolutionRule": "First published January 2030 value.",
        "title": "Agency test rate",
        "targetRegistrationPath": target["targetRegistrationPath"],
        "targetContentHash": target["targetContentHash"],
        "registeredAtUtc": target["registeredAtUtc"],
    }
    cells_path = tmp_path / "cells.json"
    cells_path.write_text(json.dumps([cell]))
    monkeypatch.setattr(sys, "argv", ["generate_ledger_targets.py", str(cells_path)])

    assert generate_ledger_targets.main() == 0
    published = generated.read_bytes()
    assert 'registrationState: "published"' in published.decode()

    # Post-commit regeneration and a later registration retry are byte-exact.
    assert generate_ledger_targets.main() == 0
    register_targets.materialize_registration_snapshots([registration["path"]])
    assert generated.read_bytes() == published
    targets_path.write_text(raw_target_payload)
    [retry] = register_targets.register(
        targets_path,
        dt.date(2030, 1, 11),
        "2030-01-11T09:08:07Z",
    )
    assert retry["existing"] is True
    assert generated.read_bytes() == published

    generated.write_text(
        generated.read_text().replace(
            'resolutionSource: "Agency table A"',
            'resolutionSource: "Tampered table"',
            1,
        )
    )
    with pytest.raises(ValueError, match="differs from canonical"):
        generate_ledger_targets.main()


def test_claims_binding_is_data_driven_and_advance_vintage() -> None:
    contract = register_targets.build_contract(
        {
            "series": "us.dol.initial_claims.sa",
            "period": "week_2030-01-05",
            "catalogSlug": "initial-claims-week-2030-01-05",
            "targetUnit": "thousands",
            "valueScale": 0.001,
        },
        dt.date(2030, 1, 6),
    )

    assert contract["dataPointId"] == "us.dol.initial_claims.sa.week_2030-01-05"
    assert contract["sourceBinding"] == {
        "adapter": "alfred-fred",
        "sourceUrl": "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA",
        "sourceSeriesId": "ICSA",
        "field": "ICSA",
        "table": "ALFRED graph CSV",
        "transform": {"operation": "multiply", "factor": 0.001},
        "releasePolicy": "advance_vintage",
        "allowedHosts": ["alfred.stlouisfed.org"],
        "expectedReleaseWindow": {"start": "2030-01-08", "end": "2030-01-12"},
    }


def test_alfred_docket_templates_build_registration_contracts() -> None:
    entries = _alfred_docket_entries()
    assert len(entries) >= 30

    for entry in entries:
        cadence = entry["cadence"]
        assert cadence in {"monthly", "quarterly"}
        period = "2030-06" if cadence == "monthly" else "2030-Q2"
        target = {
            "series": entry["series"],
            "period": period,
            "catalogSlug": entry["slug"].format(
                period=period,
                month="june",
                month_abbr="jun",
                quarter=2,
                year=2030,
            ),
            "expectedReleaseDate": "2030-07-31",
            "releaseCalendarUrl": "https://agency.example/release-calendar",
            **entry["extras"],
        }

        contract = register_targets.build_contract(target, dt.date(2030, 1, 1))
        template = entry["extras"]["sourceBinding"]
        binding = contract["sourceBinding"]

        assert register_targets._binding_matches_template(binding, template)
        assert contract["unit"] == entry["extras"]["targetUnit"]
        assert contract["valueScale"] == entry["extras"].get("valueScale", 1)
        assert contract["dataPointId"] == (
            f"{entry['series']}.2030_06.first_print"
            if cadence == "monthly"
            else f"{entry['series']}.2030_q2.first_print"
        )
        assert binding["allowedHosts"] == ["alfred.stlouisfed.org"]
        assert binding["expectedReleaseWindow"] == {
            "start": "2030-07-31",
            "end": "2030-07-31",
        }


@pytest.mark.parametrize(
    ("series", "adapter", "legacy_id"),
    [
        (
            "abs.labour.unemployment_rate",
            "abs-data-api",
            "abs.labour.unemployment_rate.australia.june_2026.first_print",
        ),
        (
            "eurostat.hicp.flash.yoy",
            "eurostat-api",
            "eurostat.hicp.all_items_annual_rate.euro_area.2026_06.flash",
        ),
        (
            "statcan.gdp_by_industry.monthly_growth",
            "statcan-wds",
            (
                "statcan.36-10-0434-01.all_industries."
                "month_to_month_percent_change.2026-06.first_print"
            ),
        ),
    ],
)
def test_native_registration_uses_canonical_series_id_stem(
    series: str, adapter: str, legacy_id: str
) -> None:
    target = {
        "series": series,
        "period": "2026-07",
        "sourceBinding": {
            "adapter": adapter,
            "releasePolicy": "first_print",
        },
    }
    previous = {"period": "2026-06", "dataPointId": legacy_id}

    assert register_targets.derive_data_point_id(target, previous) == (
        f"{series}.2026_07.first_print"
    )


def test_native_registration_refuses_cadence_inferred_release_window() -> None:
    target = {
        "series": "abs.labour.unemployment_rate",
        "period": "2026-07",
        "catalogSlug": "australia-unemployment-rate-july-2026",
        "targetUnit": "percent",
        "releaseCalendarUrl": (
            "https://www.abs.gov.au/statistics/labour/"
            "employment-and-unemployment/labour-force-australia"
        ),
        "sourceBinding": {"adapter": "abs-data-api"},
        "previousTarget": {
            "period": "2026-06",
            "resolutionDate": "2026-07-23",
            "unit": "percent",
        },
    }
    with pytest.raises(
        register_targets.RegistrationError,
        match="explicit official expectedReleaseDate",
    ):
        register_targets.build_contract(target, dt.date(2026, 7, 25))

    with pytest.raises(register_targets.RegistrationError, match="releaseCalendarUrl"):
        register_targets.build_contract(
            {
                **target,
                "expectedReleaseDate": "2026-08-20",
                "releaseCalendarUrl": "http://www.abs.gov.au/calendar",
            },
            dt.date(2026, 7, 25),
        )

    with pytest.raises(
        register_targets.RegistrationError,
        match="must start after the registration date",
    ):
        register_targets.build_contract(
            {
                **target,
                "expectedReleaseDate": "2026-07-20",
            },
            dt.date(2026, 7, 25),
        )


def _wave1_bea_successor_target() -> tuple[dict, dict]:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        row
        for row in docket["series"]
        if row["series"] == "bea.private_nonresidential_fixed_investment"
    )
    target = {
        "series": entry["series"],
        "period": "2026-Q4",
        "catalogSlug": "us-private-nonresidential-fixed-investment-q4-2026",
        "releaseCalendarUrl": entry["releaseCalendarUrl"],
        **entry["extras"],
        "previousTarget": {
            "period": "2026-Q3",
            "dataPointId": (
                "bea.private_nonresidential_fixed_investment.2026_q3.first_print"
            ),
            "country": "US",
            "unit": "usd_billions",
            "resolutionDate": "2026-10-29",
        },
    }
    return entry, target


def test_bea_release_successor_refuses_cadence_inference_literal() -> None:
    _, target = _wave1_bea_successor_target()

    with pytest.raises(register_targets.RegistrationError) as caught:
        register_targets.build_contract(target, dt.date(2026, 11, 1))

    assert str(caught.value) == (
        "calendar-gated target requires an explicit official "
        "expectedReleaseDate or expectedReleaseWindow"
    )


def test_bea_release_successor_cannot_invent_release_slot_literal() -> None:
    entry, target = _wave1_bea_successor_target()
    target["expectedReleaseDate"] = "2027-01-29"
    contract = register_targets.build_contract(target, dt.date(2026, 11, 1))

    assert contract["sourceBinding"]["expectedReleaseWindow"] == {
        "start": "2027-01-29",
        "end": "2027-01-29",
    }
    with pytest.raises(register_targets.RegistrationError) as caught:
        register_targets.validate_committed_calendar_contract(contract, target, entry)

    assert str(caught.value) == (
        "committed dated docket entry lacks the target period's release date "
        "or calendar URL"
    )


def test_bea_ita_successor_research_links_cannot_widen_custody_hosts() -> None:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        row
        for row in docket["series"]
        if row["series"] == "bea.ita.personal_transfer_payments"
    )
    target = {
        "series": entry["series"],
        "period": entry["seedPeriod"],
        "catalogSlug": "us-personal-transfer-payments-q2-2026",
        "releaseCalendarUrl": entry["releaseCalendarUrl"],
        "expectedReleaseDate": entry["releaseDates"][entry["seedPeriod"]],
        **entry["extras"],
        "previousTarget": {
            "period": "2026-Q1",
            "dataPointId": ("bea.ita.personal_transfer_payments.2026_q1.first_print"),
            "country": "US",
            "unit": "usd_millions",
            "resolutionDate": "2026-06-24",
            "resolutionSourceUrl": entry["extras"]["sourceBinding"]["sourceUrl"],
            "sourceContext": ["https://fred.stlouisfed.org/series/IAPTPQ"],
        },
    }

    contract = register_targets.build_contract(target, dt.date(2026, 8, 12))

    assert contract["sourceBinding"]["allowedHosts"] == [
        "apps.bea.gov",
        "www.bea.gov",
    ]


def test_inherited_native_binding_keeps_canonical_id_and_official_window() -> None:
    previous = {
        "period": "2026-07",
        "dataPointId": ("abs.labour.unemployment_rate.australia.july_2026.first_print"),
        "country": "AU",
        "unit": "percent",
        "resolutionDate": "2026-08-20",
        "resolutionSourceUrl": (
            "https://data.api.abs.gov.au/rest/data/"
            "LF/M13.3.1599.20.AUS.M?format=jsondata"
        ),
        "sourceBinding": {
            "adapter": "abs-data-api",
            "sourceUrl": (
                "https://data.api.abs.gov.au/rest/data/"
                "LF/M13.3.1599.20.AUS.M?format=jsondata"
            ),
            "sourceSeriesId": "LF/M13.3.1599.20.AUS.M",
            "field": "M13",
            "table": "ABS Labour Force, Australia",
            "transform": {"operation": "multiply", "factor": 1},
            "releasePolicy": "first_print",
            "expectedReleaseWindow": {
                "start": "2026-08-20",
                "end": "2026-08-20",
            },
            "allowedHosts": ["data.api.abs.gov.au"],
        },
    }
    target = {
        "series": "abs.labour.unemployment_rate",
        "period": "2026-08",
        "catalogSlug": "australia-unemployment-rate-august-2026",
        "targetUnit": "percent",
        "expectedReleaseDate": "2026-09-24",
        "releaseCalendarUrl": (
            "https://www.abs.gov.au/statistics/labour/"
            "employment-and-unemployment/labour-force-australia"
        ),
        "previousTarget": previous,
    }

    contract = register_targets.build_contract(target, dt.date(2026, 7, 25))

    assert contract["dataPointId"] == (
        "abs.labour.unemployment_rate.2026_08.first_print"
    )
    assert contract["sourceBinding"]["adapter"] == "abs-data-api"
    assert contract["sourceBinding"]["sourceSeriesId"] == ("LF/M13.3.1599.20.AUS.M")
    assert contract["sourceBinding"]["expectedReleaseWindow"] == {
        "start": "2026-09-24",
        "end": "2026-09-24",
    }


def test_inherited_native_binding_still_requires_official_release_date() -> None:
    target = {
        "series": "abs.labour.unemployment_rate",
        "period": "2026-08",
        "catalogSlug": "australia-unemployment-rate-august-2026",
        "targetUnit": "percent",
        "releaseCalendarUrl": (
            "https://www.abs.gov.au/statistics/labour/"
            "employment-and-unemployment/labour-force-australia"
        ),
        "previousTarget": {
            "period": "2026-07",
            "unit": "percent",
            "resolutionDate": "2026-08-20",
            "sourceBinding": {
                "adapter": "abs-data-api",
                "sourceUrl": (
                    "https://data.api.abs.gov.au/rest/data/"
                    "LF/M13.3.1599.20.AUS.M?format=jsondata"
                ),
                "sourceSeriesId": "LF/M13.3.1599.20.AUS.M",
                "field": "M13",
                "table": "ABS Labour Force, Australia",
                "transform": {"operation": "multiply", "factor": 1},
                "releasePolicy": "first_print",
            },
        },
    }

    with pytest.raises(
        register_targets.RegistrationError,
        match="explicit official expectedReleaseDate",
    ):
        register_targets.build_contract(target, dt.date(2026, 7, 25))


def test_publisher_contract_enforces_allowed_hosts_membership() -> None:
    registration = {
        "unit": "thousands",
        "sourceBinding": {
            "sourceUrl": "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=ICSA",
            "allowedHosts": ["alfred.stlouisfed.org", "www.dol.gov"],
        },
    }
    cell = {
        "dataPointId": "us.dol.initial_claims.sa.week_2030-01-05",
        "unit": "thousands",
        "resolutionSourceUrl": "https://www.dol.gov/ui/data.pdf",
    }
    generate_ledger_targets.validate_preregistered_contract(cell, registration)

    with pytest.raises(ValueError, match="not among the preregistered"):
        generate_ledger_targets.validate_preregistered_contract(
            dict(cell, resolutionSourceUrl="https://evil.example/data"),
            registration,
        )

    legacy = {
        "unit": "thousands",
        "sourceBinding": {"sourceUrl": "https://alfred.stlouisfed.org/g.csv"},
    }
    generate_ledger_targets.validate_preregistered_contract(
        dict(cell, resolutionSourceUrl="https://alfred.stlouisfed.org/g.csv"),
        legacy,
    )
    with pytest.raises(ValueError, match="not among the preregistered"):
        generate_ledger_targets.validate_preregistered_contract(cell, legacy)

    with pytest.raises(ValueError, match="not among the preregistered"):
        generate_ledger_targets.validate_preregistered_contract(
            cell, {"unit": "thousands", "sourceBinding": {}}
        )


def _supersede_contract() -> dict:
    return {
        "series": "abs.labour.unemployment_rate.australia",
        "period": "2026-07",
        "catalogSlug": "australia-unemployment-rate-july-2026",
        "dataPointId": "abs.labour.unemployment_rate.australia.july_2026.first_print",
        "country": "AU",
        "unit": "percent",
        "valueScale": 1.0,
        "sourceBinding": {
            "adapter": "generic-url",
            "sourceUrl": "https://www.abs.gov.au/statistics/labour",
            "sourceSeriesId": "unemployment_rate",
            "field": "unemployment_rate",
            "table": "ABS Labour Force",
            "transform": {"operation": "multiply", "factor": 1},
            "releasePolicy": "first_print",
            "expectedReleaseWindow": {"start": "2026-08-01", "end": "2026-08-15"},
            "allowedHosts": ["www.abs.gov.au"],
        },
    }


def _binding_upgrade_contracts() -> tuple[dict, dict]:
    """Mirror the portal-to-Data-API upgrade in the live ABS registration."""

    old = {
        **_supersede_contract(),
        "series": "abs.labour.unemployment_rate",
        "sourceBinding": {
            "adapter": "generic-url",
            "sourceUrl": (
                "https://www.abs.gov.au/statistics/labour/"
                "employment-and-unemployment/labour-force-australia/"
                "latest-release"
            ),
            "sourceSeriesId": "abs.labour.unemployment_rate",
            "field": "abs.labour.unemployment_rate",
            "table": (
                "Australian Bureau of Statistics Labour Force, Australia, June 2026"
            ),
            "transform": {"operation": "multiply", "factor": 1},
            "releasePolicy": "first_print",
            "expectedReleaseWindow": {
                "start": "2026-08-19",
                "end": "2026-08-27",
            },
            "allowedHosts": ["www.abs.gov.au"],
        },
    }
    upgraded = {
        **old,
        "sourceBinding": {
            "adapter": "generic-url",
            "sourceUrl": (
                "https://data.api.abs.gov.au/rest/data/"
                "LF/M13.3.1599.20.AUS.M?format=jsondata"
            ),
            "sourceSeriesId": "LF/M13.3.1599.20.AUS.M",
            "field": "M13",
            "table": (
                "Labour Force, Australia (dataflow LF): unemployment rate, "
                "persons, seasonally adjusted; first print captured on release day"
            ),
            "transform": {"operation": "multiply", "factor": 1},
            "releasePolicy": "first_print",
            "expectedReleaseWindow": {
                "start": "2026-08-19",
                "end": "2026-08-27",
            },
            "allowedHosts": ["data.api.abs.gov.au", "www.abs.gov.au"],
        },
    }
    return old, upgraded


def _binding_template(binding: dict) -> dict:
    return {
        key: value
        for key, value in binding.items()
        if key not in {"expectedReleaseWindow", "allowedHosts"}
    }


def _write_docket(tmp_path: pathlib.Path, entries: list[dict]) -> pathlib.Path:
    path = tmp_path / "scripts" / "docket_series.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"series": entries}, indent=2) + "\n")
    return path


def _docket_entry(contract: dict) -> dict:
    return {
        "series": contract["series"],
        "extras": {
            "sourceBinding": _binding_template(contract["sourceBinding"]),
        },
    }


def _docket_with_duplicate_key(contract: dict, duplicate: str) -> str:
    source = json.dumps({"series": [_docket_entry(contract)]}, indent=2) + "\n"
    if duplicate == "series":
        needle = f'"series": {json.dumps(contract["series"])}'
        replacement = (
            '"series": "ignored.invalid.series",\n'
            f'      "series": {json.dumps(contract["series"])}'
        )
    else:
        source_url = contract["sourceBinding"]["sourceUrl"]
        needle = f'"sourceUrl": {json.dumps(source_url)}'
        replacement = (
            '"sourceUrl": "https://ignored.invalid/source",\n'
            f'          "sourceUrl": {json.dumps(source_url)}'
        )
    assert source.count(needle) == 1
    return source.replace(needle, replacement, 1)


def _commit_files(
    tmp_path: pathlib.Path, paths: list[pathlib.Path], message: str
) -> None:
    subprocess.run(
        ["git", "add", *(path.relative_to(tmp_path).as_posix() for path in paths)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            message,
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def _target_from_contract(contract: dict) -> dict:
    return {
        "series": contract["series"],
        "period": contract["period"],
        "catalogSlug": contract["catalogSlug"],
        "dataPointId": contract["dataPointId"],
        "country": contract["country"],
        "targetUnit": contract["unit"],
        "valueScale": contract["valueScale"],
        "sourceBinding": contract["sourceBinding"],
        "expectedReleaseWindow": contract["sourceBinding"]["expectedReleaseWindow"],
    }


def _registered_target_payload(registration: dict, relative: pathlib.Path) -> dict:
    contract = registration["contract"]
    target = {
        "series": contract["series"],
        "period": contract["period"],
        "catalogSlug": contract["catalogSlug"],
        "dataPointId": contract["dataPointId"],
        "country": contract["country"],
        "targetUnit": contract["unit"],
        "valueScale": contract["valueScale"],
        "sourceBinding": contract["sourceBinding"],
        "registeredAtUtc": registration["registeredAtUtc"],
        "targetContentHash": registration["targetContentHash"],
        "targetRegistrationPath": relative.as_posix(),
    }
    window = contract["sourceBinding"].get("expectedReleaseWindow")
    if window is not None:
        target["expectedReleaseWindow"] = window
    for field in ("resolutionDateBasis", "resolutionDate"):
        if field in contract:
            target[field] = contract[field]
    if "seedPeriod" in contract:
        target["seedPeriod"] = contract["seedPeriod"]
    return target


def _install_registration_for_bind(
    tmp_path: pathlib.Path,
    generated: pathlib.Path,
    registration: dict,
) -> tuple[pathlib.Path, pathlib.Path]:
    relative = (
        pathlib.Path("records/targets") / f"{registration['registeredAtUtc'][:10]}-"
        f"{registration['targetContentHash']}.json"
    )
    snapshot_path = tmp_path / relative
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_bytes(canonical_bytes(registration["snapshot"]) + b"\n")
    _write_block(
        generated,
        register_targets.ts_literal(
            register_targets._entry_for(
                registration["contract"],
                registration["targetContentHash"],
                registration["registeredAtUtc"],
                registration["snapshot"].get("ledgerPin"),
            )
        ),
    )
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            {"targets": [_registered_target_payload(registration, relative)]},
            indent=2,
        )
        + "\n"
    )
    return snapshot_path, targets_path


def _registration(contract: dict, registered_at: str, pin: dict | None) -> dict:
    if pin is not None:
        snapshot = {
            "schemaVersion": register_targets.REGISTRATION_SCHEMA,
            "registeredAtUtc": registered_at,
            "targets": [contract],
            "ledgerPin": pin,
        }
    else:
        snapshot = {
            "schemaVersion": register_targets.V2_REGISTRATION_SCHEMA,
            "registeredAtUtc": registered_at,
            "targets": [contract],
        }
    # register() canonicalizes the snapshot before rendering, so a real block
    # is built from the canonical contract (e.g. valueScale 1.0 -> 1).
    snapshot = json.loads(canonical_bytes(snapshot))
    return {
        "contract": snapshot["targets"][0],
        "targetContentHash": register_targets.registration_content_hash(snapshot),
        "registeredAtUtc": registered_at,
        "snapshot": snapshot,
        "existing": False,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda entry: entry.pop("resolutionDateBasis"),
        lambda entry: entry.update(resolutionDateBasis="release-calendar"),
        lambda entry: entry.pop("resolutionDate"),
        lambda entry: entry.update(resolutionDate="2026-08-14"),
        lambda entry: entry["sourceBinding"]["expectedReleaseWindow"].update(
            start="2026-08-02"
        ),
    ],
)
def test_bounded_published_block_resolution_tampering_is_refused(
    tmp_path,
    monkeypatch,
    mutate,
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = json.loads(json.dumps(_supersede_contract()))
    contract.update(
        resolutionDateBasis="resolve-by-bound",
        resolutionDate=contract["sourceBinding"]["expectedReleaseWindow"]["end"],
    )
    registration = _registration(contract, "2026-07-10T05:03:56Z", None)
    published = json.loads(
        json.dumps(
            register_targets._entry_for(
                registration["contract"],
                registration["targetContentHash"],
                registration["registeredAtUtc"],
                None,
            )
        )
    )
    published["registrationState"] = "published"
    mutate(published)
    _write_block(generated, register_targets.ts_literal(published))

    with pytest.raises(register_targets.RegistrationError) as error:
        register_targets.render_generated_targets([registration], allow_published=True)

    assert str(error.value) == (
        "existing generated target is not the exact immutable preregistration "
        f"for {contract['dataPointId']}"
    )


def test_absent_basis_published_block_cannot_gain_explicit_default(
    tmp_path,
    monkeypatch,
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    registration = _registration(contract, "2026-07-10T05:03:56Z", None)
    published = register_targets._entry_for(
        registration["contract"],
        registration["targetContentHash"],
        registration["registeredAtUtc"],
        None,
    )
    published["registrationState"] = "published"
    published["resolutionDateBasis"] = "release-calendar"
    _write_block(generated, register_targets.ts_literal(published))

    with pytest.raises(register_targets.RegistrationError) as error:
        register_targets.render_generated_targets([registration], allow_published=True)

    assert str(error.value) == (
        "existing generated target is not the exact immutable preregistration "
        f"for {contract['dataPointId']}"
    )


def _pin(sha: str, line_count: int) -> dict:
    return {
        "repo": "PolicyEngine/chronicle",
        "branch": "codex/thesis-ledger-facts",
        "sha": sha,
        "jsonlSha256": "a" * 64,
        "lineCount": line_count,
    }


def _catalog_pin(sha: str, line_count: int) -> dict:
    return {
        **_pin(sha, line_count),
        "catalogSha256": "b" * 64,
        "catalogBytes": 12345,
    }


def _write_block(generated: pathlib.Path, block: str) -> None:
    generated.write_text(
        'import type { TargetRegisteredLedgerEntry } from "./ledger-targets";\n'
        "export const GENERATED_FORECAST_TARGETS = [\n"
        f"{block}\n"
        "] satisfies TargetRegisteredLedgerEntry[];\n"
    )


def _commit_first_registration(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    contract: dict,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, dict]:
    generated = configure_registration_root(tmp_path, monkeypatch)
    docket = _write_docket(tmp_path, [_docket_entry(contract)])
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _commit_files(tmp_path, [generated, docket], "commit binding template")
    monkeypatch.setattr(
        register_targets,
        "load_ledger_pin_binding",
        lambda: _pin("c" * 40, 128),
    )
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps({"targets": [_target_from_contract(contract)]}) + "\n"
    )
    [registration] = register_targets.register(
        targets_path, dt.date(2026, 7, 10), "2026-07-10T06:17:27Z"
    )
    _commit_files(
        tmp_path,
        [generated, registration["path"]],
        "commit first target registration",
    )
    return generated, docket, targets_path, registration


def _backed_block(
    tmp_path: pathlib.Path, contract: dict, registered_at: str, pin: dict | None
) -> str:
    """Write a real snapshot and return the generated block it renders to."""
    registration = _registration(contract, registered_at, pin)
    content_hash = registration["targetContentHash"]
    targets_dir = tmp_path / "records" / "targets"
    targets_dir.mkdir(parents=True, exist_ok=True)
    (targets_dir / f"{registered_at[:10]}-{content_hash}.json").write_bytes(
        canonical_bytes(registration["snapshot"]) + b"\n"
    )
    return register_targets.ts_literal(
        register_targets._entry_for(
            registration["contract"], content_hash, registered_at, pin
        )
    )


def _commit_v2_supersede_history(
    tmp_path: pathlib.Path,
    generated: pathlib.Path,
    contract: dict,
    monkeypatch: pytest.MonkeyPatch,
    registered_at: str = "2026-07-10T05:03:56Z",
) -> pathlib.Path:
    """Commit a v2 preregistration before a reachable v3 cutover."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "add", generated.relative_to(tmp_path).as_posix()],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    commit_args = [
        "git",
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "commit",
    ]
    subprocess.run(
        [*commit_args, "-m", "base"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    old_block = _backed_block(tmp_path, contract, registered_at, None)
    _write_block(generated, old_block)
    old_path = next((tmp_path / "records" / "targets").glob("*.json"))
    subprocess.run(
        ["git", "add", generated.name, old_path.relative_to(tmp_path).as_posix()],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [*commit_args, "-m", "register v2 target"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [*commit_args, "--allow-empty", "-m", "v3 cutover"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    cutover_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    monkeypatch.setattr(
        register_targets, "V3_REGISTRATION_CUTOVER_COMMIT", cutover_commit
    )
    return old_path


def _commit_v3_supersede_history(
    tmp_path: pathlib.Path,
    generated: pathlib.Path,
    contract: dict,
    monkeypatch: pytest.MonkeyPatch,
    registered_at: str,
    pin: dict,
) -> pathlib.Path:
    """Commit a v3 preregistration on top of the reachable cutover history."""
    _commit_v2_supersede_history(tmp_path, generated, contract, monkeypatch)
    registration = _registration(contract, registered_at, pin)
    path = (
        tmp_path
        / "records"
        / "targets"
        / f"{registered_at[:10]}-{registration['targetContentHash']}.json"
    )
    path.write_bytes(canonical_bytes(registration["snapshot"]) + b"\n")
    _write_block(
        generated,
        register_targets.ts_literal(
            register_targets._entry_for(
                registration["contract"],
                registration["targetContentHash"],
                registration["registeredAtUtc"],
                pin,
            )
        ),
    )
    subprocess.run(
        ["git", "add", generated.name, path.relative_to(tmp_path).as_posix()],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "register v3 target",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return path


def _committed_supersession_state(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict, dict]:
    """Commit an old registration, then commit its binding-only successor.

    Returns (predecessor_target, successor_target) shaped like sealed
    ticket targets for the same dataPointId.
    """
    generated = configure_registration_root(tmp_path, monkeypatch)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    commit_args = [
        "git",
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
    ]

    old_contract = {**_supersede_contract(), "conditional": "Synthetic condition"}
    old_reg = _registration(old_contract, "2026-07-10T05:03:56Z", _pin("b" * 40, 127))
    old_hash = old_reg["targetContentHash"]
    targets_dir = tmp_path / "records" / "targets"
    targets_dir.mkdir(parents=True, exist_ok=True)
    (targets_dir / f"2026-07-10-{old_hash}.json").write_bytes(
        canonical_bytes(old_reg["snapshot"]) + b"\n"
    )
    _write_block(
        generated,
        register_targets.ts_literal(
            register_targets._entry_for(
                old_contract, old_hash, "2026-07-10T05:03:56Z", None
            )
        ),
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [*commit_args, "old registration"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    new_contract = json.loads(json.dumps(old_contract))
    new_contract["sourceBinding"]["sourceUrl"] = (
        "https://legacy.abs.gov.au/statistics/labour"
    )
    new_reg = _registration(new_contract, "2026-07-11T05:03:56Z", _pin("c" * 40, 128))
    new_hash = new_reg["targetContentHash"]
    (targets_dir / f"2026-07-11-{new_hash}.json").write_bytes(
        canonical_bytes(new_reg["snapshot"]) + b"\n"
    )
    old_block = register_targets._generated_block(
        generated.read_text(), old_contract["dataPointId"]
    )
    new_block = register_targets.ts_literal(
        register_targets._entry_for(
            new_contract, new_hash, "2026-07-11T05:03:56Z", None
        )
    )
    generated.write_text(generated.read_text().replace(old_block, new_block, 1))
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [*commit_args, "supersede binding"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    def _sealed(contract: dict, content_hash: str, registered_at: str) -> dict:
        # Mirror the live hydrated ticket-target shape: unit surfaces as
        # targetUnit and the binding window lifts to the top level.
        hydrated = json.loads(json.dumps(contract))
        hydrated["targetUnit"] = hydrated.pop("unit")
        hydrated["expectedReleaseWindow"] = hydrated["sourceBinding"][
            "expectedReleaseWindow"
        ]
        return {
            **hydrated,
            "targetContentHash": content_hash,
            "registeredAtUtc": registered_at,
            "registrationCommit": "b" * 40,
            "registrationState": "preregistered",
            "targetRegistrationPath": (
                f"records/targets/{registered_at[:10]}-{content_hash}.json"
            ),
        }

    return (
        _sealed(old_contract, old_hash, "2026-07-10T05:03:56Z"),
        _sealed(new_contract, new_hash, "2026-07-11T05:03:56Z"),
    )


def test_ticket_supersession_refuses_hash_only_mismatch(tmp_path, monkeypatch) -> None:
    # Byte-identical targets with a differing registrationSetHash is
    # corrupt accounting, never a supersession — nothing changed to
    # authenticate.
    old_target, _ = _committed_supersession_state(tmp_path, monkeypatch)
    with pytest.raises(generation_tickets.TicketError, match="must be identical"):
        generation_tickets._require_superseding_targets(
            {"ticketId": "successor", "targets": [dict(old_target)]},
            {"ticketId": "predecessor", "targets": [dict(old_target)]},
            repo_root=tmp_path,
        )


def test_ticket_supersession_refuses_independent_parallel_registration(
    tmp_path, monkeypatch
) -> None:
    # A second registration for the same id committed WITHOUT replacing
    # the registry block is not a supersession lineage and must refuse.
    old_target, new_target = _committed_supersession_state(tmp_path, monkeypatch)
    laundered_contract = {
        **_supersede_contract(),
        "conditional": "Synthetic condition",
    }
    laundered_contract = json.loads(json.dumps(laundered_contract))
    laundered_contract["sourceBinding"]["sourceUrl"] = (
        "https://mirror.example.gov/statistics/labour"
    )
    laundered_reg = _registration(
        laundered_contract, "2026-07-12T05:03:56Z", _pin("d" * 40, 129)
    )
    laundered_hash = laundered_reg["targetContentHash"]
    laundered_path = (
        tmp_path / "records" / "targets" / f"2026-07-12-{laundered_hash}.json"
    )
    laundered_path.write_bytes(canonical_bytes(laundered_reg["snapshot"]) + b"\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "independent parallel registration",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    hydrated = json.loads(json.dumps(laundered_contract))
    hydrated["targetUnit"] = hydrated.pop("unit")
    hydrated["expectedReleaseWindow"] = hydrated["sourceBinding"][
        "expectedReleaseWindow"
    ]
    laundered_target = {
        **hydrated,
        "targetContentHash": laundered_hash,
        "registeredAtUtc": "2026-07-12T05:03:56Z",
        "registrationCommit": "b" * 40,
        "registrationState": "preregistered",
        "targetRegistrationPath": (f"records/targets/2026-07-12-{laundered_hash}.json"),
    }
    with pytest.raises(
        generation_tickets.TicketError,
        match="does not register its contract",
    ):
        generation_tickets._require_superseding_targets(
            {"ticketId": "successor", "targets": [laundered_target]},
            {"ticketId": "predecessor", "targets": [old_target]},
            repo_root=tmp_path,
            require_current=False,
        )


def test_find_ticket_successor_accepts_authenticated_cross_supersession(
    tmp_path, monkeypatch
) -> None:
    # The post-commit successor scan must admit the same authenticated
    # binding-only supersession that mint admits, via the time-stable
    # committed-introduction test on both sides.
    old_target, new_target = _committed_supersession_state(tmp_path, monkeypatch)

    predecessor = generation_tickets.mint_ticket(
        [old_target],
        {
            "promptMode": "fast",
            "codexModel": "gpt-5.5",
            "codexReasoningEffort": "low",
            "codexSandbox": "read-only",
            "codexNetwork": False,
            "reviewCodexModel": "gpt-5.5",
            "reviewCodexSearch": False,
            "timeoutSeconds": 3600,
        },
        nonce="a" * 64,
        minted_at_utc="2026-07-12T00:00:00Z",
        expires_hours=24,
        attempt=1,
        registration_set_hash="d" * 64,
    )
    successor = generation_tickets.mint_ticket(
        [new_target],
        {
            "promptMode": "fast",
            "codexModel": "gpt-5.5",
            "codexReasoningEffort": "high",
            "codexSandbox": "read-only",
            "codexNetwork": False,
            "reviewCodexModel": "gpt-5.5",
            "reviewCodexSearch": False,
            "timeoutSeconds": 3600,
        },
        nonce="b" * 64,
        minted_at_utc="2026-07-12T06:00:00Z",
        expires_hours=24,
        attempt=2,
        supersedes=predecessor["ticketId"],
        superseded_outcome={
            "outcome": "failed",
            "reason": "announcement fetch structurally impossible",
        },
        registration_set_hash="e" * 64,
        predecessor_ticket=predecessor,
        repo_root=tmp_path,
    )

    for ticket in (predecessor, successor):
        path = tmp_path.joinpath(
            *generation_tickets.ticket_record_path(ticket["ticketId"]).parts
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ticket, sort_keys=True) + "\n")

    found = generation_tickets.find_ticket_successor(predecessor["ticketId"], tmp_path)
    assert found is not None
    assert successor["ticketId"] in found


def test_ticket_supersession_accepts_binding_only_registration_supersession(
    tmp_path, monkeypatch
) -> None:
    old_target, new_target = _committed_supersession_state(tmp_path, monkeypatch)
    generation_tickets._require_superseding_targets(
        {"ticketId": "successor", "targets": [new_target]},
        {"ticketId": "predecessor", "targets": [old_target]},
        repo_root=tmp_path,
    )


def test_ticket_supersession_refuses_identity_changes(tmp_path, monkeypatch) -> None:
    old_target, new_target = _committed_supersession_state(tmp_path, monkeypatch)
    new_target = json.loads(json.dumps(new_target))
    new_target["period"] = "2026-08"
    with pytest.raises(generation_tickets.TicketError, match="must be identical"):
        generation_tickets._require_superseding_targets(
            {"ticketId": "successor", "targets": [new_target]},
            {"ticketId": "predecessor", "targets": [old_target]},
            repo_root=tmp_path,
        )


def test_ticket_supersession_refuses_stale_successor_contract(
    tmp_path, monkeypatch
) -> None:
    # Successor sealing a contract that is NOT the current registration
    # (hash drifted again after sealing) must refuse.
    old_target, new_target = _committed_supersession_state(tmp_path, monkeypatch)
    stale = json.loads(json.dumps(new_target))
    stale["targetContentHash"] = "e" * 64
    with pytest.raises(
        generation_tickets.TicketError,
        match="does not match the current registered contract",
    ):
        generation_tickets._require_superseding_targets(
            {"ticketId": "successor", "targets": [stale]},
            {"ticketId": "predecessor", "targets": [old_target]},
            repo_root=tmp_path,
        )


def test_ticket_supersession_refuses_uncommitted_predecessor(
    tmp_path, monkeypatch
) -> None:
    # A predecessor hash with no committed snapshot is an invention, not
    # a superseded registration.
    old_target, new_target = _committed_supersession_state(tmp_path, monkeypatch)
    invented = json.loads(json.dumps(old_target))
    invented["targetContentHash"] = "f" * 64
    with pytest.raises(
        generation_tickets.TicketError,
        match="not a committed registration",
    ):
        generation_tickets._require_superseding_targets(
            {"ticketId": "successor", "targets": [new_target]},
            {"ticketId": "predecessor", "targets": [invented]},
            repo_root=tmp_path,
        )


def test_pre_rename_pin_is_superseded_by_canonical_pin(tmp_path, monkeypatch) -> None:
    # Registrations recorded before the 2026-08-07 rename pin
    # PolicyEngine/ledger; an advancing reroll pinning the canonical
    # PolicyEngine/chronicle is the same upstream and must supersede.
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    old_pin = {**_pin("b" * 40, 127), "repo": "PolicyEngine/ledger"}
    _commit_v3_supersede_history(
        tmp_path, generated, contract, monkeypatch, "2026-07-10T05:03:56Z", old_pin
    )

    registration = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    rendered = register_targets.render_generated_targets(
        [registration], allow_published=True, allow_supersede=True
    )
    block = register_targets._generated_block(rendered, contract["dataPointId"])
    assert register_targets._block_value(block, "ledgerPinLineCount") == 128


def test_foreign_repo_pin_never_unifies_with_the_alias_set(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    old_pin = {**_pin("b" * 40, 127), "repo": "PolicyEngine/ledger"}
    _commit_v3_supersede_history(
        tmp_path, generated, contract, monkeypatch, "2026-07-10T05:03:56Z", old_pin
    )

    foreign_pin = {**_pin("d" * 40, 129), "repo": "attacker/chronicle"}
    foreign = _registration(contract, "2026-07-10T07:00:00Z", foreign_pin)
    with pytest.raises(register_targets.RegistrationError):
        register_targets.render_generated_targets(
            [foreign], allow_published=True, allow_supersede=True
        )


def test_plain_append_with_prefix_id_does_not_query_git(tmp_path, monkeypatch) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    longer_contract = {
        **contract,
        "dataPointId": f"{contract['dataPointId']}.suffix",
    }
    existing = _registration(
        longer_contract, "2026-07-10T05:03:56Z", _pin("b" * 40, 127)
    )
    _write_block(
        generated,
        register_targets.ts_literal(
            register_targets._entry_for(
                existing["contract"],
                existing["targetContentHash"],
                existing["registeredAtUtc"],
                existing["snapshot"]["ledgerPin"],
            )
        ),
    )

    def unexpected_git(*args: str) -> str:
        raise AssertionError(f"plain append queried git: {args}")

    monkeypatch.setattr(register_targets, "_git_output", unexpected_git)
    registration = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    rendered = register_targets.render_generated_targets(
        [registration], allow_published=True, allow_supersede=True
    )

    assert (
        len(register_targets._generated_blocks(rendered, contract["dataPointId"])) == 1
    )
    assert (
        len(
            register_targets._generated_blocks(rendered, longer_contract["dataPointId"])
        )
        == 1
    )


def test_unpublished_v2_target_is_superseded_by_a_pinned_v3_reroll(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _commit_v2_supersede_history(tmp_path, generated, contract, monkeypatch)

    v3 = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    rendered = register_targets.render_generated_targets(
        [v3], allow_published=True, allow_supersede=True
    )

    block = register_targets._generated_block(rendered, contract["dataPointId"])
    assert (
        register_targets._block_value(block, "targetContentHash")
        == v3["targetContentHash"]
    )
    assert register_targets._block_value(block, "ledgerPinLineCount") == 128
    assert (
        register_targets._block_value(block, "registeredAt") == "2026-07-10T06:17:27Z"
    )
    # Superseded in place, not appended: exactly one kind: target_registered.
    assert rendered.count('kind: "target_registered"') == 1


def test_committed_docket_template_authorizes_source_binding_upgrade(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    old_contract, upgraded_contract = _binding_upgrade_contracts()
    _commit_v2_supersede_history(tmp_path, generated, old_contract, monkeypatch)
    docket = _write_docket(tmp_path, [_docket_entry(upgraded_contract)])
    _commit_files(tmp_path, [docket], "upgrade ABS source binding")

    reroll = _registration(
        upgraded_contract,
        "2026-07-10T06:17:27Z",
        _pin("c" * 40, 128),
    )
    rendered = register_targets.render_generated_targets(
        [reroll], allow_published=True, allow_supersede=True
    )

    blocks = register_targets._generated_blocks(
        rendered, upgraded_contract["dataPointId"]
    )
    assert len(blocks) == 1
    assert (
        register_targets._block_value(blocks[0], "sourceBinding")
        == reroll["contract"]["sourceBinding"]
    )
    assert rendered.count('kind: "target_registered"') == 1


def test_binding_upgrade_refuses_wave_invented_binding(tmp_path, monkeypatch) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    old_contract, upgraded_contract = _binding_upgrade_contracts()
    _commit_v2_supersede_history(tmp_path, generated, old_contract, monkeypatch)
    docket = _write_docket(tmp_path, [_docket_entry(upgraded_contract)])
    _commit_files(tmp_path, [docket], "commit reviewed ABS binding")
    invented = json.loads(json.dumps(upgraded_contract))
    invented["sourceBinding"]["sourceUrl"] = "https://invented.example/abs-unemployment"
    invented["sourceBinding"]["allowedHosts"] = ["invented.example"]
    reroll = _registration(invented, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_binding_upgrade_refuses_uncommitted_docket_authority(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    old_contract, upgraded_contract = _binding_upgrade_contracts()
    _commit_v2_supersede_history(tmp_path, generated, old_contract, monkeypatch)
    docket = _write_docket(tmp_path, [_docket_entry(old_contract)])
    _commit_files(tmp_path, [docket], "commit original ABS binding")
    # The working tree advertises the upgrade, but trusted HEAD still binds A.
    _write_docket(tmp_path, [_docket_entry(upgraded_contract)])
    reroll = _registration(
        upgraded_contract,
        "2026-07-10T06:17:27Z",
        _pin("c" * 40, 128),
    )

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_binding_upgrade_refuses_identity_drift(tmp_path, monkeypatch) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    old_contract, upgraded_contract = _binding_upgrade_contracts()
    _commit_v2_supersede_history(tmp_path, generated, old_contract, monkeypatch)
    docket = _write_docket(tmp_path, [_docket_entry(upgraded_contract)])
    _commit_files(tmp_path, [docket], "commit reviewed ABS binding")
    drifted = {**upgraded_contract, "unit": "count"}
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    assert register_targets._binding_is_committed_template(drifted, head)
    reroll = _registration(drifted, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


@pytest.mark.parametrize("abuse", ["extra", "missing-template-key"])
def test_binding_upgrade_refuses_derived_key_abuse(
    tmp_path, monkeypatch, abuse
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    old_contract, upgraded_contract = _binding_upgrade_contracts()
    _commit_v2_supersede_history(tmp_path, generated, old_contract, monkeypatch)
    docket = _write_docket(tmp_path, [_docket_entry(upgraded_contract)])
    _commit_files(tmp_path, [docket], "commit reviewed ABS binding")
    abused = json.loads(json.dumps(upgraded_contract))
    if abuse == "extra":
        abused["sourceBinding"]["waveOverride"] = True
    else:
        abused["sourceBinding"].pop("field")
    reroll = _registration(abused, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_binding_upgrade_refuses_ambiguous_template(tmp_path, monkeypatch) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    old_contract, upgraded_contract = _binding_upgrade_contracts()
    _commit_v2_supersede_history(tmp_path, generated, old_contract, monkeypatch)
    entry = _docket_entry(upgraded_contract)
    docket = _write_docket(tmp_path, [entry, entry])
    _commit_files(tmp_path, [docket], "commit ambiguous ABS bindings")
    reroll = _registration(
        upgraded_contract,
        "2026-07-10T06:17:27Z",
        _pin("c" * 40, 128),
    )

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_binding_upgrade_refuses_stale_binding_projection(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    old_contract, upgraded_contract = _binding_upgrade_contracts()
    _commit_v2_supersede_history(tmp_path, generated, old_contract, monkeypatch)
    docket = _write_docket(tmp_path, [_docket_entry(upgraded_contract)])
    _commit_files(tmp_path, [docket], "commit reviewed ABS binding")
    stale = json.loads(json.dumps(old_contract))
    # Enter the changed-contract lane while retaining binding A's projection.
    # An exactly byte-equal A contract remains allowed by the required fast path.
    stale["sourceBinding"]["expectedReleaseWindow"]["end"] = "2026-08-28"
    reroll = _registration(stale, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_binding_upgrade_of_published_head_target_is_refused(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    old_contract, upgraded_contract = _binding_upgrade_contracts()
    registered_at = "2026-07-10T05:03:56Z"
    _commit_v2_supersede_history(
        tmp_path, generated, old_contract, monkeypatch, registered_at
    )
    old_registration = _registration(old_contract, registered_at, None)
    published = register_targets._entry_for(
        old_registration["contract"],
        old_registration["targetContentHash"],
        registered_at,
        None,
    )
    published["registrationState"] = "published"
    _write_block(generated, register_targets.ts_literal(published))
    docket = _write_docket(tmp_path, [_docket_entry(upgraded_contract)])
    _commit_files(tmp_path, [generated, docket], "publish target and upgrade binding")
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    assert register_targets._binding_is_committed_template(upgraded_contract, head)
    reroll = _registration(
        upgraded_contract,
        "2026-07-10T06:17:27Z",
        _pin("c" * 40, 128),
    )

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


@pytest.mark.usefixtures("resolver_admits")
def test_adoption_writes_an_authorizing_template_and_bind_accepts_it(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _commit_files(tmp_path, [generated], "base generated targets")

    contract = _supersede_contract()
    docket = _write_docket(tmp_path, [])
    records = tmp_path / "records" / "thesis-analyst"
    run_dir = records / "2026-07-10" / "adoption-fixture"
    run_dir.mkdir(parents=True)
    cells_path = run_dir / "cells.with_activity.json"
    cells_path.write_text(json.dumps([{"slug": contract["catalogSlug"]}]) + "\n")
    manifest = {
        "series": contract["series"],
        "period": contract["period"],
        "ok": True,
        "cellsPath": cells_path.relative_to(tmp_path).as_posix(),
        "targetContext": {
            "valueScale": contract["valueScale"],
            "targetUnit": contract["unit"],
            "country": contract["country"],
            "sourceBinding": contract["sourceBinding"],
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest) + "\n")
    legacy_run_dir = records / "2026-07-10" / "000-legacy-without-binding"
    legacy_run_dir.mkdir()
    legacy_cells_path = legacy_run_dir / "cells.with_activity.json"
    legacy_cells_path.write_text(json.dumps([{"slug": contract["catalogSlug"]}]) + "\n")
    legacy_manifest = {
        **manifest,
        "cellsPath": legacy_cells_path.relative_to(tmp_path).as_posix(),
        "targetContext": {
            key: value
            for key, value in manifest["targetContext"].items()
            if key != "sourceBinding"
        },
    }
    (legacy_run_dir / "manifest.json").write_text(json.dumps(legacy_manifest) + "\n")
    monkeypatch.setattr(adopt_proven_series, "ROOT", tmp_path)
    monkeypatch.setattr(adopt_proven_series, "REGISTRY", docket)
    monkeypatch.setattr(adopt_proven_series, "RECORDS", records)
    monkeypatch.setattr(
        adopt_proven_series, "scored_slugs", lambda: {contract["catalogSlug"]}
    )
    monkeypatch.setattr(sys, "argv", ["adopt_proven_series.py"])

    assert adopt_proven_series.main() == 0

    [adopted] = json.loads(docket.read_text())["series"]
    template = adopted["extras"]["sourceBinding"]
    template_keys = {
        "adapter",
        "sourceUrl",
        "sourceSeriesId",
        "field",
        "table",
        "transform",
        "releasePolicy",
    }
    assert set(template) == template_keys
    assert template == _binding_template(contract["sourceBinding"])

    monkeypatch.setattr(
        register_targets,
        "load_ledger_pin_binding",
        lambda: _pin("c" * 40, 128),
    )
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps({"targets": [_target_from_contract(contract)]}) + "\n"
    )
    [registration] = register_targets.register(
        targets_path, dt.date(2026, 7, 10), "2026-07-10T06:17:27Z"
    )
    _commit_files(
        tmp_path,
        [docket, generated, registration["path"]],
        "adopt series and register next target",
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()

    assert register_targets._binding_is_committed_template(
        registration["contract"], head
    )
    metadata = register_targets.bind_registration_commits(targets_path, head)
    assert metadata["registrationCommits"] == [head]


@pytest.mark.usefixtures("resolver_admits")
def test_bind_rejects_first_registration_after_head_template_changes(
    tmp_path, monkeypatch
) -> None:
    contract = _supersede_contract()
    _, docket, targets_path, registration = _commit_first_registration(
        tmp_path, monkeypatch, contract
    )
    authorized_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    assert register_targets._binding_is_committed_template(
        registration["contract"], authorized_head
    )

    changed_template = json.loads(json.dumps(contract))
    changed_template["sourceBinding"]["table"] = "Replacement ABS table"
    _write_docket(tmp_path, [_docket_entry(changed_template)])
    _commit_files(tmp_path, [docket], "change template during registration wave")
    rebased_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    targets_before = targets_path.read_bytes()

    with pytest.raises(register_targets.RegistrationError) as error:
        register_targets.bind_registration_commits(targets_path, rebased_head)

    assert contract["dataPointId"] in str(error.value)
    assert contract["series"] in str(error.value)
    assert targets_path.read_bytes() == targets_before


@pytest.mark.usefixtures("resolver_admits")
def test_bind_rejects_ambiguous_head_template(tmp_path, monkeypatch) -> None:
    contract = _supersede_contract()
    _, docket, targets_path, _ = _commit_first_registration(
        tmp_path, monkeypatch, contract
    )
    entry = _docket_entry(contract)
    _write_docket(tmp_path, [entry, entry])
    _commit_files(tmp_path, [docket], "make template ambiguous")

    with pytest.raises(register_targets.RegistrationError, match="ambiguous"):
        register_targets.bind_registration_commits(targets_path)


@pytest.mark.parametrize(
    ("calendar_case", "message"),
    [
        ("missing-docket-entry", "exactly one committed docket template"),
        ("template-less-docket-entry", "committed sourceBinding template"),
        ("tampered-release-date", "disagrees with the committed docket calendar"),
    ],
)
def test_bind_native_registration_requires_committed_calendar_authority(
    tmp_path, monkeypatch, calendar_case, message
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    _, contract = _binding_upgrade_contracts()
    contract = json.loads(json.dumps(contract))
    contract["sourceBinding"]["adapter"] = "abs-data-api"
    contract["sourceBinding"]["expectedReleaseWindow"] = {
        "start": "2026-08-20",
        "end": "2026-08-20",
    }
    calendar_url = (
        "https://www.abs.gov.au/statistics/labour/"
        "employment-and-unemployment/labour-force-australia"
    )
    entries: list[dict] = []
    if calendar_case != "missing-docket-entry":
        entry = (
            {"series": contract["series"]}
            if calendar_case == "template-less-docket-entry"
            else _docket_entry(contract)
        )
        entry["releaseCalendarUrl"] = calendar_url
        entry["releaseDates"] = {
            "2026-07": (
                "2026-08-21"
                if calendar_case == "tampered-release-date"
                else "2026-08-20"
            )
        }
        entries.append(entry)
    docket = _write_docket(tmp_path, entries)
    registration = _registration(contract, "2026-07-25T14:32:05Z", _pin("c" * 40, 128))
    snapshot, targets_path = _install_registration_for_bind(
        tmp_path, generated, registration
    )
    payload = json.loads(targets_path.read_text())
    payload["targets"][0]["releaseCalendarUrl"] = calendar_url
    targets_path.write_text(json.dumps(payload, indent=2) + "\n")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _commit_files(
        tmp_path,
        [generated, docket, snapshot],
        f"commit native registration with {calendar_case}",
    )

    with pytest.raises(register_targets.RegistrationError, match=message):
        register_targets.bind_registration_commits(targets_path)


@pytest.mark.parametrize(
    ("calendar_case", "message"),
    [
        ("valid", None),
        ("missing-docket-entry", "exactly one committed docket template"),
        ("template-less-docket-entry", "committed sourceBinding template"),
        ("missing-seed-period", "committed docket seedPeriod"),
        ("tampered-release-date", "committed docket calendar"),
        ("tampered-calendar-url", "releaseCalendarUrl"),
    ],
)
def test_bind_recurring_seed_requires_committed_calendar_authority(
    tmp_path, monkeypatch, calendar_case, message
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    _, contract = _binding_upgrade_contracts()
    contract = json.loads(json.dumps(contract))
    contract.update(
        {
            "series": "bls.fixture.seed",
            "period": "2026-07",
            "seedPeriod": "2026-07",
            "catalogSlug": "bls-fixture-seed-july-2026",
            "dataPointId": "bls.fixture.seed.2026_07.first_print",
            "country": "US",
        }
    )
    contract["sourceBinding"].update(
        {
            "adapter": "alfred-fred",
            "sourceUrl": (
                "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=FIXTURE"
            ),
            "sourceSeriesId": "FIXTURE",
            "field": "FIXTURE",
            "expectedReleaseWindow": {
                "start": "2026-08-20",
                "end": "2026-08-20",
            },
            "allowedHosts": ["alfred.stlouisfed.org"],
        }
    )
    calendar_url = "https://www.bls.gov/schedule/news_release/fixture.htm"
    entries: list[dict] = []
    if calendar_case != "missing-docket-entry":
        entry = (
            {"series": contract["series"]}
            if calendar_case == "template-less-docket-entry"
            else _docket_entry(contract)
        )
        if calendar_case != "missing-seed-period":
            entry["seedPeriod"] = contract["seedPeriod"]
        entry["releaseCalendarUrl"] = calendar_url
        entry["releaseDates"] = {
            contract["period"]: (
                "2026-08-21"
                if calendar_case == "tampered-release-date"
                else "2026-08-20"
            )
        }
        entries.append(entry)
    docket = _write_docket(tmp_path, entries)
    registration = _registration(contract, "2026-07-25T14:32:05Z", _pin("c" * 40, 128))
    snapshot, targets_path = _install_registration_for_bind(
        tmp_path, generated, registration
    )
    payload = json.loads(targets_path.read_text())
    payload["targets"][0]["releaseCalendarUrl"] = (
        "https://wrong.example/calendar"
        if calendar_case == "tampered-calendar-url"
        else calendar_url
    )
    targets_path.write_text(json.dumps(payload, indent=2) + "\n")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _commit_files(
        tmp_path,
        [generated, docket, snapshot],
        f"commit recurring seed registration with {calendar_case}",
    )

    if message is None:
        metadata = register_targets.bind_registration_commits(targets_path)
        assert len(metadata["registrationCommits"]) == 1
    else:
        with pytest.raises(register_targets.RegistrationError, match=message):
            register_targets.bind_registration_commits(targets_path)


@pytest.mark.parametrize(
    "entry_extras",
    [
        pytest.param(None, id="extras-absent"),
        pytest.param(
            {"valueScale": 0.001, "targetUnit": "thousands"},
            id="source-binding-key-absent",
        ),
    ],
)
def test_bind_accepts_docket_series_without_source_binding_template(
    tmp_path, monkeypatch, entry_extras
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    docket_entry = {
        "series": "us.dol.initial_claims.sa",
        "cadence": "weekly",
        "slug": "initial-claims-week-{period}",
    }
    if entry_extras is not None:
        docket_entry["extras"] = entry_extras
    docket = _write_docket(
        tmp_path,
        [docket_entry],
    )
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _commit_files(tmp_path, [generated, docket], "commit legacy docket entry")
    monkeypatch.setattr(
        register_targets,
        "load_ledger_pin_binding",
        lambda: _pin("c" * 40, 128),
    )
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "series": "us.dol.initial_claims.sa",
                        "period": "week_2030-01-05",
                        "catalogSlug": "initial-claims-week-2030-01-05",
                        "targetUnit": "thousands",
                        "valueScale": 0.001,
                    }
                ]
            }
        )
        + "\n"
    )
    [registration] = register_targets.register(
        targets_path, dt.date(2030, 1, 6), "2030-01-06T14:32:05Z"
    )
    _commit_files(
        tmp_path,
        [generated, registration["path"]],
        "register initial claims target",
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()

    assert not register_targets._binding_is_committed_template(
        registration["contract"], head
    )
    metadata = register_targets.bind_registration_commits(targets_path, head)

    target = json.loads(targets_path.read_text())["targets"][0]
    assert target["registrationCommit"] == head
    assert metadata["sourceCommit"] == head
    assert metadata["registrationCommits"] == [head]


@pytest.mark.usefixtures("resolver_admits")
@pytest.mark.parametrize(
    ("malformation", "message"),
    [
        ("non-list", "series list"),
        ("missing-series", "entry 0"),
        ("non-dict-extras", "sourceBinding template is malformed"),
        ("list-source-binding", "sourceBinding template is malformed"),
        ("null-source-binding", "sourceBinding template is malformed"),
    ],
)
def test_bind_rejects_malformed_head_docket(
    tmp_path, monkeypatch, malformation, message
) -> None:
    contract = _supersede_contract()
    _, docket, targets_path, _ = _commit_first_registration(
        tmp_path, monkeypatch, contract
    )
    if malformation == "non-list":
        malformed = {"series": {}}
    elif malformation == "missing-series":
        malformed = {"series": [{"extras": {}}]}
    elif malformation == "non-dict-extras":
        malformed = {"series": [{"series": contract["series"], "extras": []}]}
    else:
        malformed = {
            "series": [
                {
                    "series": contract["series"],
                    "extras": {
                        "sourceBinding": (
                            [] if malformation == "list-source-binding" else None
                        )
                    },
                }
            ]
        }
    docket.write_text(json.dumps(malformed) + "\n")
    _commit_files(tmp_path, [docket], f"commit {malformation} docket")

    with pytest.raises(register_targets.RegistrationError, match=message):
        register_targets.bind_registration_commits(targets_path)


@pytest.mark.parametrize("duplicate", ["series", "sourceUrl"])
def test_duplicate_docket_keys_fail_closed_for_supersede_and_bind(
    tmp_path, monkeypatch, duplicate
) -> None:
    old_contract, upgraded_contract = _binding_upgrade_contracts()

    supersede_root = tmp_path / "supersede"
    supersede_root.mkdir()
    generated = configure_registration_root(supersede_root, monkeypatch)
    _commit_v2_supersede_history(supersede_root, generated, old_contract, monkeypatch)
    docket = supersede_root / "scripts" / "docket_series.json"
    docket.parent.mkdir(parents=True)
    docket.write_text(_docket_with_duplicate_key(upgraded_contract, duplicate))
    _commit_files(supersede_root, [docket], f"commit duplicate {duplicate}")
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=supersede_root, text=True
    ).strip()
    assert not register_targets._binding_is_committed_template(upgraded_contract, head)
    reroll = _registration(
        upgraded_contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128)
    )
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )

    bind_root = tmp_path / "bind"
    bind_root.mkdir()
    generated = configure_registration_root(bind_root, monkeypatch)
    docket = bind_root / "scripts" / "docket_series.json"
    docket.parent.mkdir(parents=True)
    docket.write_text(_docket_with_duplicate_key(upgraded_contract, duplicate))
    registration = _registration(
        upgraded_contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128)
    )
    snapshot, targets_path = _install_registration_for_bind(
        bind_root, generated, registration
    )
    subprocess.run(["git", "init"], cwd=bind_root, check=True, capture_output=True)
    _commit_files(
        bind_root,
        [generated, docket, snapshot],
        f"commit registration with duplicate {duplicate}",
    )
    targets_before = targets_path.read_bytes()

    with pytest.raises(register_targets.RegistrationError, match="duplicate JSON key"):
        register_targets.bind_registration_commits(targets_path)
    assert targets_path.read_bytes() == targets_before


def test_supersede_refuses_a_published_target(tmp_path, monkeypatch) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    published = register_targets._entry_for(
        contract, "b" * 64, "2026-07-10T05:03:56Z", None
    )
    published["registrationState"] = "published"
    _write_block(generated, register_targets.ts_literal(published))

    v3 = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [v3], allow_published=True, allow_supersede=True
        )


def test_supersede_refuses_a_changed_contract_field(tmp_path, monkeypatch) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _write_block(
        generated, _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)
    )

    tampered = {**contract, "unit": "count"}  # what is forecast changed
    v3 = _registration(tampered, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [v3], allow_published=True, allow_supersede=True
        )


def test_supersede_refuses_an_unbacked_ts_only_block(tmp_path, monkeypatch) -> None:
    # A generated block with no matching snapshot on disk is tampering, not a
    # genuine re-roll, and must fail closed even when it otherwise tightens.
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    unbacked = register_targets.ts_literal(
        register_targets._entry_for(contract, "b" * 64, "2026-07-10T05:03:56Z", None)
    )
    _write_block(generated, unbacked)

    v3 = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [v3], allow_published=True, allow_supersede=True
        )


def test_supersede_refuses_a_non_advancing_timestamp(tmp_path, monkeypatch) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _write_block(
        generated, _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)
    )

    # Same instant — not strictly later.
    v3 = _registration(contract, "2026-07-10T05:03:56Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [v3], allow_published=True, allow_supersede=True
        )


def test_supersede_refuses_a_shrinking_ledger_pin(tmp_path, monkeypatch) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _write_block(
        generated,
        _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", _pin("c" * 40, 130)),
    )

    # Later timestamp but a SMALLER pinned state — refuse (would relax the
    # backfill boundary).
    v3_new = _registration(contract, "2026-07-10T06:17:27Z", _pin("d" * 40, 129))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [v3_new], allow_published=True, allow_supersede=True
        )


def test_supersede_is_refused_without_the_flag(tmp_path, monkeypatch) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _write_block(
        generated, _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)
    )

    v3 = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    # The bind/publisher passes never supersede.
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets([v3], allow_published=True)


def test_attack_v2_supersede_rejects_boolean_ledger_pin_count(
    tmp_path, monkeypatch
) -> None:
    """A JSON boolean must not disable the numeric N5 backfill boundary."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _write_block(
        generated, _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)
    )

    # bool is an int subclass in Python. If accepted, TypeScript renders
    # ledgerPinLineCount: true and the scorer's typeof === "number" guard skips
    # the backfill check entirely.
    boolean_pin = _pin("c" * 40, True)
    with pytest.raises(register_targets.RegistrationError, match="lineCount"):
        _registration(contract, "2026-07-10T06:17:27Z", boolean_pin)


def test_attack_supersede_rejects_same_count_non_descendant_pin(
    tmp_path, monkeypatch
) -> None:
    """Equal line counts do not prove that two ledger states have the same bytes."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    old_pin = _pin("c" * 40, 130)
    _write_block(
        generated,
        _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", old_pin),
    )

    unrelated_pin = {
        **_pin("d" * 40, 130),
        # Same repo, branch, and count, but demonstrably different ledger bytes.
        "jsonlSha256": "b" * 64,
    }
    reroll = _registration(contract, "2026-07-10T06:17:27Z", unrelated_pin)
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_authenticated_v3_target_accepts_an_advancing_pin(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _commit_v3_supersede_history(
        tmp_path,
        generated,
        contract,
        monkeypatch,
        "2026-07-10T06:17:27Z",
        _pin("c" * 40, 130),
    )
    reroll = _registration(contract, "2026-07-10T07:17:27Z", _pin("d" * 40, 131))

    rendered = register_targets.render_generated_targets(
        [reroll], allow_published=True, allow_supersede=True
    )

    block = register_targets._generated_block(rendered, contract["dataPointId"])
    assert register_targets._block_value(block, "ledgerPinLineCount") == 131


def test_authenticated_v3_target_rejects_dropping_catalog_commitment(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _commit_v3_supersede_history(
        tmp_path,
        generated,
        contract,
        monkeypatch,
        "2026-07-10T06:17:27Z",
        _catalog_pin("c" * 40, 130),
    )
    reroll = _registration(
        contract,
        "2026-07-10T07:17:27Z",
        _pin("d" * 40, 131),
    )

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


@pytest.mark.parametrize(
    "new_pin",
    [
        _pin("d" * 40, 129),
        {**_pin("d" * 40, 130), "jsonlSha256": "b" * 64},
        {**_pin("d" * 40, 131), "repo": "Attacker/ledger"},
        {**_pin("d" * 40, 131), "branch": "untrusted-history"},
    ],
)
def test_authenticated_v3_target_rejects_a_relaxed_or_unrelated_pin(
    tmp_path, monkeypatch, new_pin
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _commit_v3_supersede_history(
        tmp_path,
        generated,
        contract,
        monkeypatch,
        "2026-07-10T06:17:27Z",
        _pin("c" * 40, 130),
    )
    reroll = _registration(contract, "2026-07-10T07:17:27Z", new_pin)

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_attack_supersede_rejects_country_change(tmp_path, monkeypatch) -> None:
    """Country is part of the canonical target contract and forecast identity."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _write_block(
        generated, _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)
    )

    changed = {**contract, "country": "US"}
    reroll = _registration(changed, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_attack_published_state_rollback_cannot_be_superseded(
    tmp_path, monkeypatch
) -> None:
    """A retained preregistration snapshot must not erase prior consumption."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    registered_at = "2026-07-10T05:03:56Z"
    preregistered = _backed_block(tmp_path, contract, registered_at, None)
    content_hash = register_targets._block_value(preregistered, "targetContentHash")
    published = register_targets._entry_for(contract, content_hash, registered_at, None)
    published["registrationState"] = "published"
    _write_block(generated, register_targets.ts_literal(published))

    # A TS-only rollback to the genuine retained preregistration is byte-exact
    # against its snapshot. The current-state check must not forget that this
    # target was already consumed.
    _write_block(generated, preregistered)
    reroll = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_attack_snapshot_timestamp_rewrite_cannot_backdate_supersede(
    tmp_path, monkeypatch
) -> None:
    """The timestamp-excluded v2 hash cannot authenticate registration time."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    genuine_time = "2026-07-10T10:00:00Z"
    genuine_block = _backed_block(tmp_path, contract, genuine_time, None)
    content_hash = register_targets._block_value(genuine_block, "targetContentHash")
    snapshot_path = next((tmp_path / "records" / "targets").glob("*.json"))
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["registeredAtUtc"] = "2026-07-10T01:00:00Z"
    snapshot_path.write_bytes(canonical_bytes(snapshot) + b"\n")
    forged_earlier_block = register_targets.ts_literal(
        register_targets._entry_for(
            snapshot["targets"][0],
            content_hash,
            snapshot["registeredAtUtc"],
            None,
        )
    )
    _write_block(generated, forged_earlier_block)

    # 05:00 is later than the forged timestamp but earlier than the genuine
    # 10:00 registration. A self-consistency check alone cannot detect this.
    reroll = _registration(contract, "2026-07-10T05:00:00Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_attack_duplicate_published_block_prevents_supersede(
    tmp_path, monkeypatch
) -> None:
    """A noncanonically formatted duplicate must not evade the block count."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    registered_at = "2026-07-10T05:03:56Z"
    _commit_v2_supersede_history(
        tmp_path, generated, contract, monkeypatch, registered_at
    )
    source = generated.read_text()
    old_block = register_targets._generated_block(source, contract["dataPointId"])
    old_hash = register_targets._block_value(old_block, "targetContentHash")
    published = register_targets._entry_for(contract, old_hash, registered_at, None)
    published["registrationState"] = "published"
    noncanonical_duplicate = register_targets.ts_literal(published).replace(
        "  {\n", "  { \n", 1
    )
    closer = source.rindex("] satisfies")
    generated.write_text(
        source[:closer] + noncanonical_duplicate + "\n" + source[closer:]
    )

    reroll = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_attack_published_retry_rejects_dropped_pin_boundary(
    tmp_path, monkeypatch
) -> None:
    """A published block may not drop the fields the scorer enforces."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    registered_at = "2026-07-10T05:03:56Z"
    pin = _pin("c" * 40, 130)
    registration = _registration(contract, registered_at, pin)
    content_hash = registration["targetContentHash"]
    targets_dir = tmp_path / "records" / "targets"
    targets_dir.mkdir(parents=True, exist_ok=True)
    (targets_dir / f"2026-07-10-{content_hash}.json").write_bytes(
        canonical_bytes(registration["snapshot"]) + b"\n"
    )
    published = register_targets._entry_for(
        registration["contract"], content_hash, registered_at, pin
    )
    published["registrationState"] = "published"
    published.pop("ledgerPinSha")
    published.pop("ledgerPinLineCount")
    _write_block(generated, register_targets.ts_literal(published))

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [registration], allow_published=True, allow_supersede=True
        )


def test_attack_v3_publication_preserves_pin_boundary(tmp_path, monkeypatch) -> None:
    """Finalizing a v3 registration must carry its N5 fields into TypeScript."""
    configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    registered_at = "2026-07-10T05:03:56Z"
    pin = _pin("c" * 40, 130)
    registration = _registration(contract, registered_at, pin)
    content_hash = registration["targetContentHash"]
    relative = pathlib.Path("records/targets") / f"2026-07-10-{content_hash}.json"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(registration["snapshot"]) + b"\n")
    cell = {
        "slug": contract["catalogSlug"],
        "dataPointId": contract["dataPointId"],
        "unit": contract["unit"],
        "country": contract["country"],
        "resolutionDate": "2026-08-13",
        "resolutionSource": "ABS Labour Force",
        "resolutionSourceUrl": contract["sourceBinding"]["sourceUrl"],
        "resolutionRule": "First print.",
        "title": "Australian unemployment",
        "targetRegistrationPath": relative.as_posix(),
        "targetContentHash": content_hash,
        "registeredAtUtc": registered_at,
    }

    finalized = register_targets.registration_for_cell(cell)
    assert finalized["ledgerPinSha"] == pin["sha"]
    assert finalized["ledgerPinLineCount"] == pin["lineCount"]
    published = generate_ledger_targets.entry_for(cell, finalized)
    assert published["ledgerPinSha"] == pin["sha"]
    assert published["ledgerPinLineCount"] == pin["lineCount"]


def test_attack_self_consistent_uncommitted_snapshot_can_back_a_supersede(
    tmp_path, monkeypatch
) -> None:
    """An uncommitted snapshot cannot authenticate a supersession."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    forged = _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)
    content_hash = register_targets._block_value(forged, "targetContentHash")
    original_path = next((tmp_path / "records" / "targets").glob("*.json"))
    forged_path = original_path.with_name(f"forged-{content_hash}.json")
    original_path.rename(forged_path)
    _write_block(generated, forged)

    reroll = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )
    assert forged_path.name.startswith("forged-")


def test_attack_comment_decoy_cannot_misdirect_the_replacement(
    tmp_path, monkeypatch
) -> None:
    """Block bytes hidden in a comment must not absorb the supersession."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _commit_v2_supersede_history(tmp_path, generated, contract, monkeypatch)

    old_block = register_targets._generated_block(
        generated.read_text(), contract["dataPointId"]
    )
    generated.write_text(
        generated.read_text().replace(
            "export const GENERATED_FORECAST_TARGETS = [",
            f"/*\n{old_block}\n*/\nexport const GENERATED_FORECAST_TARGETS = [",
            1,
        )
    )
    subprocess.run(
        ["git", "add", generated.name],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "decoy comment",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    reroll = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="did not replace"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )
    # The real preregistration block is untouched on disk.
    assert (
        register_targets._generated_block(
            generated.read_text(), contract["dataPointId"]
        )
        == old_block
    )


def test_attack_contract_canonicalization_rejects_semantic_changes(
    tmp_path, monkeypatch
) -> None:
    """Nested transform, Unicode, and null/absent changes must all refuse."""
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    contract["sourceBinding"] = {
        **contract["sourceBinding"],
        "label": "Caf\u00e9",
        "nullable": None,
    }
    old_block = _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)

    mutations = []
    changed_transform = json.loads(json.dumps(contract))
    changed_transform["sourceBinding"]["transform"]["factor"] = 2
    mutations.append(changed_transform)
    changed_unicode = json.loads(json.dumps(contract))
    changed_unicode["sourceBinding"]["label"] = "Cafe\u0301"
    mutations.append(changed_unicode)
    absent_instead_of_null = json.loads(json.dumps(contract))
    absent_instead_of_null["sourceBinding"].pop("nullable")
    mutations.append(absent_instead_of_null)

    for changed in mutations:
        _write_block(generated, old_block)
        reroll = _registration(changed, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
        with pytest.raises(register_targets.RegistrationError, match="not the exact"):
            register_targets.render_generated_targets(
                [reroll], allow_published=True, allow_supersede=True
            )


def test_attack_canonical_key_order_and_integral_float_are_equivalent(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _commit_v2_supersede_history(tmp_path, generated, contract, monkeypatch)
    equivalent = {
        **contract,
        "valueScale": 1,
        "sourceBinding": dict(reversed(contract["sourceBinding"].items())),
    }
    equivalent["sourceBinding"]["transform"] = {
        "factor": 1.0,
        "operation": "multiply",
    }
    reroll = _registration(equivalent, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))

    rendered = register_targets.render_generated_targets(
        [reroll], allow_published=True, allow_supersede=True
    )
    block = register_targets._generated_block(rendered, contract["dataPointId"])
    assert (
        register_targets._block_value(block, "targetContentHash")
        == reroll["targetContentHash"]
    )


@pytest.mark.parametrize(
    "trick",
    [
        "2026-07-10T06:03:56+01:00",
        "2026-07-10T05:03:56.001Z",
        "2026-07-10T05:03:56z",
    ],
)
def test_attack_timestamp_format_tricks_cannot_supersede(
    tmp_path, monkeypatch, trick
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _write_block(
        generated, _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)
    )
    reroll = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    reroll["registeredAtUtc"] = trick

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_attack_snapshot_timestamp_mismatch_cannot_back_supersede(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    old_block = _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)
    snapshot_path = next((tmp_path / "records" / "targets").glob("*.json"))
    snapshot = json.loads(snapshot_path.read_text())
    # registeredAtUtc is excluded from the v2 content hash, so the filename and
    # schema-aware hash remain valid; the render-back/timestamp checks must catch it.
    snapshot["registeredAtUtc"] = "2026-07-10T04:03:56Z"
    snapshot_path.write_bytes(canonical_bytes(snapshot) + b"\n")
    _write_block(generated, old_block)

    reroll = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.render_generated_targets(
            [reroll], allow_published=True, allow_supersede=True
        )


def test_attack_publisher_materialization_cannot_supersede(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    _write_block(
        generated, _backed_block(tmp_path, contract, "2026-07-10T05:03:56Z", None)
    )
    reroll = _registration(contract, "2026-07-10T06:17:27Z", _pin("c" * 40, 128))
    path = (
        tmp_path
        / "records"
        / "targets"
        / f"2026-07-10-{reroll['targetContentHash']}.json"
    )
    path.write_bytes(canonical_bytes(reroll["snapshot"]) + b"\n")

    with pytest.raises(register_targets.RegistrationError, match="not the exact"):
        register_targets.materialize_registration_snapshots([path])


@pytest.mark.usefixtures("resolver_admits")
def test_attack_register_supersede_retains_old_snapshot_and_one_block(
    tmp_path, monkeypatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    contract = _supersede_contract()
    registered_at = "2026-07-10T05:03:56Z"
    old_path = _commit_v2_supersede_history(
        tmp_path, generated, contract, monkeypatch, registered_at
    )
    old_bytes = old_path.read_bytes()
    pin = _pin("c" * 40, 128)
    monkeypatch.setattr(register_targets, "load_ledger_pin_binding", lambda: pin)
    target = {
        "series": contract["series"],
        "period": contract["period"],
        "catalogSlug": contract["catalogSlug"],
        "dataPointId": contract["dataPointId"],
        "country": contract["country"],
        "targetUnit": contract["unit"],
        "valueScale": contract["valueScale"],
        "sourceBinding": contract["sourceBinding"],
        "expectedReleaseWindow": contract["sourceBinding"]["expectedReleaseWindow"],
    }
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [target]}))

    [reroll] = register_targets.register(
        targets_path, dt.date(2026, 7, 10), "2026-07-10T06:17:27Z"
    )

    assert old_path.read_bytes() == old_bytes
    assert reroll["path"].is_file()
    assert reroll["path"] != old_path
    assert generated.read_text().count('kind: "target_registered"') == 1


def conditional_pair_targets(
    series: str = "irs.actc.total_claims",
) -> list[dict]:
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entry = next(
        e
        for e in docket["series"]
        if e["series"] == series and isinstance(e.get("conditionalPair"), dict)
    )
    return [
        {
            "series": entry["series"],
            "period": entry["period"],
            "catalogSlug": arm["catalogSlug"],
            "dataPointId": arm["dataPointId"],
            "conditional": arm["conditional"],
            "conditionId": arm["conditionId"],
            "conditionDeadline": entry["conditionalPair"]["conditionDeadline"],
            **entry["extras"],
        }
        for arm in entry["conditionalPair"]["arms"]
    ]


def test_conditional_authentication_selects_exact_period_for_reused_series() -> None:
    series = "usaspending.dod.prime_award_obligations"
    docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    entries = [entry for entry in docket["series"] if entry["series"] == series]
    assert {entry["period"] for entry in entries} == {"FY2026", "2027"}

    conditional_target = conditional_pair_targets(series)[0]
    conditional_contract = register_targets.build_contract(
        conditional_target, dt.date(2026, 8, 1)
    )
    register_targets.require_conditional_docket_template(
        conditional_contract,
        entries,
        "2026-08-01T00:00:00Z",
    )
    assert [
        entry["period"]
        for entry in register_targets.matching_docket_templates(
            conditional_contract, entries
        )
    ] == ["2027"]

    snapshot_entry = next(
        entry for entry in entries if not isinstance(entry.get("conditionalPair"), dict)
    )
    snapshot_target = {
        **snapshot_entry["extras"],
        "series": series,
        "period": snapshot_entry["period"],
        "catalogSlug": snapshot_entry["slug"].format(period="fy2026"),
    }
    snapshot_contract = register_targets.build_contract(
        snapshot_target, dt.date(2026, 8, 1)
    )
    register_targets.require_conditional_docket_template(
        snapshot_contract,
        entries,
        "2026-08-01T00:00:00Z",
    )

    unconditional_2027 = {
        **conditional_target,
        "catalogSlug": "unconditional-dod-prime-award-obligations-fy2027",
        "dataPointId": (
            "usaspending.dod.prime_award_obligations.2027.registered_query_snapshot"
        ),
    }
    for key in ("conditional", "conditionId", "conditionDeadline"):
        unconditional_2027.pop(key)
    with pytest.raises(register_targets.RegistrationError, match="conditional-only"):
        register_targets.require_conditional_docket_template(
            register_targets.build_contract(unconditional_2027, dt.date(2026, 8, 1)),
            entries,
        )

    alias_unconditional_entry = copy.deepcopy(snapshot_entry)
    alias_unconditional_entry["period"] = "FY2027"
    alias_entries = [*entries, alias_unconditional_entry]
    assert {
        entry["period"]
        for entry in register_targets.matching_docket_templates(
            conditional_contract, alias_entries
        )
    } == {"2027", "FY2027"}
    with pytest.raises(
        register_targets.RegistrationError,
        match="exactly one committed docket entry",
    ):
        register_targets.require_conditional_docket_template(
            conditional_contract,
            alias_entries,
            "2026-08-01T00:00:00Z",
        )

    alias_unconditional_target = {
        **unconditional_2027,
        "period": "FY2027",
        "dataPointId": (
            "usaspending.dod.prime_award_obligations.fy2027.registered_query_snapshot"
        ),
    }
    with pytest.raises(register_targets.RegistrationError, match="conditional-only"):
        register_targets.require_conditional_docket_template(
            register_targets.build_contract(
                alias_unconditional_target, dt.date(2026, 8, 1)
            ),
            alias_entries,
        )

    with pytest.raises(
        register_targets.RegistrationError,
        match="exactly one committed docket entry",
    ):
        duplicate_pair_entry = next(
            entry for entry in entries if isinstance(entry.get("conditionalPair"), dict)
        )
        register_targets.require_conditional_docket_template(
            conditional_contract,
            [*entries, copy.deepcopy(duplicate_pair_entry)],
            "2026-08-01T00:00:00Z",
        )


def test_registration_must_precede_every_release_window_literally() -> None:
    target = conditional_pair_targets()[0]
    start = target["expectedReleaseWindow"]["start"]

    with pytest.raises(register_targets.RegistrationError) as caught:
        register_targets.build_contract(target, dt.date.fromisoformat(start))

    assert str(caught.value) == (
        "expected release window must start after the registration date"
    )


def test_mint_registration_refuses_bounded_target_at_window_start(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_registration_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        register_targets,
        "load_ledger_pin_binding",
        lambda: _pin("c" * 40, 128),
    )
    target = conditional_pair_targets("census.spm.child_poverty_rate")[0]
    payload = register_targets.bounded_registration_payload({"targets": [target]})
    targets_path = tmp_path / "bounded-targets.json"
    targets_path.write_text(json.dumps(payload) + "\n")
    window_start = dt.date.fromisoformat(target["expectedReleaseWindow"]["start"])

    with pytest.raises(register_targets.RegistrationError) as caught:
        register_targets.register(
            targets_path,
            window_start,
            f"{window_start.isoformat()}T00:00:00Z",
        )

    assert str(caught.value) == (
        "expected release window must start after the registration date"
    )
    assert not (tmp_path / "records" / "targets").exists()


def test_mint_registration_never_registers_calendar_targets(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    generated_before = generated.read_bytes()
    target = sample_target()
    filtered = register_targets.bounded_registration_payload({"targets": [target]})
    targets_path = tmp_path / "bounded-targets.json"
    targets_path.write_text(json.dumps(filtered) + "\n")

    assert filtered == {"targets": []}
    assert (
        register_targets.register(
            targets_path,
            dt.date(2030, 1, 10),
            "2030-01-10T14:32:05Z",
        )
        == []
    )
    assert generated.read_bytes() == generated_before
    assert not (tmp_path / "records" / "targets").exists()


@pytest.mark.usefixtures("resolver_admits")
def test_bounded_pair_can_register_bind_and_mint(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generated = configure_registration_root(tmp_path, monkeypatch)
    live_docket = json.loads((ROOT / "scripts" / "docket_series.json").read_text())
    census_entry = next(
        entry
        for entry in live_docket["series"]
        if entry["series"] == "census.spm.child_poverty_rate"
    )
    docket = _write_docket(tmp_path, [census_entry])
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    _commit_files(tmp_path, [generated, docket], "base bounded docket")
    monkeypatch.setattr(
        register_targets,
        "load_ledger_pin_binding",
        lambda: _pin("c" * 40, 128),
    )

    raw_targets = conditional_pair_targets("census.spm.child_poverty_rate")
    filtered = register_targets.bounded_registration_payload({"targets": raw_targets})
    assert len(filtered["targets"]) == 2
    targets_path = tmp_path / "ticket-targets.json"
    targets_path.write_text(json.dumps(filtered) + "\n")
    registrations = register_targets.register(
        targets_path,
        dt.date(2026, 8, 5),
        "2026-08-05T12:00:00Z",
    )
    assert len(registrations) == 2
    assert all(not registration["existing"] for registration in registrations)
    _commit_files(
        tmp_path,
        [generated, *(registration["path"] for registration in registrations)],
        "register bounded pair",
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()

    targets_path.write_text(json.dumps({"targets": raw_targets}) + "\n")
    reused = register_targets.register(
        targets_path,
        dt.date(2026, 8, 5),
        "2026-08-05T12:30:00Z",
        reuse_existing_only=True,
    )
    assert len(reused) == 2
    assert all(registration["existing"] for registration in reused)
    metadata = register_targets.bind_registration_commits(targets_path, head)
    bound_targets = json.loads(targets_path.read_text())["targets"]
    ticket = generation_tickets.mint_ticket(
        bound_targets,
        {
            "promptMode": "fast",
            "codexModel": "gpt-test",
            "codexReasoningEffort": "low",
            "codexSandbox": "read-only",
            "codexNetwork": False,
            "reviewCodexModel": "gpt-review-test",
            "reviewCodexSearch": False,
            "timeoutSeconds": 540,
        },
        nonce="a" * 64,
        minted_at_utc="2026-08-05T13:00:00Z",
        expires_hours=168,
        attempt=1,
        registration_set_hash=metadata["registrationSetHash"],
    )

    assert sorted(target["catalogSlug"] for target in ticket["targets"]) == sorted(
        target["catalogSlug"] for target in raw_targets
    )
    assert ticket["expiresAtUtc"] == "2026-08-12T13:00:00Z"


def test_condition_deadline_must_precede_bounded_window_literally() -> None:
    target = conditional_pair_targets()[0]
    target["conditionDeadline"] = target["expectedReleaseWindow"]["start"]

    with pytest.raises(register_targets.RegistrationError) as caught:
        register_targets.build_contract(target, dt.date(2026, 8, 1))

    assert str(caught.value) == (
        "conditionDeadline must precede the expected release window"
    )


@pytest.mark.usefixtures("resolver_admits")
def test_skip_unbindable_never_registers_a_lone_conditional_arm(
    tmp_path: pathlib.Path, monkeypatch, capsys
) -> None:
    # Selection admits a conditional pair only as one atomic unit, but the
    # roll's register step prunes unbindable targets INDIVIDUALLY
    # (--skip-unbindable). Without sibling pruning, one arm whose contract
    # fails to bind would let the other register, forecast, and publish
    # alone — and hand the pruned arm a later, better-informed wave.
    configure_registration_root(tmp_path, monkeypatch)
    registration_date = dt.date(2026, 8, 1)
    registered_at_utc = "2026-08-01T00:00:00Z"

    arms = conditional_pair_targets()
    sabotaged = dict(arms[0], conditionId="   ")  # fails build_contract
    plain = sample_target()
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(json.dumps({"targets": [sabotaged, arms[1], plain]}))

    registrations = register_targets.register(
        targets_path, registration_date, registered_at_utc, True
    )
    slugs = [t["catalogSlug"] for r in registrations for t in r["snapshot"]["targets"]]
    assert slugs == [plain["catalogSlug"]]
    surviving = json.loads(targets_path.read_text())["targets"]
    assert [t["catalogSlug"] for t in surviving] == [plain["catalogSlug"]]
    err = capsys.readouterr().err
    assert "skipping unbindable target" in err
    assert "skipping sibling conditional arm" in err
    assert arms[1]["catalogSlug"] in err

    # Control: the intact pair registers both arms together.
    targets_path.write_text(json.dumps({"targets": conditional_pair_targets()}))
    registrations = register_targets.register(
        targets_path, registration_date, registered_at_utc, True
    )
    slugs = [t["catalogSlug"] for r in registrations for t in r["snapshot"]["targets"]]
    assert sorted(slugs) == sorted(
        arm["catalogSlug"] for arm in conditional_pair_targets()
    )

    # A pair wiped by pruning with nothing else in the wave fails loudly.
    targets_path.write_text(
        json.dumps({"targets": [sabotaged, conditional_pair_targets()[1]]})
    )
    with pytest.raises(register_targets.RegistrationError, match="no bindable targets"):
        register_targets.register(
            targets_path, registration_date, registered_at_utc, True
        )
