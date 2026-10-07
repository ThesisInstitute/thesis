#!/usr/bin/env python3
"""Sol 6.1 shadow forecasts: an unpublished model comparison on open targets.

GPT-6.1 Sol, run on ChatGPT-subscription Codex lanes through Subfleet,
forecasts the same registered targets Thesis has already published primary
forecasts for. Each run receives the production thesis.analyst prompt as
`run_thesis_analyst.py --print-prompt` prints it (no tool-evidence MCP
section) under a short wrapper, and its final
message is validated by the production runner in `--response-file` mode.

Nothing here touches `records/**`, the docket, the site, or the publication
gate. The runner records these runs as saved responses, which the publication
gate refuses by design; they are experiment data, scored against the same
Chronicle first prints once the targets resolve.

Subcommands:

  freeze    select open published targets and write targets.json
  prompts   write the wrapped prompt for every target and arm
  batch     write a Subfleet batch manifest for one arm and rollout
  collect   pull finished jobs, audit their traces, validate their responses
  score     score validated runs and the published primaries on resolved targets
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Iterable

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXP = pathlib.Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
RUNNER = SCRIPTS / "run_thesis_analyst.py"
DEFAULT_OPS = pathlib.Path(
    os.environ.get("SOL61_SHADOW_OPS", "~/ThesisInstitute/_sol61-shadow")
).expanduser()
SUBFLEET_JOBS = (
    pathlib.Path(os.environ.get("SUBFLEET_HOME", "~/.subfleet")).expanduser() / "jobs"
)

TARGETS_SCHEMA = "thesis_sol61_shadow_targets_v1"
RESULTS_SCHEMA = "thesis_sol61_shadow_results_v1"
SCORES_SCHEMA = "thesis_sol61_shadow_scores_v1"
# `web` mirrors the CI default lane (read-only sandbox, hosted web search) in
# fast prompt mode. `net` differs from it only in tool access: it mirrors the
# runner's --codex-network lane (workspace-write with outbound network, plus
# the runner's own fetch-honesty note), which Subfleet grants writable Codex
# jobs under policy network.codex_workspace_write (d260). `full` differs from
# `web` only in prompt mode.
ARMS: dict[str, dict[str, Any]] = {
    "web": {
        "task": "research",
        "sandbox": "read-only",
        "network": False,
        "promptMode": "fast",
        "rollouts": 3,
    },
    "net": {
        "task": "build",
        "sandbox": "workspace-write",
        "network": True,
        "promptMode": "fast",
        "rollouts": 3,
    },
    "full": {
        "task": "research",
        "sandbox": "read-only",
        "network": False,
        "promptMode": "full",
        "rollouts": 3,
    },
}

WRAPPER = """\
# Run instructions (read before the task prompt)

You are producing ONE forecast for an unpublished research comparison inside
the Thesis forecasting lab. The task prompt between the markers below is the
exact production prompt the Thesis CI analyst (thesis.analyst, prompt mode
{prompt_mode}) receives for this registered target. Follow it exactly, with these
overrides:

1. No repository. This workspace intentionally holds no Thesis checkout.
   Skip the local-file suggestions in the prompt's "Context access" section.
   Do not read, list or search any file outside this workspace directory.
   Shell use is limited to `date -u +%Y-%m-%dT%H:%M:%SZ`, short arithmetic
   (python3 -c, awk, bc){shell_extra}.
2. Independence. Do not visit, search for or use thesisinstitute.org,
   app.thesisinstitute.org, github.com/ThesisInstitute, or any Thesis or
   Brier forecast, trace or record. This run is compared against Thesis's own
   published forecast for the same target, so it must not see it.
3. Evidence. Take every number from official public sources fetched in this
   run{evidence_tools}. Never present remembered values as fetched evidence.
   If you cannot fetch the history, say so in a text step instead of
   inventing numbers.
4. Do not create or modify files.
5. Output. Your final message must be exactly the one JSON object the prompt
   specifies: no Markdown, no code fence, no text before or after it.

