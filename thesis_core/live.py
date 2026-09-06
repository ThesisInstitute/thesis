"""Local admission for the permanently unranked live pilot protocol."""

from __future__ import annotations

import hashlib
import math
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .contracts import EvaluationTask, Experiment, ForecasterVersion, TargetVersion
from .evaluation import dependency_closure, outcome_boundary, validate_experiment
from .security import agent_subprocess_env

PILOT_DEADLINE_BEFORE_SPAWN = "PILOT_DEADLINE_BEFORE_SPAWN"


class PilotDeadlineError(ValueError):
    """The sealed execution budget no longer fits the local pilot boundary."""


def database_now(store) -> datetime:
    with store.connection() as connection:
        return connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]


def validate_live_dispatch(
    store,
    task: EvaluationTask,
    experiment_id: str | None,
    *,
    now: datetime | None = None,
    budget_seconds: float = 0,
) -> datetime:
    """Reopen the exact cohort and source bytes before any pilot invocation."""
    from .service import context_for_store

    if task.mode != "live_pilot" or not experiment_id:
        raise ValueError("live dispatch requires its registered experiment")
    context = context_for_store(store)
    experiment = context.records.get(experiment_id)
    if not isinstance(experiment, Experiment) or experiment.mode != "live_pilot":
        raise ValueError("pilot dispatch experiment mode mismatch")
    tasks = validate_experiment(experiment, context)
    if task.id not in {member.id for member in tasks}:
        raise ValueError("pilot dispatch task is not a cohort member")
    observed_now = now if now is not None else database_now(store)
    for record in dependency_closure(experiment, context):
        acknowledged = context.committed_at(record.id)
        if acknowledged is None or acknowledged >= observed_now:
            raise ValueError("pilot preregistration did not precede dispatch")
    boundaries = []
    for member in tasks:
        target = context.records[member.target_version_id]
        if not isinstance(target, TargetVersion):
            raise ValueError("pilot target record is missing")
        boundary = outcome_boundary(target, context)
        if boundary is None:
            raise ValueError("pilot has no authenticated future outcome boundary")
        boundaries.extend(
            (member.information_cutoff, member.submission_deadline, boundary)
        )
    deadline = min(boundaries)
    if not math.isfinite(budget_seconds) or budget_seconds < 0:
        raise ValueError("pilot execution budget must be finite and nonnegative")
    if observed_now + timedelta(seconds=budget_seconds) >= deadline:
        raise PilotDeadlineError(PILOT_DEADLINE_BEFORE_SPAWN)
    return deadline


def _wrapper_bytes(argv: tuple[str, ...]) -> dict[str, bytes]:
    if not argv or "/" in argv[0] or "\\" in argv[0]:
        raise ValueError("pilot transport must be a PATH-resolved command name")
    for argument in argv[1:]:
        value = argument.partition("=")[2] if "=" in argument else argument
        if value.startswith(("/", "~", "\\")):
            raise ValueError("pilot argv cannot publish local absolute paths")
    executable = shutil.which(argv[0], path=agent_subprocess_env().get("PATH"))
    if executable is None:
        raise ValueError("pilot transport is not available on the agent PATH")
    raw = Path(executable).read_bytes()
    settings = {"wrapper_sha256": raw}
    if argv[0] == "thesis-core-codex":
        from . import codex_transport

        settings["wrapper_module_sha256"] = Path(codex_transport.__file__).read_bytes()
    return settings


def wrapper_artifacts(store, argv: tuple[str, ...]) -> dict[str, str]:
    """Pin a PATH-resolved executable without publishing a local argv path."""
    return {
        name: store.artifacts.put_bytes(raw)
        for name, raw in _wrapper_bytes(argv).items()
    }


def verify_wrapper(store, forecaster: ForecasterVersion, argv: tuple[str, ...]) -> None:
    """Verify the executable that PATH will select against frozen public bytes."""
    if forecaster.execution_policy == "baseline":
        return
    pinned = forecaster.inference_settings
    for name, raw in _wrapper_bytes(argv).items():
        digest = hashlib.sha256(raw).hexdigest()
        expected = pinned.get(name)
        if expected != digest:
            raise ValueError("pilot transport differs from its frozen wrapper")
        if hashlib.sha256(store.artifacts.read_bytes(expected)).hexdigest() != digest:
            raise ValueError("pilot wrapper artifact is corrupt")
