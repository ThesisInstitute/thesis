"""Immutable operator assessments and retrospective revision associations."""

from typing import Literal

from pydantic import model_validator

from .conditional_contracts import Slug
from .contracts import ArtifactRef, FrozenModel, Sha256, Text


class ConditionalFinding(FrozenModel):
    id: Slug
    title: Text
    detail: Text
    source_ids: tuple[Slug, ...]
    response_location: Text


class ConditionalReview(FrozenModel):
    schema_version: Literal["conditional_review_v1"] = "conditional_review_v1"
    attempt_id: Sha256
    response_sha256: Sha256
    reviewer: Text
    review_basis: Literal["operator_assessment"] = "operator_assessment"
    outcome: Literal["issues_remaining", "no_actionable_findings"]
    findings: tuple[ConditionalFinding, ...]
    report: ArtifactRef

    @model_validator(mode="after")
    def valid_findings(self):
        if (self.outcome == "issues_remaining") != bool(self.findings):
            raise ValueError("review outcome must agree with its findings")
        if len({finding.id for finding in self.findings}) != len(self.findings):
            raise ValueError("review finding identities must be unique")
        return self


class ConditionalRevision(FrozenModel):
    schema_version: Literal["conditional_revision_v1"] = "conditional_revision_v1"
    parent_attempt_id: Sha256
    revision_attempt_id: Sha256
    contract_id: Sha256
    shared_evidence_id: Sha256
    triggering_review_id: Sha256
    feedback: ArtifactRef
    association_basis: Literal["retrospective_association"] = (
        "retrospective_association"
    )
