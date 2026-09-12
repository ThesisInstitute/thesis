"""Strict immutable scientific records and one dependency/artifact registry."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from .canonical import canonical_bytes, canonical_sha256

Sha256 = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(ge=1)]
FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
Mode = Literal["prospective", "replay"]
ExecutionPolicy = Literal["operator_subprocess", "baseline"]
VintagePolicy = Literal["first_print", "fixed_vintage", "current_unverified"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must have an explicit timezone")
    return value.astimezone(timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_utc)]


def _check_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite scientific value")
    if type(value) is int and abs(value) > 2**53 - 1:
        raise ValueError("integer exceeds exact JSON Number range")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON keys must be strings")
            _check_json(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _check_json(item)


class FrozenModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        populate_by_name=True,
        hide_input_in_errors=True,
    )


class ArtifactRef(FrozenModel):
    sha256: Sha256
    bytes: Annotated[StrictInt, Field(ge=0)]
    media_type: Text


class PublicationTimingEvidence(FrozenModel):
    """Parsing claim authenticated only by reopening the source artifact."""

    raw_value: Text
    timezone: Text
    source_url: Text
    parser_version: Text
    artifact: ArtifactRef


class ReleaseEvidence(PublicationTimingEvidence):
    pass


class CdfPoint(FrozenModel):
    value: FiniteFloat
    probability: FiniteFloat


class CdfSupport(FrozenModel):
    lower: FiniteFloat
    upper: FiniteFloat


class CdfSummary(FrozenModel):
    point_estimate: FiniteFloat = Field(alias="pointEstimate")
    median: FiniteFloat
    interval80: CdfSupport


class NumericCdf(FrozenModel):
    """Sealed 201-point wire format; never rematerialized on ingestion."""

    format: Literal["numeric_cdf_v1"] = "numeric_cdf_v1"
    point_count: Literal[201] = Field(default=201, alias="pointCount")
    support: CdfSupport
    points: tuple[CdfPoint, ...]
    summary: CdfSummary
    provenance: Literal["agent_reported", "interval_seeded"]
    transform_version: Text = Field(alias="transformVersion")

    @model_validator(mode="after")
    def valid_cdf(self) -> NumericCdf:
        if len(self.points) != 201:
            raise ValueError("numeric_cdf_v1 requires exactly 201 points")
        if (
            self.support.lower != self.points[0].value
            or self.support.upper != self.points[-1].value
        ):
            raise ValueError("CDF support must equal endpoint values")
        for index, point in enumerate(self.points):
            if not 0 <= point.probability <= 1:
                raise ValueError("CDF probability outside [0,1]")
            if index and (
                point.value <= self.points[index - 1].value
                or point.probability < self.points[index - 1].probability
            ):
                raise ValueError(
                    "CDF values must increase; probabilities cannot decrease"
                )
        if self.points[0].probability != 0 or self.points[-1].probability != 1:
            raise ValueError("CDF endpoint probabilities must be 0 and 1")
        if (
            not self.summary.interval80.lower
            <= self.summary.median
            <= self.summary.interval80.upper
        ):
            raise ValueError("CDF summary interval is inverted")
        return self


NumericCdfDistribution = NumericCdf


class ScientificRecord(FrozenModel):
    kind: str
    schema_version: Literal[1] = 1
    artifact_fields: ClassVar[tuple[str, ...]] = ()
    _snapshot: bytes = PrivateAttr(default=b"")

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value: Any) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("unsupported scientific schema version")
        return value

    def model_post_init(self, context: Any) -> None:
        payload = self.model_dump(mode="json", by_alias=True)
        _check_json(payload)
        self._snapshot = canonical_bytes(payload)

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", by_alias=True)
        _check_json(payload)
        if canonical_bytes(payload) != self._snapshot:
            raise ValueError("nested scientific data mutated after validation")
        return payload

    def canonical_bytes(self) -> bytes:
        self.canonical_payload()
        return self._snapshot

    @property
    def id(self) -> str:
        return canonical_sha256(self.canonical_payload())


class SourceSeries(ScientificRecord):
    kind: Literal["source_series"] = "source_series"
    adapter_id: Text
    adapter_version: Text
    name: Text
    unit: Text
    binding: dict[str, JsonValue]
    vintage_policies: tuple[VintagePolicy, ...]


class SourceExchange(ScientificRecord):
    kind: Literal["source_exchange"] = "source_exchange"
    source_series_id: Sha256
    url: Text
    retrieved_at: UtcDatetime
    status_code: Annotated[StrictInt, Field(ge=100, le=599)]
    body: ArtifactRef
    response_headers: dict[str, StrictStr] = Field(default_factory=dict)
    request_method: Literal["GET", "POST"] = "GET"
    request_body: ArtifactRef | None = None
    role: Literal["data", "release"] = "data"
    mode: Literal["live", "replay"]


class TargetVersion(ScientificRecord):
    kind: Literal["target_version"] = "target_version"
    target_id: Text
    source_series_id: Sha256
    measurement_period: Text
    unit: Text
    resolution_policy: VintagePolicy
    resolution_rule: Text
    submission_deadline: UtcDatetime
    release_evidence: ReleaseEvidence | None = None
    vintage_date: Annotated[StrictStr, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None = (
        None
    )

    @model_validator(mode="after")
    def exact_vintage(self) -> TargetVersion:
        if self.resolution_policy == "fixed_vintage" and self.vintage_date is None:
            raise ValueError("fixed vintage requires a machine-readable vintage_date")
        if self.vintage_date is not None:
            from datetime import date

            date.fromisoformat(self.vintage_date)
        return self


class ForecasterVersion(ScientificRecord):
    kind: Literal["forecaster_version"] = "forecaster_version"
    provider: Text
    model_request: Text
    observed_model: Text | None = None
    inference_settings: dict[str, JsonValue] = Field(default_factory=dict)
    agent_version: Text
    harness_version: Text
    prompt_template_hash: Sha256
    system_prompt_hash: Sha256
    briefing_hash: Sha256 | None = None
    tool_policy_hash: Sha256
    aggregation: Literal["none"] = "none"
    retry_policy: Literal["known_failure", "none"] = "known_failure"
    execution_policy: ExecutionPolicy
    artifact_fields = (
        "prompt_template_hash",
        "system_prompt_hash",
        "briefing_hash",
        "tool_policy_hash",
    )

    @field_validator("inference_settings")
    @classmethod
    def public_configuration(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        from .security import redact_value

        if redact_value(value) != value:
            raise ValueError(
                "credential-bearing inference settings cannot be published"
            )
        return value


class ObservationVintage(ScientificRecord):
    kind: Literal["observation"] = "observation"
    source_series_id: Sha256
    measurement_period: Text
    value: FiniteFloat
    unit: Text
    source_exchange_ids: tuple[Sha256, ...]
    retrieved_at: UtcDatetime
    accepted_at: UtcDatetime
    parser_version: Text
    vintage_policy: VintagePolicy
    publication_evidence: PublicationTimingEvidence | None = None


class EvidenceBundle(ScientificRecord):
    kind: Literal["evidence_bundle"] = "evidence_bundle"
    source_series_id: Sha256
    observation_ids: tuple[Sha256, ...]
    artifact_refs: tuple[ArtifactRef, ...]
    information_cutoff: UtcDatetime
    policy_version: Literal["accepted_and_available_v1"] = "accepted_and_available_v1"
    mode: Mode


class NormalizationRecord(ScientificRecord):
    kind: Literal["normalization"] = "normalization"
    target_version_id: Sha256
    source_series_id: Sha256
    observation_ids: tuple[Sha256, ...]
    information_cutoff: UtcDatetime
    calculation_version: Literal["step_dispersion_floor_v1"] = (
        "step_dispersion_floor_v1"
    )
    scale: Annotated[FiniteFloat, Field(gt=0)] | None
    unavailable_reason: Text | None = None

    @model_validator(mode="after")
    def scale_reason(self) -> NormalizationRecord:
        if (self.scale is None) != (self.unavailable_reason is not None):
            raise ValueError("unavailable normalization requires exactly one reason")
        return self


class EvaluationTask(ScientificRecord):
    kind: Literal["evaluation_task"] = "evaluation_task"
    target_version_id: Sha256
    forecaster_version_id: Sha256
    evidence_bundle_id: Sha256
    information_cutoff: UtcDatetime
    submission_deadline: UtcDatetime
    max_attempts: PositiveInt = 1
    selection_rule: Literal["first_valid"] = "first_valid"
    execution_policy: ExecutionPolicy
    mode: Mode

    @model_validator(mode="after")
    def ordered_times(self) -> EvaluationTask:
        if self.information_cutoff >= self.submission_deadline:
            raise ValueError("information cutoff must precede submission deadline")
        return self


class Experiment(ScientificRecord):
    kind: Literal["experiment"] = "experiment"
    task_ids: tuple[Sha256, ...]
    target_version_ids: tuple[Sha256, ...]
    forecaster_version_ids: tuple[Sha256, ...]
    baseline_forecaster_id: Sha256
    normalization_ids: tuple[Sha256, ...] = ()
    registration_deadline: UtcDatetime
    mode: Mode
    ranking_policy: Literal["complete_paired_normalized_crps_v1"] = (
        "complete_paired_normalized_crps_v1"
    )

    @model_validator(mode="after")
    def unique_members(self) -> Experiment:
        for name in (
            "task_ids",
            "target_version_ids",
            "forecaster_version_ids",
            "normalization_ids",
        ):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"duplicate {name}")
        if (
            not self.task_ids
            or not self.target_version_ids
            or not self.forecaster_version_ids
        ):
            raise ValueError("experiment membership cannot be empty")
        if self.baseline_forecaster_id not in self.forecaster_version_ids:
            raise ValueError("baseline must be a declared forecaster")
        return self


class Attempt(ScientificRecord):
    kind: Literal["attempt"] = "attempt"
    task_id: Sha256
    sequence: PositiveInt
    started_at: UtcDatetime
    command_hash: Sha256
    code_hash: Sha256
    prompt_hash: Sha256
    execution_policy: ExecutionPolicy
    cohort_proof_id: Sha256 | None = None
    cohort_token_hash: Sha256 | None = None
    artifact_fields = ("command_hash", "code_hash", "prompt_hash", "cohort_token_hash")

    @model_validator(mode="after")
    def bound_receipt(self) -> Attempt:
        if (self.cohort_proof_id is None) != (self.cohort_token_hash is None):
            raise ValueError("cohort proof ID and token hash must appear together")
        return self


class ForecastRun(ScientificRecord):
    kind: Literal["forecast_run"] = "forecast_run"
    attempt_id: Sha256
    distribution: NumericCdf
    stdout_hash: Sha256
    stderr_hash: Sha256
    raw_response_hash: Sha256
    completed_at: UtcDatetime
    observed_model: Text | None = None
    execution_policy: ExecutionPolicy
    prompt_hash: Sha256
    artifact_fields = ("stdout_hash", "stderr_hash", "raw_response_hash", "prompt_hash")


class AttemptResult(ScientificRecord):
    kind: Literal["attempt_result"] = "attempt_result"
    attempt_id: Sha256
    outcome: Literal["succeeded", "failed", "unknown"]
    recorded_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    exit_code: StrictInt | None = None
    stdout_hash: Sha256 | None = None
    stderr_hash: Sha256 | None = None
    raw_response_hash: Sha256 | None = None
    run_id: Sha256 | None = None
    reconciles_result_id: Sha256 | None = None
    reconciliation_method: Literal["sealed_artifacts", "no_sealed_result"] | None = None
    reconciled_by: Text | None = None
    reconciliation_reason: Text | None = None
    reconciliation_evidence_hashes: tuple[Sha256, ...] = ()
    artifact_fields = (
        "stdout_hash",
        "stderr_hash",
        "raw_response_hash",
        "reconciliation_evidence_hashes",
    )

    @model_validator(mode="after")
    def result_shape(self) -> AttemptResult:
        if self.outcome == "succeeded" and (
            self.run_id is None or self.completed_at is None
        ):
            raise ValueError("successful result requires its run and completion time")
        if self.outcome != "succeeded" and self.run_id is not None:
            raise ValueError("only successful results may name a run")
        if self.outcome == "unknown" and (
            self.completed_at is not None or self.exit_code is not None
        ):
            raise ValueError("unknown outcome cannot claim completion")
        reconciliation = (
            self.reconciliation_method,
            self.reconciled_by,
            self.reconciliation_reason,
        )
        if self.reconciles_result_id is not None:
            if (
                any(item is None for item in reconciliation)
                or self.outcome == "unknown"
            ):
                raise ValueError(
                    "reconciliation needs terminal result, actor and reason"
                )
            if (
                self.reconciliation_method == "no_sealed_result"
                and self.outcome != "failed"
            ):
                raise ValueError("no sealed result cannot prove nonexecution")
        elif (
            any(item is not None for item in reconciliation)
            or self.reconciliation_evidence_hashes
        ):
            raise ValueError("reconciliation fields require an unknown predecessor")
        return self


class PublicationManifest(ScientificRecord):
    kind: Literal["publication_manifest"] = "publication_manifest"
    manifest_type: Literal["cohort", "run"]
    experiment_id: Sha256
    run_id: Sha256 | None = None
    artifacts: tuple[Sha256, ...]
    code_hash: Sha256
    recorded_at: UtcDatetime
    cohort_proof_id: Sha256 | None = None
    cohort_token_hash: Sha256 | None = None
    attempt_result_ids: tuple[Sha256, ...] = ()
    declared_information_cutoff: UtcDatetime
    effective_information_boundary: UtcDatetime
    artifact_fields = ("artifacts", "code_hash", "cohort_token_hash")

    @model_validator(mode="after")
    def manifest_shape(self) -> PublicationManifest:
        if (self.manifest_type == "run") != (self.run_id is not None):
            raise ValueError(
                "run manifests require run_id; cohort manifests cannot name a run"
            )
        if self.manifest_type == "cohort" and self.cohort_proof_id is not None:
            raise ValueError("cohort manifest cannot reference its future proof")
        if self.manifest_type == "cohort" and self.attempt_result_ids:
            raise ValueError("cohort manifest cannot reference future attempt results")
        if (self.cohort_proof_id is None) != (self.cohort_token_hash is None):
            raise ValueError("cohort receipt references must appear together")
        if len(set(self.artifacts)) != len(self.artifacts):
            raise ValueError("duplicate manifest artifacts")
        return self


class PublicationProof(ScientificRecord):
    """Metadata is descriptive; verification always replays raw receipt bytes."""

    kind: Literal["publication_proof"] = "publication_proof"
    manifest_id: Sha256
    request_hash: Sha256
    token_hash: Sha256
    subject_hash: Sha256
    trust_bundle_path: Text
    trust_bundle_hash: Sha256
    trust_anchor_id: Text
    gen_time: UtcDatetime
    accuracy_micros: Annotated[StrictInt, Field(ge=0)] | None
    signer_identity: Text
    policy_oid: Text
    verification_version: Text
    verified_at: UtcDatetime
    artifact_fields = (
        "request_hash",
        "token_hash",
        "subject_hash",
        "trust_bundle_hash",
    )


class Resolution(ScientificRecord):
    kind: Literal["resolution"] = "resolution"
    target_version_id: Sha256
    observation_id: Sha256
    resolution_policy: VintagePolicy
    validation_version: Text
    recorded_at: UtcDatetime


Eligibility = Literal[
    "eligible",
    "replay",
    "invalid_contract",
    "invalid_resolution",
    "missing_artifact",
    "missing_acknowledgement",
    "evidence_unavailable",
    "invalid_normalization",
    "unresolved_attempt",
    "not_selected",
    "late_attempt_reconciliation",
    "outcome_availability_unknown",
    "invalid_publication",
    "late_publication",
    "missing_cohort_proof",
    "invalid_cohort",
    "late_cohort",
    "execution_policy_mismatch",
]


class ScoreRecord(ScientificRecord):
    kind: Literal["score"] = "score"
    run_id: Sha256
    resolution_id: Sha256
    experiment_id: Sha256
    normalization_id: Sha256 | None = None
    publication_proof_id: Sha256 | None = None
    attempt_result_ids: tuple[Sha256, ...] = ()
    scoring_version: Literal["piecewise_linear_crps_v1"] = "piecewise_linear_crps_v1"
    eligibility: Eligibility
    crps: Annotated[FiniteFloat, Field(ge=0)] | None
    pit: FiniteFloat | None
    normalized_crps: Annotated[FiniteFloat, Field(ge=0)] | None
    reward: FiniteFloat | None
    # No creation clock: repeated evaluations of identical inputs are idempotent.


class LegacyImport(ScientificRecord):
    kind: Literal["legacy_import"] = "legacy_import"
    trust_class: Literal["legacy_custody_verified"] = "legacy_custody_verified"
    verifier_revision: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{40}$")]
    verifier_code_hash: Sha256
    custody_root_hash: Sha256
    manifest_hash: Sha256
    descriptor_hash: Sha256
    artifact_hashes: tuple[Sha256, ...]
    registration_hashes: tuple[Sha256, ...] = ()
    artifact_fields = (
        "verifier_code_hash",
        "custody_root_hash",
        "manifest_hash",
        "descriptor_hash",
        "artifact_hashes",
    )


@dataclass(frozen=True)
class LinkSpec:
    field: str
    target_kind: str
    relation: str
    many: bool = False
    required: bool = True


@dataclass(frozen=True)
class RecordLink:
    field_path: str
    relation: str
    target_id: str
    target_kind: str


RECORD_TYPES: dict[str, type[ScientificRecord]] = {
    cls.model_fields["kind"].default: cls
    for cls in (
        SourceSeries,
        SourceExchange,
        TargetVersion,
        ForecasterVersion,
        ObservationVintage,
        EvidenceBundle,
        NormalizationRecord,
        EvaluationTask,
        Experiment,
        Attempt,
        ForecastRun,
        AttemptResult,
        PublicationManifest,
        PublicationProof,
        Resolution,
        ScoreRecord,
        LegacyImport,
    )
}


def _link(
    field: str, kind: str, *, many: bool = False, required: bool = True
) -> LinkSpec:
    return LinkSpec(
        field, kind, field.removesuffix("_ids").removesuffix("_id"), many, required
    )


LINK_SPECS: dict[str, tuple[LinkSpec, ...]] = {
    "source_series": (),
    "forecaster_version": (),
    "legacy_import": (),
    "source_exchange": (_link("source_series_id", "source_series"),),
    "target_version": (_link("source_series_id", "source_series"),),
    "observation": (
        _link("source_series_id", "source_series"),
        _link("source_exchange_ids", "source_exchange", many=True),
    ),
    "evidence_bundle": (
        _link("source_series_id", "source_series"),
        _link("observation_ids", "observation", many=True),
    ),
    "normalization": (
        _link("target_version_id", "target_version"),
        _link("source_series_id", "source_series"),
        _link("observation_ids", "observation", many=True),
    ),
    "evaluation_task": (
        _link("target_version_id", "target_version"),
        _link("forecaster_version_id", "forecaster_version"),
        _link("evidence_bundle_id", "evidence_bundle"),
    ),
    "experiment": (
        _link("task_ids", "evaluation_task", many=True),
        _link("target_version_ids", "target_version", many=True),
        _link("forecaster_version_ids", "forecaster_version", many=True),
        _link("baseline_forecaster_id", "forecaster_version"),
        _link("normalization_ids", "normalization", many=True),
    ),
    "attempt": (
        _link("task_id", "evaluation_task"),
        _link("cohort_proof_id", "publication_proof", required=False),
    ),
    "forecast_run": (_link("attempt_id", "attempt"),),
    "attempt_result": (
        _link("attempt_id", "attempt"),
        _link("run_id", "forecast_run", required=False),
        _link("reconciles_result_id", "attempt_result", required=False),
    ),
    "publication_manifest": (
        _link("experiment_id", "experiment"),
        _link("run_id", "forecast_run", required=False),
        _link("cohort_proof_id", "publication_proof", required=False),
        _link("attempt_result_ids", "attempt_result", many=True),
    ),
    "publication_proof": (_link("manifest_id", "publication_manifest"),),
    "resolution": (
        _link("target_version_id", "target_version"),
        _link("observation_id", "observation"),
    ),
    "score": (
        _link("publication_proof_id", "publication_proof", required=False),
        _link("attempt_result_ids", "attempt_result", many=True),
        _link("run_id", "forecast_run"),
        _link("resolution_id", "resolution"),
        _link("experiment_id", "experiment"),
        _link("normalization_id", "normalization", required=False),
    ),
}


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_record(
    kind: str, payload: Mapping[str, Any] | bytes | str
) -> ScientificRecord:
    cls = RECORD_TYPES.get(kind)
    if cls is None:
        raise ValueError(f"unknown scientific record kind: {kind}")
    value = (
        json.loads(payload, object_pairs_hook=_unique_pairs)
        if isinstance(payload, (bytes, str))
        else dict(payload)
    )
    _check_json(value)
    if value.get("kind", kind) != kind:
        raise ValueError("record kind differs from envelope")
    return cls.model_validate_json(canonical_bytes(value), strict=True)


def record_links(record: ScientificRecord) -> tuple[RecordLink, ...]:
    record.canonical_bytes()
    links: list[RecordLink] = []
    for spec in LINK_SPECS[record.kind]:
        value = getattr(record, spec.field)
        if value is None:
            if spec.required:
                raise ValueError(f"missing required link {spec.field}")
            continue
        values = enumerate(value) if spec.many else [(None, value)]
        for index, target_id in values:
            path = f"{spec.field}[{index}]" if index is not None else spec.field
            links.append(RecordLink(path, spec.relation, target_id, spec.target_kind))
    return tuple(links)


def record_artifact_hashes(record: ScientificRecord) -> tuple[str, ...]:
    record.canonical_bytes()
    hashes: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, ArtifactRef):
            hashes.add(value.sha256)
        elif isinstance(value, BaseModel):
            for name in type(value).model_fields:
                walk(getattr(value, name))
        elif isinstance(value, (tuple, list)):
            for item in value:
                walk(item)

    walk(record)
    for name in record.artifact_fields:
        value = getattr(record, name)
        if value is not None:
            hashes.update(value if isinstance(value, tuple) else (value,))
    return tuple(sorted(hashes))
