from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import docket_publication  # noqa: E402
import register_targets  # noqa: E402
from generate_ledger_targets import generated_entry_for  # noqa: E402
from strategy_targets import (  # noqa: E402
    GENERATED_TARGETS_RELATIVE,
    StrategyTargetError,
    ensure_open,
    published_resolution_date,
    published_target,
    registrations_by_slug,
    select_targets,
    selection_hash,
    stamp_artifact,
    verify_artifact,
    verify_selection,
)

OPEN_SLUG = "australia-cpi-annual-rate-july-2026"
OPEN_DATA_POINT = "abs.cpi.all_groups.yoy.2026-07.first_print"
ACTC_SLUG = "additional-child-tax-credit-total-claims-ty2027-threshold-one-dollar"


def head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def empty_ledger(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "official_observations.jsonl"
    path.write_text("")
    return path


def selection(
    tmp_path: pathlib.Path,
    *,
    slug: str = OPEN_SLUG,
    selected_at: str = "2026-07-10T07:00:00Z",
    ledger: pathlib.Path | None = None,
) -> dict:
    return select_targets(
        root=ROOT,
        source_sha=head(),
        selected_at_utc=selected_at,
        checked_at_utc=selected_at,
        workflow={"repository": "example/thesis", "runId": 123, "runAttempt": 1},
        requested_slugs=[slug],
        auto_select=False,
        max_targets=1,
        suite="both",
        ledger_path=ledger or empty_ledger(tmp_path),
        ledger_repository="PolicyEngine/chronicle",
        ledger_branch="codex/thesis-ledger-facts",
        ledger_logical_path="ledger/official_observations.jsonl",
        ledger_repository_commit="a" * 40,
        ledger_blob_sha="b" * 40,
    )


def test_selector_resolves_one_published_v2_target_and_replays(
    tmp_path: pathlib.Path,
) -> None:
    ledger = empty_ledger(tmp_path)
    payload = selection(tmp_path, ledger=ledger)

    assert payload["schemaVersion"] == "thesis_strategy_selection_v1"
    assert payload["sourceSha"] == head()
    assert payload["targets"][0]["catalogSlug"] == OPEN_SLUG
    assert payload["targets"][0]["comparisonTarget"] is True
    assert payload["targets"][0]["registrationCommit"] == (
        "f2738042716881427217caa9c3c13aa4ca8783e5"
    )
    target = payload["targets"][0]
    # The published forecast's resolver date rides separately; the trusted
    # target mirrors the registration's date fields with exact presence, and
    # this v2 release-calendar contract binds no resolutionDate.
    assert target["publishedResolutionDate"] == "2026-08-26"
    assert "resolutionDate" not in target
    assert "resolutionDateBasis" not in target
    assert target["expectedReleaseWindow"] == {
        "start": "2026-08-25",
        "end": "2026-09-02",
    }
    assert target["expectedReleaseWindow"] == (
        target["sourceBinding"]["expectedReleaseWindow"]
    )
    assert target["targetRegistrationPath"].startswith("records/targets/")
    assert payload["localResolutionEvidence"]["resolvedDataPointIds"] == []
    assert payload["ledgerEvidence"]["resolvedDataPointIds"] == []
    assert payload["selectionSetHash"] == selection_hash(payload)
    assert "billSelection" not in payload
    assert "billSlug" not in payload["request"]
    assert "billSeries" not in payload["request"]

    stamped = stamp_artifact(
        payload,
        artifact_id=456,
        artifact_name="strategy-selection-probe-123-1",
        artifact_digest="c" * 64,
        artifact_created_at_utc="2026-07-10T07:01:00Z",
    )
    verify_selection(stamped, root=ROOT, ledger_path=ledger)


def test_selector_rejects_unknown_unpublished_resolved_and_release_day(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(StrategyTargetError, match="unknown catalog slug"):
        selection(tmp_path, slug="definitely-not-a-catalog-target")

    with pytest.raises(StrategyTargetError, match="not contemporaneous"):
        selection(tmp_path, slug="ons-cpi-annual-rate-june-2026")

    resolved = tmp_path / "resolved.jsonl"
    resolved.write_text(json.dumps({"source_record_id": OPEN_DATA_POINT}) + "\n")
    with pytest.raises(StrategyTargetError, match="pinned official ledger"):
        selection(tmp_path, ledger=resolved)

    with pytest.raises(StrategyTargetError, match="release day"):
        selection(tmp_path, selected_at="2026-08-26T00:00:00Z")


def test_selector_rejects_registered_but_unpublished_targets(
    tmp_path: pathlib.Path,
) -> None:
    # Pick a registered-but-unpublished slug from live state: hardcoding one
    # broke the moment that target published (the data-state-literal trap).
    # Split from the combined rejection test so its skip cannot swallow the
    # other cases (Sol review P2-10).
    registrations = registrations_by_slug(ROOT)
    generated = ROOT.joinpath(
        "site/src/data/ledger-targets.generated.ts"
    ).read_text()

    def is_preregistered(data_point_id: str) -> bool:
        match = generated_entry_for(generated, data_point_id)
        entry = match.group(0) if match else ""
        return 'registrationState: "preregistered"' in entry

    unpublished = next(
        (
            slug
            for slug, rows in sorted(registrations.items())
            if len(rows) == 1
            and is_preregistered(rows[0]["contract"]["dataPointId"])
        ),
        None,
    )
    if unpublished is None:
        pytest.skip("every registered target is currently published")
    with pytest.raises(StrategyTargetError, match="not published"):
        selection(tmp_path, slug=unpublished)


def test_selector_requires_registration_commit_strictly_before_selection(
    tmp_path: pathlib.Path,
) -> None:
    with pytest.raises(StrategyTargetError, match="strictly predate"):
        selection(tmp_path, selected_at="2026-07-10T05:03:57Z")


def test_selector_artifact_witness_and_latest_open_checks(
    tmp_path: pathlib.Path,
) -> None:
    payload = stamp_artifact(
        selection(tmp_path),
        artifact_id=456,
        artifact_name="strategy-selection-probe-123-1",
        artifact_digest="d" * 64,
        artifact_created_at_utc="2026-07-10T07:01:00Z",
    )
    artifact = {
        "id": 456,
        "name": "strategy-selection-probe-123-1",
        "digest": f"sha256:{'d' * 64}",
        "created_at": "2026-07-10T07:01:00Z",
        "expired": False,
        "workflow_run": {"id": 123},
    }
    verify_artifact(payload, artifact)

    tampered = json.loads(json.dumps(artifact))
    tampered["workflow_run"]["id"] = 999
    with pytest.raises(StrategyTargetError, match="different workflow run"):
        verify_artifact(payload, tampered)

    missing_expiry = json.loads(json.dumps(artifact))
    missing_expiry.pop("expired")
    with pytest.raises(StrategyTargetError, match="unexpired status"):
        verify_artifact(payload, missing_expiry)

    resolved = tmp_path / "latest-resolved.jsonl"
    resolved.write_text(json.dumps({"source_record_id": OPEN_DATA_POINT}) + "\n")
    with pytest.raises(StrategyTargetError, match="became resolved"):
        ensure_open(
            payload,
            root=ROOT,
            ledger_path=resolved,
            checked_at_utc="2026-07-10T07:02:00Z",
        )


def test_selection_hash_rejects_boolean_number_substitution(
    tmp_path: pathlib.Path,
) -> None:
    payload = selection(tmp_path)
    payload["request"]["maxTargets"] = True
    assert selection_hash(payload) != payload["selectionSetHash"]


def test_require_pre_cutover_commit_semantics(tmp_path: pathlib.Path) -> None:
    import strategy_targets as module
    from strategy_targets import require_pre_cutover_commit

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.com",
                *args,
            ],
            cwd=repo,
            text=True,
        ).strip()

    git("init")
    (repo / "a").write_text("a\n")
    git("add", "a")
    git("commit", "-m", "first")
    first = git("rev-parse", "HEAD")
    (repo / "b").write_text("b\n")
    git("add", "b")
    git("commit", "-m", "cutover")
    cutover = git("rev-parse", "HEAD")

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(module, "V3_REGISTRATION_CUTOVER_COMMIT", cutover)
        require_pre_cutover_commit(repo, first)
        with pytest.raises(StrategyTargetError, match="strictly predate"):
            require_pre_cutover_commit(repo, cutover)
        monkey.setattr(module, "V3_REGISTRATION_CUTOVER_COMMIT", first)
        with pytest.raises(StrategyTargetError, match="strictly predate"):
            require_pre_cutover_commit(repo, cutover)
    finally:
        monkey.undo()


