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
    write_catalog_module(repo, cell["slug"], run_dir)
    return cells_path


def write_catalog_module(
    repo: pathlib.Path, slug: str, run_dir: pathlib.Path
) -> pathlib.Path:
    """Publish the run as the catalog's primary cell for this slug.

    The runner locates a primary cell the way the site does: the published
    catalog cell names its own recorded run in its activity log. The fixture
    writes a generated module of exactly that shape so discovery is exercised
    rather than stubbed.
    """

    published = [
        {
            "slug": slug,
            "predictionRun": {
                "agent": "thesis.analyst",
                "activityLog": [
                    {
                        "artifactType": "cells_with_activity",
                        "path": (
                            run_dir.relative_to(repo) / "cells.with_activity.json"
                        ).as_posix(),
                    }
                ],
            },
        }
    ]
    path = repo / "site" / "src" / "data" / "forecast-examples" / "test-wave.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'import type { ForecastCell } from "../forecast-cells";\n\n'
        "export const TEST_WAVE: ForecastCell[] = "
        + json.dumps(published, indent=2)
        + ";\n"
    )
    system_one._CATALOG_CACHE.clear()
    return path


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
    assert cell["reasoning"][0]["text"] == "System One emulation (mock)"
    narrative = cell["reasoning"][1]["text"]
    # A mock run never claims a model answered it, let alone in isolation.
    assert "deterministic offline stand-in, not a model" in narrative
    assert "no chain of thought" not in narrative
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


def test_reasoning_that_repeats_the_title_is_not_a_violation(repo: pathlib.Path):
    # Live analyst cells open their reasoning with a heading that repeats the
    # target title, and the title legitimately sits in the state. The value
    # scan must exempt redacted text contained in an allowed field (observed
    # on australia-cpi-annual-rate-july-2026, 2026-09-15).
    cell = primary_cell()
    title = "Australia CPI annual inflation, July 2026 monthly indicator"
    cell["title"] = title
    cell["reasoning"] = [
        {"kind": "heading", "text": title},
        {"kind": "heading", "text": title[:32]},
        {"kind": "text", "text": SENTINEL_REASONING},
    ]
    state = {"target": {"title": title, "question": f"What is {title}?"}}
    assert system_one.redaction_violations(cell, [state]) == []
    leaked = {"target": {"title": title}, "note": SENTINEL_REASONING}
    violations = system_one.redaction_violations(cell, [leaked])
    # The sentinel sits in every redacted prose field the fixture carries
    # (reasoning and the pre-submit review), so each reports; the title
    # never does.
    assert violations
    assert any("redacted reasoning content" in item for item in violations)
    assert all(title[:24] not in item for item in violations)


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


def test_primary_cell_is_discovered_from_the_published_catalog(repo: pathlib.Path):
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


def write_comparison_run(
    repo: pathlib.Path, cell: dict, *, stamp: str = "2029-12-31t23-00-00z"
) -> pathlib.Path:
    """A later successful analyst run for the same slug, outside the catalog.

    Strategy lanes (ladder, ladder_v2, fast rollouts) write runs for the same
    target into the same records tree. They are comparison runs, not the
    target's published evidence, and nothing in the catalog cites them.
    """

    run_dir = (
        repo
        / "records"
        / "thesis-analyst"
        / "2029-12-31"
        / f"{stamp}-ladder-v2-{SLUG}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "cells.with_activity.json").write_text(
        json.dumps([cell], indent=2) + "\n"
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_analyst_run_manifest_v1",
                "createdAt": "2029-12-31T23:00:00Z",
                "runStartedAt": "2029-12-31T23:00:00Z",
                "runMode": "analyst",
                "promptMode": "ladder_v2",
                "targetContext": target_context(),
                "ok": True,
                "cellsPath": (
                    run_dir.relative_to(repo) / "cells.with_activity.json"
                ).as_posix(),
                "artifacts": [],
            },
            indent=2,
        )
        + "\n"
    )
    return run_dir


