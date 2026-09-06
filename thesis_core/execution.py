"""One durable attempt: assemble, dispatch, seal.

`execute_forecast` is the whole bounded execution path for a single claimed
evaluation task. It refuses everything it cannot justify, commits the durable
attempt before any model process exists, and seals only what it actually
observed.

The order is load-bearing:

1. Load the exact stored task, target version, forecaster version and evidence
   bundle. Nothing is reconstructed from a claim payload.
2. Resolve `argv` against the *preregistered* forecaster settings. A caller may
   pass the same vector for readability; it may not substitute another one.
3. Assemble the full prompt from the exact artifact bytes the forecaster's
   hashes name, and store it as its own artifact. The assembled prompt is
   preserved separately from the template hash: the template is shared across
   tasks, the assembled prompt is what this attempt actually sent.
4. For prospective execution, verify the independent cohort proof by replaying
   the archived receipt through an injected verifier. A stored boolean is never
   accepted as verification.
5. `store.start_attempt` allocates the sequence, stamps database time and
   commits dispatch intent. Only after it returns may a process exist.
6. Run, heartbeating against database time. Losing the lease terminates the
   process and commits nothing: the outcome is unknown and recovery belongs to
   the store, never to an automatic second model invocation.
7. Redact, then hash, then seal. Redaction happens before content addressing so
   the sealed identity is the identity of clean bytes and no post-hoc scrub can
   break it.

What this module deliberately does not do: retry. A durable attempt is created
only through `store.start_attempt`, bounded solely by the task's
`max_attempts`; scheduling the next one is the caller's decision. It also never
re-runs generation to satisfy a failed publication — a sealed run is already
persisted and publication retries reuse its bytes.

Two forecaster execution policies exist:

``baseline``
    A deterministic persistence forecast computed in this process from the
    frozen evidence. No subprocess, no network, reproducible from the bundle
    alone. Its procedure version is part of the forecaster identity.

``operator_subprocess``
    An argv vector, never an interpolated shell command, run in a dedicated
    private working directory populated with the prompt and evidence files. It
    reads the prompt on stdin and writes exactly one JSON object on stdout.
    This policy proves nothing about isolation: see
    ``OPERATOR_SUBPROCESS_DISCLOSURE``, which is sealed into the command
    document so the claim travels with the record.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes
from .contracts import (
    Attempt,
    AttemptResult,
    CdfPoint,
    CdfSummary,
    CdfSupport,
    EvidenceBundle,
    ForecasterVersion,
    ForecastRun,
    NumericCdf,
    ObservationVintage,
    TargetVersion,
)
from .security import (
    AGENT_ENV_ALLOWLIST,
    RedactionError,
    agent_subprocess_env,
    redact_response_text,
    redact_text,
    redact_value,
)
from .store import Claim, JobSpec, LeaseLost, Store

logger = logging.getLogger(__name__)

__all__ = [
    "CDF_POINT_COUNT",
    "EXECUTION_PROTOCOL",
    "ExecutionError",
    "ExecutionRefused",
    # Re-exported: every caller of execute_forecast has to handle it.
    "LeaseLost",
    "OPERATOR_SUBPROCESS_DISCLOSURE",
    "PERSISTENCE_BASELINE_VERSION",
    "PROMPT_ASSEMBLY_VERSION",
    "build_prompt",
    "execute_forecast",
    "persistence_distribution",
]

CDF_POINT_COUNT = 201

#: Versioned deterministic prompt assembly. Changing the section order, the
#: labels or the serialization changes this token, because the assembled prompt
#: is a sealed input.
PROMPT_ASSEMBLY_VERSION = "thesis_core_prompt_v1"

#: The subprocess contract: the assembled prompt arrives on stdin, exactly one
#: JSON object leaves on stdout. Forecasters may pin it in
#: ``inference_settings["execution_protocol"]``.
EXECUTION_PROTOCOL = "stdin_prompt_stdout_json_v1"

#: The persistence baseline's procedure identity. A ``baseline`` forecaster
#: version must declare exactly this ``agent_version``, so the frozen
#: forecaster identity pins the procedure rather than merely labelling it.
PERSISTENCE_BASELINE_VERSION = "thesis_core.persistence_uniform_v1"

#: The distribution transform this baseline emits.
PERSISTENCE_TRANSFORM_VERSION = "persistence_uniform_v1"

#: Sealed into every operator_subprocess command document. The point is that
#: the record carries the limitation instead of a reader assuming otherwise.
OPERATOR_SUBPROCESS_DISCLOSURE = (
    "operator_subprocess runs an argv vector under an allowlisted environment "
    "in a private working directory. It does not prove filesystem or network "
    "isolation, and any retry performed inside the provider or its client is "
    "unobservable here: the internal retry count is not asserted."
)

# A uniform on [c-h, c+h] has its 80% interval at c +- 0.8h. Setting
# h = 2 * mean(|step|) puts that interval at +-1.6 mean absolute steps, which
# is the 80% interval of a normal random walk step (1.28 sigma, and a normal's
# mean absolute deviation is 0.798 sigma). The multiplier is part of
# PERSISTENCE_TRANSFORM_VERSION.
_PERSISTENCE_STEP_MULTIPLIER = 2.0

# A history with no movement cannot express its own uncertainty. Rather than
# emit a degenerate spike, the versioned fallback is one percent of the last
# value's magnitude, floored at one unit.
_DEGENERATE_HALF_WIDTH_FRACTION = 0.01

# Keeps the 201 knots strictly increasing when a real but tiny dispersion sits
# beneath float resolution at the level of the last value.
_NUMERIC_HALF_WIDTH_FRACTION = 1e-9

_STDIN_CHUNK = 1 << 16
_POLL_SECONDS = 0.05
_TERMINATE_GRACE_SECONDS = 2.0

# A valid response is a 201-point CDF: tens of kilobytes. This bound exists so
# a runaway forecaster fails its own attempt instead of exhausting the worker
# and turning an observable failure into an unknown outcome.
MAX_CAPTURED_BYTES = 8 << 20


class ExecutionError(Exception):
    """Base class for this module's refusals."""