def test_selection_binds_ladder_prompt_mode_sparsely(
    tmp_path: pathlib.Path,
) -> None:
    ledger = empty_ledger(tmp_path)

    # Default selections stay byte-identical to the pre-ladder_v2 shape so
    # historical selections keep re-verifying.
    default = selection(tmp_path, ledger=ledger)
    assert "ladderPromptMode" not in default["request"]

    v2 = select_targets(
        root=ROOT,
        source_sha=head(),
        selected_at_utc="2026-07-10T07:00:00Z",
        checked_at_utc="2026-07-10T07:00:00Z",
        workflow={"repository": "example/thesis", "runId": 124, "runAttempt": 1},
        requested_slugs=[OPEN_SLUG],
        auto_select=False,
        max_targets=1,
        suite="both",
        ladder_prompt_mode="ladder_v2",
        ledger_path=ledger,
        ledger_repository="PolicyEngine/chronicle",
        ledger_branch="codex/thesis-ledger-facts",
        ledger_logical_path="ledger/official_observations.jsonl",
        ledger_repository_commit="a" * 40,
        ledger_blob_sha="b" * 40,
    )
    assert v2["request"]["ladderPromptMode"] == "ladder_v2"
    assert v2["selectionSetHash"] == selection_hash(v2)

    # The trusted verify path replays the mode.
    stamped = stamp_artifact(
        v2,
        artifact_id=457,
        artifact_name="strategy-selection-probe-124-1",
        artifact_digest="d" * 64,
        artifact_created_at_utc="2026-07-10T07:01:00Z",
    )
    verify_selection(stamped, root=ROOT, ledger_path=ledger)

    with pytest.raises(StrategyTargetError, match="ladder prompt mode"):
        select_targets(
            root=ROOT,
            source_sha=head(),
            selected_at_utc="2026-07-10T07:00:00Z",
            checked_at_utc="2026-07-10T07:00:00Z",
            workflow={
                "repository": "example/thesis",
                "runId": 125,
                "runAttempt": 1,
            },
            requested_slugs=[OPEN_SLUG],
            auto_select=False,
            max_targets=1,
            suite="both",
            ladder_prompt_mode="ladder_v3",
            ledger_path=ledger,
            ledger_repository="PolicyEngine/chronicle",
            ledger_branch="codex/thesis-ledger-facts",
            ledger_logical_path="ledger/official_observations.jsonl",
            ledger_repository_commit="a" * 40,
            ledger_blob_sha="b" * 40,
        )


