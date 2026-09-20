from __future__ import annotations

import gzip
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TSA_FIXTURE = ROOT / "tests" / "fixtures" / "release_tsa"
sys.path.insert(0, str(ROOT / "scripts"))

import verify_witnessed_pin as vwp  # noqa: E402
import witness_upstream_ledger as wul  # noqa: E402
from canonical_json import canonical_bytes  # noqa: E402
from verify_custody import CustodyError, verify_run  # noqa: E402


def _jsonl_bytes(rows: list[dict], *, ensure_ascii: bool = True) -> bytes:
    return b"".join(
        json.dumps(row, separators=(",", ":"), ensure_ascii=ensure_ascii).encode(
            "utf-8"
        )
        + b"\n"
        for row in rows
    )


def _catalog_bytes(jsonl_raw: bytes) -> bytes:
    return (
        json.dumps(
            {
                "generator_version": 1,
                "observations_sha256": hashlib.sha256(jsonl_raw).hexdigest(),
                "observation_rows": len(jsonl_raw.splitlines()),
                "series": [],
            },
            indent=2,
        )
        + "\n"
    ).encode()


def _git_blob_sha(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw, usedforsecurity=False).hexdigest()


def _tree_bytes(sha: str, entries: list[dict]) -> bytes:
    return json.dumps(
        {"sha": sha, "tree": entries, "truncated": False},
        separators=(",", ":"),
    ).encode()


def _git_tree_sha(entries: list[dict]) -> str:
    body = bytearray()
    for entry in entries:
        mode = entry["mode"].lstrip("0") or "0"
        body.extend(f"{mode} {entry['path']}\0".encode())
        body.extend(bytes.fromhex(entry["sha"]))
    header = f"tree {len(body)}\0".encode()
    return hashlib.sha1(header + body, usedforsecurity=False).hexdigest()


def _mint_receipt(
    tsa: pathlib.Path,
    payload: pathlib.Path,
    *,
    signer: str,
) -> bytes:
    query = tsa / f"{signer}.tsq"
    receipt = tsa / f"{signer}.tsr"
    subprocess.run(
        [
            "openssl",
            "ts",
            "-query",
            "-data",
            str(payload),
            "-sha256",
            "-cert",
            "-out",
            str(query),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "ts",
            "-reply",
            "-config",
            "openssl-ts.cnf",
            "-queryfile",
            str(query),
            "-out",
            str(receipt),
        ],
        cwd=tsa / signer,
        check=True,
        capture_output=True,
    )
    return receipt.read_bytes()


def _mint_producer_signature(
    private_key: pathlib.Path,
    payload: pathlib.Path,
) -> bytes:
    if not private_key.exists():
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "Ed25519",
                "-out",
                str(private_key),
            ],
            check=True,
            capture_output=True,
        )
    signature = payload.with_name(f"{payload.stem}.producer.sig")
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private_key),
            "-rawin",
            "-in",
            str(payload),
            "-out",
            str(signature),
        ],
        check=True,
        capture_output=True,
    )
    return signature.read_bytes()


def _release_inputs(
    tmp_path: pathlib.Path,
    monkeypatch,
    *,
    with_chain: bool,
    jsonl_raw: bytes,
    release_count: int = 1,
    with_producer_signatures: bool = True,
):
    branch_sha = "b" * 40
    base = f"https://api.github.com/repos/{wul.LEDGER_REPO}/git/trees/"
    responses: dict[str, bytes] = {}
    source_files: dict[str, bytes] = {}
    if with_chain:
        if release_count not in {1, 2}:
            raise AssertionError("fixture supports one or two releases")
        tsa = tmp_path / "release_tsa"
        shutil.copytree(TSA_FIXTURE, tsa)
        producer_private_key = tmp_path / "producer-ed25519-test-private.pem"
        rows = jsonl_raw.splitlines(keepends=True)
        line_counts = [len(rows)] if release_count == 1 else [1, len(rows)]
        previous_count = 0
        previous_digest = None
        for index, line_count in enumerate(line_counts):
            state_bytes = b"".join(rows[:line_count])
            if index == 0:
                append = None
            else:
                suffix = b"".join(rows[previous_count:line_count])
                append = {
                    "previousLineCount": previous_count,
                    "appendedRowCount": line_count - previous_count,
                    "appendedBytesSha256": hashlib.sha256(suffix).hexdigest(),
                }
            manifest_raw = (
                canonical_bytes(
                    {
                        "schemaVersion": "thesis_ledger_release_v1",
                        "releaseIndex": index,
                        "previousManifestSha256": previous_digest,
                        "state": {
                            "path": wul.LEDGER_JSONL_PATH,
                            "jsonlSha256": hashlib.sha256(state_bytes).hexdigest(),
                            "lineCount": line_count,
                            "immutablePrefixSha256": hashlib.sha256(
                                b"{}\n"
                            ).hexdigest(),
                        },
                        "append": append,
                        "createdAtUtc": f"2020-01-01T00:00:0{index}Z",
                        "producer": {
                            "repo": wul.LEDGER_REPO,
                            "branch": wul.LEDGER_BRANCH,
                        },
                    }
                )
                + b"\n"
            )
            digest = hashlib.sha256(manifest_raw).hexdigest()
            manifest_name = f"{index:04d}-{digest[:16]}.json"
            manifest_path = tmp_path / manifest_name
            manifest_path.write_bytes(manifest_raw)
            source_files[f"releases/manifests/{manifest_name}"] = manifest_raw
            for tsa_name in ("freetsa", "digicert"):
                source_files[
                    f"releases/manifests/{manifest_path.stem}.{tsa_name}.tsr"
                ] = _mint_receipt(tsa, manifest_path, signer=tsa_name)
            if with_producer_signatures:
                source_files[
                    f"releases/manifests/{manifest_path.stem}.producer.sig"
                ] = _mint_producer_signature(producer_private_key, manifest_path)
            previous_count = line_count
            previous_digest = digest
        manifest_entries = [
            {
                "path": pathlib.PurePosixPath(path).name,
                "mode": "100644",
                "type": "blob",
                "sha": _git_blob_sha(raw),
            }
            for path, raw in sorted(source_files.items())
        ]
        manifests_tree_sha = _git_tree_sha(manifest_entries)
        responses[base + manifests_tree_sha] = _tree_bytes(
            manifests_tree_sha, manifest_entries
        )
        releases_entries = [
            {
                "path": "manifests",
                "mode": "040000",
                "type": "tree",
                "sha": manifests_tree_sha,
            }
        ]
        releases_tree_sha = _git_tree_sha(releases_entries)
        responses[base + releases_tree_sha] = _tree_bytes(
            releases_tree_sha, releases_entries
        )
        commit_entries = [
            {
                "path": "releases",
                "mode": "040000",
                "type": "tree",
                "sha": releases_tree_sha,
            }
        ]
        commit_tree_sha = _git_tree_sha(commit_entries)
        responses[base + commit_tree_sha] = _tree_bytes(commit_tree_sha, commit_entries)
        for path, raw in source_files.items():
            responses[
                f"https://raw.githubusercontent.com/{wul.LEDGER_REPO}/{branch_sha}/{path}"
            ] = raw
    else:
        commit_tree_sha = _git_tree_sha([])
        responses[base + commit_tree_sha] = _tree_bytes(commit_tree_sha, [])
    branch_commit_raw = json.dumps(
        {
            "sha": branch_sha,
            "commit": {"tree": {"sha": commit_tree_sha}},
        },
        separators=(",", ":"),
    ).encode()

    def fetch(url: str) -> bytes:
        try:
            return responses[url]
        except KeyError as exc:
            raise AssertionError(f"unexpected fixture fetch: {url}") from exc

    monkeypatch.setattr(wul, "_fetch", fetch)
    release_archive, inputs = wul._release_archive_inputs(branch_sha, branch_commit_raw)
    return branch_sha, branch_commit_raw, release_archive, inputs, source_files