----- BEGIN PRODUCTION PROMPT -----
{production}
----- END PRODUCTION PROMPT -----
"""

ARM_WRAPPER_FIELDS = {
    "web": {
        "shell_extra": "",
        "evidence_tools": " with your web search tool",
    },
    "net": {
        "shell_extra": ", and `curl -sS` against official public data endpoints",
        "evidence_tools": " with your web search tool or `curl -sS`",
    },
}
ARM_WRAPPER_FIELDS["full"] = ARM_WRAPPER_FIELDS["web"]

# Strings whose appearance in a run's searches, opened pages or shell
# commands means the run may have seen a Thesis forecast or record.
CONTAMINATION_RE = re.compile(
    r"thesis\s*institute|thesisinstitute|thesis-forecasts|thesis-api|"
    r"github\.com/thesisinstitute|records/thesis-analyst|forecast-cells|"
    r"ledger-targets|forecast-examples|/ThesisInstitute/",
    re.IGNORECASE,
)
NET_BRANCH = "sol61-shadow-run"

# Codex records shell calls wrapped as `bash -lc 'curl ...'`, so a quote can
# precede the command name.
CURL_RE = re.compile(r"(^|[\s;&|('\"])curl\s", re.IGNORECASE)


# ---------------------------------------------------------------- helpers


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text())


def rel(path: pathlib.Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def run_key(arm: str, slug: str, rollout: int) -> str:
    return f"{arm}/{slug}__r{rollout}"


# ---------------------------------------------------------------- freeze


def window_start(target: dict[str, Any]) -> str:
    """Earliest UTC day the answer could be known, per the registration.

    The nested sourceBinding window is the authenticated one; the top-level
    window and resolutionDate are fallbacks for older registrations.
    """
    binding = target.get("sourceBinding") or {}
    window = (
        binding.get("expectedReleaseWindow")
        or target.get("expectedReleaseWindow")
        or {}
    )
    return str(window.get("start") or target.get("resolutionDate") or "")


def target_key(target: dict[str, Any]) -> str:
    return str(
        target.get("dataPointId") or f"{target.get('series')}::{target.get('period')}"
    )


def published_primaries(batches_dir: pathlib.Path) -> dict[str, dict[str, Any]]:
    """The latest successful primary run per target in committed batch manifests.

    Strategy suites (ladder, median3) attach to an existing primary and are
    excluded; their manifests carry a strategy or suite marker in the path.
    """
    primaries: dict[str, dict[str, Any]] = {}
    for path in sorted(batches_dir.rglob("*.json")):
        if "strategy" in path.name:
            continue
        try:
            batch = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(batch, dict) or not isinstance(batch.get("results"), list):
            continue
        for result in batch["results"]:
            target = result.get("target") or {}
            if not result.get("ok") or not target.get("series"):
                continue
            primaries[target_key(target)] = {
                "target": target,
                "batch": (
                    path.relative_to(ROOT).as_posix()
                    if path.is_relative_to(ROOT)
                    else str(path)
                ),
                "manifestPath": result.get("manifestPath"),
                "cellsPath": result.get("cellsPath"),
                "startedAt": result.get("startedAt"),
                "promptMode": batch.get("promptMode"),
                "codexModel": batch.get("codexModel"),
            }
    return primaries


def select_open(
    primaries: dict[str, dict[str, Any]], cutoff: str
) -> list[dict[str, Any]]:
    """Targets whose answer cannot be known before `cutoff` (YYYY-MM-DD)."""
    chosen = []
    for key, primary in primaries.items():
        start = window_start(primary["target"])
        if start and start >= cutoff:
            chosen.append({"key": key, "windowStart": start, **primary})
    chosen.sort(key=lambda row: (row["windowStart"], row["target"]["catalogSlug"]))
    slugs = [row["target"]["catalogSlug"] for row in chosen]
    duplicates = {slug for slug in slugs if slugs.count(slug) > 1}
    if duplicates:
        raise SystemExit(
            f"duplicate catalog slugs among open targets: {sorted(duplicates)}"
        )
    return chosen


def cmd_freeze(args: argparse.Namespace) -> int:
    primaries = published_primaries(ROOT / "records" / "thesis-analyst" / "batches")
    chosen = select_open(primaries, args.cutoff)
    document = {
        "schemaVersion": TARGETS_SCHEMA,
        "frozenAtUtc": utc_now(),
        "checkoutSha": git_head(),
        "cutoff": args.cutoff,
        "targets": [
            {
                "slug": row["target"]["catalogSlug"],
                "dataPointId": row["key"],
                "windowStart": row["windowStart"],
                "target": row["target"],
                "primary": {
                    key: row[key]
                    for key in (
                        "batch",
                        "manifestPath",
                        "cellsPath",
                        "startedAt",
                        "promptMode",
                        "codexModel",
                    )
                },
            }
            for row in chosen
        ],
    }
    write_json(EXP / "targets.json", document)
    print(f"froze {len(chosen)} open targets (window start >= {args.cutoff})")
    return 0


def load_targets() -> list[dict[str, Any]]:
    document = read_json(EXP / "targets.json")
    if document.get("schemaVersion") != TARGETS_SCHEMA:
        raise SystemExit("targets.json has an unexpected schema")
    return document["targets"]


# ---------------------------------------------------------------- prompts


def runner_argv(
    target: dict[str, Any], *, network: bool, prompt_mode: str
) -> list[str]:
    argv = [
        sys.executable,
        str(RUNNER),
        "--series",
        target["series"],
        "--period",
        target["period"],
        "--prompt-mode",
        prompt_mode,
        "--allow-existing-slug",
        "--target-context-json",
        json.dumps(target, sort_keys=True),
    ]
    if target.get("conditional"):
        argv += ["--conditional", target["conditional"]]
    if network:
        argv += ["--codex-sandbox", "workspace-write", "--codex-network"]
    return argv


def production_prompt(
    target: dict[str, Any], *, network: bool, prompt_mode: str
) -> str:
    completed = subprocess.run(
        runner_argv(target, network=network, prompt_mode=prompt_mode)
        + ["--print-prompt"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"--print-prompt failed for {target.get('catalogSlug')}: "
            f"{completed.stderr[-800:]}"
        )
    return completed.stdout


def compose_prompt(production: str, arm: str) -> str:
    fields = ARM_WRAPPER_FIELDS[arm]
    return WRAPPER.format(
        production=production.rstrip("\n"),
        prompt_mode=ARMS[arm]["promptMode"],
        **fields,
    )


def extract_production(prompt: str) -> str:
    """Recover the embedded production prompt (inverse of compose_prompt)."""
    begin = "----- BEGIN PRODUCTION PROMPT -----\n"
    end = "\n----- END PRODUCTION PROMPT -----"
    start = prompt.index(begin) + len(begin)
    return prompt[start : prompt.index(end, start)]


def prompt_path(arm: str, slug: str) -> pathlib.Path:
    return EXP / "prompts" / arm / f"{slug}.md"


def cmd_prompts(args: argparse.Namespace) -> int:
    index: dict[str, str] = {}
    for row in load_targets():
        for arm, spec in ARMS.items():
            production = production_prompt(
                row["target"], network=spec["network"], prompt_mode=spec["promptMode"]
            )
            text = compose_prompt(production, arm)
            path = prompt_path(arm, row["slug"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            index[f"{arm}/{row['slug']}"] = sha256_bytes(text.encode())
    write_json(EXP / "prompts" / "index.json", index)
    print(f"wrote {len(index)} prompts")
    return 0


# ---------------------------------------------------------------- batch


def ensure_net_workdir(ops: pathlib.Path, slug: str, rollout: int) -> pathlib.Path:
    """A private one-commit repository per writable job.

    Writable Codex jobs need a repository, and jobs sharing one repository's
    git metadata have hung on its locks; a repository of their own avoids
    that. The job runs in place, so no worktree is made.
    """
    workdir = ops / "netwd" / f"{slug}__r{rollout}"
    if not (workdir / ".git").exists():
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / "README.md").write_text(
            "Empty workspace for one Sol 6.1 shadow forecast. Write nothing here.\n"
        )
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "sol61-shadow",
            "GIT_AUTHOR_EMAIL": "sol61-shadow@localhost",
            "GIT_COMMITTER_NAME": "sol61-shadow",
            "GIT_COMMITTER_EMAIL": "sol61-shadow@localhost",
        }
        for argv in (
            # Subfleet refuses a writable job on main or master.
            ["git", "init", "-q", "-b", NET_BRANCH],
            ["git", "add", "README.md"],
            ["git", "commit", "-q", "--no-verify", "-m", "Empty shadow workspace"],
        ):
            subprocess.run(argv, cwd=workdir, check=True, env=env)
    return workdir


def out_path(ops: pathlib.Path, arm: str, slug: str, rollout: int) -> pathlib.Path:
    """Where Subfleet exports the job's final message (its parent must exist)."""
    path = ops / "out" / arm / f"{slug}__r{rollout}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def batch_manifest(
    rows: list[dict[str, Any]],
    *,
    arm: str,
    rollout: int,
    ops: pathlib.Path,
    tier: str,
    label: str,
) -> dict[str, Any]:
    spec = ARMS[arm]
    defaults: dict[str, Any] = {"task": spec["task"], "tier": tier}
    jobs = []
    for row in rows:
        job: dict[str, Any] = {
            "prompt": str(prompt_path(arm, row["slug"])),
            "out": str(out_path(ops, arm, row["slug"], rollout)),
            "name": f"s61-{arm}{rollout}-{row['slug']}",
        }
        if spec["network"]:
            job["workdir"] = str(ensure_net_workdir(ops, row["slug"], rollout))
            job["in_place"] = True
            job["no_preamble"] = True
        else:
            job["workdir"] = str(ops / "workdir")
        jobs.append(job)
    return {"label": label, "defaults": defaults, "jobs": jobs}