def test_a_later_comparison_run_is_never_mistaken_for_the_primary_cell(
    repo: pathlib.Path,
):
    # Observed on australia-cpi-annual-rate-july-2026 (2026-09-16): the
    # newest successful analyst run for the slug was a ladder_v2 comparison
    # run with a different title, question and history from the cell the
    # catalog publishes.
    write_primary_run(repo, primary_cell())
    comparison = copy.deepcopy(primary_cell())
    comparison["title"] = "Agency test rate, comparison lane wording"
    comparison["historicalContext"] = history_rows(3)
    write_comparison_run(repo, comparison)

    manifest, manifest_path = system_one.run_forecast(
        target=target_context(),
        backend="mock",
        records_root=repo / "records",
        run_at=RUN_AT,
    )

    assert manifest["ok"] is True
    state = json.loads((manifest_path.parent / "state.json").read_text())
    assert state["primaryCellProvenance"]["cellPath"].endswith(
        f"2029-12-31t00-00-00z-primary-{SLUG}/cells.with_activity.json"
    )
    assert state["target"]["title"] == "Agency test rate"
    assert len(state["historicalContext"]["rows"]) == 6


def test_an_explicit_primary_cell_must_be_the_one_the_catalog_binds(
    repo: pathlib.Path,
):
    write_primary_run(repo, primary_cell())
    comparison = write_comparison_run(repo, primary_cell())

    with pytest.raises(
        system_one.SystemOneInputError, match="not the published primary cell"
    ):
        system_one.run_forecast(
            target=target_context(),
            backend="mock",
            records_root=repo / "records",
            primary_cell_path=comparison / "cells.with_activity.json",
            run_at=RUN_AT,
        )


def test_a_slug_the_catalog_does_not_publish_is_refused(repo: pathlib.Path):
    with pytest.raises(
        system_one.SystemOneInputError, match="no published catalog cell"
    ):
        system_one.run_forecast(
            target=target_context(),
            backend="mock",
            records_root=repo / "records",
            run_at=RUN_AT,
        )
    assert not (repo / "records" / "thesis-analyst" / RUN_AT[:10]).exists()


# --- backend identity -------------------------------------------------------


