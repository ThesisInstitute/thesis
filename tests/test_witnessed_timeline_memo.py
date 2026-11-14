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

import gzip
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import witnessed_timeline as timeline_module  # noqa: E402
from canonical_json import canonical_sha256  # noqa: E402
from witnessed_timeline import (  # noqa: E402
    TimelineError,
    VerificationMemo,
    _commit_root,
    _root_commitments_from_log,
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


def test_a_run_whose_bytes_changed_mid_call_is_verified_again(
    tmp_path: Path, verify_calls: list[Path]
) -> None:
    """Review of 8c83c3e3 (finding 1): a result is reused only for the root
    and manifest bytes it was computed from."""

    commitment = _run(tmp_path)
    memo = VerificationMemo()
    _commit(tmp_path, commitment, memo)
    manifest = tmp_path / "2026-10-16" / "run-a" / "manifest.json"
    manifest.write_bytes(b'{"schemaVersion":"thesis_analyst_run_manifest_v1","v":2}')
    changed = {
        **commitment,
        "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "manifestSize": manifest.stat().st_size,
    }
    _commit(tmp_path, changed, memo)
    assert len(verify_calls) == 2
    # The original bytes no longer match, so the original commitment refuses.
    with pytest.raises(TimelineError, match="committed custody manifest mismatch"):
        _commit(tmp_path, commitment, memo)


def test_a_manifest_registration_is_checked_against_each_expected_hash(
    tmp_path: Path, verify_calls: list[Path]
) -> None:
    """Two runs name one registration; the second expects another hash.

    The memo answered the first expectation; it must not answer the second.
    """

    logical, _path, _digest = _registration(tmp_path)
    good = timeline_module.canonical_sha256(
        json.loads((tmp_path / "targets" / "target.json").read_bytes())
    )
    memo = VerificationMemo()
    for name, expected in (("run-good", good), ("run-bad", "0" * 64)):
        run_dir = tmp_path / "2026-10-16" / name
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "targetContext": {
                        "targetRegistrationPath": logical,
                        "targetContentHash": expected,
                    }
                }
            )
        )
        if expected == good:
            timeline_module._registration_from_manifest(
                tmp_path, run_dir, None, {}, memo=memo
            )
        else:
            with pytest.raises(TimelineError, match="canonical SHA-256 mismatch"):
                timeline_module._registration_from_manifest(
                    tmp_path, run_dir, None, {}, memo=memo
                )


