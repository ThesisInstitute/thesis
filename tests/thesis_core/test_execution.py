"""The bounded execution path, against real subprocesses and real PostgreSQL.

Nothing here simulates a forecaster: every operator_subprocess case spawns an
actual process that reads the assembled prompt on stdin, reads the frozen
evidence out of its working directory, and writes its own JSON. Nothing here
simulates the database either — leases, fencing and attempt sequences are the
store's real ones, on the `core_store` fixture.

The properties worth breaking are the ones a plausible-looking implementation
gets wrong: that no model process can exist before the durable attempt commits,
that a lost lease terminates the process and invokes nothing a second time,
that a runtime argv cannot displace the preregistered one, and that a
credential is gone before bytes are content-addressed rather than after.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.thesis_core.factories import at, make_forecaster, make_graph
from thesis_core import execution
from thesis_core.contracts import EvaluationTask, Experiment, NumericCdf
from thesis_core.security import is_credential_key
from thesis_core.store import AttemptBlocked, JobSpec, LeaseLost

PLANTED_ENV_SECRET = "planted-parent-" + "credential-2026-09-04"
PLANTED_STDOUT_SECRET = "sk-ant-" + "planted-execution-stdout"


# --- Pure surface: the persistence baseline ----------------------------------


class _Observation:
    """The two attributes persistence_distribution is allowed to read."""

    def __init__(self, period: str, value: float, identity: str = ""):
        self.measurement_period = period
        self.value = value
        self.id = identity


def test_persistence_forecasts_the_last_value_with_a_historical_spread():
    distribution = execution.persistence_distribution(
        [
            _Observation("2025-10", 10.0),
            _Observation("2025-11", 13.0),
            _Observation("2025-12", 11.0),
        ]
    )
    # Steps are 3.0 and 2.0, so the mean absolute step is 2.5 and the versioned
    # half-width is twice that.
    assert distribution.summary.point_estimate == 11.0
    assert distribution.summary.median == 11.0
    assert distribution.support.lower == pytest.approx(6.0)
    assert distribution.support.upper == pytest.approx(16.0)
    assert distribution.summary.interval80.lower == pytest.approx(7.0)
    assert distribution.summary.interval80.upper == pytest.approx(15.0)
    assert distribution.transform_version == execution.PERSISTENCE_TRANSFORM_VERSION
    assert len(distribution.points) == execution.CDF_POINT_COUNT == 201
    assert distribution.points[0].probability == 0.0
    assert distribution.points[-1].probability == 1.0
    assert distribution.points[100].value == pytest.approx(11.0)


def test_persistence_serializes_through_the_native_camel_case_contract():
    distribution = execution.persistence_distribution(
        [_Observation("2025-10", 4.0), _Observation("2025-11", 5.0)]
    )
    payload = distribution.model_dump(mode="json", by_alias=True)
    assert payload["format"] == "numeric_cdf_v1"
    assert payload["pointCount"] == 201
    assert payload["transformVersion"] == execution.PERSISTENCE_TRANSFORM_VERSION
    assert set(payload["summary"]) == {"pointEstimate", "median", "interval80"}
    # The native model accepts its own wire bytes back.
    assert NumericCdf.model_validate_json(json.dumps(payload), strict=True) == (
        distribution
    )


def test_persistence_is_reproducible_and_indifferent_to_input_order():
    observations = [
        _Observation("2025-10", 10.0, "c"),
        _Observation("2025-11", 13.0, "a"),
        _Observation("2025-12", 11.0, "b"),
    ]
    first = execution.persistence_distribution(observations)
    assert first == execution.persistence_distribution(list(reversed(observations)))
    assert first == execution.persistence_distribution(list(observations))


def test_persistence_falls_back_deterministically_without_variance():
    flat = execution.persistence_distribution(
        [_Observation("2025-10", 5.0), _Observation("2025-11", 5.0)]
    )
    # One percent of max(|last|, 1) rather than a degenerate spike.
    assert flat.summary.point_estimate == 5.0
    assert flat.support.upper - flat.support.lower == pytest.approx(0.1)

    single = execution.persistence_distribution([_Observation("2026-01", 0.0)])
    assert single.summary.point_estimate == 0.0
    assert single.support.lower == pytest.approx(-0.01)
    assert single.support.upper == pytest.approx(0.01)

    # Every fallback still has to satisfy the native distribution contract.
    for distribution in (flat, single):
        assert len(distribution.points) == 201
        values = [point.value for point in distribution.points]
        assert all(b > a for a, b in zip(values, values[1:]))


def test_persistence_keeps_its_knots_apart_at_a_large_level():
    """A real but tiny dispersion beneath float resolution must not collapse."""
    distribution = execution.persistence_distribution(
        [_Observation("2025-10", 1e9), _Observation("2025-11", 1e9 + 1e-6)]
    )
    values = [point.value for point in distribution.points]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_persistence_refuses_empty_evidence():
    with pytest.raises(execution.ExecutionRefused):
        execution.persistence_distribution([])


# --- Pure surface: prompt assembly and the response contract ------------------


def _prompt_parts(graph):
    return dict(
        task=graph.task,
        target=graph.target,
        forecaster=graph.forecaster,
        bundle=graph.evidence,
        observations=[graph.records[i] for i in graph.evidence.observation_ids],
        system=b"SYSTEM BYTES",
        template=b"TEMPLATE BYTES",
        tool_policy=b"TOOL POLICY BYTES",
    )


def test_build_prompt_is_deterministic_and_carries_every_declared_input():
    graph = make_graph()
    parts = _prompt_parts(graph)
    prompt = execution.build_prompt(**parts)
    assert prompt == execution.build_prompt(**parts)

    text = prompt.decode()
    assert execution.PROMPT_ASSEMBLY_VERSION in text
    for marker in ("SYSTEM BYTES", "TEMPLATE BYTES", "TOOL POLICY BYTES"):
        assert marker in text
    for section in ("task", "target_version", "evidence_bundle", "observations"):
        assert f"prompt section: {section}" in text
    # The frozen evidence values reach the forecaster.
    assert '"value":10' in text and '"value":13' in text and '"value":11' in text
    assert graph.target.target_id in text


def test_build_prompt_changes_when_any_declared_input_changes():
    graph = make_graph()
    parts = _prompt_parts(graph)
    baseline = execution.build_prompt(**parts)
    assert execution.build_prompt(**parts | {"briefing": b"EXTRA"}) != baseline
    assert execution.build_prompt(**parts | {"system": b"OTHER"}) != baseline
    assert (
        execution.build_prompt(**parts | {"observations": parts["observations"][:2]})
        != baseline
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("not json at all", "invalid_response_not_json"),
        ("[1, 2]", "invalid_response_not_an_object"),
        ('{"distribution": NaN}', "invalid_response_not_json"),
        ('{"distribution": 1, "distribution": 2}', "invalid_response_not_json"),
        ('{"observed_model": "m"}', "invalid_response_missing_distribution"),
        ('{"distribution": 1, "sneaky": 2}', "invalid_response_unknown_keys:sneaky"),
        ('{"distribution": 1, "observed_model": 7}', "invalid_response_observed_model"),
        ('{"distribution": {"format": "x"}}', "invalid_response_distribution"),
    ],
)
def test_response_contract_refuses_everything_but_one_valid_forecast(text, expected):
    distribution, observed, failure = execution._parse_response(text)
    assert distribution is None and observed is None
    assert failure.startswith(expected)


# --- Store-backed helpers -----------------------------------------------------


def seed(store, graph):
    for payload in graph.artifacts.values():
        store.artifacts.put_bytes(payload)
    for record in graph.records.values():
        store.put(record)


def claim_task(store, task_id, *, payload=None, lease_seconds=60, worker="worker-1"):
    store.enqueue("forecast", task_id, payload or {}, idempotency_key=uuid.uuid4().hex)
    store.deliver_outbox()
    claim = store.claim(worker, ["forecast"], lease_seconds=lease_seconds)
    assert claim is not None and claim.subject_id == task_id
    return claim


def job_row(store, job_id):
    with store.connection() as connection:
        return connection.execute(
            "SELECT * FROM jobs WHERE id=%s", (job_id,)
        ).fetchone()


def attempts_for(store, task_id):
    with store.connection() as connection:
        return connection.execute(
            "SELECT * FROM attempt_allocations WHERE task_id=%s ORDER BY sequence",
            (task_id,),
        ).fetchall()


def add_task(graph, forecaster, *, policy, mode="replay", max_attempts=1):
    return graph.add(
        EvaluationTask(
            target_version_id=graph.target.id,
            forecaster_version_id=forecaster.id,
            evidence_bundle_id=graph.evidence.id,
            information_cutoff=at(100),
            submission_deadline=at(1000),
            max_attempts=max_attempts,
            execution_policy=policy,
            mode=mode,
        )
    )


def baseline_forecaster(graph, **overrides):
    return graph.add(
        make_forecaster(
            baseline=True,
            agent_version=execution.PERSISTENCE_BASELINE_VERSION,
            **overrides,
        )
    )


def subprocess_forecaster(graph, script, *args, **overrides):
    settings = {"argv": [sys.executable, str(script), *[str(a) for a in args]]}
    settings.update(overrides.pop("inference_settings", {}))
    return graph.add(make_forecaster(inference_settings=settings, **overrides))


def write_script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body))
    return path


#: A real forecaster: it reads the prompt on stdin, reads the frozen evidence
#: out of its working directory, and derives its own 201-point CDF from the
#: values it was actually given.
EVIDENCE_FORECASTER = """
import json, os, pathlib, sys

