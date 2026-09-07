"""Verified, immutable, local content-addressed byte storage."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Protocol


class ArtifactError(Exception):
    """An artifact cannot be safely stored or read."""


class ArtifactMissing(ArtifactError, FileNotFoundError):  # noqa: N818
    pass


class ArtifactCorrupt(ArtifactError):  # noqa: N818
    pass


class ArtifactStore(Protocol):
    def put_bytes(self, data: bytes) -> str: ...

    def read_bytes(self, digest: str) -> bytes: ...

    def exists(self, digest: str) -> bool: ...


def _digest(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Artifact identity must be a lowercase SHA-256 hex digest")
    return value


class LocalArtifactStore:
    """Atomic CAS writes; every read verifies bytes and refuses symlinks.

    MIME type and other contextual metadata belong in a scientific record, not
    in this store: the same bytes may have more than one contextual media type.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _directory(self, digest: str, *, create: bool = False) -> int:
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            if create:
                try:
                    os.mkdir(digest[:2], mode=0o700, dir_fd=root_fd)
                except FileExistsError:
                    pass
            try:
                return os.open(
                    digest[:2],
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=root_fd,
                )
            except FileNotFoundError as exc:
                raise ArtifactMissing(digest) from exc
            except OSError as exc:
                raise ArtifactCorrupt(
                    f"Unsafe artifact directory for {digest}"
                ) from exc
        finally:
            os.close(root_fd)

    @staticmethod
    def _read(directory_fd: int, digest: str) -> bytes:
        try:
            fd = os.open(digest, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        except FileNotFoundError as exc:
            raise ArtifactMissing(digest) from exc
        except OSError as exc:
            raise ArtifactCorrupt(f"Unsafe artifact path for {digest}") from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ArtifactCorrupt(f"Artifact {digest} is not a regular file")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read()
        finally:
            os.close(fd)
        if hashlib.sha256(data).hexdigest() != digest:
            raise ArtifactCorrupt(f"SHA-256 mismatch for artifact {digest}")
        return data

    def put_bytes(self, data: bytes) -> str:
        if not isinstance(data, bytes):
            raise TypeError("Artifact data must be bytes")
        digest = hashlib.sha256(data).hexdigest()
        directory_fd = self._directory(digest, create=True)
        temporary = f".pending-{uuid.uuid4().hex}"
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(
                    temporary,
                    digest,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                os.fsync(directory_fd)
            except FileExistsError:
                # A concurrent writer must have installed exactly these bytes.
                if self._read(directory_fd, digest) != data:
                    raise ArtifactCorrupt(f"Conflicting bytes for {digest}")
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)
        return digest

    def read_bytes(self, digest: str) -> bytes:
        digest = _digest(digest)
        directory_fd = self._directory(digest)
        try:
            return self._read(directory_fd, digest)
        finally:
            os.close(directory_fd)

    def exists(self, digest: str) -> bool:
        digest = _digest(digest)
        try:
            directory_fd = self._directory(digest)
        except ArtifactMissing:
            return False
        try:
            try:
                info = os.stat(digest, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            if not stat.S_ISREG(info.st_mode):
                raise ArtifactCorrupt(f"Artifact {digest} is not a regular file")
            return True
        finally:
            os.close(directory_fd)
