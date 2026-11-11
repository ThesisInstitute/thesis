from __future__ import annotations

import hashlib
import json
import pathlib
import stat
import subprocess
import sys
from collections.abc import Mapping
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import strategy_publication as publication  # noqa: E402
from canonical_json import canonical_sha256  # noqa: E402

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
        # A release-calendar registration binds no resolutionDate; the
        # published forecast's resolver date rides separately.
        "publishedResolutionDate": "2030-02-15",
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
                "suiteManifest": SUITE.as_posix(),
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
    suite["lanes"]["ladder"][
        "batchManifest"
    ] = "records/thesis-analyst/batches/2030-01-10/strategy-999-a1-ladder.json"

    with pytest.raises(publication.StrategyPublicationError, match="trusted lane"):
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
        # Comparison cells are graded against the published resolver date.
        "resolutionDate": trusted["publishedResolutionDate"],
        "resolutionSource": trusted["resolutionSource"],
        "resolutionSourceUrl": trusted["resolutionSourceUrl"],
        "resolutionRule": trusted["resolutionRule"],
        **{field: trusted[field] for field in publication.REGISTRATION_FIELDS},
    }
    publication._resolver_equal(cell, trusted)
    cell["resolutionDate"] = "2030-02-16"
    with pytest.raises(
        publication.StrategyPublicationError,
        match="resolutionDate differs from trusted target field "
        "publishedResolutionDate",
    ):
        publication._resolver_equal(cell, trusted)


@pytest.mark.parametrize(
    "field, value",
    [
        ("conditionalOn", None),
        ("conditionalOn", "Different legal premise"),
        ("type", "data"),
        ("type", None),
    ],
)
def test_conditional_comparison_requires_exact_cell_premise_and_type(field, value):
    trusted = {
        **target(),
        "conditional": "The reviewed provision is enacted by the deadline.",
    }
    cell = {
        **{
            key: trusted[key]
            for key in publication.RESOLVER_FIELDS
            if key
            not in {
                "catalogSlug",
                "targetUnit",
                "publishedResolutionDate",
                "resolutionPolicy",
            }
        },
        **{key: trusted[key] for key in publication.REGISTRATION_FIELDS},
        "slug": trusted["catalogSlug"],
        "unit": trusted["targetUnit"],
        "resolutionDate": trusted["publishedResolutionDate"],
        "conditionalOn": trusted["conditional"],
        "type": "conditional",
    }
    publication._resolver_equal(cell, trusted)
    cell[field] = value
    with pytest.raises(publication.StrategyPublicationError, match="conditional"):
        publication._resolver_equal(cell, trusted)


def test_publication_refuses_unreviewed_conditional_selection(tmp_path: pathlib.Path):
    selection = selection_payload()
    selection["targets"][0]["conditional"] = "Model-supplied legal premise"
    selection.pop("selectionSetHash")
    selection["selectionSetHash"] = canonical_sha256(selection)
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(selection))
    with pytest.raises(
        publication.StrategyPublicationError, match="reviewed bill selection"
    ):
        publication._validate_selection(path)


@pytest.mark.parametrize("checkout", [None, "d" * 40])
def test_bounded_strategy_publisher_requires_exact_selected_checkout(
    tmp_path, checkout
):
    trusted = {
        **target(),
        "conditional": "The reviewed premise holds.",
        "resolutionDateBasis": "resolve-by-bound",
    }
    relative = RUN_PREFIX / "manifest.json"
    path = tmp_path.joinpath(*relative.parts)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_analyst_run_manifest_v1",
                "promptMode": "ladder",
                "targetContext": trusted,
                "series": trusted["series"],
                "period": trusted["period"],
                "conditional": trusted["conditional"],
                "checkoutSha": checkout,
            }
        )
    )
    with pytest.raises(
        publication.StrategyPublicationError, match="exact selected checkout"
    ):
        publication._validate_analyst_result(
            tmp_path,
            {"target": trusted, "manifestPath": relative.as_posix()},
            prompt_mode="ladder",
            lower=publication._instant("2030-01-10T12:00:00Z", "lower"),
            upper=publication._instant("2030-01-10T12:04:00Z", "upper"),
            strategy_source_sha="c" * 40,
        )