def _published(
    slug: str,
    selected_at: str,
    *,
    allow_conditional: bool = False,
    registrations: dict | None = None,
    generated: str | None = None,
) -> dict:
    import datetime as dt

    if generated is None:
        generated = ROOT.joinpath(*GENERATED_TARGETS_RELATIVE.parts).read_text()
    return published_target(
        ROOT,
        slug,
        registrations if registrations is not None else registrations_by_slug(ROOT),
        generated,
        head(),
        dt.datetime.fromisoformat(selected_at.replace("Z", "+00:00")),
        allow_conditional=allow_conditional,
    )


@pytest.mark.parametrize(
    ("slug", "registration_kind"),
    [
        # v3 release-calendar contract: no resolutionDate in the snapshot.
        # Actions run 35524670779 (2026-09-20) was blocked on exactly this
        # target because the selector copied the published date into
        # resolutionDate.
        ("unemployment-rate-september-2026", "release-calendar"),
        # v3 resolve-by-bound contract: resolutionDate is the registered
        # bound. Actions run 35525381224 was blocked on this one because the
        # target lacked the top-level expectedReleaseWindow.
        ("us-natural-gas-vented-flared-2025", "resolve-by-bound"),
    ],
)
def test_selected_target_passes_publisher_registration_projection(
    slug: str, registration_kind: str
) -> None:
    target = _published(slug, "2026-09-21T00:00:00Z")
    registration = registrations_by_slug(ROOT)[slug][0]
    contract = registration["contract"]

    assert target["comparisonTarget"] is True
    assert target["publishedResolutionDate"]
    assert published_resolution_date(target).isoformat() == (
        target["publishedResolutionDate"]
    )
    assert target["expectedReleaseWindow"] == (
        contract["sourceBinding"]["expectedReleaseWindow"]
    )
    if registration_kind == "release-calendar":
        assert "resolutionDate" not in contract
        assert "resolutionDate" not in target
        assert "resolutionDateBasis" not in target
    else:
        assert contract["resolutionDateBasis"] == "resolve-by-bound"
        assert target["resolutionDateBasis"] == "resolve-by-bound"
        assert target["resolutionDate"] == contract["resolutionDate"]
        assert target["publishedResolutionDate"] == contract["resolutionDate"]

    # The exact checks the strategy publisher applies to a batch target.
    register_targets.validate_target_resolution_projection(
        contract, target, label=registration["relative"]
    )
    docket_publication.validate_target_registration(ROOT, target)


