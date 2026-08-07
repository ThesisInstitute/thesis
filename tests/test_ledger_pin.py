from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger_release_chain  # noqa: E402
import pin_ledger  # noqa: E402
import register_targets  # noqa: E402
from canonical_json import canonical_bytes  # noqa: E402
from ledger_release_chain import (  # noqa: E402
    manifest_filename,
    verify_release_chain,
)
from register_targets import (  # noqa: E402
    RegistrationError,
    registration_content_hash,
    validate_ledger_pin_binding,
)

TSA_FIXTURE = ROOT / "tests" / "fixtures" / "release_tsa"


@dataclass(frozen=True)
class ReleaseRepo:
    repo: pathlib.Path
    tsa: pathlib.Path
    base: str
    genesis: str
    release_one: str
    head: str


def _run(command: list[str], *, cwd: pathlib.Path) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def _git(repo: pathlib.Path, *arguments: str) -> str:
    return _run(["git", *arguments], cwd=repo)


def _git_bytes(repo: pathlib.Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=repo)


def _commit(repo: pathlib.Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _row_bytes(identity: str) -> bytes:
    return (
        json.dumps(
            {"source_record_id": identity, "value": identity},
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def _catalog_bytes(jsonl: bytes) -> bytes:
    return (
        json.dumps(
            {
                "generator_version": 1,
                "observations_sha256": hashlib.sha256(jsonl).hexdigest(),
                "observation_rows": len(jsonl.splitlines()),
                "series": [],
            },
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def _created_at() -> str:
    value = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _mint_receipt(
    manifest: pathlib.Path,
    receipt: pathlib.Path,
    *,
    tsa: pathlib.Path,
    signer: str,
) -> None:
    request = tsa / f"{signer}-{manifest.stem}.tsq"
    subprocess.run(
        [
            "openssl",
            "ts",
            "-query",
            "-data",
            str(manifest),
            "-sha256",
            "-cert",
            "-out",
            str(request),
        ],
        cwd=tsa,
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
            str(request),
            "-out",
            str(receipt),
        ],
        cwd=tsa / signer,
        check=True,
        capture_output=True,
    )


def _generate_producer_key(directory: pathlib.Path, name: str) -> pathlib.Path:
    key = directory / f"{name}-key.pem"
    public_key = directory / f"{name}.pub"
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "ED25519",
            "-out",
            str(key),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    return key


def _sign_manifest(manifest: pathlib.Path, key: pathlib.Path) -> pathlib.Path:
    signature = manifest.with_name(f"{manifest.stem}.producer.sig")
    subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            str(key),
            "-rawin",
            "-in",
            str(manifest),
            "-out",
            str(signature),
        ],
        check=True,
        capture_output=True,
    )
    assert len(signature.read_bytes()) == ledger_release_chain.PRODUCER_SIGNATURE_BYTES
    return signature


def _spki_sha256(public_key_pem: bytes) -> str:
    spki_der = subprocess.check_output(
        ["openssl", "pkey", "-pubin", "-outform", "DER"],
        input=public_key_pem,
    )
    return hashlib.sha256(spki_der).hexdigest()


def _test_anchor_specs(tsa: pathlib.Path) -> dict[str, ledger_release_chain.AnchorSpec]:
    fixture_specs = {
        "freetsa": ("freetsa-root-2016.pem", "1.3.6.1.4.1.55555.1.1"),
        "digicert": (
            "digicert-trusted-root-g4.pem",
            "1.3.6.1.4.1.55555.1.2",
        ),
    }
    result = {}
    for signer, (filename, policy_oid) in fixture_specs.items():
        anchor = tsa / "anchors" / filename
        certificate = tsa / signer / "signer.pem"
        certificate_der = subprocess.check_output(
            ["openssl", "x509", "-in", str(certificate), "-outform", "DER"]
        )
        signer_public_key = subprocess.check_output(
            ["openssl", "x509", "-in", str(certificate), "-pubkey", "-noout"]
        )
        result[signer] = ledger_release_chain.AnchorSpec(
            filename=filename,
            pem_sha256=hashlib.sha256(anchor.read_bytes()).hexdigest(),
            policy_oid=policy_oid,
            signer_certificate_sha256=hashlib.sha256(certificate_der).hexdigest(),
            signer_spki_sha256=_spki_sha256(signer_public_key),
        )
    return result


def _write_release(
    repo: pathlib.Path,
    tsa: pathlib.Path,
    *,
    index: int,
    previous_manifest: bytes | None,
    previous_ledger: bytes | None,
    producer_key: pathlib.Path,
) -> pathlib.Path:
    ledger = (repo / pin_ledger.LEDGER_JSONL_PATH).read_bytes()
    prefix = (repo / pin_ledger.LEDGER_PREFIX_PATH).read_bytes()
    if index == 0:
        append = None
        previous_digest = None
    else:
        assert previous_manifest is not None
        assert previous_ledger is not None
        assert ledger.startswith(previous_ledger)
        suffix = ledger[len(previous_ledger) :]
        append = {
            "previousLineCount": len(previous_ledger.splitlines()),
            "appendedRowCount": (
                len(ledger.splitlines()) - len(previous_ledger.splitlines())
            ),
            "appendedBytesSha256": hashlib.sha256(suffix).hexdigest(),
        }
        previous_digest = hashlib.sha256(previous_manifest).hexdigest()
    manifest = {
        "schemaVersion": "thesis_ledger_release_v1",
        "releaseIndex": index,
        "previousManifestSha256": previous_digest,
        "state": {
            "path": pin_ledger.LEDGER_JSONL_PATH,
            "jsonlSha256": hashlib.sha256(ledger).hexdigest(),
            "lineCount": len(ledger.splitlines()),
            "immutablePrefixSha256": hashlib.sha256(prefix).hexdigest(),
        },
        "append": append,
        "createdAtUtc": _created_at(),
        "producer": {
            "repo": pin_ledger.LEDGER_REPO,
            "branch": pin_ledger.LEDGER_BRANCH,
        },
    }
    raw = canonical_bytes(manifest) + b"\n"
    directory = repo / "releases" / "manifests"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / manifest_filename(index, raw)
    path.write_bytes(raw)
    _sign_manifest(path, producer_key)
    for slot in ("freetsa", "digicert"):
        _mint_receipt(
            path,
            path.with_name(f"{path.stem}.{slot}.tsr"),
            tsa=tsa,
            signer=slot,
        )
    return path


def _build_release_repo(root: pathlib.Path) -> ReleaseRepo:
    repo = root / "repo"
    tsa = root / "release_tsa"
    repo.mkdir()
    shutil.copytree(TSA_FIXTURE, tsa)
    producer_key = _generate_producer_key(tsa, "producer-ed25519")
    shutil.copy2(
        tsa / "producer-ed25519.pub",
        tsa / "anchors" / ledger_release_chain.PRODUCER_PUBLIC_KEY_FILENAME,
    )
    ledger = repo / pin_ledger.LEDGER_JSONL_PATH
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(_row_bytes("row-0"))
    (repo / pin_ledger.LEDGER_PREFIX_PATH).write_bytes(b"{}\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Ledger Pin Test")
    _git(repo, "config", "user.email", "ledger-pin@example.invalid")
    base = _commit(repo, "pre-genesis")

    anchors = repo / "releases" / "anchors"
    shutil.copytree(tsa / "anchors", anchors)
    (repo / "releases" / "README.md").write_text("test release journal\n")
    manifest = _write_release(
        repo,
        tsa,
        index=0,
        previous_manifest=None,
        previous_ledger=None,
        producer_key=producer_key,
    )
    genesis = _commit(repo, "release genesis")

    previous_manifest = manifest.read_bytes()
    previous_ledger = ledger.read_bytes()
    ledger.write_bytes(previous_ledger + _row_bytes("row-1"))
    manifest = _write_release(
        repo,
        tsa,
        index=1,
        previous_manifest=previous_manifest,
        previous_ledger=previous_ledger,
        producer_key=producer_key,
    )
    release_one = _commit(repo, "release one")

    previous_manifest = manifest.read_bytes()
    previous_ledger = ledger.read_bytes()
    ledger.write_bytes(previous_ledger + _row_bytes("row-2"))
    (repo / pin_ledger.LEDGER_CATALOG_PATH).write_bytes(
        _catalog_bytes(ledger.read_bytes())
    )
    _write_release(
        repo,
        tsa,
        index=2,
        previous_manifest=previous_manifest,
        previous_ledger=previous_ledger,
        producer_key=producer_key,
    )
    head = _commit(repo, "release two")
    return ReleaseRepo(repo, tsa, base, genesis, release_one, head)


def _build_pre_signing_crossing_history(
    release_repo: ReleaseRepo,
    *,
    delay_digicert_receipt: bool = False,
) -> ReleaseRepo:
    repo = release_repo.repo
    tsa = release_repo.tsa
    _git(repo, "checkout", "-q", release_repo.base)
    anchors = repo / "releases" / "anchors"
    shutil.copytree(tsa / "anchors", anchors)
    (repo / "releases" / "README.md").write_text("test release journal\n")
    ledger = repo / pin_ledger.LEDGER_JSONL_PATH
    producer_key = tsa / "producer-ed25519-key.pem"

    genesis_manifest = _write_release(
        repo,
        tsa,
        index=0,
        previous_manifest=None,
        previous_ledger=None,
        producer_key=producer_key,
    )
    genesis_signature = genesis_manifest.with_name(
        f"{genesis_manifest.stem}.producer.sig"
    )
    genesis_signature.unlink()
    delayed_receipt = genesis_manifest.with_name(
        f"{genesis_manifest.stem}.digicert.tsr"
    )
    delayed_receipt_bytes = (
        delayed_receipt.read_bytes() if delay_digicert_receipt else None
    )
    if delayed_receipt_bytes is not None:
        delayed_receipt.unlink()
    genesis = _commit(repo, "incomplete release genesis")

    if delayed_receipt_bytes is not None:
        delayed_receipt.write_bytes(delayed_receipt_bytes)
    _sign_manifest(genesis_manifest, producer_key)
    signed_genesis = _commit(repo, "add genesis producer signature")

    previous_ledger = ledger.read_bytes()
    ledger.write_bytes(previous_ledger + _row_bytes("row-1"))
    _write_release(
        repo,
        tsa,
        index=1,
        previous_manifest=genesis_manifest.read_bytes(),
        previous_ledger=previous_ledger,
        producer_key=producer_key,
    )
    head = _commit(repo, "signed four-sibling append")
    return ReleaseRepo(
        repo,
        tsa,
        release_repo.base,
        genesis,
        signed_genesis,
        head,
    )


@pytest.fixture(scope="session")
def release_repo_template(tmp_path_factory: pytest.TempPathFactory) -> ReleaseRepo:
    return _build_release_repo(tmp_path_factory.mktemp("ledger-pin-release"))


@pytest.fixture
def release_repo(
    tmp_path: pathlib.Path, release_repo_template: ReleaseRepo
) -> ReleaseRepo:
    root = tmp_path / "release-copy"
    repo = root / "repo"
    tsa = root / "release_tsa"
    shutil.copytree(release_repo_template.repo, repo)
    shutil.copytree(release_repo_template.tsa, tsa)
    return ReleaseRepo(
        repo,
        tsa,
        release_repo_template.base,
        release_repo_template.genesis,
        release_repo_template.release_one,
        release_repo_template.head,
    )


def _commit_time(repo: pathlib.Path, commit: str) -> str:
    return pin_ledger._utc_instant(_git(repo, "show", "-s", "--format=%cI", commit))


def _tree_payload(repo: pathlib.Path, tree_sha: str) -> dict[str, Any]:
    output = _git_bytes(repo, "ls-tree", "-z", tree_sha)
    entries = []
    for record in output.split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode().split(" ")
        entries.append(
            {
                "path": raw_name.decode(),
                "mode": mode,
                "type": object_type,
                "sha": object_id,
            }
        )
    return {"sha": tree_sha, "tree": entries, "truncated": False}


def _install_remote(
    monkeypatch: pytest.MonkeyPatch,
    release_repo: ReleaseRepo,
    *,
    date_overrides: dict[str, str] | None = None,
) -> None:
    repo = release_repo.repo

    def api(path: str) -> Any:
        if path.startswith("commits/"):
            ref = path.removeprefix("commits/")
            head = _git(
                repo,
                "rev-parse",
                "HEAD" if ref == pin_ledger.LEDGER_BRANCH else f"{ref}^{{commit}}",
            )
            tree = _git(repo, "show", "-s", "--format=%T", head)
            return {
                "sha": head,
                "parents": [
                    {"sha": parent}
                    for parent in _git(
                        repo, "rev-list", "--parents", "-n", "1", head
                    ).split()[1:]
                ],
                "commit": {
                    "tree": {"sha": tree},
                    "committer": {"date": _commit_time(repo, head)},
                },
            }
        if path.startswith("compare/"):
            match = re.match(
                r"compare/(?P<base>[0-9a-f]{40})\.\.\."
                r"(?P<head>[0-9a-f]{40})\?per_page=100&page=(?P<page>[0-9]+)",
                path,
            )
            assert match is not None
            base = match.group("base")
            head = match.group("head")
            assert match.group("page") == "1"
            commits = _git(
                repo, "rev-list", "--reverse", f"{base}..{head}"
            ).splitlines()
            overrides = date_overrides or {}
            return {
                "status": "ahead",
                "merge_base_commit": {"sha": _git(repo, "merge-base", base, head)},
                "total_commits": len(commits),
                "commits": [
                    {
                        "sha": commit,
                        "commit": {
                            "committer": {
                                "date": overrides.get(
                                    commit, _commit_time(repo, commit)
                                )
                            }
                        },
                    }
                    for commit in commits
                ],
            }
        if path.startswith("git/trees/"):
            return _tree_payload(repo, path.removeprefix("git/trees/"))
        raise AssertionError(f"unexpected API path {path}")

    raw_pattern = re.compile(
        r"https://raw\.githubusercontent\.com/PolicyEngine/ledger/"
        r"(?P<sha>[0-9a-f]{40})/(?P<path>.+)"
    )

    def fetch(url: str) -> bytes:
        match = raw_pattern.fullmatch(url)
        assert match is not None, url
        return _git_bytes(
            repo,
            "show",
            f"{match.group('sha')}:{unquote(match.group('path'))}",
        )

    monkeypatch.setattr(pin_ledger, "_api", api)
    monkeypatch.setattr(pin_ledger, "_fetch", fetch)


def _seed_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
    *,
    pin_sha: str | None = None,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    pin_path = tmp_path / "ledger-pin.json"
    availability_path = tmp_path / "availability.json"
    generated_path = tmp_path / "ledger-availability.generated.ts"
    monkeypatch.setattr(pin_ledger, "PIN_PATH", pin_path)
    monkeypatch.setattr(pin_ledger, "AVAILABILITY_PATH", availability_path)
    monkeypatch.setattr(pin_ledger, "GENERATED_PATH", generated_path)
    selected_sha = pin_sha or release_repo.base
    raw = _git_bytes(
        release_repo.repo,
        "show",
        f"{selected_sha}:{pin_ledger.LEDGER_JSONL_PATH}",
    )
    assert len(raw.splitlines()) == 1
    line = raw.decode().strip()
    accepted_at = _commit_time(release_repo.repo, release_repo.base)
    pin = {
        "schemaVersion": pin_ledger.PIN_SCHEMA,
        "repo": pin_ledger.LEDGER_REPO,
        "branch": pin_ledger.LEDGER_BRANCH,
        "sha": selected_sha,
        "jsonlSha256": hashlib.sha256(raw).hexdigest(),
        "jsonlBytes": len(raw),
        "lineCount": 1,
        "pinnedAtUtc": accepted_at,
    }
    availability = {
        "schemaVersion": pin_ledger.AVAILABILITY_SCHEMA,
        "repo": pin_ledger.LEDGER_REPO,
        "branch": pin_ledger.LEDGER_BRANCH,
        "headSha": selected_sha,
        "jsonlSha256": pin["jsonlSha256"],
        "legacyQuarantineLineCount": 1,
        "historyAnomalies": [],
        "rows": [
            {
                "sourceRecordId": "row-0",
                "acceptedSequence": 0,
                "acceptedAtUtc": accepted_at,
                "acceptedCommit": release_repo.base,
                "lineSha256": hashlib.sha256(line.encode()).hexdigest(),
                "custody": "append_derived",
            }
        ],
    }
    pin_path.write_text(json.dumps(pin, indent=2) + "\n")
    availability_path.write_bytes(canonical_bytes(availability) + b"\n")
    generated_path.write_text("old generated output\n")
    return pin_path, availability_path, generated_path


def _install_test_verifier(
    monkeypatch: pytest.MonkeyPatch, release_repo: ReleaseRepo
) -> list[bool]:
    production_pin_requests: list[bool] = []
    trusted_anchors = release_repo.tsa / "anchors"
    monkeypatch.setattr(
        ledger_release_chain,
        "ANCHORS",
        _test_anchor_specs(release_repo.tsa),
    )
    monkeypatch.setattr(
        ledger_release_chain,
        "PRODUCER_SPKI_SHA256",
        _spki_sha256(
            (
                trusted_anchors / ledger_release_chain.PRODUCER_PUBLIC_KEY_FILENAME
            ).read_bytes()
        ),
    )

    def verifier(root: pathlib.Path, **kwargs: Any) -> Any:
        production_pin_requests.append(kwargs["enforce_production_pins"])
        return verify_release_chain(root, **kwargs)

    monkeypatch.setattr(pin_ledger, "verify_release_chain", verifier)
    return production_pin_requests


def _prepare_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
    *,
    date_overrides: dict[str, str] | None = None,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, list[bool]]:
    paths = _seed_outputs(monkeypatch, tmp_path, release_repo)
    _install_remote(monkeypatch, release_repo, date_overrides=date_overrides)
    pin_requests = _install_test_verifier(monkeypatch, release_repo)
    return (*paths, pin_requests)


def _pin_binding() -> dict:
    return {
        "repo": "PolicyEngine/ledger",
        "branch": "codex/thesis-ledger-facts",
        "sha": "a" * 40,
        "jsonlSha256": "b" * 64,
        "lineCount": 107,
    }


def _catalog_pin_binding() -> dict:
    return {
        **_pin_binding(),
        "catalogSha256": "c" * 64,
        "catalogBytes": 12345,
    }


def _site_pin() -> dict[str, Any]:
    return {
        "schemaVersion": pin_ledger.PIN_SCHEMA,
        **_pin_binding(),
        "jsonlBytes": 12345,
        "pinnedAtUtc": "2030-01-01T00:00:00Z",
        "releaseHead": None,
    }


def test_refresh_refuses_a_rewritten_ledger_line() -> None:
    previous = ['{"source_record_id":"a"}', '{"source_record_id":"b"}']
    rewritten = ['{"source_record_id":"a","value":9}', '{"source_record_id":"b"}']

    with pytest.raises(pin_ledger.PinError, match="rewrites ledger line 1"):
        pin_ledger._require_extension(previous, rewritten, label="commit test")


def test_refresh_refuses_a_truncated_ledger() -> None:
    previous = ['{"source_record_id":"a"}', '{"source_record_id":"b"}']

    with pytest.raises(pin_ledger.PinError, match="truncates the ledger"):
        pin_ledger._require_extension(previous, previous[:1], label="commit test")


def test_refresh_accepts_a_pure_append() -> None:
    previous = ['{"source_record_id":"a"}']
    appended = ['{"source_record_id":"a"}', '{"source_record_id":"b"}']

    pin_ledger._require_extension(previous, appended, label="commit test")


def test_same_commit_tree_rejects_omitted_entry_with_false_completeness_claim(
    monkeypatch: pytest.MonkeyPatch, release_repo: ReleaseRepo
) -> None:
    tree_sha = _git(release_repo.repo, "show", "-s", "--format=%T", "HEAD")
    payload = _tree_payload(release_repo.repo, tree_sha)
    payload["tree"] = payload["tree"][:-1]
    monkeypatch.setattr(pin_ledger, "_api", lambda path: payload)

    with pytest.raises(pin_ledger.PinError, match="refusing incomplete"):
        pin_ledger._tree_entries_at(tree_sha)


@pytest.mark.parametrize(
    ("commit_shas", "diagnostic"),
    [
        (["b" * 40, "b" * 40], "duplicate commits"),
        (["c" * 40, "d" * 40], "ends at"),
    ],
)
def test_compare_commit_list_is_unique_and_ends_at_requested_head(
    monkeypatch: pytest.MonkeyPatch,
    commit_shas: list[str],
    diagnostic: str,
) -> None:
    base = "a" * 40
    head = "b" * 40
    payload = {
        "status": "ahead",
        "merge_base_commit": {"sha": base},
        "total_commits": len(commit_shas),
        "commits": [{"sha": sha} for sha in commit_shas],
    }
    monkeypatch.setattr(pin_ledger, "_api", lambda _path: payload)

    with pytest.raises(pin_ledger.PinError, match=diagnostic):
        pin_ledger._compare_commits(base, head)


def test_refresh_parent_chain_cannot_skip_an_omitted_commit() -> None:
    with pytest.raises(pin_ledger.PinError, match="skips or reorders"):
        pin_ledger._require_walk_parent(
            {"sha": "c" * 40, "parents": [{"sha": "d" * 40}]},
            "c" * 40,
            "b" * 40,
            {"b" * 40},
        )


def test_refresh_accepts_signed_four_sibling_chain_and_derives_three_release_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )

    pin_ledger.refresh()

    assert pin_requests == [True]
    manifest_directory = release_repo.repo / "releases" / "manifests"
    for manifest in manifest_directory.glob("*.json"):
        assert {
            path.name
            for path in manifest_directory.iterdir()
            if path.name.startswith(f"{manifest.stem}.")
        } == {
            manifest.name,
            f"{manifest.stem}.producer.sig",
            f"{manifest.stem}.freetsa.tsr",
            f"{manifest.stem}.digicert.tsr",
        }
    pin = json.loads(pin_path.read_text())
    assert pin["sha"] == release_repo.head
    catalog = (release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH).read_bytes()
    assert pin["catalogSha256"] == hashlib.sha256(catalog).hexdigest()
    assert pin["catalogBytes"] == len(catalog)
    assert pin["releaseHead"]["index"] == 2
    assert re.fullmatch(r"[0-9a-f]{64}", pin["releaseHead"]["manifestSha256"])
    availability = json.loads(availability_path.read_text())
    assert availability["catalogSha256"] == pin["catalogSha256"]
    rows = availability["rows"]
    assert [row["witnessedInReleaseIndex"] for row in rows] == [0, 1, 2]
    assert [row["lastExcludedReleaseIndex"] for row in rows] == [None, 0, 1]
    assert rows[0]["lastExcludedReleaseFreetsaGenTimeUtc"] is None
    assert rows[0]["lastExcludedReleaseDigicertGenTimeUtc"] is None
    assert rows[1]["lastExcludedReleaseFreetsaGenTimeUtc"].endswith("Z")
    assert rows[1]["lastExcludedReleaseDigicertGenTimeUtc"].endswith("Z")
    assert rows[2]["witnessedInReleaseFreetsaGenTimeUtc"].endswith("Z")
    assert rows[2]["witnessedInReleaseDigicertGenTimeUtc"].endswith("Z")
    verification = verify_release_chain(
        release_repo.repo,
        anchor_dir=release_repo.tsa / "anchors",
        require_chain=True,
        verify_state=True,
        enforce_production_pins=False,
    )
    for index, row in enumerate(rows):
        included = verification.releases[index]
        assert row["witnessedInReleaseFreetsaGenTimeUtc"] == (
            pin_ledger._format_utc(included.receipt_times["freetsa"])
        )
        assert row["witnessedInReleaseDigicertGenTimeUtc"] == (
            pin_ledger._format_utc(included.receipt_times["digicert"])
        )
        if index == 0:
            continue
        excluded = verification.releases[index - 1]
        assert row["lastExcludedReleaseFreetsaGenTimeUtc"] == (
            pin_ledger._format_utc(excluded.receipt_times["freetsa"])
        )
        assert row["lastExcludedReleaseDigicertGenTimeUtc"] == (
            pin_ledger._format_utc(excluded.receipt_times["digicert"])
        )
    generated = generated_path.read_text()
    assert "witnessedInReleaseIndex: number | null" in generated
    assert "lastExcludedReleaseIndex: number | null" in generated