@pytest.mark.live_records
def test_the_real_verifier_through_the_memo_on_a_committed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Differential with the real verify_run on a real run from records/.

    The latest snapshot's first custody commitment goes through _commit_root
    three times: twice with one memo and once without. The real verifier
    runs twice in all (once per memo-less call, once for the memo), and
    every pass accepts the commitment against the real bytes.
    """

    records = ROOT / "records"
    latest = None
    for path in sorted(records.glob("*/digest-*.json")):
        if path.name.endswith(".witness.json"):
            continue
        digest = json.loads(path.read_bytes())
        custody = (digest.get("artifactCommitments") or {}).get("custodyRoots")
        if custody:
            latest = custody
    assert latest, "no snapshot commits a custody root"
    commitment = latest[0]

    real = timeline_module.verify_run
    calls: list[Path] = []

    def counting(run_dir: Path):
        calls.append(run_dir)
        return real(run_dir)

    monkeypatch.setattr(timeline_module, "verify_run", counting)
    # Real proofs, so the comparison covers populated run, root and
    # registration maps rather than three empty ones.
    direct = timeline_module.ProofCandidate(
        earliest_witnessed_at="2026-10-16T00:00:00Z",
        witness_digest="records/2026-10-16/digest-direct.json",
        tsa_gen_time="2026-10-16T00:00:00Z",
        coverage="direct",
    )
    contents = timeline_module.ProofCandidate(
        earliest_witnessed_at="2026-10-16T00:00:00Z",
        witness_digest="records/2026-10-16/digest-container.json",
        tsa_gen_time="2026-10-16T00:00:00Z",
        coverage="transitive",
    )
    memo = VerificationMemo()
    outputs = []
    for use_memo in (memo, memo, None):
        runs: dict = {}
        roots: dict = {}
        registrations: dict = {}
        _commit_root(
            records,
            commitment,
            direct,
            contents,
            runs,
            roots,
            registrations,
            memo=use_memo,
        )
        outputs.append((runs, roots, registrations))
    assert len(calls) == 2
    assert outputs[0] == outputs[1] == outputs[2]
    runs, roots, _registrations = outputs[0]
    assert runs == {commitment["runDirectory"]: contents.as_json()}
    assert set(roots) == {commitment["custodyRootSha256"]}
    assert (
        roots[commitment["custodyRootSha256"]]["custodyInventoryVersion"]
        == (commitment["custodyInventoryVersion"])
    )
    assert len(memo.runs) == 1


# --- Log chunks shared by many snapshots ---


def _archive(records: Path, logical: str, document: object) -> dict:
    """Write one recorder archive and the record a digest would keep for it."""

    raw = json.dumps(document).encode()
    compressed = gzip.compress(raw, mtime=0)
    path = records.parent / logical
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(compressed)
    return {
        "archivePath": logical,
        "archiveSha256": hashlib.sha256(compressed).hexdigest(),
        "archiveBytes": len(compressed),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _chunk(rows: list, index: int = 0, collection: str = "runs") -> dict:
    return {
        "schemaVersion": "thesis_log_chunk_v1",
        "logSchemaVersion": "thesis_log_v3",
        "collection": collection,
        "chunkIndex": index,
        "count": len(rows),
        "rows": rows,
    }


def _logged_row(run: str, root_hash: str = ROOT_HASH) -> dict:
    return {
        "custodyRootSha256": root_hash,
        "activityLog": [
            {"artifactType": "prompt", "path": f"records/2026-10-16/{run}/prompt.md"},
            {
                "artifactType": "manifest",
                "path": f"records/2026-10-16/{run}/manifest.json",
            },
        ],
    }


def _snapshot(
    records: Path,
    name: str,
    chunks: list[dict],
    manifest_rows: list | None = None,
) -> dict:
    """One digest whose v3 log holds these chunks, each in its own archive."""

    references = [
        {"index": index, "sha256": canonical_sha256(chunk), "count": chunk["count"]}
        for index, chunk in enumerate(chunks)
    ]
    log_chunks = {
        f"runs:{index}": {
            **_archive(records, f"records/{name}/log/{index}.json.gz", chunk),
            "manifestSha256": canonical_sha256(chunk),
        }
        for index, chunk in enumerate(chunks)
    }
    manifest = {
        "schemaVersion": "thesis_log_v3",
        "collections": {"runs": {"chunks": references}},
        "rows": manifest_rows or [],
    }
    return {
        "surfaces": {"log": _archive(records, f"records/{name}/log.json.gz", manifest)},
        "logChunks": log_chunks,
    }


@pytest.fixture
def log_records(tmp_path: Path) -> Path:
    records = tmp_path / "records"
    for name in ("run-a", "run-b"):
        _run(records, name)
    return records


def _counted_hashes(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    hashed: list[object] = []
    real = timeline_module.canonical_sha256

    def counting(value: object) -> str:
        hashed.append(value)
        return real(value)

    monkeypatch.setattr(timeline_module, "canonical_sha256", counting)
    return hashed


def test_a_chunk_shared_by_many_snapshots_is_hashed_once(
    log_records: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = _chunk([_logged_row("run-a")])
    digests = [
        _snapshot(log_records, f"snapshot-{number}", [shared]) for number in range(5)
    ]
    plain = [_root_commitments_from_log(log_records, digest) for digest in digests]
    assert all(len(commitments) == 1 for commitments in plain)

    hashed = _counted_hashes(monkeypatch)
    memo = VerificationMemo()
    remembered = [
        _root_commitments_from_log(log_records, digest, memo=memo)
        for digest in digests
    ]
    assert remembered == plain
    assert len(hashed) == 1
    assert len(memo.chunks) == 1


def test_an_archive_is_read_and_checked_again_when_its_chunk_repeats(
    log_records: Path,
) -> None:
    shared = _chunk([_logged_row("run-a")])
    first = _snapshot(log_records, "first", [shared])
    second = _snapshot(log_records, "second", [shared])
    memo = VerificationMemo()
    _root_commitments_from_log(log_records, first, memo=memo)

    archive = log_records / "second" / "log" / "0.json.gz"
    original = archive.read_bytes()
    archive.write_bytes(gzip.compress(b"[]", mtime=0))
    with pytest.raises(TimelineError, match="covered recorder archive mismatch"):
        _root_commitments_from_log(log_records, second, memo=memo)

    archive.unlink()
    with pytest.raises(TimelineError, match="covered recorder archive is absent"):
        _root_commitments_from_log(log_records, second, memo=memo)

    # A digest that claims other raw bytes for the same archive is refused too.
    archive.write_bytes(original)
    claims_other_bytes = json.loads(json.dumps(second))
    claims_other_bytes["logChunks"]["runs:0"]["sha256"] = "0" * 64
    with pytest.raises(TimelineError, match="covered recorder raw body mismatch"):
        _root_commitments_from_log(log_records, claims_other_bytes, memo=memo)


def test_every_reference_is_checked_again_when_its_chunk_repeats(
    log_records: Path,
) -> None:
    shared = _chunk([_logged_row("run-a")])
    first = _snapshot(log_records, "first", [shared])
    second = _snapshot(log_records, "second", [shared])
    memo = VerificationMemo()
    _root_commitments_from_log(log_records, first, memo=memo)

    run_root = log_records / "2026-10-16" / "run-a" / "custody_root.json"
    run_root.unlink()
    with pytest.raises(TimelineError, match="no local root"):
        _root_commitments_from_log(log_records, second, memo=memo)


def _with_expectation(digest: dict, records: Path, **changes: object) -> dict:
    """The digest with its manifest's chunk reference changed and rearchived."""

    logical = digest["surfaces"]["log"]["archivePath"]
    manifest = json.loads(gzip.decompress((records.parent / logical).read_bytes()))
    reference = manifest["collections"]["runs"]["chunks"][0]
    reference.update(changes)
    changed = json.loads(json.dumps(digest))
    changed["surfaces"]["log"] = _archive(records, logical, manifest)
    changed["logChunks"]["runs:0"]["manifestSha256"] = reference["sha256"]
    return changed


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"count": 2}, "metadata mismatch"),
        ({"sha256": "b" * 64}, "canonical hash mismatch"),
    ],
)
def test_a_changed_expectation_of_a_known_chunk_runs_every_check(
    log_records: Path, changes: dict, message: str
) -> None:
    shared = _chunk([_logged_row("run-a")])
    memo = VerificationMemo()
    _root_commitments_from_log(
        log_records, _snapshot(log_records, "first", [shared]), memo=memo
    )
    changed = _with_expectation(
        _snapshot(log_records, "second", [shared]), log_records, **changes
    )
    with pytest.raises(TimelineError, match=message):
        _root_commitments_from_log(log_records, changed, memo=memo)