prompt = sys.stdin.read()
outdir = pathlib.Path(sys.argv[1])
outdir.mkdir(parents=True, exist_ok=True)
(outdir / "prompt-seen.txt").write_text(prompt)
(outdir / "environment.json").write_text(json.dumps(dict(os.environ)))
(outdir / "cwd.txt").write_text(os.getcwd())

observations = json.loads(pathlib.Path("evidence/observations.json").read_text())
values = [item["value"] for item in observations]
center = values[-1] + 1.0
half = 2.0
points = [
    {"value": center + half * (2.0 * i / 200 - 1.0), "probability": i / 200}
    for i in range(201)
]
response = {
    "distribution": {
        "format": "numeric_cdf_v1",
        "pointCount": 201,
        "support": {"lower": points[0]["value"], "upper": points[-1]["value"]},
        "points": points,
        "summary": {
            "pointEstimate": center,
            "median": center,
            "interval80": {"lower": center - 1.6, "upper": center + 1.6},
        },
        "provenance": "agent_reported",
        "transformVersion": "fixture_forecaster_v1",
    }
}
if len(sys.argv) > 2 and sys.argv[2] == "declare-model":
    response["observed_model"] = "fixture-model-actually-served-9"
sys.stdout.write(json.dumps(response))
"""


# --- Baseline execution -------------------------------------------------------


def test_baseline_seals_a_reproducible_run_from_frozen_evidence(core_store):
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="baseline")
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    run = execution.execute_forecast(core_store, claim)

    assert run is not None
    observations = [graph.records[i] for i in graph.evidence.observation_ids]
    assert run.distribution == execution.persistence_distribution(observations)
    assert run.execution_policy == "baseline"
    assert run.observed_model == execution.PERSISTENCE_BASELINE_VERSION

    attempt = core_store.get(run.attempt_id)
    assert attempt.sequence == 1
    assert attempt.task_id == task.id
    assert attempt.prompt_hash == run.prompt_hash
    assert attempt.cohort_proof_id is None
    # Every sealed hash resolves to bytes that verify on read.
    for digest in (
        run.prompt_hash,
        run.stdout_hash,
        run.raw_response_hash,
        attempt.command_hash,
    ):
        assert core_store.artifacts.read_bytes(digest)
    assert core_store.artifacts.read_bytes(run.stderr_hash) == b""
    sealed = json.loads(core_store.artifacts.read_bytes(run.raw_response_hash))
    assert (
        NumericCdf.model_validate_json(json.dumps(sealed["distribution"]), strict=True)
        == run.distribution
    )

    result = next(
        record
        for record in core_store.list("attempt_result").records
        if record.attempt_id == attempt.id
    )
    assert (result.outcome, result.exit_code, result.run_id) == ("succeeded", 0, run.id)
    assert job_row(core_store, claim.job_id)["state"] == "complete"


def test_baseline_is_reproducible_across_independent_workers(core_store):
    """Same frozen evidence, same forecast bytes: the baseline is a constant."""
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    first_task = add_task(graph, forecaster, policy="baseline")
    second_task = add_task(
        graph,
        graph.add(
            make_forecaster(
                baseline=True,
                agent_version=execution.PERSISTENCE_BASELINE_VERSION,
                harness_version="2",
            )
        ),
        policy="baseline",
    )
    seed(core_store, graph)

    first = execution.execute_forecast(
        core_store, claim_task(core_store, first_task.id)
    )
    second = execution.execute_forecast(
        core_store, claim_task(core_store, second_task.id, worker="worker-2")
    )
    assert first.distribution == second.distribution
    assert first.raw_response_hash == second.raw_response_hash


def test_baseline_refuses_a_forecaster_that_does_not_pin_the_procedure(core_store):
    graph = make_graph()
    unpinned = graph.add(make_forecaster(baseline=True, agent_version="1"))
    task = add_task(graph, unpinned, policy="baseline")
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    with pytest.raises(execution.ExecutionRefused, match="pin the procedure"):
        execution.execute_forecast(core_store, claim)
    assert attempts_for(core_store, task.id) == []


# --- A real subprocess --------------------------------------------------------


def test_subprocess_reads_the_supplied_evidence_and_emits_a_valid_cdf(
    core_store, tmp_path
):
    script = write_script(tmp_path, "forecaster.py", EVIDENCE_FORECASTER)
    outdir = tmp_path / "out"
    graph = make_graph()
    forecaster = subprocess_forecaster(graph, script, outdir, "declare-model")
    task = add_task(graph, forecaster, policy="operator_subprocess")
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    run = execution.execute_forecast(core_store, claim, timeout_seconds=60)

    assert run is not None
    # The forecast is derived from the evidence the bundle actually froze:
    # the last observation is 11.0 and this forecaster adds one.
    assert run.distribution.summary.point_estimate == pytest.approx(12.0)
    assert run.distribution.transform_version == "fixture_forecaster_v1"
    assert run.execution_policy == "operator_subprocess"

    # The prompt reached stdin, and it is the exact sealed prompt artifact.
    seen = (outdir / "prompt-seen.txt").read_bytes()
    assert seen == core_store.artifacts.read_bytes(run.prompt_hash)
    assert b"prompt section: observations" in seen
    # The working directory was private and disposable, not the repository.
    workdir = Path((outdir / "cwd.txt").read_text())
    assert not workdir.exists()
    assert Path.cwd() not in workdir.parents

    result = next(
        record
        for record in core_store.list("attempt_result").records
        if record.attempt_id == run.attempt_id
    )
    assert (result.outcome, result.exit_code) == ("succeeded", 0)


def test_observed_model_comes_from_the_response_not_the_request(core_store, tmp_path):
    script = write_script(tmp_path, "forecaster.py", EVIDENCE_FORECASTER)
    graph = make_graph()
    declaring = subprocess_forecaster(
        graph, script, tmp_path / "a", "declare-model", model_request="requested-1"
    )
    silent = subprocess_forecaster(
        graph, script, tmp_path / "b", model_request="requested-2"
    )
    declared_task = add_task(graph, declaring, policy="operator_subprocess")
    silent_task = add_task(graph, silent, policy="operator_subprocess")
    seed(core_store, graph)

    declared = execution.execute_forecast(
        core_store, claim_task(core_store, declared_task.id), timeout_seconds=60
    )
    quiet = execution.execute_forecast(
        core_store, claim_task(core_store, silent_task.id), timeout_seconds=60
    )
    assert declared.observed_model == "fixture-model-actually-served-9"
    # Nothing observed means nothing recorded: the requested model is not a
    # substitute for what the provider actually served.
    assert quiet.observed_model is None


def test_a_forecaster_that_ignores_its_prompt_still_completes(core_store, tmp_path):
    """The prompt pipe closing early must not deadlock or fail the attempt."""
    script = write_script(
        tmp_path,
        "ignores_stdin.py",
        """
        import json, pathlib
        observations = json.loads(
            pathlib.Path("evidence/observations.json").read_text()
        )
        center = observations[-1]["value"]
        points = [
            {"value": center - 1 + i / 100.0, "probability": i / 200}
            for i in range(201)
        ]
        print(json.dumps({"distribution": {
            "format": "numeric_cdf_v1", "pointCount": 201,
            "support": {"lower": points[0]["value"], "upper": points[-1]["value"]},
            "points": points,
            "summary": {"pointEstimate": center, "median": center,
                        "interval80": {"lower": center - 0.8,
                                       "upper": center + 0.8}},
            "provenance": "agent_reported", "transformVersion": "ignores_stdin_v1",
        }}))
        """,
    )
    graph = make_graph()
    task = add_task(
        graph,
        subprocess_forecaster(graph, script),
        policy="operator_subprocess",
    )
    seed(core_store, graph)
    run = execution.execute_forecast(
        core_store, claim_task(core_store, task.id), timeout_seconds=60
    )
    assert run is not None
    assert run.distribution.summary.point_estimate == pytest.approx(11.0)


# --- Observed failures keep their sanitized trace -----------------------------


def failed_result(core_store, task_id):
    allocation = attempts_for(core_store, task_id)[-1]
    return next(
        record
        for record in core_store.list("attempt_result").records
        if record.attempt_id == allocation["attempt_id"]
    )


def test_invalid_json_persists_a_failed_result_with_sanitized_artifacts(
    core_store, tmp_path
):
    script = write_script(
        tmp_path,
        "babbler.py",
        f"""
        import sys
        sys.stdin.read()
        print("this is not a forecast; ANTHROPIC_API_KEY={PLANTED_STDOUT_SECRET}")
        print("boom", file=sys.stderr)
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    assert execution.execute_forecast(core_store, claim, timeout_seconds=60) is None

    result = failed_result(core_store, task.id)
    assert result.outcome == "failed"
    assert result.exit_code == 0
    assert result.run_id is None
    assert core_store.list("forecast_run").records == ()
    stdout = core_store.artifacts.read_bytes(result.stdout_hash).decode()
    assert "ANTHROPIC_API_KEY=[REDACTED]" in stdout
    assert PLANTED_STDOUT_SECRET not in stdout
    assert b"boom" in core_store.artifacts.read_bytes(result.stderr_hash)
    assert job_row(core_store, claim.job_id)["state"] == "failed"