def cmd_batch(args: argparse.Namespace) -> int:
    ops = args.ops
    (ops / "workdir").mkdir(parents=True, exist_ok=True)
    rows = load_targets()
    if args.slugs:
        wanted = set(args.slugs.split(","))
        rows = [row for row in rows if row["slug"] in wanted]
        missing = wanted - {row["slug"] for row in rows}
        if missing:
            raise SystemExit(f"unknown slugs: {sorted(missing)}")
    skipped = [row["slug"] for row in rows if not validatable(row["target"])]
    if skipped:
        print(f"skipping {len(skipped)} resolve-by-bound targets: {', '.join(skipped)}")
    rows = [row for row in rows if validatable(row["target"])]
    if args.exclude:
        rows = [row for row in rows if row["slug"] not in set(args.exclude.split(","))]
    for row in rows:
        if not prompt_path(args.arm, row["slug"]).is_file():
            raise SystemExit(
                f"missing prompt for {args.arm}/{row['slug']}; run prompts"
            )
    label = args.label or f"sol61-shadow-{args.arm}-r{args.rollout}"
    manifest = batch_manifest(
        rows, arm=args.arm, rollout=args.rollout, ops=ops, tier=args.tier, label=label
    )
    path = ops / "batches" / f"{label}.json"
    write_json(path, manifest)
    print(path)
    return 0