class ExecutionRefused(ExecutionError):  # noqa: N818 - a refusal, not a fault
    """Execution cannot proceed under the registered contracts.

    Raised only before ``start_attempt``: a refusal never consumes one of the
    task's durable attempts.
    """


#: Verifies the independent cohort proof immediately before dispatch.
#:
#: Called as ``verify_cohort_proof(experiment_id=..., cohort_proof_id=...,
#: task_id=...)``. It must replay the archived RFC 3161 receipt bytes and
#: return the lowercase hex SHA-256 of the verified timestamp token, which is
#: committed to ``Attempt.cohort_token_hash`` before any process exists. Any
#: exception refuses dispatch. A stored boolean is never verification, so
#: returning a truthy flag instead of the token hash is a contract violation
#: this module rejects.
CohortProofVerifier = Callable[..., str]


# --- Persistence baseline ----------------------------------------------------


def persistence_distribution(observations: Iterable[Any]) -> NumericCdf:
    """Build the deterministic persistence CDF from frozen evidence.

    Pure: it reads only the observations handed to it, and identical inputs
    always produce identical bytes. The forecast is the latest measurement
    period's value, with a uniform spread derived from how much this series has
    historically moved between prints.

    Observations are ordered by ``(measurement_period, id)`` — the same order
    ``build_evidence_bundle`` freezes them in — so the caller cannot change the
    forecast by reordering its input. Measurement periods within one series
    share one format, which is why the lexicographic order is the chronological
    order.
    """
    ordered = sorted(
        observations,
        key=lambda item: (item.measurement_period, getattr(item, "id", "")),
    )
    if not ordered:
        raise ExecutionRefused("persistence baseline requires at least one observation")
    values = [float(item.value) for item in ordered]
    center = values[-1]
    if not _finite(center):
        raise ExecutionRefused("persistence baseline requires a finite latest value")

    steps = [abs(values[index] - values[index - 1]) for index in range(1, len(values))]
    magnitude = max(abs(center), 1.0)
    if steps and sum(steps) > 0:
        half_width = _PERSISTENCE_STEP_MULTIPLIER * (sum(steps) / len(steps))
    else:
        half_width = _DEGENERATE_HALF_WIDTH_FRACTION * magnitude
    half_width = max(half_width, _NUMERIC_HALF_WIDTH_FRACTION * magnitude)
    if not _finite(half_width) or half_width <= 0:
        raise ExecutionRefused("persistence baseline produced an unusable spread")

    last = CDF_POINT_COUNT - 1
    points = []
    for index in range(CDF_POINT_COUNT):
        probability = index / last
        points.append(
            CdfPoint(
                value=center + half_width * (2.0 * probability - 1.0),
                probability=probability,
            )
        )
    for index in range(1, CDF_POINT_COUNT):
        if points[index].value <= points[index - 1].value:
            raise ExecutionRefused(
                "persistence baseline spread is below float resolution at this level"
            )

    return NumericCdf(
        support=CdfSupport(lower=points[0].value, upper=points[-1].value),
        points=tuple(points),
        summary=CdfSummary(
            point_estimate=center,
            median=center,
            interval80=CdfSupport(
                lower=center - 0.8 * half_width, upper=center + 0.8 * half_width
            ),
        ),
        provenance="interval_seeded",
        transform_version=PERSISTENCE_TRANSFORM_VERSION,
    )


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