def test_the_unredacted_bytes_never_reach_content_addressed_storage(
    core_store, tmp_path
):
    """Redaction happens before hashing, so the secret has no address at all."""
    import hashlib

    script = write_script(
        tmp_path,
        "leaker.py",
        f"""
        import sys
        sys.stdin.read()
        sys.stdout.write("CENSUS_API_KEY={PLANTED_STDOUT_SECRET}")
        sys.stderr.write("also OPENAI_API_KEY={PLANTED_STDOUT_SECRET}")
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)
    execution.execute_forecast(
        core_store, claim_task(core_store, task.id), timeout_seconds=60
    )

    raw_stdout = f"CENSUS_API_KEY={PLANTED_STDOUT_SECRET}".encode()
    raw_stderr = f"also OPENAI_API_KEY={PLANTED_STDOUT_SECRET}".encode()
    for raw in (raw_stdout, raw_stderr):
        assert not core_store.artifacts.exists(hashlib.sha256(raw).hexdigest())

    result = failed_result(core_store, task.id)
    for digest in (result.stdout_hash, result.stderr_hash, result.raw_response_hash):
        assert (
            PLANTED_STDOUT_SECRET
            not in core_store.artifacts.read_bytes(digest).decode()
        )


def test_nonzero_exit_persists_the_failed_trace(core_store, tmp_path):
    script = write_script(
        tmp_path,
        "angry.py",
        """
        import sys
        sys.stdin.read()
        sys.stderr.write("official source refused the request\\n")
        sys.exit(3)
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    assert execution.execute_forecast(core_store, claim, timeout_seconds=60) is None
    result = failed_result(core_store, task.id)
    assert (result.outcome, result.exit_code) == ("failed", 3)
    assert b"refused the request" in core_store.artifacts.read_bytes(result.stderr_hash)


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
@pytest.mark.parametrize(
    "payload",
    [
        "[" * 1100 + '{"api_key":"planted-opaque"}' + "]" * 1100,
        "7" * 5000,
        '{"api_key":{"nested":"planted-opaque"',
        ('tool log\n{\n"creden\\u0074ials"\n:\n{"nested":"planted-opaque"\n'),
        json.dumps(
            {
                "aggregated_output": (
                    'tool log\n{\n"credentials":{"nested":"planted-opaque"\n'
                )
            }
        ),
        'log: "credentials": "%s" % "planted-opaque"',
        'log: "credentials": "prefix" if condition else "planted-opaque"',
        'log: "credentials": 1 + "planted-opaque"',
        'log: "credentials": {match: /},planted-opaque/};',
    ],
)
def test_worker_seals_unsafe_output_as_failed_without_persisting_raw_bytes(
    core_store, tmp_path, channel, payload
):
    import hashlib

    from thesis_core.worker import work_once

    other = "stderr" if channel == "stdout" else "stdout"
    script = write_script(
        tmp_path,
        "unsafe_json.py",
        f"""
        import sys
        sys.stdin.read()
        sys.{channel}.write({payload!r})
        sys.{other}.write("safe diagnostic trace\\n")
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)
    core_store.enqueue("forecast", task.id, {}, idempotency_key=uuid.uuid4().hex)
    completed = work_once(core_store, kinds=("forecast",), timeout_seconds=10)

    assert completed["run_id"] is None
    assert job_row(core_store, completed["job_id"])["state"] == "failed"
    result = failed_result(core_store, task.id)
    assert result.outcome == "failed"
    assert result.exit_code == 0
    assert not core_store.artifacts.exists(hashlib.sha256(payload.encode()).hexdigest())
    captured = json.loads(
        core_store.artifacts.read_bytes(getattr(result, f"{channel}_hash"))
    )
    assert captured["redactionFailure"] == "unsafe_json"
    assert captured["capturedBytes"] == len(payload.encode())
    assert b"safe diagnostic trace" in core_store.artifacts.read_bytes(
        getattr(result, f"{other}_hash")
    )
    for digest in (result.stdout_hash, result.stderr_hash, result.raw_response_hash):
        assert b"planted-opaque" not in core_store.artifacts.read_bytes(digest)
    assert core_store.recover_expired() == {"requeued": 0, "unknown": 0}
    assert work_once(core_store, kinds=("forecast",), timeout_seconds=10) is None
    assert len(attempts_for(core_store, task.id)) == 1


@pytest.mark.parametrize("mixed_diagnostics", [False, True])
@pytest.mark.parametrize("duplicate_members", [False, True])
def test_serialized_json_credentials_in_stderr_are_scrubbed_before_a_run_is_sealed(
    core_store, tmp_path, mixed_diagnostics, duplicate_members
):
    from thesis_core.worker import work_once

    event = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "aggregated_output": json.dumps(
                    {"credentials": {"nested": "opaque-planted-review-value"}}, indent=2
                )
            },
        }
    )
    if duplicate_members:
        duplicate_payload = (
            '{"branch":{"credentials":{"nested":"opaque-planted-review-value"}},'
            '"branch":{}}'
        )
        event = (
            '{"id":"first","item":{"aggregated_output":'
            + json.dumps(duplicate_payload)
            + '},"branch":{"credentials":{"nested":"opaque-planted-review-value"}},'
            '"branch":{},"id":"second","action":{"queries":'
            '["https://agency.example/data?api_key=opaque-planted-review-value"]},'
            '"action":{"queries":["public data"]}}'
        )
    clean_event = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3}})
    bounded_values = (
        'page: "cookie": {"operator":"equals","name":"consent",'
        '"value":"opaque-planted-review-value"}; '
        '"key": opaque_planted_identifier; "api_key": aa="opaque-planted-review-value";'
    )
    bounded_event = json.dumps({"aggregated_output": bounded_values})
    stderr = event + "\n" + bounded_event + "\n" + clean_event + "\n"
    prefix = "[1/3] Building\n[2026-09-05 12:00:00] INFO starting\n{'a': 1}\n"
    # Representative prompt-echo shape preserved in the actual June 21 Codex
    # stderr for the 2026-06-20 DOL initial-claims forecast (lines 34 onwards).
    suffix = (
        '# Required JSON shape\n{\n  "slug": "kebab-case-unique-vs-catalog",\n'
        '  "country": "US|UK|CA|AU|EA|JP",\n  "pointEstimate": 0\n}\n'
    )
    if mixed_diagnostics:
        stderr = prefix + stderr + suffix
    script = write_script(
        tmp_path,
        "jsonl_stderr.py",
        EVIDENCE_FORECASTER + f"\nsys.stderr.write({stderr!r})\n",
    )
    graph = make_graph()
    task = add_task(
        graph,
        subprocess_forecaster(graph, script, tmp_path / "out"),
        policy="operator_subprocess",
    )
    graph.records.pop(graph.experiment.id)
    experiment = graph.add(
        Experiment(
            **(
                graph.experiment.model_dump()
                | {
                    "task_ids": (task.id, graph.baseline_task.id),
                    "forecaster_version_ids": (
                        task.forecaster_version_id,
                        graph.baseline.id,
                    ),
                }
            )
        )
    )
    seed(core_store, graph)
    core_store.enqueue(
        "forecast",
        task.id,
        {"experiment_id": experiment.id},
        idempotency_key=uuid.uuid4().hex,
    )
    completed = work_once(core_store, kinds=("forecast",), timeout_seconds=10)
    run = core_store.get(completed["run_id"])

    assert run is not None
    assert job_row(core_store, completed["job_id"])["state"] == "complete"
    sealed = core_store.artifacts.read_bytes(run.stderr_hash).decode()
    if mixed_diagnostics:
        assert sealed.startswith(prefix)
        assert sealed.endswith(suffix)
        sealed = sealed[len(prefix) : -len(suffix)]
    lines = sealed.splitlines()
    assert lines[-1] == clean_event
    assert json.loads(lines[1])["aggregated_output"] == (
        'page: "cookie": "[REDACTED]"; "key": "[REDACTED]"; "api_key": "[REDACTED]";'
    )
    inner = json.loads(json.loads(lines[0])["item"]["aggregated_output"])
    if duplicate_members:
        assert inner == {"branch": {}}
        inner_pairs = json.loads(
            json.loads(lines[0])["item"]["aggregated_output"], object_pairs_hook=list
        )
        assert inner_pairs == [
            ("branch", [("credentials", "[REDACTED]")]),
            ("branch", []),
        ]
        pairs = json.loads(lines[0], object_pairs_hook=list)
        assert [item for key, item in pairs if key == "id"] == ["first", "second"]
        assert [item for key, item in pairs if key == "branch"] == [
            [("credentials", "[REDACTED]")],
            [],
        ]
        assert [item for key, item in pairs if key == "action"] == [
            [("queries", ["https://agency.example/data?api_key=[REDACTED]"])],
            [("queries", ["public data"])],
        ]
    else:
        assert inner["credentials"] == "[REDACTED]"
    for digest in (run.stdout_hash, run.stderr_hash, run.raw_response_hash):
        assert b"opaque-planted-review-value" not in core_store.artifacts.read_bytes(
            digest
        )
        assert b"opaque_planted_identifier" not in core_store.artifacts.read_bytes(
            digest
        )


def test_timeout_terminates_the_process_and_persists_the_failure(core_store, tmp_path):
    marker = tmp_path / "finished.marker"
    script = write_script(
        tmp_path,
        "sleeper.py",
        f"""
        import pathlib, sys, time
        sys.stdin.read()
        sys.stderr.write("working\\n")
        sys.stderr.flush()
        time.sleep(30)
        pathlib.Path({str(marker)!r}).write_text("finished")
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    started = time.monotonic()
    assert execution.execute_forecast(core_store, claim, timeout_seconds=1.0) is None
    assert time.monotonic() - started < 20

    result = failed_result(core_store, task.id)
    assert result.outcome == "failed"
    # A killed process is distinguishable from an ordinary nonzero exit.
    assert result.exit_code is not None and result.exit_code < 0
    assert b"working" in core_store.artifacts.read_bytes(result.stderr_hash)
    time.sleep(0.5)
    assert not marker.exists()


def test_runaway_output_fails_the_attempt_instead_of_the_worker(core_store, tmp_path):
    """A flood must stay an observable failure, never an unknown outcome."""
    script = write_script(
        tmp_path,
        "flood.py",
        """
        import sys
        sys.stdin.read()
        block = "x" * 65536
        while True:
            sys.stdout.write(block)
            sys.stdout.flush()
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)

    assert (
        execution.execute_forecast(
            core_store, claim_task(core_store, task.id), timeout_seconds=120
        )
        is None
    )
    result = failed_result(core_store, task.id)
    assert result.outcome == "failed"
    captured = core_store.artifacts.read_bytes(result.stdout_hash)
    assert len(captured) <= execution.MAX_CAPTURED_BYTES
    assert core_store.list("forecast_run").records == ()


def test_a_spawn_failure_is_a_recorded_failure_not_a_crash(core_store, tmp_path):
    graph = make_graph()
    missing = tmp_path / "no-such-forecaster"
    forecaster = graph.add(make_forecaster(inference_settings={"argv": [str(missing)]}))
    task = add_task(graph, forecaster, policy="operator_subprocess")
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    assert execution.execute_forecast(core_store, claim, timeout_seconds=60) is None
    result = failed_result(core_store, task.id)
    assert (result.outcome, result.exit_code) == ("failed", None)
    stderr = core_store.artifacts.read_bytes(result.stderr_hash).decode()
    assert "spawn failed" in stderr
    assert core_store.artifacts.read_bytes(result.stdout_hash) == b""


# --- Credential hygiene across the process boundary ---------------------------


def test_a_parent_credential_is_never_forwarded_or_recorded(
    core_store, tmp_path, monkeypatch
):
    monkeypatch.setenv("PLANTED_PARENT_API_KEY", PLANTED_ENV_SECRET)
    script = write_script(tmp_path, "forecaster.py", EVIDENCE_FORECASTER)
    outdir = tmp_path / "out"
    graph = make_graph()
    task = add_task(
        graph,
        subprocess_forecaster(graph, script, outdir),
        policy="operator_subprocess",
    )
    seed(core_store, graph)

    run = execution.execute_forecast(
        core_store, claim_task(core_store, task.id), timeout_seconds=60
    )
    assert run is not None

    child_env = json.loads((outdir / "environment.json").read_text())
    assert "PLANTED_PARENT_API_KEY" not in child_env
    # Everything the child sees is allowlisted, except names the platform
    # injects into every process it starts (macOS __CF_USER_TEXT_ENCODING).
    unexpected = {
        name
        for name in child_env
        if name not in execution.AGENT_ENV_ALLOWLIST and not name.startswith("__")
    }
    assert unexpected == set()
    assert [name for name in child_env if is_credential_key(name)] == []
    assert child_env["TMPDIR"] == (outdir / "cwd.txt").read_text()
    assert PLANTED_ENV_SECRET not in json.dumps(child_env)

    for record in (run, core_store.get(run.attempt_id)):
        assert PLANTED_ENV_SECRET not in record.canonical_bytes().decode()
    for digest in (run.stdout_hash, run.stderr_hash, run.raw_response_hash):
        assert (
            PLANTED_ENV_SECRET not in core_store.artifacts.read_bytes(digest).decode()
        )


@pytest.mark.parametrize(
    "arguments",
    [
        [f"--token={PLANTED_STDOUT_SECRET}"],
        ["--token=planted-opaque"],
        ["--api-key=planted-opaque"],
        ["--api-key", "planted-opaque"],
        ["--password", "planted-opaque"],
        ["--api-key=Bearer planted-opaque"],
        ["--password=prefix\nplanted-opaque"],
        ["API_KEY=prefix planted-opaque"],
    ],
)
def test_a_credential_can_never_be_registered_in_a_forecaster_argv(arguments):
    """The contract refuses it outright: registration is the first defense."""
    with pytest.raises(ValidationError, match="credential-bearing"):
        make_forecaster(inference_settings={"argv": [sys.executable, *arguments]})


@pytest.mark.parametrize("key", ["args", "unexpected"])
def test_registration_refuses_credentials_in_any_string_vector(key):
    with pytest.raises(ValidationError, match="credential-bearing"):
        make_forecaster(inference_settings={key: ["--api-key", "planted-opaque"]})


@pytest.mark.parametrize(
    "arguments",
    [
        ["--token=planted-opaque"],
        ["--api-key=planted-opaque"],
        ["--api-key", "planted-opaque"],
        ["--password", "planted-opaque"],
        ["--api-key=Bearer planted-opaque"],
        ["--password=prefix\nplanted-opaque"],
        ["API_KEY=prefix planted-opaque"],
    ],
)
def test_opaque_argv_credentials_are_absent_from_command_bytes(arguments):
    command = execution._command_document(
        "operator_subprocess", ("forecaster", *arguments), 60
    )
    assert "planted-opaque" not in json.dumps(command)
    assert "[REDACTED]" in json.dumps(command)


def test_the_command_document_is_redacted_before_it_is_hashed(core_store, tmp_path):
    """Second defense: whatever reaches argv is scrubbed before addressing."""
    leaky = execution._command_document(
        "operator_subprocess",
        ("/usr/bin/forecaster", f"--token={PLANTED_STDOUT_SECRET}"),
        60.0,
    )
    assert PLANTED_STDOUT_SECRET not in json.dumps(leaky)
    assert "[REDACTED]" in json.dumps(leaky["argv"])

    script = write_script(tmp_path, "forecaster.py", EVIDENCE_FORECASTER)
    graph = make_graph()
    task = add_task(
        graph,
        subprocess_forecaster(graph, script, tmp_path / "out"),
        policy="operator_subprocess",
    )
    seed(core_store, graph)
    run = execution.execute_forecast(
        core_store, claim_task(core_store, task.id), timeout_seconds=60
    )
    attempt = core_store.get(run.attempt_id)
    command = json.loads(core_store.artifacts.read_bytes(attempt.command_hash))
    assert command["shell"] is False
    assert command["promptDelivery"] == "stdin"
    assert command["protocol"] == execution.EXECUTION_PROTOCOL
    assert command["disclosure"] == execution.OPERATOR_SUBPROCESS_DISCLOSURE
    assert command["environmentAllowlist"] == list(execution.AGENT_ENV_ALLOWLIST)
    # No absolute working directory: the same registered command hashes the
    # same way on every host.
    assert str(tmp_path) not in json.dumps(
        {k: v for k, v in command.items() if k != "argv"}
    )


# --- The frozen policy governs ------------------------------------------------


def test_runtime_argv_cannot_substitute_the_preregistered_vector(core_store, tmp_path):
    script = write_script(tmp_path, "forecaster.py", EVIDENCE_FORECASTER)
    other = write_script(
        tmp_path,
        "other.py",
        """
        import pathlib
        pathlib.Path("SHOULD-NOT-EXIST").write_text("ran")
        """,
    )
    graph = make_graph()
    task = add_task(
        graph,
        subprocess_forecaster(graph, script, tmp_path / "out"),
        policy="operator_subprocess",
    )
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    with pytest.raises(execution.ExecutionRefused, match="preregistered"):
        execution.execute_forecast(
            core_store, claim, argv=[sys.executable, str(other)], timeout_seconds=60
        )
    # A refusal costs no durable attempt and starts no process.
    assert attempts_for(core_store, task.id) == []
    assert job_row(core_store, claim.job_id)["dispatched_attempt_id"] is None
    assert not (tmp_path / "SHOULD-NOT-EXIST").exists()

    # Repeating the registered vector is allowed; it changes nothing.
    run = execution.execute_forecast(
        core_store,
        claim,
        argv=[sys.executable, str(script), str(tmp_path / "out")],
        timeout_seconds=60,
    )
    assert run is not None


def test_a_subprocess_forecaster_without_a_registered_argv_refuses(core_store):
    graph = make_graph()
    task = add_task(graph, graph.forecaster, policy="operator_subprocess")
    seed(core_store, graph)
    with pytest.raises(execution.ExecutionRefused, match="preregistered"):
        execution.execute_forecast(core_store, claim_task(core_store, task.id))
    assert attempts_for(core_store, task.id) == []


def test_the_baseline_accepts_no_command_and_a_mismatched_protocol_refuses(
    core_store, tmp_path
):
    graph = make_graph()
    armed = graph.add(
        make_forecaster(
            baseline=True,
            agent_version=execution.PERSISTENCE_BASELINE_VERSION,
            inference_settings={"argv": [sys.executable, "-c", "print(1)"]},
        )
    )
    stale = subprocess_forecaster(
        graph,
        tmp_path / "forecaster.py",
        inference_settings={"execution_protocol": "prompt_file_v0"},
    )
    armed_task = add_task(graph, armed, policy="baseline")
    stale_task = add_task(graph, stale, policy="operator_subprocess")
    seed(core_store, graph)

    with pytest.raises(execution.ExecutionRefused, match="cannot register an argv"):
        execution.execute_forecast(core_store, claim_task(core_store, armed_task.id))
    with pytest.raises(execution.ExecutionRefused, match="execution protocol"):
        execution.execute_forecast(core_store, claim_task(core_store, stale_task.id))


def test_a_task_and_forecaster_must_agree_about_the_execution_policy(core_store):
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="operator_subprocess")
    seed(core_store, graph)
    with pytest.raises(execution.ExecutionRefused, match="execution policy"):
        execution.execute_forecast(core_store, claim_task(core_store, task.id))


# --- The cohort receipt gates prospective dispatch ----------------------------


def cohort_proof(core_store, graph):
    """A stored publication_proof the attempt can reference."""
    from thesis_core.contracts import PublicationManifest, PublicationProof

    manifest = graph.add(
        PublicationManifest(
            manifest_type="cohort",
            experiment_id=graph.experiment.id,
            artifacts=(graph.blob("cohort artifact"),),
            code_hash=graph.blob("code"),
            recorded_at=at(90),
            declared_information_cutoff=at(100),
            effective_information_boundary=at(80),
        )
    )
    return graph.add(
        PublicationProof(
            manifest_id=manifest.id,
            request_hash=graph.blob("tsq"),
            token_hash=graph.blob("tsr token"),
            subject_hash=manifest.id,
            trust_bundle_path="trust/test.pem",
            trust_bundle_hash=graph.blob("bundle"),
            trust_anchor_id="test-anchor",
            gen_time=at(95),
            accuracy_micros=1000,
            signer_identity="CN=Test TSA",
            policy_oid="1.2.3.4",
            verification_version="fixture_v1",
            verified_at=at(96),
        )
    )


def test_prospective_dispatch_refuses_without_a_verified_cohort_receipt(core_store):
    graph = make_graph(mode="prospective")
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="baseline", mode="prospective")
    proof = cohort_proof(core_store, graph)
    seed(core_store, graph)

    with pytest.raises(execution.ExecutionRefused, match="independently witnessed"):
        execution.execute_forecast(core_store, claim_task(core_store, task.id))

    payload = {"experiment_id": graph.experiment.id, "cohort_proof_id": proof.id}
    with pytest.raises(execution.ExecutionRefused, match="replays its receipt"):
        execution.execute_forecast(
            core_store, claim_task(core_store, task.id, payload=payload)
        )

    # A stored boolean is not verification.
    with pytest.raises(execution.ExecutionRefused, match="boolean is never"):
        execution.execute_forecast(
            core_store,
            claim_task(core_store, task.id, payload=payload),
            verify_cohort_proof=lambda **_: True,
        )

    def unverifiable(**_):
        raise ValueError("receipt does not verify against the pinned anchors")

    with pytest.raises(execution.ExecutionRefused, match="does not verify"):
        execution.execute_forecast(
            core_store,
            claim_task(core_store, task.id, payload=payload),
            verify_cohort_proof=unverifiable,
        )
    assert attempts_for(core_store, task.id) == []


@pytest.mark.parametrize("verified_token_hash", ["b" * 64, "c" * 64])
def test_a_verified_cohort_receipt_is_committed_before_dispatch(
    core_store, verified_token_hash
):
    graph = make_graph(mode="prospective")
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="baseline", mode="prospective")
    proof = cohort_proof(core_store, graph)
    seed(core_store, graph)

    seen = {}

    def verifier(**kwargs):
        seen.update(kwargs)
        return verified_token_hash

    run = execution.execute_forecast(
        core_store,
        claim_task(
            core_store,
            task.id,
            payload={
                "experiment_id": graph.experiment.id,
                "cohort_proof_id": proof.id,
            },
        ),
        verify_cohort_proof=verifier,
    )
    assert seen == {
        "experiment_id": graph.experiment.id,
        "cohort_proof_id": proof.id,
        "task_id": task.id,
    }
    attempt = core_store.get(run.attempt_id)
    assert attempt.cohort_proof_id == proof.id
    assert attempt.cohort_token_hash == verified_token_hash
    prompt = core_store.artifacts.read_bytes(run.prompt_hash)
    assert proof.id.encode() in prompt
    assert verified_token_hash.encode() in prompt
    assert b"prompt section: cohort_receipt" in prompt
    assert attempt.prompt_hash == run.prompt_hash


def test_the_receipt_is_part_of_the_assembled_prompt_identity(core_store):
    """Sealed as a section, so it changes the prompt hash rather than sitting
    beside it as an annotation."""
    graph = make_graph(mode="prospective")
    parts = _prompt_parts(graph)
    receipt = {"proof_id": "d" * 64, "token_hash": "e" * 64}
    with_receipt = execution.build_prompt(**parts | {"cohort_receipt": receipt})
    assert with_receipt != execution.build_prompt(**parts)
    assert b"prompt section: cohort_receipt" in with_receipt
    assert with_receipt == execution.build_prompt(**parts | {"cohort_receipt": receipt})


def test_replay_may_omit_the_cohort_proof_and_stays_replay(core_store):
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="baseline", mode="replay")
    seed(core_store, graph)

    run = execution.execute_forecast(
        core_store, claim_task(core_store, task.id), verify_cohort_proof=None
    )
    attempt = core_store.get(run.attempt_id)
    assert (attempt.cohort_proof_id, attempt.cohort_token_hash) == (None, None)
    assert core_store.get(task.id).mode == "replay"


# --- Leases, heartbeats and the refusal to retry ------------------------------


def test_heartbeats_hold_ownership_past_the_original_lease(core_store, tmp_path):
    script = write_script(
        tmp_path,
        "slow.py",
        """
        import json, pathlib, sys, time
        sys.stdin.read()
        time.sleep(2.0)
        observations = json.loads(
            pathlib.Path("evidence/observations.json").read_text()
        )
        center = observations[-1]["value"]
        points = [
            {"value": center - 1 + i / 100.0, "probability": i / 200}
            for i in range(201)
        ]
        print(json.dumps({"distribution": {
            "format": "numeric_cdf_v1", "pointCount": 201,
            "support": {"lower": points[0]["value"], "upper": points[-1]["value"]},
            "points": points,
            "summary": {"pointEstimate": center, "median": center,
                        "interval80": {"lower": center - 0.8,
                                       "upper": center + 0.8}},
            "provenance": "agent_reported", "transformVersion": "slow_v1",
        }}))
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)
    claim = claim_task(core_store, task.id, lease_seconds=1.0)
    original_expiry = claim.lease_expires_at

    run = execution.execute_forecast(
        core_store, claim, timeout_seconds=30, lease_seconds=1.0
    )

    assert run is not None
    assert run.completed_at > original_expiry
    assert job_row(core_store, claim.job_id)["state"] == "complete"


def test_losing_the_lease_kills_the_process_and_invokes_nothing_twice(
    core_store, tmp_path
):
    calls = tmp_path / "calls"
    calls.mkdir()
    finished = tmp_path / "finished.marker"
    script = write_script(
        tmp_path,
        "long.py",
        f"""
        import os, pathlib, sys, time
        pathlib.Path({str(calls)!r}, str(os.getpid())).write_text("called")
        sys.stdin.read()
        time.sleep(30)
        pathlib.Path({str(finished)!r}).write_text("finished")
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)
    claim = claim_task(core_store, task.id, lease_seconds=1.0)

    outcome = {}

    def run_it():
        try:
            outcome["run"] = execution.execute_forecast(
                core_store, claim, timeout_seconds=60, lease_seconds=1.0
            )
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            outcome["error"] = exc

    worker = threading.Thread(target=run_it)
    worker.start()
    deadline = time.monotonic() + 30
    while not list(calls.iterdir()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert list(calls.iterdir()), "the forecaster never started"

    # Another worker recovered this job: the fencing generation moves on.
    with core_store.connection() as connection:
        connection.execute(
            "UPDATE jobs SET generation=generation+1 WHERE id=%s", (claim.job_id,)
        )
    worker.join(timeout=60)
    assert not worker.is_alive()

    assert isinstance(outcome.get("error"), LeaseLost)
    # Nothing was committed under a lease this worker no longer held.
    assert core_store.list("forecast_run").records == ()
    assert core_store.list("attempt_result").records == ()
    # The model ran exactly once and was stopped, not left running.
    assert len(list(calls.iterdir())) == 1
    time.sleep(0.5)
    assert not finished.exists()
    pid = int(next(iter(calls.iterdir())).name)
    with pytest.raises(OSError):
        os.kill(pid, 0)


def test_a_stale_worker_cannot_finish_after_losing_ownership(core_store):
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="baseline")
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    with core_store.connection() as connection:
        connection.execute(
            "UPDATE jobs SET generation=generation+1 WHERE id=%s", (claim.job_id,)
        )
    with pytest.raises(LeaseLost):
        execution.execute_forecast(core_store, claim)
    assert core_store.list("forecast_run").records == ()


def test_a_lease_lost_between_running_and_sealing_commits_nothing(
    core_store, monkeypatch
):
    """The forecast existed, but a worker that lost ownership cannot seal it."""
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="baseline")
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    real_database_now = execution._database_now

    def steal_then_stamp(store):
        # Another worker recovered the job while this one was forecasting.
        with store.connection() as connection:
            connection.execute(
                "UPDATE jobs SET generation=generation+1 WHERE id=%s", (claim.job_id,)
            )
        return real_database_now(store)

    monkeypatch.setattr(execution, "_database_now", steal_then_stamp)
    with pytest.raises(LeaseLost):
        execution.execute_forecast(core_store, claim)

    # The attempt is durable; the result is not, so the outcome stays unknown
    # for the store to recover rather than being sealed under a lost lease.
    assert len(attempts_for(core_store, task.id)) == 1
    assert core_store.list("forecast_run").records == ()
    assert core_store.list("attempt_result").records == ()


def test_only_the_registered_maximum_creates_more_durable_attempts(
    core_store, tmp_path
):
    script = write_script(
        tmp_path,
        "angry.py",
        """
        import sys
        sys.stdin.read()
        sys.exit(4)
        """,
    )
    graph = make_graph()
    limited = add_task(
        graph,
        subprocess_forecaster(graph, script),
        policy="operator_subprocess",
        max_attempts=1,
    )
    generous = add_task(
        graph,
        subprocess_forecaster(graph, script, "second"),
        policy="operator_subprocess",
        max_attempts=2,
    )
    seed(core_store, graph)

    assert (
        execution.execute_forecast(
            core_store, claim_task(core_store, limited.id), timeout_seconds=60
        )
        is None
    )
    # One call is one attempt: execution never retries on its own.
    assert len(attempts_for(core_store, limited.id)) == 1
    with pytest.raises(AttemptBlocked, match="maximum number of attempts"):
        execution.execute_forecast(
            core_store, claim_task(core_store, limited.id), timeout_seconds=60
        )
    assert len(attempts_for(core_store, limited.id)) == 1

    for _ in range(2):
        execution.execute_forecast(
            core_store, claim_task(core_store, generous.id), timeout_seconds=60
        )
    allocations = attempts_for(core_store, generous.id)
    assert [row["sequence"] for row in allocations] == [1, 2]
    with pytest.raises(AttemptBlocked):
        execution.execute_forecast(
            core_store, claim_task(core_store, generous.id), timeout_seconds=60
        )


def test_publication_is_enqueued_with_the_result_not_re_executed(core_store):
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="baseline")
    seed(core_store, graph)
    claim = claim_task(core_store, task.id)

    run = execution.execute_forecast(
        core_store,
        claim,
        followups=(
            JobSpec(
                kind="publish",
                subject_id=task.id,
                idempotency_key="publish-once",
                payload={"reason": "sealed"},
            ),
        ),
    )
    assert run is not None
    core_store.deliver_outbox()
    publish = [job for job in core_store.jobs() if job["kind"] == "publish"]
    assert len(publish) == 1 and publish[0]["subject_id"] == task.id
    # The sealed run stays available for a publication retry without any
    # second model invocation.
    assert core_store.get(run.id) == run
    assert len(attempts_for(core_store, task.id)) == 1


def test_followups_may_be_derived_from_the_sealed_run(core_store):
    """A publication job's subject is the run, which exists only once sealed."""
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="baseline")
    seed(core_store, graph)

    run = execution.execute_forecast(
        core_store,
        claim_task(core_store, task.id),
        followups=lambda sealed: (
            JobSpec(
                kind="publish_run",
                subject_id=sealed.id,
                idempotency_key=f"publish-run:{sealed.id}",
                payload={"experiment_id": graph.experiment.id},
            ),
        ),
    )
    core_store.deliver_outbox()
    published = [job for job in core_store.jobs() if job["kind"] == "publish_run"]
    assert [job["subject_id"] for job in published] == [run.id]


def test_a_failed_attempt_schedules_no_publication(core_store, tmp_path):
    script = write_script(
        tmp_path,
        "angry.py",
        """
        import sys
        sys.stdin.read()
        sys.exit(9)
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)

    called = []
    assert (
        execution.execute_forecast(
            core_store,
            claim_task(core_store, task.id),
            timeout_seconds=60,
            followups=lambda sealed: called.append(sealed) or (),
        )
        is None
    )
    core_store.deliver_outbox()
    assert called == []
    assert [job for job in core_store.jobs() if job["kind"] != "forecast"] == []


def test_a_missing_prompt_artifact_refuses_before_any_attempt(core_store):
    graph = make_graph()
    forecaster = graph.add(
        make_forecaster(
            baseline=True,
            agent_version=execution.PERSISTENCE_BASELINE_VERSION,
            system_prompt_hash="c" * 64,
        )
    )
    task = add_task(graph, forecaster, policy="baseline")
    seed(core_store, graph)
    with pytest.raises(Exception) as caught:
        execution.execute_forecast(core_store, claim_task(core_store, task.id))
    assert "c" * 64 in str(caught.value)
    assert attempts_for(core_store, task.id) == []


def test_an_evidence_bundle_frozen_for_another_cutoff_refuses(core_store):
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    task = graph.add(
        EvaluationTask(
            target_version_id=graph.target.id,
            forecaster_version_id=forecaster.id,
            evidence_bundle_id=graph.evidence.id,
            information_cutoff=at(200),
            submission_deadline=at(1000),
            execution_policy="baseline",
            mode="replay",
        )
    )
    seed(core_store, graph)
    with pytest.raises(execution.ExecutionRefused, match="another cutoff"):
        execution.execute_forecast(core_store, claim_task(core_store, task.id))


def test_the_worker_clock_never_decides_a_sealed_timestamp(core_store, monkeypatch):
    """A skewed worker cannot stamp the record: the database clock does."""
    graph = make_graph()
    forecaster = baseline_forecaster(graph)
    task = add_task(graph, forecaster, policy="baseline")
    seed(core_store, graph)

    import datetime as datetime_module

    class SkewedDatetime(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime_module.datetime(
                1999, 1, 1, tzinfo=datetime_module.timezone.utc
            )

        @classmethod
        def utcnow(cls):
            return datetime_module.datetime(1999, 1, 1)

    monkeypatch.setattr(datetime_module, "datetime", SkewedDatetime)
    run = execution.execute_forecast(core_store, claim_task(core_store, task.id))
    attempt = core_store.get(run.attempt_id)
    assert run.completed_at.year >= 2026
    assert attempt.started_at.year >= 2026


def test_a_subprocess_cannot_reach_the_repository_from_its_working_directory(
    core_store, tmp_path
):
    script = write_script(
        tmp_path,
        "lister.py",
        """
        import json, os, pathlib, sys
        sys.stdin.read()
        listing = sorted(os.listdir("."))
        pathlib.Path(os.environ["TMPDIR"], "..", "listing.json")
        sys.stdout.write(json.dumps({"distribution": listing}))
        """,
    )
    graph = make_graph()
    task = add_task(
        graph, subprocess_forecaster(graph, script), policy="operator_subprocess"
    )
    seed(core_store, graph)
    assert (
        execution.execute_forecast(
            core_store, claim_task(core_store, task.id), timeout_seconds=60
        )
        is None
    )
    result = failed_result(core_store, task.id)
    listing = json.loads(core_store.artifacts.read_bytes(result.stdout_hash))
    assert listing["distribution"] == ["evidence", "prompt.txt"]


def test_subprocess_runs_without_a_shell(core_store, tmp_path):
    """An argv vector is never re-parsed: shell metacharacters stay literal."""
    marker = tmp_path / "shell-ran.marker"
    script = write_script(
        tmp_path,
        "echo_args.py",
        """
        import json, sys
        sys.stdin.read()
        sys.stdout.write(json.dumps({"distribution": sys.argv[1:]}))
        """,
    )
    graph = make_graph()
    task = add_task(
        graph,
        subprocess_forecaster(graph, script, f"; touch {marker}"),
        policy="operator_subprocess",
    )
    seed(core_store, graph)
    execution.execute_forecast(
        core_store, claim_task(core_store, task.id), timeout_seconds=60
    )
    result = failed_result(core_store, task.id)
    argv = json.loads(core_store.artifacts.read_bytes(result.stdout_hash))
    assert argv["distribution"] == [f"; touch {marker}"]
    assert not marker.exists()


def test_the_environment_carries_no_shell_interpreter_state(core_store, tmp_path):
    """subprocess.Popen without shell=True and with an explicit env."""
    assert subprocess.Popen is not None  # the transport uses the real thing
    graph = make_graph()
    script = write_script(tmp_path, "forecaster.py", EVIDENCE_FORECASTER)
    outdir = tmp_path / "out"
    task = add_task(
        graph,
        subprocess_forecaster(graph, script, outdir),
        policy="operator_subprocess",
    )
    seed(core_store, graph)
    execution.execute_forecast(
        core_store, claim_task(core_store, task.id), timeout_seconds=60
    )
    child_env = json.loads((outdir / "environment.json").read_text())
    assert "PYTHONPATH" not in child_env
    assert "VIRTUAL_ENV" not in child_env
