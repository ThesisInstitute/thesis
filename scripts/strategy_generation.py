"""Authenticate bounded CI strategy inputs and native announcement evidence.

CI comparisons use the witnessed, registered strategy selection, not a minted
operator generation ticket. These helpers are trusted harness code; no cell or
manifest field can grant this authority by itself.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
from types import SimpleNamespace
from typing import Any

from canonical_json import canonical_bytes
from strategy_targets import (
    StrategyTargetError,
    ensure_open,
    load_object,
    parse_utc,
    verify_selection,
)


def authenticate_strategy_target(
    *,
    root: pathlib.Path,
    selection_path: pathlib.Path,
    ledger_path: pathlib.Path,
    target: dict[str, Any],
    run_started_at: str,
    prompt_mode: str = "ladder",
) -> dict[str, Any]:
    """Reconstruct the selection from trusted source before starting Codex."""
    selection = load_object(selection_path, "strategy selection")
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    if selection.get("sourceSha") != head:
        raise StrategyTargetError(
            "bounded strategy checkout differs from selected source"
        )
    verify_selection(selection, root=root, ledger_path=ledger_path)
    selected_mode = str(
        (selection.get("request") or {}).get("ladderPromptMode") or "ladder"
    )
    if prompt_mode not in {"ladder", "ladder_v2"} or prompt_mode != selected_mode:
        raise StrategyTargetError(
            "bounded strategy prompt mode differs from selected lane"
        )
    checked = parse_utc(run_started_at, "strategy runStartedAt")
    selected = parse_utc(selection.get("selectedAtUtc"), "strategy selectedAtUtc")
    witnessed = parse_utc(
        (selection.get("workflow") or {}).get("artifactCreatedAtUtc"),
        "strategy artifactCreatedAtUtc",
    )
    if not selected <= witnessed <= checked or witnessed - selected > dt.timedelta(
        minutes=15
    ):
        raise StrategyTargetError(
            "bounded strategy run is outside its selection witness"
        )
    # verify_selection reauthenticates the source, immutable registrations,
    # reviewed pair, and pinned absence evidence. Workflow also checks the
    # latest ledger immediately before this invocation and before publication.
    ensure_open(
        selection, root=root, ledger_path=ledger_path, checked_at_utc=run_started_at
    )
    matches = [
        row
        for row in selection["targets"]
        if canonical_bytes(row) == canonical_bytes(target)
    ]
    if (
        len(matches) != 1
        or selection.get("billSelection") is None
        or target.get("comparisonTarget") is not True
        or not target.get("conditional")
        or target.get("resolutionDateBasis") != "resolve-by-bound"
    ):
        raise StrategyTargetError(
            "bounded strategy target differs from its reviewed selection"
        )
    return matches[0]


def bounded_strategy_evidence_errors(
    run_dir: pathlib.Path,
    run_relative: pathlib.PurePosixPath,
    target: dict[str, Any],
) -> list[str]:
    """Require exact-URL successful native MCP fetch before a forecast output.

    The publisher first verifies the complete custody inventory. At generation
    this reads the harness-written stage artifacts before sealing that inventory.
    The same command-shape and structured-event checks serve the ticket lane.
    Reviewer prose, stderr, search citations, and failed/redirected fetches do
    not qualify.
    """
    from run_thesis_analyst import parse_codex_jsonl, target_announcement_url
    from verify_attested_bundle import (
        _check_command_argv,
        _stage_has_authenticated_announcement_fetch,
    )

    url = target_announcement_url(target)
    if not url:
        return ["bounded strategy target lacks its registered announcement URL"]
    for prefix in ("draft_", ""):
        command_path = run_dir / f"{prefix}command.json"
        stdout_path = run_dir / f"{prefix}codex_stdout.jsonl"
        last_path = run_dir / f"{prefix}codex_last_message.txt"
        response_path = run_dir / f"{prefix}stdout.txt"
        if not all(
            path.is_file()
            for path in (command_path, stdout_path, last_path, response_path)
        ):
            continue
        try:
            command = json.loads(command_path.read_text())
            if not isinstance(command, dict):
                continue
            argv = command.get("argv")
            if (
                command.get("backend") != "codex"
                or command.get("returnCode") != 0
                or not isinstance(argv, list)
                or not all(isinstance(value, str) for value in argv)
            ):
                continue
            model = argv[argv.index("-m") + 1]
            _check_command_argv(
                argv,
                run=SimpleNamespace(index="strategy", run_relative=run_relative),
                filename=command_path.name,
                model=model,
                search=True,
                policy={
                    "codexReasoningEffort": "low",
                    "codexSandbox": "read-only",
                    "codexNetwork": False,
                },
                announcement_url=url,
                tool_evidence=True,
            )
            parsed = parse_codex_jsonl(stdout_path.read_text(), "")
            last = last_path.read_text()
            if parsed["lastAssistantText"] != last or response_path.read_text() != last:
                continue
            if _stage_has_authenticated_announcement_fetch(
                tuple(parsed["events"]), announcement_url=url
            ):
                return []
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
    return [
        "bounded strategy requires a successful authenticated announcement fetch "
        f"for {url!r} in draft/final Codex stdout"
    ]
