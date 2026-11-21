from __future__ import annotations

import base64
import hashlib
import io
import json
import pathlib
import sys
import warnings
import zipfile
from collections.abc import Callable

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import witness_sba_pdf as witness  # noqa: E402
import witnessed_timeline as timeline_module  # noqa: E402
from record_forecast_snapshot import current_artifact_commitments  # noqa: E402
from verify_custody import CustodyError, verify_run  # noqa: E402
from verify_record_chain import ChainVerification, WitnessEvidence  # noqa: E402

FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "sba_loan_performance"
ASSET_URL = (
    "https://legacy.sba.gov/sites/default/files/2025-09/WebsiteReports_FY25Q3.zip"
)
LANDING_URL = (
    "https://legacy.sba.gov/document/"
    "report-small-business-administration-loan-program-performance"
)
REPORT_FIXTURES = (
    "WDS_ChargeOffAmount_Report_20250630.pdf",
    "WDS_ChargeOffRates_Report_20250630.pdf",
    "WDS_PostChargeOffRecovery_Report_20250630.pdf",
)


def _bundle_bytes(
    *,
    omit: str | None = None,
    extras: tuple[tuple[str, bytes], ...] = (),
    overrides: dict[str, bytes] | None = None,
) -> bytes:
    overrides = overrides or {}
    output = io.BytesIO()
    root = "WebsiteReports_FY25Q3"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in REPORT_FIXTURES:
            if name != omit:
                raw = overrides.get(name, (FIXTURE_ROOT / name).read_bytes())
                archive.writestr(f"{root}/{name}", raw)
        for name, raw in extras:
            archive.writestr(name, raw)
    return output.getvalue()


def _landing_bytes(*links: str) -> bytes:
    anchors = "".join(f'<a href="{link}">download</a>' for link in links)
    return f"<!doctype html><html><body>{anchors}</body></html>".encode()


def _bundle_with_duplicate_member() -> bytes:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return _bundle_bytes(
            extras=(
                (
                    "WebsiteReports_FY25Q3/WDS_ChargeOffAmount_Report_20250630.pdf",
                    b"duplicate",
                ),
            )
        )


def _bundle_with_encrypted_flag() -> bytes:
    raw = bytearray(_bundle_bytes())
    local = raw.index(b"PK\x03\x04")
    central = raw.index(b"PK\x01\x02")
    raw[local + 6 : local + 8] = (
        int.from_bytes(raw[local + 6 : local + 8], "little") | 1
    ).to_bytes(2, "little")
    raw[central + 8 : central + 10] = (
        int.from_bytes(raw[central + 8 : central + 10], "little") | 1
    ).to_bytes(2, "little")
    return bytes(raw)


def _success(url: str, body: bytes, content_type: str) -> witness.FetchAttempt:
    return witness.FetchAttempt(
        requested_url=url,
        redirects=(),
        final_url=url,
        status=200,
        headers={
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        },
        body=body,
        error=None,
    )


def _landing_success(body: bytes) -> witness.FetchAttempt:
    return witness.FetchAttempt(
        requested_url=witness.ENTRY_URL,
        redirects=(
            {
                "sourceUrl": witness.ENTRY_URL,
                "status": 302,
                "location": LANDING_URL,
                "targetUrl": LANDING_URL,
                "headers": {"Location": LANDING_URL},
            },
        ),
        final_url=LANDING_URL,
        status=200,
        headers={
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": str(len(body)),
        },
        body=body,
        error=None,
    )


def _fetcher(
    *attempts: witness.FetchAttempt,
) -> Callable[..., witness.FetchAttempt]:
    pending = iter(attempts)

    def fetch(
        url: str, *, timeout_seconds: float, max_bytes: int
    ) -> witness.FetchAttempt:
        del timeout_seconds, max_bytes
        attempt = next(pending)
        assert url == attempt.requested_url
        return attempt

    return fetch