def test_selector_refuses_published_date_that_contradicts_a_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import strategy_targets as module

    slug = "us-natural-gas-vented-flared-2025"
    original = module.block_value

    def contradicting(block: str, key: str):
        value = original(block, key)
        if key == "resolutionDate" and value == "2026-10-31":
            return "2026-10-30"
        return value

    monkeypatch.setattr(module, "block_value", contradicting)
    with pytest.raises(StrategyTargetError, match="resolutionDate"):
        _published(slug, "2026-09-21T00:00:00Z")


def test_selector_fails_closed_on_the_publisher_projection_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The selector runs the publisher's registration projection itself so an
    # ineligible target is refused in the free select job; its RegistrationError
    # surfaces as the selector's own error type with the message intact.
    import strategy_targets as module

    def refuse(contract, target, *, label):
        raise register_targets.RegistrationError(
            f"target registration contract mismatch for resolutionDate: {label}"
        )

    monkeypatch.setattr(module, "validate_target_resolution_projection", refuse)
    with pytest.raises(
        StrategyTargetError,
        match="contract mismatch for resolutionDate: records/targets/",
    ):
        _published("unemployment-rate-september-2026", "2026-09-21T00:00:00Z")


def test_published_resolution_date_requires_the_published_field() -> None:
    with pytest.raises(StrategyTargetError, match="lacks publishedResolutionDate"):
        published_resolution_date({"catalogSlug": "x", "resolutionDate": "2030-01-01"})
    with pytest.raises(StrategyTargetError, match="invalid publishedResolutionDate"):
        published_resolution_date(
            {"catalogSlug": "x", "publishedResolutionDate": "2030-13-01"}
        )


def bill_selection(tmp_path: pathlib.Path, **overrides) -> dict:
    options = dict(
        root=ROOT,
        source_sha=head(),
        selected_at_utc="2026-09-21T19:00:00Z",
        workflow={"repository": "example/thesis", "runId": 999, "runAttempt": 1},
        requested_slugs=[],
        auto_select=False,
        max_targets=2,
        suite="ladder",
        bill_slug="s3596-119",
        bill_series="irs.actc.total_claims",
        ledger_path=empty_ledger(tmp_path),
        ledger_repository="PolicyEngine/chronicle",
        ledger_branch="codex/thesis-ledger-facts",
        ledger_logical_path="ledger/official_observations.jsonl",
        ledger_repository_commit="a" * 40,
        ledger_blob_sha="b" * 40,
    )
    options.update(overrides)
    return select_targets(**options)


@pytest.fixture
def recorded_bill_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    # No subprocess needed in selector tests; bill-plan tests separately cover
    # the trusted registry loader and its exact status/text/deadline checks.
    import bill_forecast_plan as plan

    reviewed = plan.build_bill_selection(ROOT, "s3596-119", "irs.actc.total_claims")
    monkeypatch.setattr(
        plan,
        "load_conditions",
        lambda root: [
            {
                "conditionId": arm["conditionId"],
                "status": "open",
                "resolvesBy": pair["conditionDeadline"],
                "matchStrings": [arm["conditional"]],
            }
            for pair in reviewed["pairs"]
            for arm in pair["arms"]
        ],
    )