def test_a_known_chunk_at_another_position_runs_every_check(log_records: Path) -> None:
    other = _chunk([_logged_row("run-b")], index=0)
    shared = _chunk([_logged_row("run-a")], index=0)
    memo = VerificationMemo()
    _root_commitments_from_log(
        log_records, _snapshot(log_records, "first", [shared]), memo=memo
    )
    # The same chunk bytes now sit at index 1, where their chunkIndex is wrong.
    moved = _snapshot(log_records, "second", [other, shared])
    with pytest.raises(TimelineError, match="runs:1 metadata mismatch"):
        _root_commitments_from_log(log_records, moved, memo=memo)


def test_a_rejected_chunk_is_not_remembered(log_records: Path) -> None:
    rejected = _chunk([_logged_row("run-a")])
    rejected["count"] = 5
    digest = _snapshot(log_records, "first", [rejected])
    memo = VerificationMemo()
    for _attempt in range(2):
        with pytest.raises(TimelineError, match="row count mismatch"):
            _root_commitments_from_log(log_records, digest, memo=memo)
    assert memo.chunks == {}


def test_a_log_manifest_row_still_counts_and_comes_first(log_records: Path) -> None:
    shared = _chunk([_logged_row("run-a", "c" * 64)])
    digest = _snapshot(
        log_records,
        "first",
        [shared],
        manifest_rows=[_logged_row("run-b", "d" * 64)],
    )
    memo = VerificationMemo()
    for _attempt in range(2):
        commitments = _root_commitments_from_log(log_records, digest, memo=memo)
        assert [row["custodyRootSha256"] for row in commitments] == ["d" * 64, "c" * 64]


