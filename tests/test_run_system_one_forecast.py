"""The System One (Jev) threshold-ladder forecaster lane."""

from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import docket_publication  # noqa: E402
import run_system_one_forecast as system_one  # noqa: E402
import run_thesis_analyst as analyst  # noqa: E402
import verify_custody  # noqa: E402
from verify_custody import verify_run  # noqa: E402

SLUG = "agency-test-rate-january-2030"
SERIES = "agency.test.rate"
RUN_AT = "2030-01-10T12:00:00Z"

# Distinctive sentinels: every one of them lives in a redacted field of the
# published primary cell, so none may appear in the state the model sees.
SENTINEL_POINT = 987654.321
SENTINEL_CI_LOW = 987000.111
SENTINEL_CI_HIGH = 988000.999
SENTINEL_DRIVER = "Sentinel driver phrase naming the withheld forecast rationale"
SENTINEL_REASONING = "Sentinel reasoning narrative that must never reach the state"
SENTINEL_MODEL = "sentinel-model-identifier"
SENTINEL_RUN_AT = "2029-12-31T00:00:00Z"
SENTINELS = (
    SENTINEL_DRIVER,
    SENTINEL_REASONING,
    SENTINEL_MODEL,
    SENTINEL_RUN_AT,
    repr(SENTINEL_POINT),
    repr(SENTINEL_CI_LOW),
    repr(SENTINEL_CI_HIGH),
)


def target_context() -> dict:
    return {
        "catalogSlug": SLUG,
        "comparisonTarget": True,
        "country": "US",
        "dataPointId": "agency.test.rate.2030_01.first_print",
        "period": "2030-01",
        "registeredAtUtc": "2030-01-01T00:00:00Z",
        "registrationCommit": "a" * 40,
        "resolutionDate": "2030-02-15",
        "resolutionPolicy": "first_print",
        "resolutionRule": "Use the first official print only; ignore revisions.",
        "resolutionSource": "Agency monthly rate release",
        "resolutionSourceUrl": "https://agency.example/rate",
        "series": SERIES,
        "sourceBinding": {
            "adapter": "generic-url",
            "allowedHosts": ["agency.example"],
            "sourceSeriesId": SERIES,
            "sourceUrl": "https://agency.example/rate",
        },
        "targetContentHash": "b" * 64,
        "targetRegistrationPath": f"records/targets/2030-01-01-{'b' * 64}.json",
        "targetUnit": "percent",
        "valueScale": 1,
    }


HISTORY_VALUES = [3.1, 3.4, 3.2, 3.6, 3.5, 3.8]
HISTORY_PERIODS = [
    "2029-06",
    "2029-07",
    "2029-08",
    "2029-09",
    "2029-10",
    "2029-11",
]


def history_rows(count: int = 6) -> list[dict]:
    rows = []
    for period, value in list(zip(HISTORY_PERIODS, HISTORY_VALUES))[:count]:
        rows.append(
            {
                "label": period,
                "period": {"type": "month", "value": period},
                "value": value,
            }
        )
    return rows