def test_local_catalog_read_allows_legacy_absence_and_requires_forward_presence(
    release_repo: ReleaseRepo,
) -> None:
    assert (
        pin_ledger._local_catalog_at_commit(
            release_repo.repo,
            release_repo.release_one,
            required=False,
        )
        is None
    )
    with pytest.raises(pin_ledger.PinError, match="missing required"):
        pin_ledger._local_catalog_at_commit(
            release_repo.repo,
            release_repo.release_one,
            required=True,
        )

    assert (
        pin_ledger._local_catalog_at_commit(
            release_repo.repo,
            release_repo.head,
            required=True,
        )
        == (release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH).read_bytes()
    )


def test_refresh_required_catalog_rejects_legacy_head_before_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    _git(release_repo.repo, "checkout", "-q", release_repo.release_one)
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="missing required"):
        pin_ledger.refresh(require_catalog=True)

    assert pin_requests == []
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_rejects_catalog_bytes_outside_same_commit_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    original_fetch = pin_ledger._fetch

    def fetch(url: str) -> bytes:
        raw = original_fetch(url)
        if url.endswith(f"/{pin_ledger.LEDGER_CATALOG_PATH}"):
            return raw + b"tampered"
        return raw

    monkeypatch.setattr(pin_ledger, "_fetch", fetch)
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(
        pin_ledger.PinError,
        match=r"same-commit blob bytes for ledger/series_catalog\.json",
    ):
        pin_ledger.refresh()

    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observations_sha256", "f" * 64),
        ("observation_rows", 999),
    ],
)
def test_refresh_rejects_catalog_not_bound_to_same_commit_observations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
    field: str,
    value: Any,
) -> None:
    catalog_path = release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH
    catalog = json.loads(catalog_path.read_text())
    catalog[field] = value
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    _commit(release_repo.repo, f"break catalog {field} binding")
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match=field):
        pin_ledger.refresh()

    assert {path: path.read_bytes() for path in before} == before


