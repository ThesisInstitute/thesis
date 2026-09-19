"""The ledger release chain pins TSA responder certificates as a reviewed set.

TSAs replace their responder certificate about once a year. DigiCert did in
2026: from 2026-09-09 every daily resolver run minted a receipt signed by
"DigiCert SHA256 RSA4096 Timestamp Responder 2026 1", met a verifier that
pinned only the previous responder, and aborted before appending. The journal
already holds releases signed by the previous responder, so the fix is a set of
pinned (certificate, SPKI) pairs, not a replaced pin.

These tests use the committed local fixture CAs (tests/fixtures/release_tsa)
and make no network calls.
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_release_chain as chain  # noqa: E402
from ledger_release_chain import PinnedSigner, ReleaseChainError  # noqa: E402

TSA_FIXTURE = ROOT / "tests" / "fixtures" / "release_tsa"
OTHER = PinnedSigner(label="some other responder", certificate_sha256="a" * 64,
                     spki_sha256="b" * 64)


def _identity(certificate: pathlib.Path) -> tuple[str, str]:
    der = subprocess.check_output(
        ["openssl", "x509", "-in", str(certificate), "-outform", "DER"])
    public_pem = subprocess.check_output(
        ["openssl", "x509", "-in", str(certificate), "-pubkey", "-noout"])
    spki = subprocess.run(
        ["openssl", "pkey", "-pubin", "-outform", "DER"],
        input=public_pem, check=True, capture_output=True).stdout
    return hashlib.sha256(der).hexdigest(), hashlib.sha256(spki).hexdigest()


@pytest.fixture
def receipt(tmp_path, monkeypatch):
    """A receipt from the fixture 'digicert' responder, plus a way to pin."""
    tsa = tmp_path / "release_tsa"
    shutil.copytree(TSA_FIXTURE, tsa)
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"test":"manifest"}\n')
    request = tmp_path / "request.tsq"
    subprocess.run(["openssl", "ts", "-query", "-data", str(manifest), "-sha256",
                    "-cert", "-out", str(request)], check=True, capture_output=True)
    out = tmp_path / "0001-0123456789abcdef.digicert.tsr"
    subprocess.run(["openssl", "ts", "-reply", "-config", "openssl-ts.cnf",
                    "-queryfile", str(request), "-out", str(out)],
                   cwd=tsa / "digicert", check=True, capture_output=True)
    anchor = tsa / "anchors" / "digicert-trusted-root-g4.pem"
    certificate_sha256, spki_sha256 = _identity(tsa / "digicert" / "signer.pem")
    real = PinnedSigner(label="fixture digicert responder",
                        certificate_sha256=certificate_sha256, spki_sha256=spki_sha256)

    def verify(*signers: PinnedSigner):
        spec = chain.AnchorSpec(
            filename=anchor.name,
            pem_sha256=hashlib.sha256(anchor.read_bytes()).hexdigest(),
            policy_oid="1.3.6.1.4.1.55555.1.2",
            signers=tuple(signers),
        )
        monkeypatch.setitem(chain.ANCHORS, "digicert", spec)
        return chain.verify_receipt(
            hashlib.sha256(manifest.read_bytes()).hexdigest(), out, "digicert",
            anchor_dir=anchor.parent, enforce_production_pins=True)

    return real, verify


def test_the_pinned_responder_is_accepted(receipt):
    real, verify = receipt
    assert verify(real).tzinfo is not None


def test_a_later_entry_in_the_set_is_accepted(receipt):
    """The rotation case: the journal's old responder stays pinned, the new
    one is appended, and a receipt from either verifies."""
    real, verify = receipt
    verify(OTHER, real)


def test_an_unpinned_responder_is_refused_and_described(receipt):
    real, verify = receipt
    with pytest.raises(ReleaseChainError) as refusal:
        verify(OTHER)
    message = str(refusal.value)
    assert "signer certificate is not pinned" in message
    # Everything needed to check the certificate against a fresh receipt
    # from the TSA is in the message: both hashes and the subject.
    assert real.certificate_sha256 in message
    assert real.spki_sha256 in message
    assert "subject=" in message
    assert "docs/tsa-signer-rotation.md" in message


def test_certificate_and_key_are_pinned_as_a_pair(receipt):
    """The certificate hash of one entry with the SPKI of another is a
    certificate nobody reviewed."""
    real, verify = receipt
    halves = (
        dataclasses.replace(OTHER, certificate_sha256=real.certificate_sha256),
        dataclasses.replace(OTHER, spki_sha256=real.spki_sha256),
    )
    with pytest.raises(ReleaseChainError, match="signer SPKI is not pinned"):
        verify(*halves)


def test_an_empty_set_accepts_nothing(receipt):
    _real, verify = receipt
    with pytest.raises(ReleaseChainError, match="not pinned"):
        verify()


def test_production_pins_are_well_formed():
    hex64 = re.compile(r"[0-9a-f]{64}\Z")
    for tsa, spec in chain.ANCHORS.items():
        assert spec.signers, tsa
        for signer in spec.signers:
            assert signer.label.strip(), tsa
            assert hex64.match(signer.certificate_sha256), (tsa, signer.label)
            assert hex64.match(signer.spki_sha256), (tsa, signer.label)
        certificates = [s.certificate_sha256 for s in spec.signers]
        assert len(set(certificates)) == len(certificates), tsa


def test_digicert_keeps_the_responder_that_signed_the_existing_journal():
    """Releases 0000-0020 carry the first entry; dropping it would make the
    whole journal unverifiable. The 2026 responder is appended after it."""
    pairs = [(s.certificate_sha256, s.spki_sha256)
             for s in chain.ANCHORS["digicert"].signers]
    assert pairs[0] == (
        "4aa03fa22cd75c84c55c938f828e676b9caecab33fe36d269aa334f146110a33",
        "7abda95ed7301ac94bded350babc319903d0b4f16c4e7e39346dba5f9e992b72",
    )
    assert (
        "2da09da7f4131f9fe72db6c5e6e9c9656755af043f1ea742cc0d2120e141ebfc",
        "753596b60a629061144cbd312017bbfb77510eac20b7eadc5fafb7cabe142fd5",
    ) in pairs