def _v2_witness_run(
    tmp_path: pathlib.Path,
    monkeypatch,
    *,
    with_chain: bool = True,
    with_catalog: bool = False,
    release_count: int = 1,
    with_producer_signatures: bool = True,
    skip_archive_names: set[str] | None = None,
    skip_source_suffix: str | None = None,
    mutate_manifest=None,
) -> tuple[pathlib.Path, dict[str, bytes]]:
    monkeypatch.setattr(wul, "ROOT", tmp_path)
    jsonl_raw = _jsonl_bytes(
        [
            {"source_record_id": "series.a.2030", "value": 1},
            {"source_record_id": "series.b.2030", "value": 2},
        ]
    )
    catalog_raw = _catalog_bytes(jsonl_raw)
    branch_sha, branch_commit_raw, release_archive, release_inputs, source_files = (
        _release_inputs(
            tmp_path,
            monkeypatch,
            with_chain=with_chain,
            jsonl_raw=jsonl_raw,
            release_count=release_count,
            with_producer_signatures=with_producer_signatures,
        )
    )
    skipped = set(skip_archive_names or set())
    if skip_source_suffix is not None:
        skipped.update(
            file["archiveName"]
            for file in release_archive["files"]
            if file["path"].endswith(skip_source_suffix)
        )
    run_dir = tmp_path / "records" / "2030-01-01" / "run-ledger-witness-v2"
    run_dir.mkdir(parents=True)
    main_sha = "c" * 40
    archive_inputs = [
        wul.ArchiveInput(
            "official-observations.jsonl",
            jsonl_raw,
            "official_observations_jsonl",
            f"https://raw.githubusercontent.com/{wul.LEDGER_REPO}/{branch_sha}/"
            f"{wul.LEDGER_JSONL_PATH}",
        ),
        *(
            [
                wul.ArchiveInput(
                    "series-catalog.json",
                    catalog_raw,
                    "series_catalog_json",
                    f"https://raw.githubusercontent.com/{wul.LEDGER_REPO}/"
                    f"{branch_sha}/{wul.LEDGER_CATALOG_PATH}",
                )
            ]
            if with_catalog
            else []
        ),
        wul.ArchiveInput(
            "ledger-branch-commit.json",
            branch_commit_raw,
            "ledger_branch_commit_api",
            f"https://api.github.com/repos/{wul.LEDGER_REPO}/commits/{branch_sha}",
        ),
        wul.ArchiveInput(
            "ledger-main-commit.json",
            json.dumps({"sha": main_sha}).encode(),
            "ledger_main_commit_api",
            f"https://api.github.com/repos/{wul.LEDGER_REPO}/commits/{main_sha}",
        ),
        *release_inputs,
    ]
    upstream = []
    for item in archive_inputs:
        if item.name in skipped:
            continue
        record = wul._archive(
            run_dir,
            item.name,
            item.raw,
            role=item.role,
            url=item.url,
        )
        if item.metadata:
            record.update(item.metadata)
        upstream.append(record)
    manifest = {
        "schemaVersion": wul.WITNESS_SCHEMA,
        "retrievedAt": "2030-01-01T00:00:00Z",
        "ledgerRepo": wul.LEDGER_REPO,
        "ledgerBranch": wul.LEDGER_BRANCH,
        "ledgerBranchSha": branch_sha,
        "ledgerMainSha": main_sha,
        "jsonl": wul._validate_jsonl(jsonl_raw),
        **(
            {
                "catalog": wul._validate_catalog(
                    catalog_raw, wul._validate_jsonl(jsonl_raw)
                )
            }
            if with_catalog
            else {}
        ),
        "releaseArchive": release_archive,
        "upstream": upstream,
    }
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    wul._seal(run_dir, manifest)
    return run_dir, source_files


def _witness_run(
    tmp_path: pathlib.Path,
    monkeypatch,
    *,
    rows: list[dict] | None = None,
    ensure_ascii: bool = True,
) -> pathlib.Path:
    monkeypatch.setattr(wul, "ROOT", tmp_path)
    run_dir = tmp_path / "records" / "2030-01-01" / "run-ledger-witness"
    run_dir.mkdir(parents=True)
    jsonl_raw = _jsonl_bytes(
        rows
        or [
            {"source_record_id": "series.a.2030", "value": 1},
            {"source_record_id": "series.b.2030", "value": 2},
        ],
        ensure_ascii=ensure_ascii,
    )
    branch_url = (
        "https://raw.githubusercontent.com/PolicyEngine/chronicle/"
        + ("b" * 40)
        + "/ledger/official_observations.jsonl"
    )
    upstream = [
        wul._archive(
            run_dir,
            "official-observations.jsonl",
            jsonl_raw,
            role="official_observations_jsonl",
            url=branch_url,
        ),
        wul._archive(
            run_dir,
            "ledger-branch-commit.json",
            json.dumps({"sha": "b" * 40}).encode(),
            role="ledger_branch_commit_api",
            url="https://example.test/commit",
        ),
        wul._archive(
            run_dir,
            "ledger-main-commit.json",
            json.dumps({"sha": "c" * 40}).encode(),
            role="ledger_main_commit_api",
            url="https://example.test/main-commit",
        ),
    ]
    manifest = {
        "schemaVersion": "thesis_ledger_witness_run_v1",
        "retrievedAt": "2030-01-01T00:00:00Z",
        "ledgerRepo": "PolicyEngine/chronicle",
        "ledgerBranch": "codex/thesis-ledger-facts",
        "ledgerBranchSha": "b" * 40,
        "ledgerMainSha": "c" * 40,
        "jsonl": wul._validate_jsonl(jsonl_raw),
        "upstream": upstream,
    }
    wul._seal(run_dir, manifest)
    return run_dir


