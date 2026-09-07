"""Real RFC 3161 behaviour for :mod:`thesis_core.tsa`.

Every timestamp here is produced by an actual OpenSSL timestamp authority
running locally and verified through the same pinned path the record-chain
verifier uses.  The synthetic roots exist only inside these tests: they are
installed by monkeypatching the verifier's code pins and the packaged trust
directory, never by shipping a configuration file, and
``tests/thesis_core/test_legacy_imports.py`` asserts that the shipped
configuration still names nothing but the two real anchors.

The last test in this file replays real published receipts from
``records/`` through the public replay entry point, which is the strongest
available check that the standalone path reproduces production proofs.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from thesis_core import record_chain, tsa
from thesis_core.canonical import canonical_bytes, canonical_sha256

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "records"
SHA256_OID = "2.16.840.1.101.3.4.2.1"
BUNDLE_LOGICAL_PATH = "records/trust/tsa-anchors-v2.json"
BUNDLE_ID = "tsa-anchors-v2"
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
SUBJECT_RECORDED_AT = datetime(2020, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------
# A real, local OpenSSL timestamp authority
# --------------------------------------------------------------------------


def _openssl(*arguments):
    completed = subprocess.run(
        ["openssl", *arguments],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "OPENSSL_CONF": os.devnull, "LC_ALL": "C"},
    )
    if completed.returncode:
        raise RuntimeError(f"openssl {' '.join(arguments)} failed: {completed.stderr}")


@dataclass(frozen=True)
class Authority:
    """A locally generated TSA: its own root, signing certificate and key."""

    anchor_id: str
    endpoint: str
    policy_oid: str
    directory: Path
    root_certificate: Path
    signer_certificate: Path
    signer_key: Path

    def config(self, *, accuracy=None, clock_precision_digits=0, policy_oid=None):
        """Write one ``openssl ts -reply`` configuration and return its path."""

        raw = f"{accuracy or 'none'}-{clock_precision_digits}-{policy_oid or 'x'}"
        label = "".join(item if item.isalnum() else "-" for item in raw)
        serial = self.directory / f"serial-{label}"
        serial.write_text("01\n")
        path = self.directory / f"tsa-{label}.cnf"
        lines = [
            "[tsa]",
            "default_tsa=tsa_config",
            "[tsa_config]",
            f"serial={serial}",
            f"signer_cert={self.signer_certificate}",
            f"signer_key={self.signer_key}",
            "signer_digest=sha256",
            f"default_policy={policy_oid or self.policy_oid}",
            f"other_policies={policy_oid or self.policy_oid}",
            "digests=sha256",
            f"clock_precision_digits={clock_precision_digits}",
            "ordering=yes",
            "tsa_name=yes",
            "ess_cert_id_chain=no",
        ]
        if accuracy:
            lines.append(f"accuracy={accuracy}")
        path.write_text("\n".join(lines) + "\n")
        return path

    def issue(self, query, **config_kwargs):
        """Sign one ``TimeStampReq`` and return the raw ``TimeStampResp``."""

        configuration = self.config(**config_kwargs)
        with tempfile.TemporaryDirectory(prefix="local-tsa-") as temporary:
            temporary = Path(temporary)
            (temporary / "request.tsq").write_bytes(query)
            _openssl(
                "ts",
                "-reply",
                "-config",
                str(configuration),
                "-section",
                "tsa_config",
                "-queryfile",
                str(temporary / "request.tsq"),
                "-out",
                str(temporary / "response.tsr"),
            )
            return (temporary / "response.tsr").read_bytes()

    def transport(self, **config_kwargs):
        """A :data:`thesis_core.tsa.Transport` backed by this authority."""

        def send(endpoint, query, timeout_seconds):
            assert endpoint == self.endpoint, endpoint
            assert timeout_seconds > 0
            return self.issue(query, **config_kwargs)

        return send


def _make_authority(directory, *, anchor_id, endpoint, policy_oid, certificate_serial):
    directory.mkdir(parents=True, exist_ok=True)
    root_key = directory / "root.key"
    root_certificate = directory / "root.pem"
    signer_key = directory / "signer.key"
    signer_request = directory / "signer.csr"
    signer_certificate = directory / "signer.pem"
    extensions = directory / "signer-extensions.cnf"

    _openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-sha256",
        "-days",
        "3650",
        "-subj",
        f"/CN={anchor_id} Root",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
        "-keyout",
        str(root_key),
        "-out",
        str(root_certificate),
    )
    _openssl(
        "req",
        "-new",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-sha256",
        "-subj",
        f"/CN={anchor_id} Timestamp Signer",
        "-keyout",
        str(signer_key),
        "-out",
        str(signer_request),
    )
    extensions.write_text(
        "\n".join(
            [
                "[tsa_signer]",
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,nonRepudiation",
                "extendedKeyUsage=critical,timeStamping",
                "subjectKeyIdentifier=hash",
                "authorityKeyIdentifier=keyid,issuer",
            ]
        )
        + "\n"
    )
    _openssl(
        "x509",
        "-req",
        "-in",
        str(signer_request),
        "-CA",
        str(root_certificate),
        "-CAkey",
        str(root_key),
        "-set_serial",
        str(certificate_serial),
        "-days",
        "3650",
        "-sha256",
        "-extfile",
        str(extensions),
        "-extensions",
        "tsa_signer",
        "-out",
        str(signer_certificate),
    )
    return Authority(
        anchor_id=anchor_id,
        endpoint=endpoint,
        policy_oid=policy_oid,
        directory=directory,
        root_certificate=root_certificate,
        signer_certificate=signer_certificate,
        signer_key=signer_key,
    )


@pytest.fixture(scope="module")
def authorities(tmp_path_factory):
    base = tmp_path_factory.mktemp("local-tsas")
    return {
        "pinned": _make_authority(
            base / "pinned",
            anchor_id="synthetic-pinned",
            endpoint="https://pinned.invalid/tsr",
            policy_oid="1.2.3.4.1",
            certificate_serial=201,
        ),
        "rogue": _make_authority(
            base / "rogue",
            anchor_id="synthetic-rogue",
            endpoint="https://rogue.invalid/tsr",
            policy_oid="1.2.3.4.1",
            certificate_serial=202,
        ),
    }


def _certificate_identity(path):
    return record_chain._certificate_identity(path)


@pytest.fixture
def pinned_tsa(authorities, tmp_path, monkeypatch):
    """Install the local authority as the only pinned anchor, in memory.

    The packaged trust directory and the verifier's code pins are both
    redirected, which is the only way a test root can ever be trusted: no
    file this repository ships names it.
    """

    authority = authorities["pinned"]
    trust = tmp_path / "packaged-trust"
    trust.mkdir()
    root_name = f"{authority.anchor_id}-root.pem"
    shutil.copyfile(authority.root_certificate, trust / root_name)

    root_identity = _certificate_identity(trust / root_name)
    signer_identity = _certificate_identity(authority.signer_certificate)
    anchor = {
        "allowedImprintAlgorithmOids": [SHA256_OID],
        "allowedPolicyOids": [authority.policy_oid],
        "allowedSigners": [signer_identity],
        "endpoint": authority.endpoint,
        "id": authority.anchor_id,
        "maxFutureSeconds": 0,
        "maxTokenLeadSeconds": 300,
        "rootCertificate": {
            **root_identity,
            "path": f"records/trust/{root_name}",
            "pemSha256": hashlib.sha256((trust / root_name).read_bytes()).hexdigest(),
        },
    }
    payload = {
        "anchors": [anchor],
        "bundleId": BUNDLE_ID,
        "schemaVersion": "thesis_tsa_trust_bundle_v1",
    }
    bundle = trust / Path(BUNDLE_LOGICAL_PATH).name
    bundle.write_bytes(canonical_bytes(payload))
    reference = {
        "bundleId": BUNDLE_ID,
        "path": BUNDLE_LOGICAL_PATH,
        "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "size": bundle.stat().st_size,
        "canonicalJsonSha256": canonical_sha256(payload),
    }

    monkeypatch.setattr(tsa, "TRUST_ASSET_DIR", trust)
    monkeypatch.setattr(
        record_chain, "CODE_PINNED_TRUST_BUNDLES", {BUNDLE_LOGICAL_PATH: reference}
    )
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_TSA_IDENTITIES",
        {
            BUNDLE_ID: {
                authority.anchor_id: {
                    "rootSpkiSha256": root_identity["spkiSha256"],
                    "signerSpkiSha256": {signer_identity["spkiSha256"]},
                }
            }
        },
    )
    return authority


def subject_bytes(recorded_at=SUBJECT_RECORDED_AT, **extra):
    payload = {
        "recordedAt": record_chain._format_utc(recorded_at),
        "schemaVersion": "thesis_core_test_subject_v1",
        **extra,
    }
    return canonical_bytes(payload)


def rotate_test_bundle(monkeypatch):
    """Keep the old test pin authorized while selecting a new default bundle."""
    path = "records/trust/tsa-anchors-v3.json"
    bundle_id = "tsa-anchors-v3"
    payload = json.loads(tsa.read_trust_asset(BUNDLE_LOGICAL_PATH))
    payload["bundleId"] = bundle_id
    raw = canonical_bytes(payload)
    (tsa.TRUST_ASSET_DIR / Path(path).name).write_bytes(raw)
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_TRUST_BUNDLES",
        record_chain.CODE_PINNED_TRUST_BUNDLES
        | {
            path: {
                "bundleId": bundle_id,
                "path": path,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
                "canonicalJsonSha256": canonical_sha256(payload),
            }
        },
    )
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_TSA_IDENTITIES",
        record_chain.CODE_PINNED_TSA_IDENTITIES
        | {bundle_id: record_chain.CODE_PINNED_TSA_IDENTITIES[BUNDLE_ID]},
    )
    monkeypatch.setattr(tsa, "TRUST_BUNDLE_LOGICAL_PATH", path)
    return path


def test_recorded_bundle_replay_survives_default_rotation(pinned_tsa, monkeypatch):
    receipt = tsa.request_and_verify(
        subject_bytes(),
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        transport=pinned_tsa.transport(accuracy="millisecs:500"),
    )
    new_path = rotate_test_bundle(monkeypatch)
    replay = tsa.verify_receipt(
        receipt.subject_bytes,
        receipt.response_der,
        request=receipt.request_der,
        anchor_id=pinned_tsa.anchor_id,
        trust_bundle_path=receipt.trust_bundle_path,
    )
    assert replay.trust_bundle_path == BUNDLE_LOGICAL_PATH
    assert replay.trust_bundle_sha256 == receipt.trust_bundle_sha256
    assert replay.accuracy_micros == 500_000
    new_receipt = tsa.request_and_verify(
        subject_bytes(),
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        transport=pinned_tsa.transport(),
    )
    assert new_receipt.trust_bundle_path == new_path
    with pytest.raises(tsa.TsaError, match="not pinned by verifier code"):
        tsa.verify_receipt(
            receipt.subject_bytes,
            receipt.response_der,
            anchor_id=pinned_tsa.anchor_id,
            trust_bundle_path="records/trust/tsa-anchors-v999.json",
        )
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_TRUST_BUNDLES",
        {new_path: record_chain.CODE_PINNED_TRUST_BUNDLES[new_path]},
    )
    with pytest.raises(tsa.TsaError, match="not pinned by verifier code"):
        tsa.verify_receipt(
            receipt.subject_bytes,
            receipt.response_der,
            anchor_id=pinned_tsa.anchor_id,
            trust_bundle_path=BUNDLE_LOGICAL_PATH,
        )


# --------------------------------------------------------------------------
# Request and verify
# --------------------------------------------------------------------------


def test_request_and_verify_against_a_local_authority(pinned_tsa):
    subject = subject_bytes(runId="alpha")
    receipt = tsa.request_and_verify(
        subject,
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(accuracy="secs:1, millisecs:500, microsecs:100"),
    )

    assert receipt.anchor_id == pinned_tsa.anchor_id
    assert receipt.endpoint == pinned_tsa.endpoint
    assert receipt.trust_bundle_id == BUNDLE_ID
    assert receipt.policy_oid == pinned_tsa.policy_oid
    assert receipt.imprint_algorithm_oid == SHA256_OID
    assert receipt.subject_bytes == subject
    assert receipt.subject_sha256 == hashlib.sha256(subject).hexdigest()
    assert receipt.token_sha256 == hashlib.sha256(receipt.response_der).hexdigest()
    assert receipt.recorded_at == SUBJECT_RECORDED_AT
    # The imprint covers the exact subject bytes, not a re-serialization.
    assert receipt.tst_info.hashed_message == hashlib.sha256(subject).digest()
    # Accuracy is read from the signed TSTInfo, in the units the TSA emitted.
    assert receipt.accuracy_micros == 1_500_100
    assert receipt.witness_upper_bound == receipt.gen_time + timedelta(
        microseconds=1_500_100
    )
    # The archive is complete enough to replay.
    assert receipt.request_der and receipt.response_der
    assert receipt.query.nonce == receipt.nonce is not None
    assert receipt.query.cert_req is True


def test_the_request_goes_only_to_the_pinned_endpoint(pinned_tsa):
    seen = []

    def send(endpoint, query, timeout_seconds):
        seen.append((endpoint, timeout_seconds))
        return pinned_tsa.issue(query)

    tsa.request_and_verify(
        subject_bytes(),
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        timeout_seconds=7.5,
        now=FAR_FUTURE,
        transport=send,
    )
    assert seen == [(pinned_tsa.endpoint, 7.5)]
    # There is no parameter through which a caller could name a URL.
    import inspect

    parameters = set(inspect.signature(tsa.request_and_verify).parameters)
    assert not parameters & {"endpoint", "url", "tsa", "host"}


def test_an_unknown_anchor_is_refused_before_any_request(pinned_tsa):
    def explode(endpoint, query, timeout_seconds):
        raise AssertionError("a request must not be attempted")

    with pytest.raises(tsa.TsaError, match="unknown TSA anchor"):
        tsa.request_and_verify(
            subject_bytes(),
            SUBJECT_RECORDED_AT,
            anchor_id="not-a-pinned-anchor",
            transport=explode,
        )


def test_recorded_at_must_match_the_subject_claim(pinned_tsa):
    def explode(endpoint, query, timeout_seconds):
        raise AssertionError("a request must not be attempted")

    with pytest.raises(tsa.TsaError, match="disagrees with the subject"):
        tsa.request_and_verify(
            subject_bytes(),
            SUBJECT_RECORDED_AT + timedelta(seconds=1),
            anchor_id=pinned_tsa.anchor_id,
            transport=explode,
        )


def test_a_naive_recorded_at_is_refused(pinned_tsa):
    with pytest.raises(tsa.TsaError, match="timezone-aware"):
        tsa.request_and_verify(
            subject_bytes(),
            datetime(2020, 1, 1),
            anchor_id=pinned_tsa.anchor_id,
            transport=lambda *_: b"",
        )


def test_a_failed_request_still_carries_the_query(pinned_tsa):
    def refuse(endpoint, query, timeout_seconds):
        raise OSError("connection reset")

    with pytest.raises(tsa.TsaError) as raised:
        tsa.request_and_verify(
            subject_bytes(),
            SUBJECT_RECORDED_AT,
            anchor_id=pinned_tsa.anchor_id,
            transport=refuse,
        )
    error = raised.value
    assert "connection reset" in str(error)
    assert error.anchor_id == pinned_tsa.anchor_id
    assert error.endpoint == pinned_tsa.endpoint
    assert error.response_der is None
    # The archived query is a real, parseable RFC 3161 request.
    query = tsa.parse_timestamp_query(error.request_der)
    assert query.hashed_message == hashlib.sha256(subject_bytes()).digest()


def test_a_failed_verification_carries_the_request_and_the_response(pinned_tsa):
    def tamper(endpoint, query, timeout_seconds):
        response = bytearray(pinned_tsa.issue(query))
        response[-1] ^= 0xFF
        return bytes(response)

    with pytest.raises(tsa.TsaError) as raised:
        tsa.request_and_verify(
            subject_bytes(),
            SUBJECT_RECORDED_AT,
            anchor_id=pinned_tsa.anchor_id,
            now=FAR_FUTURE,
            transport=tamper,
        )
    error = raised.value
    assert error.request_der and error.response_der
    assert "pinned RFC 3161 verification failed" in str(error)


def test_an_empty_or_oversized_response_is_refused(pinned_tsa):
    with pytest.raises(tsa.TsaError, match="empty response"):
        tsa.request_and_verify(
            subject_bytes(),
            SUBJECT_RECORDED_AT,
            anchor_id=pinned_tsa.anchor_id,
            transport=lambda *_: b"",
        )
    with pytest.raises(tsa.TsaError, match="exceeds"):
        tsa.request_and_verify(
            subject_bytes(),
            SUBJECT_RECORDED_AT,
            anchor_id=pinned_tsa.anchor_id,
            transport=lambda *_: b"\x00" * (tsa.MAX_RESPONSE_BYTES + 1),
        )


# --------------------------------------------------------------------------
# Offline replay
# --------------------------------------------------------------------------


def test_a_receipt_replays_offline_from_raw_bytes(pinned_tsa, tmp_path, monkeypatch):
    subject = subject_bytes(runId="replay")
    receipt = tsa.request_and_verify(
        subject,
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(accuracy="millisecs:500"),
    )

    # Nothing but the two byte strings crosses into the replay, and it runs
    # from a directory that has no records tree at all.
    monkeypatch.chdir(tmp_path)
    replayed = tsa.verify_receipt(
        bytes(receipt.subject_bytes),
        bytes(receipt.response_der),
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        request=bytes(receipt.request_der),
    )
    assert replayed.evidence.gen_time == receipt.evidence.gen_time
    assert replayed.evidence.tst_info == receipt.evidence.tst_info
    assert replayed.token_sha256 == receipt.token_sha256
    assert replayed.accuracy_micros == 500_000
    assert replayed.nonce == receipt.nonce
    # Replaying without the query is allowed; it just checks less.
    assert (
        tsa.verify_receipt(
            bytes(subject),
            bytes(receipt.response_der),
            anchor_id=pinned_tsa.anchor_id,
            now=FAR_FUTURE,
        ).token_sha256
        == receipt.token_sha256
    )


def test_replay_rejects_a_different_subject(pinned_tsa):
    receipt = tsa.request_and_verify(
        subject_bytes(runId="one"),
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(),
    )
    with pytest.raises(tsa.TsaError, match="pinned RFC 3161 verification failed"):
        tsa.verify_receipt(
            subject_bytes(runId="two"),
            receipt.response_der,
            anchor_id=pinned_tsa.anchor_id,
            now=FAR_FUTURE,
        )


def test_replay_rejects_a_single_flipped_subject_byte(pinned_tsa):
    subject = subject_bytes(runId="bitflip")
    receipt = tsa.request_and_verify(
        subject,
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(),
    )
    mutated = bytearray(subject)
    mutated[-2] = ord("X") if mutated[-2] != ord("X") else ord("Y")
    with pytest.raises(tsa.TsaError):
        tsa.verify_receipt(
            bytes(mutated),
            receipt.response_der,
            anchor_id=pinned_tsa.anchor_id,
            now=FAR_FUTURE,
        )


def test_replay_rejects_a_malformed_response(pinned_tsa):
    subject = subject_bytes()
    with pytest.raises(tsa.TsaError, match="pinned RFC 3161 verification failed"):
        tsa.verify_receipt(
            subject, b"not DER at all", anchor_id=pinned_tsa.anchor_id, now=FAR_FUTURE
        )


def test_a_rejection_response_is_not_a_witness(pinned_tsa, tmp_path):
    """A refusing TSA still answers with a ``TimeStampResp`` carrying no token."""

    subject = subject_bytes()
    (tmp_path / "subject.json").write_bytes(subject)
    # SHA-1 is absent from the authority's ``digests``, so it answers with a
    # PKIStatus rejection instead of a signed token.
    _openssl(
        "ts",
        "-query",
        "-config",
        os.devnull,
        "-data",
        str(tmp_path / "subject.json"),
        "-sha1",
        "-cert",
        "-out",
        str(tmp_path / "rejected.tsq"),
    )
    rejection = pinned_tsa.issue((tmp_path / "rejected.tsq").read_bytes())
    assert 0 < len(rejection) < 128, "a rejection carries status only, never a token"

    with pytest.raises(tsa.TsaError, match="pinned RFC 3161 verification failed"):
        tsa.verify_receipt(
            subject, rejection, anchor_id=pinned_tsa.anchor_id, now=FAR_FUTURE
        )


def test_replay_rejects_a_token_from_an_unpinned_signer(pinned_tsa, authorities):
    subject = subject_bytes()
    rogue = authorities["rogue"]
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        (temporary / "subject.json").write_bytes(subject)
        query = tsa.build_query(temporary / "subject.json")
    response = rogue.issue(query)

    with pytest.raises(tsa.TsaError, match="pinned RFC 3161 verification failed"):
        tsa.verify_receipt(
            subject,
            response,
            anchor_id=pinned_tsa.anchor_id,
            now=FAR_FUTURE,
        )


def test_replay_rejects_a_policy_the_anchor_does_not_allow(pinned_tsa):
    subject = subject_bytes()
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        (temporary / "subject.json").write_bytes(subject)
        query = tsa.build_query(temporary / "subject.json")
    response = pinned_tsa.issue(query, policy_oid="1.2.3.4.99")

    with pytest.raises(tsa.TsaError, match="is not allowed for TSA anchor"):
        tsa.verify_receipt(
            subject, response, anchor_id=pinned_tsa.anchor_id, now=FAR_FUTURE
        )


def test_replay_rejects_a_nonce_from_a_different_query(pinned_tsa):
    subject = subject_bytes()
    first = tsa.request_and_verify(
        subject,
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(),
    )
    second = tsa.request_and_verify(
        subject,
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(),
    )
    assert first.nonce != second.nonce

    with pytest.raises(tsa.TsaError, match="does not echo the query nonce"):
        tsa.verify_receipt(
            subject,
            first.response_der,
            anchor_id=pinned_tsa.anchor_id,
            now=FAR_FUTURE,
            request=second.request_der,
        )


def test_replay_rejects_a_query_over_a_different_subject(pinned_tsa):
    receipt = tsa.request_and_verify(
        subject_bytes(runId="query-mismatch"),
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(),
    )
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        (temporary / "subject.json").write_bytes(subject_bytes(runId="other"))
        foreign_query = tsa.build_query(temporary / "subject.json")

    with pytest.raises(tsa.TsaError, match="query does not cover the exact subject"):
        tsa.verify_receipt(
            receipt.subject_bytes,
            receipt.response_der,
            anchor_id=pinned_tsa.anchor_id,
            now=FAR_FUTURE,
            request=foreign_query,
        )


def test_a_subject_without_a_recorded_at_claim_is_refused(pinned_tsa):
    with pytest.raises(tsa.TsaError, match="recordedAt"):
        tsa.verify_receipt(
            canonical_bytes({"schemaVersion": "x"}),
            b"\x30\x00",
            anchor_id=pinned_tsa.anchor_id,
        )
    with pytest.raises(tsa.TsaError, match="not JSON"):
        tsa.verify_receipt(b"\x00\x01\x02", b"\x30\x00", anchor_id=pinned_tsa.anchor_id)


# --------------------------------------------------------------------------
# Time rules
# --------------------------------------------------------------------------


def test_a_token_that_postdates_the_verification_clock_is_refused(pinned_tsa):
    receipt = tsa.request_and_verify(
        subject_bytes(),
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(),
    )
    with pytest.raises(tsa.TsaError, match="postdates verification time"):
        tsa.verify_receipt(
            receipt.subject_bytes,
            receipt.response_der,
            anchor_id=pinned_tsa.anchor_id,
            now=receipt.gen_time - timedelta(seconds=1),
        )


def test_a_token_that_precedes_its_creation_claim_is_refused(pinned_tsa):
    late_claim = datetime(2099, 1, 1, tzinfo=UTC)
    subject = subject_bytes(recorded_at=late_claim)
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        (temporary / "subject.json").write_bytes(subject)
        query = tsa.build_query(temporary / "subject.json")
    response = pinned_tsa.issue(query)

    with pytest.raises(tsa.TsaError, match="impossibly precedes"):
        tsa.verify_receipt(
            subject, response, anchor_id=pinned_tsa.anchor_id, now=FAR_FUTURE
        )


def test_the_default_verification_clock_accepts_a_fresh_token(pinned_tsa):
    """No injected clock: the real wall clock must accept a live token."""

    receipt = tsa.request_and_verify(
        subject_bytes(),
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        transport=pinned_tsa.transport(),
    )
    assert receipt.gen_time <= datetime.now(UTC) + timedelta(seconds=5)


# --------------------------------------------------------------------------
# Accuracy and genTime rendering
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("accuracy", "expected_micros"),
    [
        (None, None),
        ("secs:2", 2_000_000),
        ("millisecs:500", 500_000),
        ("microsecs:100", 100),
        ("secs:1, millisecs:250, microsecs:999", 1_250_999),
    ],
)
def test_signed_accuracy_is_reported_in_microseconds(
    pinned_tsa, accuracy, expected_micros
):
    receipt = tsa.request_and_verify(
        subject_bytes(),
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(accuracy=accuracy),
    )
    assert receipt.accuracy_micros == expected_micros
    if expected_micros is None:
        # An absent Accuracy is an absent statement, never a fabricated zero.
        assert receipt.witness_upper_bound is None
        assert receipt.tst_info.accuracy is None
    else:
        assert receipt.witness_upper_bound == receipt.gen_time + timedelta(
            microseconds=expected_micros
        )
        assert receipt.witness_upper_bound > receipt.gen_time


@pytest.mark.parametrize("digits", [0, 1, 3, 6])
def test_a_fractional_gen_time_renders_as_valid_rfc3339(pinned_tsa, digits):
    """Regression: the fraction is trimmed, never the UTC offset.

    ``_format_utc`` used to strip trailing zeros from the fully rendered
    ``+00:00`` form, so a token whose genTime carried milliseconds produced
    ``...T12:00:00.123000+00:`` -- neither RFC 3339 nor round-trippable.
    """

    receipt = tsa.request_and_verify(
        subject_bytes(),
        SUBJECT_RECORDED_AT,
        anchor_id=pinned_tsa.anchor_id,
        now=FAR_FUTURE,
        transport=pinned_tsa.transport(
            accuracy="millisecs:500", clock_precision_digits=digits
        ),
    )
    rendered = receipt.gen_time_text
    assert rendered.endswith("Z")
    assert "+00:" not in rendered
    assert record_chain._parse_rfc3339(rendered, "genTime") == receipt.gen_time
    if digits == 0:
        assert receipt.gen_time.microsecond == 0
        assert "." not in rendered


@pytest.mark.parametrize(
    ("microsecond", "expected"),
    [
        (0, "2026-09-04T12:00:00Z"),
        (123000, "2026-09-04T12:00:00.123Z"),
        (123456, "2026-09-04T12:00:00.123456Z"),
        (100000, "2026-09-04T12:00:00.1Z"),
        (1, "2026-09-04T12:00:00.000001Z"),
        (10, "2026-09-04T12:00:00.00001Z"),
    ],
)
def test_format_utc_trims_the_fraction_not_the_offset(microsecond, expected):
    value = datetime(2026, 9, 4, 12, 0, 0, microsecond, tzinfo=UTC)
    assert record_chain._format_utc(value) == expected
    assert record_chain._parse_rfc3339(expected, "value") == value


def test_format_utc_normalizes_a_non_utc_offset():
    value = datetime(2026, 9, 4, 14, 30, 0, 500000, tzinfo=timezone(timedelta(hours=2)))
    assert record_chain._format_utc(value) == "2026-09-04T12:30:00.5Z"


# --------------------------------------------------------------------------
# TSTInfo / TimeStampReq decoding
# --------------------------------------------------------------------------


def _der(tag, content):
    if len(content) < 0x80:
        return bytes([tag, len(content)]) + content
    length = len(content).to_bytes((len(content).bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(length)]) + length + content


def _tst_info_der(*, accuracy=None, gen_time=b"20260904120000Z", trailing=b""):
    imprint = _der(
        0x30,
        _der(0x30, _der(0x06, bytes.fromhex("608648016503040201")) + _der(0x05, b""))
        + _der(0x04, b"\x11" * 32),
    )
    body = (
        _der(0x02, b"\x01")
        + _der(0x06, bytes.fromhex("2a0304010b"))
        + imprint
        + _der(0x02, b"\x02")
        + _der(0x18, gen_time)
    )
    if accuracy is not None:
        body += _der(0x30, accuracy)
    return _der(0x30, body + trailing)


def test_accuracy_decoding_accepts_every_field_combination():
    info = record_chain.parse_tst_info(
        _tst_info_der(
            accuracy=_der(0x02, b"\x01") + _der(0x80, b"\x01\xf4") + _der(0x81, b"\x64")
        )
    )
    assert info.accuracy == record_chain.TstAccuracy(seconds=1, millis=500, micros=100)
    assert info.accuracy_micros == 1_500_100
    assert info.upper_bound == info.gen_time + timedelta(microseconds=1_500_100)

    only_millis = record_chain.parse_tst_info(
        _tst_info_der(accuracy=_der(0x80, b"\x01"))
    )
    assert only_millis.accuracy == record_chain.TstAccuracy(millis=1)
    assert only_millis.accuracy_micros == 1_000


def test_absent_accuracy_is_unknown_rather_than_zero():
    info = record_chain.parse_tst_info(_tst_info_der())
    assert info.accuracy is None
    assert info.accuracy_micros is None
    assert info.upper_bound is None


@pytest.mark.parametrize(
    ("accuracy", "message"),
    [
        (_der(0x80, b"\x00"), "millis must be 1..999"),
        (_der(0x80, b"\x03\xe8"), "millis must be 1..999"),
        (_der(0x81, b"\x00"), "micros must be 1..999"),
        (_der(0x81, b"\x03\xe8"), "micros must be 1..999"),
        (_der(0x02, b"\xff"), "seconds must be non-negative"),
        (b"", "Accuracy is present but empty"),
        (
            _der(0x02, b"\x01") + _der(0x04, b"junk"),
            "trailing data in RFC 3161 Accuracy",
        ),
    ],
)
def test_malformed_accuracy_fails_closed(accuracy, message):
    with pytest.raises(record_chain.ChainError, match=message):
        record_chain.parse_tst_info(_tst_info_der(accuracy=accuracy))


def test_malformed_tst_info_der_fails_closed():
    complete = _tst_info_der()
    with pytest.raises(record_chain.ChainError, match="truncated|not one complete"):
        record_chain.parse_tst_info(complete[:-3])
    with pytest.raises(record_chain.ChainError, match="not one complete DER sequence"):
        record_chain.parse_tst_info(complete + b"\x00")
    with pytest.raises(record_chain.ChainError, match="unsupported RFC 3161 genTime"):
        record_chain.parse_tst_info(_tst_info_der(gen_time=b"not-a-time"))
    with pytest.raises(record_chain.ChainError, match="unexpected RFC 3161 TSTInfo"):
        record_chain.parse_tst_info(_tst_info_der(trailing=_der(0x04, b"junk")))


def test_the_historic_four_tuple_parser_still_works():
    info = record_chain.parse_tst_info(_tst_info_der())
    assert record_chain._parse_tst_info(_tst_info_der()) == (
        info.policy_oid,
        info.imprint_algorithm_oid,
        info.hashed_message,
        info.gen_time,
    )


def test_timestamp_query_parsing_round_trips(pinned_tsa, tmp_path):
    subject = subject_bytes()
    (tmp_path / "subject.json").write_bytes(subject)
    query = tsa.build_query(tmp_path / "subject.json")
    parsed = tsa.parse_timestamp_query(query)
    assert parsed.version == 1
    assert parsed.imprint_algorithm_oid == SHA256_OID
    assert parsed.hashed_message == hashlib.sha256(subject).digest()
    assert parsed.cert_req is True
    assert parsed.nonce is not None
    with pytest.raises(tsa.TsaError, match="timestamp query is malformed"):
        tsa.parse_timestamp_query(query[:-4])


# --------------------------------------------------------------------------
# Trust configuration cannot be widened
# --------------------------------------------------------------------------


def test_a_packaged_asset_that_drifts_from_the_code_pin_fails_closed(
    pinned_tsa, tmp_path
):
    bundle = tsa.TRUST_ASSET_DIR / Path(BUNDLE_LOGICAL_PATH).name
    bundle.write_bytes(bundle.read_bytes() + b" ")
    with pytest.raises(tsa.TsaError, match="does not match the verifier code pin"):
        tsa.verify_receipt(subject_bytes(), b"\x30\x00", anchor_id=pinned_tsa.anchor_id)


def test_a_bundle_absent_from_the_code_pins_fails_closed(pinned_tsa, monkeypatch):
    monkeypatch.setattr(record_chain, "CODE_PINNED_TRUST_BUNDLES", {})
    with pytest.raises(tsa.TsaError, match="not pinned by verifier code"):
        tsa.verify_receipt(subject_bytes(), b"\x30\x00", anchor_id=pinned_tsa.anchor_id)


def test_an_endpoint_scheme_outside_http_is_refused(pinned_tsa, monkeypatch):
    bundle = tsa.TRUST_ASSET_DIR / Path(BUNDLE_LOGICAL_PATH).name
    payload = json.loads(bundle.read_bytes())
    payload["anchors"][0]["endpoint"] = "file:///etc/passwd"
    bundle.write_bytes(canonical_bytes(payload))
    reference = dict(record_chain.CODE_PINNED_TRUST_BUNDLES[BUNDLE_LOGICAL_PATH])
    reference.update(
        sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        size=bundle.stat().st_size,
        canonicalJsonSha256=canonical_sha256(payload),
    )
    monkeypatch.setattr(
        record_chain, "CODE_PINNED_TRUST_BUNDLES", {BUNDLE_LOGICAL_PATH: reference}
    )
    with pytest.raises(tsa.TsaError, match="endpoint scheme"):
        tsa.request_and_verify(
            subject_bytes(),
            SUBJECT_RECORDED_AT,
            anchor_id=pinned_tsa.anchor_id,
            transport=lambda *_: b"",
        )


def test_a_trust_asset_outside_the_packaged_directory_is_refused(monkeypatch):
    outside = "records/trust/../secret.json"
    monkeypatch.setattr(tsa, "TRUST_BUNDLE_LOGICAL_PATH", outside)
    monkeypatch.setattr(
        record_chain,
        "CODE_PINNED_TRUST_BUNDLES",
        {outside: {"path": outside}},
    )
    with pytest.raises(tsa.TsaError, match="unsafe trust asset path"):
        tsa.anchor_ids()


# --------------------------------------------------------------------------
# Published production proofs
# --------------------------------------------------------------------------


def _published_receipts(limit_per_anchor=2):
    """Collect real published (snapshot, token, anchor) triples.

    The published witness marker is the authority for which token belongs to
    which anchor, so both the single-token v1 markers and the multi-token v2
    markers are covered.
    """

    found = {}
    markers = sorted(RECORDS.glob("????-??-??/digest-*.witness.json"))
    for marker_path in reversed(markers):
        marker = json.loads(marker_path.read_text())
        snapshot = marker_path.with_suffix("").with_suffix(".json")
        outcomes = marker.get("anchorOutcomes")
        claims = outcomes if isinstance(outcomes, list) else [marker]
        for claim in claims:
            if claim.get("status") != "available":
                continue
            anchor_id = claim.get("tsaAnchorId")
            token = claim.get("tokenPath")
            if not anchor_id or not token:
                continue
            if len(found.setdefault(anchor_id, [])) >= limit_per_anchor:
                continue
            found[anchor_id].append(
                (snapshot, RECORDS / Path(token).relative_to("records"), anchor_id)
            )
    return [triple for triples in found.values() for triple in triples]


@pytest.mark.skipif(not RECORDS.is_dir(), reason="no published records tree")
def test_published_receipts_replay_through_the_standalone_path(tmp_path, monkeypatch):
    """Real production proofs verify offline against the packaged assets."""

    triples = _published_receipts()
    anchors = {anchor_id for _snapshot, _token, anchor_id in triples}
    assert anchors == {"freetsa-root-2016", "digicert-trusted-root-g4"}, anchors

    # No records tree in reach: the packaged trust assets carry the verification.
    monkeypatch.chdir(tmp_path)
    for snapshot, token, anchor_id in triples:
        receipt = tsa.verify_receipt(
            snapshot.read_bytes(), token.read_bytes(), anchor_id=anchor_id
        )
        assert receipt.anchor_id == anchor_id
        assert receipt.trust_bundle_id == BUNDLE_ID
        subject = snapshot.read_bytes()
        assert receipt.subject_sha256 == hashlib.sha256(subject).hexdigest()
        assert receipt.gen_time_text.endswith("Z")
        assert receipt.nonce is not None
        # Neither pinned authority emits Accuracy today, so ordering by an
        # upper bound is genuinely unavailable rather than silently exact.
        assert receipt.accuracy_micros is None
        assert receipt.witness_upper_bound is None
        # A published receipt must not verify against a subject it never covered.
        with pytest.raises(tsa.TsaError):
            tsa.verify_receipt(
                snapshot.read_bytes() + b"\n", token.read_bytes(), anchor_id=anchor_id
            )
        # Nor against the other pinned anchor: an anchor is an identity, not a
        # label, so a token signed by one authority cannot be claimed for the
        # other even though both are trusted.
        other = (anchors - {anchor_id}).pop()
        with pytest.raises(tsa.TsaError):
            tsa.verify_receipt(subject, token.read_bytes(), anchor_id=other)