# --- Prompt assembly ---------------------------------------------------------


def build_prompt(
    *,
    task: Any,
    target: TargetVersion,
    forecaster: ForecasterVersion,
    bundle: EvidenceBundle,
    observations: Sequence[ObservationVintage],
    system: bytes,
    template: bytes,
    tool_policy: bytes,
    briefing: bytes | None = None,
    cohort_receipt: Mapping[str, str] | None = None,
) -> bytes:
    """Assemble the exact prompt bytes an attempt sends.

    Pure and deterministic: the same records and the same artifact bytes always
    produce the same document, so the assembled prompt hash is reproducible
    from the sealed dependencies alone. Record sections are canonical JSON, so
    they inherit the repository's one serialization; artifact sections are the
    stored bytes verbatim, decoded as UTF-8.

    ``cohort_receipt`` seals the verified independent receipt into the prompt
    for prospective execution, so the run's actual input commits to a value
    that could not exist before the cohort was witnessed.

    The prompt is deliberately not scrubbed. Every byte in it comes from a
    registered artifact or a validated record — and ForecasterVersion already
    refuses inference settings that redaction would change — so scrubbing here
    could only corrupt a legitimate instruction that happens to look like a
    credential, while changing what the model was actually asked.
    """
    sections: list[tuple[str, bytes]] = [
        ("assembly", PROMPT_ASSEMBLY_VERSION.encode("utf-8")),
        ("system", system),
    ]
    if briefing is not None:
        sections.append(("briefing", briefing))
    sections.extend(
        [
            ("template", template),
            ("tool_policy", tool_policy),
            ("task", canonical_bytes(task.canonical_payload())),
            ("target_version", canonical_bytes(target.canonical_payload())),
            ("forecaster_version", canonical_bytes(forecaster.canonical_payload())),
            ("evidence_bundle", canonical_bytes(bundle.canonical_payload())),
            (
                "observations",
                canonical_bytes([item.canonical_payload() for item in observations]),
            ),
        ]
    )
    if cohort_receipt is not None:
        # The independently witnessed receipt is unpredictable before the
        # cohort was witnessed, so sealing it into the prompt makes it part of
        # the execution input rather than a claim attached afterwards.
        sections.append(("cohort_receipt", canonical_bytes(dict(cohort_receipt))))
    rendered = [
        f"===== thesis_core prompt section: {name} =====\n"
        + body.decode("utf-8", errors="replace")
        for name, body in sections
    ]
    return ("\n\n".join(rendered) + "\n").encode("utf-8")


# --- Execution ---------------------------------------------------------------