def _remove_seal_fields(manifest: dict) -> None:
    for key in (
        "custodyInventoryVersion",
        "runMode",
        "ok",
        "manifestHashSemantics",
        "artifacts",
        "custodyRootSha256",
    ):
        manifest.pop(key, None)


def _receipt_times_for_stem(
    tmp_path: pathlib.Path, manifest: dict, stem: str
) -> dict[str, str]:
    receipt_times: dict[str, str] = {}
    for tsa in ("freetsa", "digicert"):
        record = next(
            item
            for item in manifest["upstream"]
            if str(item.get("sourcePath", "")).endswith(f"{stem}.{tsa}.tsr")
        )
        receipt_path = tmp_path / record["archive"]["path"]
        receipt_times[tsa] = vwp._receipt_gen_time(
            gzip.decompress(receipt_path.read_bytes()),
            str(record["sourcePath"]),
        )
    return receipt_times


def _pin_for_witness(tmp_path: pathlib.Path, run_dir: pathlib.Path) -> pathlib.Path:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    release_manifest = max(
        (
            item
            for item in manifest["releaseArchive"]["files"]
            if str(item["path"]).endswith(".json")
        ),
        key=lambda item: str(item["path"]),
    )
    match = re.fullmatch(
        r"releases/manifests/(?P<index>[0-9]{4})-[0-9a-f]{16}\.json",
        release_manifest["path"],
    )
    assert match is not None
    stem = pathlib.PurePosixPath(release_manifest["path"]).stem
    receipt_times = _receipt_times_for_stem(tmp_path, manifest, stem)
    pin = {
        "schemaVersion": "thesis_ledger_pin_v1",
        "repo": wul.LEDGER_REPO,
        "branch": wul.LEDGER_BRANCH,
        "sha": manifest["ledgerBranchSha"],
        "jsonlSha256": manifest["jsonl"]["sha256"],
        "jsonlBytes": manifest["jsonl"]["bytes"],
        "lineCount": manifest["jsonl"]["lineCount"],
        "pinnedAtUtc": "2030-01-01T00:00:00Z",
        "releaseHead": {
            "index": int(match.group("index")),
            "manifestSha256": release_manifest["sha256"],
            "freetsaGenTimeUtc": receipt_times["freetsa"],
            "digicertGenTimeUtc": receipt_times["digicert"],
        },
    }
    if "catalog" in manifest:
        pin.update(
            {
                "catalogSha256": manifest["catalog"]["sha256"],
                "catalogBytes": manifest["catalog"]["bytes"],
            }
        )
    path = tmp_path / "ledger-pin.json"
    path.write_text(json.dumps(pin, indent=2) + "\n")
    return path


def test_jsonl_line_count_splits_on_newlines_only() -> None:
    # A row containing U+0085 or U+2028 (which non-ASCII JSON writers leave
    # unescaped inside strings) must count as one line, matching
    # pin_ledger._lines and the custody verifier; str.splitlines() would
    # count four lines here and the witnessed lineCount would disagree with
    # the pinned one.
    raw = (
        '{"source_record_id": "a", "title": "x\u0085y\u2028z"}\n'
        '{"source_record_id": "b"}\n'
    ).encode("utf-8")
    assert len(raw.decode("utf-8").splitlines()) == 4

    result = wul._validate_jsonl(raw)

    assert result["lineCount"] == 2
    assert result["sourceRecordIdCount"] == 2


def test_witness_run_verifies_rows_with_unicode_line_separators(
    tmp_path, monkeypatch
) -> None:
    # The upstream ledger is written by a non-ASCII JSON writer; a row whose
    # text carries U+0085 or U+2028 is still one line for both the witness
    # writer and the custody verifier's lineCount check.
    run_dir = _witness_run(
        tmp_path,
        monkeypatch,
        rows=[
            {"source_record_id": "series.a.2030", "value": 1, "note": "x\u0085y\u2028z"},
            {"source_record_id": "series.b.2030", "value": 2},
        ],
        ensure_ascii=False,
    )
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["jsonl"]["lineCount"] == 2

    result = verify_run(run_dir)

    assert result.run_mode == "ledger_witness"
    assert result.inventory_status == "complete"


def test_witness_run_seals_and_verifies(tmp_path, monkeypatch) -> None:
    run_dir = _witness_run(tmp_path, monkeypatch)

    result = verify_run(run_dir)

    assert result.run_mode == "ledger_witness"
    assert result.inventory_status == "complete"
    assert result.headline_eligible is False
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["jsonl"]["lineCount"] == 2
    assert manifest["jsonl"]["sourceRecordIdCount"] == 2


def test_v2_witness_archives_and_verifies_series_catalog(tmp_path, monkeypatch) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch, with_catalog=True)

    result = verify_run(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    catalog_record = next(
        item for item in manifest["upstream"] if item["role"] == "series_catalog_json"
    )
    catalog_raw = gzip.decompress(
        (tmp_path / catalog_record["archive"]["path"]).read_bytes()
    )
    catalog = json.loads(catalog_raw)

    assert result.inventory_status == "complete"
    assert catalog_record["name"] == "series-catalog.json"
    assert catalog_record["url"] == (
        f"https://raw.githubusercontent.com/{wul.LEDGER_REPO}/"
        f"{manifest['ledgerBranchSha']}/{wul.LEDGER_CATALOG_PATH}"
    )
    assert manifest["catalog"] == {
        "sha256": hashlib.sha256(catalog_raw).hexdigest(),
        "bytes": len(catalog_raw),
    }
    assert catalog["observations_sha256"] == manifest["jsonl"]["sha256"]
    assert catalog["observation_rows"] == manifest["jsonl"]["lineCount"]

    pin_path = _pin_for_witness(tmp_path, run_dir)
    pin = json.loads(pin_path.read_text())
    assert pin["catalogSha256"] == manifest["catalog"]["sha256"]
    assert pin["catalogBytes"] == manifest["catalog"]["bytes"]
    monkeypatch.setattr(vwp, "ROOT", tmp_path)
    assert vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path) == run_dir


