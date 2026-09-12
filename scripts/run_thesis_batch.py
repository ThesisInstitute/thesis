#!/usr/bin/env python3
"""Run a finite queue of thesis.analyst forecasts.

This is intentionally a loop, not a daemon. It records every child run under
`records/thesis-analyst/` through `run_thesis_analyst.py`, then writes a batch
manifest summarizing successes, validation failures, and record paths.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from generation_tickets import (
    TicketError,
    find_ticket_consumption,
    find_ticket_successor,
    load_ticket,
    ticket_batch_filename,
    ticket_introducing_commit,
    ticket_manifest_binding,
    ticket_record_path,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_thesis_analyst.py"
DEFAULT_CODEX_MODEL = "gpt-5.5"

TICKET_CONFLICT_FLAGS = (
    "--target",
    "--targets-file",
    "--max-targets",
    "--skip",
    "--max-failures",
    "--command",
    "--codex-model",
    "--gemini-model",
    "--codex-reasoning-effort",
    "--no-codex-search",
    "--codex-sandbox",
    "--codex-network",
    "--prompt-mode",
    "--pre-submit-review-codex-model",
    "--no-pre-submit-review",
    "--pre-submit-review-codex-search",
    "--timeout-seconds",
    "--out",
)


class BatchRunError(ValueError):
    """A batch invocation was refused before any forecast could run."""


DEFAULT_TARGETS: list[dict[str, Any]] = [
    {
        "series": "statcan.employment_insurance.regular_beneficiaries",
        "period": "2026-04",
        "catalogSlug": "canada-ei-regular-beneficiaries-april-2026",
        "valueScale": 0.001,
        "targetUnit": "thousands",
    },
    {
        "series": "abs.cpi.all_groups.yoy",
        "period": "2026-05",
        "catalogSlug": "australia-cpi-annual-rate-may-2026",
    },
    {
        "series": "abs.labour.unemployment_rate",
        "period": "2026-05",
        "catalogSlug": "australia-unemployment-rate-may-2026",
    },
    {
        "series": "abs.labour.employment_change",
        "period": "2026-05",
        "catalogSlug": "australia-employment-change-may-2026",
    },
    {
        "series": "statcan.gdp_by_industry.monthly_growth",
        "period": "2026-04",
        "catalogSlug": "canada-monthly-gdp-growth-april-2026",
    },
    {
        "series": "statjp.cpi.tokyo_all_items_yoy",
        "period": "2026-06",
        "catalogSlug": "japan-tokyo-cpi-annual-rate-june-2026-prelim",
    },
    {
        "series": "statjp.lfs.unemployment_rate",
        "period": "2026-05",
        "catalogSlug": "japan-unemployment-rate-may-2026",
    },
    {
        "series": "eurostat.hicp.flash.yoy",
        "period": "2026-06",
        "catalogSlug": "euro-flash-hicp-june-2026",
    },
    {
        "series": "eurostat.unemployment_rate",
        "period": "2026-05",
        "catalogSlug": "euro-area-unemployment-rate-may-2026",
    },
    {
        "series": "eurostat.retail_trade.volume_mom",
        "period": "2026-05",
        "catalogSlug": "euro-area-retail-trade-volume-growth-may-2026",
    },
    {
        "series": "bea.core_pce.mom",
        "period": "2026-05",
        "catalogSlug": "us-core-pce-mom-may-2026",
    },
    {
        "series": "bls.jolts.job_openings",
        "period": "2026-05",
        "catalogSlug": "jolts-openings-may-2026",
        "valueScale": 0.001,
        "targetUnit": "millions",
    },
    {
        "series": "bls.ces.nonfarm_payrolls.change",
        "period": "2026-06",
        "catalogSlug": "nonfarm-payrolls-june-2026",
    },
    {
        "series": "bls.cps.unemployment_rate",
        "period": "2026-06",
        "catalogSlug": "unemployment-rate-june-2026",
    },
    {
        "series": "treasury.mts.monthly_deficit",
        "period": "2026-06",
        "catalogSlug": "us-mts-deficit-june-2026",
    },
    {
        "series": "bls.cpi.u.headline_mom",
        "period": "2026-06",
        "catalogSlug": "us-cpi-u-mom-june-2026",
    },
    {
        "series": "bls.cpi.u.core_mom",
        "period": "2026-06",
        "catalogSlug": "us-core-cpi-mom-june-2026",
    },
    {
        "series": "us.dol.initial_claims.sa",
        "period": "week_2026-06-20",
        "catalogSlug": "initial-claims-week-2026-06-20",
        "valueScale": 0.001,
        "targetUnit": "thousands",
    },
    {
        "series": "bea.government_social_benefits.level",
        "period": "2026-05",
        "catalogSlug": "us-government-social-benefits-may-2026",
    },
    {
        "series": "bea.government_social_benefits.social_security",
        "period": "2026-05",
        "catalogSlug": "us-social-security-benefits-may-2026",
    },
    {
        "series": "bea.government_social_benefits.medicare",
        "period": "2026-05",
        "catalogSlug": "us-medicare-benefits-may-2026",
    },
    {
        "series": "bea.government_social_benefits.medicaid",
        "period": "2026-05",
        "catalogSlug": "us-medicaid-benefits-may-2026",
    },
    {
        "series": "bea.wages_and_salaries.level",
        "period": "2026-05",
        "catalogSlug": "us-wages-and-salaries-may-2026",
    },
]


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def slug_time(value: str) -> str:
    return value.lower().replace(":", "-").replace("+00-00", "z")


def parse_target(value: str) -> dict[str, str]:
    parts = value.split(":", 2)
    if len(parts) not in {2, 3}:
        raise argparse.ArgumentTypeError(
            "targets must be SERIES:PERIOD or SERIES:PERIOD:CATALOG_SLUG"
        )
    target = {"series": parts[0], "period": parts[1]}
    if len(parts) == 3:
        target["catalogSlug"] = parts[2]
    return target


def _argv_has_option(argv: list[str], option: str) -> bool:
    return any(value == option or value.startswith(f"{option}=") for value in argv)


def refuse_ticket_conflicts(argv: list[str]) -> None:
    """Reject every argument that could override a ticket's sealed scope."""

    if not _argv_has_option(argv, "--ticket"):
        return
    for option in TICKET_CONFLICT_FLAGS:
        if _argv_has_option(argv, option):
            raise BatchRunError(
                f"ticket mode refuses {option}: generation policy and target "
                "scope come from the ticket"
            )