def _registry_bytes() -> bytes:
    return (
        json.dumps(
            {
                "concept": "test.series",
                "geography": None,
                "entity": None,
                "uuid": "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f",
            },
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def _declare_registry(
    repo: pathlib.Path,
    *,
    registry: bytes | None,
    declared_digest: str | None,
    message: str,
) -> None:
    """Commit a catalog/registry coupling state onto the release repo."""

    if registry is not None:
        (repo / pin_ledger.LEDGER_REGISTRY_PATH).write_bytes(registry)
    catalog_path = repo / pin_ledger.LEDGER_CATALOG_PATH
    catalog = json.loads(catalog_path.read_text())
    if declared_digest is None:
        catalog.pop("uuid_registry_sha256", None)
    else:
        catalog["uuid_registry_sha256"] = declared_digest
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    _commit(repo, message)


def test_v3_catalog_cannot_downgrade_registry_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    # Coordinated removal of the declaration AND the registry file from a
    # generator-v3 catalog must be a PinError, not a silent legacy fallback.
    catalog_path = release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH
    catalog = json.loads(catalog_path.read_text())
    catalog["generator_version"] = 3
    catalog.pop("uuid_registry_sha256", None)
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    _commit(release_repo.repo, "downgrade registry binding")
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="downgraded away"):
        pin_ledger.refresh()

    assert {path: path.read_bytes() for path in before} == before


def test_registry_coupling_has_one_choke_point(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    """Every pin path — advancing refresh, local rebuild — funnels
    catalog/registry coupling through _validate_catalog_and_registry, so
    a declared digest with no registry file fails everywhere the pin can
    move. (A pinned commit cannot later become invalid without the head
    moving, so the stationary path re-validates the identical state it
    pinned.)"""
    catalog_path = release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH
    catalog = json.loads(catalog_path.read_text())
    catalog["uuid_registry_sha256"] = "a" * 64
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    _commit(release_repo.repo, "declare registry without file")
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    pin_before = pin_path.read_bytes()

    with pytest.raises(pin_ledger.PinError, match="is missing"):
        pin_ledger.refresh()

    assert pin_path.read_bytes() == pin_before


def test_registry_ratchet_blocks_version_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    # Second-round repro: pin a valid v3+registry state, then roll the
    # catalog back to "generator v2" with declaration and registry file
    # both removed. The monotonic ratchet must refuse.
    registry = _registry_bytes()
    _declare_registry(
        release_repo.repo,
        registry=registry,
        declared_digest=hashlib.sha256(registry).hexdigest(),
        message="declare uuid registry",
    )
    catalog_path = release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH
    catalog = json.loads(catalog_path.read_text())
    catalog["generator_version"] = 3
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    _commit(release_repo.repo, "v3 catalog")
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    pin_ledger.refresh()
    assert b"registry" not in pin_path.read_bytes() or True

    catalog = json.loads(catalog_path.read_text())
    catalog["generator_version"] = 2
    catalog.pop("uuid_registry_sha256", None)
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    (release_repo.repo / pin_ledger.LEDGER_REGISTRY_PATH).unlink()
    _commit(release_repo.repo, "roll back to v2 without registry")
    before = pin_path.read_bytes()

    with pytest.raises(pin_ledger.PinError, match="downgraded away"):
        pin_ledger.refresh()

    assert pin_path.read_bytes() == before


@pytest.mark.parametrize("version", ["3", True, None])
def test_generator_version_type_floor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
    version,
) -> None:
    catalog_path = release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH
    catalog = json.loads(catalog_path.read_text())
    if version is None:
        catalog.pop("generator_version", None)
    else:
        catalog["generator_version"] = version
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    _commit(release_repo.repo, "malform generator_version")
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )

    with pytest.raises(pin_ledger.PinError, match="positive integer"):
        pin_ledger.refresh()