def test_v2_witness_archives_complete_four_sibling_release(
    tmp_path, monkeypatch
) -> None:
    run_dir, source_files = _v2_witness_run(tmp_path, monkeypatch)

    result = verify_run(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    release_archive = manifest["releaseArchive"]

    assert result.inventory_status == "complete"
    assert release_archive["schemaVersion"] == wul.RELEASE_ARCHIVE_SCHEMA
    assert release_archive["fileCount"] == 4
    receipt_slots = {
        path.rsplit(".", 2)[-2] for path in source_files if path.endswith(".tsr")
    }
    assert receipt_slots == {
        "freetsa",
        "digicert",
    }
    assert sum(path.endswith(".producer.sig") for path in source_files) == 1
    upstream_by_source = {
        record["sourcePath"]: record
        for record in manifest["upstream"]
        if record["role"] == "ledger_release_file"
    }
    assert set(upstream_by_source) == set(source_files)
    for source_path, expected in source_files.items():
        record = upstream_by_source[source_path]
        compressed = (tmp_path / record["archive"]["path"]).read_bytes()
        assert gzip.decompress(compressed) == expected
        assert record["archive"]["sha256"] == hashlib.sha256(expected).hexdigest()
        assert record["gitBlobSha"] == _git_blob_sha(expected)


def test_v2_witness_archives_and_inventory_binds_producer_signature(
    tmp_path, monkeypatch
) -> None:
    run_dir, source_files = _v2_witness_run(
        tmp_path,
        monkeypatch,
        with_producer_signatures=True,
    )

    result = verify_run(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    signature_path, expected = next(
        (path, raw)
        for path, raw in source_files.items()
        if path.endswith(".producer.sig")
    )
    file_record = next(
        item
        for item in manifest["releaseArchive"]["files"]
        if item["path"] == signature_path
    )
    upstream_record = next(
        item
        for item in manifest["upstream"]
        if item.get("sourcePath") == signature_path
    )
    archive_path = tmp_path / upstream_record["archive"]["path"]

    assert result.inventory_status == "complete"
    assert gzip.decompress(archive_path.read_bytes()) == expected
    assert file_record["sha256"] == hashlib.sha256(expected).hexdigest()
    assert file_record["gitBlobSha"] == _git_blob_sha(expected)
    assert upstream_record["name"] == file_record["archiveName"]
    assert upstream_record["role"] == "ledger_release_file"

    replacement = hashlib.sha512(b"replacement producer signature").digest()
    replacement_compressed = gzip.compress(replacement, mtime=0)
    replacement_blob_sha = _git_blob_sha(replacement)
    archive_path.write_bytes(replacement_compressed)
    upstream_record["archive"].update(
        {
            "sha256": hashlib.sha256(replacement).hexdigest(),
            "bytes": len(replacement),
            "gzipSha256": hashlib.sha256(replacement_compressed).hexdigest(),
            "gzipBytes": len(replacement_compressed),
        }
    )
    upstream_record["gitBlobSha"] = replacement_blob_sha
    file_record.update(
        {
            "gitBlobSha": replacement_blob_sha,
            "sha256": hashlib.sha256(replacement).hexdigest(),
            "bytes": len(replacement),
        }
    )
    _remove_seal_fields(manifest)

    with pytest.raises(CustodyError, match="Git blob SHA mismatch"):
        wul._seal(run_dir, manifest)


def test_witnessed_pin_validator_binds_full_release_head(tmp_path, monkeypatch) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    assert vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path) == run_dir
    assert "catalog" not in json.loads((run_dir / "manifest.json").read_text())
    assert "catalogSha256" not in json.loads(pin_path.read_text())

    pin = json.loads(pin_path.read_text())
    pin["releaseHead"]["manifestSha256"] = "0" * 64
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    with pytest.raises(vwp.WitnessedPinError, match="releaseHead"):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


def test_witnessed_pin_validator_refuses_unsigned_postgenesis_archive(
    tmp_path, monkeypatch
) -> None:
    run_dir, _source_files = _v2_witness_run(
        tmp_path,
        monkeypatch,
        with_producer_signatures=False,
    )
    pin_path = _pin_for_witness(tmp_path, run_dir)
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match="producer signatures"):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


def test_witnessed_pin_validator_refuses_tampered_producer_signature(
    tmp_path, monkeypatch
) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    signature = next(
        item
        for item in manifest["upstream"]
        if str(item.get("sourcePath", "")).endswith(".producer.sig")
    )
    (tmp_path / signature["archive"]["path"]).write_bytes(
        gzip.compress(b"tampered producer signature", mtime=0)
    )
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match="custody verification failed"):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("freetsaGenTimeUtc", None),
        ("digicertGenTimeUtc", "1900-01-01T00:00:00Z"),
    ],
)
def test_witnessed_pin_validator_binds_both_receipt_times(
    tmp_path, monkeypatch, field: str, value: str | None
) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    pin = json.loads(pin_path.read_text())
    if value is None:
        pin["releaseHead"].pop(field)
    else:
        pin["releaseHead"][field] = value
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match="releaseHead"):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


def test_witnessed_pin_validator_rejects_stale_nonterminal_release_head(
    tmp_path, monkeypatch
) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch, release_count=2)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    genesis = next(
        item
        for item in manifest["releaseArchive"]["files"]
        if str(item["path"]).endswith(".json")
        and pathlib.PurePosixPath(item["path"]).name.startswith("0000-")
    )
    stem = pathlib.PurePosixPath(genesis["path"]).stem
    times = _receipt_times_for_stem(tmp_path, manifest, stem)
    pin = json.loads(pin_path.read_text())
    pin["releaseHead"] = {
        "index": 0,
        "manifestSha256": genesis["sha256"],
        "freetsaGenTimeUtc": times["freetsa"],
        "digicertGenTimeUtc": times["digicert"],
    }
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match="releaseHead.index"):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


@pytest.mark.parametrize(
    ("field", "value", "diagnostic"),
    [
        ("sha", "a" * 40, "ledgerBranchSha"),
        ("jsonlSha256", "0" * 64, "jsonl.sha256"),
        ("jsonlBytes", 999, "jsonl.bytes"),
        ("lineCount", 999, "jsonl.lineCount"),
    ],
)
def test_witnessed_pin_validator_refuses_pin_mismatch(
    tmp_path, monkeypatch, field: str, value, diagnostic: str
) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    pin = json.loads(pin_path.read_text())
    pin[field] = value
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match=diagnostic):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