def _git_output(repo_root: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or f"git exited {completed.returncode}"
        raise BatchRunError(f"ticket mode git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _ticket_path_and_payload(
    ticket_path: str | pathlib.Path, repo_root: pathlib.Path
) -> tuple[pathlib.PurePosixPath, dict[str, Any]]:
    root = repo_root.resolve()
    candidate = pathlib.Path(ticket_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise BatchRunError(
            f"ticket mode refuses a ticket path outside the checkout: {ticket_path}"
        ) from exc
    relative_posix = pathlib.PurePosixPath(relative.as_posix())
    ticket = load_ticket(candidate)
    expected = pathlib.PurePosixPath(ticket_record_path(ticket["ticketId"]))
    if relative_posix != expected:
        raise BatchRunError(
            "ticket mode requires the conventional ticket path: "
            f"{relative_posix} != {expected}"
        )
    return relative_posix, ticket


def _parse_ticket_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def prepare_ticket_mode(
    ticket_path: str | pathlib.Path,
    *,
    repo_root: pathlib.Path,
    now_utc: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, str], str]:
    """Validate one-use ticket state and its exact clean checkout."""

    root = repo_root.resolve()
    relative, ticket = _ticket_path_and_payload(ticket_path, root)
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise BatchRunError("ticket mode now_utc must be timezone-aware UTC")
    if now >= _parse_ticket_time(ticket["expiresAtUtc"]):
        raise BatchRunError(
            f"generation ticket {ticket['ticketId']} expired at "
            f"{ticket['expiresAtUtc']}"
        )

    consumption = find_ticket_consumption(ticket["ticketId"], root)
    if consumption is not None:
        raise BatchRunError(
            f"generation ticket {ticket['ticketId']} was already consumed by "
            f"{consumption}"
        )
    successor = find_ticket_successor(ticket["ticketId"], root)
    if successor is not None:
        raise BatchRunError(
            f"generation ticket {ticket['ticketId']} was superseded by {successor}"
        )

    status = _git_output(root, "status", "--porcelain=v1", "-uall")
    if status:
        raise BatchRunError(
            "ticket mode requires a clean checkout; git status begins: "
            f"{status.splitlines()[0]}"
        )
    introducing = ticket_introducing_commit(relative, root)
    head = _git_output(root, "rev-parse", "HEAD")
    if head != introducing:
        raise BatchRunError(
            f"ticket checkout mismatch: HEAD {head} != ticket introducing "
            f"commit {introducing}"
        )
    context = {
        "ticketId": ticket["ticketId"],
        "ticketPath": relative.as_posix(),
        "nonce": ticket["nonce"],
    }
    return ticket, context, head


def apply_ticket_policy(args: argparse.Namespace, ticket: dict[str, Any]) -> None:
    """Replace every effective batch setting with its ticket-sealed value."""

    policy = ticket["policy"]
    args.prompt_mode = policy["promptMode"]
    args.codex_model = policy["codexModel"]
    args.gemini_model = None
    args.codex_reasoning_effort = policy["codexReasoningEffort"]
    args.codex_sandbox = policy["codexSandbox"]
    args.codex_network = policy["codexNetwork"]
    args.no_codex_search = False
    args.command = None
    args.pre_submit_review_codex_model = policy["reviewCodexModel"]
    args.pre_submit_review_codex_search = policy["reviewCodexSearch"]
    args.no_pre_submit_review = False
    args.timeout_seconds = policy["timeoutSeconds"]


def ticket_batch_path(
    repo_root: pathlib.Path, started_at: str, ticket: dict[str, Any]
) -> pathlib.Path:
    return (
        repo_root
        / "records"
        / "thesis-analyst"
        / "batches"
        / started_at[:10]
        / ticket_batch_filename(ticket)
    )


def load_targets(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.targets_file:
        data = json.loads(pathlib.Path(args.targets_file).read_text())
        targets = data["targets"] if isinstance(data, dict) else data
    elif args.target:
        targets = args.target
    else:
        targets = DEFAULT_TARGETS
    if args.skip:
        targets = targets[args.skip :]
    if args.max_targets is not None:
        targets = targets[: args.max_targets]
    return targets


def resolve_agent_backend(
    args: argparse.Namespace,
    ticket_context: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve one effective forecast backend without silently ignoring another."""

    if ticket_context is not None:
        return "codex", str(args.codex_model)

    command = args.command or os.environ.get("THESIS_AGENT_COMMAND")
    codex_model = args.codex_model or os.environ.get("THESIS_CODEX_MODEL")
    gemini_model = args.gemini_model or os.environ.get("THESIS_GEMINI_MODEL")
    selections = [
        ("command", command),
        ("codex", codex_model),
        ("gemini", gemini_model),
    ]
    selected = [(backend, value) for backend, value in selections if value]
    if len(selected) > 1:
        labels = {
            "command": "--command/THESIS_AGENT_COMMAND",
            "codex": "--codex-model/THESIS_CODEX_MODEL",
            "gemini": "--gemini-model/THESIS_GEMINI_MODEL",
        }
        conflicts = ", ".join(labels[backend] for backend, _value in selected)
        raise BatchRunError(
            "non-ticket batch forecast backend is ambiguous; choose exactly one of "
            f"--command, --codex-model, or --gemini-model (selected: {conflicts})"
        )
    if selected:
        backend, value = selected[0]
        return backend, str(value)
    return "codex", DEFAULT_CODEX_MODEL


def run_one(
    target: dict[str, Any],
    args: argparse.Namespace,
    ticket_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    backend, backend_value = resolve_agent_backend(args, ticket_context)
    argv = [
        sys.executable,
        str(RUNNER),
        "--series",
        target["series"],
        "--period",
        target["period"],
        "--prompt-mode",
        args.prompt_mode,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--allow-existing-slug",
        "--target-context-json",
        json.dumps(target, sort_keys=True),
    ]
    if ticket_context is not None:
        argv.extend(
            [
                "--ticket-id",
                ticket_context["ticketId"],
                "--ticket-path",
                ticket_context["ticketPath"],
                "--ticket-nonce",
                ticket_context["nonce"],
            ]
        )
    if target.get("conditional"):
        argv.extend(["--conditional", target["conditional"]])
    if backend == "command":
        argv.extend(["--command", backend_value])
    elif backend == "gemini":
        argv.extend(["--gemini-model", backend_value])
    else:
        argv.extend(["--codex-model", backend_value])
        if args.no_codex_search:
            argv.append("--no-codex-search")
        if args.codex_reasoning_effort:
            argv.extend(["--codex-reasoning-effort", args.codex_reasoning_effort])
        if args.codex_sandbox:
            argv.extend(["--codex-sandbox", args.codex_sandbox])
        if args.codex_network:
            argv.append("--codex-network")
    if args.no_pre_submit_review:
        pass
    elif args.pre_submit_review_codex_model:
        argv.extend(
            [
                "--pre-submit-review-codex-model",
                args.pre_submit_review_codex_model,
            ]
        )
        if args.pre_submit_review_codex_search:
            argv.append("--pre-submit-review-codex-search")
    started_at = utc_now()
    completed = subprocess.run(
        argv,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    finished_at = utc_now()
    manifest = None
    try:
        manifest = json.loads(completed.stdout)
    except json.JSONDecodeError:
        manifest = None
    validation_errors = []
    if manifest and manifest.get("validation"):
        for cell in manifest["validation"].get("cells", []):
            validation_errors.extend(cell.get("errors", []))
    return {
        "target": target,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "returnCode": completed.returncode,
        "ok": completed.returncode == 0 and bool(manifest and manifest.get("ok")),
        "manifestPath": manifest_path(manifest) if manifest else None,
        "cellsPath": manifest.get("cellsPath") if manifest else None,
        "stdoutTail": completed.stdout[-2000:],
        "stderrTail": completed.stderr[-2000:],
        "validationErrors": validation_errors,
    }


def manifest_path(manifest: dict[str, Any]) -> str | None:
    for artifact in manifest.get("artifacts", []):
        if artifact.get("artifactType") == "manifest":
            return artifact.get("path")
    return None


def write_batch_manifest(
    out_path: pathlib.Path,
    started_at: str,
    finished_at: str,
    args: argparse.Namespace,
    results: list[dict[str, Any]],
    ticket_context: dict[str, str] | None = None,
    checkout_sha: str | None = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schemaVersion": "thesis_batch_manifest_v1",
        "startedAt": started_at,
        "finishedAt": finished_at,
        "promptMode": args.prompt_mode,
        "timeoutSeconds": args.timeout_seconds,
        "targets": len(results),
        "ok": sum(1 for result in results if result["ok"]),
        "failed": sum(1 for result in results if not result["ok"]),
        "results": results,
    }
    if ticket_context is not None:
        if checkout_sha is None:
            raise BatchRunError("ticket batch manifest requires checkoutSha")
        manifest.update(
            {
                "codexModel": args.codex_model,
                "codexReasoningEffort": args.codex_reasoning_effort,
                "codexSandbox": args.codex_sandbox,
                "codexNetwork": args.codex_network,
                "reviewCodexModel": args.pre_submit_review_codex_model,
                "reviewCodexSearch": args.pre_submit_review_codex_search,
                "generationTicket": ticket_manifest_binding(ticket_context),
                "checkoutSha": checkout_sha,
            }
        )
    out_path.write_text(json.dumps(manifest, indent=2) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--ticket")
    parser.add_argument("--target", action="append", type=parse_target)
    parser.add_argument("--targets-file")
    parser.add_argument("--max-targets", type=int)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument(
        "--prompt-mode", choices=["full", "fast", "ladder", "ladder_v2"], default="fast"
    )
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--max-failures", type=int, default=999)
    parser.add_argument("--command")
    parser.add_argument("--codex-model")
    parser.add_argument("--gemini-model")
    parser.add_argument("--codex-reasoning-effort", default="low")
    parser.add_argument("--no-codex-search", action="store_true")
    parser.add_argument(
        "--codex-sandbox",
        help="Forwarded to run_thesis_analyst.py --codex-sandbox",
    )
    parser.add_argument(
        "--codex-network",
        action="store_true",
        help=(
            "Forwarded to run_thesis_analyst.py --codex-network (requires "
            "--codex-sandbox workspace-write); use for targets whose "
            "official endpoints the hosted web-search tool cannot fetch"
        ),
    )
    # Review is on by default: the reviewer rubric (interval-from-realized-
    # volatility, resolver exactness, variant pinning) is exactly the failure
    # profile of unreviewed fast-mode runs. --no-pre-submit-review to opt out.
    parser.add_argument("--pre-submit-review-codex-model", default="gpt-5.5")
    parser.add_argument("--no-pre-submit-review", action="store_true")
    parser.add_argument("--pre-submit-review-codex-search", action="store_true")
    parser.add_argument("--out")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    repo_root: pathlib.Path = ROOT,
    now_utc: datetime | None = None,
) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        refuse_ticket_conflicts(raw_argv)
        args = parse_args(raw_argv)
        ticket: dict[str, Any] | None = None
        ticket_context: dict[str, str] | None = None
        checkout_sha: str | None = None
        if args.ticket:
            ticket, ticket_context, checkout_sha = prepare_ticket_mode(
                args.ticket,
                repo_root=repo_root,
                now_utc=now_utc,
            )
            apply_ticket_policy(args, ticket)
            targets = ticket["targets"]
        else:
            targets = load_targets(args)
        resolve_agent_backend(args, ticket_context)
        started_at = utc_now()
        out = (
            ticket_batch_path(repo_root, started_at, ticket)
            if ticket is not None
            else pathlib.Path(args.out)
            if args.out
            else repo_root
            / "records"
            / "thesis-analyst"
            / "batches"
            / f"{slug_time(started_at)}.json"
        )
    except (BatchRunError, TicketError, OSError) as exc:
        print(f"batch run refused: {exc}", file=sys.stderr)
        return 1

    results = []
    failures = 0
    for index, target in enumerate(targets, start=1):
        print(
            f"[{index}/{len(targets)}] {target['series']} {target['period']}",
            flush=True,
        )
        result = run_one(target, args, ticket_context)
        results.append(result)
        print(
            json.dumps(
                {
                    "ok": result["ok"],
                    "manifestPath": result["manifestPath"],
                    "validationErrors": result["validationErrors"],
                }
            ),
            flush=True,
        )
        write_batch_manifest(
            out,
            started_at,
            utc_now(),
            args,
            results,
            ticket_context,
            checkout_sha,
        )
        if not result["ok"]:
            failures += 1
            if ticket_context is None and failures >= args.max_failures:
                break
    write_batch_manifest(
        out,
        started_at,
        utc_now(),
        args,
        results,
        ticket_context,
        checkout_sha,
    )
    print(f"batch manifest: {out}")
    return 0 if all(result["ok"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
