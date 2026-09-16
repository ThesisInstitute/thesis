from __future__ import annotations

import hashlib
import json
import pathlib
import stat
import subprocess
import sys
from collections.abc import Mapping

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_system_one_forecast as system_one  # noqa: E402
import run_thesis_analyst as analyst  # noqa: E402
import strategy_publication as publication  # noqa: E402
import verify_custody  # noqa: E402
from canonical_json import canonical_sha256  # noqa: E402

from tests.test_run_system_one_forecast import (  # noqa: E402
    RUN_AT,
    SLUG,
    ledger_rows,
    primary_cell,
    target_context,
    write_comparison_run,
    write_ledger,
    write_primary_run,
)

SUITE = pathlib.PurePosixPath(
    "records/thesis-analyst/strategy-suites/2030-01-10/strategy-123-a1.json"
)
BATCH = pathlib.PurePosixPath(
    "records/thesis-analyst/batches/2030-01-10/strategy-123-a1-ladder.json"
)
RUN_PREFIX = pathlib.PurePosixPath(
    "records/thesis-analyst/2030-01-10/2030-01-10t12-01-00z-agency-test-rate"
)


def target() -> dict:
    return {
        "series": "agency.test.rate",
        "period": "2030-01",
        "catalogSlug": "agency-test-rate-january-2030",
        "country": "US",
        "dataPointId": "agency.test.rate.2030_01.first_print",
        "targetUnit": "percent",
        "valueScale": 1,
        "sourceBinding": {
            "adapter": "generic-url",
            "sourceUrl": "https://agency.example/rate",
            "allowedHosts": ["agency.example"],
        },
        "resolutionDate": "2030-02-15",
        "resolutionSource": "Agency",
        "resolutionSourceUrl": "https://agency.example/rate",
        "resolutionRule": "Use the first official print only.",
        "resolutionPolicy": "first_print",
        "registeredAtUtc": "2030-01-01T00:00:00Z",
        "targetContentHash": "b" * 64,
        "targetRegistrationPath": f"records/targets/2030-01-01-{'b' * 64}.json",
        "registrationCommit": "a" * 40,
        "comparisonTarget": True,
    }


def selection_payload() -> dict:
    value = {
        "schemaVersion": publication.SELECTION_SCHEMA,
        "sourceSha": "c" * 40,
        "selectedAtUtc": "2030-01-10T12:00:00Z",
        "selectionPath": (
            "records/thesis-analyst/strategy-selections/2030-01-10/strategy-123-a1.json"
        ),
        "workflow": {
            "repository": "owner/repo",
            "runId": 123,
            "runAttempt": 1,
            "artifactId": 456,
            "artifactName": "strategy-probe-123-1",
            "artifactDigest": "sha256:" + "d" * 64,
            "artifactCreatedAtUtc": "2030-01-10T12:01:00Z",
        },
        "request": {
            "catalogSlugs": [target()["catalogSlug"]],
            "autoSelect": False,
            "maxTargets": 1,
            "suite": "ladder",
        },
        "localResolutionEvidence": {},
        "ledgerEvidence": {},
        "targets": [target()],
    }
    value["selectionSetHash"] = canonical_sha256(value)
    return value


def suite_payload(selection_path: pathlib.Path) -> dict:
    selection = json.loads(selection_path.read_text())
    return {
        "schemaVersion": publication.SUITE_SCHEMA,
        "sourceSha": selection["sourceSha"],
        "selectionPath": selection["selectionPath"],
        "selectionSha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "selectionSetHash": selection["selectionSetHash"],
        "suite": "ladder",
        "createdAt": "2030-01-10T12:10:00Z",
        "lanes": {
            "ladder": {"batchManifest": BATCH.as_posix()},
            "rollouts": [],
            "median3": [],
        },
    }


def write_selection(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(selection_payload(), indent=2) + "\n")
    return path


def init_git(path: pathlib.Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "base",
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )


def write_bundle(
    root: pathlib.Path,
    selection_path: pathlib.Path,
    files: Mapping[pathlib.PurePosixPath, bytes],
) -> pathlib.Path:
    return write_bundle_for(root, selection_path, SUITE, files)


def write_bundle_for(
    root: pathlib.Path,
    selection_path: pathlib.Path,
    suite_relative: pathlib.PurePosixPath,
    files: Mapping[pathlib.PurePosixPath, bytes],
) -> pathlib.Path:
    bundle = root / "bundle"
    repo = bundle / "repo"
    entries = []
    for relative, raw in files.items():
        path = repo.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        entries.append(
            {
                "path": relative.as_posix(),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
        )
    selection = json.loads(selection_path.read_text())
    (bundle / "bundle_manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": publication.BUNDLE_SCHEMA,
                "publicationKind": "strategy_comparison",
                "suiteManifest": suite_relative.as_posix(),
                "sourceSha": selection["sourceSha"],
                "selectionSha256": hashlib.sha256(
                    selection_path.read_bytes()
                ).hexdigest(),
                "selectionSetHash": selection["selectionSetHash"],
                "files": entries,
            }
        )
        + "\n"
    )
    return bundle


def test_selection_requires_server_timestamp_near_select(tmp_path: pathlib.Path):
    path = write_selection(tmp_path)
    selection = json.loads(path.read_text())
    selection["workflow"]["artifactCreatedAtUtc"] = "2030-01-10T12:16:00Z"
    selection.pop("selectionSetHash")
    selection["selectionSetHash"] = canonical_sha256(selection)
    path.write_text(json.dumps(selection))

    with pytest.raises(
        publication.StrategyPublicationError, match="not contemporaneous"
    ):
        publication._validate_selection(path)


@pytest.mark.parametrize("label", ["analyst", "median3"])
def test_claimed_runat_before_artifact_witness_is_rejected(label: str):
    lower = publication._instant("2030-01-10T12:01:00Z", "lower")
    with pytest.raises(
        publication.StrategyPublicationError, match="outside the witnessed window"
    ):
        publication._require_claimed_run_window(
            lower,
            publication._instant("2030-01-10T12:00:59Z", "start"),
            publication._instant("2030-01-10T12:01:01Z", "runAt"),
            publication._instant("2030-01-10T12:10:00Z", "upper"),
            label,
        )