@pytest.mark.parametrize(
    ("field", "value", "diagnostic"),
    [
        ("catalogSha256", "0" * 64, "catalog.sha256"),
        ("catalogBytes", 999, "catalog.bytes"),
    ],
)
def test_witnessed_pin_validator_refuses_catalog_pin_mismatch(
    tmp_path, monkeypatch, field: str, value, diagnostic: str
) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch, with_catalog=True)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    pin = json.loads(pin_path.read_text())
    pin[field] = value
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match=diagnostic):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


def test_witnessed_pin_validator_requires_catalog_fields_together(
    tmp_path, monkeypatch
) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch, with_catalog=True)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    pin = json.loads(pin_path.read_text())
    pin.pop("catalogBytes")
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match="together"):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


def test_catalog_bearing_pin_requires_catalog_witness(tmp_path, monkeypatch) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    pin = json.loads(pin_path.read_text())
    pin.update({"catalogSha256": "0" * 64, "catalogBytes": 0})
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match="catalog"):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        ("missing_pinned_at", "keys are not closed-world"),
        ("unknown_field", "keys are not closed-world"),
        ("impossible_pinned_at", "not a real UTC time"),
    ],
)
def test_witnessed_pin_validator_enforces_closed_pin_schema(
    tmp_path, monkeypatch, mutation: str, diagnostic: str
) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    pin = json.loads(pin_path.read_text())
    if mutation == "missing_pinned_at":
        pin.pop("pinnedAtUtc")
    elif mutation == "unknown_field":
        pin["attackerField"] = True
    else:
        pin["pinnedAtUtc"] = "2030-02-31T00:00:00Z"
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match=diagnostic):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


def test_v2_witness_accepts_commit_tree_with_no_releases(tmp_path, monkeypatch) -> None:
    run_dir, source_files = _v2_witness_run(tmp_path, monkeypatch, with_chain=False)

    result = verify_run(run_dir)
    release_archive = json.loads((run_dir / "manifest.json").read_text())[
        "releaseArchive"
    ]

    assert result.inventory_status == "complete"
    assert source_files == {}
    assert release_archive["releasesTreeSha"] is None
    assert release_archive["manifestsTreeSha"] is None
    assert release_archive["treeArchiveNames"] == {
        "commit": "ledger-commit-tree.json",
        "releases": None,
        "manifests": None,
    }
    assert release_archive["files"] == []

    pin_path = tmp_path / "pregenesis-pin.json"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    pin_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_ledger_pin_v1",
                "repo": wul.LEDGER_REPO,
                "branch": wul.LEDGER_BRANCH,
                "sha": manifest["ledgerBranchSha"],
                "jsonlSha256": manifest["jsonl"]["sha256"],
                "jsonlBytes": manifest["jsonl"]["bytes"],
                "lineCount": manifest["jsonl"]["lineCount"],
                "pinnedAtUtc": "2030-01-01T00:00:00Z",
                "releaseHead": None,
            },
            indent=2,
        )
        + "\n"
    )
    monkeypatch.setattr(vwp, "ROOT", tmp_path)
    assert vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path) == run_dir


def test_pregenesis_pin_refuses_any_archived_release_artifact(
    tmp_path, monkeypatch
) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch)
    pin_path = _pin_for_witness(tmp_path, run_dir)
    pin = json.loads(pin_path.read_text())
    pin["releaseHead"] = None
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    monkeypatch.setattr(vwp, "ROOT", tmp_path)

    with pytest.raises(vwp.WitnessedPinError, match="releaseHead"):
        vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path)


def test_v2_witness_accepts_pre_rename_ledger_repo_alias(tmp_path, monkeypatch) -> None:
    # Records witnessed before the 2026-08-07 PolicyEngine/ledger ->
    # PolicyEngine/chronicle rename store URLs under the old slug; the
    # same repository stands behind both names, so they must keep
    # verifying forever.
    def mutate(manifest: dict) -> None:
        manifest["ledgerRepo"] = "PolicyEngine/ledger"
        for record in manifest["upstream"]:
            if isinstance(record.get("url"), str):
                record["url"] = record["url"].replace(
                    "PolicyEngine/chronicle", "PolicyEngine/ledger"
                )

    run_dir, _source_files = _v2_witness_run(
        tmp_path, monkeypatch, mutate_manifest=mutate
    )
    result = verify_run(run_dir)
    assert result.inventory_status == "complete"


def test_witnessed_pin_replays_across_the_rename(tmp_path, monkeypatch) -> None:
    # A witness sealed before the 2026-08-07 rename records
    # PolicyEngine/ledger; the CURRENT canonical pin names
    # PolicyEngine/chronicle. The replay must unify the two slugs while
    # every other identity field stays a literal comparison.
    def mutate(manifest: dict) -> None:
        manifest["ledgerRepo"] = "PolicyEngine/ledger"
        for record in manifest["upstream"]:
            if isinstance(record.get("url"), str):
                record["url"] = record["url"].replace(
                    "PolicyEngine/chronicle", "PolicyEngine/ledger"
                )

    run_dir, _source_files = _v2_witness_run(
        tmp_path, monkeypatch, mutate_manifest=mutate
    )
    pin_path = _pin_for_witness(tmp_path, run_dir)
    pin = json.loads(pin_path.read_text())
    assert pin["repo"] == "PolicyEngine/chronicle"
    monkeypatch.setattr(vwp, "ROOT", tmp_path)
    assert vwp.verify_witnessed_pin(run_dir / "manifest.json", pin_path) == run_dir


def test_witnessed_pin_refuses_foreign_repo_manifest(tmp_path, monkeypatch) -> None:
    def mutate(manifest: dict) -> None:
        manifest["ledgerRepo"] = "attacker/chronicle"

    with pytest.raises(CustodyError):
        _v2_witness_run(tmp_path, monkeypatch, mutate_manifest=mutate)


def test_v2_witness_rejects_resealed_wrong_jsonl_byte_count(
    tmp_path, monkeypatch
) -> None:
    def mutate(manifest: dict) -> None:
        manifest["jsonl"]["bytes"] += 1

    with pytest.raises(CustodyError, match="jsonl byte count mismatch"):
        _v2_witness_run(tmp_path, monkeypatch, mutate_manifest=mutate)


def test_v2_witness_rejects_resealed_wrong_catalog_byte_count(
    tmp_path, monkeypatch
) -> None:
    def mutate(manifest: dict) -> None:
        manifest["catalog"]["bytes"] += 1

    with pytest.raises(CustodyError, match="catalog byte count mismatch"):
        _v2_witness_run(
            tmp_path,
            monkeypatch,
            with_catalog=True,
            mutate_manifest=mutate,
        )


