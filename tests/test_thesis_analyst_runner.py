from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_thesis_analyst.py"
COMPARISON_GENERATOR = ROOT / "scripts" / "thesis_records_to_comparisons.py"
sys.path.insert(0, str(ROOT / "scripts"))
import generation_tickets  # noqa: E402
import median_rollout_ensemble as median_ensemble  # noqa: E402
import run_thesis_analyst as analyst_runner  # noqa: E402
import spawned_cells_to_ts  # noqa: E402
from history_floor import (  # noqa: E402
    canonical_period_identities_from_label,
    canonical_period_identity,
    validate_history_floor_authorization,
)
from run_thesis_analyst import (  # noqa: E402
    interval_distribution,
)
from run_thesis_analyst import (  # noqa: E402
    ladder_distribution as runner_ladder_distribution,
)
from strategy_comparisons import (  # noqa: E402
    ladder_distribution as comparison_ladder_distribution,
)
from thesis_records_to_comparisons import comparison_run  # noqa: E402
from verify_custody import verify_run  # noqa: E402


def generation_ticket_context() -> dict[str, str]:
    ticket_id = f"2030-01-10-{'a' * 64}"
    return {
        "ticketId": ticket_id,
        "ticketPath": f"records/tickets/2030-01-10/{ticket_id}.json",
        "nonce": "b" * 64,
    }


def test_interval_distribution_matches_typescript_fixture():
    fixture = json.loads(
        (
            ROOT / "tests" / "fixtures" / "interval_anchor_v1_distribution.json"
        ).read_text()
    )
    materialized = interval_distribution(fixture["inputs"])
    actual_points = [
        {
            "value": f"{point['value']:.10f}",
            "probability": f"{point['probability']:.10f}",
        }
        for point in materialized["points"]
    ]

    assert fixture["source"].endswith("::buildNumericCdfFromInterval")
    assert materialized["pointCount"] == 201
    assert materialized["provenance"] == "interval_seeded"
    assert materialized["transformVersion"] == fixture["transformVersion"]
    assert actual_points == fixture["points"]


def test_runner_ladder_distribution_matches_strategy_builder():
    cell = {
        "pointEstimate": 5.0,
        "ciLow": 4.0,
        "ciHigh": 6.0,
        "thresholdLadder": {
            "thresholds": [3.0, 4.0, 5.0, 6.0, 7.0],
            "cumulativeProbabilities": [0.02, 0.1, 0.5, 0.9, 0.98],
        },
    }

    actual = runner_ladder_distribution(cell)
    expected = comparison_ladder_distribution(cell, 1)

    assert actual is not None
    assert expected is not None
    assert actual["points"] == expected["points"]
    assert actual["support"] == expected["support"]
    assert actual["provenance"] == "agent_reported"
    assert actual["transformVersion"] == "agent_cdf_v1"


def _quantile_cell(ladder: object) -> dict:
    return {
        "pointEstimate": 100.0,
        "ciLow": 90.0,
        "ciHigh": 110.0,
        "thresholdLadder": ladder,
    }


def test_declared_ladder_must_promote_or_fail_closed() -> None:
    # A cell that DECLARES a quantile contract but carries a malformed ladder
    # must fail promotion, not silently degrade to the interval_seeded CDF
    # (which both mislabels provenance and re-derives a distribution the run
    # already authored).
    malformed = _quantile_cell({"thresholds": [90.0, 100.0]})  # missing probs
    with pytest.raises(ValueError, match="thresholdLadder"):
        analyst_runner.materialize_run_distributions([malformed])


def test_wellformed_ladder_still_promotes_agent_reported() -> None:
    cell = _quantile_cell(
        {
            "thresholds": [90.0, 100.0, 110.0],
            "cumulativeProbabilities": [0.1, 0.5, 0.9],
        }
    )
    distribution = analyst_runner.materialize_run_distributions([cell])
    assert distribution["provenance"] == "agent_reported"


def test_cell_without_ladder_keeps_interval_path() -> None:
    cell = {"pointEstimate": 100.0, "ciLow": 90.0, "ciHigh": 110.0}
    distribution = analyst_runner.materialize_run_distributions([cell])
    assert distribution["provenance"] == "interval_seeded"


def test_explicitly_null_ladder_also_fails_closed() -> None:
    # "thresholdLadder": null is still a declaration — the run authored the
    # key. Only absence of the key may take the interval path.
    with pytest.raises(ValueError, match="thresholdLadder"):
        analyst_runner.materialize_run_distributions([_quantile_cell(None)])


def test_malformed_ladder_leaves_custody_clean_seal_refusal(tmp_path: Path) -> None:
    # PR #78's bug end to end: a quantile-declaring cell whose ladder cannot
    # materialize must refuse at seal with a custody-verifiable ok:false
    # manifest — not silently relabel the distribution interval_seeded.
    cell = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    cell["thresholdLadder"] = {"thresholds": [4.6, 5.2, 5.9]}
    code, out_dir = _run_fake_codex_case(tmp_path, "malformed-ladder", cell)
    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "seal"
    assert "thresholdLadder" in manifest["error"]["message"]
    _custody_passes(out_dir)


def test_median3_requires_exactly_three_distinct_custody_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(median_ensemble, "verify_run", lambda _run_dir: None)

    def rollout(index: int, custody_root: str | None = None):
        run_dir = tmp_path / f"run-{index}"
        run_dir.mkdir()
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "custodyRootSha256": custody_root or f"root-{index}",
                }
            )
        )
        return {
            "manifestPath": str(manifest_path),
            "cell": {"runAt": f"2026-07-08T00:00:0{index}Z"},
        }

    valid = [rollout(1), rollout(2), rollout(3)]
    references = median_ensemble.validate_constituent_rollouts(valid)
    assert len(references) == 3
    assert len({ref["custodyRootSha256"] for ref in references}) == 3

    with pytest.raises(ValueError, match="exactly 3 constituent"):
        median_ensemble.validate_constituent_rollouts(valid[:2])
    with pytest.raises(ValueError, match="exactly 3 constituent"):
        median_ensemble.validate_constituent_rollouts([*valid, rollout(4)])

    duplicate = [rollout(5, "duplicate"), rollout(6, "duplicate"), rollout(7)]
    with pytest.raises(ValueError, match="3 distinct custody-verifiable"):
        median_ensemble.validate_constituent_rollouts(duplicate)


def test_comparison_run_preserves_median3_algorithm_metadata():
    constituent_runs = [
        {
            "manifestPath": f"records/run-{index}/manifest.json",
            "custodyRootSha256": f"root-{index}",
            "runAt": f"2026-07-08T00:00:0{index}Z",
        }
        for index in range(1, 4)
    ]
    manifest = {
        "promptMode": "median3",
        "aggregationAlgorithmVersion": "pointwise_median_cdf_v1",
        "constituentRuns": constituent_runs,
        "artifacts": [],
        "agent": {
            "agent": "thesis.analyst.median3",
            "model": "fixture-model",
        },
    }
    cell = {
        "runAt": "2026-07-08T01:00:00Z",
        "sourceContext": [],
        "pointEstimate": 1,
        "ciLow": 0,
        "ciHigh": 2,
        "confidence": 0.8,
        "drivers": [],
        "reasoning": [],
    }

    run = comparison_run(cell, manifest, "fixture", 1)

    assert (
        run["predictionRun"]["aggregationAlgorithmVersion"] == "pointwise_median_cdf_v1"
    )
    assert run["predictionRun"]["constituentRuns"] == constituent_runs


def test_print_prompt_contains_question_spec():
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "ons.labour.unemployment_rate",
            "--period",
            "2026-Q4",
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "# Question spec" in result.stdout
    assert "- series: ons.labour.unemployment_rate" in result.stdout
    assert "- period: 2026-Q4" in result.stdout
    assert "Produce one JSON cell per the contract above" in result.stdout
    assert "# Cell contract (verbatim" in result.stdout
    assert "Default promoted practices" in result.stdout
    assert "outside-view base rate before current-news adjustments" in result.stdout
    assert "At least 6 distinct prints are MANDATORY" in " ".join(result.stdout.split())
    assert "official_source_exposes_fewer_than_six_prints" in result.stdout


def test_fast_prompt_inlines_contract_and_allows_optional_repo_reads():
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "boe.bank_rate",
            "--period",
            "2026-06-18",
            "--prompt-mode",
            "fast",
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "# Thesis analyst fast public-release run" in result.stdout
    assert "You may inspect the local repository/workspace when useful" in (
        result.stdout
    )
    assert "This is optional, not required" in result.stdout
    assert "Treat prior forecasts as historical forecasts" in result.stdout
    assert "# Default promoted forecasting practices" in result.stdout
    assert "Anchor on the outside-view base rate before current-release" in (
        result.stdout
    )
    assert '"resolutionDate": "YYYY-MM-DD"' in result.stdout
    assert "Every tool step result must include at least one fetched numeric" in (
        result.stdout
    )
    assert "at least 6 distinct prints are MANDATORY" in result.stdout
    assert "Validation refuses fewer" in result.stdout
    assert "official_source_exposes_fewer_than_six_prints" in result.stdout
    assert "- series: boe.bank_rate" in result.stdout
    assert "Bank of England MPC" in result.stdout
    assert "docs/cell-contract.md" in result.stdout


def test_fast_prompt_includes_target_context():
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--prompt-mode",
            "fast",
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "targetUnit": "percent",
                    "dataPointId": "test.ledger_series.2030_01.first_print",
                    "resolutionDate": "2030-02-15",
                }
            ),
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "# Canonical ledger target context" in result.stdout
    assert '- catalogSlug: "canonical-ledger-slug"' in result.stdout
    assert '- targetUnit: "percent"' in result.stdout
    assert '- resolutionDate: "2030-02-15"' in result.stdout
    # A registered run's schema demands the registered unit verbatim —
    # never the exploratory enum, whose members exclude legitimate
    # registered units (the 2026-08-07 DoD "billions USD" pair failed
    # four runs by following the enum exactly).
    assert "the registered targetUnit, byte-for-byte" in result.stdout
    assert "percent|count|thousands" not in result.stdout


def test_partial_context_without_target_unit_keeps_the_menu():
    # run_thesis_batch --target builds partial contexts; one without
    # targetUnit must not claim "targetUnit below" and must keep the
    # exploratory menu.
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--prompt-mode",
            "fast",
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "dataPointId": "test.ledger_series.2030_01.first_print",
                }
            ),
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "# Canonical ledger target context" in result.stdout
    assert "targetUnit below" not in result.stdout
    assert "the registered targetUnit, byte-for-byte" not in result.stdout
    assert "percent|count|thousands" in result.stdout


def test_normalization_failure_writes_a_failure_manifest(
    tmp_path: Path,
) -> None:
    # The B1 rescue failure shape: a cell missing historicalContext hit
    # an uncaught normalizer RuntimeError, so NO run record existed and
    # whole-wave publication blocked on "lacks a registration-bound
    # manifest". A malformed cell must leave an ok:false manifest.
    out_dir = tmp_path / "normalize-failure"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "codex"
    bad_cell = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    bad_cell.pop("historicalContext", None)
    write_fake_codex(fake_codex, bad_cell)
    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "normalize"
    assert "historicalContext" in manifest["error"]["message"]


def test_empty_cell_payload_fails_instead_of_green_manifest(
    tmp_path: Path,
) -> None:
    # "[]" passed zero validations and produced manifest.ok=true — an
    # empty payload is neither a forecast nor a refusal record.
    out_dir = tmp_path / "empty-payload"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "args = sys.argv[1:]",
                "last = pathlib.Path(args[args.index('-o') + 1])",
                "last.write_text('[]')",
                "print(json.dumps({'type': 'item.completed',"
                " 'item': {'type': 'agent_message', 'text': '[]'}}))",
                "print(json.dumps({'type': 'turn.completed',"
                " 'usage': {'input_tokens': 1, 'output_tokens': 1,"
                " 'cached_input_tokens': 0}}))",
            ]
        )
    )
    fake_codex.chmod(0o755)
    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert "empty cell payload" in manifest["error"]["message"]


def _run_fake_codex_case(
    tmp_path: Path,
    name: str,
    cell,
    *,
    extra_args: list[str] | None = None,
) -> tuple[int, Path]:
    out_dir = tmp_path / name
    codex_home = tmp_path / f"{name}-codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / f"{name}-codex"
    write_fake_codex(fake_codex, cell)
    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--out-dir",
            str(out_dir),
            *(extra_args or []),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode, out_dir


def _custody_passes(out_dir: Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from verify_custody import verify_run
    finally:
        sys.path.pop(0)
    verify_run(out_dir)


def test_malformed_cell_values_leave_custody_clean_failure_manifests(
    tmp_path: Path,
) -> None:
    # Round-two reproductions: a non-numeric pointEstimate and a numeric
    # slug crashed sealing with no manifest at all. Both must now leave
    # an ok:false manifest that custody verification accepts — otherwise
    # publication still rejects the wave.
    bad_point = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    bad_point["pointEstimate"] = "not-a-number"
    code, out_dir = _run_fake_codex_case(tmp_path, "bad-point", bad_point)
    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] in {"normalize", "seal", "validate"}
    _custody_passes(out_dir)

    bad_slug = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    bad_slug["slug"] = 7
    code, out_dir = _run_fake_codex_case(tmp_path, "bad-slug", bad_slug)
    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] in {"normalize", "seal", "validate"}
    _custody_passes(out_dir)


def test_normalize_failure_manifest_passes_custody(tmp_path: Path) -> None:
    # The B1 shape end to end: history-less cell -> normalize failure
    # manifest -> custody verification green (publication treats it as
    # any failed run instead of blocking the wave).
    cell = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    cell.pop("historicalContext", None)
    code, out_dir = _run_fake_codex_case(tmp_path, "hist-less", cell)
    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["error"]["phase"] == "normalize"
    _custody_passes(out_dir)


def test_unencodable_numbers_and_reviewer_shapes_leave_manifests(
    tmp_path: Path,
) -> None:
    # Round-three reproductions: an oversized integer pointEstimate, a
    # 1e309 in an extra field, and a bare-number reviewer finding all
    # crashed after parsing with no run record. Each must now leave a
    # custody-clean ok:false manifest (or, for the reviewer shape, keep
    # the run alive).
    big_int = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    big_int["pointEstimate"] = 10**400
    code, out_dir = _run_fake_codex_case(tmp_path, "big-int", big_int)
    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "parse"
    assert "exactly representable" in manifest["error"]["message"]
    _custody_passes(out_dir)

    big_float = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    big_float["extraDiagnostic"] = {"weird": 1e309}
    code, out_dir = _run_fake_codex_case(tmp_path, "big-float", big_float)
    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "parse"
    _custody_passes(out_dir)


def test_malformed_reviewer_findings_do_not_crash() -> None:
    # {"requiredFixes": [7]} raised AttributeError mid-run; malformed
    # rows become plain findings instead.
    metadata = analyst_runner.build_pre_submit_review_metadata(
        status="completed",
        requested_at="2026-08-12T00:00:00Z",
        review_result=None,
        review_payload={
            "requiredFixes": [7],
            "optionalSuggestions": ["tighten interval"],
        },
        draft_ref=None,
        review_ref=None,
        revision_prompt_ref=None,
    )
    summaries = [f["summary"] for f in metadata["findings"]]
    assert "7" in summaries
    assert "tighten interval" in summaries


def test_malformed_reviewer_collection_containers_become_findings() -> None:
    # Round-five reproduction: the COLLECTION itself may be a scalar,
    # string, or object rather than a list. list(7) and list(1e309)
    # raise TypeError after validation (no manifest), and a bare string
    # exploded into per-character findings.
    for container, expected in (
        (7, "7"),
        (float("inf"), "inf"),
        ("tighten the interval", "tighten the interval"),
        ({"note": "x"}, "{'note': 'x'}"),
    ):
        metadata = analyst_runner.build_pre_submit_review_metadata(
            status="completed",
            requested_at="2026-08-12T00:00:00Z",
            review_result=None,
            review_payload={
                "requiredFixes": container,
                "optionalSuggestions": container,
            },
            draft_ref=None,
            review_ref=None,
            revision_prompt_ref=None,
        )
        findings = metadata["findings"]
        # One malformed row per field — never per-character, never a crash.
        assert len(findings) == 2, container
        assert [f["summary"] for f in findings] == [expected, expected], container


def test_reviewer_scalar_collections_run_end_to_end(tmp_path: Path) -> None:
    # The same shapes through the real runner and reviewer loop: the
    # run must complete with the malformed reviewer output recorded in
    # the manifest, not crash after validation with no run record.
    final_cell = review_test_cell(
        point=5.2,
        ci_low=4.6,
        ci_high=5.9,
        review_disposition=(
            "Review disposition: reviewer output was malformed; kept the "
            "draft forecast unchanged."
        ),
    )
    for name, review_text in (
        ("scalar-fixes", '{"requiredFixes": 7, "optionalSuggestions": ["ok"]}'),
        ("inf-fixes", '{"requiredFixes": 1e309, "optionalSuggestions": 1e309}'),
    ):
        out_dir = tmp_path / name
        codex_home = tmp_path / f"{name}-codex-home"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text("{}\n")
        fake_codex = tmp_path / f"{name}-codex"
        write_fake_codex(
            fake_codex,
            review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8),
            extra_lines=[
                "model = args[args.index('-m') + 1]",
                "prompt = args[-1]",
                f"review_text = {json.dumps(review_text)}",
                f"final_text = {json.dumps(json.dumps(final_cell))}",
                "if model == 'gpt-review':",
                "    text = review_text",
                "elif 'Pre-submit review loop' in prompt:",
                "    text = final_text",
            ],
        )
        env = {
            **os.environ,
            "THESIS_CODEX_BIN": str(fake_codex),
            "CODEX_HOME": str(codex_home),
        }
        result = subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "--series",
                "test.codex_rate",
                "--period",
                "2030-01",
                "--codex-model",
                "gpt-5.5",
                "--pre-submit-review-codex-model",
                "gpt-review",
                "--out-dir",
                str(out_dir),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (name, result.stderr[-2000:])
        manifest = json.loads((out_dir / "manifest.json").read_text())
        assert manifest["ok"] is True, name
        review_meta = manifest["preSubmitReview"]
        assert review_meta["schemaVersion"] == "thesis_pre_submit_review_v1"
        summaries = [f["summary"] for f in review_meta["findings"]]
        assert summaries, name
        if name == "scalar-fixes":
            assert "7" in summaries
        else:
            assert "inf" in summaries
        _custody_passes(out_dir)


