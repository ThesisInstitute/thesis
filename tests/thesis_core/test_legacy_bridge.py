from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from thesis_core import legacy
from thesis_core.artifacts import LocalArtifactStore

ROOT = Path(__file__).parents[2]
RUN = (
    ROOT
    / "records/thesis-analyst/2026-08-13"
    / ("2026-08-13t07-07-42z-statbel-health-index-yoy-2026-08")
)


def test_real_sealed_run_preserves_exact_materialized_distribution(tmp_path):
    artifacts = LocalArtifactStore(tmp_path / "cas")
    imported = legacy.import_legacy_run(ROOT, RUN, artifacts)
    descriptor = json.loads(artifacts.read_bytes(imported.descriptor_hash))
    distribution = next(
        e for e in descriptor["artifacts"] if e["path"] == "distribution.json"
    )
    assert (
        artifacts.read_bytes(distribution["sha256"])
        == (RUN / "distribution.json").read_bytes()
    )
    assert (
        artifacts.read_bytes(imported.manifest_hash)
        == (RUN / "manifest.json").read_bytes()
    )
    assert (
        artifacts.read_bytes(imported.custody_root_hash)
        == (RUN / "custody_root.json").read_bytes()
    )
    assert imported.trust_class == "legacy_custody_verified"
    assert descriptor["prospective_eligible"] is False
    assert (
        descriptor["loaded_code_hashes"]["scripts/verify_custody.py"]
        == imported.verifier_code_hash
    )


def test_mutation_after_verification_cannot_enter_cas(tmp_path, monkeypatch):
    checkout = tmp_path / "trusted"
    checkout.mkdir()
    run = checkout / "records" / "analyst" / "run"
    shutil.copytree(RUN, run)
    # A real verifier authenticates control files before simulating the race.
    verified = legacy._invoke(ROOT, RUN, legacy._VERIFY_RUN)

    def invoke(*args):
        (run / "distribution.json").write_bytes(b"changed after verification")
        return verified

    monkeypatch.setattr(legacy, "_invoke", invoke)
    with pytest.raises(
        legacy.LegacyImportError, match="changed after custody verification"
    ):
        legacy.import_legacy_run(checkout, run, LocalArtifactStore(tmp_path / "cas"))


def test_legacy_registration_keeps_exact_bytes_and_semantic_hash(tmp_path):
    path = (
        ROOT
        / "records/targets"
        / (
            "2026-07-11-cf3a2f76bb15d9f5eb9f5ae19d2e96b55"
            "111cf6842a1c8c8412b915ae614a85b.json"
        )
    )
    artifacts = LocalArtifactStore(tmp_path / "cas")
    descriptor = legacy.import_legacy_registration(ROOT, path, artifacts)
    assert descriptor["content_hash"] == path.stem[-64:]
    assert artifacts.read_bytes(descriptor["artifact_hash"]) == path.read_bytes()
    assert descriptor["prospective_eligible"] is False


def test_artifact_cannot_choose_a_verifier_checkout(tmp_path):
    with pytest.raises(legacy.LegacyImportError, match="inside trusted records"):
        legacy.import_legacy_registration(
            ROOT, ROOT / "pyproject.toml", LocalArtifactStore(tmp_path / "cas")
        )
