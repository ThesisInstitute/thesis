"""One extract_timeline call verifies each custody run once.

Every recorder snapshot recommits every earlier custody root, so the chain's
212 snapshots carried 84,652 root commitments of 591 runs on 2026-10-16. Each
commitment re-ran verify_run over the whole run, which made one call take about
50 minutes in CI. These tests pin the memo that removes the repetition, and
that every per-commitment check still runs when a run's verification is
reused. The live-records golden test in test_record_integrity.py
(witnessed-timeline.json equals a fresh extraction, byte for byte) is the
differential check that the memo changes no output.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import witnessed_timeline as timeline_module  # noqa: E402
from witnessed_timeline import (  # noqa: E402
    TimelineError,
    VerificationMemo,
    _commit_root,
    _validate_registration,
)

ROOT_HASH = "a" * 64


def _run(records: Path, name: str = "run-a") -> dict:
    """A run directory and the commitment a snapshot would make to it."""

    run_dir = records / "2026-10-16" / name
    run_dir.mkdir(parents=True)
    root = run_dir / "custody_root.json"
    manifest = run_dir / "manifest.json"
    root.write_bytes(b'{"custodyInventoryVersion":2}')
    manifest.write_bytes(b'{"schemaVersion":"thesis_analyst_run_manifest_v1"}')
    logical = f"records/2026-10-16/{name}"
    return {
        "runDirectory": logical,
        "custodyRootPath": f"{logical}/custody_root.json",
        "manifestPath": f"{logical}/manifest.json",
        "custodyRootSha256": ROOT_HASH,
        "custodyRootFileSha256": hashlib.sha256(root.read_bytes()).hexdigest(),
        "custodyRootSize": root.stat().st_size,
        "custodyInventoryVersion": 2,
        "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "manifestSize": manifest.stat().st_size,
    }


@pytest.fixture
def verify_calls(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    def fake_verify_run(run_dir: Path) -> SimpleNamespace:
        calls.append(run_dir)
        return SimpleNamespace(
            custody_root_sha256=ROOT_HASH,
            custody_inventory_version=2,
            inventory_status="complete",
            headline_eligible=True,
        )

    monkeypatch.setattr(timeline_module, "verify_run", fake_verify_run)
    return calls


def _commit(records: Path, commitment: dict, memo: VerificationMemo | None) -> None:
    _commit_root(records, commitment, None, None, {}, {}, {}, memo=memo)


def test_a_run_recommitted_by_many_snapshots_is_verified_once(
    tmp_path: Path, verify_calls: list[Path]
) -> None:
    commitment = _run(tmp_path)
    memo = VerificationMemo()
    for _snapshot in range(208):
        _commit(tmp_path, commitment, memo)
    assert len(verify_calls) == 1

    # Without a memo every commitment verifies again, as before.
    for _snapshot in range(3):
        _commit(tmp_path, commitment, None)
    assert len(verify_calls) == 4


def test_distinct_runs_are_each_verified(
    tmp_path: Path, verify_calls: list[Path]
) -> None:
    memo = VerificationMemo()
    commitments = [_run(tmp_path, f"run-{index}") for index in range(5)]
    for _snapshot in range(10):
        for commitment in commitments:
            _commit(tmp_path, commitment, memo)
    assert len(verify_calls) == 5
    assert len(set(verify_calls)) == 5


def test_a_memo_does_not_outlive_its_call(
    tmp_path: Path, verify_calls: list[Path]
) -> None:
    commitment = _run(tmp_path)
    _commit(tmp_path, commitment, VerificationMemo())
    _commit(tmp_path, commitment, VerificationMemo())
    assert len(verify_calls) == 2


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("manifestSha256", "b" * 64, "committed custody manifest mismatch"),
        ("manifestSize", 1, "committed custody manifest mismatch"),
        ("custodyRootFileSha256", "b" * 64, "committed custody root file mismatch"),
        ("custodyRootSize", 1, "committed custody root file mismatch"),
        ("custodyRootSha256", "c" * 64, "custody root identity mismatch"),
        ("custodyInventoryVersion", 1, "custody inventory version mismatch"),
    ],
)
def test_every_commitment_is_still_checked_when_its_run_is_reused(
    tmp_path: Path,
    verify_calls: list[Path],
    field: str,
    value: object,
    message: str,
) -> None:
    commitment = _run(tmp_path)
    memo = VerificationMemo()
    _commit(tmp_path, commitment, memo)
    with pytest.raises(TimelineError, match=message):
        _commit(tmp_path, {**commitment, field: value}, memo)
    assert len(verify_calls) == 1


def test_a_failed_verification_is_not_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commitment = _run(tmp_path)
    calls: list[Path] = []

    def refusing_verify_run(run_dir: Path) -> None:
        calls.append(run_dir)
        raise timeline_module.CustodyError("artifact digest mismatch")

    monkeypatch.setattr(timeline_module, "verify_run", refusing_verify_run)
    memo = VerificationMemo()
    for _attempt in range(2):
        with pytest.raises(TimelineError, match="does not verify"):
            _commit(tmp_path, commitment, memo)
    assert len(calls) == 2
    assert memo.runs == {}


def _registration(records: Path) -> tuple[str, Path, str]:
    path = records / "targets" / "target.json"
    path.parent.mkdir(parents=True)
    raw = json.dumps({"targetId": "t", "version": 1}).encode()
    path.write_bytes(raw)
    return "records/targets/target.json", path, hashlib.sha256(raw).hexdigest()


def test_a_registration_is_validated_once_per_expectation(tmp_path: Path) -> None:
    logical, path, digest = _registration(tmp_path)
    memo = VerificationMemo()
    _validate_registration(tmp_path, logical, raw_sha256=digest, memo=memo)
    path.unlink()
    # The same expectation is answered from the memo, without a read ...
    _validate_registration(tmp_path, logical, raw_sha256=digest, memo=memo)
    # ... but a different expectation, or no memo, reads the file again.
    with pytest.raises(TimelineError, match="absent"):
        _validate_registration(tmp_path, logical, raw_sha256="0" * 64, memo=memo)
    with pytest.raises(TimelineError, match="absent"):
        _validate_registration(tmp_path, logical, raw_sha256=digest)


def test_a_rejected_registration_is_not_remembered(tmp_path: Path) -> None:
    logical, _path, _digest = _registration(tmp_path)
    memo = VerificationMemo()
    for _attempt in range(2):
        with pytest.raises(TimelineError, match="raw SHA-256 mismatch"):
            _validate_registration(tmp_path, logical, raw_sha256="0" * 64, memo=memo)
    assert memo.registrations == set()