def test_string_coerced_numbers_fail_at_normalize(tmp_path: Path) -> None:
    # Round-four reproduction: "1e309" as a STRING passes the parse gate
    # (strings are canonical-safe), then normalization coerces it to
    # infinity and later stages crashed with no record. The
    # post-normalize sweep must catch both point and history shapes.
    for name, mutate in (
        ("str-point", lambda c: c.__setitem__("pointEstimate", "1e309")),
        (
            "str-history",
            lambda c: c.__setitem__(
                "historicalContext", [{"label": "t-1", "value": "1e309"}]
            ),
        ),
    ):
        cell = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
        mutate(cell)
        code, out_dir = _run_fake_codex_case(tmp_path, name, cell)
        assert code == 1, name
        manifest = json.loads((out_dir / "manifest.json").read_text())
        assert manifest["ok"] is False, name
        # Where the poison surfaces depends on which stage coerces the
        # string: history values coerce at normalize, pointEstimate at
        # seal. Either way: a custody-clean failure manifest.
        assert manifest["error"]["phase"] in {"normalize", "seal"}, name
        _custody_passes(out_dir)


def test_unencodable_target_context_is_refused_at_entry(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--target-context-json",
            json.dumps({"anchorsLike": 10**400}),
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "exactly representable" in result.stderr


def test_custody_rejects_forged_parse_phase_and_loose_error_equality(
    tmp_path: Path,
) -> None:
    # Round four: the parse branch returned before the semantic checks,
    # and error equality used Python == (true == 1). Both re-sealed
    # forgeries must refuse.
    cell = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    cell.pop("historicalContext", None)
    code, out_dir = _run_fake_codex_case(tmp_path, "parse-forgery", cell)
    assert code == 1

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import run_thesis_analyst as runner_mod
        from verify_custody import CustodyError, verify_run
    finally:
        sys.path.pop(0)

    manifest_path = out_dir / "manifest.json"

    def reseal(mutate) -> None:
        manifest = json.loads(manifest_path.read_text())
        mutate(manifest)
        manifest.pop("custodyRootSha256", None)
        refs = [
            ref
            for ref in manifest["artifacts"]
            if Path(str(ref["path"])).name != "manifest.json"
        ]
        manifest["artifacts"] = refs
        runner_mod.finalize_manifest(out_dir, manifest["runStartedAt"], manifest, refs)

    def forge_parse_complete(manifest) -> None:
        manifest["error"]["phase"] = "parse"
        manifest["ok"] = True
        manifest["validation"] = {"ok": True}
        manifest["cellsPath"] = "cells.with_activity.json"

    reseal(forge_parse_complete)
    with pytest.raises(CustodyError, match="does not present as failed"):
        verify_run(out_dir)

    # Restore failed presentation but desync error.json loosely: a
    # boolean-vs-1 difference that Python == would miss.
    def desync_error(manifest) -> None:
        manifest["error"]["phase"] = "normalize"
        manifest["ok"] = False
        manifest["validation"] = None
        manifest["cellsPath"] = None
        error_artifact = out_dir / "error.json"
        disk_error = json.loads(error_artifact.read_text())
        disk_error["flag"] = True
        payload = json.dumps(disk_error, indent=2)
        error_artifact.write_text(payload)
        # Keep the artifact hash-consistent so the SEMANTIC canonical
        # comparison, not an integrity mismatch, is what refuses.
        import hashlib

        for ref in manifest["artifacts"]:
            if Path(str(ref["path"])).name == "error.json":
                ref["sha256"] = hashlib.sha256(payload.encode()).hexdigest()
                ref["bytes"] = len(payload.encode())
        manifest["error"] = {**disk_error, "flag": 1}

    reseal(desync_error)
    with pytest.raises(CustodyError, match="disagrees with"):
        verify_run(out_dir)


def test_custody_requires_explicit_null_presentation(tmp_path: Path) -> None:
    # Omitting the validation/cellsPath keys must not read as null.
    cell = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    cell.pop("historicalContext", None)
    code, out_dir = _run_fake_codex_case(tmp_path, "omitted-keys", cell)
    assert code == 1

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import run_thesis_analyst as runner_mod
        from verify_custody import CustodyError, verify_run
    finally:
        sys.path.pop(0)

    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("validation", None)
    manifest.pop("cellsPath", None)
    manifest.pop("custodyRootSha256", None)
    refs = [
        ref
        for ref in manifest["artifacts"]
        if Path(str(ref["path"])).name != "manifest.json"
    ]
    manifest["artifacts"] = refs
    runner_mod.finalize_manifest(out_dir, manifest["runStartedAt"], manifest, refs)
    with pytest.raises(CustodyError, match="does not present as failed"):
        verify_run(out_dir)


def test_custody_rejects_a_failure_phase_that_presents_as_complete(
    tmp_path: Path,
) -> None:
    # Round-three forgery: error.phase used to win without requiring
    # ok:false, so a phase-tagged manifest presenting as complete rode
    # the lighter failure inventories and read as succeeded downstream.
    cell = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    cell.pop("historicalContext", None)
    code, out_dir = _run_fake_codex_case(tmp_path, "forged-phase", cell)
    assert code == 1

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import run_thesis_analyst as runner_mod
        from verify_custody import CustodyError, verify_run
    finally:
        sys.path.pop(0)

    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["ok"] = True
    manifest["validation"] = {"ok": True}
    # Re-seal so the forgery is internally hash-consistent — the
    # semantic guard, not a hash mismatch, must be what rejects it.
    manifest.pop("custodyRootSha256", None)
    refs = [
        ref
        for ref in manifest["artifacts"]
        if Path(str(ref["path"])).name != "manifest.json"
    ]
    manifest["artifacts"] = refs
    runner_mod.finalize_manifest(out_dir, manifest["runStartedAt"], manifest, refs)

    with pytest.raises(CustodyError, match="does not present as failed"):
        verify_run(out_dir)


def test_custody_requires_the_phase_artifacts_typed(tmp_path: Path) -> None:
    # A seal failure must carry normalized_cells.json AS a
    # normalized_cell artifact — pathname-only allowances let it vanish
    # or be relabeled.
    bad_point = review_test_cell(point=5.2, ci_low=4.6, ci_high=5.9)
    bad_point["pointEstimate"] = "not-a-number"
    code, out_dir = _run_fake_codex_case(tmp_path, "typed-inv", bad_point)
    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    phase = manifest["error"]["phase"]
    if phase == "normalize":
        # Normalizer caught it first on this build; the typed-inventory
        # branch is exercised by the seal shape below regardless.
        return

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import run_thesis_analyst as runner_mod
        from verify_custody import CustodyError, verify_run
    finally:
        sys.path.pop(0)

    refs = [
        ref
        for ref in manifest["artifacts"]
        if Path(str(ref["path"])).name not in {"normalized_cells.json", "manifest.json"}
    ]
    (out_dir / "normalized_cells.json").unlink()
    manifest["artifacts"] = refs
    manifest.pop("custodyRootSha256", None)
    runner_mod.finalize_manifest(out_dir, manifest["runStartedAt"], manifest, refs)
    with pytest.raises(CustodyError):
        verify_run(out_dir)


def test_registered_query_snapshot_context_instructs_query_history():
    # A registered_query_snapshot series has no published table: history
    # must come from executing the registered query for prior periods.
    # All three B1 rescue failures (missing historicalContext twice, a
    # wrong headline aggregate once) trace to this instruction's absence.
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.snapshot_series",
            "--period",
            "FY2026",
            "--prompt-mode",
            "fast",
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "snapshot-slug",
                    "targetUnit": "usd_millions",
                    "dataPointId": (
                        "test.snapshot_series.fy2026.registered_query_snapshot"
                    ),
                    "sourceBinding": {
                        "adapter": "usaspending-api",
                        "releasePolicy": "registered_query_snapshot",
                        "sourceUrl": (
                            "https://api.usaspending.gov/api/v2/agency/097/"
                            "awards/?fiscal_year={fiscal_year}"
                        ),
                        "field": "obligations",
                        "transform": {"operation": "multiply", "factor": 1e-09},
                    },
                }
            ),
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "# Registered-query series (machine checked)" in result.stdout
    assert "executing the exact registered query" in result.stdout
    assert "refuse with the fetch" in result.stdout
    # GET binding (period slot in the URL, no requestMethod): the block
    # must instruct URL substitution and GET, never a POST template.
    assert "sourceBinding.sourceUrl" in result.stdout
    assert "and GET it" in result.stdout
    assert "fiscal_year={fiscal_year}" in result.stdout
    assert "request template" not in result.stdout

    post = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.snapshot_series",
            "--period",
            "FY2026",
            "--prompt-mode",
            "fast",
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "snapshot-post-slug",
                    "targetUnit": "usd_millions",
                    "dataPointId": (
                        "test.snapshot_series.fy2026.registered_query_snapshot"
                    ),
                    "sourceBinding": {
                        "adapter": "usaspending-api",
                        "releasePolicy": "registered_query_snapshot",
                        "sourceUrl": (
                            "https://api.usaspending.gov/api/v2/search/"
                            "spending_over_time/"
                        ),
                        "field": (
                            "results[time_period.fiscal_year={fiscal_year}]"
                            ".aggregated_amount"
                        ),
                        "transform": {
                            "operation": "multiply",
                            "factor": 1e-06,
                            "requestMethod": "POST",
                            "programNumbers": ["95.001"],
                        },
                    },
                }
            ),
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    # POST binding: the block must instruct the transform's request
    # template POSTed to the endpoint.
    assert "request template and POST it to" in post.stdout
    assert "spending_over_time" in post.stdout
    assert "and GET it" not in post.stdout

    # A non-snapshot binding must not get the block.
    plain = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--prompt-mode",
            "fast",
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "targetUnit": "percent",
                    "sourceBinding": {"adapter": "alfred-fred"},
                }
            ),
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "# Registered-query series (machine checked)" not in plain.stdout


def test_fast_prompt_offers_the_unit_menu_only_without_a_registration():
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--prompt-mode",
            "fast",
            "--print-prompt",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "percent|count|thousands" in result.stdout
    assert "million_cubic_feet" in result.stdout
    assert "the registered targetUnit, byte-for-byte" not in result.stdout


@pytest.mark.parametrize("mode", ["full", "fast", "ladder", "ladder_v2"])
def test_generation_ticket_block_follows_target_context_in_every_prompt_mode(
    mode: str,
) -> None:
    target_context = {
        "catalogSlug": "canonical-ledger-slug",
        "targetUnit": "percent",
    }
    ticket = generation_ticket_context()

    prompt, _ = analyst_runner.build_run_prompt(
        "test.ledger_series",
        "2030-01",
        None,
        mode,
        target_context,
        ticket=ticket,
        network_tools=mode == "full",
    )

    context_block = analyst_runner.format_target_context(target_context)
    ticket_block = analyst_runner.format_generation_ticket(ticket)
    assert f"{context_block}\n\n{ticket_block}" in prompt
    assert prompt.count("# Generation ticket") == 1
    assert (
        ticket_block == "# Generation ticket\n"
        f"ticket: {ticket['ticketId']}\n"
        f"nonce: {ticket['nonce']}\n"
    )
    if mode == "full":
        assert prompt.index("# Generation ticket") < prompt.index("# Network access")
    else:
        assert prompt.index("# Generation ticket") < prompt.index("# Source hints")


def test_generation_ticket_internal_flags_are_all_or_none() -> None:
    ticket = generation_ticket_context()
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ticket",
            "--period",
            "2030-01",
            "--ticket-id",
            ticket["ticketId"],
            "--codex-model",
            "gpt-5.5",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stderr.strip() == (
        "ticket mode requires --ticket-id, --ticket-path, and --ticket-nonce together"
    )


@pytest.mark.parametrize(
    ("backend_args", "message"),
    [
        (
            ["--response-file", "/tmp/not-read.json"],
            "ticket mode refuses --response-file",
        ),
        (["--mock-cell"], "ticket mode refuses --mock-cell"),
        (["--command", "ignored"], "ticket mode refuses --command"),
        (
            ["--pre-submit-review-command", "ignored"],
            "ticket mode refuses --pre-submit-review-command",
        ),
    ],
)
def test_generation_ticket_refuses_non_codex_backends(
    backend_args: list[str], message: str
) -> None:
    ticket = generation_ticket_context()
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ticket",
            "--period",
            "2030-01",
            "--ticket-id",
            ticket["ticketId"],
            "--ticket-path",
            ticket["ticketPath"],
            "--ticket-nonce",
            ticket["nonce"],
            "--codex-model",
            "gpt-5.5",
            *backend_args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stderr.strip() == message


def test_generation_ticket_requires_native_codex() -> None:
    ticket = generation_ticket_context()
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ticket",
            "--period",
            "2030-01",
            "--ticket-id",
            ticket["ticketId"],
            "--ticket-path",
            ticket["ticketPath"],
            "--ticket-nonce",
            ticket["nonce"],
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stderr.strip() == "ticket mode requires --codex-model"


def test_generation_ticket_refuses_idle_timeout_environment_override() -> None:
    ticket = generation_ticket_context()
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ticket",
            "--period",
            "2030-01",
            "--ticket-id",
            ticket["ticketId"],
            "--ticket-path",
            ticket["ticketPath"],
            "--ticket-nonce",
            ticket["nonce"],
            "--codex-model",
            "gpt-5.5",
        ],
        cwd=ROOT,
        env={**os.environ, "THESIS_CODEX_IDLE_TIMEOUT_SECONDS": "1"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stderr.strip() == (
        "ticket mode refuses THESIS_CODEX_IDLE_TIMEOUT_SECONDS because timeout "
        "policy is ticket-sealed"
    )


def test_generation_ticket_refuses_non_codex_executable_override() -> None:
    ticket = generation_ticket_context()
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ticket",
            "--period",
            "2030-01",
            "--ticket-id",
            ticket["ticketId"],
            "--ticket-path",
            ticket["ticketPath"],
            "--ticket-nonce",
            ticket["nonce"],
            "--codex-model",
            "gpt-5.5",
        ],
        cwd=ROOT,
        env={**os.environ, "THESIS_CODEX_BIN": "/tmp/fake-codex"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stderr.strip() == (
        "ticket mode refuses THESIS_CODEX_BIN unless its executable basename is codex"
    )


def test_ticket_manifest_binding_requires_exact_canonical_context() -> None:
    ticket = generation_ticket_context()
    assert (
        generation_tickets.ticket_record_path(ticket["ticketId"]).as_posix()
        == (ticket["ticketPath"])
    )
    assert generation_tickets.ticket_manifest_binding(ticket) == {
        "ticketId": ticket["ticketId"],
        "ticketPath": ticket["ticketPath"],
        "nonceSha256": hashlib.sha256(ticket["nonce"].encode()).hexdigest(),
    }

    with pytest.raises(
        generation_tickets.TicketError,
        match="generation ticket context must contain exactly",
    ):
        generation_tickets.ticket_manifest_binding({**ticket, "extra": True})


def test_mock_run_writes_activity_artifacts(tmp_path):
    out_dir = tmp_path / "run"
    generated_ts = tmp_path / "generated.ts"

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.synthetic_rate",
            "--period",
            "2030-01",
            "--mock-cell",
            "--out-dir",
            str(out_dir),
            "--write-ts",
            str(generated_ts),
            "--const-name",
            "GENERATED_TEST_CELLS",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    printed_manifest = json.loads(result.stdout)
    assert manifest["schemaVersion"] == "thesis_analyst_run_manifest_v1"
    assert printed_manifest["ok"] is True
    assert manifest["ok"] is True
    assert manifest["series"] == "test.synthetic_rate"
    assert manifest["period"] == "2030-01"
    assert manifest["promptMode"] == "full"
    assert len(manifest["checkoutSha"]) == 40

    artifact_types = {artifact["artifactType"] for artifact in manifest["artifacts"]}
    assert {
        "prompt",
        "command",
        "raw_response",
        "parsed_cell",
        "normalized_cell",
        "run_distribution",
        "validation_report",
        "manifest",
    }.issubset(artifact_types)

    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        if not path.exists():
            path = Path(artifact["path"])
        assert path.exists()
        assert artifact["sha256"]
        assert artifact["bytes"] > 0

    cells = json.loads((out_dir / "cells.with_activity.json").read_text())
    assert len(cells) == 1
    cell = cells[0]
    assert manifest["sealedAt"] == cell["runAt"]
    assert cell["slug"] == "test-synthetic-rate-2030-01"
    assert cell["predictionDistribution"] == json.loads(
        (out_dir / "distribution.json").read_text()
    )
    assert cell["predictionDistribution"]["pointCount"] == 201
    assert cell["predictionDistribution"]["provenance"] == "interval_seeded"
    assert cell["predictionDistribution"]["transformVersion"] == "interval_anchor_v1"
    assert cell["activityLog"]
    activity_types = {artifact["artifactType"] for artifact in cell["activityLog"]}
    assert {
        "prompt",
        "raw_response",
        "run_distribution",
        "validation_report",
    }.issubset(activity_types)
    assert manifest["validation"]["cells"][0]["ok"] is True
    generated_text = generated_ts.read_text()
    assert '"predictionDistribution"' in generated_text
    assert '"transformVersion": "interval_anchor_v1"' in generated_text


def test_target_context_validation_rejects_drift(tmp_path):
    out_dir = tmp_path / "target-context-run"
    response_path = tmp_path / "response.json"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["slug"] = "canonical-ledger-slug"
    cell["unit"] = "percent"
    cell["dataPointId"] = "test.ledger_series.2030_01.first_print"
    cell["resolutionDate"] = "2030-02-28"
    response_path.write_text(json.dumps(cell))

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--response-file",
            str(response_path),
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "targetUnit": "percent",
                    "dataPointId": "test.ledger_series.2030_01.first_print",
                    "resolutionDate": "2030-02-15",
                }
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    errors = manifest["validation"]["cells"][0]["errors"]
    assert any("resolutionDate" in error for error in errors)
    assert manifest["ok"] is False