def test_v2_witness_requires_catalog_archive_for_catalog_commitment(
    tmp_path, monkeypatch
) -> None:
    with pytest.raises(CustodyError, match="does not witness series_catalog"):
        _v2_witness_run(
            tmp_path,
            monkeypatch,
            with_catalog=True,
            skip_archive_names={"series-catalog.json"},
        )


def test_v2_witness_refuses_catalog_archive_without_commitment(
    tmp_path, monkeypatch
) -> None:
    def mutate(manifest: dict) -> None:
        manifest.pop("catalog")

    with pytest.raises(CustodyError, match="lacks a manifest commitment"):
        _v2_witness_run(
            tmp_path,
            monkeypatch,
            with_catalog=True,
            mutate_manifest=mutate,
        )


def test_v2_witness_requires_exact_catalog_url(tmp_path, monkeypatch) -> None:
    def mutate(manifest: dict) -> None:
        record = next(
            item
            for item in manifest["upstream"]
            if item["role"] == "series_catalog_json"
        )
        record["url"] = (
            "https://attacker.invalid/"
            + str(manifest["ledgerBranchSha"])
            + "/series_catalog.json"
        )

    with pytest.raises(CustodyError, match="catalog URL is not the exact"):
        _v2_witness_run(
            tmp_path,
            monkeypatch,
            with_catalog=True,
            mutate_manifest=mutate,
        )


def test_resolution_workflow_revalidates_custody_and_marks_deployed_commit() -> None:
    workflow = (ROOT / ".github/workflows/resolve-and-rebuild.yml").read_text()
    signing_key_env = (
        "          LEDGER_PRODUCER_SIGNING_KEY: "
        "${{ secrets.LEDGER_PRODUCER_SIGNING_KEY }}\n"
    )
    resolve_step = workflow.split(
        "      - name: Resolve pending cells against official prints\n", 1
    )[1].split("\n      - name:", 1)[0]

    assert workflow.count("scripts/verify_witnessed_pin.py") == 2
    assert 'git show "${SITE_SHA}:site/src/data/ledger-pin.json"' in workflow
    assert "scripts/pin_ledger.py --require-catalog" in workflow
    assert '--expect-catalog-sha256 "$PIN_CATALOG_SHA256"' in workflow
    assert '--expect-catalog-bytes "$PIN_CATALOG_BYTES"' in workflow
    assert workflow.count(signing_key_env) == 1
    assert signing_key_env in resolve_step


def test_v2_witness_detects_tampered_der_receipt(tmp_path, monkeypatch) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    receipt = next(
        record
        for record in manifest["upstream"]
        if str(record.get("sourcePath", "")).endswith(".freetsa.tsr")
    )
    path = tmp_path / receipt["archive"]["path"]
    path.write_bytes(gzip.compress(b"tampered DER", mtime=0))

    with pytest.raises(CustodyError, match="mismatch"):
        verify_run(run_dir)


def test_v2_witness_refuses_resealed_receipt_replacement(tmp_path, monkeypatch) -> None:
    run_dir, _source_files = _v2_witness_run(tmp_path, monkeypatch)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    receipt = next(
        record
        for record in manifest["upstream"]
        if str(record.get("sourcePath", "")).endswith(".freetsa.tsr")
    )
    replacement = b"different but internally resealed DER bytes"
    compressed = gzip.compress(replacement, mtime=0)
    path = tmp_path / receipt["archive"]["path"]
    path.write_bytes(compressed)
    receipt["archive"].update(
        {
            "sha256": hashlib.sha256(replacement).hexdigest(),
            "bytes": len(replacement),
            "gzipSha256": hashlib.sha256(compressed).hexdigest(),
            "gzipBytes": len(compressed),
        }
    )
    file_record = next(
        entry
        for entry in manifest["releaseArchive"]["files"]
        if entry["archiveName"] == receipt["name"]
    )
    file_record["sha256"] = hashlib.sha256(replacement).hexdigest()
    file_record["bytes"] = len(replacement)
    _remove_seal_fields(manifest)

    with pytest.raises(CustodyError, match="release file bytes mismatch"):
        wul._seal(run_dir, manifest)


@pytest.mark.parametrize(
    ("field", "value", "diagnostic"),
    [
        ("ledgerRepo", "attacker/ledger", "repo must be one of"),
        ("ledgerRepo", "PolicyEngine/Chronicle", "repo must be one of"),
        ("ledgerBranch", "attacker/branch", "branch must be exactly"),
        ("ledgerBranchSha", "not-a-git-sha", "branch SHA"),
        ("ledgerMainSha", "not-a-git-sha", "main SHA"),
    ],
)
def test_v2_witness_refuses_invalid_ledger_identity(
    tmp_path, monkeypatch, field: str, value: str, diagnostic: str
) -> None:
    def mutate(manifest: dict) -> None:
        manifest[field] = value

    with pytest.raises(CustodyError, match=diagnostic):
        _v2_witness_run(tmp_path, monkeypatch, mutate_manifest=mutate)


def test_v2_witness_requires_exact_observation_url(tmp_path, monkeypatch) -> None:
    def mutate(manifest: dict) -> None:
        record = next(
            item
            for item in manifest["upstream"]
            if item["role"] == "official_observations_jsonl"
        )
        record["url"] = (
            "https://attacker.invalid/"
            + str(manifest["ledgerBranchSha"])
            + "/official_observations.jsonl"
        )

    with pytest.raises(CustodyError, match="exact immutable URL"):
        _v2_witness_run(tmp_path, monkeypatch, mutate_manifest=mutate)


@pytest.mark.parametrize(
    "role",
    [
        "ledger_branch_commit_api",
        "ledger_main_commit_api",
        "ledger_commit_tree_api",
        "ledger_releases_tree_api",
        "ledger_release_manifests_tree_api",
    ],
)
def test_v2_witness_requires_exact_commit_and_tree_urls(
    tmp_path, monkeypatch, role: str
) -> None:
    def mutate(manifest: dict) -> None:
        record = next(item for item in manifest["upstream"] if item["role"] == role)
        record["url"] = "https://attacker.invalid/not-the-immutable-object"

    with pytest.raises(CustodyError, match="exact immutable|exact immutable Git-tree"):
        _v2_witness_run(tmp_path, monkeypatch, mutate_manifest=mutate)