# ---------------------------------------------------------------- collect


def iter_events(stream: Iterable[str]) -> Iterable[dict[str, Any]]:
    for line in stream:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def audit_trace(lines: Iterable[str]) -> dict[str, Any]:
    """Summarize a Codex JSONL event stream and flag contamination.

    Contamination is any search query, opened page or shell command that names
    a Thesis surface (site, API, repository, record paths), or a shell command
    reading outside the job's own workspace for Thesis files.
    """
    web_searches: list[str] = []
    commands: list[dict[str, Any]] = []
    hits: list[str] = []
    usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    for event in iter_events(lines):
        kind = event.get("type")
        if kind == "turn.completed":
            for key in usage:
                value = (event.get("usage") or {}).get(key)
                if isinstance(value, int):
                    usage[key] += value
            continue
        if kind != "item.completed":
            continue
        item = event.get("item") or {}
        item_type = item.get("type")
        if item_type == "web_search":
            texts = [text for text in _strings(item.get("action") or {})]
            texts.append(str(item.get("query") or ""))
            joined = " | ".join(text for text in texts if text)
            web_searches.append(joined)
            if CONTAMINATION_RE.search(joined):
                hits.append(f"web_search: {joined[:300]}")
        elif item_type == "command_execution":
            command = str(item.get("command") or "")
            commands.append(
                {
                    "command": command[:500],
                    "exitCode": item.get("exit_code"),
                    "curl": bool(CURL_RE.search(command)),
                }
            )
            if CONTAMINATION_RE.search(command):
                hits.append(f"command: {command[:300]}")
    curls = [c for c in commands if c["curl"]]
    return {
        "webSearchCount": len(web_searches),
        "webSearches": web_searches,
        "commandCount": len(commands),
        "curlCount": len(curls),
        "curlSucceeded": sum(1 for c in curls if c["exitCode"] == 0),
        "commands": commands,
        "contaminated": bool(hits),
        "contaminationHits": hits,
        "usage": usage,
    }


def chronology_ok(finished_at: str | None, start_day: str) -> bool:
    """The run must have finished before its target's release window opens.

    `finished_at` is the Subfleet job's UTC finish time; `start_day` is the
    window's first UTC day, so the run must end strictly before 00:00Z on it.
    """
    if not finished_at or not start_day:
        return False
    return finished_at[:10] < start_day