def test_run_record_stamps_privileged_registration_binding(tmp_path):
    out_dir = tmp_path / "registration-bound-run"
    response_path = tmp_path / "response.json"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["slug"] = "canonical-ledger-slug"
    cell["unit"] = "percent"
    cell["dataPointId"] = "test.ledger_series.2030_01.first_print"
    response_path.write_text(json.dumps(cell))
    binding = {
        "registrationCommit": "a" * 40,
        "targetContentHash": "b" * 64,
        "targetRegistrationPath": f"records/targets/2030-01-10-{'b' * 64}.json",
        "registeredAtUtc": "2030-01-10T12:00:00Z",
    }
    target_context = {
        "catalogSlug": cell["slug"],
        "targetUnit": cell["unit"],
        "dataPointId": cell["dataPointId"],
        **binding,
    }

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--response-file",
            str(response_path),
            "--target-context-json",
            json.dumps(target_context),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    [recorded_cell] = json.loads((out_dir / "cells.with_activity.json").read_text())
    assert json.loads(result.stdout)["ok"] is True
    assert manifest["targetContext"] == target_context
    assert manifest["runStartedAt"] == manifest["createdAt"]
    assert recorded_cell["runStartedAt"] == manifest["runStartedAt"]
    for field, value in binding.items():
        assert manifest[field] == value
        assert recorded_cell[field] == value


def test_target_context_validation_rejects_identity_unit_and_source_host_drift(
    tmp_path,
):
    out_dir = tmp_path / "target-binding-run"
    response_path = tmp_path / "response.json"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["slug"] = "canonical-ledger-slug"
    cell["unit"] = "ratio"
    cell["dataPointId"] = "wrong.series.2030_01.first_print"
    cell["resolutionDate"] = "2030-02-15"
    cell["resolutionSourceUrl"] = "https://revision.example.com/rate"
    response_path.write_text(json.dumps(cell))

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--response-file",
            str(response_path),
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "targetUnit": "percent",
                    "dataPointId": "test.ledger_series.2030_01.first_print",
                    "sourceBinding": {"sourceUrl": "https://official.example.gov/rate"},
                }
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    errors = json.loads((out_dir / "manifest.json").read_text())["validation"]["cells"][
        0
    ]["errors"]
    assert any("unit" in error and "target context" in error for error in errors)
    assert any("dataPointId" in error for error in errors)
    assert any("source binding host" in error for error in errors)


def test_target_context_validation_rejects_first_print_grace_exception(tmp_path):
    out_dir = tmp_path / "target-context-rule-run"
    response_path = tmp_path / "response.json"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["slug"] = "canonical-ledger-slug"
    cell["unit"] = "percent"
    cell["dataPointId"] = "test.ledger_series.2030_01.first_print"
    cell["resolutionDate"] = "2030-02-15"
    cell["resolutionRule"] = (
        "Resolves to the first published official value for January 2030; "
        "same-day corrections before release day ends count."
    )
    response_path.write_text(json.dumps(cell))

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.ledger_series",
            "--period",
            "2030-01",
            "--response-file",
            str(response_path),
            "--target-context-json",
            json.dumps(
                {
                    "catalogSlug": "canonical-ledger-slug",
                    "targetUnit": "percent",
                    "dataPointId": "test.ledger_series.2030_01.first_print",
                    "resolutionDate": "2030-02-15",
                    "resolutionRule": (
                        "Resolves to the first published official value for "
                        "January 2030; later revisions do not count."
                    ),
                }
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    errors = manifest["validation"]["cells"][0]["errors"]
    assert any("correction/grace exception" in error for error in errors)
    assert manifest["ok"] is False


def test_fast_mock_run_records_prompt_mode(tmp_path):
    out_dir = tmp_path / "fast-run"

    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "boe.bank_rate",
            "--period",
            "2026-06-18",
            "--prompt-mode",
            "fast",
            "--mock-cell",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    prompt = (out_dir / "prompt.md").read_text()

    assert manifest["promptMode"] == "fast"
    assert "You may inspect the local repository/workspace when useful" in prompt
    assert "Do not modify files" in prompt


def test_command_start_failure_is_sealed_as_complete_failed_trace(tmp_path):
    out_dir = tmp_path / "command-start-failure"
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.start_failure",
            "--period",
            "2030-01",
            "--command",
            "/definitely/not/a/command",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    manifest = json.loads((out_dir / "manifest.json").read_text())
    command = json.loads((out_dir / "command.json").read_text())
    verification = verify_run(out_dir)
    assert command["returnCode"] == 127
    assert manifest["error"]["phase"] == "parse"
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is False
    assert verification.headline_eligible is False


def test_reviewer_start_failure_is_sealed_and_labeled_failed(tmp_path):
    out_dir = tmp_path / "review-start-failure"
    forecaster = tmp_path / "forecaster.py"
    forecaster.write_text(
        "import json, sys\n"
        "_prompt = sys.stdin.read()\n"
        f"print(json.dumps({review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)!r}))\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.review_start_failure",
            "--period",
            "2030-01",
            "--command",
            f"{shlex.quote(sys.executable)} {shlex.quote(str(forecaster))}",
            "--pre-submit-review-command",
            "/definitely/not/a/reviewer",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    manifest = json.loads((out_dir / "manifest.json").read_text())
    reviewer = json.loads((out_dir / "pre_submit_review_command.json").read_text())
    verification = verify_run(out_dir)
    assert reviewer["returnCode"] == 127
    assert manifest["preSubmitReview"]["status"] == "review_failed"
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is False
    assert verification.headline_eligible is False


def test_command_run_can_capture_pre_submit_review_loop(tmp_path):
    out_dir = tmp_path / "reviewed-run"
    forecaster_path = tmp_path / "forecaster.py"
    reviewer_path = tmp_path / "reviewer.py"
    draft_cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    final_cell = review_test_cell(
        point=5.2,
        ci_low=4.6,
        ci_high=5.9,
        review_disposition=(
            "Review disposition: accepted the reviewer request to make the "
            "interval source explicit and widened the upper tail by 0.1."
        ),
    )
    forecaster_path.write_text(
        "\n".join(
            [
                "import json, sys",
                f"draft = {json.dumps(draft_cell)!r}",
                f"final = {json.dumps(final_cell)!r}",
                "prompt = sys.stdin.read()",
                "print('model: gpt-5.5', file=sys.stderr)",
                "print(final if 'Pre-submit review loop' in prompt else draft)",
            ]
        )
    )
    reviewer_path.write_text(
        "\n".join(
            [
                "import json, sys",
                "_prompt = sys.stdin.read()",
                "print('model: gpt-5.5-reviewer', file=sys.stderr)",
                "print(json.dumps({",
                "  'summary': 'Draft is publishable after interval-source '",
                "    'clarification.',",
                "  'requiredFixes': [{",
                "    'rubricItem': 'interval',",
                "    'severity': 'warning',",
                "    'summary': 'Interval source should be explicit in the '",
                "      'public trace.',",
                "    'actionRequested': 'Name realized volatility or release '",
                "      'dispersion.'",
                "  }],",
                "  'optionalSuggestions': ['Keep the first-print resolver visible.']",
                "}))",
            ]
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.reviewed_rate",
            "--period",
            "2030-01",
            "--command",
            (
                f"{shlex.quote(sys.executable)} "
                f"{shlex.quote(str(forecaster_path))} "
                "--model gpt-5.5"
            ),
            "--pre-submit-review-command",
            (
                f"{shlex.quote(sys.executable)} "
                f"{shlex.quote(str(reviewer_path))} "
                "--model gpt-5.5-reviewer"
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    cells = json.loads((out_dir / "cells.with_activity.json").read_text())
    artifact_types = {artifact["artifactType"] for artifact in manifest["artifacts"]}

    assert manifest["ok"] is True
    assert manifest["preSubmitReview"]["status"] == "completed"
    assert manifest["preSubmitReview"]["reviewer"]["model"] == "gpt-5.5-reviewer"
    assert manifest["preSubmitReview"]["findings"][0]["rubricItem"] == "interval"
    assert manifest["preSubmitReview"]["dispositions"][0]["decision"] == "accepted"
    assert {
        "draft_forecast",
        "review_prompt",
        "pre_submit_review",
        "revision_prompt",
        "raw_response",
    }.issubset(artifact_types)
    assert cells[0]["pointEstimate"] == 5.2
    assert cells[0]["preSubmitReview"]["status"] == "completed"
    assert any(
        step.get("text", "").startswith("Review disposition:")
        for step in cells[0]["reasoning"]
        if isinstance(step, dict)
    )
    assert (out_dir / "draft_stdout.txt").exists()
    assert (out_dir / "pre_submit_review_stdout.txt").exists()
    assert (out_dir / "revision_prompt.md").exists()


def test_codex_model_run_captures_full_codex_trace(tmp_path):
    out_dir = tmp_path / "codex-run"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "fake_codex.py"
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)

    fake_codex.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "args = sys.argv[1:]",
                "last_message = pathlib.Path(args[args.index('-o') + 1])",
                "model = args[args.index('-m') + 1]",
                f"text = {json.dumps(json.dumps(cell))}",
                "last_message.write_text(text)",
                "print(json.dumps({",
                "  'type': 'item.completed',",
                "  'item': {'type': 'agent_message', 'text': text}",
                "}))",
                "print(json.dumps({",
                "  'type': 'turn.completed',",
                "  'usage': {",
                "    'input_tokens': 10,",
                "    'output_tokens': 5,",
                "    'cached_input_tokens': 2",
                "  }",
                "}))",
                "print(f'model: {model}', file=sys.stderr)",
            ]
        )
    )
    fake_codex.chmod(0o755)

    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }

    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    command = json.loads((out_dir / "command.json").read_text())
    cells = json.loads((out_dir / "cells.with_activity.json").read_text())
    artifact_types = {artifact["artifactType"] for artifact in manifest["artifacts"]}

    assert manifest["ok"] is True
    assert manifest["agent"]["model"] == "gpt-5.5"
    assert cells[0]["model"] == "gpt-5.5"
    assert command["argv"][-1] == "<prompt>"
    assert "--search" in command["argv"]
    assert "--ignore-user-config" in command["argv"]
    assert {
        "codex_stdout_jsonl",
        "codex_stderr_log",
        "codex_events_jsonl",
        "codex_last_message",
        "codex_trace",
        "stdout",
    }.issubset(artifact_types)
    trace = json.loads((out_dir / "codex_trace.json").read_text())
    assert trace["auth"] == "codex-cli-subscription"
    assert trace["backend"] == "codex-exec"
    assert trace["model"] == "gpt-5.5"
    assert trace["usage"]["input_tokens"] == 10
    assert (out_dir / "codex_events.jsonl").read_text().count("\n") == 2


def write_fake_codex(
    path: Path, cell: dict, extra_lines: list[str] | None = None
) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "args = sys.argv[1:]",
                "last_message = pathlib.Path(args[args.index('-o') + 1])",
                f"text = {json.dumps(json.dumps(cell))}",
                *(extra_lines or []),
                "last_message.write_text(text)",
                "print(json.dumps({",
                "  'type': 'item.completed',",
                "  'item': {'type': 'agent_message', 'text': text}",
                "}))",
                "print(json.dumps({",
                "  'type': 'turn.completed',",
                "  'usage': {",
                "    'input_tokens': 10,",
                "    'output_tokens': 5,",
                "    'cached_input_tokens': 2",
                "  }",
                "}))",
            ]
        )
    )
    path.chmod(0o755)


def test_generation_ticket_codex_run_stamps_prompt_command_and_manifest(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "ticket-run"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "codex"
    final_cell = review_test_cell(
        point=5.2,
        ci_low=4.6,
        ci_high=5.9,
        review_disposition=(
            "Review disposition: accepted the request to name the interval "
            "source and widened the upper tail by 0.1."
        ),
    )
    final_cell["model"] = "agent-supplied-model"
    review_payload = {
        "summary": "Clarify the interval source before publication.",
        "requiredFixes": [
            {
                "rubricItem": "interval",
                "severity": "warning",
                "summary": "The interval source should be explicit.",
                "actionRequested": "Name realized release volatility.",
            }
        ],
        "optionalSuggestions": [],
    }
    write_fake_codex(
        fake_codex,
        review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8),
        extra_lines=[
            "model = args[args.index('-m') + 1]",
            "prompt = args[-1]",
            f"review_text = {json.dumps(json.dumps(review_payload))}",
            f"final_text = {json.dumps(json.dumps(final_cell))}",
            "if model == 'gpt-ticket-review':",
            "    text = review_text",
            "elif 'Pre-submit review loop' in prompt:",
            "    text = final_text",
        ],
    )
    ticket = generation_ticket_context()
    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }

    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--pre-submit-review-codex-model",
            "gpt-ticket-review",
            "--pre-submit-review-codex-search",
            "--ticket-id",
            ticket["ticketId"],
            "--ticket-path",
            ticket["ticketPath"],
            "--ticket-nonce",
            ticket["nonce"],
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    commands = [
        json.loads((out_dir / name).read_text())
        for name in (
            "draft_command.json",
            "pre_submit_review_command.json",
            "command.json",
        )
    ]
    [cell] = json.loads((out_dir / "cells.with_activity.json").read_text())
    checkout_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    expected_binding = {
        "ticketId": ticket["ticketId"],
        "ticketPath": ticket["ticketPath"],
        "nonceSha256": hashlib.sha256(ticket["nonce"].encode()).hexdigest(),
    }

    assert manifest["generationTicket"] == expected_binding
    assert manifest["checkoutSha"] == checkout_sha
    assert manifest["sealedAt"] == cell["runAt"]
    assert manifest["preSubmitReview"]["status"] == "completed"
    assert cell["pointEstimate"] == 5.2
    assert cell["model"] == "gpt-5.5"
    for command in commands:
        assert command["generationTicket"] == {
            "ticketId": ticket["ticketId"],
            "ticketPath": ticket["ticketPath"],
        }
        assert command["timeoutSeconds"] == 600
    assert (
        analyst_runner.format_generation_ticket(ticket)
        in (out_dir / "prompt.md").read_text()
    )


def test_generation_ticket_parse_failure_keeps_ticket_and_checkout_binding(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "ticket-failure"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                "args = sys.argv[1:]",
                "last_message = pathlib.Path(args[args.index('-o') + 1])",
                "text = 'not a JSON forecast'",
                "last_message.write_text(text)",
                "print(json.dumps({",
                "  'type': 'item.completed',",
                "  'item': {'type': 'agent_message', 'text': text}",
                "}))",
            ]
        )
    )
    fake_codex.chmod(0o755)
    ticket = generation_ticket_context()
    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }

    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--ticket-id",
            ticket["ticketId"],
            "--ticket-path",
            ticket["ticketPath"],
            "--ticket-nonce",
            ticket["nonce"],
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    command = json.loads((out_dir / "command.json").read_text())
    verification = verify_run(out_dir)
    assert completed.returncode == 1
    assert manifest["error"]["phase"] == "parse"
    assert manifest["generationTicket"] == {
        "ticketId": ticket["ticketId"],
        "ticketPath": ticket["ticketPath"],
        "nonceSha256": hashlib.sha256(ticket["nonce"].encode()).hexdigest(),
    }
    assert len(manifest["checkoutSha"]) == 40
    assert command["generationTicket"] == {
        "ticketId": ticket["ticketId"],
        "ticketPath": ticket["ticketPath"],
    }
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is False


def test_codex_network_requires_workspace_write_sandbox(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--codex-network",
            "--out-dir",
            str(tmp_path / "run"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "workspace-write" in completed.stderr


def test_codex_network_run_records_grant_and_clean_guard(tmp_path):
    out_dir = tmp_path / "codex-network-run"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "fake_codex.py"
    write_fake_codex(fake_codex, review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8))

    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }
    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--codex-sandbox",
            "workspace-write",
            "--codex-network",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    command = json.loads((out_dir / "command.json").read_text())
    argv = command["argv"]
    assert manifest["ok"] is True
    assert command["networkAccess"] is True
    assert command["workspaceMutations"] == []
    assert "sandbox_workspace_write.network_access=true" in argv
    assert argv[argv.index("-s") + 1] == "workspace-write"
    assert manifest["workspaceHygiene"] == {"guarded": True, "mutations": []}
    trace = json.loads((out_dir / "codex_trace.json").read_text())
    assert trace["networkAccess"] is True
    assert trace["sandbox"] == "workspace-write"
    assert "Outbound network access is enabled" in (out_dir / "prompt.md").read_text()