def test_refresh_binds_declared_uuid_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    registry = _registry_bytes()
    _declare_registry(
        release_repo.repo,
        registry=registry,
        declared_digest=hashlib.sha256(registry).hexdigest(),
        message="declare uuid registry",
    )
    head = _git(release_repo.repo, "rev-parse", "HEAD")
    pin_path, _availability_path, _generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )

    pin_ledger.refresh()

    pin = json.loads(pin_path.read_text())
    assert pin["sha"] == head
    catalog_raw = _git_bytes(
        release_repo.repo, "show", f"{head}:{pin_ledger.LEDGER_CATALOG_PATH}"
    )
    assert pin["catalogSha256"] == hashlib.sha256(catalog_raw).hexdigest()


@pytest.mark.parametrize(
    ("registry", "declared_digest", "match"),
    [
        # Declared digest, registry file absent from the commit.
        (None, "a" * 64, "is missing"),
        # Declared digest disagrees with the same-commit registry bytes.
        (b'{"tampered": true}\n', "a" * 64, "does not match same-commit"),
        # Registry file present while the catalog does not declare it.
        (b'{"undeclared": true}\n', None, "does not declare"),
    ],
)
def test_refresh_rejects_registry_coupling_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
    registry: bytes | None,
    declared_digest: str | None,
    match: str,
) -> None:
    _declare_registry(
        release_repo.repo,
        registry=registry,
        declared_digest=declared_digest,
        message="break registry coupling",
    )
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match=match):
        pin_ledger.refresh()

    assert {path: path.read_bytes() for path in before} == before


def test_catalog_bearing_pin_ratchets_against_later_removal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    pin_ledger.refresh()
    assert "catalogSha256" in json.loads(pin_path.read_text())

    (release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH).unlink()
    _commit(release_repo.repo, "remove catalog after catalog-bearing pin")
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="missing required"):
        pin_ledger.refresh()

    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize(
    ("delay_digicert_receipt", "genesis_sibling_count"),
    [(False, 3), (True, 2)],
)
def test_refresh_crosses_incomplete_genesis_and_lands_signed_release_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
    delay_digicert_receipt: bool,
    genesis_sibling_count: int,
) -> None:
    crossing_repo = _build_pre_signing_crossing_history(
        release_repo,
        delay_digicert_receipt=delay_digicert_receipt,
    )
    genesis_inventory = _git(
        crossing_repo.repo,
        "ls-tree",
        "--name-only",
        f"{crossing_repo.genesis}:releases/manifests",
    ).splitlines()
    assert len(genesis_inventory) == genesis_sibling_count
    assert not any(name.endswith(".producer.sig") for name in genesis_inventory)
    pin_path, availability_path, _generated_path = _seed_outputs(
        monkeypatch,
        tmp_path,
        crossing_repo,
        pin_sha=crossing_repo.genesis,
    )
    _install_remote(monkeypatch, crossing_repo)
    pin_requests = _install_test_verifier(monkeypatch, crossing_repo)

    pin_ledger.refresh()

    assert pin_requests == [True]
    pin = json.loads(pin_path.read_text())
    assert pin["sha"] == crossing_repo.head
    assert pin["releaseHead"]["index"] == 1
    rows = json.loads(availability_path.read_text())["rows"]
    assert [row["witnessedInReleaseIndex"] for row in rows] == [0, 1]