def execute_forecast(
    store: Store,
    claim: Claim,
    *,
    argv: Sequence[str] | None = None,
    timeout_seconds: float = 120,
    lease_seconds: float = 60,
    verify_cohort_proof: CohortProofVerifier | None = None,
    followups: Sequence[JobSpec] | Callable[[ForecastRun], Sequence[JobSpec]] = (),
    work_root: str | os.PathLike[str] | None = None,
) -> ForecastRun | None:
    """Run one durable attempt for the claimed evaluation task.

    ``claim.subject_id`` is the ``EvaluationTask`` ID; every other input is read
    from the store at that ID rather than trusted from the claim payload.

    Returns the sealed :class:`ForecastRun` on success, committed atomically
    with its :class:`AttemptResult` and any ``followups``. Returns ``None`` when
    the attempt failed in a way this worker actually observed — a spawn error, a
    timeout, a nonzero exit, output past ``MAX_CAPTURED_BYTES``, or output that
    is not one valid forecast — after committing a failed result with its trace
    artifacts under a valid lease. Those cases stay distinguishable in the
    record without a free-text reason: a spawn failure has no exit code and its
    stderr artifact carries the runtime's own message, a killed process has a
    negative exit code, and an unparseable response exits zero with no run.

    Raises :class:`ExecutionRefused` before any attempt exists when the
    registered contracts do not permit the run, and :class:`LeaseLost` when
    ownership is gone. Lease loss commits nothing: the outcome is unknown,
    recovery is the store's, and this module never re-invokes the model.

    ``verify_cohort_proof`` is required for prospective tasks and is called
    immediately before ``start_attempt``; see :data:`CohortProofVerifier`.

    ``followups`` are enqueued in the same transaction as a successful result,
    so publication cannot be lost between sealing and scheduling. Pass a
    callable to derive them from the sealed run — a publication job's subject
    is the run, which does not exist until the run is sealed. A failed attempt
    schedules nothing: there is no forecast to publish, and a failed
    publication must never re-run generation.
    """
    task_id = claim.subject_id
    task = store.get(task_id)
    if task.kind != "evaluation_task":
        raise ExecutionRefused(f"claim subject {task_id} is not an evaluation task")
    target = store.get(task.target_version_id)
    forecaster = store.get(task.forecaster_version_id)
    bundle = store.get(task.evidence_bundle_id)
    if task.execution_policy != forecaster.execution_policy:
        raise ExecutionRefused(
            "task and forecaster disagree about the execution policy: "
            f"{task.execution_policy} vs {forecaster.execution_policy}"
        )
    if bundle.information_cutoff != task.information_cutoff:
        raise ExecutionRefused("evidence bundle was frozen for another cutoff")

    policy = forecaster.execution_policy
    resolved_argv = _resolve_argv(forecaster, argv)
    observations = [store.get(identity) for identity in bundle.observation_ids]
    cohort_proof_id, cohort_token_hash = _cohort_binding(
        task, claim, verify_cohort_proof
    )
    pilot = task.mode == "live_pilot"
    experiment_id = (claim.payload or {}).get("experiment_id")
    if pilot:
        from .live import (
            PILOT_DEADLINE_BEFORE_SPAWN,
            PilotDeadlineError,
            validate_live_dispatch,
            verify_wrapper,
        )

        validate_live_dispatch(store, task, experiment_id)
        verify_wrapper(store, forecaster, resolved_argv)

    prompt = build_prompt(
        task=task,
        target=target,
        forecaster=forecaster,
        bundle=bundle,
        observations=observations,
        system=store.artifacts.read_bytes(forecaster.system_prompt_hash),
        template=store.artifacts.read_bytes(forecaster.prompt_template_hash),
        tool_policy=store.artifacts.read_bytes(forecaster.tool_policy_hash),
        briefing=(
            None
            if forecaster.briefing_hash is None
            else store.artifacts.read_bytes(forecaster.briefing_hash)
        ),
        cohort_receipt=(
            None
            if cohort_proof_id is None
            else {"proof_id": cohort_proof_id, "token_hash": cohort_token_hash}
        ),
    )
    prompt_hash = store.artifacts.put_bytes(prompt)
    code_hash = _code_identity(store)
    if pilot:
        sampled = _database_now(store)
        boundary = validate_live_dispatch(store, task, experiment_id, now=sampled)
        # Leave one second for allocation/spawn and eventual sealing. The actual
        # budget is fixed before hashing; later checks may refuse, never alter it.
        timeout_seconds = min(timeout_seconds, (boundary - sampled).total_seconds() - 1)
        if timeout_seconds <= 0:
            raise PilotDeadlineError(PILOT_DEADLINE_BEFORE_SPAWN)
    command_hash = store.artifacts.put_bytes(
        canonical_bytes(_command_document(policy, resolved_argv, timeout_seconds))
    )
    pilot_deadline_failed = False

    def allocate(sequence, now):
        nonlocal pilot_deadline_failed
        if pilot:
            try:
                validate_live_dispatch(
                    store,
                    task,
                    experiment_id,
                    now=now,
                    budget_seconds=timeout_seconds,
                )
            except PilotDeadlineError:
                pilot_deadline_failed = True
        return Attempt(
            task_id=task_id,
            code_hash=code_hash,
            sequence=sequence,
            started_at=now,
            command_hash=command_hash,
            prompt_hash=prompt_hash,
            execution_policy=policy,
            cohort_proof_id=cohort_proof_id,
            cohort_token_hash=cohort_token_hash,
        )

    attempt = store.start_attempt(
        claim,
        task_id,
        allocate,
    )

    def before_spawn():
        if not pilot:
            return True
        if pilot_deadline_failed:
            return False
        try:
            validate_live_dispatch(
                store,
                task,
                experiment_id,
                budget_seconds=timeout_seconds,
            )
        except PilotDeadlineError:
            return False
        verify_wrapper(store, forecaster, resolved_argv)
        return True

    # From here a durable attempt exists. Every exit below either commits a
    # terminal result under a valid lease or leaves the outcome unknown.
    if pilot_deadline_failed:
        completed = _pilot_deadline_failure()
    elif policy == "baseline":
        if not before_spawn():
            completed = _pilot_deadline_failure()
        else:
            completed = _run_baseline(observations)
    else:
        completed = _run_subprocess(
            store,
            claim,
            resolved_argv,
            prompt,
            observations=observations,
            task=task,
            target=target,
            bundle=bundle,
            timeout_seconds=timeout_seconds,
            lease_seconds=lease_seconds,
            work_root=work_root,
            before_spawn=before_spawn if pilot else None,
        )

    stdout_hash = store.artifacts.put_bytes(completed.stdout.encode("utf-8"))
    stderr_hash = store.artifacts.put_bytes(completed.stderr.encode("utf-8"))
    raw_response_hash = store.artifacts.put_bytes(
        completed.raw_response.encode("utf-8")
    )
    now = _database_now(store)

    if completed.failure is not None:
        logger.warning(
            "attempt %s failed: %s (exit_code=%s)",
            attempt.id,
            completed.failure,
            completed.exit_code,
        )
        store.finish(
            claim,
            outcome="failed",
            records=(
                AttemptResult(
                    attempt_id=attempt.id,
                    outcome="failed",
                    recorded_at=now,
                    completed_at=now,
                    exit_code=completed.exit_code,
                    stdout_hash=stdout_hash,
                    stderr_hash=stderr_hash,
                    raw_response_hash=raw_response_hash,
                ),
            ),
        )
        return None

    run = ForecastRun(
        attempt_id=attempt.id,
        distribution=completed.distribution,
        stdout_hash=stdout_hash,
        stderr_hash=stderr_hash,
        raw_response_hash=raw_response_hash,
        completed_at=now,
        observed_model=completed.observed_model,
        execution_policy=policy,
        prompt_hash=prompt_hash,
    )
    store.finish(
        claim,
        outcome="succeeded",
        records=(
            run,
            AttemptResult(
                attempt_id=attempt.id,
                outcome="succeeded",
                recorded_at=now,
                completed_at=now,
                exit_code=completed.exit_code,
                stdout_hash=stdout_hash,
                stderr_hash=stderr_hash,
                raw_response_hash=raw_response_hash,
                run_id=run.id,
            ),
        ),
        followups=followups(run) if callable(followups) else followups,
    )
    return run