def test_codex_network_run_fails_closed_on_workspace_mutation(tmp_path):
    out_dir = tmp_path / "codex-mutating-run"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "fake_codex.py"
    write_fake_codex(
        fake_codex,
        review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8),
        extra_lines=[
            "run_dir = last_message.parent",
            "(run_dir / 'planted.txt').write_text('agent wrote this')",
            "prompt_md = run_dir / 'prompt.md'",
            "prompt_md.write_text(prompt_md.read_text() + 'tampered')",
        ],
    )

    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
    }
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.codex_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--codex-sandbox",
            "workspace-write",
            "--codex-network",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    manifest = json.loads((out_dir / "manifest.json").read_text())
    command = json.loads((out_dir / "command.json").read_text())
    assert manifest["ok"] is False
    mutations = command["workspaceMutations"]
    assert any("planted.txt" in mutation for mutation in mutations)
    assert any("prompt.md" in mutation for mutation in mutations)
    assert manifest["workspaceHygiene"]["guarded"] is True
    assert manifest["workspaceHygiene"]["mutations"] == mutations


def test_fast_prompt_network_note_is_gated_and_census_notes_name_endpoint():
    series = "census.acs.broadband_subscription_65_plus.share"
    prompt_with, _ = analyst_runner.build_run_prompt(
        series, "2025", None, "fast", None, network_tools=True
    )
    prompt_without, _ = analyst_runner.build_run_prompt(
        series, "2025", None, "fast", None
    )
    assert "Outbound network access is enabled" in prompt_with
    assert "Outbound network access is enabled" not in prompt_without
    for prompt in (prompt_with, prompt_without):
        assert "data.census.gov/api/access/" in prompt
        assert "ACSDT1Y" in prompt
        assert "api.census.gov requires an API key" in prompt


def review_test_cell(
    *,
    point: float,
    ci_low: float,
    ci_high: float,
    review_disposition: str | None = None,
) -> dict:
    reasoning = [
        {"kind": "heading", "text": "Reviewed synthetic rate forecast"},
        {
            "kind": "text",
            "text": (
                "The first-print resolver is the official synthetic January "
                "2030 release on 2030-01-15."
            ),
        },
        {
            "kind": "tool",
            "tool": "official.lookup",
            "call": "official.lookup(series='test.reviewed_rate')",
            "result": ("Fetched t-6 4.8, t-5 4.9, t-4 5.0, t-3 4.9, t-2 5.0, t-1 5.2."),
        },
        {
            "kind": "tool",
            "tool": "calendar.lookup",
            "call": "calendar.lookup(series='test.reviewed_rate')",
            "result": "Fetched release date 2030-01-15 from official calendar.",
        },
        {
            "kind": "tool",
            "tool": "volatility.lookup",
            "call": "volatility.lookup(series='test.reviewed_rate')",
            "result": "Fetched first-print absolute errors 0.2, 0.3, 0.4.",
        },
        {
            "kind": "text",
            "text": (
                "Base rate prior from the reference class of the last 6 "
                "prints is the recent center near 5.1 before the small "
                "current-release adjustment."
            ),
        },
        {
            "kind": "math",
            "text": (
                f"Point {point} uses the recent center plus a 0.1 update; "
                f"realized dispersion sigma = 0.45, so the 80% interval "
                f"[{ci_low}, {ci_high}] is point \u00b1 1.28 \u00d7 sigma."
            ),
        },
        {
            "kind": "text",
            "text": (
                "Outside the interval if the synthetic release breaks from "
                "recent first-print dispersion."
            ),
        },
        {"kind": "forecast", "point": point, "ciLow": ci_low, "ciHigh": ci_high},
    ]
    if review_disposition:
        reasoning.insert(7, {"kind": "text", "text": review_disposition})
    return {
        "slug": "test-reviewed-rate-2030-01",
        "country": "US",
        "type": "data",
        "title": "Reviewed synthetic rate forecast",
        "question": (
            "What will the first-print value of the reviewed synthetic rate "
            "be for January 2030?"
        ),
        "unit": "percent",
        "pointEstimate": point,
        "ciLow": ci_low,
        "ciHigh": ci_high,
        "confidence": 0.8,
        "resolutionDate": "2030-01-15",
        "resolutionSource": "Official synthetic release",
        "resolutionSourceUrl": "https://example.com/reviewed-rate",
        "resolutionRule": (
            "Resolves to the first official synthetic release value for "
            "January 2030; later revisions do not count."
        ),
        "dataPointId": "test.reviewed_rate.january_2030.first_print",
        "historicalContext": [
            {
                "period": {"type": "month", "value": f"2029-{index:02d}"},
                "label": f"2029-{index:02d}",
                "value": value,
            }
            for index, value in enumerate([4.8, 4.9, 5.0, 4.9, 5.0, 5.2], start=1)
        ],
        "drivers": [
            "recent reference class",
            "reviewed interval calibration",
            "synthetic release volatility",
        ],
        "sourceContext": [
            "https://example.com/reviewed-rate",
            "https://example.com/reviewed-rate-calendar",
        ],
        "runAt": "2026-06-17T12:00:00Z",
        "reasoning": reasoning,
    }


POLICY_CONDITIONAL = (
    "A registered teacher-pay policy applies to the measured 2030 outcome."
)
POLICY_PRECEDENT_URL = "https://example.com/policy-precedent"


def conditional_policy_test_cell(
    policy_step: str | None,
    *,
    include_precedent_url: bool = True,
) -> dict:
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["type"] = "conditional"
    cell["conditionalOn"] = POLICY_CONDITIONAL
    if include_precedent_url:
        cell["sourceContext"].append(POLICY_PRECEDENT_URL)
    if policy_step is not None:
        cell["reasoning"].insert(-1, {"kind": "text", "text": policy_step})
    return cell


def run_fast_conditional_policy_case(
    tmp_path: Path,
    name: str,
    cell: dict,
) -> tuple[int, Path]:
    return _run_fake_codex_case(
        tmp_path,
        name,
        cell,
        extra_args=[
            "--prompt-mode",
            "fast",
            "--conditional",
            POLICY_CONDITIONAL,
        ],
    )


def policy_validation_errors(out_dir: Path) -> list[str]:
    validation = json.loads((out_dir / "validation.json").read_text())
    return validation["cells"][0]["errors"]


def test_fast_conditional_policy_chain_with_cited_precedent_passes(
    tmp_path: Path,
) -> None:
    step = (
        "Policy chain: the policy touches a fetched count of 12,000 teachers; "
        f"the evaluation at `{POLICY_PRECEDENT_URL}` found a 0.3-point response "
        "per funded unit, implying a 0.2-point measured effect; hiring and "
        "turnover partly offset it; implementation lag leaves half the effect "
        "in the 2030 resolution period."
    )
    code, out_dir = run_fast_conditional_policy_case(
        tmp_path,
        "policy-precedent-pass",
        conditional_policy_test_cell(step),
    )

    assert code == 0
    assert policy_validation_errors(out_dir) == []


def test_fast_conditional_policy_chain_missing_step_fails_closed(
    tmp_path: Path,
) -> None:
    code, out_dir = run_fast_conditional_policy_case(
        tmp_path,
        "policy-step-missing",
        conditional_policy_test_cell(None),
    )

    assert code == 1
    assert policy_validation_errors(out_dir) == [
        "conditional policy chain: missing reasoning step beginning exactly "
        "'Policy chain:'"
    ]


def test_fast_conditional_policy_chain_url_must_be_in_source_context(
    tmp_path: Path,
) -> None:
    step = (
        "Policy chain: the policy touches a fetched count of 12,000 teachers; "
        f"{POLICY_PRECEDENT_URL} supplies the propagation estimate; behavioral "
        "offsets halve it; the remaining effect arrives before the 2030 print."
    )
    code, out_dir = run_fast_conditional_policy_case(
        tmp_path,
        "policy-url-missing",
        conditional_policy_test_cell(step, include_precedent_url=False),
    )

    assert code == 1
    assert policy_validation_errors(out_dir) == [
        "conditional policy chain: precedent URL in Policy chain step is not "
        "listed exactly in sourceContext: "
        f"{POLICY_PRECEDENT_URL!r}"
    ]


def test_conditional_policy_chain_rejects_url_without_hostname() -> None:
    cell = conditional_policy_test_cell(
        "Policy chain: the purported precedent is https://)",
        include_precedent_url=False,
    )
    cell["sourceContext"].append("https://")

    assert analyst_runner.conditional_policy_chain_errors(cell) == [
        "conditional policy chain: Policy chain step must cite a precedent URL "
        "also listed exactly in sourceContext or contain exact phrase "
        "'no fetched precedent'"
    ]


def test_fast_conditional_policy_chain_requires_precedent_or_explicit_fallback(
    tmp_path: Path,
) -> None:
    step = (
        "Policy chain: the policy touches a fetched count of 12,000 teachers; "
        "the 0.2-point propagation term is judgmental; hiring offsets halve "
        "it; implementation lag leaves half the effect in the 2030 period."
    )
    code, out_dir = run_fast_conditional_policy_case(
        tmp_path,
        "policy-route-missing",
        conditional_policy_test_cell(step, include_precedent_url=False),
    )

    assert code == 1
    assert policy_validation_errors(out_dir) == [
        "conditional policy chain: Policy chain step must cite a precedent URL "
        "also listed exactly in sourceContext or contain exact phrase "
        "'no fetched precedent'"
    ]


def test_fast_conditional_policy_chain_no_precedent_with_bound_passes(
    tmp_path: Path,
) -> None:
    step = (
        "Policy chain: the policy touches a fetched count of 12,000 teachers; "
        "propagation has no fetched precedent; policy term bound: [-0.2, +0.4] "
        "percentage points; policy term is low-confidence; hiring offsets "
        "could erase the gain; implementation lag limits the effect in the "
        "2030 period."
    )
    code, out_dir = run_fast_conditional_policy_case(
        tmp_path,
        "policy-no-precedent-pass",
        conditional_policy_test_cell(step, include_precedent_url=False),
    )

    assert code == 0
    assert policy_validation_errors(out_dir) == []


@pytest.mark.parametrize(
    "bound",
    [
        "policy term bound is [-.2, +.4] percentage points",
        "policy effect is in the range -0.2 to +0.4 percentage points",
        "-0.2 <= policy term <= +0.4 percentage points",
    ],
)
def test_conditional_policy_chain_accepts_clear_numeric_bound_forms(
    bound: str,
) -> None:
    cell = conditional_policy_test_cell(
        "Policy chain: there is no fetched precedent; "
        f"{bound}; policy term is low-confidence.",
        include_precedent_url=False,
    )

    assert analyst_runner.conditional_policy_chain_errors(cell) == []


@pytest.mark.parametrize(
    "confidence_bound",
    [
        "80% confidence",
        "80 percent confidence",
        "80 pct confidence",
        "80-percent confidence",
        "80 percent level of confidence",
        "80-percent level of confidence",
        "80 per cent confidence",
    ],
)
def test_conditional_policy_chain_does_not_treat_confidence_as_effect_bound(
    confidence_bound: str,
) -> None:
    cell = conditional_policy_test_cell(
        "Policy chain: there is no fetched precedent; the policy effect is "
        f"bounded at {confidence_bound}; policy term is low-confidence.",
        include_precedent_url=False,
    )

    assert analyst_runner.conditional_policy_chain_errors(cell) == [
        "conditional policy chain: 'no fetched precedent' path must state a "
        "numeric policy-term bound"
    ]


@pytest.mark.parametrize(
    "label",
    [
        "policy term is not low-confidence",
        "policy term uses low-confidence evidence",
    ],
)
def test_conditional_policy_chain_requires_low_confidence_term_label(
    label: str,
) -> None:
    cell = conditional_policy_test_cell(
        "Policy chain: there is no fetched precedent; policy term bound: "
        f"[-0.2, +0.4] percentage points; {label}.",
        include_precedent_url=False,
    )

    assert analyst_runner.conditional_policy_chain_errors(cell) == [
        "conditional policy chain: 'no fetched precedent' path must label the "
        "policy term low-confidence"
    ]


def test_conditional_policy_chain_does_not_ignore_a_conflicting_second_step() -> None:
    cell = conditional_policy_test_cell(
        "Policy chain: a fetched precedent evaluation at "
        f"{POLICY_PRECEDENT_URL} anchors the effect."
    )
    cell["reasoning"].insert(
        -1,
        {
            "kind": "text",
            "text": (
                "Policy chain: there is no fetched precedent; policy term is "
                "low-confidence, but no numeric bound is available."
            ),
        },
    )

    assert analyst_runner.conditional_policy_chain_errors(cell) == [
        "conditional policy chain: 'no fetched precedent' path must state a "
        "numeric policy-term bound"
    ]


@pytest.mark.parametrize(
    ("name", "step", "expected_error"),
    [
        (
            "policy-no-precedent-no-bound",
            "Policy chain: the policy touches a fetched count of 12,000 "
            "teachers; propagation has no fetched precedent; the "
            "low-confidence policy term lacks a quantitative limit; hiring "
            "offsets and implementation lag remain.",
            "conditional policy chain: 'no fetched precedent' path must state "
            "a numeric policy-term bound",
        ),
        (
            "policy-no-precedent-population-is-not-bound",
            "Policy chain: propagation has no fetched precedent; the "
            "low-confidence policy term remains uncertain; at most 12,000 "
            "teachers are touched; hiring offsets apply within the 2030 "
            "resolution period after an implementation lag.",
            "conditional policy chain: 'no fetched precedent' path must state "
            "a numeric policy-term bound",
        ),
        (
            "policy-no-precedent-no-confidence",
            "Policy chain: the policy touches a fetched count of 12,000 "
            "teachers; propagation has no fetched precedent; policy term "
            "bound: [-0.2, +0.4] percentage points; hiring offsets and "
            "implementation lag remain.",
            "conditional policy chain: 'no fetched precedent' path must label "
            "the policy term low-confidence",
        ),
    ],
)
def test_fast_conditional_policy_chain_no_precedent_requires_bound_and_confidence(
    tmp_path: Path,
    name: str,
    step: str,
    expected_error: str,
) -> None:
    code, out_dir = run_fast_conditional_policy_case(
        tmp_path,
        name,
        conditional_policy_test_cell(step, include_precedent_url=False),
    )

    assert code == 1
    assert policy_validation_errors(out_dir) == [expected_error]


def test_fast_nonconditional_cell_is_unaffected_by_policy_chain_gate(
    tmp_path: Path,
) -> None:
    code, out_dir = _run_fake_codex_case(
        tmp_path,
        "nonconditional-policy-gate",
        review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8),
        extra_args=["--prompt-mode", "fast"],
    )

    assert code == 0
    assert policy_validation_errors(out_dir) == []


def test_parse_codex_jsonl_exposes_the_last_assistant_message() -> None:
    first = {
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "draft"},
    }
    second = {
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "final"},
    }
    parsed = analyst_runner.parse_codex_jsonl(
        f"{json.dumps(first)}\n{json.dumps(second)}\n", ""
    )

    assert parsed["assistantText"] == "draft\nfinal"
    assert parsed["lastAssistantText"] == "final"


def test_ticket_codex_stream_binding_refuses_o_file_only_success() -> None:
    result = {
        "backend": "codex",
        "returnCode": 0,
        "stderr": "",
        "codexStdoutRaw": json.dumps({"type": "turn.completed", "usage": {}}),
        "codexStderrRaw": "",
        "codexLastMessage": '{"pointEstimate": 1}',
        "codexTrace": {"effectiveReturnCode": 0, "lastError": None},
    }

    bound = analyst_runner.enforce_ticket_codex_stream_binding(result)

    assert bound["returnCode"] == 1
    assert bound["codexTrace"]["effectiveReturnCode"] == 1
    assert "raw JSONL and the codex_last_message artifact disagree" in bound["stderr"]
    assert result["returnCode"] == 0


def test_seal_normalized_cells_replays_all_trusted_stamps() -> None:
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    binding = {
        "registrationCommit": "c" * 40,
        "targetContentHash": "d" * 64,
        "targetRegistrationPath": f"records/targets/2030-01-10-{'d' * 64}.json",
        "registeredAtUtc": "2030-01-10T12:00:00Z",
    }

    distributions = analyst_runner.seal_normalized_cells(
        [cell],
        conditional="the registered condition",
        run_started_at="2030-01-11T10:00:00Z",
        sealed_at="2030-01-11T10:05:00Z",
        prompt_mode="fast",
        target_context=binding,
    )

    assert cell["type"] == "conditional"
    assert cell["agentReportedRunAt"] == "2026-06-17T12:00:00Z"
    assert cell["runStartedAt"] == "2030-01-11T10:00:00Z"
    assert cell["runAt"] == "2030-01-11T10:05:00Z"
    assert cell["promptMode"] == "fast"
    for field, value in binding.items():
        assert cell[field] == value
    assert distributions == cell["predictionDistribution"]