@pytest.mark.parametrize("label", ["analyst", "median3"])
def test_claimed_runat_after_publish_validation_is_rejected(label: str):
    lower = publication._instant("2030-01-10T12:01:00Z", "lower")
    with pytest.raises(
        publication.StrategyPublicationError, match="outside the witnessed window"
    ):
        publication._require_claimed_run_window(
            lower,
            publication._instant("2030-01-10T12:02:00Z", "start"),
            publication._instant("2030-01-10T12:10:01Z", "runAt"),
            publication._instant("2030-01-10T12:10:00Z", "upper"),
            label,
        )


def test_suite_shape_yields_only_exact_component_batches(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    selection_path = write_selection(tmp_path)
    repo = tmp_path / "repo"
    suite_path = repo.joinpath(*SUITE.parts)
    suite_path.parent.mkdir(parents=True)
    suite_path.write_text(json.dumps(suite_payload(selection_path)))
    monkeypatch.setattr(publication, "_validate_source_sha", lambda *_a, **_k: None)
    monkeypatch.setattr(
        publication,
        "_validate_batch",
        lambda *_a, **_k: (
            {target()["catalogSlug"]: {"target": target()}},
            {RUN_PREFIX},
            publication._instant("2030-01-10T12:09:00Z", "fixture"),
        ),
    )

    exact, prefixes = publication.validate_tree(
        repo,
        SUITE,
        selection_path,
        publish_validated_at="2030-01-10T12:11:00Z",
        exact_source=True,
    )
    assert exact == {SUITE, BATCH}
    assert prefixes == {RUN_PREFIX}


def test_suite_shape_rejects_batch_from_another_invocation(
    tmp_path: pathlib.Path,
) -> None:
    selection_path = write_selection(tmp_path)
    selection = json.loads(selection_path.read_text())
    suite = suite_payload(selection_path)
    suite["lanes"]["ladder"]["batchManifest"] = (
        "records/thesis-analyst/batches/2030-01-10/strategy-999-a1-ladder.json"
    )

    with pytest.raises(
        publication.StrategyPublicationError, match="trusted lane"
    ):
        publication._validate_suite_shape(
            suite,
            SUITE,
            selection,
            selection_path,
            {target()["catalogSlug"]: target()},
        )


@pytest.mark.parametrize(
    ("forbidden", "message"),
    [
        (
            pathlib.PurePosixPath(f"records/targets/2030-01-01-{'b' * 64}.json"),
            "target registration snapshots",
        ),
        (RUN_PREFIX / "ledger-targets.generated.ts", "executable source code"),
        (RUN_PREFIX / "resolution.json", "resolution markers"),
        (pathlib.PurePosixPath("records/CHAIN_HEAD.json"), "record-chain"),
    ],
)
def test_bundle_rejects_forbidden_paths_even_if_suite_scope_claims_them(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    forbidden: pathlib.PurePosixPath,
    message: str,
):
    checkout = tmp_path / "checkout"
    init_git(checkout)
    selection_path = write_selection(tmp_path)
    suite_raw = json.dumps(suite_payload(selection_path)).encode()
    files = {SUITE: suite_raw, BATCH: b"{}\n", forbidden: b"{}\n"}
    bundle = write_bundle(tmp_path, selection_path, files)
    monkeypatch.setattr(publication, "ROOT", checkout)
    monkeypatch.setattr(
        publication,
        "validate_tree",
        lambda *_a, **_k: ({SUITE, BATCH, forbidden}, {RUN_PREFIX}),
    )

    with pytest.raises(publication.StrategyPublicationError, match=message):
        publication._load_bundle(
            bundle,
            SUITE,
            selection_path,
            "2030-01-10T12:11:00Z",
        )


def test_bundle_rejects_uninventoried_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    checkout = tmp_path / "checkout"
    init_git(checkout)
    selection_path = write_selection(tmp_path)
    bundle = write_bundle(
        tmp_path,
        selection_path,
        {SUITE: json.dumps(suite_payload(selection_path)).encode(), BATCH: b"{}\n"},
    )
    extra = bundle / "repo" / RUN_PREFIX.as_posix() / "surprise.txt"
    extra.parent.mkdir(parents=True)
    extra.write_text("not inventoried\n")
    monkeypatch.setattr(publication, "ROOT", checkout)

    with pytest.raises(
        publication.StrategyPublicationError, match="inventory mismatch"
    ):
        publication._load_bundle(
            bundle,
            SUITE,
            selection_path,
            "2030-01-10T12:11:00Z",
        )


@pytest.mark.parametrize("symlinked", ["repo", "manifest"])
def test_bundle_rejects_symlinked_control_roots(
    tmp_path: pathlib.Path,
    symlinked: str,
) -> None:
    selection_path = write_selection(tmp_path)
    bundle = write_bundle(
        tmp_path,
        selection_path,
        {SUITE: json.dumps(suite_payload(selection_path)).encode(), BATCH: b"{}\n"},
    )
    if symlinked == "repo":
        original = tmp_path / "real-repo"
        (bundle / "repo").rename(original)
        (bundle / "repo").symlink_to(original, target_is_directory=True)
    else:
        original = tmp_path / "real-bundle-manifest.json"
        (bundle / "bundle_manifest.json").rename(original)
        (bundle / "bundle_manifest.json").symlink_to(original)

    with pytest.raises(publication.StrategyPublicationError, match="not a regular"):
        publication._load_bundle(
            bundle,
            SUITE,
            selection_path,
            "2030-01-10T12:11:00Z",
        )


def test_batch_target_set_rejects_out_of_selection_target():
    rogue = {**target(), "catalogSlug": "rogue-target"}
    with pytest.raises(
        publication.StrategyPublicationError, match="unauthorized target"
    ):
        publication._target_map(
            [{"target": rogue}],
            {target()["catalogSlug"]: target()},
            "fast",
        )


def test_strategy_lanes_cannot_reuse_failed_run_directories() -> None:
    claimed = {RUN_PREFIX}

    with pytest.raises(publication.StrategyPublicationError, match="reuse analyst"):
        publication._claim_run_prefixes(claimed, {RUN_PREFIX})


def test_strategy_manifest_identity_must_match_trusted_target() -> None:
    trusted = target()

    with pytest.raises(publication.StrategyPublicationError, match="series"):
        publication._validate_manifest_identity(
            {"series": "rogue.series", "period": trusted["period"]},
            trusted,
            ("series", "period"),
        )


def test_cell_resolver_equality_does_not_require_resolution_policy():
    trusted = target()
    cell = {
        "slug": trusted["catalogSlug"],
        "country": trusted["country"],
        "dataPointId": trusted["dataPointId"],
        "unit": trusted["targetUnit"],
        "resolutionDate": trusted["resolutionDate"],
        "resolutionSource": trusted["resolutionSource"],
        "resolutionSourceUrl": trusted["resolutionSourceUrl"],
        "resolutionRule": trusted["resolutionRule"],
        **{field: trusted[field] for field in publication.REGISTRATION_FIELDS},
    }
    publication._resolver_equal(cell, trusted)
    cell["resolutionDate"] = "2030-02-16"
    with pytest.raises(publication.StrategyPublicationError, match="resolutionDate"):
        publication._resolver_equal(cell, trusted)


def test_ladder_lane_prompt_mode_binds_to_trusted_selection(
    tmp_path: pathlib.Path,
) -> None:
    selection_path = write_selection(tmp_path)
    selection = json.loads(selection_path.read_text())
    slug_map = {target()["catalogSlug"]: target()}

    # A recorded lane mode that matches the trusted default passes shape.
    suite = suite_payload(selection_path)
    suite["lanes"]["ladder"]["promptMode"] = "ladder"
    publication._validate_suite_shape(
        suite, SUITE, selection, selection_path, slug_map
    )

    # A recorded mode differing from the trusted selection fails closed.
    suite = suite_payload(selection_path)
    suite["lanes"]["ladder"]["promptMode"] = "ladder_v2"
    with pytest.raises(
        publication.StrategyPublicationError,
        match="differs from trusted selection",
    ):
        publication._validate_suite_shape(
            suite, SUITE, selection, selection_path, slug_map
        )

    # A ladder_v2 selection demands the lane record its mode...
    v2_selection = json.loads(selection_path.read_text())
    v2_selection["request"]["ladderPromptMode"] = "ladder_v2"
    v2_path = tmp_path / "selection-v2.json"
    v2_path.write_text(json.dumps(v2_selection, indent=2) + "\n")
    suite = suite_payload(v2_path)
    with pytest.raises(
        publication.StrategyPublicationError,
        match="does not record the trusted non-default prompt mode",
    ):
        publication._validate_suite_shape(
            suite, SUITE, v2_selection, v2_path, slug_map
        )

    # ...and passes once it does.
    suite = suite_payload(v2_path)
    suite["lanes"]["ladder"]["promptMode"] = "ladder_v2"
    publication._validate_suite_shape(
        suite, SUITE, v2_selection, v2_path, slug_map
    )

    # Unexpected extra lane keys stay rejected.
    suite = suite_payload(selection_path)
    suite["lanes"]["ladder"]["extra"] = True
    with pytest.raises(
        publication.StrategyPublicationError,
        match="lacks its exact batch manifest",
    ):
        publication._validate_suite_shape(
            suite, SUITE, selection, selection_path, slug_map
        )


# --- system one lane --------------------------------------------------------
#
# Every fixture below is a real run produced by the core runner
# (scripts/run_system_one_forecast.py) into tmp_path: the manifests, the
# custody root and the sealed ladder are the runner's own bytes, so the
# boundary is exercised against what the lane actually writes.

SYSTEM_ONE_SUITE_PATH = pathlib.PurePosixPath(
    "records/thesis-analyst/strategy-suites/2030-01-10/strategy-321-a1.json"
)
SYSTEM_ONE_BATCH = pathlib.PurePosixPath(
    "records/thesis-analyst/batches/2030-01-10/strategy-321-a1-system-one.json"
)
SYSTEM_ONE_SELECTION = (
    "records/thesis-analyst/strategy-selections/2030-01-10/strategy-321-a1.json"
)
SYSTEM_ONE_RUN_PREFIX = pathlib.PurePosixPath(
    f"records/thesis-analyst/2030-01-10/2030-01-10t12-00-00z-system-one-{SLUG}"
)
BATCH_STARTED = "2030-01-10T11:59:00Z"
RESULT_STARTED = "2030-01-10T11:59:30Z"
RESULT_FINISHED = "2030-01-10T12:01:00Z"
BATCH_FINISHED = "2030-01-10T12:05:00Z"
SUITE_CREATED = "2030-01-10T12:06:00Z"
PUBLISH_VALIDATED = "2030-01-10T12:10:00Z"
# Sentinel: the suite lane repeats the trusted request unless a test overrides
# it, and None is itself a meaningful lane value (the backend default model).
FROM_REQUEST = object()

# A deliberately non-monotone raw ladder: rungs 6 and 7 are swapped, so the
# published ladder can only be right if pool-adjacent-violators actually ran.
RAW_NOULS = [
    0.01,
    0.03,
    0.07,
    0.12,
    0.2,
    0.42,
    0.31,
    0.55,
    0.66,
    0.75,
    0.83,
    0.89,
    0.93,
    0.96,
    0.99,
]


def fake_system_one_answers(payloads: dict, model: str) -> dict:
    return {
        "model": model,
        "usage": {"input_tokens": 1024, "output_tokens": 96},
        "answers": {
            name: {"type": "noul", "noul": value}
            for name, value in zip(payloads, RAW_NOULS)
        },
    }


def system_one_selection_payload(
    *, backend: str = "adapter", model: str | None = "gpt-5.6-terra"
) -> dict:
    value = {
        "schemaVersion": publication.SELECTION_SCHEMA,
        "sourceSha": "c" * 40,
        "selectedAtUtc": "2030-01-10T11:50:00Z",
        "selectionPath": SYSTEM_ONE_SELECTION,
        "workflow": {
            "repository": "owner/repo",
            "runId": 321,
            "runAttempt": 1,
            "artifactId": 654,
            "artifactName": "strategy-probe-321-1",
            "artifactDigest": "sha256:" + "e" * 64,
            "artifactCreatedAtUtc": "2030-01-10T11:55:00Z",
        },
        "request": {
            "catalogSlugs": [SLUG],
            "autoSelect": False,
            "maxTargets": 1,
            "suite": "system_one",
            "systemOneBackend": backend,
            "systemOneModel": model,
        },
        "localResolutionEvidence": {},
        "ledgerEvidence": {},
        "targets": [target_context()],
    }
    value["selectionSetHash"] = canonical_sha256(value)
    return value


def write_system_one_selection(tmp_path: pathlib.Path, **kwargs) -> pathlib.Path:
    path = tmp_path / "system-one-selection.json"
    path.write_text(json.dumps(system_one_selection_payload(**kwargs), indent=2) + "\n")
    return path


def run_system_one(
    repo: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    backend: str = "adapter",
    provider: str | None = "openai",
    model: str | None = "gpt-5.6-terra",
    answering_model: str | None = None,
    cell: dict | None = None,
    ledger: list[dict] | None = None,
    expect_ok: bool = True,
) -> pathlib.Path:
    """Produce one sealed system one run inside repo and return its manifest."""

    monkeypatch.setattr(publication, "ROOT", repo)
    monkeypatch.setattr(analyst, "ROOT", repo)
    monkeypatch.setattr(system_one, "ROOT", repo)
    monkeypatch.setattr(verify_custody, "REPOSITORY_ROOT", repo)
    monkeypatch.setenv("OPENAI_API_KEY", "publication-test-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "publication-test-key")
    monkeypatch.setattr(
        system_one,
        "call_adapter",
        lambda *, state, payloads, provider, model: fake_system_one_answers(
            payloads, answering_model or model
        ),
    )
    monkeypatch.setattr(
        system_one,
        "call_typesafe",
        lambda *, state, payloads, model: fake_system_one_answers(
            payloads, answering_model or model or "jev-1"
        ),
    )
    if not (repo / "records" / "thesis-analyst" / "2029-12-31").exists():
        write_primary_run(repo, cell or primary_cell())
    ledger_path = (
        write_ledger(repo, ledger_rows() if ledger is None else ledger)
        if ledger != []
        else None
    )
    manifest, manifest_path = system_one.run_forecast(
        target=target_context(),
        backend=backend,
        records_root=repo / "records",
        ledger_path=ledger_path,
        provider=provider,
        model=model,
        run_at=RUN_AT,
    )
    assert manifest["ok"] is expect_ok, manifest.get("error")
    return manifest_path


def write_system_one_batch(
    repo: pathlib.Path,
    manifest_path: pathlib.Path,
    *,
    manifest_override: str | None = None,
) -> pathlib.Path:
    relative = pathlib.PurePosixPath(manifest_path.relative_to(repo).as_posix())
    manifest = json.loads(manifest_path.read_text())
    ok = manifest["ok"] is True
    result = {
        "target": target_context(),
        "startedAt": RESULT_STARTED,
        "finishedAt": RESULT_FINISHED,
        "returnCode": 0 if ok else 1,
        "ok": ok,
        "manifestPath": manifest_override or relative.as_posix(),
        "cellsPath": manifest["cellsPath"],
        "error": None if ok else (manifest["error"] or {}).get("message"),
    }
    batch = {
        "schemaVersion": "thesis_batch_manifest_v1",
        "startedAt": BATCH_STARTED,
        "finishedAt": BATCH_FINISHED,
        "promptMode": publication.SYSTEM_ONE_PROMPT_MODE,
        "targets": 1,
        "ok": 1 if ok else 0,
        "failed": 0 if ok else 1,
        "results": [result],
    }
    path = repo.joinpath(*SYSTEM_ONE_BATCH.parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(batch, indent=2) + "\n")
    return path


def write_system_one_suite(
    repo: pathlib.Path,
    selection_path: pathlib.Path,
    *,
    backend: str = "adapter",
    model: str | None = "gpt-5.6-terra",
) -> pathlib.Path:
    selection = json.loads(selection_path.read_text())
    suite = {
        "schemaVersion": publication.SUITE_SCHEMA,
        "sourceSha": selection["sourceSha"],
        "selectionPath": selection["selectionPath"],
        "selectionSha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
        "selectionSetHash": selection["selectionSetHash"],
        "suite": "system_one",
        "createdAt": SUITE_CREATED,
        "lanes": {
            "ladder": None,
            "rollouts": [],
            "median3": [],
            "systemOne": {
                "batchManifest": SYSTEM_ONE_BATCH.as_posix(),
                "backend": backend,
                "model": model,
            },
        },
    }
    path = repo.joinpath(*SYSTEM_ONE_SUITE_PATH.parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(suite, indent=2) + "\n")
    return path


def system_one_tree(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    request_backend: str = "adapter",
    request_model: str | None = "gpt-5.6-terra",
    run_backend: str = "adapter",
    run_provider: str | None = "openai",
    run_model: str | None = "gpt-5.6-terra",
    answering_model: str | None = None,
    lane_backend: object = FROM_REQUEST,
    lane_model: object = FROM_REQUEST,
    manifest_override: str | None = None,
    git: bool = False,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Build a complete system one suite; return (repo, selection path)."""

    repo = tmp_path / "repo"
    if git:
        init_git(repo)
    else:
        repo.mkdir()
    selection_path = write_system_one_selection(
        tmp_path, backend=request_backend, model=request_model
    )
    manifest_path = run_system_one(
        repo,
        monkeypatch,
        backend=run_backend,
        provider=run_provider,
        model=run_model,
        answering_model=answering_model,
    )
    write_system_one_batch(repo, manifest_path, manifest_override=manifest_override)
    write_system_one_suite(
        repo,
        selection_path,
        backend=request_backend if lane_backend is FROM_REQUEST else lane_backend,
        model=request_model if lane_model is FROM_REQUEST else lane_model,
    )
    monkeypatch.setattr(publication, "_validate_source_sha", lambda *_a, **_k: None)
    monkeypatch.setattr(
        publication.docket, "validate_target_registration", lambda *_a, **_k: {}
    )
    return repo, selection_path


def system_one_ledger(repo: pathlib.Path) -> pathlib.Path:
    """The pinned ledger the boundary rebuilds the evidence state from.

    A run that matched no ledger rows still validates against the pin; an
    empty file stands in for a ledger with nothing for this series.
    """

    path = repo / "official_observations.jsonl"
    if not path.exists():
        path.write_text("")
    return path


def validate_system_one_tree(
    repo: pathlib.Path,
    selection_path: pathlib.Path,
    ledger_path: pathlib.Path | None = None,
) -> tuple[set, set]:
    return publication.validate_tree(
        repo,
        SYSTEM_ONE_SUITE_PATH,
        selection_path,
        publish_validated_at=PUBLISH_VALIDATED,
        exact_source=True,
        ledger_path=(
            system_one_ledger(repo) if ledger_path is None else ledger_path
        ),
    )


def test_validate_tree_accepts_a_well_formed_system_one_suite(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(tmp_path, monkeypatch)

    exact, prefixes = validate_system_one_tree(repo, selection_path)

    assert exact == {SYSTEM_ONE_SUITE_PATH, SYSTEM_ONE_BATCH}
    assert prefixes == {SYSTEM_ONE_RUN_PREFIX}


def test_validate_tree_accepts_the_typesafe_backend(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A typesafe run answers with the model identifier the service returned,
    # which the request never fixes; the lane still binds the requested one.
    repo, selection_path = system_one_tree(
        tmp_path,
        monkeypatch,
        request_backend="typesafe",
        request_model="jev-1",
        run_backend="typesafe",
        run_provider=None,
        run_model="jev-1",
        answering_model="jev-1-2030-01",
    )

    exact, prefixes = validate_system_one_tree(repo, selection_path)

    assert exact == {SYSTEM_ONE_SUITE_PATH, SYSTEM_ONE_BATCH}
    assert prefixes == {SYSTEM_ONE_RUN_PREFIX}
    manifest = json.loads(
        repo.joinpath(*SYSTEM_ONE_RUN_PREFIX.parts, "manifest.json").read_text()
    )
    assert manifest["agent"]["model"] == "jev-1-2030-01"


def test_system_one_bundle_crosses_the_publication_boundary(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(tmp_path, monkeypatch, git=True)
    files = {
        relative: repo.joinpath(*relative.parts).read_bytes()
        for relative in (
            SYSTEM_ONE_SUITE_PATH,
            SYSTEM_ONE_BATCH,
            *(
                SYSTEM_ONE_RUN_PREFIX / path.name
                for path in sorted(
                    repo.joinpath(*SYSTEM_ONE_RUN_PREFIX.parts).iterdir()
                )
            ),
        )
    }
    bundle = write_bundle_for(tmp_path, selection_path, SYSTEM_ONE_SUITE_PATH, files)

    bundle_repo, manifest = publication._load_bundle(
        bundle,
        SYSTEM_ONE_SUITE_PATH,
        selection_path,
        PUBLISH_VALIDATED,
        system_one_ledger(repo),
    )

    assert (bundle_repo / SYSTEM_ONE_BATCH.as_posix()).is_file()
    assert {entry["path"] for entry in manifest["files"]} == {
        relative.as_posix() for relative in files
    }


def test_system_one_bundle_rejects_an_unreferenced_run_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(tmp_path, monkeypatch, git=True)
    foreign = pathlib.PurePosixPath(
        "records/thesis-analyst/2030-01-10/2030-01-10t12-30-00z-system-one-foreign"
    )
    files = {
        relative: repo.joinpath(*relative.parts).read_bytes()
        for relative in (
            SYSTEM_ONE_SUITE_PATH,
            SYSTEM_ONE_BATCH,
            *(
                SYSTEM_ONE_RUN_PREFIX / path.name
                for path in sorted(
                    repo.joinpath(*SYSTEM_ONE_RUN_PREFIX.parts).iterdir()
                )
            ),
        )
    }
    files[foreign / "manifest.json"] = repo.joinpath(
        *SYSTEM_ONE_RUN_PREFIX.parts, "manifest.json"
    ).read_bytes()
    bundle = write_bundle_for(tmp_path, selection_path, SYSTEM_ONE_SUITE_PATH, files)

    with pytest.raises(
        publication.StrategyPublicationError, match="outside exact scope"
    ):
        publication._load_bundle(
            bundle,
            SYSTEM_ONE_SUITE_PATH,
            selection_path,
            PUBLISH_VALIDATED,
            system_one_ledger(repo),
        )


def test_system_one_lane_rejects_a_foreign_run_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(
        tmp_path,
        monkeypatch,
        manifest_override="records/thesis-analyst/elsewhere/manifest.json",
    )

    with pytest.raises(
        publication.StrategyPublicationError, match="outside exact scope"
    ):
        validate_system_one_tree(repo, selection_path)


def test_system_one_lane_rejects_a_run_from_another_lane(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The primary analyst run is a real, custody-complete run in the same
    # records tree. It is still not this lane's run.
    repo, selection_path = system_one_tree(
        tmp_path,
        monkeypatch,
        manifest_override=(
            "records/thesis-analyst/2029-12-31/"
            f"2029-12-31t00-00-00z-primary-{SLUG}/manifest.json"
        ),
    )

    with pytest.raises(
        publication.StrategyPublicationError, match="non-system-one manifest"
    ):
        validate_system_one_tree(repo, selection_path)


def test_system_one_run_backend_must_equal_the_trusted_request(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(
        tmp_path,
        monkeypatch,
        request_backend="typesafe",
        request_model=None,
        run_backend="adapter",
        run_provider="openai",
        run_model="gpt-5.6-terra",
    )

    with pytest.raises(
        publication.StrategyPublicationError,
        match="backend differs from the trusted request",
    ):
        validate_system_one_tree(repo, selection_path)


def test_system_one_run_model_must_equal_the_trusted_request(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(
        tmp_path, monkeypatch, request_model="gpt-5.6-terra", run_model="gpt-5.6-luna"
    )

    with pytest.raises(
        publication.StrategyPublicationError,
        match="model differs from the trusted request",
    ):
        validate_system_one_tree(repo, selection_path)


def test_a_null_request_model_means_the_runner_default_not_any_model(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A null systemOneModel is what the workflow sends when the operator
    # leaves the model input empty, and the suite runner then passes no
    # --model at all. It authorizes the runner default, nothing else.
    repo, selection_path = system_one_tree(
        tmp_path,
        monkeypatch,
        request_model=None,
        lane_model=None,
        run_model="gpt-4o-mini",
    )

    with pytest.raises(
        publication.StrategyPublicationError,
        match="model differs from the trusted request",
    ):
        validate_system_one_tree(repo, selection_path)


def test_a_null_request_model_accepts_the_runner_default(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(
        tmp_path,
        monkeypatch,
        request_model=None,
        lane_model=None,
        run_model=system_one.DEFAULT_ADAPTER_MODEL,
    )

    exact, prefixes = validate_system_one_tree(repo, selection_path)

    assert exact == {SYSTEM_ONE_SUITE_PATH, SYSTEM_ONE_BATCH}
    assert prefixes == {SYSTEM_ONE_RUN_PREFIX}


def test_an_adapter_run_must_use_the_lane_default_provider(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The trusted request carries no provider because a dispatched run never
    # picks one: --provider anthropic is a local-run option only.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "publication-test-key")
    repo, selection_path = system_one_tree(
        tmp_path, monkeypatch, run_provider="anthropic"
    )

    with pytest.raises(
        publication.StrategyPublicationError,
        match="provider differs from the trusted lane default",
    ):
        validate_system_one_tree(repo, selection_path)


def test_mock_system_one_runs_never_cross_the_boundary(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(
        tmp_path, monkeypatch, run_backend="mock", run_provider=None, run_model=None
    )

    with pytest.raises(
        publication.StrategyPublicationError,
        match="backend differs from the trusted request",
    ):
        validate_system_one_tree(repo, selection_path)


def test_system_one_lane_backend_must_equal_the_trusted_selection(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(
        tmp_path, monkeypatch, lane_backend="typesafe"
    )

    with pytest.raises(
        publication.StrategyPublicationError,
        match="lane backend differs from trusted selection",
    ):
        validate_system_one_tree(repo, selection_path)


@pytest.mark.parametrize(
    ("request_model", "lane_model"),
    [("gpt-5.6-terra", "gpt-5.6-luna"), ("gpt-5.6-terra", None), (None, "gpt-5.6-terra")],
)
def test_system_one_lane_model_must_equal_the_trusted_selection(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    request_model: str | None,
    lane_model: str | None,
) -> None:
    repo, selection_path = system_one_tree(
        tmp_path,
        monkeypatch,
        request_model=request_model,
        run_model=request_model or "gpt-5.6-terra",
        lane_model=lane_model,
    )

    with pytest.raises(
        publication.StrategyPublicationError,
        match="lane model differs from trusted selection",
    ):
        validate_system_one_tree(repo, selection_path)


def test_system_one_batch_path_must_be_invocation_scoped(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(tmp_path, monkeypatch)
    suite_path = repo.joinpath(*SYSTEM_ONE_SUITE_PATH.parts)
    suite = json.loads(suite_path.read_text())
    suite["lanes"]["systemOne"]["batchManifest"] = (
        "records/thesis-analyst/batches/2030-01-10/strategy-999-a1-system-one.json"
    )
    suite_path.write_text(json.dumps(suite, indent=2) + "\n")

    with pytest.raises(publication.StrategyPublicationError, match="trusted lane"):
        validate_system_one_tree(repo, selection_path)


def test_system_one_primary_cell_must_be_in_the_publisher_checkout(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(tmp_path, monkeypatch)
    primary = (
        repo
        / "records"
        / "thesis-analyst"
        / "2029-12-31"
        / f"2029-12-31t00-00-00z-primary-{SLUG}"
        / "cells.with_activity.json"
    )
    primary.unlink()

    with pytest.raises(
        publication.StrategyPublicationError,
        match="primary cell is not in the publisher checkout",
    ):
        validate_system_one_tree(repo, selection_path)


def test_system_one_primary_cell_digest_is_pinned(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The boundary rebuilds the whole evidence state from the primary cell
    # the catalog binds, so a primary cell that changed after the run no
    # longer reproduces the sealed state.
    repo, selection_path = system_one_tree(tmp_path, monkeypatch)
    primary = (
        repo
        / "records"
        / "thesis-analyst"
        / "2029-12-31"
        / f"2029-12-31t00-00-00z-primary-{SLUG}"
        / "cells.with_activity.json"
    )
    cells = json.loads(primary.read_text())
    cells[0]["pointEstimate"] = 1.5
    primary.write_text(json.dumps(cells, indent=2) + "\n")

    with pytest.raises(
        publication.StrategyPublicationError,
        match="state is not the evidence the trusted inputs produce",
    ):
        validate_system_one_tree(repo, selection_path)


def test_system_one_cells_are_custody_bound(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(tmp_path, monkeypatch)
    cells_path = repo.joinpath(*SYSTEM_ONE_RUN_PREFIX.parts, "cells.with_activity.json")
    cells = json.loads(cells_path.read_text())
    cells[0]["pointEstimate"] = cells[0]["ciHigh"]
    cells_path.write_text(json.dumps(cells, indent=2) + "\n")

    with pytest.raises(
        publication.StrategyPublicationError, match="custody verification failed"
    ):
        validate_system_one_tree(repo, selection_path)


def test_suite_lanes_accept_a_null_system_one_key(tmp_path: pathlib.Path) -> None:
    selection_path = write_selection(tmp_path)
    selection = json.loads(selection_path.read_text())
    slug_map = {target()["catalogSlug"]: target()}

    suite = suite_payload(selection_path)
    suite["lanes"]["systemOne"] = None
    publication._validate_suite_shape(
        suite, SUITE, selection, selection_path, slug_map
    )

    suite = suite_payload(selection_path)
    suite["lanes"]["systemOne"] = {
        "batchManifest": (
            "records/thesis-analyst/batches/2030-01-10/strategy-123-a1-system-one.json"
        ),
        "backend": "adapter",
        "model": "gpt-5.6-terra",
    }
    with pytest.raises(
        publication.StrategyPublicationError,
        match="unexpectedly has a system one lane",
    ):
        publication._validate_suite_shape(
            suite, SUITE, selection, selection_path, slug_map
        )


def staged_system_one_cell(repo: pathlib.Path) -> tuple[dict, dict]:
    manifest = json.loads(
        repo.joinpath(*SYSTEM_ONE_RUN_PREFIX.parts, "manifest.json").read_text()
    )
    cells = json.loads(
        repo.joinpath(
            *SYSTEM_ONE_RUN_PREFIX.parts, "cells.with_activity.json"
        ).read_text()
    )
    return manifest, cells[0]


def restage_system_one_cell(repo: pathlib.Path, cell: dict) -> None:
    """Re-write the normalized record so a tamper reaches the recomputation."""

    normalized = {
        key: value
        for key, value in cell.items()
        if key not in {"model", "activityLog"}
    }
    repo.joinpath(*SYSTEM_ONE_RUN_PREFIX.parts, "normalized_cells.json").write_text(
        json.dumps([normalized], indent=2) + "\n"
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda cell: cell["thresholdLadder"]["cumulativeProbabilities"].__setitem__(
                7, 0.5
            ),
            "not the monotonized response",
        ),
        (
            lambda cell: cell["thresholdLadder"][
                "rawCumulativeProbabilities"
            ].__setitem__(0, 0.0),
            "differs from the recorded response",
        ),
        (
            lambda cell: cell.__setitem__("pointEstimate", cell["ciHigh"]),
            "pointEstimate is not the interpolated ladder",
        ),
        (
            lambda cell: cell["thresholdLadder"].__setitem__(
                "monotonization", "sorted_v1"
            ),
            "declares another monotonization",
        ),
        (
            lambda cell: cell.__setitem__("promptMode", "ladder_v2"),
            "cell prompt mode differs from lane",
        ),
        (
            lambda cell: cell["thresholdLadder"]["thresholds"].__setitem__(0, -99.0),
            "differ from the trusted ladder",
        ),
    ],
)
def test_system_one_revalidation_recomputes_the_published_ladder(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
    message: str,
) -> None:
    # The boundary never takes the sealed ladder on trust: it rebuilds the
    # questions, the monotone CDF and the interpolated forecast from the
    # recorded state and the recorded raw response.
    repo, _ = system_one_tree(tmp_path, monkeypatch)
    manifest, cell = staged_system_one_cell(repo)
    mutate(cell)

    restage_system_one_cell(repo, cell)

    with pytest.raises(publication.StrategyPublicationError, match=message):
        publication._revalidate_system_one_run(
            repo,
            SYSTEM_ONE_RUN_PREFIX,
            manifest,
            cell,
            target_context(),
            ledger_rows(),
        )


def test_system_one_published_cell_must_be_its_normalized_record(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = system_one_tree(tmp_path, monkeypatch)
    manifest, cell = staged_system_one_cell(repo)
    cell["pointEstimate"] = cell["ciHigh"]

    with pytest.raises(
        publication.StrategyPublicationError,
        match="differs from its normalized record",
    ):
        publication._revalidate_system_one_run(
            repo,
            SYSTEM_ONE_RUN_PREFIX,
            manifest,
            cell,
            target_context(),
            ledger_rows(),
        )


def test_system_one_revalidation_accepts_the_sealed_run(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = system_one_tree(tmp_path, monkeypatch)
    manifest, cell = staged_system_one_cell(repo)

    publication._revalidate_system_one_run(
        repo, SYSTEM_ONE_RUN_PREFIX, manifest, cell, target_context(), ledger_rows()
    )

    ladder = cell["thresholdLadder"]
    # Pool adjacent violators had something to do: the recorded answers are
    # not monotone, the published ladder is.
    assert ladder["rawCumulativeProbabilities"] == RAW_NOULS
    assert ladder["cumulativeProbabilities"] != RAW_NOULS
    assert ladder["cumulativeProbabilities"] == sorted(
        ladder["cumulativeProbabilities"]
    )


@pytest.mark.parametrize(
    ("key", "value"), [("backend", "typesafe"), ("model", "gpt-5.6-luna")]
)
def test_system_one_batch_echo_must_be_the_trusted_forecaster(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    # The suite runner echoes the lane's backend and model onto the batch
    # header; a false echo is a false record even though the runs are what
    # the boundary binds.
    repo, selection_path = system_one_tree(tmp_path, monkeypatch)
    batch_path = repo.joinpath(*SYSTEM_ONE_BATCH.parts)
    batch = json.loads(batch_path.read_text())
    batch[key] = value
    batch_path.write_text(json.dumps(batch, indent=2) + "\n")

    with pytest.raises(
        publication.StrategyPublicationError,
        match=f"batch {key} differs from its trusted lane",
    ):
        validate_system_one_tree(repo, selection_path)


def test_system_one_lane_carries_a_failed_run(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A target with too little history fails closed in the state phase, before
    # any backend call, so the run seals without a command. The lane still has
    # to carry that record across the boundary.
    repo = tmp_path / "repo"
    repo.mkdir()
    selection_path = write_system_one_selection(tmp_path)
    manifest_path = run_system_one(
        repo,
        monkeypatch,
        cell=primary_cell(history_count=2),
        ledger=[],
        expect_ok=False,
    )
    manifest = json.loads(manifest_path.read_text())
    assert manifest["error"]["phase"] == "state"
    assert [ref["artifactType"] for ref in manifest["artifacts"]] == [
        "system_one_state",
        "error",
        "manifest",
    ]
    write_system_one_batch(repo, manifest_path)
    write_system_one_suite(repo, selection_path)
    monkeypatch.setattr(publication, "_validate_source_sha", lambda *_a, **_k: None)
    monkeypatch.setattr(
        publication.docket, "validate_target_registration", lambda *_a, **_k: {}
    )

    exact, prefixes = validate_system_one_tree(repo, selection_path)

    assert exact == {SYSTEM_ONE_SUITE_PATH, SYSTEM_ONE_BATCH}
    assert prefixes == {SYSTEM_ONE_RUN_PREFIX}


def test_failed_system_one_run_still_binds_the_trusted_forecaster(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    selection_path = write_system_one_selection(tmp_path, model="gpt-5.6-terra")
    manifest_path = run_system_one(
        repo,
        monkeypatch,
        model="gpt-5.6-luna",
        cell=primary_cell(history_count=2),
        ledger=[],
        expect_ok=False,
    )
    write_system_one_batch(repo, manifest_path)
    write_system_one_suite(repo, selection_path)
    monkeypatch.setattr(publication, "_validate_source_sha", lambda *_a, **_k: None)
    monkeypatch.setattr(
        publication.docket, "validate_target_registration", lambda *_a, **_k: {}
    )

    with pytest.raises(
        publication.StrategyPublicationError,
        match="model differs from the trusted request",
    ):
        validate_system_one_tree(repo, selection_path)


def test_only_a_state_phase_failure_may_omit_its_command(
    tmp_path: pathlib.Path,
) -> None:
    manifest_relative = SYSTEM_ONE_RUN_PREFIX / "manifest.json"
    state_failure = {
        "ok": False,
        "error": {"phase": "state", "message": "insufficient_history"},
        "artifacts": [],
    }
    assert (
        publication._system_one_command(tmp_path, manifest_relative, state_failure)
        is None
    )

    for manifest in (
        {"ok": True, "error": None, "artifacts": []},
        {
            "ok": False,
            "error": {"phase": "backend", "message": "call failed"},
            "artifacts": [],
        },
    ):
        with pytest.raises(
            publication.StrategyPublicationError, match="lacks its recorded command"
        ):
            publication._system_one_command(tmp_path, manifest_relative, manifest)


def test_system_one_command_must_live_in_its_own_run(tmp_path: pathlib.Path) -> None:
    manifest = {
        "ok": True,
        "error": None,
        "artifacts": [
            {
                "artifactType": "command",
                "path": "records/thesis-analyst/2030-01-10/other-run/command.json",
            }
        ],
    }

    with pytest.raises(
        publication.StrategyPublicationError, match="outside its exact run"
    ):
        publication._system_one_command(
            tmp_path, SYSTEM_ONE_RUN_PREFIX / "manifest.json", manifest
        )


# --- the boundary rebuilds the evidence, it does not read it ----------------


def test_a_run_that_saw_forged_history_never_publishes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The generate job is unprivileged: it can write any state it likes into
    # its own sealed run. The boundary rebuilds the state from the trusted
    # target, the catalog primary cell and the pinned ledger instead of
    # reading the one that was staged.
    trusted_history_rows = system_one.history_rows
    monkeypatch.setattr(
        system_one,
        "history_rows",
        lambda cell: [
            {**row, "value": row["value"] + 1000}
            for row in trusted_history_rows(cell)
        ],
    )
    repo, selection_path = system_one_tree(tmp_path, monkeypatch, run_model="gpt-5.6-terra")
    staged = json.loads(
        repo.joinpath(*SYSTEM_ONE_RUN_PREFIX.parts, "state.json").read_text()
    )
    assert staged["historicalContext"]["rows"][0]["value"] > 1000

    monkeypatch.setattr(system_one, "history_rows", trusted_history_rows)

    with pytest.raises(
        publication.StrategyPublicationError,
        match="state is not the evidence the trusted inputs produce",
    ):
        validate_system_one_tree(repo, selection_path)


def test_a_forged_ladder_never_publishes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted_build_ladder = system_one.build_ladder

    def shifted(**kwargs):
        ladder = trusted_build_ladder(**kwargs)
        return {
            **ladder,
            "center": ladder["center"] + 1000,
            "thresholds": [value + 1000 for value in ladder["thresholds"]],
        }

    monkeypatch.setattr(system_one, "build_ladder", shifted)
    repo, selection_path = system_one_tree(tmp_path, monkeypatch, run_model="gpt-5.6-terra")
    staged = json.loads(
        repo.joinpath(*SYSTEM_ONE_RUN_PREFIX.parts, "questions.json").read_text()
    )
    assert staged["center"] > 1000

    monkeypatch.setattr(system_one, "build_ladder", trusted_build_ladder)

    with pytest.raises(
        publication.StrategyPublicationError,
        match="thresholds differ from the trusted ladder",
    ):
        validate_system_one_tree(repo, selection_path)


def test_a_run_that_saw_a_forged_ledger_never_publishes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forged = [
        {**row, "value": row["value"] + 1000}
        for row in ledger_rows()
    ]
    repo = tmp_path / "repo"
    repo.mkdir()
    selection_path = write_system_one_selection(tmp_path)
    manifest_path = run_system_one(repo, monkeypatch, ledger=forged)
    write_system_one_batch(repo, manifest_path)
    write_system_one_suite(repo, selection_path)
    monkeypatch.setattr(publication, "_validate_source_sha", lambda *_a, **_k: None)
    monkeypatch.setattr(
        publication.docket, "validate_target_registration", lambda *_a, **_k: {}
    )
    pinned = write_ledger(tmp_path, ledger_rows())

    with pytest.raises(
        publication.StrategyPublicationError,
        match="state is not the evidence the trusted inputs produce",
    ):
        validate_system_one_tree(repo, selection_path, pinned)


def test_a_system_one_suite_without_the_pinned_ledger_is_refused(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(tmp_path, monkeypatch)

    with pytest.raises(
        publication.StrategyPublicationError, match="requires the pinned ledger"
    ):
        publication.validate_tree(
            repo,
            SYSTEM_ONE_SUITE_PATH,
            selection_path,
            publish_validated_at=PUBLISH_VALIDATED,
            exact_source=True,
        )


def test_a_comparison_lane_run_is_not_an_acceptable_primary_cell(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Strategy lanes write runs for the same slug into the same tree. Only
    # the run the published catalog cites is this target's evidence.
    repo = tmp_path / "repo"
    repo.mkdir()
    selection_path = write_system_one_selection(tmp_path)
    write_primary_run(repo, primary_cell())
    comparison = write_comparison_run(repo, primary_cell())
    trusted_catalog_primary_cell = system_one.catalog_primary_cell
    monkeypatch.setattr(
        system_one,
        "catalog_primary_cell",
        lambda slug, root=None: comparison / "cells.with_activity.json",
    )
    manifest_path = run_system_one(repo, monkeypatch)
    staged = json.loads(
        repo.joinpath(*SYSTEM_ONE_RUN_PREFIX.parts, "state.json").read_text()
    )
    assert "ladder-v2" in staged["primaryCellProvenance"]["cellPath"]
    write_system_one_batch(repo, manifest_path)
    write_system_one_suite(repo, selection_path)
    monkeypatch.setattr(publication, "_validate_source_sha", lambda *_a, **_k: None)
    monkeypatch.setattr(
        publication.docket, "validate_target_registration", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        system_one, "catalog_primary_cell", trusted_catalog_primary_cell
    )

    with pytest.raises(
        publication.StrategyPublicationError,
        match="state is not the evidence the trusted inputs produce",
    ):
        validate_system_one_tree(repo, selection_path)


def test_a_slug_the_catalog_does_not_bind_never_publishes(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, selection_path = system_one_tree(tmp_path, monkeypatch)
    (repo / "site" / "src" / "data" / "forecast-examples" / "test-wave.ts").unlink()
    # The catalog is read once per process; the boundary is a fresh process
    # in the workflow, so drop what this one cached.
    system_one._CATALOG_CACHE.clear()

    with pytest.raises(
        publication.StrategyPublicationError,
        match="catalog binds no primary cell",
    ):
        validate_system_one_tree(repo, selection_path)