class _Completed:
    """What a transport actually produced, already redacted."""

    __slots__ = (
        "distribution",
        "exit_code",
        "failure",
        "observed_model",
        "raw_response",
        "stderr",
        "stdout",
    )

    def __init__(
        self,
        *,
        stdout: str,
        stderr: str,
        raw_response: str,
        exit_code: int | None,
        distribution: NumericCdf | None = None,
        observed_model: str | None = None,
        failure: str | None = None,
    ):
        self.stdout = stdout
        self.stderr = stderr
        self.raw_response = raw_response
        self.exit_code = exit_code
        self.distribution = distribution
        self.observed_model = observed_model
        self.failure = failure


def _pilot_deadline_failure() -> _Completed:
    from .live import PILOT_DEADLINE_BEFORE_SPAWN

    return _Completed(
        stdout="",
        stderr=PILOT_DEADLINE_BEFORE_SPAWN + "\n",
        raw_response="",
        exit_code=None,
        failure="pilot_deadline_before_spawn",
    )


def _run_baseline(observations: Sequence[ObservationVintage]) -> _Completed:
    """The baseline emits the same response document a subprocess would.

    Going through the wire format keeps one artifact trail for both transports,
    and proves the baseline's own output satisfies the response contract.
    """
    distribution = persistence_distribution(observations)
    document = json.dumps(
        {
            "distribution": distribution.model_dump(mode="json", by_alias=True),
            # The executing program is directly observed here, not inferred
            # from a requested model name: there is no provider to ask.
            "observed_model": PERSISTENCE_BASELINE_VERSION,
        },
        indent=2,
        sort_keys=True,
    )
    parsed, observed_model, failure = _parse_response(document)
    return _Completed(
        stdout=document,
        stderr="",
        raw_response=document,
        exit_code=0,
        distribution=parsed,
        observed_model=observed_model,
        failure=failure,
    )