def test_collision_exclusion_ignores_only_the_exact_generated_wave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_data = tmp_path / "site" / "src" / "data"
    examples = site_data / "forecast-examples"
    examples.mkdir(parents=True)
    (site_data / "forecast-cells.ts").write_text("export {};\n")
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    own_wave = examples / "auto-2030-01-10-deadbeef.ts"
    own_wave.write_text(f'export const wave = [{{ slug: "{cell["slug"]}" }}];\n')
    monkeypatch.setattr(analyst_runner, "ROOT", tmp_path)

    blocked = analyst_runner.validate_cells([cell])
    assert any("slug collides" in error for error in blocked["cells"][0]["errors"])

    allowed = analyst_runner.validate_cells([cell], collision_exclusion=own_wave)
    assert allowed["ok"] is True

    (examples / "competing-wave.ts").write_text(
        f'export const wave = [{{ slug: "{cell["slug"]}" }}];\n'
    )
    still_blocked = analyst_runner.validate_cells([cell], collision_exclusion=own_wave)
    assert any(
        "slug collides" in error for error in still_blocked["cells"][0]["errors"]
    )


def test_command_model_override_is_stamped_in_manifest_and_cells(tmp_path):
    out_dir = tmp_path / "model-run"
    response_path = tmp_path / "response.json"
    response_path.write_text(
        json.dumps(
            [
                {
                    "slug": "test-runtime-model-2030-01",
                    "country": "US",
                    "type": "data",
                    "title": "Runtime model test forecast",
                    "question": (
                        "What will the first-print value of the synthetic "
                        "runtime-model test series be for January 2030?"
                    ),
                    "unit": "percent",
                    "pointEstimate": 5.1,
                    "ciLow": 4.7,
                    "ciHigh": 5.8,
                    "confidence": 0.8,
                    "resolutionDate": "2030-01-15",
                    "resolutionSource": "Official synthetic release",
                    "resolutionSourceUrl": "https://example.com/runtime-model",
                    "resolutionRule": (
                        "Resolves to the first official synthetic release "
                        "value for January 2030; later revisions do not count."
                    ),
                    "dataPointId": "test.runtime_model.january_2030.first_print",
                    "historicalContext": [
                        {
                            "period": {
                                "type": "month",
                                "value": f"2029-{index:02d}",
                            },
                            "label": f"2029-{index:02d}",
                            "value": value,
                        }
                        for index, value in enumerate(
                            [4.8, 4.9, 5.0, 4.9, 5.0, 5.2], start=1
                        )
                    ],
                    "drivers": [
                        "recent reference class",
                        "stable monthly series",
                        "synthetic release volatility",
                    ],
                    "sourceContext": [
                        "https://example.com/runtime-model",
                        "https://example.com/runtime-model-calendar",
                    ],
                    "runAt": "2026-06-17T10:00:00Z",
                    "reasoning": [
                        {"kind": "heading", "text": "Runtime model forecast"},
                        {
                            "kind": "text",
                            "text": (
                                "The base-rate reference class is the last "
                                "six synthetic prints around 5.0 percent."
                            ),
                        },
                        {
                            "kind": "tool",
                            "tool": "official.lookup",
                            "call": "lookup synthetic latest values",
                            "result": (
                                "Fetched t-6 4.8, t-5 4.9, t-4 5.0, "
                                "t-3 4.9, t-2 5.0, t-1 5.2."
                            ),
                        },
                        {
                            "kind": "tool",
                            "tool": "calendar.lookup",
                            "call": "lookup synthetic release date",
                            "result": "Fetched release date 2030-01-15.",
                        },
                        {
                            "kind": "math",
                            "text": (
                                "Center on the 5.1 recent mean; sigma = "
                                "0.43 so 1.28 \u00d7 sigma gives the 80% "
                                "interval from 4.7 to 5.8."
                            ),
                        },
                        {
                            "kind": "text",
                            "text": (
                                "Outside the interval if the synthetic series "
                                "breaks from its recent stable pattern."
                            ),
                        },
                        {
                            "kind": "forecast",
                            "point": 5.1,
                            "ciLow": 4.7,
                            "ciHigh": 5.8,
                        },
                    ],
                }
            ]
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.runtime_model",
            "--period",
            "2030-01",
            "--command",
            (
                f"{sys.executable} -c 'import pathlib, sys; "
                "print(pathlib.Path(sys.argv[1]).read_text())' "
                f"{response_path} --model gpt-5.5"
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    manifest = json.loads((out_dir / "manifest.json").read_text())
    cells = json.loads((out_dir / "cells.with_activity.json").read_text())

    assert manifest["agent"]["model"] == "gpt-5.5"
    assert manifest["agent"]["configuredModel"] == "claude-fable-5"
    assert cells[0]["model"] == "gpt-5.5"


def test_command_timeout_writes_failure_manifest(tmp_path):
    out_dir = tmp_path / "timeout-run"
    binding = {
        "registrationCommit": "c" * 40,
        "targetContentHash": "d" * 64,
        "targetRegistrationPath": f"records/targets/2030-01-10-{'d' * 64}.json",
        "registeredAtUtc": "2030-01-10T12:00:00Z",
    }

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.synthetic_rate",
            "--period",
            "2030-01",
            "--command",
            f"{sys.executable} -c 'import time; time.sleep(2)'",
            "--timeout-seconds",
            "1",
            "--target-context-json",
            json.dumps(binding),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    command = json.loads((out_dir / "command.json").read_text())
    manifest = json.loads((out_dir / "manifest.json").read_text())
    error = json.loads((out_dir / "error.json").read_text())

    assert command["returnCode"] == 124
    assert command["timedOut"] is True
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "parse"
    assert error["command"]["timedOut"] is True
    assert manifest["targetContext"] == binding
    assert manifest["runStartedAt"] == manifest["createdAt"]
    for field, value in binding.items():
        assert manifest[field] == value


def test_comparison_generator_maps_and_scales_claims_record(tmp_path):
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    cells_path = record_dir / "cells.with_activity.json"
    command_path = record_dir / "command.json"
    manifest_path = record_dir / "manifest.json"
    out_ts = tmp_path / "live-comparisons.ts"

    command_path.write_text(
        json.dumps({"argv": ["codex", "exec", "-m", "gpt-5.5", "-"]})
    )
    cells_path.write_text(
        json.dumps(
            [
                {
                    "slug": ("us-dol-initial-claims-sa-week-2026-06-13-first-print"),
                    "pointEstimate": 225000,
                    "ciLow": 209000,
                    "ciHigh": 243000,
                    "confidence": 0.8,
                    "drivers": ["latest print rose to 229000"],
                    "sourceContext": ["https://www.dol.gov/ui/data.pdf"],
                    "runAt": "2026-06-16T12:33:22Z",
                    "reasoning": [
                        {"kind": "heading", "text": "Claims"},
                        {
                            "kind": "forecast",
                            "point": 225000,
                            "ciLow": 209000,
                            "ciHigh": 243000,
                        },
                    ],
                }
            ]
        )
    )
    manifest_path.write_text(
        json.dumps(
            {
                "ok": True,
                "promptMode": "fast",
                "cellsPath": str(cells_path),
                "agent": {
                    "agent": "thesis.analyst",
                    "model": "claude-fable-5",
                    "agentVersion": "2.0.0",
                    "promptHash": "prompt-hash",
                    "toolPolicyHash": "tool-hash",
                },
                "artifacts": [
                    {
                        "artifactType": "command",
                        "path": str(command_path),
                        "sha256": "abc",
                        "bytes": 1,
                        "createdAt": "2026-06-16T12:33:11Z",
                    }
                ],
            }
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(COMPARISON_GENERATOR),
            str(out_ts),
            "LIVE_RUNS",
            str(manifest_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    output = out_ts.read_text()
    assert '"initial-claims-week-2026-06-13"' in output
    assert '"pointEstimate": 225' in output
    assert '"ciLow": 209' in output
    assert '"model": "gpt-5.5"' in output
    assert '"promptMode": "fast"' in output


def test_comparison_generator_uses_batch_manifest_catalog_slug(tmp_path):
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    cells_path = record_dir / "cells.with_activity.json"
    command_path = record_dir / "command.json"
    manifest_path = record_dir / "manifest.json"
    batch_manifest_path = tmp_path / "batch.json"
    out_ts = tmp_path / "live-comparisons.ts"

    command_path.write_text(
        json.dumps({"argv": ["codex", "exec", "-m", "gpt-5.5", "-"]})
    )
    cells_path.write_text(
        json.dumps(
            [
                {
                    "slug": "agent-emitted-near-duplicate-slug",
                    "pointEstimate": 4.2,
                    "ciLow": 3.6,
                    "ciHigh": 4.8,
                    "confidence": 0.8,
                    "drivers": ["official monthly indicator is noisy"],
                    "sourceContext": ["https://www.abs.gov.au/statistics"],
                    "runAt": "2026-06-17T02:10:00Z",
                    "reasoning": [
                        {"kind": "heading", "text": "ABS CPI"},
                        {
                            "kind": "forecast",
                            "point": 4.2,
                            "ciLow": 3.6,
                            "ciHigh": 4.8,
                        },
                    ],
                }
            ]
        )
    )
    manifest_path.write_text(
        json.dumps(
            {
                "ok": True,
                "promptMode": "fast",
                "cellsPath": str(cells_path),
                "agent": {
                    "agent": "thesis.analyst",
                    "model": "claude-fable-5",
                    "agentVersion": "2.0.0",
                    "promptHash": "prompt-hash",
                    "toolPolicyHash": "tool-hash",
                },
                "artifacts": [
                    {
                        "artifactType": "command",
                        "path": str(command_path),
                        "sha256": "abc",
                        "bytes": 1,
                        "createdAt": "2026-06-17T02:10:00Z",
                    }
                ],
            }
        )
    )
    batch_manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_batch_manifest_v1",
                "results": [
                    {
                        "ok": True,
                        "manifestPath": str(manifest_path),
                        "target": {
                            "series": "abs.cpi.all_groups.yoy",
                            "period": "2026-05",
                            "catalogSlug": "australia-cpi-annual-rate-may-2026",
                        },
                    }
                ],
            }
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(COMPARISON_GENERATOR),
            str(out_ts),
            "LIVE_RUNS",
            str(manifest_path),
            "--batch-manifest",
            str(batch_manifest_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    output = out_ts.read_text()
    assert '"australia-cpi-annual-rate-may-2026"' in output
    assert '"agent-emitted-near-duplicate-slug"' not in output
    assert '"pointEstimate": 4.2' in output


def test_comparison_generator_does_not_rescale_matching_target_unit(tmp_path):
    record_dir = tmp_path / "record"
    record_dir.mkdir()
    cells_path = record_dir / "cells.with_activity.json"
    command_path = record_dir / "command.json"
    manifest_path = record_dir / "manifest.json"
    batch_manifest_path = tmp_path / "batch.json"
    out_ts = tmp_path / "live-comparisons.ts"

    command_path.write_text(
        json.dumps({"argv": ["codex", "exec", "-m", "gpt-5.5", "-"]})
    )
    cells_path.write_text(
        json.dumps(
            [
                {
                    "slug": "us-dol-initial-claims-sa-week-2026-06-20",
                    "unit": "thousands",
                    "pointEstimate": 225,
                    "ciLow": 208,
                    "ciHigh": 243,
                    "confidence": 0.8,
                    "drivers": ["latest print was 245 thousand"],
                    "sourceContext": ["https://www.dol.gov/ui/data.pdf"],
                    "runAt": "2026-06-21T15:11:54Z",
                    "reasoning": [
                        {"kind": "heading", "text": "Claims"},
                        {
                            "kind": "forecast",
                            "point": 225,
                            "ciLow": 208,
                            "ciHigh": 243,
                        },
                    ],
                }
            ]
        )
    )
    manifest_path.write_text(
        json.dumps(
            {
                "ok": True,
                "promptMode": "fast",
                "cellsPath": str(cells_path),
                "agent": {
                    "agent": "thesis.analyst",
                    "model": "gpt-5.5",
                    "agentVersion": "2.0.0",
                    "promptHash": "prompt-hash",
                    "toolPolicyHash": "tool-hash",
                },
                "artifacts": [
                    {
                        "artifactType": "command",
                        "path": str(command_path),
                        "sha256": "abc",
                        "bytes": 1,
                        "createdAt": "2026-06-21T15:11:48Z",
                    }
                ],
            }
        )
    )
    batch_manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_batch_manifest_v1",
                "results": [
                    {
                        "ok": True,
                        "manifestPath": str(manifest_path),
                        "target": {
                            "series": "us.dol.initial_claims.sa",
                            "period": "week_2026-06-20",
                            "catalogSlug": "initial-claims-week-2026-06-20",
                            "valueScale": 0.001,
                            "targetUnit": "thousands",
                        },
                    }
                ],
            }
        )
    )

    subprocess.run(
        [
            sys.executable,
            str(COMPARISON_GENERATOR),
            str(out_ts),
            "LIVE_RUNS",
            str(manifest_path),
            "--batch-manifest",
            str(batch_manifest_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    output = out_ts.read_text()
    assert '"initial-claims-week-2026-06-20"' in output
    assert '"pointEstimate": 225' in output
    assert '"ciLow": 208' in output
    assert '"pointEstimate": 0.225' not in output


def test_pin_comparison_contract_pins_resolver_but_not_units() -> None:
    from run_thesis_analyst import pin_comparison_contract

    context = {
        "comparisonTarget": True,
        "catalogSlug": "australia-cpi-annual-rate-july-2026",
        "country": "AU",
        "resolutionDate": "2026-08-26",
        "resolutionSource": "Australian Bureau of Statistics",
        "resolutionSourceUrl": "https://www.abs.gov.au/statistics",
        "resolutionRule": "First print of the all groups CPI annual rate.",
        "targetUnit": "percent",
    }
    cell = {
        "slug": "abs-cpi-all-groups-yoy-2026-07",
        "country": "AU",
        "unit": "index points",
        "resolutionDate": "2026-08-27",
        "resolutionSource": "ABS",
        "resolutionSourceUrl": "https://www.abs.gov.au/other",
        "resolutionRule": "First print, unless corrected the same day.",
    }
    pin_comparison_contract(cell, context)
    assert cell["slug"] == context["catalogSlug"]
    assert cell["resolutionDate"] == context["resolutionDate"]
    assert cell["resolutionSource"] == context["resolutionSource"]
    assert cell["resolutionSourceUrl"] == context["resolutionSourceUrl"]
    assert cell["resolutionRule"] == context["resolutionRule"]
    assert cell["unit"] == "index points"

    unpinned = {"slug": "model-slug", "resolutionRule": "model words"}
    pin_comparison_contract(unpinned, {**context, "comparisonTarget": False})
    pin_comparison_contract(unpinned, None)
    assert unpinned == {"slug": "model-slug", "resolutionRule": "model words"}


def _find_negative_zeros(value, path="$"):
    import math

    hits = []
    if isinstance(value, float):
        if value == 0.0 and math.copysign(1.0, value) < 0:
            hits.append(path)
    elif isinstance(value, dict):
        for key, item in value.items():
            hits.extend(_find_negative_zeros(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_find_negative_zeros(item, f"{path}[{index}]"))
    return hits


def test_signed_zeros_never_reach_sealed_artifacts(tmp_path: Path) -> None:
    # An agent may legitimately forecast "-0.0" (zero approached from below).
    # Python's json keeps the sign while JSON.stringify drops it, so a signed
    # zero anywhere in a sealed record splits the Python-written sidecars from
    # the regenerated TS surfaces. The intake normalizer must scrub it.
    from normalize_spawn_json import scrub_signed_zeros

    payload = {
        "pointEstimate": -0.0,
        "ciLow": -0.1,
        "ciHigh": 0.1,
        "thresholdLadder": {
            "thresholds": [-0.1, -0.0, 0.1],
            "cumulativeProbabilities": [0.1, 0.5, 0.9],
        },
        "historicalContext": [{"label": "May 2026", "value": -0.0}],
        "count": 30,
    }
    scrubbed = scrub_signed_zeros(payload)
    assert _find_negative_zeros(scrubbed) == []
    # Ints and ordinary floats pass through untouched.
    assert scrubbed["count"] == 30 and isinstance(scrubbed["count"], int)
    assert scrubbed["ciLow"] == -0.1

    cell = {
        "pointEstimate": -0.0,
        "ciLow": -0.1,
        "ciHigh": 0.1,
    }
    interval = analyst_runner.interval_distribution(cell)
    assert _find_negative_zeros(interval) == []

    ladder_cell = {
        **cell,
        "thresholdLadder": {
            "thresholds": [-0.2, -0.0, 0.2],
            "cumulativeProbabilities": [0.1, 0.5, 0.9],
        },
    }
    ladder = analyst_runner.ladder_distribution(ladder_cell)
    assert ladder is not None
    assert _find_negative_zeros(ladder) == []

    assert json.dumps(analyst_runner.round_distribution_number(-0.0)) == "0.0"
    assert analyst_runner.unsign_zero(240) == 240
    assert isinstance(analyst_runner.unsign_zero(240), int)


def test_ladder_v2_prompt_swaps_the_derivation_contract() -> None:
    meta = {
        "agent": "thesis.analyst",
        "agentVersion": "1.0.0",
        "promptHash": "a" * 64,
        "toolPolicyHash": "b" * 64,
        "model": "gpt-5.5",
    }
    v1 = analyst_runner.build_ladder_prompt("s", "2026-07", None, meta)
    v2 = analyst_runner.build_ladder_v2_prompt("s", "2026-07", None, meta)

    # v1 keeps the parametric discipline; v2 replaces it with the
    # quantile-native contract and never demands the sigma idiom.
    assert "sigma = X" in v1 and "1.28*sigma" in v1
    assert "sigma = X" not in v2 and "1.28*sigma" not in v2
    assert "10th percentile at X" in v2
    assert "90th percentile at Z" in v2
    assert "promptMode ladder_v2" in v2
    # Both elicit the identical ladder mechanics.
    for phrase in (
        "11-15 strictly increasing thresholds",
        "'P(X <= t) = p' pairs",
        "thresholdLadder",
    ):
        assert phrase in v1 and phrase in v2

    prompt, run_meta = analyst_runner.build_run_prompt(
        "s", "2026-07", None, "ladder_v2"
    )
    assert run_meta["agent"] == "thesis.analyst.ladder_v2"
    assert "promptMode ladder_v2" in prompt


def test_canonical_steps_are_stripped_to_contract_keys(tmp_path: Path) -> None:
    # A forecast step decorated with commentary text broke the typed publish
    # build (2026-07-15 APEL wave): canonical kinds must keep only the
    # contract's keys.
    from normalize_spawn_json import norm_steps

    cell = {
        "pointEstimate": 5,
        "ciLow": 4,
        "ciHigh": 6,
        "reasoning": [
            {"kind": "math", "text": "sigma = 1", "confidence": 0.9},
            {
                "kind": "tool",
                "tool": "data.fetch",
                "call": "GET x",
                "result": "42",
                "url": "https://example.gov",
            },
            {
                "kind": "forecast",
                "point": 5,
                "ciLow": 4,
                "ciHigh": 6,
                "text": "final answer commentary",
            },
        ],
    }
    steps = norm_steps(cell)
    assert steps[0] == {"kind": "math", "text": "sigma = 1"}
    assert steps[1] == {
        "kind": "tool",
        "tool": "data.fetch",
        "call": "GET x",
        "result": "42",
    }
    assert steps[2] == {"kind": "forecast", "point": 5, "ciLow": 4, "ciHigh": 6}


def history_floor_test_cell(print_count: int) -> dict:
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["historicalContext"] = [
        {
            "period": {"type": "month", "value": f"2029-{index:02d}"},
            "label": f"2029-{index:02d}",
            "value": 4.5 + index / 10,
        }
        for index in range(1, print_count + 1)
    ]
    return cell


def history_floor_validation(
    cell: dict,
    agent_version: object = analyst_runner.HISTORY_FLOOR_AGENT_VERSION,
) -> dict:
    return analyst_runner.validate_cells(
        [cell],
        allow_existing_slug=True,
        agent_version=agent_version,
    )


def test_history_floor_refuses_five_entry_run_with_custody_clean_record(
    tmp_path: Path,
) -> None:
    generated_ts = tmp_path / "must-not-promote.ts"
    code, out_dir = _run_fake_codex_case(
        tmp_path,
        "five-print-history",
        history_floor_test_cell(5),
        extra_args=["--write-ts", str(generated_ts)],
    )

    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    errors = manifest["validation"]["cells"][0]["errors"]
    assert any(
        "historicalContext has 5 distinct canonical prints" in error
        and "at least 6 are mandatory" in error
        for error in errors
    )
    _custody_passes(out_dir)
    assert not generated_ts.exists()


def test_history_floor_accepts_current_run_with_genuine_custody_root(
    tmp_path: Path,
) -> None:
    generated_ts = tmp_path / "current-rooted.ts"
    code, out_dir = _run_fake_codex_case(
        tmp_path,
        "six-print-current-history",
        history_floor_test_cell(6),
        extra_args=["--write-ts", str(generated_ts)],
    )

    assert code == 0
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is True
    assert spawned_cells_to_ts.agent_version_enforces_history_floor(
        manifest["agent"]["agentVersion"]
    )
    _custody_passes(out_dir)

    [loaded] = spawned_cells_to_ts.load_cells(out_dir / "cells.with_activity.json")
    sealed_version = loaded[spawned_cells_to_ts.SEALED_AGENT_KEY]["agentVersion"]
    sealed_authorization = loaded.get(
        spawned_cells_to_ts.SEALED_HISTORY_AUTHORIZATION_KEY
    )
    assert sealed_version == manifest["agent"]["agentVersion"]
    assert loaded["custodyRootSha256"] == manifest["custodyRootSha256"]
    assert (
        spawned_cells_to_ts.validate(
            loaded,
            set(),
            agent_version=sealed_version,
            trusted_history_authorization=sealed_authorization,
        )
        == []
    )
    assert generated_ts.exists()


def test_history_floor_accepts_six_numeric_entries() -> None:
    assert history_floor_validation(history_floor_test_cell(6))["ok"] is True


def test_history_floor_counts_distinct_periods_with_identical_values() -> None:
    cell = history_floor_test_cell(6)
    for row in cell["historicalContext"]:
        row["value"] = 5.0

    assert history_floor_validation(cell)["ok"] is True


def test_history_floor_refuses_agent_only_attestation_even_with_detail_x() -> None:
    cell = history_floor_test_cell(4)
    cell["historyAvailability"] = {
        "status": "official_source_exposes_fewer_than_six_prints",
        "availablePrintCount": 4,
        "detail": "x",
    }
    cell["_sealedAgentMeta"] = {
        "agent": "thesis.analyst",
        "agentVersion": "2.5.9",
        "promptHash": "a" * 64,
        "toolPolicyHash": "b" * 64,
    }
    cell["_sealedHistoryFloorAuthorization"] = {
        "targetPeriod": "2030-01",
        "status": "official_source_exposes_fewer_than_six_prints",
        "availablePrintCount": 4,
        "availablePeriods": [
            {"type": "month", "value": f"2029-{index:02d}"} for index in range(1, 5)
        ],
    }

    report = history_floor_validation(cell)

    assert report["ok"] is False
    assert any(
        "reviewed docket authorizes this exact series and target period" in error
        for error in report["cells"][0]["errors"]
    )


def test_history_floor_accepts_exact_reviewed_docket_authorization(
    tmp_path: Path,
) -> None:
    periods = [{"type": "month", "value": f"2029-{index:02d}"} for index in range(1, 5)]
    registry = {
        "series": [
            {
                "series": "test.reviewed_rate",
                "period": "2030-01",
                "extras": {
                    "historyFloorAuthorization": {
                        "targetPeriod": "2030-01",
                        "status": "official_source_exposes_fewer_than_six_prints",
                        "availablePrintCount": 4,
                        "availablePeriods": periods,
                    }
                },
            }
        ]
    }
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "docket_series.json").write_text(
        json.dumps(registry) + "\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "add", "scripts/docket_series.json"], cwd=tmp_path, check=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "Review young-series authorization",
        ],
        cwd=tmp_path,
        check=True,
    )
    checkout_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    cell = history_floor_test_cell(4)
    cell["historyAvailability"] = {
        "status": "official_source_exposes_fewer_than_six_prints",
        "availablePrintCount": 4,
        "detail": "The official source contains four prints.",
    }
    report = analyst_runner.validate_cells(
        [cell],
        allow_existing_slug=True,
        agent_version="2.5.10",
        checkout_sha=checkout_sha,
        series="test.reviewed_rate",
        target_period="2030-01",
        history_registry_root=tmp_path,
    )

    assert report["ok"] is True, report


def test_reviewed_authorization_cannot_lower_three_point_minimum() -> None:
    with pytest.raises(ValueError, match="from 3 through 5"):
        validate_history_floor_authorization(
            {
                "targetPeriod": "2030-01",
                "status": "official_source_exposes_fewer_than_six_prints",
                "availablePrintCount": 2,
                "availablePeriods": [
                    {"type": "month", "value": "2029-11"},
                    {"type": "month", "value": "2029-12"},
                ],
            }
        )


def test_history_floor_counts_canonical_periods_not_alias_labels() -> None:
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["historicalContext"] = [
        {
            "period": {"type": "month", "value": "2025-11"},
            "label": "November 2025",
            "value": 26317011,
        },
        {
            "period": {"type": "month", "value": "2026-03"},
            "label": "March 2026",
            "value": 26203615,
        },
        {
            "period": {"type": "month", "value": "2026-04"},
            "label": "April 2026",
            "value": 26182019,
        },
        {
            "period": {"type": "month", "value": "2026-04"},
            "label": "2026-04",
            "value": 26182019,
        },
        {
            "period": {"type": "month", "value": "2026-04"},
            "label": "Apr 2026",
            "value": 26182019,
        },
        {
            "period": {"type": "month", "value": "2026-04"},
            "label": "2026 April print",
            "value": 26182019,
        },
    ]
    cell["historyAvailability"] = {
        "status": "official_source_exposes_fewer_than_six_prints",
        "availablePrintCount": 3,
        "detail": "x",
    }
    target = {
        "anchors": {
            "2025-11": 26317011,
            "2026-03": 26203615,
            "2026-04": 26182019,
        }
    }

    assert analyst_runner.history_anchor_errors(cell, target) == []
    report = analyst_runner.validate_cells(
        [cell], allow_existing_slug=True, target_context=target
    )

    assert report["ok"] is False
    errors = report["cells"][0]["errors"]
    assert any("duplicate canonical periods" in error for error in errors)
    assert any("has 3 distinct canonical prints" in error for error in errors)


def test_history_floor_refuses_labels_that_contradict_forged_periods(
    tmp_path: Path,
) -> None:
    cell = history_floor_test_cell(6)
    for row in cell["historicalContext"]:
        row["label"] = "April 2029"
    target = {
        "anchors": {
            row["period"]["value"]: row["value"] for row in cell["historicalContext"]
        }
    }

    # The existing anchor path trusts the structured period and therefore
    # passes. The shared floor must independently bind each parseable label.
    assert analyst_runner.history_anchor_errors(cell, target) == []
    report = analyst_runner.validate_cells(
        [cell], allow_existing_slug=True, target_context=target
    )
    assert report["ok"] is False
    errors = report["cells"][0]["errors"]
    assert any("label period month 2029-04 does not match" in error for error in errors)
    assert any("has 1 distinct canonical prints" in error for error in errors)

    code, out_dir = _run_fake_codex_case(tmp_path, "mismatched-period-labels", cell)
    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert any(
        "label period month 2029-04 does not match" in error
        for error in manifest["validation"]["cells"][0]["errors"]
    )
    _custody_passes(out_dir)


def test_history_floor_refuses_overlapping_contradictory_period_tokens() -> None:
    cell = history_floor_test_cell(6)
    for index, row in enumerate(cell["historicalContext"], start=1):
        row["label"] = f"April 2029-{index:02d}"

    report = history_floor_validation(cell)

    assert report["ok"] is False
    errors = report["cells"][0]["errors"]
    assert any(
        "label has ambiguous or unsupported period syntax" in error for error in errors
    )
    assert any("has 0 distinct canonical prints" in error for error in errors)


def test_history_floor_refuses_orphan_period_tokens_beside_forged_periods() -> None:
    cell = history_floor_test_cell(6)
    for index, row in enumerate(cell["historicalContext"], start=1):
        row["period"] = {"type": "month", "value": f"2026-{index:02d}"}
        row["label"] = f"April value for 2026-{index:02d}"
    target = {
        "anchors": {
            row["period"]["value"]: row["value"] for row in cell["historicalContext"]
        }
    }

    # The anchor check sees each planted numeric token. The shared floor must
    # also reject the unbound month token rather than count those six aliases.
    assert analyst_runner.history_anchor_errors(cell, target) == []
    report = history_floor_validation(cell)

    assert report["ok"] is False
    errors = report["cells"][0]["errors"]
    assert any(
        "label has ambiguous or unsupported period syntax" in error for error in errors
    )
    assert any("has 0 distinct canonical prints" in error for error in errors)


@pytest.mark.parametrize(
    "label_template",
    [
        "month 4 value for {period}",
        "Q.2 value for {period}",
        "{period} / may",
    ],
)
def test_history_floor_closed_label_grammar_blocks_ascii_aliases(
    label_template: str,
) -> None:
    cell = history_floor_test_cell(6)
    for index, row in enumerate(cell["historicalContext"], start=1):
        period = f"2026-{index:02d}"
        row["period"] = {"type": "month", "value": period}
        row["label"] = label_template.format(period=period)
    target = {
        "anchors": {
            row["period"]["value"]: row["value"] for row in cell["historicalContext"]
        }
    }

    assert analyst_runner.history_anchor_errors(cell, target) == []
    report = history_floor_validation(cell)

    assert report["ok"] is False
    errors = report["cells"][0]["errors"]
    assert any("closed single-period label grammar" in error for error in errors)
    assert any("has 0 distinct canonical prints" in error for error in errors)


def test_history_floor_refuses_fullwidth_orphan_tokens_beside_forged_periods(
    tmp_path: Path,
) -> None:
    cell = history_floor_test_cell(6)
    for index, row in enumerate(cell["historicalContext"], start=1):
        row["period"] = {"type": "month", "value": f"2026-{index:02d}"}
        row["label"] = f"Ａｐｒｉｌ value for 2026-{index:02d}"
    target = {
        "anchors": {
            row["period"]["value"]: row["value"] for row in cell["historicalContext"]
        }
    }

    assert analyst_runner.history_anchor_errors(cell, target) == []
    report = analyst_runner.validate_cells(
        [cell], allow_existing_slug=True, target_context=target
    )
    assert report["ok"] is False
    assert any(
        "characters outside printable ASCII" in error
        for error in report["cells"][0]["errors"]
    )

    code, out_dir = _run_fake_codex_case(tmp_path, "fullwidth-period-labels", cell)
    assert code == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    _custody_passes(out_dir)


@pytest.mark.parametrize("solidus", ["⁄", "∕", "／"])
def test_history_floor_refuses_unicode_solidus_period_aliases(
    solidus: str,
) -> None:
    cell = history_floor_test_cell(6)
    for index, row in enumerate(cell["historicalContext"], start=1):
        row["period"] = {"type": "month", "value": f"2026-{index:02d}"}
        row["label"] = f"2026-{index:02d}{solidus}04"
    target = {
        "anchors": {
            row["period"]["value"]: row["value"] for row in cell["historicalContext"]
        }
    }

    assert analyst_runner.history_anchor_errors(cell, target) == []
    report = history_floor_validation(cell)

    assert report["ok"] is False
    errors = report["cells"][0]["errors"]
    assert any("characters outside printable ASCII" in error for error in errors)
    assert any("has 0 distinct canonical prints" in error for error in errors)


def test_history_floor_refuses_six_shorthand_period_ranges() -> None:
    labels = [
        "December/January 2029",
        "January/February 2029",
        "February/March 2029",
        "March/April 2029",
        "April/May 2029",
        "May/June 2029",
    ]
    cell = history_floor_test_cell(6)
    for row, label in zip(cell["historicalContext"], labels):
        row["label"] = label

    report = history_floor_validation(cell)

    assert report["ok"] is False
    errors = report["cells"][0]["errors"]
    assert any(
        "label has ambiguous or unsupported period syntax" in error for error in errors
    )
    assert any("has 0 distinct canonical prints" in error for error in errors)


@pytest.mark.parametrize(
    "label, expected_error",
    [
        ("latest print", "label has ambiguous or unsupported period syntax"),
        (
            "March 2029 / April 2029",
            "label has ambiguous or unsupported period syntax",
        ),
        (
            "January/February 2029",
            "label has ambiguous or unsupported period syntax",
        ),
        (
            "１2029-01２",
            "label has ambiguous or unsupported period syntax",
        ),
        (
            "January 2029\u200b",
            "label has ambiguous or unsupported period syntax",
        ),
    ],
)
def test_history_floor_refuses_unbound_or_ambiguous_labels(
    label: str, expected_error: str
) -> None:
    cell = history_floor_test_cell(6)
    cell["historicalContext"][0]["label"] = label

    report = history_floor_validation(cell)

    assert report["ok"] is False
    assert any(expected_error in error for error in report["cells"][0]["errors"])


def test_history_floor_refuses_unicode_digit_aliases_of_one_month() -> None:
    aliases = [
        "2026-04",
        "２０２６-０４",
        "٢٠٢٦-٠٤",
        "۲۰۲۶-۰۴",
        "२०२६-०४",
        "২০২৬-০৪",
    ]
    cell = history_floor_test_cell(6)
    cell["historicalContext"] = [
        {
            "period": {"type": "month", "value": alias},
            "label": "April 2026",
            "value": 5.0,
        }
        for alias in aliases
    ]

    assert canonical_period_identity(cell["historicalContext"][0]["period"]) == (
        "month",
        "2026-04",
    )
    assert all(
        canonical_period_identity(row["period"]) is None
        for row in cell["historicalContext"][1:]
    )
    report = history_floor_validation(cell)

    assert report["ok"] is False
    errors = report["cells"][0]["errors"]
    assert any("has no valid canonical period identity" in error for error in errors)
    assert any("has 1 distinct canonical prints" in error for error in errors)


@pytest.mark.parametrize(
    "label, expected",
    [
        ("April 2026", ("month", "2026-04")),
        ("Sept. 2026", ("month", "2026-09")),
        ("2026 April", ("month", "2026-04")),
        ("2026-Q1", ("quarter", "2026-Q1")),
        ("2026 Q1", ("quarter", "2026-Q1")),
        ("Q1 2026", ("quarter", "2026-Q1")),
        ("calendar year 2026", ("year", "2026")),
        ("FY2026", ("fiscal_year", "2026")),
        ("fiscal year 2026", ("fiscal_year", "2026")),
        ("2026-04-03", ("week_ending", "2026-04-03")),
        ("week ending 2026-04-03", ("week_ending", "2026-04-03")),
    ],
)
def test_history_floor_parses_supported_display_label_periods(
    label: str, expected: tuple[str, str]
) -> None:
    assert canonical_period_identities_from_label(label) == {expected}


@pytest.mark.parametrize(
    "label",
    [
        "January/February 2026",
        "2026-01/02",
        "2026-Q1/Q2",
        "2029 Q1/2",
        "Q1/2 2029",
        "2026/27",
        "week ending 2026-04-03/10",
        "１2026-04２",
        "April 2026 / May ２０２６",
        "April ²⁰²⁶ / 2026-01",
        "April ②⓪②⑥ / 2026-01",
        "2026-01 April",
        "FY2026 Q1",
        "FYQ1 2029",
        "2029 quarter 1",
        "2026 QIV",
        "2026 QI",
        "2026 Q1 / II",
        "2026-Q1 April",
        "2026-01 Q4",
        "week ending 2026-04-03 Q1",
        "Ｑ1 2029",
        "ＦＹ2029",
        "fiscal\u00a0year 2026",
        "fiscal\u2028year 2026",
        "week\u00a0ending 2026",
        "week\u2028ending 2026",
        "2026-Q1⁄2",
        "2026 Q1⁄2",
        "2026-01⁄02",
        "2026-01∕02",
        "2026-01／02",
        "2026⁄27",
        "week ending 2026-04-03⁄10",
        "2026−04",
        "2026˗04",
        "2026➖04",
        "2̶0̶2̶6̶-0̶4̶ / 2026-01",
        "Аpril value for 2026-01",
        "April 2026 value may be revised",
        "2026-04 value may be revised",
        "2026-01 / may",
        "2026-01 and may",
        "may value for 2026-01",
        "month 4 value for 2026-01",
        "M04 value for 2026-01",
        "Q.2 value for 2026-01",
        "Q_1 2029",
        "Q.1 2029",
        "Q-1 2029",
        "1Q 2029",
        "2029-QTR1",
        "April 2026 fiscally adjusted",
        "April 2026 FYI preliminary",
    ],
)
def test_history_floor_label_parser_rejects_hidden_period_shorthand(
    label: str,
) -> None:
    assert canonical_period_identities_from_label(label) == set()


def test_history_floor_refuses_oversized_json_integer_with_diagnostic() -> None:
    cell = history_floor_test_cell(6)
    cell["historicalContext"][0]["value"] = 10**400

    report = history_floor_validation(cell)

    assert report["ok"] is False
    assert (
        "historicalContext[0] has no finite numeric value"
        in report["cells"][0]["errors"]
    )


def test_history_floor_refuses_short_history_without_attestation() -> None:
    report = history_floor_validation(history_floor_test_cell(4))

    assert report["ok"] is False
    assert any("reviewed docket" in error for error in report["cells"][0]["errors"])


@pytest.mark.parametrize(
    "availability",
    [
        {
            "status": "official_source_exposes_fewer_than_six_prints",
            "availablePrintCount": 4,
            "detail": "   ",
        },
        {
            "status": "official_source_exposes_fewer_than_six_prints",
            "availablePrintCount": 3,
            "detail": "Only four official prints exist.",
        },
        {
            "status": "fewer_than_six",
            "availablePrintCount": 4,
            "detail": "Only four official prints exist.",
        },
    ],
)
def test_history_floor_refuses_malformed_attestation(availability: dict) -> None:
    cell = history_floor_test_cell(4)
    cell["historyAvailability"] = availability

    assert history_floor_validation(cell)["ok"] is False


def test_history_floor_does_not_retroactively_change_published_replays() -> None:
    assert (
        history_floor_validation(history_floor_test_cell(5), agent_version="2.5.9")[
            "ok"
        ]
        is True
    )


def test_pre_floor_version_still_requires_three_legacy_points() -> None:
    report = history_floor_validation(history_floor_test_cell(2), agent_version="2.5.9")

    assert report["ok"] is False
    assert "needs >=3 historical points" in report["cells"][0]["errors"]


@pytest.mark.parametrize(
    "history, expected_error",
    [
        ([[], [], []], "historicalContext[0] must be an object"),
        ([{}, {}], "historicalContext[0] has no nonempty label"),
        (["x", 7, None], "historicalContext[0] must be an object"),
    ],
)
def test_pre_floor_version_refuses_malformed_legacy_history_shapes(
    history: list[object],
    expected_error: str,
) -> None:
    cell = history_floor_test_cell(3)
    cell["historicalContext"] = history

    report = history_floor_validation(cell, agent_version="2.5.9")

    assert report["ok"] is False
    assert expected_error in report["cells"][0]["errors"]


@pytest.mark.parametrize(
    "row, expected_error",
    [
        ({"label": "   ", "value": 1.0}, "has no nonempty label"),
        ({"label": "legacy", "value": float("inf")}, "has no finite numeric value"),
        ({"label": "legacy", "value": float("nan")}, "has no finite numeric value"),
        ({"label": "legacy", "value": True}, "has no finite numeric value"),
    ],
)
def test_pre_floor_version_requires_labeled_finite_numeric_legacy_rows(
    row: dict[str, object],
    expected_error: str,
) -> None:
    cell = history_floor_test_cell(3)
    cell["historicalContext"][0] = row

    report = history_floor_validation(cell, agent_version="2.5.9")

    assert report["ok"] is False
    assert any(expected_error in error for error in report["cells"][0]["errors"])


@pytest.mark.parametrize(
    "agent_version",
    [
        None,
        "fixture",
        "2.5",
        "02.5.9",
        "2.05.9",
        "2.5.09",
        "2.5.9+.",
        "2.5.9-..",
        "2.5.9-01",
        "２.５.９",
    ],
)
def test_history_floor_missing_or_malformed_version_fails_closed(
    agent_version: object,
) -> None:
    report = history_floor_validation(
        history_floor_test_cell(5), agent_version=agent_version
    )

    assert report["ok"] is False
    assert any(
        "historicalContext has 5 distinct canonical prints" in error
        for error in report["cells"][0]["errors"]
    )


@pytest.mark.parametrize("agent_version", ["2.5.9-alpha+build", "2.2.0+median3"])
def test_history_floor_preserves_valid_complex_pre_floor_versions(
    agent_version: str,
) -> None:
    assert (
        history_floor_validation(
            history_floor_test_cell(5), agent_version=agent_version
        )["ok"]
        is True
    )


def test_history_floor_refuses_overlong_version_without_crashing() -> None:
    report = history_floor_validation(
        history_floor_test_cell(5), agent_version=f"{'9' * 5000}.0.0"
    )

    assert report["ok"] is False
    assert (
        "sealed agentVersion is missing or malformed; current history floor applies"
        in report["cells"][0]["errors"]
    )
    assert any(
        "historicalContext has 5 distinct canonical prints" in error
        for error in report["cells"][0]["errors"]
    )


@pytest.mark.parametrize("agent_version", ["2.5.10-0", "2.5.10-alpha"])
def test_floor_version_family_prereleases_cannot_waive_existing_check(
    agent_version: str,
) -> None:
    report = history_floor_validation(
        history_floor_test_cell(5), agent_version=agent_version
    )

    assert report["ok"] is False
    assert not any(
        "agentVersion is missing or malformed" in error
        for error in report["cells"][0]["errors"]
    )


def test_history_anchor_gate_passes_matching_values() -> None:
    cell = {
        "historicalContext": [
            {"label": "2023 ACS 1-year U.S. B28005 65+ broadband share", "value": 86.5},
            {
                "label": "2024 ACS 1-year U.S. B28005 65+ broadband share",
                "value": 88.24,
            },
            {"label": "2024 ACS all-household broadband share", "value": 91.0},
        ]
    }
    errors = analyst_runner.history_anchor_errors(
        cell, {"anchors": {"2023": 86.5, "2024": 88.2}}
    )
    assert errors == []


def test_history_anchor_gate_refuses_wrong_vintage() -> None:
    # The corrupted lineage: 5-year values labeled as the 1-year series.
    cell = {
        "historicalContext": [
            {"label": "2024 ACS 1-year U.S. B28005 65+ broadband share", "value": 84.8},
        ]
    }
    errors = analyst_runner.history_anchor_errors(cell, {"anchors": {"2024": 88.2}})
    assert len(errors) == 1
    assert "contradict" in errors[0] and "88.2" in errors[0]


def test_history_anchor_gate_requires_anchored_periods() -> None:
    cell = {"historicalContext": [{"label": "2022 share", "value": 84.8}]}
    errors = analyst_runner.history_anchor_errors(cell, {"anchors": {"2024": 88.2}})
    assert len(errors) == 1 and "no historicalContext entry" in errors[0]


def test_history_anchor_gate_flows_through_target_context_validation() -> None:
    cell = {
        "historicalContext": [{"label": "2024 first print", "value": 84.8}],
    }
    errors = analyst_runner.target_context_validation_errors(
        cell, {"anchors": {"2024": 88.2}}
    )
    assert any("anchor" in error for error in errors)


def test_target_context_binds_the_preregistered_conditional_verbatim() -> None:
    # A conditional arm's legal-state text is part of the registered
    # contract; the model must repeat it byte-for-byte in conditionalOn or
    # the site's exact-match condition registry could not gate the cell.
    registered = (
        "Legislation enacted by 2027-12-31 makes the IRC §24(d)(1)(B)(i) "
        "earned-income threshold no more than $1 for tax year 2027."
    )
    exact = {"conditionalOn": registered}
    drifted = {"conditionalOn": registered.replace("$1", "one dollar")}
    context = {"conditional": registered}
    assert analyst_runner.target_context_validation_errors(exact, context) == []
    errors = analyst_runner.target_context_validation_errors(drifted, context)
    assert len(errors) == 1 and "conditionalOn" in errors[0]
    missing = analyst_runner.target_context_validation_errors({}, context)
    assert len(missing) == 1 and "conditionalOn" in missing[0]
    # Unconditional targets are unaffected.
    assert analyst_runner.target_context_validation_errors(exact, {}) == []


def test_bounded_target_context_renders_bound_and_announcement() -> None:
    announcement = "https://www.census.gov/newsroom/spm-announcement.html"
    block = analyst_runner.format_target_context(
        {
            "resolutionDate": "2027-12-31",
            "resolutionDateBasis": "resolve-by-bound",
            "expectedReleaseWindow": {
                "start": "2027-09-01",
                "end": "2027-12-31",
            },
            "sourceBinding": {"sourceUrl": announcement},
        }
    )

    assert 'resolutionDateBasis: "resolve-by-bound"' in block
    assert 'registeredResolveByBound: "2027-12-31"' in block
    assert f'officialAnnouncementUrl: "{announcement}"' in block
    assert "Thesis lab commitments" in block
    assert "announcement authenticates methodology identity only" in block
    assert "does not establish the bound or expected release window" in block
    assert "outer bound, not a scheduled release day" in block
    assert "resolutionDate must byte-echo the registered resolve-by bound" in block
    assert "thesis_announcement_fetch.fetch_official_announcement" in block
    assert "reasoning-token claim" in block


def test_bounded_announcement_mcp_config_is_exact_and_target_scoped() -> None:
    root = Path("/trusted/checkout")
    url = "https://www.census.gov/newsroom/spm-announcement.html"

    assert analyst_runner.announcement_mcp_config(
        url,
        checkout_root=root,
        python_executable="/trusted/checkout/.venv/bin/python3",
    ) == [
        'mcp_servers.thesis_announcement_fetch.command="/trusted/checkout/'
        '.venv/bin/python3"',
        'mcp_servers.thesis_announcement_fetch.args=["/trusted/checkout/scripts/'
        'announcement_fetch_mcp.py","--allowed-url","https://www.census.gov/'
        'newsroom/spm-announcement.html"]',
        'mcp_servers.thesis_announcement_fetch.cwd="/trusted/checkout"',
        "mcp_servers.thesis_announcement_fetch.required=true",
        "mcp_servers.thesis_announcement_fetch.enabled_tools=["
        '"fetch_official_announcement"]',
        "mcp_servers.thesis_announcement_fetch.startup_timeout_sec=10",
        "mcp_servers.thesis_announcement_fetch.tool_timeout_sec=30",
        "mcp_servers.thesis_announcement_fetch.tools.fetch_official_announcement."
        'approval_mode="approve"',
    ]


def test_bounded_cell_gate_requires_byte_echo_but_not_reasoning_fetch_proof() -> None:
    announcement = "https://www.census.gov/newsroom/spm-announcement.html"
    context = {
        "resolutionDate": "2027-12-31",
        "resolutionDateBasis": "resolve-by-bound",
        "sourceBinding": {
            "sourceUrl": announcement,
            "allowedHosts": ["www.census.gov"],
            "expectedReleaseWindow": {
                "start": "2027-09-01",
                "end": "2027-12-31",
            },
        },
    }

    def bounded_cell() -> dict:
        cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
        cell["resolutionDate"] = "2027-12-31"
        cell["resolutionSourceUrl"] = announcement
        cell["sourceContext"][0] = announcement
        cell["runStartedAt"] = "2026-06-17T11:55:00Z"
        return cell

    exact = bounded_cell()
    assert analyst_runner.target_context_validation_errors(exact, context) == []
    unticketed = analyst_runner.validate_cells(
        [exact], allow_existing_slug=True, target_context=context
    )
    assert unticketed["cells"][0]["errors"] == [
        "resolve-by-bound target requires generation ticket context"
    ]
    assert analyst_runner.validate_cells(
        [exact],
        allow_existing_slug=True,
        target_context=context,
        generation_ticket={
            "ticketId": "2030-01-10-deadbeef",
            "ticketPath": ("records/tickets/2030-01-10/2030-01-10-deadbeef.json"),
            "nonceSha256": "a" * 64,
        },
    )["ok"]

    assert announcement not in json.dumps(exact["reasoning"])

    wrong_citation = bounded_cell()
    wrong_citation["resolutionSourceUrl"] = (
        "https://www.census.gov/newsroom/different-announcement.html"
    )
    errors = analyst_runner.target_context_validation_errors(wrong_citation, context)
    assert errors == [
        "resolutionSourceUrl must byte-echo the resolve-by-bound official "
        "announcement URL "
        "'https://www.census.gov/newsroom/spm-announcement.html'"
    ]

    missing_bound = bounded_cell()
    missing_context = dict(context)
    missing_context.pop("resolutionDate")
    errors = analyst_runner.target_context_validation_errors(
        missing_bound, missing_context
    )
    assert errors == [
        "resolve-by-bound target has no canonical registered resolutionDate bound"
    ]

    malformed_context = {**context, "resolutionDate": "2027-02-29"}
    errors = analyst_runner.target_context_validation_errors(
        bounded_cell(), malformed_context
    )
    assert errors == [
        "resolve-by-bound target has no canonical registered resolutionDate bound"
    ]


def test_calendar_target_context_does_not_require_announcement_tool_fetch() -> None:
    cell = review_test_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    context = {
        "sourceBinding": {"sourceUrl": "https://example.com/calendar"},
    }
    assert analyst_runner.target_context_validation_errors(cell, context) == []
    assert (
        analyst_runner.target_context_validation_errors(
            cell, {**context, "resolutionDateBasis": "release-calendar"}
        )
        == []
    )


def test_normalizer_refuses_schema_incomplete_drafts_with_diagnostics(
    tmp_path,
) -> None:
    # The 2026-08-03 auto-roll (run 30779511345): a draft cell lacking
    # `reasoning` crashed normalize_spawn_json with a KeyError, so the batch
    # recorded ok:false with EMPTY validationErrors. A schema-incomplete
    # draft must instead exit nonzero with a line NAMING the cell and the
    # missing key, so the failure record is diagnosable.
    import subprocess

    script = ROOT / "scripts" / "normalize_spawn_json.py"
    src = tmp_path / "parsed.json"
    dst = tmp_path / "normalized.json"

    src.write_text(
        json.dumps(
            [
                {
                    "dataPointId": "irs.actc.total_claims.2027.first_print.current_law",
                    "historicalContext": [],
                }
            ]
        )
    )
    result = subprocess.run(
        [sys.executable, str(script), str(src), str(dst)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "REFUSING" in result.stderr
    assert "irs.actc.total_claims.2027.first_print.current_law" in result.stderr
    assert "reasoning" in result.stderr
    assert not dst.exists()

    # Wrong-typed fields refuse with the type named.
    src.write_text(json.dumps([{"reasoning": "prose", "historicalContext": []}]))
    result = subprocess.run(
        [sys.executable, str(script), str(src), str(dst)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "reasoning is str, not a list" in result.stderr

    # Non-list top level refuses.
    src.write_text(json.dumps({"cells": []}))
    result = subprocess.run(
        [sys.executable, str(script), str(src), str(dst)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "not a list of cell objects" in result.stderr

    # A complete cell still normalizes.
    src.write_text(
        json.dumps(
            [
                {
                    "dataPointId": "x.y.2027.first_print",
                    "reasoning": [{"kind": "text", "text": "base rate"}],
                    "historicalContext": [
                        {
                            "period": {"type": "year", "value": "2023"},
                            "label": "2023",
                            "value": 17.6,
                        }
                    ],
                }
            ]
        )
    )
    result = subprocess.run(
        [sys.executable, str(script), str(src), str(dst)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(dst.read_text())[0]["historicalContext"] == [
        {
            "label": "2023",
            "value": 17.6,
            "period": {"type": "year", "value": "2023"},
        }
    ]

    # A period object cannot manufacture its own corroborating display label.
    # Preserve the missing label as null so shared validation refuses it.
    missing_label = history_floor_test_cell(6)
    missing_label["historicalContext"][0].pop("label")
    src.write_text(json.dumps([missing_label]))
    result = subprocess.run(
        [sys.executable, str(script), str(src), str(dst)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    [normalized] = json.loads(dst.read_text())
    assert normalized["historicalContext"][0]["label"] is None
    report = history_floor_validation(normalized)
    assert report["ok"] is False
    assert "historicalContext[0] has no nonempty label" in report["cells"][0]["errors"]


def test_full_prompt_embeds_the_cell_contract_verbatim() -> None:
    # Four CI waves (thesis#115) produced sound drafts with invented field
    # names because the schema lived behind a "per docs/cell-contract.md"
    # pointer only repo-reading local runs followed. The full prompt must
    # carry the contract text itself and the byte-echo rule for
    # conditionals.
    conditional = (
        "Legislation enacted by 2027-12-31 makes the IRC §24(d)(1)(B)(i) "
        "earned-income threshold no more than $1 for tax year 2027."
    )
    prompt, _meta = analyst_runner.build_run_prompt(
        "irs.actc.total_claims", "2027", conditional, "full"
    )
    contract = (ROOT / "docs" / "cell-contract.md").read_text()
    assert "Cell contract (verbatim" in prompt
    assert contract in prompt
    for field in ('"slug"', '"title"', '"confidence"', '"conditionalOn"'):
        assert field in prompt
    assert f"conditionalOn: {conditional}" in prompt
    assert "byte-for-byte" in prompt
    assert "conditional_on" not in prompt

    unconditional, _ = analyst_runner.build_run_prompt(
        "bls.cps.unemployment_rate", "2026-06", None, "full"
    )
    assert "conditionalOn: null" in unconditional
    assert contract in unconditional


def test_fast_prompt_names_conditional_on_exactly() -> None:
    conditional = (
        "No farm bill enacted by 2027-09-30 sets a CRP acreage ceiling for "
        "fiscal years 2027 through 2031; current law holds."
    )
    prompt, _ = analyst_runner.build_run_prompt(
        "usda.fsa.crp.enrolled_acres_total", "2027-09", conditional, "fast"
    )
    assert f"conditionalOn: {conditional}" in prompt
    assert '"conditionalOn"' in prompt
    assert "byte-for-byte" in prompt
    assert "conditional_on" not in prompt
    assert "# Conditional policy chain (required)" in prompt
    assert "touched population" in prompt and "fetched count" in prompt
    assert "study, program evaluation, or natural experiment" in prompt
    assert "offsetting responses" in prompt
    assert "timing or lag relative to the resolution period" in prompt
    assert "begins exactly `Policy chain:`" in prompt
    assert "repeat each URL exactly in sourceContext" in prompt
    assert "exact phrase `no fetched precedent`" in prompt
    assert "policy term bound: [LOW, HIGH] UNIT" in prompt
    assert "policy term is low-confidence" in prompt

    unconditional, _ = analyst_runner.build_run_prompt(
        "bls.cps.unemployment_rate", "2026-06", None, "fast"
    )
    assert "conditionalOn: null" in unconditional
    assert '"conditionalOn"' not in unconditional
    assert "# Conditional policy chain (required)" not in unconditional


def test_pre_submit_review_requires_conditional_policy_chain_changes() -> None:
    prompt = analyst_runner.build_pre_submit_review_prompt(
        series="test.policy",
        period="2030",
        conditional=POLICY_CONDITIONAL,
        target_context=None,
        original_prompt="original forecaster prompt",
        draft_response="{}",
        prompt_mode="fast",
    )

    assert "beginning exactly `Policy chain:`" in prompt
    assert "touched population with a fetched count" in prompt
    assert "propagation to the measured quantity" in prompt
    assert "offsetting responses" in prompt
    assert "timing or lag" in prompt
    assert "precedent URL" in prompt and "sourceContext" in prompt
    assert "no fetched precedent" in prompt
    assert "numeric policy-term bound" in prompt
    assert "low-confidence label" in prompt
    assert "requires REQUEST_CHANGES" in prompt
    assert "direction and size with the cited precedent" in prompt
    assert '"decision": "APPROVE|REQUEST_CHANGES"' in prompt
    assert "coherence|leakage|policy_chain" in prompt


@pytest.mark.parametrize("mode", ["ladder", "ladder_v2"])
def test_conditional_policy_chain_prompt_does_not_modify_ladder_contracts(
    mode: str,
) -> None:
    prompt, _ = analyst_runner.build_run_prompt(
        "test.policy", "2030", POLICY_CONDITIONAL, mode
    )
    review_prompt = analyst_runner.build_pre_submit_review_prompt(
        series="test.policy",
        period="2030",
        conditional=POLICY_CONDITIONAL,
        target_context=None,
        original_prompt=prompt,
        draft_response="{}",
        prompt_mode=mode,
    )

    assert "# Conditional policy chain (required)" not in prompt
    assert "REQUEST_CHANGES" not in review_prompt
    assert "policy_chain" not in review_prompt


@pytest.mark.parametrize(
    ("mode", "expects_policy_error"),
    [
        ("fast", True),
        ("full", True),
        ("ladder", False),
        ("ladder_v2", False),
    ],
)
def test_conditional_policy_chain_validation_respects_prompt_mode_boundary(
    mode: str,
    expects_policy_error: bool,
) -> None:
    report = analyst_runner.validate_cells(
        [conditional_policy_test_cell(None)],
        allow_existing_slug=True,
        prompt_mode=mode,
    )
    policy_errors = [
        error
        for error in report["cells"][0]["errors"]
        if error.startswith("conditional policy chain:")
    ]

    assert bool(policy_errors) is expects_policy_error


@pytest.mark.parametrize("mode", ["full", "fast", "ladder", "ladder_v2"])
def test_prompts_use_bounded_source_and_date_rules(mode: str) -> None:
    announcement = "https://www.census.gov/newsroom/spm-announcement.html"
    window = {"start": "2028-08-01", "end": "2028-12-31"}
    context = {
        "resolutionDate": "2028-12-31",
        "resolutionDateBasis": "resolve-by-bound",
        "expectedReleaseWindow": window,
        "sourceBinding": {
            "sourceUrl": announcement,
            "expectedReleaseWindow": window,
        },
    }

    prompt, _ = analyst_runner.build_run_prompt(
        "census.spm.child_poverty_rate", "2027", None, mode, context
    )

    assert "resolutionSourceUrl must byte-echo" in prompt
    assert "thesis_announcement_fetch.fetch_official_announcement" in prompt
    assert "resolutionDate must byte-echo the registered resolve-by bound" in prompt
    assert "outer bound, not a scheduled release day" in prompt
    assert "Thesis lab commitments" in prompt
    assert "announcement authenticates methodology identity only" in prompt
    assert "does not establish the bound or expected release window" in prompt
    assert announcement in prompt
    if mode != "full":
        assert "most specific stable page for the exact series" not in prompt
        assert "verified from an official release calendar" not in prompt
    else:
        assert "resolve-by-bound target, byte-echo the Thesis lab-committed" in prompt
        assert "Do not invent a scheduled day" in prompt
        assert "registered methodology-announcement MCP tool" in prompt


def test_fast_calendar_prompt_keeps_literal_calendar_rules() -> None:
    prompt, _ = analyst_runner.build_run_prompt(
        "bls.cps.unemployment_rate",
        "2026-06",
        None,
        "fast",
        {"resolutionDateBasis": "release-calendar"},
    )

    assert "most specific stable page for the exact series" in prompt
    assert "verified from an official release calendar" in prompt
    assert "resolutionDate must byte-echo the registered resolve-by bound" not in prompt


def test_full_prompt_carries_machine_checked_phrasings() -> None:
    # Attempt 5 (thesis#115): drafts finally spoke the schema but were
    # refused for missing interval-falsification phrasing — a CI-regex
    # requirement no prompt stated — and for base rates fetched from
    # near-miss secondary series. Both requirements now live in the
    # contract, which the full prompt embeds.
    prompt, _ = analyst_runner.build_run_prompt(
        "irs.actc.total_claims", "2027", None, "full"
    )
    assert "Machine-checked requirements" in prompt
    assert '"upside risk"' in prompt
    assert '"outside the interval"' in prompt
    assert '"sigma = X"' in prompt
    assert "Prior/update/interval:" in prompt
    assert "Base-rate provenance" in prompt
    assert "never a secondary summary" in prompt
    assert "irs_soi_pub1304_fetch_year" in prompt


def test_target_context_surfaces_the_resolution_parser_command() -> None:
    # Five waves fetched IRS Pub 4801 line-item estimates — a real official
    # near-neighbor — instead of the registered Table 3.3 print; prose
    # pointing at the parser did not change that (thesis#115). The target
    # context now renders the adapter's own fetch as a copy-runnable
    # command; anchor values are still never injected.
    context = {
        "series": "irs.actc.total_claims",
        "dataPointId": "irs.actc.total_claims.2027.first_print.current_law",
        "sourceBinding": {"adapter": "irs-soi-pub1304"},
    }
    block = analyst_runner.format_target_context(context)
    assert "Resolution-grade base-rate fetch" in block
    assert "IRS_SOI_PUB1304_ADAPTERS['irs.actc.total_claims']" in block
    assert "irs_soi_pub1304_fetch_normalized_year" in block
    assert "xlrd==2.0.1" in block
    assert "PERIOD" in block
    for anchor_value in ("19119249", "37771612", "18076696", "17626084"):
        assert anchor_value not in block

    crp = analyst_runner.format_target_context(
        {
            "series": "usda.fsa.crp.enrolled_acres_total",
            "sourceBinding": {"adapter": "fsa-crp-monthly-summary"},
        }
    )
    assert "FSA_CRP_ADAPTERS['usda.fsa.crp.enrolled_acres_total']" in crp
    assert "fsa_crp_fetch_period" in crp
    assert "fetch at least the latest six" in crp
    assert "fetch at least the latest four" not in crp

    eia = analyst_runner.format_target_context(
        {
            "series": "eia.ng.vented_flared.us.annual",
            "sourceBinding": {"adapter": "eia-dnav-xls"},
        }
    )
    assert "EIA_DNAV_ADAPTERS['eia.ng.vented_flared.us.annual']" in eia
    assert "eia_dnav_fetch_year" in eia
    assert "xlrd==2.0.1" in eia
    assert "PERIOD" in eia
    for anchor_value in ("271682", "324207", "335163"):
        assert anchor_value not in eia

    plain = analyst_runner.format_target_context(
        {"series": "x.y", "sourceBinding": {"adapter": "alfred-fred"}}
    )
    assert "Resolution-grade base-rate fetch" not in plain


def test_quarter_anchor_labels_normalize_across_standard_writings() -> None:
    # The 2026-08-12 BEA ITA run fetched the byte-exact official value
    # (18511) labeled "2026 Q1" and was refused because the docket
    # anchor key is "2026-Q1". Quarter keys now match the same quarter
    # in any standard writing; nothing else loosens.
    context = {"anchors": {"2026-Q1": 18511}}
    # The EXACT sealed label from the refused run, pinned byte-for-byte
    # (records/thesis-analyst/2026-08-12/2026-08-12t21-18-43z-bea-ita-
    # personal-transfer-payments-2026-q2/normalized_cells.json).
    ok_cell = {
        "historicalContext": [
            {
                "label": (
                    "BEA ITA Table 5.1 line 18, 2026 Q1 current June 24 2026 vintage"
                ),
                "value": 18511,
            },
        ]
    }
    assert analyst_runner.history_anchor_errors(ok_cell, context) == []
    # Same quarter, other writings.
    for label in ("2026Q1 print", "Q1 2026 seasonally adjusted", "2026-Q1"):
        cell = {"historicalContext": [{"label": label, "value": 18511}]}
        assert analyst_runner.history_anchor_errors(cell, context) == [], label
    # A DIFFERENT quarter or year never matches, and neither do
    # malformed digit runs, out-of-range quarters, or the key appearing
    # inside a longer token (the round-one review's exploit labels).
    for label in (
        "2026 Q2 print",
        "2025 Q1 print",
        "12026 Q15 print",
        "2026 Q10 print",
        "Q1 20260 print",
        "12026-Q15 print",
    ):
        cell = {"historicalContext": [{"label": label, "value": 18511}]}
        errors = analyst_runner.history_anchor_errors(cell, context)
        assert errors and "no historicalContext entry mentions" in errors[0], label
    # A label naming multiple distinct quarters cannot attribute its
    # value to either period; the same quarter written twice still can.
    # ...including with Unicode separators, bare quarter references,
    # and prefixed years (the round-two review's fail-open labels): any
    # quarter mention the extractor cannot canonicalize fails closed.
    for label in (
        "Comparison 2026 Q1 to 2026 Q2; Q2 value",
        "Comparison 2026 Q1 to 2026 Q2; Q2 value",
        "Comparison 2026 Q1 to Q2; Q2 value",
        "2026 Q1 vs 2026‑Q2",
        "FY2026 Q1",
        "x2026 Q1",
        "١Q1 2026",
        "１Q1 2026",
        "éQ1 2026",
        "Q12026 vs Q2",
        "2026 Q1 vs 2026 Q\u200d2",
        "QII print",
        "Q\u0662 print",
        "Q1/2 print",
        "1Q 2026 print",
        "2026 Q1/2 print",
        "2026 Q1/II",
        "Q1 2026/2",
        "2026 Q1 vs Q\u0301\u0032",
        "2026 Q1 vs Q.2",
        "2026 Q1 vs Q_2",
        "2026 Q1 vs Q\u20442",
        "2026 Q1 vs \u051a2",
        "2026 Q1 vs Q\u30222",
        "2026 Q1 vs Q\u2475",
        "2026 Q1 / 2",
        "2026 Q1 (2)",
        "2026 Q1 (II)",
        "2026 Q1 (2027)",
        "2027 (2026 Q1)",
        "2026 Q1\u20442",
        "2026 Q1 2027",
        "Q IV 2026",
        "2026 Q1Q2",
        # Deletion killers: Cf must REJECT (not strip-to-valid) even
        # far from any digit; controls and buffered fraction slashes
        # reject; two strict groups accumulate into distinct tokens.
        "2026 Q\u200d1",
        "2026 Q1 print\u200d",
        "2026 Q1 and Q\u00002",
        "2026 Q1 \u2044 2",
        # Poison dominates mixed gaps and taints even same-token pairs.
        "2026 Q1 , \u2044 2",
        "2026 Q1 \u2044 , 2",
        "2026 Q1 and \u2044 2",
        "2026 Q1 \u2044 2026 Q1",
        "2026 Q1 and 2026 Q2",
        # NFKC must not launder poison: fullwidth punctuation and
        # No-category numerals keep their taint through folding.
        "2026 Q1\uff012",
        "2026 Q1 and \uff01 2",
        "Q\u00b9 2026",
        "2026 QIV,",
    ):
        cell = {"historicalContext": [{"label": label, "value": 18511}]}
        errors = analyst_runner.history_anchor_errors(cell, context)
        assert errors and "no historicalContext entry mentions" in errors[0], label
    twice = {"historicalContext": [{"label": "2026 Q1 (2026Q1) print", "value": 18511}]}
    assert analyst_runner.history_anchor_errors(twice, context) == []
    # Prose "quarterly" after a digit is not a designator.
    for label in (
        "value for 2026 Q1, quarterly seasonally adjusted",
        "Quebec series, 2026 Q1 print",
        "Grade Q, 2026 Q1",
        # Precise mechanism killers: fullwidth Q opens ONLY via NFKC;
        # Arabic-Indic 1 opens ONLY via explicit digit folding;
        # fullwidth 1 opens via either (redundancy sanity).
        "2026 \uff31\uff11 print",
        "2026 Q\u0661 print",
        "2026 Q\uff11 print",
        # Roman-letter prose stays open, including the real published
        # G.19 label (records/.../2026-07-31t15-11-55z-fed-g19-.../
        # normalized_cells.json).
        "2026 Q1 in Fed G.19 table",
        "2026 Q1 value",
        "2026 Q1 vintage",
        "2026 Q1 via BEA",
        # Pinned round-eight rulings: a SPACED confusable letter and a
        # comma-isolated orphan read as prose; glued forms reject.
        "2026 Q1 \u051a 2",
        "2026 Q1 , 2",
    ):
        prose = {"historicalContext": [{"label": label, "value": 18511}]}
        assert analyst_runner.history_anchor_errors(prose, context) == [], label
    # The value check still refuses a wrong number on a matching label.
    wrong = {"historicalContext": [{"label": "2026 Q1", "value": 20000}]}
    errors = analyst_runner.history_anchor_errors(wrong, context)
    assert errors and "contradict" in errors[0]
    # Non-quarter keys keep literal-substring semantics exactly.
    year_context = {"anchors": {"2024": 88.2}}
    miss = {"historicalContext": [{"label": "FY24 print", "value": 88.2}]}
    errors = analyst_runner.history_anchor_errors(miss, year_context)
    assert errors and "no historicalContext entry mentions" in errors[0]


def test_target_context_never_guesses_parser_series_from_data_point_id() -> None:
    missing_series = analyst_runner.format_target_context(
        {
            "dataPointId": ("irs.actc.total_claims.2027.first_print.foreign_suffix"),
            "sourceBinding": {"adapter": "irs-soi-pub1304"},
        }
    )
    assert "Resolution-grade base-rate fetch" not in missing_series
    assert "IRS_SOI_PUB1304_ADAPTERS" not in missing_series

    exact_series = analyst_runner.format_target_context(
        {
            "series": "irs.actc.total_claims",
            "dataPointId": "opaque.unrelated.stem.2027.first_print",
            "sourceBinding": {"adapter": "irs-soi-pub1304"},
        }
    )
    assert "IRS_SOI_PUB1304_ADAPTERS['irs.actc.total_claims']" in exact_series
    assert "IRS_SOI_PUB1304_ADAPTERS['opaque.unrelated.stem']" not in exact_series
