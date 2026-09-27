from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import strategy_comparisons as strategy  # noqa: E402


def run(variant_id: str, run_at: str = "2030-01-01T00:00:00Z") -> dict:
    return {
        "variantId": variant_id,
        "predictionRun": {"runAt": run_at},
    }


@pytest.mark.parametrize(
    "sibling_state, expected",
    [
        ("complete", ["arm-0", "arm-1"]),
        ("failed", []),
        ("missing", []),
        ("empty", []),
        ("duplicate-condition", []),
    ],
)
def test_conditional_comparisons_publish_only_complete_pairs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    sibling_state: str,
    expected: list[str],
) -> None:
    rows = []
    for index in range(2):
        manifest = tmp_path / f"manifest-{index}.json"
        cells = tmp_path / f"cells-{index}.json"
        manifest.write_text(json.dumps({"ok": True}))
        cells.write_text(json.dumps([{"slug": f"arm-{index}"}]))
        rows.append(
            {
                "ok": True,
                "manifestPath": str(manifest),
                "cellsPath": str(cells),
                "target": {
                    "catalogSlug": f"arm-{index}",
                    "dataPointId": f"id-{index}",
                    "series": "agency.metric",
                    "period": "2030",
                    "conditional": f"premise-{index}",
                    "conditionId": f"condition-{index}",
                },
            }
        )
    if sibling_state == "failed":
        rows[1]["ok"] = False
        rows[1]["cellsPath"] = None
    elif sibling_state == "missing":
        rows.pop()
    elif sibling_state == "empty":
        pathlib.Path(rows[1]["cellsPath"]).write_text("[]")
    elif sibling_state == "duplicate-condition":
        rows[1]["target"]["conditionId"] = rows[0]["target"]["conditionId"]
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"results": rows}))
    monkeypatch.setattr(strategy, "repo_path", pathlib.Path)
    assert [
        target["catalogSlug"] for target, _, _ in strategy.batch_results([batch])
    ] == expected
    # Suppression does not erase either the failed attempt or its successful
    # sibling from the immutable batch archive.
    assert json.loads(batch.read_text())["results"] == rows


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
        "agent": {"agent": "thesis.analyst", "model": "gpt-5.5"},
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