def _run_subprocess(
    store: Store,
    claim: Claim,
    argv: tuple[str, ...],
    prompt: bytes,
    *,
    observations: Sequence[ObservationVintage],
    task: Any,
    target: TargetVersion,
    bundle: EvidenceBundle,
    timeout_seconds: float,
    lease_seconds: float,
    work_root: str | os.PathLike[str] | None,
    before_spawn: Callable[[], bool] | None = None,
) -> _Completed:
    directory = Path(
        tempfile.mkdtemp(prefix="thesis-core-attempt-", dir=work_root)
    ).resolve()
    try:
        _populate_working_directory(
            directory,
            prompt,
            observations=observations,
            task=task,
            target=target,
            bundle=bundle,
        )
        return _spawn_and_wait(
            store,
            claim,
            argv,
            prompt,
            directory=directory,
            timeout_seconds=timeout_seconds,
            lease_seconds=lease_seconds,
            before_spawn=before_spawn,
        )
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _populate_working_directory(
    directory: Path,
    prompt: bytes,
    *,
    observations: Sequence[ObservationVintage],
    task: Any,
    target: TargetVersion,
    bundle: EvidenceBundle,
) -> None:
    (directory / "prompt.txt").write_bytes(prompt)
    evidence = directory / "evidence"
    evidence.mkdir(mode=0o700)
    for name, payload in (
        ("task.json", task.canonical_payload()),
        ("target_version.json", target.canonical_payload()),
        ("evidence_bundle.json", bundle.canonical_payload()),
        ("observations.json", [item.canonical_payload() for item in observations]),
    ):
        (evidence / name).write_bytes(canonical_bytes(payload))


