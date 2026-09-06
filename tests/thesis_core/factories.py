"""Small explicit record graphs; no database or network imports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from thesis_core.contracts import (
    ArtifactRef,
    Attempt,
    AttemptResult,
    EvaluationTask,
    EvidenceBundle,
    Experiment,
    ForecasterVersion,
    ForecastRun,
    ObservationVintage,
    Resolution,
    ScientificRecord,
    SourceExchange,
    SourceSeries,
    TargetVersion,
)
from thesis_core.evaluation import Availability, EvaluationContext, build_normalization
from thesis_core.scoring import build_interval_distribution


def at(seconds: int = 0) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def digest(value: str = "fixture") -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def make_source(**overrides) -> SourceSeries:
    return SourceSeries(
        **dict(
            adapter_id="fixture",
            adapter_version="1",
            name="Fixture official series",
            unit="percent",
            binding={"series": "TEST"},
            vintage_policies=("first_print", "fixed_vintage"),
        )
        | overrides
    )


def make_forecaster(*, baseline: bool = False, **overrides) -> ForecasterVersion:
    values = dict(
        provider="deterministic" if baseline else "fixture",
        model_request="persistence" if baseline else "fixture-model",
        inference_settings={},
        agent_version="1",
        harness_version="1",
        prompt_template_hash=digest("template"),
        system_prompt_hash=digest("system"),
        tool_policy_hash=digest("tools"),
        execution_policy="baseline" if baseline else "operator_subprocess",
    )
    return ForecasterVersion(**(values | overrides))


@dataclass
class Graph:
    records: dict[str, ScientificRecord] = field(default_factory=dict)
    acknowledgements: dict[str, datetime] = field(default_factory=dict)
    artifacts: dict[str, bytes] = field(default_factory=dict)
    official: dict[str, Availability] = field(default_factory=dict)
    source: SourceSeries | None = None
    target: TargetVersion | None = None
    forecaster: ForecasterVersion | None = None
    baseline: ForecasterVersion | None = None
    evidence: EvidenceBundle | None = None
    task: EvaluationTask | None = None
    baseline_task: EvaluationTask | None = None
    experiment: Experiment | None = None

    def add(self, record: ScientificRecord, acknowledged_at: datetime | None = None):
        self.records[record.id] = record
        self.acknowledgements[record.id] = acknowledged_at or at()
        self.artifacts[record.id] = record.canonical_bytes()
        return record

    def blob(self, text: str) -> str:
        key = digest(text)
        self.artifacts[key] = text.encode()
        return key

    def context(self, **overrides) -> EvaluationContext:
        values = dict(
            records=self.records,
            committed_at=self.acknowledgements.get,
            availability=lambda record: self.official.get(record.id),
            target_availability=lambda _: Availability(at(500), at(500)),
            artifact_exists=lambda key: key in self.artifacts,
            resolution_valid=lambda *_: True,
        )
        return EvaluationContext(**(values | overrides))


def make_graph(*, mode="replay") -> Graph:
    graph = Graph()
    graph.source = graph.add(make_source())
    observations = []
    for i, value in enumerate((10.0, 13.0, 11.0)):
        body = graph.blob(f"official historical response {i}")
        exchange = graph.add(
            SourceExchange(
                source_series_id=graph.source.id,
                url="https://example.test/official",
                retrieved_at=at(),
                status_code=200,
                body=ArtifactRef(
                    sha256=body,
                    bytes=len(graph.artifacts[body]),
                    media_type="application/json",
                ),
                mode="replay",
            )
        )
        obs = graph.add(
            ObservationVintage(
                source_series_id=graph.source.id,
                measurement_period=f"2025-{10 + i:02d}",
                value=value,
                unit="percent",
                source_exchange_ids=(exchange.id,),
                retrieved_at=at(),
                accepted_at=at(),
                parser_version="fixture_v1",
                vintage_policy="first_print",
            )
        )
        graph.official[obs.id] = Availability(at(-1000 + i * 100), at(-1000 + i * 100))
        observations.append(obs)
    graph.target = graph.add(
        TargetVersion(
            target_id="fixture-2026-01",
            source_series_id=graph.source.id,
            measurement_period="2026-01",
            unit="percent",
            resolution_policy="first_print",
            resolution_rule="Official first print",
            submission_deadline=at(1000),
        )
    )
    for text in ("template", "system", "tools"):
        graph.blob(text)
    graph.forecaster = graph.add(make_forecaster())
    graph.baseline = graph.add(make_forecaster(baseline=True))
    graph.evidence = graph.add(
        EvidenceBundle(
            source_series_id=graph.source.id,
            observation_ids=tuple(o.id for o in observations),
            artifact_refs=(),
            information_cutoff=at(100),
            mode=mode,
        ),
        at(80),
    )
    normalization = graph.add(
        build_normalization(
            graph.target, observations, at(100), mode=mode, context=graph.context()
        )
    )
    graph.task = graph.add(
        EvaluationTask(
            target_version_id=graph.target.id,
            forecaster_version_id=graph.forecaster.id,
            evidence_bundle_id=graph.evidence.id,
            information_cutoff=at(100),
            submission_deadline=at(1000),
            max_attempts=3,
            execution_policy="operator_subprocess",
            mode=mode,
        )
    )
    graph.baseline_task = graph.add(
        EvaluationTask(
            target_version_id=graph.target.id,
            forecaster_version_id=graph.baseline.id,
            evidence_bundle_id=graph.evidence.id,
            information_cutoff=at(100),
            submission_deadline=at(1000),
            max_attempts=1,
            execution_policy="baseline",
            mode=mode,
        )
    )
    graph.experiment = graph.add(
        Experiment(
            task_ids=(graph.task.id, graph.baseline_task.id),
            target_version_ids=(graph.target.id,),
            forecaster_version_ids=(graph.forecaster.id, graph.baseline.id),
            baseline_forecaster_id=graph.baseline.id,
            normalization_ids=(normalization.id,),
            registration_deadline=at(100),
            mode=mode,
        )
    )
    return graph


def add_run(
    graph: Graph,
    *,
    task=None,
    sequence=1,
    point=12.0,
    cohort_proof_id=None,
    cohort_token_hash=None,
):
    task = task or graph.task
    attempt = graph.add(
        Attempt(
            task_id=task.id,
            sequence=sequence,
            started_at=at(110 + sequence),
            command_hash=graph.blob("command"),
            code_hash=graph.blob("code"),
            prompt_hash=graph.blob("assembled prompt"),
            execution_policy=task.execution_policy,
            cohort_proof_id=cohort_proof_id,
            cohort_token_hash=cohort_token_hash,
        ),
        at(110 + sequence),
    )
    run = graph.add(
        ForecastRun(
            attempt_id=attempt.id,
            distribution=build_interval_distribution(point, point - 2, point + 2),
            stdout_hash=graph.blob("stdout"),
            stderr_hash=graph.blob("stderr"),
            raw_response_hash=graph.blob(f"response {point}"),
            completed_at=at(200 + sequence),
            execution_policy=task.execution_policy,
            prompt_hash=attempt.prompt_hash,
        ),
        at(201 + sequence),
    )
    result = graph.add(
        AttemptResult(
            attempt_id=attempt.id,
            outcome="succeeded",
            recorded_at=at(202 + sequence),
            completed_at=run.completed_at,
            run_id=run.id,
        ),
        at(202 + sequence),
    )
    return attempt, run, result


def add_resolution(graph: Graph, *, value=12.0):
    body = graph.blob("official resolving response")
    exchange = graph.add(
        SourceExchange(
            source_series_id=graph.source.id,
            url="https://example.test/official",
            retrieved_at=at(500),
            status_code=200,
            body=ArtifactRef(
                sha256=body,
                bytes=len(graph.artifacts[body]),
                media_type="application/json",
            ),
            mode="replay",
        ),
        at(501),
    )
    obs = graph.add(
        ObservationVintage(
            source_series_id=graph.source.id,
            measurement_period="2026-01",
            value=value,
            unit="percent",
            source_exchange_ids=(exchange.id,),
            retrieved_at=at(500),
            accepted_at=at(501),
            parser_version="fixture_v1",
            vintage_policy="first_print",
        ),
        at(501),
    )
    graph.official[obs.id] = Availability(at(500), at(500))
    resolution = graph.add(
        Resolution(
            target_version_id=graph.target.id,
            observation_id=obs.id,
            resolution_policy="first_print",
            validation_version="fixture_v1",
            recorded_at=at(502),
        ),
        at(502),
    )
    return obs, resolution