def _capture(
    records: pathlib.Path,
    *,
    retrieved_at: str,
    bundle: bytes,
    landing: bytes | None = None,
) -> pathlib.Path:
    landing = landing if landing is not None else _landing_bytes(ASSET_URL)
    return witness.capture_sba_pdf(
        records,
        retrieved_at=retrieved_at,
        fetcher=_fetcher(
            _landing_success(landing),
            _success(ASSET_URL, bundle, "application/zip"),
        ),
    )


def _manifest(path: pathlib.Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    assert isinstance(value, dict)
    return value


def _ungridded_probe_bytes() -> bytes:
    encoded = (FIXTURE_ROOT / "adversarial-ungridded.pdf.b64").read_bytes()
    return base64.b64decode(encoded.strip(), validate=True)


def test_valid_zip_with_octet_stream_header_is_captured(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    landing = _landing_bytes(ASSET_URL)
    manifest_path = witness.capture_sba_pdf(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(
            _landing_success(landing),
            _success(ASSET_URL, _bundle_bytes(), "application/octet-stream"),
        ),
    )
    assert _manifest(manifest_path)["outcome"] == "bootstrap"


def test_split_single_segment_zip_is_captured(
    tmp_path: pathlib.Path,
) -> None:
    # PKWARE APPNOTE 8.5.4: a split archive with only one segment starts
    # with the PK00 marker before the first local file header. The bundle
    # validator parses it, so asset validation must accept it too — the
    # shared _require_zip_bytes boundary makes disagreement impossible.
    records = tmp_path / "records"
    landing = _landing_bytes(ASSET_URL)
    manifest_path = witness.capture_sba_pdf(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(
            _landing_success(landing),
            _success(ASSET_URL, b"PK00" + _bundle_bytes(), "application/zip"),
        ),
    )
    assert _manifest(manifest_path)["outcome"] == "bootstrap"


def test_empty_zip_retains_as_bundle_validation_failure(
    tmp_path: pathlib.Path,
) -> None:
    # An empty archive IS a parseable ZIP, so it crosses the shared
    # non-ZIP boundary and fails inside bundle validation, where the
    # capture retains and blocks later revisions. This pins the boundary
    # decision: only bodies that are not ZIPs at all escape retention.
    records = tmp_path / "records"
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w"):
        pass
    landing = _landing_bytes(ASSET_URL)
    manifest_path = witness.capture_sba_pdf(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(
            _landing_success(landing),
            _success(ASSET_URL, empty.getvalue(), "application/zip"),
        ),
    )
    manifest = _manifest(manifest_path)
    assert manifest["outcome"] == "failed"
    failure = manifest["failure"]
    assert isinstance(failure, dict)
    assert failure["stage"] == "bundle validation"
    assert isinstance(manifest.get("bundle"), dict)


def test_non_zip_bytes_with_zip_header_are_refused(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    landing = _landing_bytes(ASSET_URL)
    manifest_path = witness.capture_sba_pdf(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(
            _landing_success(landing),
            _success(ASSET_URL, b"%PDF-1.7 not a zip at all", "application/zip"),
        ),
    )
    manifest = _manifest(manifest_path)
    assert manifest["outcome"] == "failed"
    failure = manifest["failure"]
    assert isinstance(failure, dict)
    # Non-ZIP bodies fail at ASSET validation with no bundle: they carry
    # no period coverage and must never block a later real capture.
    assert failure["stage"] == "asset validation"
    assert "not a ZIP archive" in str(failure["reason"])
    assert manifest.get("bundle") is None


def test_bootstrap_capture_seals_and_strictly_replays_official_reports(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    manifest_path = _capture(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        bundle=_bundle_bytes(),
    )

    manifest = _manifest(manifest_path)
    assert manifest["schemaVersion"] == witness.RUN_SCHEMA
    assert manifest["runMode"] == witness.RUN_MODE
    assert manifest["outcome"] == "bootstrap"
    assert manifest["ok"] is True
    assert manifest["previousCompleteCapture"] is None
    bundle = manifest["bundle"]
    assert isinstance(bundle, dict)
    assert bundle["label"] == "FY25Q3"
    assert bundle["reportAsOf"] == "2025-06-30"
    assert [report["value"] for report in bundle["reports"]] == [
        299_971_326,
        3.06,
        126_510_000,
    ]
    assert {item["artifactType"] for item in manifest["artifacts"]} == {
        "fetch_event",
        "landing_archive",
        "bundle_archive",
        "manifest",
    }

    verification = verify_run(manifest_path.parent)
    assert verification.run_mode == witness.RUN_MODE
    assert verification.custody_inventory_version == 2
    assert verification.artifact_count == 3
    assert verification.run_succeeded is True


def test_capture_refuses_ungridded_pdf_probe_end_to_end(
    tmp_path: pathlib.Path,
) -> None:
    report_name = "WDS_ChargeOffAmount_Report_20250630.pdf"
    manifest_path = _capture(
        tmp_path / "records",
        retrieved_at="2026-08-07T12:00:00Z",
        bundle=_bundle_bytes(overrides={report_name: _ungridded_probe_bytes()}),
    )

    manifest = _manifest(manifest_path)
    assert manifest["outcome"] == "failed"
    assert manifest["ok"] is False
    assert manifest["failure"] == {
        "stage": "bundle validation",
        "reason": (
            "SBA CAPTURE FAILED (refusing): "
            "WebsiteReports_FY25Q3/WDS_ChargeOffAmount_Report_20250630.pdf: "
            "SBA PDF LAYOUT DRIFT (refusing): page 1 has no reviewed table grid"
        ),
    }
    bundle = manifest["bundle"]
    assert isinstance(bundle, dict)
    assert bundle["periodCoverage"] == {
        "periodType": "fiscal_year",
        "displayedFiscalYears": list(range(2016, 2026)),
        "possibleCompletedFiscalYears": list(range(2016, 2025)),
    }
    assert (manifest_path.parent / bundle["zipArchive"]["path"]).is_file()
    assert verify_run(manifest_path.parent).run_succeeded is False


def test_changed_capture_archives_and_replays_new_bundle(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    original = _bundle_bytes()
    first = _capture(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        bundle=original,
    )
    changed = _bundle_bytes(
        extras=(("WebsiteReports_FY25Q3/README.txt", b"changed bundle"),)
    )

    second = _capture(
        records,
        retrieved_at="2026-08-08T12:00:00Z",
        bundle=changed,
    )

    first_manifest = _manifest(first)
    second_manifest = _manifest(second)
    assert second_manifest["outcome"] == "changed"
    assert second_manifest["previousCompleteCapture"] is None
    assert (
        second_manifest["bundle"]["rawSha256"] != first_manifest["bundle"]["rawSha256"]
    )
    assert (second.parent / "upstream" / "landing-page.html.gz").is_file()
    assert (second.parent / "upstream" / "loan-program-performance.zip.gz").is_file()
    assert verify_run(second.parent).run_succeeded is True


def test_unchanged_capture_references_verified_prior_bytes_without_duplication(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    bundle = _bundle_bytes()
    first = _capture(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        bundle=bundle,
    )

    second = _capture(
        records,
        retrieved_at="2026-08-08T12:00:00Z",
        bundle=bundle,
    )

    first_manifest = _manifest(first)
    second_manifest = _manifest(second)
    assert second_manifest["outcome"] == "unchanged"
    assert (
        second_manifest["bundle"]["rawSha256"] == first_manifest["bundle"]["rawSha256"]
    )
    previous = second_manifest["previousCompleteCapture"]
    assert previous["runDirectory"] == first.parent.relative_to(tmp_path).as_posix()
    assert (
        previous["custodyRootPath"]
        == (first.parent / "custody_root.json").relative_to(tmp_path).as_posix()
    )
    # The fresh landing body proves which asset the page linked on this poll;
    # the unchanged ZIP itself is deduplicated through the prior custody root.
    assert (second.parent / "upstream" / "landing-page.html.gz").is_file()
    assert not (second.parent / "upstream" / "loan-program-performance.zip.gz").exists()
    assert [item["artifactType"] for item in second_manifest["artifacts"]] == [
        "fetch_event",
        "landing_archive",
        "manifest",
    ]
    verification = verify_run(second.parent)
    assert verification.artifact_count == 2
    assert verification.run_succeeded is True


def test_failed_network_attempt_is_still_custody_rooted(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    failed = witness.FetchAttempt(
        requested_url=witness.ENTRY_URL,
        redirects=(),
        final_url=witness.ENTRY_URL,
        status=None,
        headers={},
        body=None,
        error="network fetch failed: TimeoutError",
    )

    manifest_path = witness.capture_sba_pdf(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(failed),
    )

    manifest = _manifest(manifest_path)
    assert manifest["outcome"] == "failed"
    assert manifest["ok"] is False
    assert manifest["bundle"] is None
    assert manifest["failure"] == {
        "stage": "landing fetch",
        "reason": ("SBA CAPTURE FAILED (refusing): network fetch failed: TimeoutError"),
    }
    verification = verify_run(manifest_path.parent)
    assert verification.artifact_count == 1
    assert verification.run_succeeded is False


def test_failed_off_host_redirect_is_preserved_without_following_it(
    tmp_path: pathlib.Path,
) -> None:
    target = "https://example.com/WebsiteReports_FY25Q3.zip"
    failed = witness.FetchAttempt(
        requested_url=witness.ENTRY_URL,
        redirects=(
            {
                "sourceUrl": witness.ENTRY_URL,
                "status": 302,
                "location": target,
                "targetUrl": target,
                "headers": {"Location": target},
            },
        ),
        final_url=target,
        status=None,
        headers={},
        body=None,
        error="redirect target host 'example.com' is outside the SBA allowlist",
    )

    manifest_path = witness.capture_sba_pdf(
        tmp_path / "records",
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(failed),
    )

    manifest = _manifest(manifest_path)
    assert manifest["outcome"] == "failed"
    assert "outside the SBA allowlist" in manifest["failure"]["reason"]
    assert verify_run(manifest_path.parent).run_succeeded is False


def test_redirect_limit_is_sealed_as_a_failed_attempt(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class RedirectingOpener:
        def __init__(self) -> None:
            self.count = 0

        def open(self, request: object, *, timeout: float) -> object:
            del timeout
            self.count += 1
            target = f"{witness.ENTRY_URL}?hop={self.count}"
            raise witness.urllib.error.HTTPError(
                request.full_url,
                302,
                "Found",
                {"Location": target},
                io.BytesIO(),
            )

    opener = RedirectingOpener()
    monkeypatch.setattr(
        witness.urllib.request,
        "build_opener",
        lambda *handlers: opener,
    )
    attempt = witness._fetch_url(
        witness.ENTRY_URL,
        timeout_seconds=1,
        max_bytes=witness.MAX_LANDING_BYTES,
    )
    assert len(attempt.redirects) == witness.MAX_REDIRECTS
    assert attempt.error == f"redirect chain exceeds {witness.MAX_REDIRECTS} hops"

    manifest_path = witness.capture_sba_pdf(
        tmp_path / "records",
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(attempt),
    )
    assert _manifest(manifest_path)["outcome"] == "failed"
    assert verify_run(manifest_path.parent).run_succeeded is False


@pytest.mark.parametrize(
    ("read_mode", "expected_detail"),
    [
        ("oversized", "response exceeds the 3-byte capture limit"),
        ("error", "simulated response read error"),
        ("incomplete", "IncompleteRead(2 bytes read, 1 more expected)"),
    ],
)
def test_response_read_failure_preserves_received_http_metadata(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    read_mode: str,
    expected_detail: str,
) -> None:
    class BrokenResponse:
        status = 200
        headers = {
            "Content-Type": "text/html; charset=utf-8",
            "ETag": '"received-before-read"',
            "X-Ignored": "not retained",
        }

        def __enter__(self) -> BrokenResponse:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def geturl(self) -> str:
            return witness.ENTRY_URL

        def read(self, maximum: int) -> bytes:
            if read_mode == "error":
                raise OSError("simulated response read error")
            if read_mode == "incomplete":
                raise witness.http.client.IncompleteRead(b"xx", 1)
            return b"x" * maximum

    class BrokenOpener:
        def open(self, request: object, *, timeout: float) -> BrokenResponse:
            del request, timeout
            return BrokenResponse()

    monkeypatch.setattr(
        witness.urllib.request,
        "build_opener",
        lambda *handlers: BrokenOpener(),
    )
    attempt = witness._fetch_url(
        witness.ENTRY_URL,
        timeout_seconds=1,
        max_bytes=3,
    )

    assert attempt.final_url == witness.ENTRY_URL
    assert attempt.status == 200
    assert attempt.headers == {
        "Content-Type": "text/html; charset=utf-8",
        "ETag": '"received-before-read"',
    }
    assert attempt.body is None
    assert attempt.error == f"response read failed: {expected_detail}"

    manifest_path = witness.capture_sba_pdf(
        tmp_path / "records",
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(attempt),
    )
    assert _manifest(manifest_path)["outcome"] == "failed"
    assert verify_run(manifest_path.parent).run_succeeded is False


def test_http_error_body_read_failure_preserves_received_metadata(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class IncompleteHttpError(witness.urllib.error.HTTPError):
        def read(self, amount: int = -1) -> bytes:
            del amount
            raise witness.http.client.IncompleteRead(b"x", 2)

    error = IncompleteHttpError(
        witness.ENTRY_URL,
        503,
        "Service Unavailable",
        {
            "Content-Type": "text/html",
            "ETag": '"failed-response"',
            "X-Ignored": "not retained",
        },
        None,
    )

    class BrokenOpener:
        def open(self, request: object, *, timeout: float) -> object:
            del request, timeout
            raise error

    monkeypatch.setattr(
        witness.urllib.request,
        "build_opener",
        lambda *handlers: BrokenOpener(),
    )
    attempt = witness._fetch_url(
        witness.ENTRY_URL,
        timeout_seconds=1,
        max_bytes=3,
    )

    assert attempt.final_url == witness.ENTRY_URL
    assert attempt.status == 503
    assert attempt.headers == {
        "Content-Type": "text/html",
        "ETag": '"failed-response"',
    }
    assert attempt.body is None
    assert attempt.error == (
        "response read failed: IncompleteRead(1 bytes read, 2 more expected)"
    )

    manifest_path = witness.capture_sba_pdf(
        tmp_path / "records",
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(attempt),
    )
    assert _manifest(manifest_path)["outcome"] == "failed"
    assert verify_run(manifest_path.parent).run_succeeded is False


@pytest.mark.parametrize(
    ("links", "expected_detail"),
    [
        (
            ("https://example.com/WebsiteReports_FY25Q3.zip",),
            "found 0",
        ),
        ((ASSET_URL, ASSET_URL), "found 2"),
    ],
)
def test_capture_refuses_unapproved_or_ambiguous_page_links(
    tmp_path: pathlib.Path,
    links: tuple[str, ...],
    expected_detail: str,
) -> None:
    landing = _landing_bytes(*links)

    manifest_path = witness.capture_sba_pdf(
        tmp_path / "records",
        retrieved_at="2026-08-07T12:00:00Z",
        fetcher=_fetcher(
            _success(witness.ENTRY_URL, landing, "text/html; charset=utf-8")
        ),
    )

    manifest = _manifest(manifest_path)
    assert manifest["outcome"] == "failed"
    assert manifest["failure"]["stage"] == "landing validation"
    assert expected_detail in manifest["failure"]["reason"]
    assert verify_run(manifest_path.parent).run_succeeded is False


@pytest.mark.parametrize(
    ("bundle", "expected_detail"),
    [
        (
            _bundle_bytes(extras=(("../escape.txt", b"unsafe"),)),
            "unsafe ZIP member path",
        ),
        (
            _bundle_bytes(extras=(("WebsiteReports_FY25Q3/./alias.txt", b"unsafe"),)),
            "is not canonical",
        ),
        (_bundle_bytes(extras=((".", b"unsafe"),)), "unsafe ZIP member path"),
        (
            _bundle_bytes(omit="WDS_PostChargeOffRecovery_Report_20250630.pdf"),
            "must occur once, found 0",
        ),
        (_bundle_with_duplicate_member(), "duplicate ZIP member path"),
        (_bundle_with_encrypted_flag(), "encrypted ZIP member"),
        (b"PK malformed", "not a ZIP archive"),
        (b"not a ZIP", "not a ZIP archive"),
    ],
    # Without ids pytest names each case after its bytes, ZIP timestamps
    # included, and xdist stops the run if two workers collect different names.
    ids=[
        "parent_path",
        "dot_segment",
        "dot_member",
        "missing_report",
        "duplicate_member",
        "encrypted_member",
        "malformed_header",
        "not_a_zip",
    ],
)
def test_capture_refuses_unsafe_or_incomplete_zip(
    tmp_path: pathlib.Path,
    bundle: bytes,
    expected_detail: str,
) -> None:
    manifest_path = _capture(
        tmp_path / "records",
        retrieved_at="2026-08-07T12:00:00Z",
        bundle=bundle,
    )

    manifest = _manifest(manifest_path)
    assert manifest["outcome"] == "failed"
    assert manifest["failure"]["reason"].startswith(witness.CAPTURE_REFUSAL)
    assert expected_detail in manifest["failure"]["reason"]
    assert verify_run(manifest_path.parent).run_succeeded is False


def test_verifier_rejects_tampered_archive(tmp_path: pathlib.Path) -> None:
    manifest_path = _capture(
        tmp_path / "records",
        retrieved_at="2026-08-07T12:00:00Z",
        bundle=_bundle_bytes(),
    )
    archive = manifest_path.parent / "upstream" / "loan-program-performance.zip.gz"
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(CustodyError, match="raw SHA-256 mismatch"):
        verify_run(manifest_path.parent)


def test_verifier_rejects_unreferenced_run_file(tmp_path: pathlib.Path) -> None:
    manifest_path = _capture(
        tmp_path / "records",
        retrieved_at="2026-08-07T12:00:00Z",
        bundle=_bundle_bytes(),
    )
    (manifest_path.parent / "unreferenced.txt").write_text("not custody rooted")

    with pytest.raises(CustodyError, match="run directory inventory mismatch"):
        verify_run(manifest_path.parent)


def test_unchanged_verifier_replays_the_fresh_landing_link(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = tmp_path / "records"
    bundle = _bundle_bytes()
    _capture(records, retrieved_at="2026-08-07T12:00:00Z", bundle=bundle)
    identity = witness.BundleIdentity(
        label="FY25Q3",
        fiscal_year=2025,
        quarter=3,
        linked_url=ASSET_URL,
    )
    with monkeypatch.context() as context:
        context.setattr(witness, "_linked_bundle", lambda *args, **kwargs: identity)
        invalid = _capture(
            records,
            retrieved_at="2026-08-08T12:00:00Z",
            bundle=bundle,
            landing=_landing_bytes(),
        )

    with pytest.raises(CustodyError, match="unchanged landing replay refused"):
        verify_run(invalid.parent)


def test_unchanged_reference_must_precede_the_current_run(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    bundle = _bundle_bytes()
    _capture(records, retrieved_at="2026-08-09T12:00:00Z", bundle=bundle)

    with pytest.raises(CustodyError, match="does not precede"):
        _capture(records, retrieved_at="2026-08-08T12:00:00Z", bundle=bundle)


def test_failed_stage_must_match_structured_fetch_state(
    tmp_path: pathlib.Path,
) -> None:
    landing = _landing_bytes(ASSET_URL)
    with pytest.raises(CustodyError, match="failure stage disagrees"):
        witness._seal_run(
            records=tmp_path / "records",
            retrieved_at="2026-08-07T12:00:00Z",
            outcome="failed",
            landing=_landing_success(landing),
            asset=_success(ASSET_URL, _bundle_bytes(), "application/zip"),
            bundle=None,
            previous=None,
            failure_stage="landing fetch",
            failure_reason=f"{witness.CAPTURE_REFUSAL} fabricated timeout",
        )


def test_recorder_commitments_include_verified_sba_capture_root(
    tmp_path: pathlib.Path,
) -> None:
    records = tmp_path / "records"
    manifest_path = _capture(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        bundle=_bundle_bytes(),
    )
    verified = verify_run(manifest_path.parent)

    commitments = current_artifact_commitments(records)

    assert commitments["registrationSnapshots"] == []
    assert commitments["custodyRoots"] == [
        {
            "runDirectory": manifest_path.parent.relative_to(tmp_path).as_posix(),
            "custodyRootPath": (manifest_path.parent / "custody_root.json")
            .relative_to(tmp_path)
            .as_posix(),
            "custodyRootSha256": verified.custody_root_sha256,
            "custodyRootFileSha256": commitments["custodyRoots"][0][
                "custodyRootFileSha256"
            ],
            "custodyRootSize": (manifest_path.parent / "custody_root.json")
            .stat()
            .st_size,
            "custodyInventoryVersion": 2,
            "manifestPath": manifest_path.relative_to(tmp_path).as_posix(),
            "manifestSha256": commitments["custodyRoots"][0]["manifestSha256"],
            "manifestSize": manifest_path.stat().st_size,
        }
    ]


def test_sba_root_enters_timeline_only_after_available_witness(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = tmp_path / "records"
    manifest_path = _capture(
        records,
        retrieved_at="2026-08-07T12:00:00Z",
        bundle=_bundle_bytes(),
    )
    commitment = current_artifact_commitments(records)["custodyRoots"][0]
    (records / "CHAIN_GENESIS.json").write_text("{}\n")
    first = records / "2026-08-08" / "digest-sba.json"
    first.parent.mkdir(parents=True)
    first.write_text(
        json.dumps(
            {
                "artifactCommitments": {
                    "custodyRoots": [commitment],
                    "registrationSnapshots": [],
                }
            }
        )
        + "\n"
    )
    second = records / "2026-08-09" / "digest-successor.json"
    second.parent.mkdir(parents=True)
    second.write_text(
        json.dumps(
            {
                "artifactCommitments": {
                    "custodyRoots": [],
                    "registrationSnapshots": [],
                }
            }
        )
        + "\n"
    )
    unavailable = WitnessEvidence(
        status="unavailable",
        digest_sha256=hashlib.sha256(first.read_bytes()).hexdigest(),
    )
    available = WitnessEvidence(
        status="available",
        digest_sha256=hashlib.sha256(second.read_bytes()).hexdigest(),
        gen_time="2026-08-09T13:00:00Z",
    )

    monkeypatch.setattr(
        timeline_module,
        "verify_chain",
        lambda _records: ChainVerification(
            ordered=(first,),
            witnesses={first: unavailable},
            enumeration_cutover=None,
        ),
    )
    without_witness = timeline_module.extract_timeline(records)
    assert without_witness["custodyRoots"] == {}
    assert without_witness["runs"] == {}

    monkeypatch.setattr(
        timeline_module,
        "verify_chain",
        lambda _records: ChainVerification(
            ordered=(first, second),
            witnesses={first: unavailable, second: available},
            enumeration_cutover=None,
        ),
    )
    witnessed = timeline_module.extract_timeline(records)
    proof = witnessed["custodyRoots"][commitment["custodyRootSha256"]]
    assert proof["earliestWitnessedAt"] == "2026-08-09T13:00:00Z"
    assert proof["coverage"] == "transitive"
    run_key = manifest_path.parent.relative_to(tmp_path).as_posix()
    assert witnessed["runs"][run_key]["earliestWitnessedAt"] == ("2026-08-09T13:00:00Z")