def primary_cell(history_count: int = 6) -> dict:
    target = target_context()
    return {
        "slug": SLUG,
        "country": "US",
        "type": "data",
        "title": "Agency test rate",
        "question": (
            "What will the agency report as the first print of the test rate "
            "for January 2030, in percent?"
        ),
        "unit": target["targetUnit"],
        "resolutionDate": target["resolutionDate"],
        "resolutionSource": target["resolutionSource"],
        "resolutionSourceUrl": target["resolutionSourceUrl"],
        "resolutionRule": target["resolutionRule"],
        "dataPointId": target["dataPointId"],
        "historicalContext": history_rows(history_count),
        "sourceContext": [
            "https://agency.example/rate",
            "https://agency.example/calendar",
        ],
        "pointEstimate": SENTINEL_POINT,
        "ciLow": SENTINEL_CI_LOW,
        "ciHigh": SENTINEL_CI_HIGH,
        "confidence": 0.8,
        "drivers": [SENTINEL_DRIVER],
        "reasoning": [
            {"kind": "heading", "text": "Primary run"},
            {"kind": "text", "text": SENTINEL_REASONING},
            {
                "kind": "forecast",
                "point": SENTINEL_POINT,
                "ciLow": SENTINEL_CI_LOW,
                "ciHigh": SENTINEL_CI_HIGH,
            },
        ],
        "predictionDistribution": {"format": "numeric_cdf_v1", "points": []},
        "thresholdLadder": {
            "thresholds": [1.0, 2.0, 3.0],
            "cumulativeProbabilities": [0.1, 0.5, 0.9],
        },
        "preSubmitReview": {"status": "completed", "findings": [SENTINEL_REASONING]},
        "activityLog": [
            {
                "artifactType": "prompt",
                "path": "records/thesis-analyst/2029-12-31/primary/prompt.md",
                "sha256": "c" * 64,
                "bytes": 12,
                "createdAt": SENTINEL_RUN_AT,
            }
        ],
        "model": SENTINEL_MODEL,
        "runStartedAt": SENTINEL_RUN_AT,
        "runAt": SENTINEL_RUN_AT,
        **{
            field: target[field]
            for field in (
                "registrationCommit",
                "targetContentHash",
                "targetRegistrationPath",
                "registeredAtUtc",
            )
        },
    }


def ledger_rows(values: list[float] | None = None) -> list[dict]:
    values = HISTORY_VALUES if values is None else values
    rows = []
    for index, (period, value) in enumerate(zip(HISTORY_PERIODS, values), start=1):
        rows.append(
            {
                "source_record_id": f"agency-test-rate-{period}",
                "label": f"Agency test rate, {period}",
                "value": value,
                "observed_at": f"{period}-20",
                "period": {"type": "month", "value": period},
                "measure": {
                    "concept": SERIES,
                    "source_concept": "AGENCYRATE",
                    "unit": "percent",
                },
                "source": {"source_name": "agency"},
            }
        )
    return rows