@pytest.mark.parametrize(
    "rewrite",
    [
        lambda path: path.replace("releases/manifests/", "releases//manifests/"),
        lambda path: path.replace("releases/manifests/", "releases/manifests/../"),
        lambda path: path + "/",
        lambda path: path.replace("/", "\\", 1),
    ],
)
def test_v2_witness_refuses_noncanonical_release_paths(
    tmp_path, monkeypatch, rewrite
) -> None:
    def mutate(manifest: dict) -> None:
        file_record = manifest["releaseArchive"]["files"][0]
        original = file_record["path"]
        changed = rewrite(original)
        file_record["path"] = changed
        archive_name = file_record["archiveName"]
        upstream = next(
            item for item in manifest["upstream"] if item["name"] == archive_name
        )
        upstream["sourcePath"] = changed

    with pytest.raises(CustodyError, match="canonical direct manifest child"):
        _v2_witness_run(tmp_path, monkeypatch, mutate_manifest=mutate)


def test_v2_witness_refuses_missing_release_archive(tmp_path, monkeypatch) -> None:
    with pytest.raises(CustodyError, match="archive .* is missing"):
        _v2_witness_run(
            tmp_path,
            monkeypatch,
            skip_source_suffix=".freetsa.tsr",
        )


def test_v2_witness_refuses_file_omitted_from_inventory(tmp_path, monkeypatch) -> None:
    def omit_receipt(manifest: dict) -> None:
        files = manifest["releaseArchive"]["files"]
        manifest["releaseArchive"]["files"] = files[:-1]
        manifest["releaseArchive"]["fileCount"] = len(files) - 1

    with pytest.raises(CustodyError, match="does not equal the manifests Git tree"):
        _v2_witness_run(tmp_path, monkeypatch, mutate_manifest=omit_receipt)


def test_v2_witness_refuses_omitted_release_inventory(tmp_path, monkeypatch) -> None:
    def omit_inventory(manifest: dict) -> None:
        manifest.pop("releaseArchive")

    with pytest.raises(CustodyError, match="lacks releaseArchive"):
        _v2_witness_run(tmp_path, monkeypatch, mutate_manifest=omit_inventory)


@pytest.mark.parametrize("expectation", ["sha256", "bytes"])
def test_main_refuses_catalog_expectation_mismatch_before_creating_run(
    tmp_path, monkeypatch, expectation: str
) -> None:
    retrieved_at = "2030-01-01T00:00:00Z"
    branch_sha = "b" * 40
    main_sha = "c" * 40
    jsonl_raw = _jsonl_bytes([{"source_record_id": "series.a.2030", "value": 1}])
    catalog_raw = _catalog_bytes(jsonl_raw)
    catalog_url = (
        f"https://raw.githubusercontent.com/{wul.LEDGER_REPO}/{branch_sha}/"
        f"{wul.LEDGER_CATALOG_PATH}"
    )
    branch_commit_raw = json.dumps({"sha": branch_sha}).encode()

    monkeypatch.setattr(wul, "ROOT", tmp_path)
    monkeypatch.setattr(wul, "utc_now", lambda: retrieved_at)
    monkeypatch.setattr(
        wul,
        "_commit_api",
        lambda ref: (
            (branch_sha, branch_commit_raw)
            if ref == wul.LEDGER_BRANCH
            else (main_sha, json.dumps({"sha": main_sha}).encode())
        ),
    )
    monkeypatch.setattr(wul, "_fetch", lambda _url: jsonl_raw)
    monkeypatch.setattr(wul, "_catalog_at", lambda _sha: (catalog_raw, catalog_url))
    expected_args = (
        ["--expect-catalog-sha256", "0" * 64]
        if expectation == "sha256"
        else ["--expect-catalog-bytes", str(len(catalog_raw) + 1)]
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["witness_upstream_ledger.py", *expected_args],
    )

    with pytest.raises(SystemExit, match="catalog .* expected"):
        wul.main()

    run_dir = (
        tmp_path / "records" / "2030-01-01" / "2030-01-01t00-00-00z-ledger-witness"
    )
    assert not run_dir.exists()


def test_main_require_catalog_refuses_absent_catalog_before_creating_run(
    tmp_path, monkeypatch
) -> None:
    retrieved_at = "2030-01-01T00:00:00Z"
    branch_sha = "b" * 40
    main_sha = "c" * 40
    jsonl_raw = _jsonl_bytes([{"source_record_id": "series.a.2030", "value": 1}])

    monkeypatch.setattr(wul, "ROOT", tmp_path)
    monkeypatch.setattr(wul, "utc_now", lambda: retrieved_at)
    monkeypatch.setattr(
        wul,
        "_commit_api",
        lambda ref: (
            (branch_sha, json.dumps({"sha": branch_sha}).encode())
            if ref == wul.LEDGER_BRANCH
            else (main_sha, json.dumps({"sha": main_sha}).encode())
        ),
    )
    monkeypatch.setattr(wul, "_fetch", lambda _url: jsonl_raw)
    monkeypatch.setattr(wul, "_catalog_at", lambda _sha: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["witness_upstream_ledger.py", "--require-catalog"],
    )

    with pytest.raises(SystemExit, match="required .*series_catalog.* absent"):
        wul.main()

    run_dir = (
        tmp_path / "records" / "2030-01-01" / "2030-01-01t00-00-00z-ledger-witness"
    )
    assert not run_dir.exists()


def test_main_fetch_failure_precedes_run_directory_creation(
    tmp_path, monkeypatch
) -> None:
    retrieved_at = "2030-01-01T00:00:00Z"
    branch_sha = "b" * 40
    branch_commit_raw = json.dumps(
        {
            "sha": branch_sha,
            "commit": {"tree": {"sha": "d" * 40}},
        }
    ).encode()
    main_sha = "c" * 40
    jsonl_raw = _jsonl_bytes([{"source_record_id": "series.a.2030", "value": 1}])

    monkeypatch.setattr(wul, "ROOT", tmp_path)
    monkeypatch.setattr(wul, "utc_now", lambda: retrieved_at)
    monkeypatch.setattr(
        wul,
        "_commit_api",
        lambda ref: (
            (branch_sha, branch_commit_raw)
            if ref == wul.LEDGER_BRANCH
            else (main_sha, json.dumps({"sha": main_sha}).encode())
        ),
    )
    monkeypatch.setattr(wul, "_fetch", lambda _url: jsonl_raw)
    monkeypatch.setattr(wul, "_catalog_at", lambda _sha: None)
    monkeypatch.setattr(
        wul,
        "_release_archive_inputs",
        lambda *_args: (_ for _ in ()).throw(ValueError("tree fetch failed")),
    )
    monkeypatch.setattr(sys, "argv", ["witness_upstream_ledger.py"])

    with pytest.raises(ValueError, match="tree fetch failed"):
        wul.main()

    run_dir = (
        tmp_path / "records" / "2030-01-01" / "2030-01-01t00-00-00z-ledger-witness"
    )
    assert not run_dir.exists()