def subfleet_job(job_id: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["subfleet", "runs", "show", job_id, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in completed.stdout.splitlines():
        if line.strip().startswith("{"):
            data = json.loads(line)
            return data.get("job", data) if isinstance(data, dict) else {}
    raise RuntimeError(f"subfleet runs show {job_id} failed: {completed.stderr[-300:]}")


def attempt_stream(job_id: str, attempt_id: str | None) -> pathlib.Path | None:
    job_dir = SUBFLEET_JOBS / job_id
    candidates = []
    if attempt_id:
        candidates.append(job_dir / attempt_id.rsplit("/", 1)[-1] / "stdout")
    candidates += sorted(job_dir.glob("a*/stdout"), reverse=True)
    for path in candidates:
        if path.is_file():
            return path
    return None


EXPECTED_MODEL = "gpt-6.1-sol"


def launch_facts(argv: list[str]) -> dict[str, Any]:
    """Model, effort, sandbox and network access from a Codex launch argv."""

    def option(flag: str) -> str | None:
        for index, value in enumerate(argv[:-1]):
            if value == flag:
                return argv[index + 1]
        return None

    configs = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "-c"]
    effort = next(
        (
            c.split("=", 1)[1]
            for c in configs
            if c.startswith("model_reasoning_effort=")
        ),
        None,
    )
    return {
        "binary": pathlib.Path(argv[0]).name if argv else None,
        "model": option("-m"),
        "reasoningEffort": effort,
        "sandbox": option("--sandbox"),
        "networkAccess": "sandbox_workspace_write.network_access=true" in configs,
    }


def attempt_launch(job_id: str, attempt_id: str | None) -> dict[str, Any] | None:
    if not attempt_id:
        return None
    path = SUBFLEET_JOBS / job_id / attempt_id.rsplit("/", 1)[-1] / "launch.json"
    if not path.is_file():
        return None
    return launch_facts(list(json.loads(path.read_text()).get("argv") or []))


def redacted_lines(path: pathlib.Path) -> list[str]:
    sys.path.insert(0, str(SCRIPTS))
    from tool_evidence import redact_json_value, redact_text  # noqa: PLC0415

    out = []
    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                out.append(
                    json.dumps(redact_json_value(json.loads(stripped)), sort_keys=True)
                )
                continue
            except json.JSONDecodeError:
                pass
        out.append(redact_text(line))
    return out


def validatable(target: dict[str, Any]) -> bool:
    """Whether the runner can validate a saved response for this target.

    The runner validates a resolve-by-bound target only inside a generation
    ticket (spawned_cells_to_ts.py refuses it otherwise), so a shadow run on
    one could never pass validation.
    """
    return target.get("resolutionDateBasis") != "resolve-by-bound"


def validate_response(
    target: dict[str, Any],
    response: pathlib.Path,
    run_dir: pathlib.Path,
    *,
    prompt_mode: str,
) -> dict[str, Any]:
    """Validate a saved response with the production runner.

    The network flag is never passed: the runner refuses --codex-network
    outside a live --codex-model run, and the flag changes only the prompt
    text and the Codex invocation, not validation. The run directory's
    prompt.md is therefore the non-network variant; the prompt actually sent
    is pinned in prompts/ and prompts/index.json.
    """
    if run_dir.exists():
        for child in sorted(run_dir.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
    argv = runner_argv(target, network=False, prompt_mode=prompt_mode) + [
        "--response-file",
        str(response),
        "--out-dir",
        str(run_dir),
    ]
    completed = subprocess.run(
        argv, cwd=ROOT, capture_output=True, text=True, check=False
    )
    try:
        manifest = json.loads(completed.stdout)
    except json.JSONDecodeError:
        manifest = {}
    errors: list[str] = []
    for cell in (manifest.get("validation") or {}).get("cells", []):
        errors.extend(cell.get("errors", []))
    if not manifest:
        errors.append(f"runner produced no manifest: {completed.stderr[-500:]}")
    return {
        "ok": completed.returncode == 0 and bool(manifest.get("ok")),
        "returnCode": completed.returncode,
        "errors": errors,
        "runDir": rel(run_dir),
    }


def load_submissions(ops: pathlib.Path) -> list[dict[str, Any]]:
    """Job receipts written when each batch was submitted (one JSON per line).

    A batch re-submitted under its request id answers with the same jobs, so
    a job id seen twice is kept once.
    """
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted((ops / "submissions").glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip().startswith("{"):
                continue
            row = json.loads(line)
            if row.get("job_id") and row.get("out"):
                rows.setdefault(row["job_id"], row)
    return list(rows.values())


def receipt_key(receipt: dict[str, Any]) -> str:
    out = pathlib.Path(receipt["out"])
    slug, rollout = out.stem.rsplit("__r", 1)
    return run_key(out.parent.name, slug, int(rollout))


def latest_receipts(receipts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Receipts grouped by run key, oldest job first.

    Job ids begin with their UTC creation stamp, so sorting by id orders a
    run's original job before any re-dispatch of it.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for receipt in sorted(receipts, key=lambda row: row["job_id"]):
        grouped.setdefault(receipt_key(receipt), []).append(receipt)
    return grouped


def cmd_submit(args: argparse.Namespace) -> int:
    """Submit one batch manifest under a stable request id and keep the receipts.

    The request id is derived from the label, so submitting the same manifest
    again settles the same jobs instead of creating duplicates.
    """
    manifest_path = args.ops / "batches" / f"{args.label}.json"
    if not manifest_path.is_file():
        raise SystemExit(f"no batch manifest {manifest_path}; run batch first")
    request_id = f"sol61-shadow-{args.label}"
    completed = subprocess.run(
        [
            "subfleet",
            "run",
            "--batch",
            str(manifest_path),
            "--request-id",
            request_id,
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    receipts = args.ops / "submissions" / f"{args.label}.jsonl"
    receipts.parent.mkdir(parents=True, exist_ok=True)
    with receipts.open("a") as handle:
        handle.write(completed.stdout)
    rows = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.strip().startswith("{")
    ]
    made = sum(1 for row in rows if row.get("job_id"))
    rc = completed.returncode
    print(f"{args.label}: {made} of {len(rows)} jobs submitted (rc {rc})")
    if completed.stderr.strip():
        print(completed.stderr.strip()[-2000:], file=sys.stderr)
    return completed.returncode


def cmd_collect(args: argparse.Namespace) -> int:
    ops = args.ops
    targets = {row["slug"]: row for row in load_targets()}
    results_path = EXP / "results.json"
    results = read_json(results_path)["runs"] if results_path.exists() else {}
    pending = 0
    for key, receipts in latest_receipts(load_submissions(ops)).items():
        receipt = receipts[-1]
        job_id = receipt["job_id"]
        out = pathlib.Path(receipt["out"])
        slug = out.name.rsplit("__r", 1)[0]
        arm = out.parent.name
        rollout = int(out.stem.rsplit("__r", 1)[1])
        prior = results.get(key) or {}
        if prior.get("final") and prior.get("jobId") == job_id and not args.revalidate:
            continue
        job = subfleet_job(job_id)
        state = job.get("state")
        row: dict[str, Any] = {
            "arm": arm,
            "slug": slug,
            "rollout": rollout,
            "jobId": job_id,
            "state": state,
            "model": job.get("pinned_model") or job.get("model"),
            "createdAt": job.get("created_at"),
            "startedAt": job.get("started_at"),
            "finishedAt": job.get("finished_at"),
            "acceptedAttempt": job.get("accepted_attempt_id"),
        }
        if state not in {"succeeded", "failed", "cancelled", "abandoned"}:
            pending += 1
            results[key] = {**row, "final": False}
            continue
        target = targets[slug]
        row["windowStart"] = target["windowStart"]
        row["chronologyOk"] = chronology_ok(row["finishedAt"], target["windowStart"])
        stream = attempt_stream(job_id, row["acceptedAttempt"])
        if stream is not None:
            lines = redacted_lines(stream)
            trace = EXP / "traces" / arm / f"{slug}__r{rollout}.jsonl.gz"
            trace.parent.mkdir(parents=True, exist_ok=True)
            payload = ("\n".join(lines) + "\n").encode()
            # mtime=0 keeps the archive byte-identical across re-collections.
            trace.write_bytes(gzip.compress(payload, mtime=0))
            row["trace"] = rel(trace)
            row["traceSha256"] = sha256_bytes(payload)
            row["audit"] = audit_trace(lines)
        else:
            row["audit"] = None
        launch = attempt_launch(job_id, row["acceptedAttempt"])
        row["launch"] = launch
        row["model"] = (launch or {}).get("model")
        if state == "succeeded" and out.is_file() and out.stat().st_size:
            response = EXP / "responses" / arm / f"{slug}__r{rollout}.txt"
            response.parent.mkdir(parents=True, exist_ok=True)
            response.write_bytes(out.read_bytes())
            row["response"] = rel(response)
            row["responseSha256"] = sha256_bytes(out.read_bytes())
            row["validation"] = validate_response(
                target["target"],
                response,
                EXP / "runs" / arm / f"{slug}__r{rollout}",
                prompt_mode=ARMS[arm]["promptMode"],
            )
        else:
            row["validation"] = {
                "ok": False,
                "errors": [f"job {state} without a deliverable"],
            }
        audit = row.get("audit") or {}
        row["eligible"] = bool(
            row["validation"]["ok"]
            and row["chronologyOk"]
            and audit
            and not audit.get("contaminated")
            and row["model"] == EXPECTED_MODEL
        )
        # A re-dispatched run replaces the record of the job it retried;
        # the earlier jobs stay listed with their final state.
        row["supersededJobs"] = [
            {
                "jobId": earlier["job_id"],
                "state": subfleet_job(earlier["job_id"]).get("state"),
            }
            for earlier in receipts[:-1]
        ]
        row["final"] = True
        results[key] = row
    write_json(
        results_path,
        {"schemaVersion": RESULTS_SCHEMA, "collectedAtUtc": utc_now(), "runs": results},
    )
    finals = [row for row in results.values() if row.get("final")]
    eligible = sum(1 for row in finals if row.get("eligible"))
    print(
        f"collected {len(finals)} finished runs ({eligible} eligible), "
        f"{pending} still pending"
    )
    return 0


# ---------------------------------------------------------------- score


def integrate_squared_linear(width: float, start: float, end: float) -> float:
    """Exact integral of a squared linear function over [0, width]."""
    if width <= 0:
        return 0.0
    return width * (start * start + start * end + end * end) / 3


def crps_numeric_cdf(points: list[dict[str, float]], observed: float) -> float:
    """Exact CRPS of a piecewise-linear CDF (numeric_cdf_v1) at `observed`.

    A line-for-line port of scoreNumericCdfDistribution in
    site/src/data/prediction-distribution.ts, so these scores match the
    site's for the same distribution and observation (before its rounding).
    """
    if len(points) < 2:
        raise ValueError("CDF must contain at least 2 points")
    if not isinstance(observed, (int, float)) or observed != observed:
        raise ValueError("observed value must be finite")
    crps = 0.0
    for index in range(1, len(points)):
        previous, current = points[index - 1], points[index]
        pv, pp = float(previous["value"]), float(previous["probability"])
        cv, cp = float(current["value"]), float(current["probability"])
        if pv < observed < cv:
            at = pp + (observed - pv) / (cv - pv) * (cp - pp)
            crps += integrate_squared_linear(observed - pv, pp, at)
            crps += integrate_squared_linear(cv - observed, at - 1, cp - 1)
            continue
        indicator = 0.0 if cv <= observed else 1.0
        crps += integrate_squared_linear(cv - pv, pp - indicator, cp - indicator)
    lower, upper = float(points[0]["value"]), float(points[-1]["value"])
    if observed < lower:
        crps += lower - observed
    if observed > upper:
        crps += observed - upper
    return crps


def cdf_probability(points: list[dict[str, float]], value: float) -> float:
    if value <= points[0]["value"]:
        return float(points[0]["probability"])
    for index in range(1, len(points)):
        previous, current = points[index - 1], points[index]
        if value <= current["value"]:
            width = current["value"] - previous["value"]
            if width <= 0:
                return float(current["probability"])
            ratio = (value - previous["value"]) / width
            return float(
                previous["probability"]
                + ratio * (current["probability"] - previous["probability"])
            )
    return float(points[-1]["probability"])


def load_observations(path: pathlib.Path) -> dict[str, dict[str, Any]]:
    """First Chronicle observation per source_record_id (= Thesis dataPointId)."""
    observations: dict[str, dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = row.get("source_record_id")
        if key and key not in observations:
            observations[key] = row
    return observations


def distribution_of(run_dir: pathlib.Path) -> dict[str, Any] | None:
    path = run_dir / "distribution.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    if isinstance(data, list):
        data = data[0] if data else None
    return data


def primary_distribution(manifest_path: str | None) -> dict[str, Any] | None:
    """The published primary's distribution, read from main's history."""
    if not manifest_path:
        return None
    run_dir = pathlib.PurePosixPath(manifest_path).parent
    completed = subprocess.run(
        ["git", "show", f"origin/main:{run_dir}/distribution.json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    data = json.loads(completed.stdout)
    if isinstance(data, list):
        data = data[0] if data else None
    return data


def score_distribution(
    dist: dict[str, Any] | None, observed: float
) -> dict[str, Any] | None:
    if not dist or not dist.get("points"):
        return None
    points = dist["points"]
    p10 = _quantile(points, 0.1)
    p90 = _quantile(points, 0.9)
    return {
        "crps": crps_numeric_cdf(points, observed),
        "pit": cdf_probability(points, observed),
        "median": _quantile(points, 0.5),
        "absErrorMedian": abs(_quantile(points, 0.5) - observed),
        "covered80": p10 <= observed <= p90,
    }


def _quantile(points: list[dict[str, float]], q: float) -> float:
    for index in range(1, len(points)):
        previous, current = points[index - 1], points[index]
        if current["probability"] >= q:
            span = current["probability"] - previous["probability"]
            if span <= 0:
                return float(current["value"])
            ratio = (q - previous["probability"]) / span
            return float(
                previous["value"] + ratio * (current["value"] - previous["value"])
            )
    return float(points[-1]["value"])


def cmd_score(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(SCRIPTS))
    from median_rollout_ensemble import median_distribution  # noqa: PLC0415

    observations = load_observations(args.ledger)
    targets = {row["slug"]: row for row in load_targets()}
    runs = read_json(EXP / "results.json")["runs"]
    scored = []
    for slug, target in targets.items():
        observation = observations.get(target["dataPointId"])
        if observation is None:
            continue
        unit = (observation.get("measure") or {}).get("unit")
        target_unit = target["target"].get("targetUnit") or target["target"].get("unit")
        observed = float(observation["value"])
        row: dict[str, Any] = {
            "slug": slug,
            "dataPointId": target["dataPointId"],
            "observed": observed,
            "observationUnit": unit,
            "targetUnit": target_unit,
            "unitMatch": unit == target_unit,
            "primary": score_distribution(
                primary_distribution(target["primary"].get("manifestPath")), observed
            ),
            "arms": {},
        }
        for arm, spec in ARMS.items():
            eligible = [
                runs[run_key(arm, slug, r)]
                for r in range(1, spec["rollouts"] + 1)
                if runs.get(run_key(arm, slug, r), {}).get("eligible")
            ]
            per_run = {
                f"r{run['rollout']}": score_distribution(
                    distribution_of(ROOT / run["validation"]["runDir"]), observed
                )
                for run in eligible
            }
            arm_row: dict[str, Any] = {"runs": per_run}
            if spec["rollouts"] >= 3 and len(eligible) >= 3:
                cells = []
                for run in eligible[:3]:
                    normalized = json.loads(
                        (
                            ROOT / run["validation"]["runDir"] / "normalized_cells.json"
                        ).read_text()
                    )
                    cells.append(
                        normalized[0] if isinstance(normalized, list) else normalized
                    )
                arm_row["median3"] = score_distribution(
                    median_distribution(cells), observed
                )
            row["arms"][arm] = arm_row
        scored.append(row)
    write_json(
        EXP / "scores.json",
        {
            "schemaVersion": SCORES_SCHEMA,
            "scoredAtUtc": utc_now(),
            "ledger": str(args.ledger),
            "targets": scored,
        },
    )
    print(f"scored {len(scored)} resolved targets")
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ops", type=pathlib.Path, default=DEFAULT_OPS)
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser("freeze")
    freeze.add_argument("--cutoff", required=True, help="YYYY-MM-DD")
    freeze.set_defaults(func=cmd_freeze)

    prompts = sub.add_parser("prompts")
    prompts.set_defaults(func=cmd_prompts)

    batch = sub.add_parser("batch")
    batch.add_argument("--arm", choices=sorted(ARMS), required=True)
    batch.add_argument("--rollout", type=int, required=True)
    batch.add_argument("--tier", default="hard")
    batch.add_argument("--slugs", help="comma-separated subset (default: all)")
    batch.add_argument("--exclude", help="comma-separated slugs to leave out")
    batch.add_argument("--label")
    batch.set_defaults(func=cmd_batch)

    submit = sub.add_parser("submit")
    submit.add_argument("--label", required=True)
    submit.set_defaults(func=cmd_submit)

    collect = sub.add_parser("collect")
    collect.add_argument("--revalidate", action="store_true")
    collect.set_defaults(func=cmd_collect)

    score = sub.add_parser("score")
    score.add_argument("--ledger", type=pathlib.Path, required=True)
    score.set_defaults(func=cmd_score)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