@pytest.mark.parametrize("bounded", [False, True])
def test_failed_wrong_premise_is_archived_but_cannot_claim_success(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    bounded: bool,
) -> None:
    import run_thesis_analyst

    trusted = {**target(), "conditional": "The exact registered legal premise."}
    if bounded:
        trusted["resolutionDateBasis"] = "resolve-by-bound"
    manifest_relative = RUN_PREFIX / "manifest.json"
    cells_relative = RUN_PREFIX / "cells.with_activity.json"
    manifest_path = tmp_path.joinpath(*manifest_relative.parts)
    manifest_path.parent.mkdir(parents=True)
    cells = [
        {
            "conditionalOn": "A different premise",
            "type": "conditional",
            "runAt": "2030-01-10T12:02:00Z",
            "runStartedAt": "2030-01-10T12:01:00Z",
        }
    ]
    tmp_path.joinpath(*cells_relative.parts).write_text(json.dumps(cells))
    manifest = {
        "schemaVersion": "thesis_analyst_run_manifest_v1",
        "promptMode": "ladder",
        "targetContext": trusted,
        "series": trusted["series"],
        "period": trusted["period"],
        "conditional": trusted["conditional"],
        "checkoutSha": "c" * 40,
        "ok": False,
        "createdAt": "2030-01-10T12:01:00Z",
        "runStartedAt": "2030-01-10T12:01:00Z",
        "cellsPath": cells_relative.as_posix(),
        **{field: trusted[field] for field in publication.REGISTRATION_FIELDS},
    }
    manifest_path.write_text(json.dumps(manifest))
    result = {
        "target": trusted,
        "manifestPath": manifest_relative.as_posix(),
        "ok": False,
        "cellsPath": cells_relative.as_posix(),
        "startedAt": "2030-01-10T12:01:00Z",
        "finishedAt": "2030-01-10T12:03:00Z",
    }
    monkeypatch.setattr(
        publication.docket, "validate_run_file_inventory", lambda *_: None
    )
    monkeypatch.setattr(
        publication.docket, "validate_target_registration", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        publication, "conditional_comparison_context", lambda _root, value: value
    )
    monkeypatch.setattr(
        publication,
        "verify_run",
        lambda _path: SimpleNamespace(
            inventory_status="complete",
            run_mode="analyst",
            run_succeeded=manifest["ok"],
        ),
    )
    validations = []

    def validate_failed(value, **kwargs):
        validations.append((value, kwargs["target_context"]))
        assert kwargs["trusted_strategy_target"] == (trusted if bounded else None)
        assert kwargs["strategy_run_dir"] == manifest_path.parent
        assert kwargs["strategy_run_relative"] == manifest_relative.parent
        return {"ok": False}

    monkeypatch.setattr(run_thesis_analyst, "validate_cells", validate_failed)
    kwargs = dict(
        prompt_mode="ladder",
        lower=publication._instant("2030-01-10T12:00:00Z", "lower"),
        upper=publication._instant("2030-01-10T12:04:00Z", "upper"),
        strategy_source_sha="c" * 40,
    )
    assert publication._validate_analyst_result(tmp_path, result, **kwargs) == (
        manifest_relative,
        "2030-01-10T12:02:00Z",
    )
    assert validations == [(cells, trusted)]
    # Neither the wrapper nor custody can relabel failed output as successful.
    manifest["ok"] = result["ok"] = True
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(publication.StrategyPublicationError, match="conditionalOn"):
        publication._validate_analyst_result(tmp_path, result, **kwargs)


def test_selection_requires_published_resolution_date(tmp_path: pathlib.Path):
    # The pre-2026-09-20 selection shape stored the published date under
    # resolutionDate, which the publisher's registration projection rejects
    # for release-calendar contracts. The trusted selection must now carry
    # publishedResolutionDate; a legacy-shaped target is not silently accepted.
    legacy = selection_payload()
    legacy_target = legacy["targets"][0]
    legacy_target["resolutionDate"] = legacy_target.pop("publishedResolutionDate")
    legacy.pop("selectionSetHash")
    legacy["selectionSetHash"] = canonical_sha256(legacy)
    path = tmp_path / "legacy-selection.json"
    path.write_text(json.dumps(legacy, indent=2) + "\n")

    with pytest.raises(
        publication.StrategyPublicationError,
        match="lacks publishedResolutionDate",
    ):
        publication._validate_selection(path)


def test_ladder_lane_prompt_mode_binds_to_trusted_selection(
    tmp_path: pathlib.Path,
) -> None:
    selection_path = write_selection(tmp_path)
    selection = json.loads(selection_path.read_text())
    slug_map = {target()["catalogSlug"]: target()}

    # A recorded lane mode that matches the trusted default passes shape.
    suite = suite_payload(selection_path)
    suite["lanes"]["ladder"]["promptMode"] = "ladder"
    publication._validate_suite_shape(suite, SUITE, selection, selection_path, slug_map)

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
        publication._validate_suite_shape(suite, SUITE, v2_selection, v2_path, slug_map)

    # ...and passes once it does.
    suite = suite_payload(v2_path)
    suite["lanes"]["ladder"]["promptMode"] = "ladder_v2"
    publication._validate_suite_shape(suite, SUITE, v2_selection, v2_path, slug_map)

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