def test_main_removes_run_directory_if_sealing_fails(tmp_path, monkeypatch) -> None:
    retrieved_at = "2030-01-01T00:00:00Z"
    branch_sha = "b" * 40
    main_sha = "c" * 40
    branch_commit_raw = json.dumps({"sha": branch_sha}).encode()
    jsonl_raw = _jsonl_bytes([{"source_record_id": "series.a.2030", "value": 1}])
    release_archive = {
        "schemaVersion": wul.RELEASE_ARCHIVE_SCHEMA,
        "directory": wul.LEDGER_RELEASE_DIRECTORY,
        "commitTreeSha": "d" * 40,
        "releasesTreeSha": None,
        "manifestsTreeSha": None,
        "treeArchiveNames": {
            "commit": "ledger-commit-tree.json",
            "releases": None,
            "manifests": None,
        },
        "fileCount": 0,
        "files": [],
    }

    monkeypatch.setattr(wul, "ROOT", tmp_path)
    monkeypatch.setattr(wul, "utc_now", lambda: retrieved_at)
    monkeypatch.setattr(
        wul,
        "_commit_api",
        lambda ref: (
            (branch_sha, branch_commit_raw)
            if ref == wul.LEDGER_BRANCH
            else (main_sha, json.dumps({"sha": main_sha}).encode())
        ),
    )
    monkeypatch.setattr(wul, "_fetch", lambda _url: jsonl_raw)
    monkeypatch.setattr(wul, "_catalog_at", lambda _sha: None)
    monkeypatch.setattr(
        wul,
        "_release_archive_inputs",
        lambda *_args: (release_archive, []),
    )
    monkeypatch.setattr(
        wul, "_seal", lambda *_args: (_ for _ in ()).throw(ValueError("seal failed"))
    )
    monkeypatch.setattr(sys, "argv", ["witness_upstream_ledger.py"])

    with pytest.raises(ValueError, match="seal failed"):
        wul.main()

    run_dir = (
        tmp_path / "records" / "2030-01-01" / "2030-01-01t00-00-00z-ledger-witness"
    )
    assert not run_dir.exists()


def test_witness_run_detects_tampered_archive(tmp_path, monkeypatch) -> None:
    run_dir = _witness_run(tmp_path, monkeypatch)
    archive = run_dir / "upstream" / "official-observations.jsonl.gz"
    tampered = _jsonl_bytes(
        [
            {"source_record_id": "series.a.2030", "value": 999},
            {"source_record_id": "series.b.2030", "value": 2},
        ]
    )
    archive.write_bytes(gzip.compress(tampered, mtime=0))

    with pytest.raises(CustodyError):
        verify_run(run_dir)


def test_witness_run_requires_the_observations_archive(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(wul, "ROOT", tmp_path)
    run_dir = tmp_path / "records" / "2030-01-01" / "run-ledger-witness"
    run_dir.mkdir(parents=True)
    jsonl_raw = _jsonl_bytes([{"source_record_id": "series.a.2030", "value": 1}])
    upstream = [
        wul._archive(
            run_dir,
            "ledger-branch-commit.json",
            json.dumps({"sha": "b" * 40}).encode(),
            role="ledger_branch_commit_api",
            url="https://example.test/commit",
        )
    ]
    manifest = {
        "schemaVersion": "thesis_ledger_witness_run_v1",
        "retrievedAt": "2030-01-01T00:00:00Z",
        "ledgerRepo": "PolicyEngine/chronicle",
        "ledgerBranch": "codex/thesis-ledger-facts",
        "ledgerBranchSha": "b" * 40,
        "ledgerMainSha": "c" * 40,
        "jsonl": wul._validate_jsonl(jsonl_raw),
        "upstream": upstream,
    }

    with pytest.raises(CustodyError):
        wul._seal(run_dir, manifest)


def test_witness_run_detects_wrong_line_count_commitment(tmp_path, monkeypatch) -> None:
    run_dir = _witness_run(tmp_path, monkeypatch)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["jsonl"]["lineCount"] = 3

    # Rewriting the commitment invalidates the sealed manifest hashes first;
    # both failures are CustodyError and both fail closed.
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(CustodyError):
        verify_run(run_dir)


def test_witness_rejects_a_commit_archive_unrelated_to_the_manifest_sha(
    tmp_path, monkeypatch
) -> None:
    # Finding 11: the archived branch-commit response must actually identify
    # the SHA the manifest claims, not merely be byte-consistent.
    monkeypatch.setattr(wul, "ROOT", tmp_path)
    run_dir = tmp_path / "records" / "2030-01-01" / "run-ledger-witness"
    run_dir.mkdir(parents=True)
    jsonl_raw = _jsonl_bytes([{"source_record_id": "series.a.2030", "value": 1}])
    branch_url = (
        "https://raw.githubusercontent.com/PolicyEngine/chronicle/"
        + ("b" * 40)
        + "/ledger/official_observations.jsonl"
    )
    upstream = [
        wul._archive(
            run_dir,
            "official-observations.jsonl",
            jsonl_raw,
            role="official_observations_jsonl",
            url=branch_url,
        ),
        wul._archive(
            run_dir,
            "ledger-branch-commit.json",
            # The archived response identifies a DIFFERENT sha than claimed.
            json.dumps({"sha": "d" * 40}).encode(),
            role="ledger_branch_commit_api",
            url="https://example.test/commit",
        ),
        wul._archive(
            run_dir,
            "ledger-main-commit.json",
            json.dumps({"sha": "c" * 40}).encode(),
            role="ledger_main_commit_api",
            url="https://example.test/main-commit",
        ),
    ]
    manifest = {
        "schemaVersion": "thesis_ledger_witness_run_v1",
        "retrievedAt": "2030-01-01T00:00:00Z",
        "ledgerRepo": "PolicyEngine/chronicle",
        "ledgerBranch": "codex/thesis-ledger-facts",
        "ledgerBranchSha": "b" * 40,
        "ledgerMainSha": "c" * 40,
        "jsonl": wul._validate_jsonl(jsonl_raw),
        "upstream": upstream,
    }

    with pytest.raises(CustodyError, match="not the manifest's claimed SHA"):
        wul._seal(run_dir, manifest)