def write_primary_run(repo: pathlib.Path, cell: dict) -> pathlib.Path:
    run_dir = (
        repo
        / "records"
        / "thesis-analyst"
        / "2029-12-31"
        / f"2029-12-31t00-00-00z-primary-{SLUG}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    cells_path = run_dir / "cells.with_activity.json"
    cells_path.write_text(json.dumps([cell], indent=2) + "\n")
    manifest = {
        "schemaVersion": "thesis_analyst_run_manifest_v1",
        "createdAt": SENTINEL_RUN_AT,
        "runStartedAt": SENTINEL_RUN_AT,
        "runMode": "analyst",
        "promptMode": "fast",
        "targetContext": target_context(),
        "ok": True,
        "cellsPath": "records/thesis-analyst/2029-12-31/"
        f"2029-12-31t00-00-00z-primary-{SLUG}/cells.with_activity.json",
        "artifacts": [],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return cells_path


def write_ledger(repo: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    path = repo / "official_observations.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


@pytest.fixture
def repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    checkout = tmp_path / "repo"
    checkout.mkdir()
    monkeypatch.setattr(analyst, "ROOT", checkout)
    monkeypatch.setattr(system_one, "ROOT", checkout)
    monkeypatch.setattr(verify_custody, "REPOSITORY_ROOT", checkout)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    return checkout


def system_one_run(
    repo: pathlib.Path,
    *,
    backend: str = "mock",
    cell: dict | None = None,
    ledger: list[dict] | None = None,
    run_at: str = RUN_AT,
    response_file: pathlib.Path | None = None,
    primary_cell_path: pathlib.Path | None = None,
) -> tuple[dict, pathlib.Path]:
    if primary_cell_path is None:
        write_primary_run(repo, cell or primary_cell())
    ledger_path = write_ledger(repo, ledger) if ledger is not None else None
    return system_one.run_forecast(
        target=target_context(),
        backend=backend,
        records_root=repo / "records",
        primary_cell_path=primary_cell_path,
        ledger_path=ledger_path,
        response_file=response_file,
        run_at=run_at,
    )


# --- end to end -------------------------------------------------------------


def test_mock_run_is_custody_verifiable(repo: pathlib.Path):
    manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())

    assert manifest["ok"] is True
    assert manifest["schemaVersion"] == "thesis_system_one_run_manifest_v1"
    assert manifest["runMode"] == "system_one"
    assert manifest["promptMode"] == "system_one_noul_ladder"
    assert manifest["agent"]["agent"] == "thesis.system_one"
    assert manifest["agent"]["model"] == "mock"
    assert manifest["agent"]["backend"] == "mock"
    assert manifest["error"] is None
    assert docket_publication.RUN_MANIFEST_RE.fullmatch(
        manifest_path.relative_to(repo).as_posix()
    )
    assert manifest_path.parent.name.endswith(f"-system-one-{SLUG}")

    verification = verify_run(manifest_path.parent)
    assert verification.run_mode == "system_one"
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is True
    assert verification.headline_eligible is False

    inventory = [
        (ref["artifactType"], pathlib.Path(ref["path"]).name)
        for ref in manifest["artifacts"]
    ]
    assert inventory == [
        ("system_one_state", "state.json"),
        ("system_one_questions", "questions.json"),
        ("system_one_request", "request.json"),
        ("system_one_response", "response.json"),
        ("command", "command.json"),
        ("normalized_cell", "normalized_cells.json"),
        ("run_distribution", "distribution.json"),
        ("validation_report", "validation.json"),
        ("cells_with_activity", "cells.with_activity.json"),
        ("manifest", "manifest.json"),
    ]

    cell = json.loads((manifest_path.parent / "cells.with_activity.json").read_text())[
        0
    ]
    ladder = cell["thresholdLadder"]
    assert len(ladder["thresholds"]) == 15
    assert len(ladder["cumulativeProbabilities"]) == 15
    assert ladder["monotonization"] == "pav_v1"
    assert ladder["thresholds"] == sorted(set(ladder["thresholds"]))
    assert all(
        later >= earlier
        for earlier, later in zip(
            ladder["cumulativeProbabilities"], ladder["cumulativeProbabilities"][1:]
        )
    )
    assert ladder["rawCumulativeProbabilities"] != ladder["cumulativeProbabilities"]
    assert cell["ciLow"] < cell["pointEstimate"] < cell["ciHigh"]
    assert cell["confidence"] == 0.8
    assert cell["drivers"] == []
    assert cell["slug"] == SLUG
    assert cell["runStartedAt"] == RUN_AT
    assert cell["runAt"] == manifest["sealedAt"]

    kinds = [step["kind"] for step in cell["reasoning"]]
    assert kinds == ["heading", "text", "tool", "math", "forecast"]
    assert cell["reasoning"][0]["text"] == "System One threshold ladder"
    narrative = cell["reasoning"][1]["text"]
    assert "no tools, no search, and no chain of thought" in narrative
    assert cell["reasoning"][2]["tool"] == "system_one.noul_ladder"
    math_text = cell["reasoning"][3]["text"]
    assert math_text.startswith("Ladder: P(X <= ")
    assert "10th percentile" in math_text and "90th percentile" in math_text

    distribution = json.loads((manifest_path.parent / "distribution.json").read_text())
    assert distribution["format"] == "numeric_cdf_v1"
    assert distribution["provenance"] == "agent_reported"
    assert distribution["summary"]["pointEstimate"] == cell["pointEstimate"]


def test_cli_writes_a_run_outside_records(
    repo: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture
):
    write_primary_run(repo, primary_cell())
    target_path = tmp_path / "target.json"
    target_path.write_text(json.dumps(target_context()))
    ledger_path = write_ledger(repo, ledger_rows())
    out_manifest = tmp_path / "manifest-path.txt"
    records_root = tmp_path / "smoke-records"

    exit_code = system_one.main(
        [
            "--target-json",
            str(target_path),
            "--primary-cell",
            str(
                repo
                / "records/thesis-analyst/2029-12-31"
                / f"2029-12-31t00-00-00z-primary-{SLUG}"
                / "cells.with_activity.json"
            ),
            "--ledger-jsonl",
            str(ledger_path),
            "--backend",
            "mock",
            "--records-root",
            str(records_root),
            "--run-at",
            RUN_AT,
            "--out-manifest",
            str(out_manifest),
        ]
    )
    capsys.readouterr()
    assert exit_code == 0
    manifest_path = pathlib.Path(out_manifest.read_text().strip())
    assert manifest_path.is_absolute()
    assert records_root in manifest_path.parents
    assert verify_run(manifest_path.parent).run_mode == "system_one"
    assert not (repo / "records/thesis-analyst" / RUN_AT[:10]).exists()


def test_response_file_backend_replays_deterministically(repo: pathlib.Path):
    manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    saved = manifest_path.parent / "response.json"
    replay_source = repo / "saved-response.json"
    replay_source.write_text(saved.read_text())

    first, first_path = system_one_run(
        repo,
        backend="response_file",
        ledger=ledger_rows(),
        response_file=replay_source,
        run_at="2030-01-10T13:00:00Z",
    )
    second, second_path = system_one_run(
        repo,
        backend="response_file",
        ledger=ledger_rows(),
        response_file=replay_source,
        run_at="2030-01-10T14:00:00Z",
    )
    assert first["ok"] is True and second["ok"] is True
    assert first["agent"]["model"] == "response_file"
    assert verify_run(first_path.parent).run_succeeded is True
    assert verify_run(second_path.parent).run_succeeded is True

    def ladder_of(path: pathlib.Path) -> dict:
        cell = json.loads((path.parent / "cells.with_activity.json").read_text())[0]
        return {
            "ladder": cell["thresholdLadder"],
            "point": cell["pointEstimate"],
            "ciLow": cell["ciLow"],
            "ciHigh": cell["ciHigh"],
        }

    assert ladder_of(first_path) == ladder_of(second_path)
    assert ladder_of(first_path)["ladder"]["cumulativeProbabilities"] == (
        json.loads((manifest_path.parent / "cells.with_activity.json").read_text())[0][
            "thresholdLadder"
        ]["cumulativeProbabilities"]
    )
    assert (
        json.loads((first_path.parent / "response.json").read_text())["answers"]
        == json.loads(saved.read_text())["answers"]
    )
    command = json.loads((first_path.parent / "command.json").read_text())
    assert command["backend"] == "response_file"
    assert command["responseFile"]["name"] == "saved-response.json"


# --- ladder mechanics -------------------------------------------------------


def test_pav_monotone_known_vectors():
    assert system_one.pav_monotone([0.1, 0.2, 0.3]) == [0.1, 0.2, 0.3]
    assert system_one.pav_monotone([0.2, 0.1, 0.3]) == pytest.approx([0.15, 0.15, 0.3])
    assert system_one.pav_monotone([0.5, 0.4, 0.3]) == pytest.approx([0.4, 0.4, 0.4])
    assert system_one.pav_monotone([0.0, 1.0, 0.5, 0.5]) == pytest.approx(
        [0.0, 2.0 / 3, 2.0 / 3, 2.0 / 3]
    )
    assert system_one.pav_monotone([0.9]) == [0.9]
    monotone = system_one.pav_monotone([0.4, 0.1, 0.9, 0.2, 0.8])
    assert monotone == sorted(monotone)
    assert sum(monotone) == pytest.approx(sum([0.4, 0.1, 0.9, 0.2, 0.8]))


def test_ladder_uses_ledger_dispersion_when_history_exists(repo: pathlib.Path):
    _manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    questions = json.loads((manifest_path.parent / "questions.json").read_text())
    changes = [
        abs(later - earlier)
        for earlier, later in zip(HISTORY_VALUES, HISTORY_VALUES[1:])
    ]
    assert questions["ladderBasis"] == "ledger_dispersion"
    assert questions["center"] == pytest.approx(HISTORY_VALUES[-1])
    assert questions["scale"] == pytest.approx(system_one.quantile(changes, 0.8))
    assert questions["observationCount"] == len(HISTORY_VALUES)
    assert questions["ledgerSourceRecordIds"] == [
        f"agency-test-rate-{period}" for period in HISTORY_PERIODS
    ]
    assert len(questions["questions"]) == 15
    assert list(questions["questions"]) == [
        f"rung_{index:02d}" for index in range(1, 16)
    ]
    first = questions["questions"]["rung_01"]
    assert first["type"] == "noul"
    assert first["instructions"] == (
        "The official first print of Agency test rate for 2030-01 will be at "
        f"or below {questions['thresholds'][0]:.1f} percent."
    )


def test_ladder_falls_back_to_history_dispersion(repo: pathlib.Path):
    _manifest, manifest_path = system_one_run(repo, ledger=None)
    questions = json.loads((manifest_path.parent / "questions.json").read_text())
    assert questions["ladderBasis"] == "history_dispersion"
    assert questions["center"] == pytest.approx(HISTORY_VALUES[-1])
    assert questions["ledgerSourceRecordIds"] == []
    state = json.loads((manifest_path.parent / "state.json").read_text())
    assert state["ledgerObservations"]["rows"] == []
    assert len(state["historicalContext"]["rows"]) == 6


def test_ledger_rows_after_the_target_period_are_not_matched(repo: pathlib.Path):
    future = copy.deepcopy(ledger_rows())
    for row in future:
        row["period"] = {"type": "month", "value": "2030-05"}
    _manifest, manifest_path = system_one_run(repo, ledger=future)
    questions = json.loads((manifest_path.parent / "questions.json").read_text())
    assert questions["ladderBasis"] == "history_dispersion"


def test_insufficient_history_fails_closed(repo: pathlib.Path):
    manifest, manifest_path = system_one_run(
        repo, cell=primary_cell(history_count=2), ledger=None
    )
    assert manifest["ok"] is False
    assert manifest["cellsPath"] is None
    assert manifest["validation"] is None
    assert manifest["error"]["phase"] == "state"
    assert manifest["error"]["detail"]["reason"] == "insufficient_history"
    assert [
        (ref["artifactType"], pathlib.Path(ref["path"]).name)
        for ref in manifest["artifacts"]
    ] == [
        ("system_one_state", "state.json"),
        ("error", "error.json"),
        ("manifest", "manifest.json"),
    ]
    verification = verify_run(manifest_path.parent)
    assert verification.run_mode == "system_one"
    assert verification.run_succeeded is False
    assert verification.headline_eligible is False


def test_rounding_collapse_fails_closed(repo: pathlib.Path):
    flat = [3.8] * len(HISTORY_PERIODS)
    manifest, manifest_path = system_one_run(repo, ledger=ledger_rows(flat))
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "state"
    assert manifest["error"]["detail"]["reason"] == "ladder_collapsed_under_rounding"
    assert verify_run(manifest_path.parent).run_succeeded is False


def test_off_ladder_mass_fails_closed(repo: pathlib.Path):
    _manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    saved = json.loads((manifest_path.parent / "response.json").read_text())
    for answer in saved["answers"].values():
        answer["noul"] = 0.5
    flat_response = repo / "flat-response.json"
    flat_response.write_text(json.dumps(saved, indent=2))

    manifest, failed_path = system_one_run(
        repo,
        backend="response_file",
        ledger=ledger_rows(),
        response_file=flat_response,
        run_at="2030-01-10T15:00:00Z",
    )
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "ladder"
    assert manifest["error"]["detail"]["reason"] == "off_ladder_mass"
    assert manifest["error"]["detail"]["rawCumulativeProbabilities"] == [0.5] * 15
    assert [
        (ref["artifactType"], pathlib.Path(ref["path"]).name)
        for ref in manifest["artifacts"]
    ] == [
        ("system_one_state", "state.json"),
        ("system_one_questions", "questions.json"),
        ("system_one_request", "request.json"),
        ("system_one_response", "response.json"),
        ("command", "command.json"),
        ("error", "error.json"),
        ("manifest", "manifest.json"),
    ]
    verification = verify_run(failed_path.parent)
    assert verification.run_mode == "system_one"
    assert verification.run_succeeded is False


def test_backend_answer_mismatch_fails_closed(repo: pathlib.Path):
    _manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    saved = json.loads((manifest_path.parent / "response.json").read_text())
    saved["answers"].pop("rung_07")
    short_response = repo / "short-response.json"
    short_response.write_text(json.dumps(saved, indent=2))
    manifest, failed_path = system_one_run(
        repo,
        backend="response_file",
        ledger=ledger_rows(),
        response_file=short_response,
        run_at="2030-01-10T16:00:00Z",
    )
    assert manifest["error"]["phase"] == "ladder"
    assert manifest["error"]["detail"]["missing"] == ["rung_07"]
    assert verify_run(failed_path.parent).run_succeeded is False


# --- evidence boundary ------------------------------------------------------


def test_state_and_questions_carry_no_redacted_forecast_content(repo: pathlib.Path):
    _manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    run_dir = manifest_path.parent
    state_text = (run_dir / "state.json").read_text()
    questions_text = (run_dir / "questions.json").read_text()
    request_text = (run_dir / "request.json").read_text()
    state = json.loads(state_text)
    questions = json.loads(questions_text)

    # The only place a redacted name may appear is the state's own redaction
    # notice, which lists the names as values; none may appear as a key.
    # request.json carries its own top-level model key: the model asked for,
    # not the primary cell's.
    for field in system_one.REDACTED_CELL_FIELDS:
        assert f'"{field}":' not in state_text, field
        assert f'"{field}":' not in questions_text, field
    assert json.loads(request_text)["model"] is None
    for sentinel in SENTINELS:
        for text in (state_text, questions_text, request_text):
            assert sentinel not in text, sentinel

    assert system_one.redaction_violations(primary_cell(), [state, questions]) == []
    assert state["redaction"]["cellFields"] == list(system_one.REDACTED_CELL_FIELDS)
    assert state["historicalContext"]["provenance"] == "agent_reported"
    assert state["ledgerObservations"]["provenance"] == "official_ledger"
    assert state["sourceContext"]["urls"] == [
        "https://agency.example/rate",
        "https://agency.example/calendar",
    ]
    assert set(state["target"]) == {
        "catalogSlug",
        "title",
        "question",
        "unit",
        "country",
        "series",
        "period",
        "dataPointId",
        "resolutionDate",
        "resolutionRule",
        "resolutionSource",
        "resolutionSourceUrl",
    }
    provenance = state["primaryCellProvenance"]
    assert provenance["manifestPath"].endswith("manifest.json")
    assert len(provenance["manifestSha256"]) == 64
    assert len(provenance["cellSha256"]) == 64


def test_redaction_violation_is_detected(repo: pathlib.Path):
    cell = primary_cell()
    leaked = {"drivers": cell["drivers"], "note": SENTINEL_REASONING}
    violations = system_one.redaction_violations(cell, [leaked])
    assert any("redacted key drivers" in item for item in violations)
    assert any("redacted reasoning content" in item for item in violations)


def test_requested_backends_refuse_missing_credentials(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(system_one.SystemOneInputError, match="TYPESAFE_API_KEY"):
        system_one_run(repo, backend="typesafe", ledger=ledger_rows())
    with pytest.raises(system_one.SystemOneInputError, match="OPENAI_API_KEY"):
        system_one.run_forecast(
            target=target_context(),
            backend="adapter",
            records_root=repo / "records",
            provider="openai",
            model="gpt-5.5",
            run_at=RUN_AT,
        )


def test_primary_cell_is_discovered_from_the_records_tree(repo: pathlib.Path):
    write_primary_run(repo, primary_cell())
    manifest, manifest_path = system_one.run_forecast(
        target=target_context(),
        backend="mock",
        records_root=repo / "records",
        ledger_path=write_ledger(repo, ledger_rows()),
        run_at=RUN_AT,
    )
    assert manifest["ok"] is True
    state = json.loads((manifest_path.parent / "state.json").read_text())
    assert state["primaryCellProvenance"]["cellPath"].endswith(
        f"2029-12-31t00-00-00z-primary-{SLUG}/cells.with_activity.json"
    )


# --- SDK contract -----------------------------------------------------------


def test_sdk_field_names_match_the_recorded_shapes():
    msgspec = pytest.importorskip("msgspec")
    typesafe_sdk = pytest.importorskip("typesafe_sdk")

    question = typesafe_sdk.Noul(instructions="The first print will be at or below 1.")
    assert msgspec.to_builtins({"rung_01": question}) == {
        "rung_01": {"type": "noul", "instructions": question.instructions}
    }

    response = typesafe_sdk.SystemOneResponse(
        model="jev-1",
        usage=typesafe_sdk.Usage(input_tokens=11, output_tokens=0),
        answers={"rung_01": typesafe_sdk.NoulAnswer(noul=0.25)},
    )
    encoded = msgspec.to_builtins(response)
    assert encoded == {
        "model": "jev-1",
        "usage": {"input_tokens": 11, "output_tokens": 0},
        "answers": {"rung_01": {"type": "noul", "noul": 0.25}},
    }
    assert system_one.noul_probabilities(encoded, ["rung_01"]) == [0.25]

    choice = typesafe_sdk.ChoiceAnswer(
        choice="up", confidence=0.6, probabilities={"up": 0.6, "down": 0.4}
    )
    score = typesafe_sdk.ScoreAnswer(
        score=2.0, confidence=0.5, legend={1: "low"}, probabilities={1: 0.5, 2: 0.5}
    )
    assert set(msgspec.to_builtins(choice)) == {
        "type",
        "choice",
        "confidence",
        "probabilities",
    }
    assert set(msgspec.to_builtins(score)) == {
        "type",
        "score",
        "confidence",
        "legend",
        "probabilities",
    }
    assert {
        name
        for name in (
            "TypeSafeAuthenticationError",
            "TypeSafeRateLimitError",
            "TypeSafeAPITimeoutError",
        )
    } <= set(dir(typesafe_sdk))


def test_mock_run_never_imports_the_optional_extra(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    # Setting a module to None in sys.modules makes importing it raise, so a
    # green run here proves the SDK import is lazy.
    for name in ("typesafe_sdk", "system_one_adapter"):
        monkeypatch.setitem(sys.modules, name, None)
    manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    assert manifest["ok"] is True
    assert verify_run(manifest_path.parent).run_succeeded is True


def test_question_title_drops_a_period_the_title_repeats():
    assert (
        system_one.question_title(
            "US initial claims, week ending 2026-09-19", "week ending 2026-09-19"
        )
        == "US initial claims"
    )
    assert (
        system_one.question_title("Agency test rate", "2030-01") == "Agency test rate"
    )
    assert system_one.question_title("2030-01", "2030-01") == "2030-01"
    assert system_one.period_phrase("week_2026-09-19") == "week ending 2026-09-19"
    assert system_one.period_phrase("2030-01") == "2030-01"


def test_validate_phase_crash_is_sealed_as_a_failure(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    def crash(**_kwargs):
        raise ValueError("validation exploded")

    monkeypatch.setattr(system_one, "validate_run", crash)
    manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "validate"
    assert manifest["error"]["detail"]["exception"] == "ValueError"
    assert [
        (ref["artifactType"], pathlib.Path(ref["path"]).name)
        for ref in manifest["artifacts"]
    ] == [
        ("system_one_state", "state.json"),
        ("system_one_questions", "questions.json"),
        ("system_one_request", "request.json"),
        ("system_one_response", "response.json"),
        ("command", "command.json"),
        ("normalized_cell", "normalized_cells.json"),
        ("run_distribution", "distribution.json"),
        ("error", "error.json"),
        ("manifest", "manifest.json"),
    ]
    verification = verify_run(manifest_path.parent)
    assert verification.run_mode == "system_one"
    assert verification.run_succeeded is False


def test_late_failure_records_the_model_that_answered(repo: pathlib.Path):
    _manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    saved = json.loads((manifest_path.parent / "response.json").read_text())
    saved["model"] = "jev-1"
    for answer in saved["answers"].values():
        answer["noul"] = 0.5
    flat = repo / "flat-jev-response.json"
    flat.write_text(json.dumps(saved, indent=2))

    manifest, failed_path = system_one_run(
        repo,
        backend="response_file",
        ledger=ledger_rows(),
        response_file=flat,
        run_at="2030-01-10T17:00:00Z",
    )
    assert manifest["error"]["phase"] == "ladder"
    assert manifest["agent"]["model"] == "response_file"
    recorded = json.loads((failed_path.parent / "response.json").read_text())
    assert recorded["model"] == "jev-1"
    assert verify_run(failed_path.parent).run_succeeded is False