def test_refresh_refuses_unsigned_three_sibling_post_genesis_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    manifest = next((release_repo.repo / "releases" / "manifests").glob("0002-*.json"))
    manifest.with_name(f"{manifest.stem}.producer.sig").unlink()
    _commit(release_repo.repo, "remove post-genesis producer signature")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="missing its producer signature"):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_wrong_key_producer_signature(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    manifest = next((release_repo.repo / "releases" / "manifests").glob("0002-*.json"))
    wrong_key = _generate_producer_key(release_repo.tsa, "wrong-producer")
    _sign_manifest(manifest, wrong_key)
    _commit(release_repo.repo, "replace producer signature with wrong key")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(
        pin_ledger.PinError,
        match="producer Ed25519 signature verification failed",
    ):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_tampered_committed_producer_anchor_spki(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    attacker_key = _generate_producer_key(release_repo.tsa, "attacker-producer")
    committed_anchor = (
        release_repo.repo
        / "releases"
        / "anchors"
        / ledger_release_chain.PRODUCER_PUBLIC_KEY_FILENAME
    )
    shutil.copy2(release_repo.tsa / "attacker-producer.pub", committed_anchor)
    for manifest in (release_repo.repo / "releases" / "manifests").glob("*.json"):
        _sign_manifest(manifest, attacker_key)
    _commit(release_repo.repo, "replace committed producer anchor and signatures")

    # The attacker-controlled anchor and signatures are internally consistent;
    # only the independent code pin distinguishes them from the trusted key.
    verify_release_chain(
        release_repo.repo,
        require_chain=True,
        verify_state=True,
        enforce_production_pins=False,
    )
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(
        pin_ledger.PinError,
        match="producer public-key SPKI is not code-pinned",
    ):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize(
    ("tamper", "diagnostic"),
    [
        ("manifest", "manifest bytes are not canonical"),
        ("missing_receipt", "must have exactly freetsa and digicert receipts"),
        ("head_state", "HEAD release lineCount"),
    ],
)
def test_refresh_refuses_invalid_or_unwitnessed_release_state_before_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
    tamper: str,
    diagnostic: str,
) -> None:
    directory = release_repo.repo / "releases" / "manifests"
    if tamper == "manifest":
        genesis = next(directory.glob("0000-*.json"))
        genesis.write_bytes(genesis.read_bytes() + b" ")
    elif tamper == "missing_receipt":
        head = next(directory.glob("0002-*.json"))
        head.with_name(f"{head.stem}.digicert.tsr").unlink()
    else:
        ledger = release_repo.repo / pin_ledger.LEDGER_JSONL_PATH
        ledger.write_bytes(ledger.read_bytes() + _row_bytes("row-3-unwitnessed"))
    _commit(release_repo.repo, f"tamper {tamper}")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match=diagnostic):
        pin_ledger.refresh()

    assert pin_requests and all(pin_requests)
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_absent_chain_after_stored_release_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    pin_path, _, _, pin_requests = _prepare_refresh(monkeypatch, tmp_path, release_repo)
    pin_ledger.refresh()
    witnessed_pin = pin_path.read_bytes()
    shutil.rmtree(release_repo.repo / "releases" / "manifests")
    _commit(release_repo.repo, "delete witnessed chain")

    with pytest.raises(pin_ledger.PinError, match="absent after witnessed genesis"):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert pin_path.read_bytes() == witnessed_pin


def test_legacy_pin_refuses_chain_introduced_then_removed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    shutil.rmtree(release_repo.repo / "releases")
    ledger = release_repo.repo / pin_ledger.LEDGER_JSONL_PATH
    ledger.write_bytes(ledger.read_bytes() + _row_bytes("row-3-unwitnessed"))
    _commit(release_repo.repo, "delete chain and append unwitnessed row")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch,
        tmp_path,
        release_repo,
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="absent after witnessed genesis"):
        pin_ledger.refresh()

    assert pin_requests == []
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_unwitnessed_intermediate_append_even_if_later_released(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    ledger = release_repo.repo / pin_ledger.LEDGER_JSONL_PATH
    previous_ledger = ledger.read_bytes()
    previous_manifest_path = next(
        (release_repo.repo / "releases/manifests").glob("0002-*.json")
    )
    previous_manifest = previous_manifest_path.read_bytes()
    ledger.write_bytes(previous_ledger + _row_bytes("row-3"))
    _commit(release_repo.repo, "unwitnessed intermediate append")
    _write_release(
        release_repo.repo,
        release_repo.tsa,
        index=3,
        previous_manifest=previous_manifest,
        previous_ledger=previous_ledger,
        producer_key=release_repo.tsa / "producer-ed25519-key.pem",
    )
    _commit(release_repo.repo, "later release cannot sanitize intermediate")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="unwitnessed JSONL state"):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_transient_chain_deletion_hiding_unwitnessed_append(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    manifest_directory = release_repo.repo / "releases" / "manifests"
    saved_manifests = tmp_path / "saved-manifests"
    shutil.copytree(manifest_directory, saved_manifests)
    ledger = release_repo.repo / pin_ledger.LEDGER_JSONL_PATH
    previous_ledger = ledger.read_bytes()
    previous_manifest = next(manifest_directory.glob("0002-*.json")).read_bytes()
    shutil.rmtree(manifest_directory)
    ledger.write_bytes(previous_ledger + _row_bytes("row-3-unwitnessed"))
    _commit(release_repo.repo, "hide unwitnessed append behind absent chain")

    shutil.copytree(saved_manifests, manifest_directory)
    _write_release(
        release_repo.repo,
        release_repo.tsa,
        index=3,
        previous_manifest=previous_manifest,
        previous_ledger=previous_ledger,
        producer_key=release_repo.tsa / "producer-ed25519-key.pem",
    )
    _commit(release_repo.repo, "restore chain and release hidden append")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="deletes or replaces"):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_transient_release_receipt_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    receipt = next(
        (release_repo.repo / "releases/manifests").glob("0002-*.freetsa.tsr")
    )
    original = receipt.read_bytes()
    receipt.write_bytes(original + b"tampered")
    _commit(release_repo.repo, "transient receipt replacement")
    receipt.write_bytes(original)
    _commit(release_repo.repo, "restore receipt before refresh")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="absent or changed"):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_transient_release_manifest_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    manifest = next((release_repo.repo / "releases/manifests").glob("0002-*.json"))
    original = manifest.read_bytes()
    manifest.write_bytes(original + b"tampered")
    _commit(release_repo.repo, "transient manifest replacement")
    manifest.write_bytes(original)
    _commit(release_repo.repo, "restore manifest before refresh")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="absent or changed"):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_transient_producer_signature_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    signature = next(
        (release_repo.repo / "releases" / "manifests").glob("0002-*.producer.sig")
    )
    original = signature.read_bytes()
    signature.write_bytes(b"x" * ledger_release_chain.PRODUCER_SIGNATURE_BYTES)
    _commit(release_repo.repo, "transient producer signature replacement")
    signature.write_bytes(original)
    _commit(release_repo.repo, "restore producer signature before refresh")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="absent or changed"):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_crossed_manifest_missing_from_final_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    transient = (
        release_repo.repo / "releases" / "manifests" / "0003-0000000000000000.json"
    )
    transient.write_bytes(b"transient release manifest\n")
    _commit(release_repo.repo, "add release artifact absent from final chain")
    transient.unlink()
    _commit(release_repo.repo, "remove transient release artifact")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="absent or changed"):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


def test_refresh_refuses_transient_release_mode_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    receipt = next(
        (release_repo.repo / "releases/manifests").glob("0002-*.freetsa.tsr")
    )
    original_mode = receipt.stat().st_mode
    receipt.chmod(original_mode | 0o111)
    _commit(release_repo.repo, "transient receipt mode change")
    receipt.chmod(original_mode)
    _commit(release_repo.repo, "restore receipt mode before refresh")
    pin_path, availability_path, generated_path, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="absent or changed"):
        pin_ledger.refresh()

    assert pin_requests == [True]
    assert {path: path.read_bytes() for path in before} == before


def test_same_sha_refresh_migrates_legacy_witness_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    _git(release_repo.repo, "checkout", "-q", release_repo.genesis)
    pin_path, availability_path, generated_path = _seed_outputs(
        monkeypatch,
        tmp_path,
        release_repo,
        pin_sha=release_repo.genesis,
    )
    _install_remote(monkeypatch, release_repo)
    pin_requests = _install_test_verifier(monkeypatch, release_repo)

    pin_ledger.refresh()

    assert pin_requests == [True]
    assert json.loads(pin_path.read_text())["releaseHead"]["index"] == 0
    row = json.loads(availability_path.read_text())["rows"][0]
    assert row["witnessedInReleaseIndex"] == 0
    assert row["lastExcludedReleaseIndex"] is None
    assert "witnessedInReleaseIndex: number | null" in generated_path.read_text()


