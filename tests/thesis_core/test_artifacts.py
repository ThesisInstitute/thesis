import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from thesis_core.artifacts import ArtifactCorrupt, ArtifactMissing, LocalArtifactStore


def test_concurrent_atomic_writes_and_verified_reads(tmp_path):
    artifacts = LocalArtifactStore(tmp_path)
    body = b"An immutable official response\n" * 1024
    digest = hashlib.sha256(body).hexdigest()
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert set(pool.map(artifacts.put_bytes, [body] * 16)) == {digest}
    assert artifacts.exists(digest)
    assert artifacts.read_bytes(digest) == body
    assert list((tmp_path / digest[:2]).iterdir()) == [tmp_path / digest[:2] / digest]
    (tmp_path / digest[:2] / digest).write_bytes(b"tampered")
    with pytest.raises(ArtifactCorrupt):
        artifacts.read_bytes(digest)
    with pytest.raises(ArtifactCorrupt):
        artifacts.put_bytes(body)


def test_missing_and_unsafe_paths(tmp_path):
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    digest = hashlib.sha256(b"source").hexdigest()
    assert not artifacts.exists(digest)
    with pytest.raises(ArtifactMissing):
        artifacts.read_bytes(digest)
    with pytest.raises(ValueError):
        artifacts.read_bytes("../../etc/passwd")
    outside = tmp_path / "outside"
    outside.mkdir()
    (artifacts.root / digest[:2]).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactCorrupt):
        artifacts.put_bytes(b"source")
    (artifacts.root / digest[:2]).unlink()
    (artifacts.root / digest[:2]).mkdir()
    target = outside / "source"
    target.write_bytes(b"source")
    (artifacts.root / digest[:2] / digest).symlink_to(target)
    with pytest.raises(ArtifactCorrupt):
        artifacts.read_bytes(digest)
    with pytest.raises(ArtifactCorrupt):
        artifacts.exists(digest)
