from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import strategy_comparisons as strategy  # noqa: E402
import thesis_records_to_comparisons as records_to_comparisons  # noqa: E402

from tests.test_run_system_one_forecast import (  # noqa: E402
    SLUG,
    ledger_rows,
    repo,  # noqa: F401 - pytest fixture
    system_one_run,
    target_context,
)

# The System One lane's fixture target, named for this module's readers.
SYSTEM_ONE_SLUG = SLUG


def run(variant_id: str, run_at: str = "2030-01-01T00:00:00Z") -> dict:
    return {
        "variantId": variant_id,
        "predictionRun": {"runAt": run_at},
    }


def test_all_record_regeneration_is_byte_identical(
    tmp_path: pathlib.Path,
) -> None:
    # Regenerate exactly like the publisher (frozen legacy index + real
    # suite records) and require byte-identity with the committed module.
    output = tmp_path / "strategy.ts"
    augments = strategy.all_record_augments()
    strategy.write_strategy_ts(output, augments)

    assert output.read_bytes() == (
        ROOT / "site/src/data/thesis-strategy-comparisons.ts"
    ).read_bytes()


def test_frozen_legacy_projection_is_preserved_inside_full_corpus(
    tmp_path: pathlib.Path,
) -> None:
    # The 2026-07-08 legacy wave is an immutable record set: its projection
    # is exactly 30 runs, and suite publications may only add runs on top.
    legacy_only = strategy.all_record_augments(
        legacy_index=strategy.LEGACY_INDEX,
        suites_root=tmp_path / "no-suites",
    )
    assert sum(map(len, legacy_only.values())) == 30

    full = strategy.all_record_augments()
    for slug, legacy_runs in legacy_only.items():
        assert len(full.get(slug, [])) >= len(legacy_runs)
    assert sum(map(len, full.values())) >= 30