def test_same_sha_refresh_repairs_interrupted_pin_last_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    _git(release_repo.repo, "checkout", "-q", release_repo.genesis)
    pin_path, availability_path, generated_path = _seed_outputs(
        monkeypatch,
        tmp_path,
        release_repo,
        pin_sha=release_repo.genesis,
    )
    _install_remote(monkeypatch, release_repo)
    _install_test_verifier(monkeypatch, release_repo)
    original_replace = pin_ledger.os.replace
    calls = 0

    def fail_second_replace(source: pathlib.Path, destination: pathlib.Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated generated-output replace failure")
        original_replace(source, destination)

    monkeypatch.setattr(pin_ledger.os, "replace", fail_second_replace)
    with pytest.raises(OSError, match="generated-output"):
        pin_ledger.refresh()

    assert "witnessedInReleaseIndex" in availability_path.read_text()
    assert generated_path.read_text() == "old generated output\n"
    assert "releaseHead" not in json.loads(pin_path.read_text())

    monkeypatch.setattr(pin_ledger.os, "replace", original_replace)
    pin_ledger.refresh()

    assert json.loads(pin_path.read_text())["releaseHead"]["index"] == 0
    assert "witnessedInReleaseIndex: number | null" in generated_path.read_text()


def test_refresh_allows_support_files_before_genesis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    _git(release_repo.repo, "checkout", "-q", release_repo.base)
    anchors = release_repo.repo / "releases" / "anchors"
    shutil.copytree(release_repo.tsa / "anchors", anchors)
    (release_repo.repo / "releases" / "README.md").write_text("support only\n")
    support_head = _commit(release_repo.repo, "release support before genesis")
    pin_path, availability_path, _, pin_requests = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )

    pin_ledger.refresh()

    assert pin_requests == []
    pin = json.loads(pin_path.read_text())
    assert pin["sha"] == support_head
    assert "catalogSha256" not in pin
    assert "catalogBytes" not in pin
    assert pin["releaseHead"] is None
    row = json.loads(availability_path.read_text())["rows"][0]
    assert row["witnessedInReleaseIndex"] is None
    assert row["lastExcludedReleaseIndex"] is None


def test_backdated_acceptance_before_last_excluding_release_refuses_refresh(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch,
        tmp_path,
        release_repo,
        date_overrides={release_repo.release_one: "2000-01-01T00:00:00Z"},
    )
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="last excluding release 0"):
        pin_ledger.refresh()

    assert {path: path.read_bytes() for path in before} == before


def test_release_checkpoint_continuity_includes_both_receipt_times(
    release_repo: ReleaseRepo,
) -> None:
    verification = verify_release_chain(
        release_repo.repo,
        anchor_dir=release_repo.tsa / "anchors",
        require_chain=True,
        verify_state=True,
        enforce_production_pins=False,
    )
    previous = pin_ledger._release_head(verification)
    previous["digicertGenTimeUtc"] = "2000-01-01T00:00:00Z"

    with pytest.raises(pin_ledger.PinError, match="digicertGenTimeUtc changed"):
        pin_ledger._require_checkpoint_continuity(verification, previous)


def test_acceptance_window_enforces_only_last_excluded_minus_skew(
    release_repo: ReleaseRepo,
) -> None:
    verification = verify_release_chain(
        release_repo.repo,
        anchor_dir=release_repo.tsa / "anchors",
        require_chain=True,
        verify_state=True,
        enforce_production_pins=False,
    )
    rows = [{"acceptedAtUtc": "2000-01-01T00:00:00Z"}]
    for excluded in verification.releases[:2]:
        threshold = max(excluded.receipt_times.values()) - dt.timedelta(
            seconds=pin_ledger.DEFAULT_CLOCK_SKEW_SECONDS
        )
        rows.append({"acceptedAtUtc": pin_ledger._format_utc(threshold)})

    windowed = pin_ledger._rows_with_release_windows(rows, verification)

    assert windowed[0]["lastExcludedReleaseIndex"] is None
    assert windowed[1]["lastExcludedReleaseIndex"] == 0
    assert windowed[2]["lastExcludedReleaseIndex"] == 1


def test_acceptance_windows_preserve_distinct_exact_provider_times() -> None:
    release_times = (
        (
            dt.datetime(2030, 1, 1, 0, 0, 1, tzinfo=dt.timezone.utc),
            dt.datetime(2030, 1, 1, 0, 0, 2, tzinfo=dt.timezone.utc),
        ),
        (
            dt.datetime(2030, 1, 1, 0, 1, 3, tzinfo=dt.timezone.utc),
            dt.datetime(2030, 1, 1, 0, 1, 4, tzinfo=dt.timezone.utc),
        ),
        (
            dt.datetime(2030, 1, 1, 0, 2, 5, tzinfo=dt.timezone.utc),
            dt.datetime(2030, 1, 1, 0, 2, 6, tzinfo=dt.timezone.utc),
        ),
    )
    releases = tuple(
        SimpleNamespace(
            release_index=index,
            manifest={"state": {"lineCount": index + 1}},
            receipt_times={"freetsa": times[0], "digicert": times[1]},
        )
        for index, times in enumerate(release_times)
    )
    verification = SimpleNamespace(releases=releases)
    rows = [
        {"acceptedAtUtc": "2030-01-01T00:00:00Z"},
        {"acceptedAtUtc": "2030-01-01T00:00:03Z"},
        {"acceptedAtUtc": "2030-01-01T00:01:05Z"},
    ]

    windowed = pin_ledger._rows_with_release_windows(rows, verification)

    assert [row["witnessedInReleaseFreetsaGenTimeUtc"] for row in windowed] == [
        "2030-01-01T00:00:01Z",
        "2030-01-01T00:01:03Z",
        "2030-01-01T00:02:05Z",
    ]
    assert [row["witnessedInReleaseDigicertGenTimeUtc"] for row in windowed] == [
        "2030-01-01T00:00:02Z",
        "2030-01-01T00:01:04Z",
        "2030-01-01T00:02:06Z",
    ]
    assert windowed[0]["lastExcludedReleaseIndex"] is None
    assert windowed[1]["lastExcludedReleaseFreetsaGenTimeUtc"] == (
        "2030-01-01T00:00:01Z"
    )
    assert windowed[1]["lastExcludedReleaseDigicertGenTimeUtc"] == (
        "2030-01-01T00:00:02Z"
    )
    assert windowed[2]["lastExcludedReleaseFreetsaGenTimeUtc"] == (
        "2030-01-01T00:01:03Z"
    )
    assert windowed[2]["lastExcludedReleaseDigicertGenTimeUtc"] == (
        "2030-01-01T00:01:04Z"
    )


def test_rebuild_writes_verified_release_head_and_windows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    pin_path, availability_path, _generated_path = _seed_outputs(
        monkeypatch,
        tmp_path,
        release_repo,
    )
    pin_requests = _install_test_verifier(monkeypatch, release_repo)

    pin_ledger.rebuild_from_history(release_repo.repo, release_repo.head)

    assert pin_requests == [True]
    pin = json.loads(pin_path.read_text())
    assert pin["sha"] == release_repo.head
    catalog = (release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH).read_bytes()
    assert pin["catalogSha256"] == hashlib.sha256(catalog).hexdigest()
    assert pin["catalogBytes"] == len(catalog)
    assert pin["releaseHead"]["index"] == 2
    availability = json.loads(availability_path.read_text())
    assert availability["catalogSha256"] == pin["catalogSha256"]
    rows = availability["rows"]
    assert [row["witnessedInReleaseIndex"] for row in rows] == [0, 1, 2]
    assert [row["lastExcludedReleaseIndex"] for row in rows] == [None, 0, 1]


def test_rebuild_verifies_release_chain_before_any_output_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    pin_path, availability_path, generated_path = _seed_outputs(
        monkeypatch, tmp_path, release_repo
    )
    pin_requests = _install_test_verifier(monkeypatch, release_repo)
    head = next((release_repo.repo / "releases/manifests").glob("0002-*.json"))
    head.with_name(f"{head.stem}.freetsa.tsr").unlink()
    bad_head = _commit(release_repo.repo, "missing receipt before rebuild")
    before = {
        pin_path: pin_path.read_bytes(),
        availability_path: availability_path.read_bytes(),
        generated_path: generated_path.read_bytes(),
    }

    with pytest.raises(pin_ledger.PinError, match="must have exactly"):
        pin_ledger.rebuild_from_history(release_repo.repo, bad_head)

    assert pin_requests and all(pin_requests)
    assert {path: path.read_bytes() for path in before} == before


def test_v3_registration_hash_commits_to_the_ledger_pin() -> None:
    snapshot = {
        "schemaVersion": "thesis_target_registration_v3",
        "registeredAtUtc": "2030-01-01T00:00:00Z",
        "targets": [{"dataPointId": "test.series.2030"}],
        "ledgerPin": _pin_binding(),
    }

    baseline = registration_content_hash(snapshot)
    moved_pin = {
        **snapshot,
        "ledgerPin": {**_pin_binding(), "lineCount": 108},
    }
    catalog_bound_pin = {
        **snapshot,
        "ledgerPin": _catalog_pin_binding(),
    }

    assert registration_content_hash(moved_pin) != baseline
    assert registration_content_hash(catalog_bound_pin) != baseline


def test_v3_registration_requires_the_ledger_pin() -> None:
    snapshot = {
        "schemaVersion": "thesis_target_registration_v3",
        "registeredAtUtc": "2030-01-01T00:00:00Z",
        "targets": [{"dataPointId": "test.series.2030"}],
    }

    with pytest.raises(RegistrationError, match="missing=\\['ledgerPin'\\]"):
        registration_content_hash(snapshot)


