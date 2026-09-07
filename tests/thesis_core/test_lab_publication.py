"""Public exports preserve real store projections and refuse incomplete closure."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from tests.thesis_core.test_conditional_reviews import complete, review
from thesis_core import lab_publication
from thesis_core.artifacts import ArtifactCorrupt, ArtifactMissing
from thesis_core.conditional_reviews import link_revision
from thesis_core.conditionals import conditional_detail
from thesis_core.lab_publication import export_conditionals

REVISION = "a" * 40


def exported_details(destination, manifest):
    return {
        item["id"]: json.loads(
            (destination / "blobs" / item["detail"]["sha256"]).read_bytes()
        )
        for item in manifest["attempts"]
    }


def test_export_closes_revision_history_and_preserves_exact_public_artifacts(
    core_store, tmp_path
):
    parent, _ = complete(core_store, model="gemini-test")
    assessment = review(core_store, parent.id)
    feedback = b"Explicit source feedback for revision."
    child, _ = complete(core_store, model="gemini-test", feedback=feedback)
    association = link_revision(
        core_store,
        parent_attempt_id=parent.id,
        revision_attempt_id=child.id,
        triggering_review_id=assessment,
        feedback=feedback,
    )
    unrelated, _ = complete(core_store, model="unselected-model")
    private = core_store.artifacts.put_bytes(b"unreferenced private fixture")
    cas_before = sorted(
        path.relative_to(core_store.artifacts.root)
        for path in core_store.artifacts.root.rglob("*")
    )
    destination = tmp_path / "published"
    manifest = export_conditionals(
        core_store, [child.id], destination, code_revision=REVISION
    )
    assert json.loads((destination / "manifest.json").read_bytes()) == manifest
    assert manifest["schema_version"] == "thesis_conditional_snapshot_v1"
    assert manifest["code_revision"] == REVISION
    assert [item["id"] for item in manifest["attempts"]] == sorted(
        [parent.id, child.id]
    )
    assert unrelated.id not in {item["id"] for item in manifest["attempts"]}
    artifact_hashes = {item["sha256"] for item in manifest["artifacts"]}
    assert {
        assessment,
        association,
        hashlib.sha256(feedback).hexdigest(),
    } <= artifact_hashes
    assert private not in artifact_hashes
    assert [item["sha256"] for item in manifest["artifacts"]] == sorted(artifact_hashes)
    expected_blobs = artifact_hashes | {
        item["detail"]["sha256"] for item in manifest["attempts"]
    }
    assert {path.name for path in (destination / "blobs").iterdir()} == expected_blobs
    for item in manifest["artifacts"]:
        raw = (destination / "blobs" / item["sha256"]).read_bytes()
        assert raw == core_store.artifacts.read_bytes(item["sha256"])
        assert len(raw) == item["bytes"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
    details = exported_details(destination, manifest)
    for identity, data in details.items():
        original = conditional_detail(core_store, identity).model_dump(
            mode="json", by_alias=True
        )
        original["generated_at"] = manifest["generated_at"]
        assert data == original
        assert data["scoring_status"] == "not_registered"
        response = data["response"]
        for cdf in [
            response["reference"],
            *(arm["distribution"] for arm in response["arms"]),
        ]:
            assert cdf["pointCount"] == 201
            assert "transformVersion" in cdf
            assert "pointEstimate" in cdf["summary"]
            assert not {"point_count", "transform_version"}.intersection(cdf)
            assert "point_estimate" not in cdf["summary"]
        item = next(item for item in manifest["attempts"] if item["id"] == identity)
        raw = (destination / "blobs" / item["detail"]["sha256"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["detail"]["sha256"]
        assert len(raw) == item["detail"]["bytes"]
    assert (
        sorted(
            path.relative_to(core_store.artifacts.root)
            for path in core_store.artifacts.root.rglob("*")
        )
        == cas_before
    )
    with core_store.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM conditional_attempts"
            ).fetchone()["n"]
            == 3
        )
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM conditional_reviews"
            ).fetchone()["n"]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM conditional_revisions"
            ).fetchone()["n"]
            == 1
        )
        assert (
            connection.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0
        )


def test_contract_source_refs_are_exported_without_download_links(
    core_store, tmp_path, monkeypatch
):
    attempt, detail = complete(core_store)
    source_hash = detail.contract.sources[0].artifact.sha256
    detail = detail.model_copy(
        update={
            "artifacts": tuple(
                item for item in detail.artifacts if item.sha256 != source_hash
            ),
        }
    )
    monkeypatch.setattr(lab_publication, "conditional_detail", lambda *_: detail)
    manifest = export_conditionals(
        core_store, [attempt.id], tmp_path / "export", code_revision=REVISION
    )
    assert source_hash in {item["sha256"] for item in manifest["artifacts"]}


@pytest.mark.parametrize("damage", ["missing", "corrupt", "length"])
def test_artifact_damage_refuses_without_partial_destination(
    core_store, tmp_path, monkeypatch, damage
):
    attempt, detail = complete(core_store)
    source = detail.contract.sources[0].artifact
    if damage == "length":
        bad_source = detail.contract.sources[0].model_copy(
            update={
                "artifact": source.model_copy(update={"bytes": source.bytes + 1}),
            }
        )
        # Retain the real contract and corrupt the operational link's size.
        detail = detail.model_copy(
            update={
                "artifacts": (
                    *detail.artifacts,
                    detail.artifacts[0].model_copy(
                        update={
                            "sha256": source.sha256,
                            "bytes": bad_source.artifact.bytes,
                            "media_type": source.media_type,
                            "download_path": "/artifacts/" + source.sha256,
                        }
                    ),
                ),
            }
        )
        monkeypatch.setattr(lab_publication, "conditional_detail", lambda *_: detail)
    else:
        path = core_store.artifacts.root / source.sha256[:2] / source.sha256
        if damage == "missing":
            path.unlink()
        else:
            path.write_bytes(b"tampered")
    destination = tmp_path / "export"
    with pytest.raises((ArtifactCorrupt, ArtifactMissing)):
        export_conditionals(
            core_store, [attempt.id], destination, code_revision=REVISION
        )
    assert not destination.exists()
    assert not list(tmp_path.glob(".conditional-export-*"))


def test_export_independently_checks_cas_hash(core_store, tmp_path):
    attempt, detail = complete(core_store)
    artifacts = core_store.artifacts
    source = detail.contract.sources[0].artifact
    core_store.artifacts = SimpleNamespace(
        read_bytes=lambda digest: (
            b"not real" if digest == source.sha256 else artifacts.read_bytes(digest)
        )
    )
    with pytest.raises(ArtifactCorrupt):
        export_conditionals(
            core_store, [attempt.id], tmp_path / "export", code_revision=REVISION
        )


def test_missing_history_attempt_is_not_silently_omitted(
    core_store, tmp_path, monkeypatch
):
    attempt, detail = complete(core_store)
    absent = "f" * 64
    foreign = detail.revision_history[0].model_copy(update={"attempt_id": absent})
    detail = detail.model_copy(
        update={"revision_history": (*detail.revision_history, foreign)}
    )

    def load(_store, identity):
        if identity == absent:
            raise KeyError(absent)
        return detail

    monkeypatch.setattr(lab_publication, "conditional_detail", load)
    with pytest.raises(KeyError):
        export_conditionals(
            core_store, [attempt.id], tmp_path / "export", code_revision=REVISION
        )
    assert not (tmp_path / "export").exists()


@pytest.mark.parametrize("damage", ["identity", "history", "link"])
def test_projection_mismatch_refuses(core_store, tmp_path, monkeypatch, damage):
    attempt, detail = complete(core_store)
    if damage == "identity":
        detail = detail.model_copy(update={"id": "f" * 64})
    elif damage == "history":
        detail = detail.model_copy(update={"revision_history": ()})
    else:
        detail = detail.model_copy(
            update={
                "artifacts": (
                    detail.artifacts[0].model_copy(
                        update={"download_path": "/artifacts/" + "f" * 64}
                    ),
                    *detail.artifacts[1:],
                )
            }
        )
    monkeypatch.setattr(lab_publication, "conditional_detail", lambda *_: detail)
    with pytest.raises(ValueError):
        export_conditionals(
            core_store, [attempt.id], tmp_path / "export", code_revision=REVISION
        )


@pytest.mark.parametrize(
    "ids",
    [
        [],
        "a" * 64,
        ["invalid"],
        [True],
        ["a" * 64] * 2,
        [f"{i:064x}" for i in range(101)],
    ],
)
def test_invalid_selection_never_reads_store(tmp_path, ids):
    with pytest.raises(ValueError):
        export_conditionals(None, ids, tmp_path / "export", code_revision=REVISION)


@pytest.mark.parametrize("revision", ["", "main", "abc123", "A" * 40, True])
def test_revision_is_explicit_full_object_identity(tmp_path, revision):
    with pytest.raises(ValueError):
        export_conditionals(
            None, ["a" * 64], tmp_path / "export", code_revision=revision
        )


@pytest.mark.parametrize(
    "limit",
    [
        "MAX_ATTEMPTS",
        "MAX_ARTIFACTS",
        "MAX_ARTIFACT_BYTES",
        "MAX_TOTAL_ARTIFACT_BYTES",
        "MAX_DETAIL_BYTES",
        "MAX_TOTAL_DETAIL_BYTES",
        "MAX_MANIFEST_BYTES",
    ],
)
def test_export_caps_refuse_atomically(core_store, tmp_path, monkeypatch, limit):
    attempt, _ = complete(core_store)
    monkeypatch.setattr(lab_publication, limit, 0)
    with pytest.raises(ValueError):
        export_conditionals(
            core_store, [attempt.id], tmp_path / "export", code_revision=REVISION
        )
    assert not (tmp_path / "export").exists()
    assert not list(tmp_path.glob(".conditional-export-*"))


def test_revision_closure_is_bounded(core_store, tmp_path, monkeypatch):
    first, _ = complete(core_store)
    assessment = review(core_store, first.id)
    child, _ = complete(core_store, feedback=b"feedback")
    link_revision(
        core_store,
        parent_attempt_id=first.id,
        revision_attempt_id=child.id,
        triggering_review_id=assessment,
        feedback=b"feedback",
    )
    monkeypatch.setattr(lab_publication, "MAX_ATTEMPTS", 1)
    with pytest.raises(ValueError, match="closure"):
        export_conditionals(
            core_store, [child.id], tmp_path / "export", code_revision=REVISION
        )


@pytest.mark.parametrize("kind", ["empty_directory", "directory", "file", "symlink"])
def test_atomic_install_never_overwrites_any_existing_path(tmp_path, kind):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "new").write_bytes(b"new")
    destination = tmp_path / "export"
    if kind in ("empty_directory", "directory"):
        destination.mkdir()
        if kind == "directory":
            (destination / "existing").write_bytes(b"existing")
    elif kind == "file":
        destination.write_bytes(b"existing")
    else:
        destination.symlink_to(tmp_path / "absent")
    with pytest.raises(OSError):
        lab_publication._install_directory(staging, destination)
    assert (staging / "new").read_bytes() == b"new"
    assert not (destination / "new").exists()


def test_competing_exports_install_once(core_store, tmp_path):
    attempt, _ = complete(core_store)
    destination = tmp_path / "export"

    def publish(_):
        try:
            return export_conditionals(
                core_store, [attempt.id], destination, code_revision=REVISION
            )
        except FileExistsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, range(2)))
    installed = [result for result in results if result is not None]
    assert len(installed) == 1
    assert json.loads((destination / "manifest.json").read_bytes()) == installed[0]
    assert not list(tmp_path.glob(".conditional-export-*"))


def test_failed_install_removes_staging(core_store, tmp_path, monkeypatch):
    attempt, _ = complete(core_store)

    def refuse(*_):
        raise OSError("fixture filesystem failure")

    monkeypatch.setattr(lab_publication, "_install_directory", refuse)
    with pytest.raises(OSError):
        export_conditionals(
            core_store, [attempt.id], tmp_path / "export", code_revision=REVISION
        )
    assert not (tmp_path / "export").exists()
    assert not list(tmp_path.glob(".conditional-export-*"))