def test_cli_always_regenerates_whole_corpus_and_rejects_partial_inputs(
    tmp_path: pathlib.Path,
) -> None:
    output = tmp_path / "strategy.ts"
    result = subprocess.run(
        [sys.executable, str(strategy.__file__), "--out", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == (
        ROOT / "site/src/data/thesis-strategy-comparisons.ts"
    ).read_bytes()

    partial = subprocess.run(
        [
            sys.executable,
            str(strategy.__file__),
            "--ladder-batch",
            "records/example.json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert partial.returncode != 0
    assert "unrecognized arguments: --ladder-batch" in partial.stderr

    override = subprocess.run(
        [sys.executable, str(strategy.__file__), "--suites-root", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert override.returncode != 0
    assert "unrecognized arguments: --suites-root" in override.stderr


def test_indexed_rollout_labels_are_fixed_within_each_suite(monkeypatch) -> None:
    target = {
        "catalogSlug": "example-target",
        "valueScale": 1,
        "targetUnit": "percent",
    }

    def results(paths):
        index = int(pathlib.Path(paths[0]).stem[-1])
        manifest = {
            "promptMode": "fast",
            "artifacts": [],
            "agent": {"agent": "thesis.analyst", "model": "fixture"},
        }
        cell = {
            "runAt": f"2030-01-01T00:00:0{index}Z",
            "sourceContext": [],
            "pointEstimate": index,
            "ciLow": index - 1,
            "ciHigh": index + 1,
            "confidence": 0.8,
            "drivers": [],
            "reasoning": [],
        }
        yield target, manifest, cell

    monkeypatch.setattr(strategy, "batch_results", results)
    first = strategy.indexed_rollout_augments(
        [
            (1, pathlib.Path("rollout-1")),
            (2, pathlib.Path("rollout-2")),
            (3, pathlib.Path("rollout-3")),
        ]
    )
    second = strategy.indexed_rollout_augments(
        [
            (1, pathlib.Path("second-1")),
            (2, pathlib.Path("second-2")),
            (3, pathlib.Path("second-3")),
        ]
    )

    assert [row["label"] for row in first["example-target"]] == [
        "Fast rollout 1 of 3",
        "Fast rollout 2 of 3",
        "Fast rollout 3 of 3",
    ]
    assert [row["label"] for row in second["example-target"]] == [
        "Fast rollout 1 of 3",
        "Fast rollout 2 of 3",
        "Fast rollout 3 of 3",
    ]


def test_suite_scanner_requires_exact_lane_shape(tmp_path: pathlib.Path) -> None:
    root = tmp_path / "strategy-suites"
    path = root / "2030-01-01" / "strategy-123-a1.json"
    path.parent.mkdir(parents=True)
    payload = {
        "schemaVersion": "thesis_strategy_suite_v1",
        "sourceSha": "a" * 40,
        "selectionPath": "records/selection.json",
        "selectionSha256": "b" * 64,
        "selectionSetHash": "c" * 64,
        "suite": "both",
        "createdAt": "2030-01-01T00:00:00Z",
        "lanes": {
            "ladder": {"batchManifest": "records/ladder.json"},
            "rollouts": [
                {"index": index, "batchManifest": f"records/rollout-{index}.json"}
                for index in range(1, 4)
            ],
            "median3": [
                {
                    "catalogSlug": "target",
                    "ok": False,
                    "manifestPath": None,
                    "error": "constituent failure",
                }
            ],
        },
    }
    path.write_text(json.dumps(payload))

    waves = strategy.load_suite_waves(root)
    assert [index for index, _path in waves[0]["rolloutBatches"]] == [1, 2, 3]

    payload["lanes"]["rollouts"].pop()
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="rollout lane cardinality"):
        strategy.load_suite_waves(root)

    payload["lanes"]["rollouts"] = [
        {"index": index, "batchManifest": f"records/rollout-{index}.json"}
        for index in range(1, 4)
    ]
    payload["suite"] = "median3"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="median3-only suite has a ladder"):
        strategy.load_suite_waves(root)


def test_new_median_projects_verified_parent_activity(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    distribution_path = tmp_path / "distribution.json"
    distribution_path.write_text(
        json.dumps(
            {
                "format": "numeric_cdf_v1",
                "pointCount": 2,
                "support": {"lower": 0, "upper": 1},
                "points": [
                    {"value": 0, "probability": 0},
                    {"value": 1, "probability": 1},
                ],
                "summary": {
                    "pointEstimate": 0.5,
                    "median": 0.5,
                    "interval80": {"lower": 0.1, "upper": 0.9},
                },
                "provenance": "agent_reported",
            }
        )
    )
    parent_activity = [
        {"artifactType": "constituent_manifest", "path": f"parent-{index}.json"}
        for index in range(1, 4)
    ] + [{"artifactType": "derived_distribution", "path": str(distribution_path)}]
    cells_path = tmp_path / "cells.json"
    cells_path.write_text(
        json.dumps(
            [
                {
                    "unit": "percent",
                    "pointEstimate": 0.5,
                    "ciLow": 0.1,
                    "ciHigh": 0.9,
                    "activityLog": parent_activity,
                }
            ]
        )
    )
    constituent_runs = [
        {
            "manifestPath": f"parent-{index}.json",
            "custodyRootSha256": str(index) * 64,
        }
        for index in range(1, 4)
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "ok": True,
                "targetContext": {
                    "catalogSlug": "example-target",
                    "targetUnit": "percent",
                    "valueScale": 1,
                },
                "cellsPath": str(cells_path),
                "aggregationAlgorithmVersion": "pointwise_median_cdf_v1",
                "constituentRuns": constituent_runs,
                "artifacts": [
                    {
                        "artifactType": "derived_distribution",
                        "path": str(distribution_path),
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(
        strategy,
        "comparison_run",
        lambda *_args, **_kwargs: {
            "description": "fixture",
            "predictionRun": {"activityLog": ["local-only"]},
        },
    )

    augments = strategy.median_augments([manifest_path])

    assert (
        augments["example-target"][0]["predictionRun"]["activityLog"]
        == parent_activity
    )
    assert (
        augments["example-target"][0]["predictionRun"]["constituentRuns"]
        == constituent_runs
    )


def test_strategy_custody_provenance_fields_are_typed() -> None:
    source = (ROOT / "site/src/data/forecast-cells.ts").read_text()

    assert "hashMode?: string;" in source
    assert "manifestSha256?: string;" in source
    assert "manifestBytes?: number;" in source


def test_merge_rejects_duplicate_variant_ids() -> None:
    with pytest.raises(ValueError, match="duplicate or missing strategy variantId"):
        strategy.merge(
            {"first": [run("duplicate")]},
            {"second": [run("duplicate", "2030-01-02T00:00:00Z")]},
        )


def test_model_lane_stats_regeneration_is_byte_identical(
    tmp_path: pathlib.Path,
) -> None:
    # Same publisher-defaults discipline as the comparisons module: the
    # committed stats must equal a fresh regeneration from records.
    rows = strategy.build_model_lane_stats()
    output = tmp_path / "model-lane-stats.generated.ts"
    strategy.write_model_lane_stats(output, rows)
    assert output.read_bytes() == strategy.MODEL_LANE_STATS_OUT.read_bytes()

    for row in rows:
        assert 0 <= row["passed"] <= row["attempted"]
    assert rows == sorted(
        rows, key=lambda row: (row["model"], row["lane"])
    )


def test_comparison_review_is_manifest_only_and_screened() -> None:
    # Round-two screen review: comparison projections copied
    # preSubmitReview verbatim (cell fallback included), so reviewer
    # text bypassed the screen and agent-planted review could attach.
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
    try:
        from thesis_records_to_comparisons import comparison_run
    finally:
        sys.path.pop(0)
    cell = {
        "runAt": "2026-08-12T00:00:00Z",
        "sourceContext": ["https://example.gov/series"],
        "unit": "percent",
        "pointEstimate": 1.0,
        "ciLow": 0.5,
        "ciHigh": 1.5,
        "confidence": 0.8,
        "drivers": ["driver"],
        "reasoning": [],
        # Agent-planted review: must never attach.
        "preSubmitReview": {"summary": "planted"},
    }
    manifest = {
        "agent": {"agent": "thesis.analyst", "model": "gpt-5.6-terra"},
        "artifacts": [],
        "preSubmitReview": {
            "schemaVersion": "thesis_pre_submit_review_v1",
            "status": "completed",
            "summary": "Attach the fetch transcript next time.",
            "findings": [
                {
                    "findingId": "review.suggestion.1",
                    "severity": "info",
                    "rubricItem": "optional_suggestion",
                    "summary": "Consider attaching the fetch transcript.",
                }
            ],
            "dispositions": [],
        },
    }
    run = comparison_run(cell, manifest, "fixture-target", 1)["predictionRun"]
    review = run["preSubmitReview"]
    marker = "[withheld by the private-source screen]"
    assert review["summary"] == marker
    assert review["findings"][0]["summary"] == marker
    assert "planted" not in json.dumps(run)

    # Manifest without review: the cell's planted claim still never attaches.
    bare = comparison_run(cell, {"agent": manifest["agent"], "artifacts": []},
                          "fixture-target", 1)["predictionRun"]
    assert "preSubmitReview" not in bare


# --- system one lane --------------------------------------------------------


def write_system_one_batch(
    repo_root: pathlib.Path,
    manifest: dict,
    manifest_path: pathlib.Path,
    *,
    ok: bool = True,
) -> pathlib.Path:
    """The batch manifest scripts/run_strategy_suite.py writes for the lane."""

    batch_path = (
        repo_root
        / "records"
        / "thesis-analyst"
        / "batches"
        / "2030-01-10"
        / "strategy-1-a1-system-one.json"
    )
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_batch_manifest_v1",
                "promptMode": "system_one_noul_ladder",
                "results": [
                    {
                        "target": target_context(),
                        "startedAt": manifest["runStartedAt"],
                        "finishedAt": manifest["sealedAt"],
                        "ok": ok,
                        "manifestPath": manifest_path.relative_to(
                            repo_root
                        ).as_posix(),
                        "cellsPath": manifest["cellsPath"],
                        "error": None,
                    }
                ],
            },
            indent=2,
        )
    )
    return batch_path


def write_system_one_suite(
    repo_root: pathlib.Path, batch_path: pathlib.Path
) -> pathlib.Path:
    suites_root = repo_root / "records" / "thesis-analyst" / "strategy-suites"
    path = suites_root / "2030-01-10" / "strategy-1-a1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": strategy.SUITE_SCHEMA,
                "sourceSha": "a" * 40,
                "selectionPath": "records/selection.json",
                "selectionSha256": "b" * 64,
                "selectionSetHash": "c" * 64,
                "suite": "system_one",
                "createdAt": "2030-01-10T12:00:00Z",
                "lanes": {
                    "ladder": None,
                    "rollouts": [],
                    "median3": [],
                    "systemOne": {
                        "batchManifest": batch_path.relative_to(
                            repo_root
                        ).as_posix(),
                        "backend": "mock",
                        "model": "mock",
                    },
                },
            },
            indent=2,
        )
    )
    return suites_root


@pytest.fixture
def system_one_batch(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> tuple[pathlib.Path, pathlib.Path, dict]:
    """A sealed System One run, its batch manifest, and the repo it lives in."""

    manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    assert manifest["ok"] is True
    batch_path = write_system_one_batch(repo, manifest, manifest_path)
    # The projection resolves record paths against the repository root; point
    # it at the fixture checkout so no test ever reads the real records tree.
    monkeypatch.setattr(records_to_comparisons, "ROOT", repo)
    return batch_path, manifest_path, manifest


def test_system_one_projection_carries_the_lane_identity(
    system_one_batch: tuple[pathlib.Path, pathlib.Path, dict],
) -> None:
    batch_path, manifest_path, manifest = system_one_batch

    augments = strategy.system_one_augments([batch_path])

    assert list(augments) == [SYSTEM_ONE_SLUG]
    run = augments[SYSTEM_ONE_SLUG][0]
    prediction_run = run["predictionRun"]

    assert prediction_run["agent"] == "thesis.system_one"
    assert prediction_run["model"] == manifest["agent"]["model"] == "mock"
    assert prediction_run["promptMode"] == "system_one_noul_ladder"
    assert prediction_run["agentVersion"] == "0.1.0"
    assert prediction_run["kind"] == "recorded-agent-run"
    # A mock run is not a System One run, and the row says so; only the
    # typesafe backend earns the bare lane label.
    assert run["label"] == "System One emulation (mock)"
    assert prediction_run["runLabel"] == "System One emulation (mock)"

    # The variant id and the copy are the lane's own: no analyst identity is
    # borrowed by a run the analyst never made.
    assert run["variantId"].startswith(f"{SYSTEM_ONE_SLUG}-thesis-system-one-")
    assert "thesis-analyst" not in run["variantId"]
    assert "thesis.analyst" not in json.dumps(run)
    assert "Codex" not in run["description"]
    assert "deterministic offline stand-in, not a model" in run["description"]
    assert "no chain of thought" not in run["description"]
    assert "monotonized ladder itself" in run["description"]
    assert "sealed" in prediction_run["runDescription"]

    # The activity log is the sealed inventory, not the cell's own claim.
    assert prediction_run["activityLog"] == manifest["artifacts"]
    assert {ref["artifactType"] for ref in prediction_run["activityLog"]} >= {
        "system_one_state",
        "system_one_questions",
        "system_one_request",
        "system_one_response",
        "manifest",
    }

    cell = json.loads(
        (manifest_path.parent / "cells.with_activity.json").read_text()
    )[0]
    assert run["pointEstimate"] == cell["pointEstimate"]
    assert run["ciLow"] == cell["ciLow"]
    assert run["ciHigh"] == cell["ciHigh"]
    assert run["reasoning"] == cell["reasoning"]


def test_system_one_projection_materializes_the_ladder_cdf(
    system_one_batch: tuple[pathlib.Path, pathlib.Path, dict],
) -> None:
    batch_path, manifest_path, _manifest = system_one_batch

    run = strategy.system_one_augments([batch_path])[SYSTEM_ONE_SLUG][0]
    distribution = run["predictionDistribution"]
    cell = json.loads(
        (manifest_path.parent / "cells.with_activity.json").read_text()
    )[0]

    assert distribution["format"] == "numeric_cdf_v1"
    assert distribution["provenance"] == "agent_reported"
    assert distribution["pointCount"] == strategy.POINT_COUNT
    assert len(distribution["points"]) == strategy.POINT_COUNT
    probabilities = [point["probability"] for point in distribution["points"]]
    assert probabilities == sorted(probabilities)
    assert probabilities[0] == 0.0
    assert probabilities[-1] == 1.0
    values = [point["value"] for point in distribution["points"]]
    assert values == sorted(values)
    assert distribution["support"]["lower"] <= cell["thresholdLadder"]["thresholds"][0]
    assert distribution["support"]["upper"] >= cell["thresholdLadder"]["thresholds"][-1]
    assert distribution["summary"]["pointEstimate"] == cell["pointEstimate"]
    assert distribution["summary"]["interval80"] == {
        "lower": cell["ciLow"],
        "upper": cell["ciHigh"],
    }

    # The published CDF is the monotonized ladder: every rung's cumulative
    # probability is reproduced by the interpolated curve.
    ladder = cell["thresholdLadder"]
    for threshold, probability in zip(
        ladder["thresholds"], ladder["cumulativeProbabilities"]
    ):
        nearest = min(
            distribution["points"], key=lambda p: abs(p["value"] - threshold)
        )
        assert nearest["probability"] == pytest.approx(probability, abs=5e-3)


def test_system_one_projection_refuses_a_foreign_run(
    system_one_batch: tuple[pathlib.Path, pathlib.Path, dict],
) -> None:
    # A batch listed as the System One lane cannot launder another agent's
    # run into the lane's label: the manifest itself has to say system_one.
    batch_path, manifest_path, manifest = system_one_batch
    manifest["agent"]["agent"] = "thesis.analyst"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    with pytest.raises(ValueError, match="non-system-one run"):
        strategy.system_one_augments([batch_path])

    manifest["agent"]["agent"] = "thesis.system_one"
    manifest["runMode"] = "analyst"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    with pytest.raises(ValueError, match="non-system-one run"):
        strategy.system_one_augments([batch_path])


def test_system_one_failures_are_recorded_but_never_published(
    repo: pathlib.Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A failed run still seals a manifest and still counts as attempted in
    # the lane stats; it must not reach a published comparison row.
    manifest, manifest_path = system_one_run(repo, ledger=ledger_rows())
    batch_path = write_system_one_batch(repo, manifest, manifest_path, ok=False)
    monkeypatch.setattr(records_to_comparisons, "ROOT", repo)
    suites_root = write_system_one_suite(repo, batch_path)
    empty_legacy = repo / "legacy.json"
    empty_legacy.write_text(
        json.dumps({"schemaVersion": strategy.LEGACY_INDEX_SCHEMA, "waves": []})
    )

    assert strategy.system_one_augments([batch_path]) == {}
    assert strategy.build_model_lane_stats(
        legacy_index=empty_legacy, suites_root=suites_root
    ) == [{"model": "mock", "lane": "system_one", "attempted": 1, "passed": 0}]


def test_system_one_suite_reaches_the_published_corpus(
    system_one_batch: tuple[pathlib.Path, pathlib.Path, dict],
    tmp_path: pathlib.Path,
) -> None:
    batch_path, _manifest_path, _manifest = system_one_batch
    repo_root = batch_path.parents[4]
    suites_root = write_system_one_suite(repo_root, batch_path)
    empty_legacy = tmp_path / "legacy.json"
    empty_legacy.write_text(
        json.dumps({"schemaVersion": strategy.LEGACY_INDEX_SCHEMA, "waves": []})
    )

    waves = strategy.load_suite_waves(suites_root)
    assert [path.name for path in waves[0]["systemOneBatches"]] == [
        batch_path.name
    ]

    augments = strategy.all_record_augments(
        legacy_index=empty_legacy, suites_root=suites_root
    )
    assert list(augments) == [SYSTEM_ONE_SLUG]
    assert augments[SYSTEM_ONE_SLUG][0]["predictionRun"]["agent"] == (
        "thesis.system_one"
    )

    assert strategy.build_model_lane_stats(
        legacy_index=empty_legacy, suites_root=suites_root
    ) == [{"model": "mock", "lane": "system_one", "attempted": 1, "passed": 1}]


def test_suite_scanner_binds_the_system_one_lane_to_its_selector(
    system_one_batch: tuple[pathlib.Path, pathlib.Path, dict],
) -> None:
    batch_path, _manifest_path, _manifest = system_one_batch
    repo_root = batch_path.parents[4]
    suites_root = write_system_one_suite(repo_root, batch_path)
    path = suites_root / "2030-01-10" / "strategy-1-a1.json"
    payload = json.loads(path.read_text())

    # A ladder suite may not smuggle a System One batch through the lane key.
    ladder_suite = json.loads(json.dumps(payload))
    ladder_suite["suite"] = "ladder"
    ladder_suite["lanes"]["ladder"] = {"batchManifest": "records/ladder.json"}
    path.write_text(json.dumps(ladder_suite))
    with pytest.raises(ValueError, match="carries a system one lane"):
        strategy.load_suite_waves(suites_root)

    # A system_one suite has to carry the lane it claims to be.
    missing = json.loads(json.dumps(payload))
    missing["lanes"]["systemOne"] = None
    path.write_text(json.dumps(missing))
    with pytest.raises(ValueError, match="lacks its system one lane"):
        strategy.load_suite_waves(suites_root)

    # ... and it may not carry the analyst lanes.
    with_ladder = json.loads(json.dumps(payload))
    with_ladder["lanes"]["ladder"] = {"batchManifest": "records/ladder.json"}
    path.write_text(json.dumps(with_ladder))
    with pytest.raises(ValueError, match="system_one-only suite has a ladder"):
        strategy.load_suite_waves(suites_root)

    with_median = json.loads(json.dumps(payload))
    with_median["lanes"]["median3"] = [
        {
            "catalogSlug": SYSTEM_ONE_SLUG,
            "ok": False,
            "manifestPath": None,
            "error": "constituent failure",
        }
    ]
    path.write_text(json.dumps(with_median))
    with pytest.raises(
        ValueError, match="system_one-only suite has median3 lanes"
    ):
        strategy.load_suite_waves(suites_root)

    # An unknown lane key is still refused outright.
    unknown = json.loads(json.dumps(payload))
    unknown["lanes"]["somethingElse"] = None
    path.write_text(json.dumps(unknown))
    with pytest.raises(ValueError, match="invalid strategy lane inventory"):
        strategy.load_suite_waves(suites_root)


def test_legacy_lane_inventory_without_the_system_one_key_still_loads(
    tmp_path: pathlib.Path,
) -> None:
    # Every suite committed before the lane existed carries three lane keys.
    root = tmp_path / "strategy-suites"
    path = root / "2030-01-01" / "strategy-9-a1.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": strategy.SUITE_SCHEMA,
                "suite": "ladder",
                "lanes": {
                    "ladder": {"batchManifest": "records/ladder.json"},
                    "rollouts": [],
                    "median3": [],
                },
            }
        )
    )

    waves = strategy.load_suite_waves(root)
    assert waves[0]["systemOneBatches"] == []


def test_system_one_lane_stats_are_tallied_per_run_not_per_batch(
    repo: pathlib.Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    # A typesafe batch learns each model name from the response it got, so
    # one batch can hold more than one, and a run that failed before any
    # response names none. Filing the batch under its first result's model
    # tallied the rest under a model that never answered them.
    first_manifest, first_path = system_one_run(repo, ledger=ledger_rows())
    second_manifest, second_path = system_one_run(
        repo, ledger=ledger_rows(), run_at="2030-01-10T13:00:00Z"
    )
    second_manifest["agent"]["model"] = "jev-1-2030-01"
    second_path.write_text(json.dumps(second_manifest, indent=2))
    batch_path = write_system_one_batch(repo, first_manifest, first_path)
    batch = json.loads(batch_path.read_text())
    batch["results"].append(
        {
            "target": target_context(),
            "startedAt": second_manifest["runStartedAt"],
            "finishedAt": second_manifest["sealedAt"],
            "ok": False,
            "manifestPath": second_path.relative_to(repo).as_posix(),
            "cellsPath": second_manifest["cellsPath"],
            "error": "sealed failure",
        }
    )
    batch_path.write_text(json.dumps(batch, indent=2))
    monkeypatch.setattr(records_to_comparisons, "ROOT", repo)
    suites_root = write_system_one_suite(repo, batch_path)
    empty_legacy = tmp_path / "legacy.json"
    empty_legacy.write_text(
        json.dumps({"schemaVersion": strategy.LEGACY_INDEX_SCHEMA, "waves": []})
    )

    assert strategy.build_model_lane_stats(
        legacy_index=empty_legacy, suites_root=suites_root
    ) == [
        {"model": "jev-1-2030-01", "lane": "system_one", "attempted": 1, "passed": 0},
        {"model": "mock", "lane": "system_one", "attempted": 1, "passed": 1},
    ]