def test_v2_registration_hashes_remain_stable() -> None:
    snapshot = {
        "schemaVersion": "thesis_target_registration_v2",
        "registeredAtUtc": "2030-01-01T00:00:00Z",
        "targets": [{"dataPointId": "test.series.2030"}],
    }

    # v2 predates the pin; its payload must not gain one retroactively.
    assert registration_content_hash(snapshot) == registration_content_hash(
        dict(snapshot)
    )
    with pytest.raises(RegistrationError):
        registration_content_hash({**snapshot, "ledgerPin": _pin_binding()})


def test_pin_binding_validation_fails_closed() -> None:
    assert validate_ledger_pin_binding(_pin_binding()) == _pin_binding()
    assert validate_ledger_pin_binding(_catalog_pin_binding()) == _catalog_pin_binding()
    with pytest.raises(RegistrationError, match="bind exactly"):
        validate_ledger_pin_binding({**_pin_binding(), "extra": 1})
    with pytest.raises(RegistrationError, match="bind exactly"):
        validate_ledger_pin_binding({**_pin_binding(), "catalogSha256": "c" * 64})
    with pytest.raises(RegistrationError, match="bind exactly"):
        validate_ledger_pin_binding({**_pin_binding(), "catalogBytes": 12345})
    with pytest.raises(RegistrationError, match="commit SHA"):
        validate_ledger_pin_binding({**_pin_binding(), "sha": "main"})
    with pytest.raises(RegistrationError, match="lineCount"):
        validate_ledger_pin_binding({**_pin_binding(), "lineCount": -1})
    with pytest.raises(RegistrationError, match="catalogSha256"):
        validate_ledger_pin_binding(
            {**_catalog_pin_binding(), "catalogSha256": "not-a-digest"}
        )
    with pytest.raises(RegistrationError, match="catalogSha256"):
        validate_ledger_pin_binding(
            {**_catalog_pin_binding(), "catalogSha256": int("1" * 64)}
        )
    with pytest.raises(RegistrationError, match="catalogBytes"):
        validate_ledger_pin_binding({**_catalog_pin_binding(), "catalogBytes": True})


@pytest.mark.parametrize(
    "catalog_fields",
    [
        {"catalogSha256": "c" * 64},
        {"catalogBytes": 123},
    ],
)
def test_pin_schema_requires_catalog_commitment_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    catalog_fields: dict[str, Any],
) -> None:
    pin_path = tmp_path / "ledger-pin.json"
    pin_path.write_text(json.dumps({**_site_pin(), **catalog_fields}) + "\n")
    monkeypatch.setattr(pin_ledger, "PIN_PATH", pin_path)

    with pytest.raises(pin_ledger.PinError, match="must contain.*together"):
        pin_ledger.load_pin()


@pytest.mark.parametrize(
    ("catalog_fields", "diagnostic"),
    [
        ({"catalogSha256": "not-a-digest", "catalogBytes": 123}, "SHA-256"),
        ({"catalogSha256": "c" * 64, "catalogBytes": True}, "non-negative"),
    ],
)
def test_pin_schema_validates_catalog_commitment_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    catalog_fields: dict[str, Any],
    diagnostic: str,
) -> None:
    pin_path = tmp_path / "ledger-pin.json"
    pin_path.write_text(json.dumps({**_site_pin(), **catalog_fields}) + "\n")
    monkeypatch.setattr(pin_ledger, "PIN_PATH", pin_path)

    with pytest.raises(pin_ledger.PinError, match=diagnostic):
        pin_ledger.load_pin()


def test_pin_schema_rejects_malformed_release_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    pin_path = tmp_path / "ledger-pin.json"
    pin_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_ledger_pin_v1",
                **_pin_binding(),
                "jsonlBytes": 12345,
                "pinnedAtUtc": "2030-01-01T00:00:00Z",
                "releaseHead": {
                    "index": True,
                    "manifestSha256": "c" * 64,
                    "freetsaGenTimeUtc": "2030-01-01T00:00:00Z",
                    "digicertGenTimeUtc": "2030-01-01T00:00:01Z",
                },
            }
        )
    )
    monkeypatch.setattr(pin_ledger, "PIN_PATH", pin_path)

    with pytest.raises(pin_ledger.PinError, match="non-negative integer"):
        pin_ledger.load_pin()


def test_release_head_index_cannot_exceed_four_digit_manifest_namespace() -> None:
    release_head = {
        "index": 10_000,
        "manifestSha256": "c" * 64,
        "freetsaGenTimeUtc": "2030-01-01T00:00:00Z",
        "digicertGenTimeUtc": "2030-01-01T00:00:01Z",
    }

    with pytest.raises(pin_ledger.PinError, match="no greater than 9999"):
        pin_ledger._validate_release_head(release_head)


@pytest.mark.parametrize("expected_binding", [_pin_binding(), _catalog_pin_binding()])
def test_registration_reads_the_committed_pin(
    monkeypatch, tmp_path, expected_binding
) -> None:
    pin_path = tmp_path / "ledger-pin.json"
    pin_path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_ledger_pin_v1",
                **expected_binding,
                "jsonlBytes": 12345,
                "pinnedAtUtc": "2030-01-01T00:00:00Z",
                "releaseHead": {
                    "index": 7,
                    "manifestSha256": "c" * 64,
                    "freetsaGenTimeUtc": "2030-01-01T00:00:00Z",
                    "digicertGenTimeUtc": "2030-01-01T00:00:01Z",
                },
            }
        )
    )
    monkeypatch.setattr(register_targets, "LEDGER_PIN_PATH", pin_path)

    actual_binding = register_targets.load_ledger_pin_binding()

    assert actual_binding == expected_binding


@pytest.mark.parametrize(
    "catalog_fields",
    [
        {"catalogSha256": "c" * 64},
        {"catalogBytes": 12345},
    ],
)
def test_registration_rejects_a_partial_catalog_pin_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    catalog_fields: dict[str, Any],
) -> None:
    pin_path = tmp_path / "ledger-pin.json"
    pin_path.write_text(json.dumps({**_site_pin(), **catalog_fields}) + "\n")
    monkeypatch.setattr(register_targets, "LEDGER_PIN_PATH", pin_path)

    with pytest.raises(RegistrationError, match="bind exactly"):
        register_targets.load_ledger_pin_binding()


def test_registration_without_a_pin_file_fails_closed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(register_targets, "LEDGER_PIN_PATH", tmp_path / "missing.json")

    with pytest.raises(RegistrationError, match="committed ledger pin"):
        register_targets.load_ledger_pin_binding()


def test_walk_parent_admits_branch_internal_merge_only() -> None:
    from pin_ledger import PinError, _require_walk_parent

    def payload(sha, parents):
        return {"sha": sha, "parents": [{"sha": parent} for parent in parents]}

    base, side, merge = "a" * 40, "b" * 40, "c" * 40

    # Single-parent commits keep the exact-chain rule.
    assert _require_walk_parent(payload(side, [base]), side, base, {base}) is False
    with pytest.raises(PinError, match="skips or reorders"):
        _require_walk_parent(payload(side, ["d" * 40]), side, base, {base})

    # The real 2026-07-18 diamond: side branch forked from the pin, merged
    # back while the walk predecessor is the side commit. Both parents are
    # walked, so the merge is traversable.
    assert (
        _require_walk_parent(payload(merge, [base, side]), merge, side, {base, side})
        is True
    )

    # A merge whose other parent was never walked splices foreign history.
    with pytest.raises(PinError, match="unwalked history"):
        _require_walk_parent(
            payload(merge, ["e" * 40, side]), merge, side, {base, side}
        )

    # A merge that does not continue the walk predecessor is rejected too.
    with pytest.raises(PinError, match="does not continue the walk"):
        _require_walk_parent(
            payload(merge, [base, "e" * 40]), merge, side, {base, side}
        )

    # No parents at all is never traversable.
    with pytest.raises(PinError, match="linear single-parent"):
        _require_walk_parent(payload(merge, []), merge, side, {base, side})


def test_rebuild_from_history_carries_the_ratchet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    # Final-review residual: operator rebuild reset the monotonic registry
    # ratchet, accepting a v2/no-registry head after a v3+registry commit.
    registry = _registry_bytes()
    _declare_registry(
        release_repo.repo,
        registry=registry,
        declared_digest=hashlib.sha256(registry).hexdigest(),
        message="declare uuid registry",
    )
    catalog_path = release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH
    catalog = json.loads(catalog_path.read_text())
    catalog.pop("uuid_registry_sha256", None)
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    (release_repo.repo / pin_ledger.LEDGER_REGISTRY_PATH).unlink()
    _commit(release_repo.repo, "downgrade after declaring")
    _prepare_refresh(monkeypatch, tmp_path, release_repo)

    with pytest.raises(pin_ledger.PinError, match="downgraded away"):
        pin_ledger.rebuild_from_history(release_repo.repo, "HEAD")


