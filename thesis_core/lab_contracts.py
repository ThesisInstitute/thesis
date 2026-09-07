"""Versioned public read projections, separate from immutable scientific records."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    StrictInt,
)

from .contracts import Eligibility, NumericCdf


def _instant(value: str) -> str:
    datetime.fromisoformat(value)
    return value


def _date(value: str) -> str:
    date.fromisoformat(value)
    return value


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Instant = Annotated[
    str,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$",
        json_schema_extra={"format": "date-time"},
    ),
    AfterValidator(_instant),
]
CalendarDate = Annotated[
    str,
    Field(pattern=r"^\d{4}-\d{2}-\d{2}$", json_schema_extra={"format": "date"}),
    AfterValidator(_date),
]
ApiPath = Annotated[
    str, Field(pattern=r"^/(?:lab|records|artifacts)/[A-Za-z0-9_/?=&.-]+$")
]
Count = Annotated[StrictInt, Field(ge=0)]
Positive = Annotated[StrictInt, Field(ge=1)]
Metric = Annotated[FiniteFloat, Field(ge=0)]
LabMode = Literal["prospective", "replay", "live_pilot"]
LabEligibilityCode = (
    Eligibility
    | Literal[
        "awaiting_resolution",
        "no_selected_run",
    ]
)


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Envelope(DTO):
    schema_version: Literal["thesis_lab_v1"]
    generated_at: Instant


class RecordLink(DTO):
    id: Digest
    kind: str
    record_path: ApiPath


class ArtifactLink(DTO):
    sha256: Digest
    bytes: Count | None
    media_type: str | None
    role: str
    download_path: ApiPath


class Cost(DTO):
    amount: None
    currency: None
    state: Literal["not_reported"]


class ModeCounts(DTO):
    prospective: Count
    replay: Count
    live_pilot: Count


class AgentIdentity(DTO):
    id: Digest
    label: str
    provider: str
    model_request: str
    observed_model: str | None
    agent_version: str
    harness_version: str


class AttemptCounts(DTO):
    total: Count
    succeeded: Count
    failed: Count
    unknown: Count
    pending: Count
    reconciled: Count
    unknown_history: Count


class Coverage(DTO):
    declared_targets: Count
    declared_tasks: Count
    selected_tasks: Count
    succeeded_tasks: Count
    failed_tasks: Count
    unknown_tasks: Count
    queued_tasks: Count
    running_tasks: Count
    not_scheduled_tasks: Count
    invalid_tasks: Count
    resolved_targets: Count
    eligible_tasks: Count
    paired_targets: Count


class ReleaseSummary(DTO):
    state: Literal["verified", "unknown", "invalid"]
    lower: Instant | None
    upper: Instant | None
    raw_value: str | None
    timezone: str | None
    official_url: str | None
    evidence: ArtifactLink | None


class ResolutionSummary(DTO):
    state: Literal["pending", "resolved", "invalid"]
    resolution: RecordLink | None
    observation: RecordLink | None
    value: FiniteFloat | None
    unit: str
    recorded_at: Instant | None
    reason_code: Literal["invalid_resolution"] | None


class EligibilitySummary(DTO):
    state: Literal["not_assessed", "eligible", "ineligible"]
    reason_codes: list[LabEligibilityCode]
    ranking_allowed: bool
    reward: FiniteFloat | None


class ScoreSummary(DTO):
    score: RecordLink | None
    crps: Metric | None
    normalized_crps: Metric | None
    pit: Annotated[FiniteFloat, Field(ge=0, le=1)] | None
    scoring_version: str | None
    eligibility: EligibilitySummary


class ExecutionSummary(DTO):
    state: Literal[
        "not_scheduled",
        "queued",
        "running",
        "succeeded",
        "failed",
        "unknown",
        "invalid",
    ]
    attempt_counts: AttemptCounts
    elapsed_seconds: Metric | None
    elapsed_basis: Literal["recorded_attempt_elapsed"] | None
    cost: Cost
    attempts_path: ApiPath | None


class Quantiles(DTO):
    method: Literal["inverse_piecewise_linear_cdf_v1"]
    q10: FiniteFloat
    q50: FiniteFloat
    q90: FiniteFloat


class SourceIdentity(DTO):
    id: Digest
    name: str
    adapter_id: str


class ForecastSummary(DTO):
    id: Digest
    title: str
    source: SourceIdentity
    measurement_period: str
    unit: str
    mode_counts: ModeCounts
    experiment_count: Count
    coverage: Coverage
    resolution: ResolutionSummary
    release: ReleaseSummary


class ForecastDetail(Envelope, ForecastSummary):
    target: RecordLink
    target_label: str
    resolution_rule: str
    resolution_policy: str
    vintage_date: CalendarDate | None
    submission_deadline: Instant
    source_record: RecordLink
    experiments_path: ApiPath
    comparisons_path: ApiPath
    evidence_links: list[ArtifactLink]


class TaskComparison(DTO):
    task: RecordLink
    target_id: Digest
    experiment_id: Digest
    agent: AgentIdentity
    is_baseline: bool
    mode: LabMode
    execution: ExecutionSummary
    selected_run: RecordLink | None
    distribution: NumericCdf | None
    quantiles: Quantiles | None
    resolution: ResolutionSummary
    score: ScoreSummary
    declared_information_cutoff: Instant
    effective_information_boundary: Instant | None
    submission_deadline: Instant
    evidence_links: list[ArtifactLink]


class ExperimentSummary(DTO):
    id: Digest
    title: str
    hypothesis: None
    mode: LabMode
    baseline: AgentIdentity
    target_count: Count
    agent_count: Count
    registration_deadline: Instant
    coverage: Coverage
    rank_eligible_agent_count: Count


class ExperimentDetail(Envelope, ExperimentSummary):
    record: RecordLink
    ranking_policy: str
    declared_information_cutoff: Instant | None
    effective_information_boundary: Instant | None
    matrix_path: ApiPath
    results_path: ApiPath


class MatrixColumn(DTO):
    forecaster_id: Digest
    agent: AgentIdentity
    is_baseline: bool


class MatrixCell(DTO):
    target_id: Digest
    forecaster_id: Digest
    task: RecordLink | None
    mode: LabMode
    execution: ExecutionSummary
    selected_run: RecordLink | None
    quantiles: Quantiles | None
    resolution: ResolutionSummary
    score: ScoreSummary
    declared_information_cutoff: Instant | None
    effective_information_boundary: Instant | None
    submission_deadline: Instant | None
    comparison_path: ApiPath


class MatrixRow(DTO):
    target_id: Digest
    title: str
    measurement_period: str
    unit: str
    forecast_path: ApiPath
    cells: list[MatrixCell]


class MatrixPage(Envelope):
    experiment_id: Digest
    experiment_title: str
    mode: LabMode
    columns: list[MatrixColumn]
    rows: list[MatrixRow]
    total_targets: Count
    total_methods: Count
    next_cursor: Digest | None
    next_method_cursor: Digest | None


class AttemptResultItem(DTO):
    record: RecordLink
    outcome: Literal["succeeded", "failed", "unknown"]
    recorded_at: Instant
    completed_at: Instant | None
    exit_code: StrictInt | None
    run: RecordLink | None
    reconciles_result_id: Digest | None
    reconciliation_method: Literal["sealed_artifacts", "no_sealed_result"] | None
    reconciliation_verified: bool | None
    evidence_links: list[ArtifactLink]


class AttemptItem(DTO):
    id: Digest
    record: RecordLink
    task_id: Digest
    sequence: Positive
    started_at: Instant
    execution_policy: Literal["operator_subprocess", "baseline"]
    outcome: Literal["pending", "succeeded", "failed", "unknown"]
    selected: bool
    selected_run: RecordLink | None
    observed_model: str | None
    elapsed_seconds: Metric | None
    elapsed_basis: Literal["recorded_attempt_elapsed"] | None
    cost: Cost
    results: list[AttemptResultItem]
    evidence_links: list[ArtifactLink]


class AgentSummary(AgentIdentity):
    experiment_count: Count
    declared_task_count: Count
    attempt_counts: AttemptCounts


class AgentDetail(Envelope, AgentSummary):
    record: RecordLink
    inference_settings: dict[str, JsonValue]
    execution_policy: Literal["operator_subprocess", "baseline"]
    aggregation: Literal["none"]
    retry_policy: Literal["known_failure", "none"]
    prompt_template: ArtifactLink
    system_prompt: ArtifactLink
    briefing: ArtifactLink | None
    tool_policy: ArtifactLink
    experiments_path: ApiPath


class ExperimentResult(DTO):
    experiment_id: Digest
    experiment_title: str
    forecaster_id: Digest
    agent: AgentIdentity
    is_baseline: bool
    mode: LabMode
    rank: Positive | None
    rank_eligible: bool
    paired_coverage: Count
    targets: Count
    mean_normalized_crps: Metric | None
    attempt_counts: AttemptCounts
    mean_elapsed_seconds: Metric | None
    elapsed_sample_count: Count
    cost: Cost
    exclusions: list[LabEligibilityCode]


class JobCounts(DTO):
    pending: Count
    leased: Count
    complete: Count
    failed: Count
    unknown: Count
    expired_leases: Count


class DatabaseStatus(DTO):
    state: Literal["available"]
    checked_at: Instant


class WorkerStatus(DTO):
    state: Literal["unknown", "observed_active", "stale"]
    last_activity_at: Instant | None
    basis: Literal["job_lease_observation", "not_reported"]


class PollWorkerStatus(DTO):
    status: Literal["never_seen", "recent", "stale"]
    last_poll_at: Instant | None


class PollingSummary(DTO):
    state: Literal["not_scheduled", "scheduled", "stale", "unknown"]
    scheduled_sources: Count
    next_poll_at: Instant | None
    last_success_at: Instant | None
    worker: PollWorkerStatus


AttentionCode = Literal[
    "capture_not_scheduled",
    "capture_stale",
    "release_passed_unresolved",
    "resolution_invalid",
    "job_failed",
    "attempt_unknown",
]
RecoveryCode = Literal[
    "schedule_capture",
    "inspect_capture",
    "inspect_resolution",
    "inspect_jobs",
    "reconcile_attempt",
]


class OperationTarget(DTO):
    target_id: Digest
    title: str
    release: ReleaseSummary
    resolution: ResolutionSummary
    polling_state: Literal["not_scheduled", "active", "resolved", "overdue", "paused"]
    next_poll_at: Instant | None
    last_success_at: Instant | None
    attention_codes: list[AttentionCode]
    recovery_action_codes: list[RecoveryCode]


class OperationsSummary(Envelope):
    database: DatabaseStatus
    jobs: JobCounts
    worker: WorkerStatus
    polling: PollingSummary
    items: list[OperationTarget]
    total: Count
    next_cursor: Digest | None


class ForecastPage(Envelope):
    items: list[ForecastSummary]
    total: Count
    next_cursor: Digest | None


class ExperimentPage(Envelope):
    items: list[ExperimentSummary]
    total: Count
    next_cursor: Digest | None


class ComparisonPage(Envelope):
    items: list[TaskComparison]
    total: Count
    next_cursor: Digest | None


class AttemptPage(Envelope):
    items: list[AttemptItem]
    total: Count
    next_cursor: Digest | None


class AgentPage(Envelope):
    items: list[AgentSummary]
    total: Count
    next_cursor: Digest | None


class ExperimentResultPage(Envelope):
    items: list[ExperimentResult]
    total: Count
    next_cursor: Digest | None


RESPONSE_MODELS = (
    ForecastPage,
    ForecastDetail,
    ExperimentPage,
    ExperimentDetail,
    ComparisonPage,
    MatrixPage,
    AttemptPage,
    AgentPage,
    AgentDetail,
    ExperimentResultPage,
    OperationsSummary,
)