LOG_ROWS = st.lists(
    st.one_of(
        st.sampled_from(["run-a", "run-b", "run-missing"]).map(_logged_row),
        st.sampled_from(["run-a", "run-b"]).map(
            lambda run: _logged_row(run, "e" * 64)
        ),
        st.sampled_from(["run-a", "run-b"]).map(
            lambda run: {"nested": [_logged_row(run)]}
        ),
        # Rows that name no run: no hash, a hash of the wrong type, two
        # manifests, and an activity log of the wrong type.
        st.just({"custodyRootSha256": ROOT_HASH}),
        st.just({"custodyRootSha256": 7, "activityLog": []}),
        st.just(
            {
                "custodyRootSha256": ROOT_HASH,
                "activityLog": [
                    {"artifactType": "manifest", "path": "records/a"},
                    {"artifactType": "manifest", "path": "records/b"},
                ],
            }
        ),
        st.just({"custodyRootSha256": ROOT_HASH, "activityLog": {}}),
    ),
    max_size=4,
)
# Each snapshot lists chunks from a small pool, so bytes repeat across snapshots,
# and may change what its manifest expects of its first chunk.
SNAPSHOTS = st.lists(
    st.tuples(
        st.lists(st.integers(0, 3), max_size=3),
        st.sampled_from(
            [
                None,
                None,
                None,
                {"count": 99},
                {"sha256": "b" * 64},
            ]
        ),
    ),
    min_size=1,
    max_size=8,
)


def _outcome(records: Path, digest: dict, memo: VerificationMemo | None) -> object:
    try:
        return _root_commitments_from_log(records, digest, memo=memo)
    except TimelineError as exc:
        return str(exc)


@settings(max_examples=60, deadline=None)
@given(st.lists(LOG_ROWS, min_size=4, max_size=4), SNAPSHOTS)
def test_a_memo_never_changes_what_a_log_yields(
    pool_rows: list[list], snapshots: list[tuple[list[int], dict | None]]
) -> None:
    """Differential: one shared memo against no memo, snapshot by snapshot."""

    with tempfile.TemporaryDirectory() as directory:
        records = Path(directory) / "records"
        for name in ("run-a", "run-b"):
            _run(records, name)
        memo = VerificationMemo()
        for number, (picks, changes) in enumerate(snapshots):
            chunks = [
                _chunk(pool_rows[pick], index=position)
                for position, pick in enumerate(picks)
            ]
            digest = _snapshot(records, f"snapshot-{number}", chunks)
            if changes and chunks:
                digest = _with_expectation(digest, records, **changes)
            assert _outcome(records, digest, memo) == _outcome(records, digest, None)
