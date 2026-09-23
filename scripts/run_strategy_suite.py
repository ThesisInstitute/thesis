#!/usr/bin/env python3
"""Run one trusted strategy-suite plan over an immutable target selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Any

from strategy_targets import SELECTION_SCHEMA, SUITES, load_object, utc_now

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_BATCH = ROOT / "scripts" / "run_thesis_batch.py"
DERIVE_MEDIAN = ROOT / "scripts" / "median_rollout_ensemble.py"
SUITE_SCHEMA = "thesis_strategy_suite_v1"


class StrategySuiteError(ValueError):
    """The trusted suite plan or one of its deterministic stages is invalid."""


def repo_relative(path: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise StrategySuiteError(
            f"suite path is outside the repository: {path}"
        ) from exc


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def batch_path(day: str, run_id: int, run_attempt: int, lane: str) -> pathlib.Path:
    return (
        ROOT
        / "records"
        / "thesis-analyst"
        / "batches"
        / day
        / f"strategy-{run_id}-a{run_attempt}-{lane}.json"
    )


def suite_path(day: str, run_id: int, run_attempt: int) -> pathlib.Path:
    return (
        ROOT
        / "records"
        / "thesis-analyst"
        / "strategy-suites"
        / day
        / f"strategy-{run_id}-a{run_attempt}.json"
    )


def run_batch(
    *,
    selection_path: pathlib.Path,
    output_path: pathlib.Path,
    prompt_mode: str,
    model: str,
    timeout_seconds: int,
    reviewed: bool,
    selection_ledger_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(RUN_BATCH),
        "--targets-file",
        str(selection_path),
        "--prompt-mode",
        prompt_mode,
        "--timeout-seconds",
        str(timeout_seconds),
        "--codex-model",
        model,
        "--codex-reasoning-effort",
        "low",
        "--out",
        str(output_path),
    ]
    if selection_ledger_path is not None:
        command.extend(["--strategy-ledger-jsonl", str(selection_ledger_path)])
    if reviewed:
        command.extend(["--pre-submit-review-codex-model", model])
    else:
        command.append("--no-pre-submit-review")
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if not output_path.is_file():
        raise StrategySuiteError(
            f"batch runner did not create {output_path} (exit {completed.returncode})"
        )
    batch = load_object(output_path, "strategy batch")
    if batch.get("schemaVersion") != "thesis_batch_manifest_v1":
        raise StrategySuiteError(f"unsupported batch schema: {output_path}")
    return batch


def result_by_slug(batch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = batch.get("results")
    if not isinstance(results, list):
        raise StrategySuiteError("strategy batch has no result inventory")
    indexed: dict[str, dict[str, Any]] = {}
    for result in results:
        target = result.get("target") if isinstance(result, dict) else None
        slug = target.get("catalogSlug") if isinstance(target, dict) else None
        if not slug or slug in indexed:
            raise StrategySuiteError(
                "strategy batch has duplicate or missing target slug"
            )
        indexed[str(slug)] = result
    return indexed


def filtered_batch(batch: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        **batch,
        "targets": 1,
        "ok": 1 if result.get("ok") is True else 0,
        "failed": 0 if result.get("ok") is True else 1,
        "results": [result],
    }


def derive_medians(
    targets: list[dict[str, Any]], rollout_batches: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(rollout_batches) != 3:
        raise StrategySuiteError("median3 requires exactly three rollout batches")
    indexes = [result_by_slug(batch) for batch in rollout_batches]
    derivations: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="thesis-strategy-median-") as temp:
        temp_root = pathlib.Path(temp)
        for target in sorted(targets, key=lambda row: row["catalogSlug"]):
            slug = str(target["catalogSlug"])
            results = [index.get(slug) for index in indexes]
            if any(
                result is None or result.get("ok") is not True for result in results
            ):
                derivations.append(
                    {
                        "catalogSlug": slug,
                        "ok": False,
                        "manifestPath": None,
                        "error": (
                            "median3 requires one passing run in each rollout lane"
                        ),
                    }
                )
                continue
            batch_paths: list[pathlib.Path] = []
            for lane_index, (batch, result) in enumerate(
                zip(rollout_batches, results), start=1
            ):
                assert result is not None
                path = temp_root / f"{slug}-rollout-{lane_index}.json"
                write_json(path, filtered_batch(batch, result))
                batch_paths.append(path)
            out_list = temp_root / f"{slug}-manifests.txt"
            command = [sys.executable, str(DERIVE_MEDIAN)]
            for path in batch_paths:
                command.extend(["--batch", str(path)])
            command.extend(["--out-list", str(out_list)])
            completed = subprocess.run(command, cwd=ROOT, check=False)
            manifests = (
                [
                    line.strip()
                    for line in out_list.read_text().splitlines()
                    if line.strip()
                ]
                if out_list.is_file()
                else []
            )
            if completed.returncode != 0 or len(manifests) != 1:
                derivations.append(
                    {
                        "catalogSlug": slug,
                        "ok": False,
                        "manifestPath": None,
                        "error": (
                            "median3 derivation failed "
                            f"(exit {completed.returncode}, manifests={len(manifests)})"
                        ),
                    }
                )
                continue
            manifest_path = ROOT / manifests[0]
            manifest = load_object(manifest_path, "median3 manifest")
            manifest_slug = (manifest.get("targetContext") or {}).get("catalogSlug")
            if manifest_slug != slug:
                raise StrategySuiteError(
                    f"median3 manifest target mismatch: {slug} != {manifest_slug}"
                )
            derivations.append(
                {
                    "catalogSlug": slug,
                    "ok": True,
                    "manifestPath": manifests[0],
                    "error": None,
                }
            )
    return derivations


def run_suite(
    *,
    selection_path: pathlib.Path,
    run_id: int,
    run_attempt: int,
    output_path: pathlib.Path | None,
    model: str,
    timeout_seconds: int,
    selection_ledger_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    selection = load_object(selection_path, "strategy selection")
    if selection.get("schemaVersion") != SELECTION_SCHEMA:
        raise StrategySuiteError("unsupported strategy selection schema")
    request = selection.get("request") or {}
    suite = request.get("suite")
    if suite not in SUITES:
        raise StrategySuiteError(f"unsupported strategy suite: {suite!r}")
    # The ladder lane's elicitation contract comes from the TRUSTED selection
    # (absent = the v1 ladder contract), never from generate-job inputs.
    ladder_prompt_mode = str(request.get("ladderPromptMode") or "ladder")
    if ladder_prompt_mode not in {"ladder", "ladder_v2"}:
        raise StrategySuiteError(
            f"unsupported ladder prompt mode: {ladder_prompt_mode!r}"
        )
    targets = selection.get("targets")
    if not isinstance(targets, list) or not all(
        isinstance(target, dict) for target in targets
    ):
        raise StrategySuiteError("strategy selection targets must be an object list")
    if any(
        target.get("resolutionDateBasis") == "resolve-by-bound" for target in targets
    ):
        if selection_ledger_path is None:
            raise StrategySuiteError(
                "bounded strategy requires its pinned selection ledger"
            )
    if (
        type(run_id) is not int
        or run_id < 1
        or type(run_attempt) is not int
        or run_attempt < 1
    ):
        raise StrategySuiteError("run id and attempt must be positive integers")
    source_sha = str(selection.get("sourceSha") or "")
    checkout_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if checkout_sha != source_sha:
        raise StrategySuiteError(
            "suite checkout differs from selected source SHA: "
            f"{checkout_sha} != {source_sha}"
        )
    selected_at = str(selection.get("selectedAtUtc") or "")
    day = selected_at[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise StrategySuiteError("selection has no canonical selectedAtUtc")

    lanes: dict[str, Any] = {"ladder": None, "rollouts": [], "median3": []}
    if suite in {"ladder", "both"}:
        path = batch_path(day, run_id, run_attempt, "ladder")
        run_batch(
            selection_path=selection_path,
            output_path=path,
            prompt_mode=ladder_prompt_mode,
            model=model,
            timeout_seconds=timeout_seconds,
            reviewed=True,
            selection_ledger_path=selection_ledger_path,
        )
        lanes["ladder"] = {
            "batchManifest": repo_relative(path),
            "promptMode": ladder_prompt_mode,
        }

    rollout_payloads: list[dict[str, Any]] = []
    if suite in {"median3", "both"}:
        for index in range(1, 4):
            path = batch_path(day, run_id, run_attempt, f"rollout-{index}")
            payload = run_batch(
                selection_path=selection_path,
                output_path=path,
                prompt_mode="fast",
                model=model,
                timeout_seconds=timeout_seconds,
                reviewed=False,
                selection_ledger_path=selection_ledger_path,
            )
            rollout_payloads.append(payload)
            lanes["rollouts"].append(
                {"index": index, "batchManifest": repo_relative(path)}
            )
        lanes["median3"] = derive_medians(targets, rollout_payloads)

    created_at = utc_now()
    expected_output = suite_path(created_at[:10], run_id, run_attempt)
    output_path = output_path or expected_output
    if output_path.resolve() != expected_output.resolve():
        raise StrategySuiteError(
            "suite output must use the invocation path "
            f"{repo_relative(expected_output)}"
        )
    payload = {
        "schemaVersion": SUITE_SCHEMA,
        "sourceSha": source_sha,
        "selectionPath": selection["selectionPath"],
        "selectionSha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "selectionSetHash": selection["selectionSetHash"],
        "suite": suite,
        "createdAt": created_at,
        "lanes": lanes,
    }
    write_json(output_path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=pathlib.Path, required=True)
    parser.add_argument("--selection-ledger-jsonl", type=pathlib.Path)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--timeout-seconds", type=int, default=540)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = run_suite(
            selection_path=args.selection,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            output_path=args.out,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            selection_ledger_path=args.selection_ledger_jsonl,
        )
    except (StrategySuiteError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"STRATEGY SUITE BLOCKED: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "suite": payload["suite"],
                "selectionSetHash": payload["selectionSetHash"],
                "median3": sum(1 for row in payload["lanes"]["median3"] if row["ok"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