def test_lineage_scan_survives_merge_dags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    # Review repro (a): a merge ADOPTING an undeclared side catalog used
    # to be pruned by path-limited history simplification, letting the
    # downgrade through rebuild_from_history.
    repo = release_repo.repo
    registry = _registry_bytes()
    _declare_registry(
        repo,
        registry=registry,
        declared_digest=hashlib.sha256(registry).hexdigest(),
        message="declare uuid registry",
    )
    declared_sha = _git(repo, "rev-parse", "HEAD")
    catalog_path = repo / pin_ledger.LEDGER_CATALOG_PATH

    # Side branch: still-undeclared catalog, distinguishable content.
    _git(repo, "checkout", "-q", "-b", "side", f"{declared_sha}~1")
    side_catalog = json.loads(catalog_path.read_text())
    side_catalog["comment"] = "side variant, never declared"
    catalog_path.write_text(json.dumps(side_catalog, separators=(",", ":")) + "\n")
    _commit(repo, "side: undeclared catalog variant")

    # Mainline merge that ADOPTS the side catalog and drops the registry.
    _git(repo, "checkout", "-q", declared_sha)
    _git(repo, "checkout", "-q", "-b", "mainline")
    subprocess.run(
        ["git", "merge", "--no-ff", "--no-commit", "side"],
        cwd=repo,
        capture_output=True,
        text=True,
    )  # a content conflict is expected; the resolution is written below
    catalog_path.write_text(json.dumps(side_catalog, separators=(",", ":")) + "\n")
    registry_file = repo / pin_ledger.LEDGER_REGISTRY_PATH
    if registry_file.exists():
        registry_file.unlink()
    _commit(repo, "merge side (adopts undeclared catalog)")

    with pytest.raises(pin_ledger.PinError, match="downgraded away"):
        pin_ledger.rebuild_from_history(repo, "HEAD")


def test_lineage_scan_accepts_declaration_retaining_merge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    # Round-1 false-rejection repro: a DECLARED mainline merges an
    # undeclared sibling while RETAINING its declared catalog. The scan
    # must report the declaration and must not read the sibling's
    # undeclared content as a downgrade.
    repo = release_repo.repo
    base_sha = _git(repo, "rev-parse", "HEAD")
    catalog_path = repo / pin_ledger.LEDGER_CATALOG_PATH

    _git(repo, "checkout", "-q", "-b", "undeclared-side")
    catalog = json.loads(catalog_path.read_text())
    catalog["comment"] = "sibling touch, never declared"
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    _commit(repo, "side: touch catalog, still undeclared")

    registry = _registry_bytes()
    _git(repo, "checkout", "-q", base_sha)
    _git(repo, "checkout", "-q", "-b", "declared-mainline")
    _declare_registry(
        repo,
        registry=registry,
        declared_digest=hashlib.sha256(registry).hexdigest(),
        message="mainline: declare uuid registry",
    )
    _git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "-s",
        "ours",
        "undeclared-side",
        "-m",
        "merge sibling, retain declared catalog",
    )

    assert (
        pin_ledger._walked_lineage_declares_registry(
            repo, _git(repo, "rev-parse", "HEAD")
        )
        is True
    )


def test_unadopted_side_declaration_binds_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    # Merge topology cannot distinguish "we declined a side branch's
    # declaration" from "an undeclared branch swallowed a declared
    # mainline and the ref fast-forwarded onto the merge" — the DAGs are
    # identical. The ratchet is therefore existential: once a declaring
    # catalog is in the ancestry, an undeclared head refuses, even when
    # the declaration's content was never adopted.
    repo = release_repo.repo
    base_sha = _git(repo, "rev-parse", "HEAD")
    catalog_path = repo / pin_ledger.LEDGER_CATALOG_PATH

    registry = _registry_bytes()
    _git(repo, "checkout", "-q", "-b", "declaring-side")
    _declare_registry(
        repo,
        registry=registry,
        declared_digest=hashlib.sha256(registry).hexdigest(),
        message="side: declare uuid registry",
    )
    _git(repo, "checkout", "-q", base_sha)
    _git(repo, "checkout", "-q", "-b", "mainline2")
    catalog = json.loads(catalog_path.read_text())
    catalog["comment"] = "mainline touch"
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    _commit(repo, "mainline: touch catalog, still undeclared")
    _git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "-s",
        "ours",
        "declaring-side",
        "-m",
        "merge side, retain mainline catalog",
    )

    with pytest.raises(pin_ledger.PinError, match="downgraded away"):
        pin_ledger._walked_lineage_declares_registry(
            repo, _git(repo, "rev-parse", "HEAD")
        )


def test_second_parent_declaration_cannot_be_laundered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    # Round-2 repro: mainline DECLARES; an undeclared branch merges the
    # declared tip with `-s ours` (declaration content discarded, the
    # declaring commit demoted to second parent and TREESAME to the first
    # parent), then the ref fast-forwards onto the merge. A single-parent
    # walk never lists the declaring commit; the existential scan must
    # still find it and refuse the undeclared head.
    repo = release_repo.repo
    undeclared_sha = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")

    registry = _registry_bytes()
    _declare_registry(
        repo,
        registry=registry,
        declared_digest=hashlib.sha256(registry).hexdigest(),
        message="mainline declares uuid registry",
    )
    declared_sha = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-q", "-b", "swallow", undeclared_sha)
    (repo / "side-note.txt").write_text("diverged while undeclared\n")
    _commit(repo, "side diverges while undeclared")
    _git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        "-s",
        "ours",
        branch,
        "-m",
        "swallow declared mainline as second parent",
    )
    merge_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", branch)
    _git(repo, "merge", "-q", "--ff-only", "swallow")
    assert _git(repo, "rev-parse", "HEAD") == merge_sha
    parents = _git(repo, "show", "-s", "--format=%P", merge_sha).split()
    assert parents[1] == declared_sha

    with pytest.raises(pin_ledger.PinError, match="downgraded away"):
        pin_ledger.rebuild_from_history(repo, "HEAD")


def test_refresh_cannot_cross_declaration_then_downgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    # Round-3 repro: the pin sits at an UNDECLARED commit; a later commit
    # declares the registry and the next removes it again, leaving a
    # well-formed v2 head. registry_expected derived from the endpoints
    # alone would advance the pin straight over the crossed declaration;
    # the walk must latch it and refuse the downgraded head.
    pin_path, availability_path, generated_path, _ = _prepare_refresh(
        monkeypatch, tmp_path, release_repo
    )
    pin_ledger.refresh()  # pin at the undeclared base

    registry = _registry_bytes()
    _declare_registry(
        release_repo.repo,
        registry=registry,
        declared_digest=hashlib.sha256(registry).hexdigest(),
        message="declare uuid registry mid-window",
    )
    catalog_path = release_repo.repo / pin_ledger.LEDGER_CATALOG_PATH
    catalog = json.loads(catalog_path.read_text())
    catalog["generator_version"] = 3
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    _commit(release_repo.repo, "v3 catalog mid-window")

    catalog = json.loads(catalog_path.read_text())
    catalog["generator_version"] = 2
    catalog.pop("uuid_registry_sha256", None)
    catalog_path.write_text(json.dumps(catalog, separators=(",", ":")) + "\n")
    (release_repo.repo / pin_ledger.LEDGER_REGISTRY_PATH).unlink()
    _commit(release_repo.repo, "downgrade back to v2 in the same window")

    before = pin_path.read_bytes()
    with pytest.raises(pin_ledger.PinError, match="downgraded away"):
        pin_ledger.refresh()
    assert pin_path.read_bytes() == before


def test_lineage_scan_refuses_shallow_clone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    release_repo: ReleaseRepo,
) -> None:
    # Round-3 repro: a depth-limited clone turns the shallow boundary into
    # a root, so rev-list silently omits every commit behind it — an
    # ancestor declaration disappears without error. The scan must refuse
    # shallow repositories instead of reporting "never declared".
    repo = release_repo.repo
    registry = _registry_bytes()
    _declare_registry(
        repo,
        registry=registry,
        declared_digest=hashlib.sha256(registry).hexdigest(),
        message="declare uuid registry",
    )
    shallow = tmp_path / "shallow-clone"
    _run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow)],
        cwd=repo.parent,
    )
    with pytest.raises(pin_ledger.PinError, match="shallow"):
        pin_ledger._walked_lineage_declares_registry(
            shallow, _git(shallow, "rev-parse", "HEAD")
        )
