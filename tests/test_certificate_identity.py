"""verify_record_chain keeps each certificate's identity by the file's bytes.

Every RFC 3161 token names one of a few certificates, and reading one identity
takes four openssl runs. These tests pin that the kept answer equals what openssl
reports for the file, that it costs one reading per distinct certificate, and
that a failure is never kept.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_record_chain as record_chain  # noqa: E402
from verify_record_chain import ChainError  # noqa: E402


def _certificate(directory: Path, name: str) -> Path:
    path = directory / f"{name}.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-keyout",
            str(directory / f"{name}.key"),
            "-out",
            str(path),
            "-subj",
            f"/O=Thesis tests/CN={name}",
            "-days",
            "1",
        ],
        check=True,
        capture_output=True,
    )
    return path


def _openssl(*arguments: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        ["openssl", *arguments], input=input_bytes, check=True, capture_output=True
    ).stdout


def _identity_read_from_the_file(path: Path) -> dict[str, str]:
    """The definition this replaced: each openssl run opens the file itself."""

    certificate_der = _openssl("x509", "-in", str(path), "-outform", "DER")
    public_key_pem = _openssl("x509", "-in", str(path), "-pubkey", "-noout")
    public_key_der = _openssl(
        "pkey", "-pubin", "-outform", "DER", input_bytes=public_key_pem
    )
    description = _openssl(
        "x509", "-in", str(path), "-noout", "-serial", "-subject", "-nameopt", "RFC2253"
    ).decode()
    fields = dict(
        line.split("=", 1) for line in description.splitlines() if "=" in line
    )
    return {
        "certificateSha256": hashlib.sha256(certificate_der).hexdigest(),
        "spkiSha256": hashlib.sha256(public_key_der).hexdigest(),
        "serial": fields["serial"].upper(),
        "subject": fields["subject"],
    }


@pytest.fixture
def openssl_runs(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    record_chain._identity_of_certificate.cache_clear()
    runs: list[list[str]] = []
    real = record_chain._run_openssl

    def counting(arguments: list[str], **options: object) -> bytes | str:
        runs.append(arguments)
        return real(arguments, **options)

    monkeypatch.setattr(record_chain, "_run_openssl", counting)
    yield runs
    record_chain._identity_of_certificate.cache_clear()


def test_a_kept_identity_equals_what_openssl_reports_for_the_file(
    tmp_path: Path, openssl_runs: list[list[str]]
) -> None:
    for name in ("first", "second"):
        path = _certificate(tmp_path, name)
        expected = _identity_read_from_the_file(path)
        assert record_chain._certificate_identity(path) == expected
        assert record_chain._certificate_identity(path) == expected


def test_equal_bytes_take_one_reading_and_other_bytes_take_another(
    tmp_path: Path, openssl_runs: list[list[str]]
) -> None:
    first = _certificate(tmp_path, "first")
    copy = tmp_path / "copy.pem"
    copy.write_bytes(first.read_bytes())
    other = _certificate(tmp_path, "other")

    first_identity = record_chain._certificate_identity(first)
    assert len(openssl_runs) == 4
    assert record_chain._certificate_identity(first) == first_identity
    assert record_chain._certificate_identity(copy) == first_identity
    assert len(openssl_runs) == 4

    assert record_chain._certificate_identity(other) != first_identity
    assert len(openssl_runs) == 8


def test_a_file_that_changes_gets_the_identity_of_its_new_bytes(
    tmp_path: Path, openssl_runs: list[list[str]]
) -> None:
    path = _certificate(tmp_path, "first")
    other = _certificate(tmp_path, "other")
    record_chain._certificate_identity(path)
    path.write_bytes(other.read_bytes())
    assert record_chain._certificate_identity(path) == _identity_read_from_the_file(
        other
    )


def test_a_caller_cannot_change_a_kept_identity(
    tmp_path: Path, openssl_runs: list[list[str]]
) -> None:
    path = _certificate(tmp_path, "first")
    expected = _identity_read_from_the_file(path)
    record_chain._certificate_identity(path)["subject"] = "CN=somebody else"
    assert record_chain._certificate_identity(path) == expected


def test_a_failed_reading_is_refused_each_time_and_not_kept(
    tmp_path: Path, openssl_runs: list[list[str]]
) -> None:
    path = tmp_path / "garbage.pem"
    path.write_bytes(b"not a certificate")
    for attempt in (1, 2):
        with pytest.raises(ChainError, match="OpenSSL command failed"):
            record_chain._certificate_identity(path)
        assert len(openssl_runs) == attempt
    assert record_chain._identity_of_certificate.cache_info().currsize == 0


def test_a_missing_file_is_a_chain_error(
    tmp_path: Path, openssl_runs: list[list[str]]
) -> None:
    with pytest.raises(ChainError, match="cannot read certificate"):
        record_chain._certificate_identity(tmp_path / "absent.pem")
    assert openssl_runs == []
