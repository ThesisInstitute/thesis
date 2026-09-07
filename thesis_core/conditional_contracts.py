"""Exploratory paired forecasts; never scientific registration or scoring records."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, FiniteFloat, field_validator, model_validator

from .canonical import canonical_sha256
from .contracts import ArtifactRef, FrozenModel, NumericCdf, Sha256, Text, UtcDatetime

Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,95}$")]


class ConditionalSource(FrozenModel):
    id: Slug
    title: Text
    url: Text
    retrieved_at: UtcDatetime
    artifact: ArtifactRef

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("source must use a public HTTPS URL without credentials")
        return value


class ConditionalHistory(FrozenModel):
    period: Text
    value: FiniteFloat
    source_id: Slug


class ConditionalEvidence(FrozenModel):
    claim: Text
    source_ids: tuple[Slug, ...] = Field(min_length=1)


class ConditionalOutcome(FrozenModel):
    name: Text
    country: Text
    geography: Text
    population: Text
    measure: Text
    measurement_period: Text
    unit: Text
    resolution_rule: Text
    resolution_source_url: Text
    release_date: str | None

    @field_validator("release_date")
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            from datetime import date

            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("release date must be ISO calendar date")
        return value

    @field_validator("resolution_source_url")
    @classmethod
    def public_url(cls, value):
        return ConditionalSource.public_url(value)


class ConditionalArmSpec(FrozenModel):
    id: Slug
    label: Text
    condition: Text
    assumptions: tuple[Text, ...]


class ConditionalContract(FrozenModel):
    schema_version: Literal["thesis_conditional_contract_v1"] = (
        "thesis_conditional_contract_v1"
    )
    title: Text
    question: Text
    outcome: ConditionalOutcome
    arms: tuple[ConditionalArmSpec, ConditionalArmSpec]
    reference_description: Text
    condition_deadline: UtcDatetime
    condition_resolution_note: Text
    exhaustive: bool
    shared_history: tuple[ConditionalHistory, ...] = Field(min_length=1)
    sources: tuple[ConditionalSource, ...] = Field(min_length=1)
    shared_evidence: tuple[ConditionalEvidence, ...] = Field(min_length=1)
    limitations: tuple[Text, ...] = Field(min_length=1)
    methodology: Literal["paired_conditional_v1"] = "paired_conditional_v1"
    status: Literal["exploratory"] = "exploratory"
    scoring_status: Literal["not_registered"] = "not_registered"
    trust_class: Literal["local_operator"] = "local_operator"

    @model_validator(mode="after")
    def coherent(self):
        if self.arms[0].id == self.arms[1].id:
            raise ValueError("conditional arms must have distinct identities")
        ids = {source.id for source in self.sources}
        if len(ids) != len(self.sources):
            raise ValueError("source identities must be unique")
        if len({item.period for item in self.shared_history}) != len(
            self.shared_history
        ):
            raise ValueError("shared history cannot duplicate periods")
        references = {item.source_id for item in self.shared_history}
        references.update(
            source for item in self.shared_evidence for source in item.source_ids
        )
        if not references.issubset(ids):
            raise ValueError("shared evidence references an unknown source")
        return self


class ConditionalArmForecast(FrozenModel):
    id: Slug
    baseline_delta: FiniteFloat
    distribution: NumericCdf
    reasoning: Text


class PairedModelResponse(FrozenModel):
    contract_id: Sha256
    shared_evidence_id: Sha256
    reference: NumericCdf
    reference_reasoning: Text
    arms: tuple[ConditionalArmForecast, ConditionalArmForecast]


class ConditionalArtifact(FrozenModel):
    role: Text
    artifact: ArtifactRef


class ConditionalAttempt(FrozenModel):
    id: Sha256
    contract_id: Sha256
    shared_evidence_id: Sha256
    requested_model: Text
    observed_model: None = None
    started_at: UtcDatetime
    expires_at: UtcDatetime
    artifacts: tuple[ConditionalArtifact, ...]


def contract_id(contract: ConditionalContract) -> str:
    return canonical_sha256(contract.model_dump(mode="json", by_alias=True))


def shared_evidence_id(contract: ConditionalContract) -> str:
    payload = contract.model_dump(mode="json", by_alias=True)
    return canonical_sha256(
        {key: payload[key] for key in ("sources", "shared_history", "shared_evidence")}
    )


def validate_response(
    contract: ConditionalContract, response: PairedModelResponse
) -> None:
    from .lab import display_quantiles

    if response.contract_id != contract_id(
        contract
    ) or response.shared_evidence_id != shared_evidence_id(contract):
        raise ValueError("paired response does not match its frozen inputs")
    if tuple(arm.id for arm in response.arms) != tuple(arm.id for arm in contract.arms):
        raise ValueError("paired arm identity or order mismatch")
    distributions = (response.reference, *(arm.distribution for arm in response.arms))
    quantiles = []
    tolerance = Decimal("0.00000001")
    for distribution in distributions:
        if distribution.provenance != "agent_reported":
            raise ValueError(
                "conditional distributions must be directly agent reported"
            )
        if distribution.transform_version != "native_conditional_v1":
            raise ValueError(
                "conditional distribution transform version is unsupported"
            )
        q = display_quantiles(distribution)
        quantiles.append(q)
        summary = distribution.summary
        for actual, expected in (
            (summary.point_estimate, q["q50"]),
            (summary.median, q["q50"]),
            (summary.interval80.lower, q["q10"]),
            (summary.interval80.upper, q["q90"]),
        ):
            if abs(Decimal(str(actual)) - Decimal(str(expected))) > tolerance:
                raise ValueError("reported CDF summary disagrees with original points")
    for arm, q in zip(response.arms, quantiles[1:]):
        delta = Decimal(str(q["q50"])) - Decimal(str(quantiles[0]["q50"]))
        if abs(Decimal(str(arm.baseline_delta)) - delta) > tolerance:
            raise ValueError("arm delta differs from shared reference median")