def test_bill_selection_preserves_full_context_and_reverifies(
    tmp_path: pathlib.Path,
    recorded_bill_conditions: None,
) -> None:
    import strategy_targets as module

    payload = bill_selection(tmp_path)
    assert len(payload["targets"]) == 2
    assert payload["request"]["catalogSlugs"] == []
    assert payload["request"]["billSlug"] == "s3596-119"
    entry = next(
        row
        for row in json.loads((ROOT / "scripts/docket_series.json").read_text())[
            "series"
        ]
        if row.get("series") == "irs.actc.total_claims" and row.get("period") == "2027"
    )
    registrations = registrations_by_slug(ROOT)
    for target in payload["targets"]:
        registration = next(
            row
            for row in registrations[target["catalogSlug"]]
            if row["relative"] == target["targetRegistrationPath"]
        )
        contract = registration["contract"]
        assert target["anchors"] == entry["extras"]["anchors"]
        assert target["conditional"] == contract["conditional"]
        assert target["conditionDeadline"] == contract["conditionDeadline"]
        assert target["resolutionDate"] == "2029-12-31"
        assert target["resolutionDateBasis"] == "resolve-by-bound"
        context = module.conditional_comparison_context(ROOT, target)
        register_targets.require_conditional_docket_template(
            contract,
            [entry],
            target["registeredAtUtc"],
            batch_target=context,
        )
        # Exercise the real privileged publisher contract/ancestry validation,
        # including the narrow pre-basis IRS registration compatibility.
        docket_publication.validate_target_registration(
            ROOT,
            context,
            run_started_at="2026-09-21T19:01:00Z",
            require_git_binding=True,
            allow_pre_cutover_v2=True,
        )
    verify_selection(payload, root=ROOT, ledger_path=empty_ledger(tmp_path))
    ensure_open(
        payload,
        root=ROOT,
        ledger_path=empty_ledger(tmp_path),
        checked_at_utc="2026-09-22T00:00:00Z",
    )


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"max_targets": 1}, "atomically"),
        ({"requested_slugs": [ACTC_SLUG]}, "without catalog slugs"),
        ({"auto_select": True}, "without catalog slugs"),
        ({"suite": "both"}, "ladder suite"),
        ({"bill_slug": ""}, "billSeries requires"),
    ],
)
def test_bill_selection_rejects_partial_or_mixed_requests(
    tmp_path: pathlib.Path,
    recorded_bill_conditions: None,
    overrides: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        bill_selection(tmp_path, **overrides)


def test_conditional_slugs_remain_ineligible_without_bill_plan() -> None:
    with pytest.raises(
        StrategyTargetError, match="conditional targets are not selectable"
    ):
        _published(ACTC_SLUG, "2026-09-21T19:00:00Z")


@pytest.mark.parametrize(
    "slug, published_hash",
    [
        (
            ACTC_SLUG,
            "6978365a2924b850a9516b49451ed3e07b2bb14321ea908344ce17744296f5e6",
        ),
        (
            "additional-child-tax-credit-total-claims-ty2027-current-law",
            "b92e9752beaf38a9e2e735c5066e7c741e29436546e7fab2c8d0568f05355909",
        ),
    ],
)
def test_published_actc_binding_selects_exact_historical_registration(
    slug: str, published_hash: str
) -> None:
    registrations = registrations_by_slug(ROOT)
    original_paths = [row["relative"] for row in registrations[slug]]
    # Both August 3 attempts are real, canonical v3 registrations. The
    # published forecast binds the later ledger pin, regardless of hash order.
    assert len(original_paths) == 2
    target = _published(
        slug,
        "2026-09-21T19:00:00Z",
        allow_conditional=True,
        registrations=registrations,
    )
    assert target["targetContentHash"] == published_hash
    assert target["targetRegistrationPath"] == (
        f"records/targets/2026-08-03-{published_hash}.json"
    )
    assert target["registeredAtUtc"] == "2026-08-03T20:13:09Z"
    assert target["registrationCommit"] == "a4f59c018641c8d772975263735424cb5d46bb25"
    assert [row["relative"] for row in registrations[slug]] == original_paths


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_selector_requires_exactly_one_published_registration_match(
    mutation: str,
) -> None:
    registrations = registrations_by_slug(ROOT)
    rows = registrations[ACTC_SLUG]
    published = next(
        row
        for row in rows
        if row["targetContentHash"]
        == "6978365a2924b850a9516b49451ed3e07b2bb14321ea908344ce17744296f5e6"
    )
    if mutation == "missing":
        rows.remove(published)
    else:
        rows.append(dict(published))
    with pytest.raises(StrategyTargetError, match="unique published registration"):
        _published(
            ACTC_SLUG,
            "2026-09-21T19:00:00Z",
            allow_conditional=True,
            registrations=registrations,
        )


@pytest.mark.parametrize(
    "key, value, message",
    [
        ("targetContentHash", "0" * 64, "unique published registration"),
        ("registeredAt", "2026-08-03T20:13:10Z", "unique published registration"),
        ("dataPointId", "unregistered.actc", "unique published registration"),
        ("unit", "count", "differs from registration.*unit"),
    ],
)
def test_published_registration_binding_does_not_relax_contract_checks(
    key: str, value: str, message: str
) -> None:
    from generate_ledger_targets import block_value

    generated = ROOT.joinpath(*GENERATED_TARGETS_RELATIVE.parts).read_text()
    block = generated_entry_for(
        generated, "irs.actc.total_claims.2027.first_print.threshold_one_dollar"
    ).group(0)
    mutated = block.replace(
        f"    {key}: {json.dumps(block_value(block, key))},",
        f"    {key}: {json.dumps(value)},",
    )
    assert mutated != block
    with pytest.raises(StrategyTargetError, match=message):
        _published(
            ACTC_SLUG,
            "2026-09-21T19:00:00Z",
            allow_conditional=True,
            generated=generated.replace(block, mutated),
        )


@pytest.mark.parametrize("duplicate_slug", [False, True])
def test_selector_rejects_ambiguous_generated_publication(
    duplicate_slug: bool,
) -> None:
    generated = ROOT.joinpath(*GENERATED_TARGETS_RELATIVE.parts).read_text()
    block = generated_entry_for(
        generated, "irs.actc.total_claims.2027.first_print.threshold_one_dollar"
    ).group(0)
    duplicate = block
    if not duplicate_slug:
        # A different slug cannot publish a second binding for the same
        # data-point identity either.
        duplicate = block.replace(ACTC_SLUG, "different-actc-slug")
    with pytest.raises(StrategyTargetError, match="unique generated ledger entry"):
        _published(
            ACTC_SLUG,
            "2026-09-21T19:00:00Z",
            allow_conditional=True,
            generated=generated + "\n" + duplicate + "\n",
        )


def test_bill_selection_rejects_missing_sibling(
    tmp_path: pathlib.Path,
    recorded_bill_conditions: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import strategy_targets as module

    original = module.registrations_by_slug

    def missing(root):
        rows = original(root)
        rows.pop(ACTC_SLUG)
        return rows

    monkeypatch.setattr(module, "registrations_by_slug", missing)
    with pytest.raises(StrategyTargetError, match="unique published registration"):
        bill_selection(tmp_path)


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("sibling", "missing a registered conditional sibling"),
        ("premise", "differs from reviewed conditional premise"),
        ("window", "differs from reviewed source release window"),
    ],
)
def test_latest_bill_gate_rejects_changed_selection_context(
    tmp_path: pathlib.Path,
    recorded_bill_conditions: None,
    mutation: str,
    message: str,
) -> None:
    payload = bill_selection(tmp_path)
    if mutation == "sibling":
        payload["targets"].pop()
    elif mutation == "premise":
        payload["targets"][0]["conditional"] += " altered"
    else:
        payload["targets"][0]["sourceBinding"]["expectedReleaseWindow"][
            "start"
        ] = "2030-01-01"
    with pytest.raises(StrategyTargetError, match=message):
        ensure_open(
            payload,
            root=ROOT,
            ledger_path=empty_ledger(tmp_path),
            checked_at_utc="2026-09-22T00:00:00Z",
        )