def test_each_backend_hashes_and_describes_its_own_mechanism(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    # The adapter sends every question in one structured-output request and
    # the provider model may reason first (system-one-adapter 0.1.3), so an
    # adapter run must never publish the isolation sentence.
    monkeypatch.setenv("OPENAI_API_KEY", "runner-test-key")
    monkeypatch.setattr(
        system_one,
        "call_adapter",
        lambda *, state, payloads, provider, model: {
            "model": model,
            "usage": {"input_tokens": 512, "output_tokens": 64},
            "answers": {
                name: {"type": "noul", "noul": value}
                for name, value in zip(
                    payloads, [index / 16 for index in range(1, 16)]
                )
            },
        },
    )
    write_primary_run(repo, primary_cell())

    manifest, manifest_path = system_one.run_forecast(
        target=target_context(),
        backend="adapter",
        records_root=repo / "records",
        ledger_path=write_ledger(repo, ledger_rows()),
        provider="openai",
        model="gpt-5.5",
        run_at=RUN_AT,
    )

    assert manifest["ok"] is True
    assert manifest["agent"]["model"] == "openai/gpt-5.5"
    cell = json.loads((manifest_path.parent / "cells.with_activity.json").read_text())[
        0
    ]
    assert cell["reasoning"][0]["text"] == (
        "System One emulation (adapter: openai/gpt-5.5)"
    )
    narrative = cell["reasoning"][1]["text"]
    assert "emulates the System One interface rather than using it" in narrative
    assert "one structured-output request" in narrative
    assert "not isolated from one another" in narrative
    assert "no chain of thought" not in narrative
    assert "independent yes/no questions" not in narrative

    policies = {
        backend: system_one.backend_policy(backend)
        for backend in system_one.BACKENDS
    }
    assert policies["typesafe"]["questionIsolation"] == (
        "vendor_asserted_independent"
    )
    assert policies["adapter"]["questionIsolation"] == (
        "single_request_all_questions"
    )
    assert policies["adapter"]["chainOfThought"] == "provider_default"
    hashes = {
        backend: system_one.agent_block(
            backend=backend, provider="openai", model="m", response=None
        )["toolPolicyHash"]
        for backend in system_one.BACKENDS
    }
    assert len(set(hashes.values())) == len(hashes)


def test_typesafe_narrative_is_the_isolated_one():
    narrative = system_one.lane_narrative(
        backend="typesafe", model="jev-1", rungs=15
    )
    assert system_one.lane_label("typesafe", "jev-1") == (
        "System One threshold ladder"
    )
    assert "15 independent yes/no questions" in narrative
    assert "no tools, no search, and no chain of thought" in narrative


def test_a_typesafe_run_that_never_answered_records_no_model(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    # A failed run must not be tallied against a model that never spoke.
    monkeypatch.setenv("TYPESAFE_API_KEY", "runner-test-key")

    def refuse(**_kwargs):
        raise system_one.SystemOneRunError(
            "backend",
            "system_one call failed: TypeSafeAuthenticationError",
            {"exception": "TypeSafeAuthenticationError"},
        )

    monkeypatch.setattr(system_one, "call_typesafe", refuse)
    write_primary_run(repo, primary_cell())

    manifest, manifest_path = system_one.run_forecast(
        target=target_context(),
        backend="typesafe",
        records_root=repo / "records",
        ledger_path=write_ledger(repo, ledger_rows()),
        run_at=RUN_AT,
    )

    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "backend"
    assert manifest["agent"]["model"] is None
    verification = verify_run(manifest_path.parent)
    assert verification.run_mode == "system_one"
    assert verification.run_succeeded is False


# --- ledger match rule ------------------------------------------------------


def national(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["geography"] = {
            "level": "country",
            "id": "0100000US",
            "name": "United States",
        }
    return rows


def test_state_geography_rows_are_not_this_targets_series(repo: pathlib.Path):
    # The ledger carries one row per state as well as the national row for
    # the same concept (fns.snap.total_payment_error_rate has 54). Pooling
    # them would average a country into one series.
    rows = ledger_rows()
    for index, row in enumerate(rows):
        row["geography"] = {
            "level": "state",
            "id": f"0400000US{index:02d}",
            "name": f"State {index}",
        }
    _manifest, manifest_path = system_one_run(repo, ledger=rows)

    questions = json.loads((manifest_path.parent / "questions.json").read_text())
    state = json.loads((manifest_path.parent / "state.json").read_text())
    assert questions["ladderBasis"] == "history_dispersion"
    assert state["ledgerObservations"]["rows"] == []
    assert state["ledgerObservations"]["rejectedRows"]["geography"] == len(rows)


def test_national_geography_rows_still_match(repo: pathlib.Path):
    _manifest, manifest_path = system_one_run(repo, ledger=national(ledger_rows()))

    questions = json.loads((manifest_path.parent / "questions.json").read_text())
    assert questions["ladderBasis"] == "ledger_dispersion"
    state = json.loads((manifest_path.parent / "state.json").read_text())
    assert state["ledgerObservations"]["matchRule"]["geographyId"] == "0100000US"


def test_numeric_fiscal_year_periods_match_a_fiscal_year_target():
    # Real ledger rows spell a fiscal year as a number; docket targets spell
    # it FY2026. A string-only rule silently matched neither.
    target = {**target_context(), "period": "FY2029"}
    rows = []
    for year in (2026, 2027, 2028, 2029):
        row = ledger_rows()[0]
        row["period"] = {"type": "fiscal_year", "value": year}
        row["observed_at"] = f"{year}-10-15"
        row["source_record_id"] = f"agency-test-rate-fy{year}"
        rows.append(row)

    selection = system_one.ledger_selection(target, national(rows), RUN_AT)

    assert [row["period"]["value"] for row in selection["rows"]] == [
        "2026",
        "2027",
        "2028",
    ]


def test_one_entity_lineage_survives():
    rows = national(ledger_rows())
    for row in rows[:2]:
        row["entity"] = {"name": "person", "role": "legacy"}
    for row in rows[2:]:
        row["entity"] = {"name": "person", "role": "current"}

    selection = system_one.ledger_selection(target_context(), rows, RUN_AT)

    assert selection["entityLineage"] == {"name": "person", "role": "current"}
    assert len(selection["rows"]) == len(rows) - 2
    assert selection["rejectedRows"]["entity"] == 2


def test_observed_at_cutoff_is_the_run_instant_not_the_day():
    rows = national(ledger_rows())
    rows[0]["observed_at"] = "2030-01-10T11:00:00Z"
    rows[1]["observed_at"] = "2030-01-10T12:30:00Z"

    selection = system_one.ledger_selection(target_context(), rows, RUN_AT)

    identifiers = [row["sourceRecordId"] for row in selection["rows"]]
    assert f"agency-test-rate-{HISTORY_PERIODS[0]}" in identifiers
    assert f"agency-test-rate-{HISTORY_PERIODS[1]}" not in identifiers
    assert selection["rejectedRows"]["observedAt"] == 1


# --- history as a series ----------------------------------------------------


def test_label_dated_history_is_ordered_by_its_own_period(repo: pathlib.Path):
    # Most published cells carry a null period and name it only in the label.
    cell = primary_cell()
    labels = ["Nov 2029", "Jun 2029", "Jul 2029", "Aug 2029", "Sep 2029", "Oct 2029"]
    values = [3.8, 3.1, 3.4, 3.2, 3.6, 3.5]
    cell["historicalContext"] = [
        {"label": label, "value": value, "period": None}
        for label, value in zip(labels, values)
    ]

    _manifest, manifest_path = system_one_run(repo, cell=cell, ledger=None)

    questions = json.loads((manifest_path.parent / "questions.json").read_text())
    assert questions["ladderBasis"] == "history_dispersion"
    # Ordered by period, the last observation is November, not the first row.
    assert questions["center"] == pytest.approx(3.8)


def test_history_that_repeats_a_period_is_refused(repo: pathlib.Path):
    # A second series in the same list (a four-week average, a CPI row beside
    # the real-earnings rows) reads as a series only because it is a list.
    cell = primary_cell()
    cell["historicalContext"] = [
        {"label": "May 2029 target series", "value": 3.1, "period": None},
        {"label": "Jun 2029 target series", "value": 3.4, "period": None},
        {"label": "Jul 2029 target series", "value": 3.2, "period": None},
        {"label": "Jul 2029 a different series entirely", "value": 41.0,
         "period": None},
    ]

    manifest, manifest_path = system_one_run(repo, cell=cell, ledger=None)

    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "state"
    assert manifest["error"]["detail"]["reason"] == "history_periods_repeat"
    assert verify_run(manifest_path.parent).run_succeeded is False


def test_undated_history_rows_are_dropped_not_reordered(repo: pathlib.Path):
    cell = primary_cell()
    cell["historicalContext"] = [
        {"label": "Jun 2029", "value": 3.1, "period": None},
        {"label": "Jul 2029", "value": 3.4, "period": None},
        {"label": "Aug 2029", "value": 3.2, "period": None},
        {"label": "latest 4-week average", "value": 90.0, "period": None},
    ]

    _manifest, manifest_path = system_one_run(repo, cell=cell, ledger=None)

    questions = json.loads((manifest_path.parent / "questions.json").read_text())
    assert questions["observationCount"] == 3
    assert questions["center"] == pytest.approx(3.2)
    state = json.loads((manifest_path.parent / "state.json").read_text())
    # The model still sees every row the cell reported; only the ladder is
    # built from the dated series.
    assert len(state["historicalContext"]["rows"]) == 4


# --- refusals and sealing ---------------------------------------------------


def test_a_blank_credential_is_a_refused_input(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    # typesafe_sdk strips the key and raises from its own constructor, which
    # used to escape halfway through a run.
    monkeypatch.setenv("TYPESAFE_API_KEY", "   ")
    write_primary_run(repo, primary_cell())

    with pytest.raises(system_one.SystemOneInputError, match="TYPESAFE_API_KEY"):
        system_one.run_forecast(
            target=target_context(),
            backend="typesafe",
            records_root=repo / "records",
            run_at=RUN_AT,
        )

    assert not (repo / "records" / "thesis-analyst" / RUN_AT[:10]).exists()


def test_an_unreadable_response_file_is_refused_before_any_run_directory(
    repo: pathlib.Path,
):
    write_primary_run(repo, primary_cell())

    with pytest.raises(system_one.SystemOneInputError, match="response file"):
        system_one.run_forecast(
            target=target_context(),
            backend="response_file",
            records_root=repo / "records",
            response_file=repo / "missing-response.json",
            run_at=RUN_AT,
        )

    assert not (repo / "records" / "thesis-analyst" / RUN_AT[:10]).exists()


def test_an_unexpected_backend_exception_is_sealed_as_a_backend_failure(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    def boom(**_kwargs):
        raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(system_one, "call_mock", boom)
    manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())

    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "backend"
    assert manifest["error"]["detail"]["exception"] == "RuntimeError"
    # The exception text could carry request detail, so only the class name
    # is recorded.
    assert "connection reset" not in json.dumps(manifest)
    assert [
        (ref["artifactType"], pathlib.Path(ref["path"]).name)
        for ref in manifest["artifacts"]
    ] == [
        ("system_one_state", "state.json"),
        ("system_one_questions", "questions.json"),
        ("system_one_request", "request.json"),
        ("command", "command.json"),
        ("error", "error.json"),
        ("manifest", "manifest.json"),
    ]
    assert verify_run(manifest_path.parent).run_succeeded is False


def test_a_crash_before_the_backend_seals_a_state_failure(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    def boom(**_kwargs):
        raise RuntimeError("questions exploded")

    monkeypatch.setattr(system_one, "question_payloads", boom)
    write_primary_run(repo, primary_cell())

    manifest, manifest_path = system_one.run_forecast(
        target=target_context(),
        backend="mock",
        records_root=repo / "records",
        run_at=RUN_AT,
    )
    # build_ladder ran, question_payloads did not: state.json alone is the
    # state-phase inventory, so the failure seals rather than vanishing.
    assert manifest["error"]["phase"] == "state"
    assert manifest["error"]["detail"]["exception"] == "RuntimeError"
    assert verify_run(manifest_path.parent).run_succeeded is False


def test_an_unsealable_crash_leaves_nothing_behind(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    # Nothing written so far is a whole phase inventory, so there is no
    # honest record to seal: the partial directory goes, and the runner
    # reports a refused input, which is what exit code 2 promises.
    real_write_artifact = system_one.write_artifact
    calls: list[str] = []

    def fail_on_request(out_dir, artifact_type, name, payload, created_at):
        calls.append(name)
        if name == "request.json":
            raise RuntimeError("disk gave out")
        return real_write_artifact(out_dir, artifact_type, name, payload, created_at)

    monkeypatch.setattr(system_one, "write_artifact", fail_on_request)
    write_primary_run(repo, primary_cell())

    with pytest.raises(system_one.SystemOneInputError, match="RuntimeError"):
        system_one.run_forecast(
            target=target_context(),
            backend="mock",
            records_root=repo / "records",
            run_at=RUN_AT,
        )

    assert calls == ["state.json", "questions.json", "request.json"]
    assert list((repo / "records" / "thesis-analyst" / RUN_AT[:10]).iterdir()) == []