def _spawn_and_wait(
    store: Store,
    claim: Claim,
    argv: tuple[str, ...],
    prompt: bytes,
    *,
    directory: Path,
    timeout_seconds: float,
    lease_seconds: float,
    before_spawn: Callable[[], bool] | None = None,
) -> _Completed:
    environment = agent_subprocess_env({"TMPDIR": str(directory)})
    # Re-fence against database time immediately before the process exists, so
    # the window between committing the attempt and starting the model is as
    # small as this worker can make it.
    store.heartbeat(claim, lease_seconds=lease_seconds)
    if before_spawn is not None and not before_spawn():
        return _pilot_deadline_failure()
    try:
        process = subprocess.Popen(  # noqa: S603 - argv vector, never a shell
            list(argv),
            cwd=str(directory),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        # No process ran, so nothing else claims the stderr channel: the
        # execution runtime's own message is the attempt's error output.
        message = redact_text(f"thesis_core.execution: spawn failed: {exc}\n")
        return _Completed(
            stdout="",
            stderr=message,
            raw_response="",
            exit_code=None,
            failure="spawn_failed",
        )

    stdout = bytearray()
    stderr = bytearray()
    overflowed = threading.Event()
    workers = [
        threading.Thread(target=_feed, args=(process.stdin, prompt), daemon=True),
        threading.Thread(
            target=_drain, args=(process.stdout, stdout, overflowed), daemon=True
        ),
        threading.Thread(
            target=_drain, args=(process.stderr, stderr, overflowed), daemon=True
        ),
    ]
    for worker in workers:
        worker.start()

    started = time.monotonic()
    last_heartbeat = started
    heartbeat_every = max(_POLL_SECONDS, lease_seconds / 3.0)
    failure: str | None = None
    try:
        while True:
            try:
                process.wait(timeout=_POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                pass
            elapsed = time.monotonic() - started
            if elapsed >= timeout_seconds:
                failure = "timeout"
                _terminate(process)
                break
            if overflowed.is_set():
                failure = "output_too_large"
                _terminate(process)
                break
            if time.monotonic() - last_heartbeat >= heartbeat_every:
                # Database time decides ownership. A worker whose lease has
                # already been recovered must not keep a model running.
                store.heartbeat(claim, lease_seconds=lease_seconds)
                last_heartbeat = time.monotonic()
    except BaseException:
        # LeaseLost is the expected one — ownership moved on, so this worker
        # must stop the model rather than let it finish into a lost lease. Any
        # other interruption gets the same treatment: never orphan a process.
        _terminate(process)
        for worker in workers:
            worker.join(timeout=_TERMINATE_GRACE_SECONDS)
        raise

    for worker in workers:
        worker.join(timeout=_TERMINATE_GRACE_SECONDS)

    # Redact before anything is hashed or content-addressed. An observed child
    # exit followed by unsafe JSON is a known failed response, not a transport
    # uncertainty. Preserve unaffected streams and an explicit omission marker;
    # never downgrade failed structural redaction to a plain-text scrub.
    redaction_failed = False

    def captured_text(data: bytearray, channel: str) -> str:
        nonlocal redaction_failed
        try:
            return redact_response_text(data.decode("utf-8", errors="replace"))
        except RedactionError:
            redaction_failed = True
            return json.dumps(
                {
                    "redactionFailure": "unsafe_json",
                    "channel": channel,
                    "capturedBytes": len(data),
                    "detail": "Content withheld: safe redaction was unavailable.",
                }
            )

    stdout_text = captured_text(stdout, "stdout")
    stderr_text = captured_text(stderr, "stderr")
    raw_response = stdout_text
    exit_code = process.returncode

    if failure is None and redaction_failed:
        failure = "invalid_response_unredactable"
    if failure is None and overflowed.is_set():
        failure = "output_too_large"
    if failure is None and exit_code != 0:
        failure = "nonzero_exit"
    distribution = None
    observed_model = None
    if failure is None:
        # Parse the redacted bytes, never the raw ones: the sealed forecast and
        # the sealed stdout artifact must be the same document.
        distribution, observed_model, failure = _parse_response(raw_response)
    return _Completed(
        stdout=stdout_text,
        stderr=stderr_text,
        raw_response=raw_response,
        exit_code=exit_code,
        distribution=distribution,
        observed_model=observed_model,
        failure=failure,
    )


def _feed(stream: Any, data: bytes) -> None:
    try:
        for start in range(0, len(data), _STDIN_CHUNK):
            stream.write(data[start : start + _STDIN_CHUNK])
        stream.flush()
    except (BrokenPipeError, ValueError, OSError):
        # A forecaster is allowed to stop reading its prompt early.
        pass
    finally:
        try:
            stream.close()
        except (BrokenPipeError, OSError):
            pass


def _drain(stream: Any, sink: bytearray, overflowed: threading.Event) -> None:
    """Capture a stream up to MAX_CAPTURED_BYTES, then stop and say so."""
    try:
        while True:
            chunk = stream.read(_STDIN_CHUNK)
            if not chunk:
                return
            if len(sink) + len(chunk) > MAX_CAPTURED_BYTES:
                sink.extend(chunk[: MAX_CAPTURED_BYTES - len(sink)])
                overflowed.set()
                return
            sink.extend(chunk)
    except (ValueError, OSError):
        return
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """Stop the whole process group; a forecaster may have spawned children."""
    escalation = ((signal.SIGTERM, _TERMINATE_GRACE_SECONDS), (signal.SIGKILL, 5.0))
    for sig, wait in escalation:
        if process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except OSError:
                return
        try:
            process.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant: {name}")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_response(text: str) -> tuple[NumericCdf | None, str | None, str | None]:
    """Validate the one strict JSON object a forecaster is allowed to emit.

    Strict means strict: NaN/Infinity literals and duplicate object keys are
    refused rather than silently resolved, so the sealed forecast cannot depend
    on which JSON dialect read it.
    """
    try:
        payload = json.loads(
            text, parse_constant=_reject_constant, object_pairs_hook=_unique_keys
        )
    except (json.JSONDecodeError, ValueError, RecursionError):
        return None, None, "invalid_response_not_json"
    if not isinstance(payload, dict):
        return None, None, "invalid_response_not_an_object"
    unknown = set(payload) - {"distribution", "observed_model", "observedModel"}
    if unknown:
        return None, None, f"invalid_response_unknown_keys:{','.join(sorted(unknown))}"
    if "distribution" not in payload:
        return None, None, "invalid_response_missing_distribution"
    observed = payload.get("observed_model", payload.get("observedModel"))
    if observed is not None and (not isinstance(observed, str) or not observed.strip()):
        return None, None, "invalid_response_observed_model"
    try:
        # Validated from JSON text, the same way parse_record validates a
        # record: strict dict validation would reject the array-for-tuple
        # shape that is the only JSON representation of the 201 points.
        distribution = NumericCdf.model_validate_json(
            json.dumps(payload["distribution"]), strict=True
        )
    except Exception as exc:  # pydantic ValidationError and friends
        return None, None, f"invalid_response_distribution:{type(exc).__name__}"
    return distribution, observed, None


# --- Registered-contract checks ----------------------------------------------


def _resolve_argv(
    forecaster: ForecasterVersion, argv: Sequence[str] | None
) -> tuple[str, ...]:
    """Take the argv vector from the frozen forecaster, never from the caller.

    A caller may repeat the registered vector; it may not substitute one. An
    empty vector means the deterministic persistence baseline, and only a
    ``baseline`` forecaster may have one.
    """
    supplied = None if argv is None else tuple(str(item) for item in argv)
    declared = forecaster.inference_settings.get("argv")
    if declared is not None:
        if (
            not isinstance(declared, list)
            or not declared
            or not all(isinstance(item, str) and item for item in declared)
        ):
            raise ExecutionRefused(
                "inference_settings['argv'] must be a non-empty list of strings"
            )
        declared = tuple(declared)

    if forecaster.execution_policy == "baseline":
        # The procedure has to be part of the frozen identity, not a label
        # applied at run time; either identity field may carry it.
        pinned = {
            forecaster.agent_version,
            forecaster.inference_settings.get("baseline_version"),
        }
        if PERSISTENCE_BASELINE_VERSION not in pinned:
            raise ExecutionRefused(
                "a baseline forecaster must pin the procedure as "
                f"{PERSISTENCE_BASELINE_VERSION!r} in agent_version or "
                "inference_settings['baseline_version']"
            )
        if declared:
            raise ExecutionRefused("a baseline forecaster cannot register an argv")
        if supplied:
            raise ExecutionRefused(
                "the persistence baseline runs no command; argv cannot be supplied"
            )
        return ()

    if not declared:
        raise ExecutionRefused(
            "operator_subprocess requires a preregistered "
            "inference_settings['argv']; runtime argv is never authoritative"
        )
    if supplied is not None and supplied != declared:
        raise ExecutionRefused(
            "supplied argv does not match the preregistered forecaster settings"
        )
    protocol = forecaster.inference_settings.get("execution_protocol")
    if protocol is not None and protocol != EXECUTION_PROTOCOL:
        raise ExecutionRefused(
            f"forecaster declares execution protocol {protocol!r}, "
            f"but this transport implements {EXECUTION_PROTOCOL!r}"
        )
    return declared


def _command_document(
    policy: str, argv: tuple[str, ...], timeout_seconds: float
) -> dict[str, Any]:
    """The hashed description of what this attempt runs.

    It holds no absolute paths, so the same registered command produces the
    same ``command_hash`` on every host and the baseline stays reproducible.
    Redaction runs before hashing, so a credential that reached an argv is
    absent from the content address rather than sealed into it.
    """
    return redact_value(
        {
            "assemblyVersion": PROMPT_ASSEMBLY_VERSION,
            "disclosure": OPERATOR_SUBPROCESS_DISCLOSURE if argv else None,
            "environmentAllowlist": list(AGENT_ENV_ALLOWLIST),
            "evidenceFiles": [
                "evidence/evidence_bundle.json",
                "evidence/observations.json",
                "evidence/target_version.json",
                "evidence/task.json",
            ],
            "executionPolicy": policy,
            "argv": list(argv),
            "promptDelivery": "stdin",
            "promptFile": "prompt.txt",
            "protocol": EXECUTION_PROTOCOL if argv else PERSISTENCE_BASELINE_VERSION,
            "shell": False,
            "timeoutSeconds": float(timeout_seconds),
        }
    )


def _cohort_binding(
    task: Any, claim: Claim, verify_cohort_proof: CohortProofVerifier | None
) -> tuple[str | None, str | None]:
    """Verify the independent cohort receipt before any process exists.

    Prospective execution requires it. Replay may omit it and stays replay; a
    replay claim that does name a proof still has to verify, because a proof
    that cannot be replayed is evidence of a problem either way.
    """
    payload = claim.payload or {}
    experiment_id = payload.get("experiment_id")
    cohort_proof_id = payload.get("cohort_proof_id")
    prospective = task.mode == "prospective"
    if task.mode == "live_pilot" and cohort_proof_id is not None:
        raise ExecutionRefused("live pilot cannot dispatch with a cohort proof")
    if not cohort_proof_id:
        if prospective:
            raise ExecutionRefused(
                "prospective dispatch requires an independently witnessed cohort "
                "proof in the claim payload"
            )
        return None, None
    if not experiment_id:
        raise ExecutionRefused("a cohort proof reference requires its experiment ID")
    if verify_cohort_proof is None:
        raise ExecutionRefused(
            "a cohort proof cannot be accepted without a verifier that replays "
            "its receipt bytes"
        )
    try:
        token_hash = verify_cohort_proof(
            experiment_id=str(experiment_id),
            cohort_proof_id=str(cohort_proof_id),
            task_id=str(claim.subject_id),
        )
    except Exception as exc:
        # A receipt that will not replay is not a dispatch condition that can
        # be waived; it refuses here, before an attempt exists.
        raise ExecutionRefused(f"cohort proof verification failed: {exc}") from exc
    if not isinstance(token_hash, str) or len(token_hash) != 64:
        raise ExecutionRefused(
            "cohort verification must return the verified token's SHA-256 hex "
            "digest; a boolean is never verification"
        )
    return str(cohort_proof_id), token_hash


def _code_identity(store: Store) -> str:
    """Archive the executing core source and return its content identity.

    Imported here rather than at module scope: publication reads sealed runs,
    so a module-level import would close the cycle.
    """
    from .publication import archive_code

    return archive_code(store)


def _database_now(store: Store) -> datetime:
    """Sample the database clock; a worker's own clock is never authoritative."""
    with store.connection() as connection:
        return connection.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