def test_conditional_deadline_and_source_start_close_before_resolver_bound() -> None:
    from strategy_targets import require_conditional_open

    target = {
        "conditional": "premise",
        "catalogSlug": "example",
        "conditionDeadline": "2030-01-01",
        "sourceBinding": {
            "expectedReleaseWindow": {"start": "2030-02-01", "end": "2030-12-31"}
        },
    }
    with pytest.raises(StrategyTargetError, match="condition deadline"):
        require_conditional_open(
            target, dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)
        )
    target["conditionDeadline"] = "2030-12-01"
    with pytest.raises(StrategyTargetError, match="source release window"):
        require_conditional_open(
            target, dt.datetime(2030, 2, 1, tzinfo=dt.timezone.utc)
        )


@pytest.mark.parametrize("mutation", ["anchors", "unknown"])
def test_publisher_projection_keeps_unknown_and_mutated_prompt_context(
    tmp_path: pathlib.Path,
    recorded_bill_conditions: None,
    mutation: str,
) -> None:
    from strategy_targets import conditional_comparison_context

    payload = bill_selection(tmp_path)
    target = payload["targets"][0]
    if mutation == "anchors":
        target["anchors"]["2023"] = -1
    else:
        target["inventedPromptContext"] = "unreviewed"
    context = conditional_comparison_context(ROOT, target)
    with pytest.raises(docket_publication.PublicationError, match="run context"):
        docket_publication.validate_target_registration(
            ROOT,
            context,
            run_started_at="2026-09-21T19:01:00Z",
            require_git_binding=True,
        )
