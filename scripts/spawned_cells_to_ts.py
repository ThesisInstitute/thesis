#!/usr/bin/env python3
"""Convert spawned-forecast JSON (from thesis.analyst agent runs) into a
ForecastCell TS module, validating the trace-depth contract on the way in.

Usage:
  python3 scripts/spawned_cells_to_ts.py OUT_TS CONST_NAME IN1.json [IN2.json ...]
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Immutable parent of the commit that introduced the 2.5.10 history floor.
# A custody-less run may use the legacy floor only if both its manifest and
# cells are byte-identical to this already-known records tree. Using HEAD here
# would let a later branch commit manufacture a new grandfathered record.
LEGACY_HISTORY_RECORDS_COMMIT = "9668e4a5e6c627704caca6ec9ba518739597a0d5"
PROVENANCE_VALUES = {"ci", "local_operator_attested"}

ALLOWED_UNITS = {
    "count",
    "percent",
    "gbp_billions",
    "usd",
    "usd_billions",
    "usd_millions",
    "usd_monthly",
    "thousands",
    "millions",
    "million_cubic_feet",
    "per_1000_live_births",
    "ratio",
    "minutes",
    "percent_growth",
    "index_points",
}
ALLOWED_COUNTRIES = {"US", "UK", "CA", "AU", "EA", "JP", "BE"}
ALLOWED_TYPES = {"data", "policy", "conditional"}
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REQUIRED = [
    "slug",
    "country",
    "type",
    "title",
    "question",
    "unit",
    "pointEstimate",
    "ciLow",
    "ciHigh",
    "confidence",
    "resolutionDate",
    "resolutionSource",
    "resolutionSourceUrl",
    "resolutionRule",
    "dataPointId",
    "historicalContext",
    "drivers",
    "sourceContext",
    "runAt",
    "reasoning",
]
# The private-source screen (granola, transcripts, meeting notes, private
# meetings, ...) has one source of truth shared with the site's catalog
# test and every other projection, so the refusing side and the enforcing
# side cannot drift.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    from history_floor import (
        agent_version_enforces_history_floor,
        history_floor_errors,
        history_floor_requires_authorization,
        reviewed_history_floor_authorization,
        valid_agent_version,
    )
    from private_source_screen import (
        PRIVATE_SOURCE_MARKER,  # noqa: F401  (re-exported for tests/tools)
        PRIVATE_SOURCE_RE,
        screen_pre_submit_review,
    )
finally:
    sys.path.pop(0)


def private_source_hits(cell: dict) -> list[str]:
    hits = []
    fields = {
        "sourceContext": cell.get("sourceContext"),
        "drivers": cell.get("drivers"),
        "reasoning": cell.get("reasoning"),
        "historicalContext": cell.get("historicalContext"),
        "historyAvailability": cell.get("historyAvailability"),
    }
    for name, value in fields.items():
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if PRIVATE_SOURCE_RE.search(text):
            hits.append(name)
    return hits


def existing_slugs(site_data: pathlib.Path, out_ts: pathlib.Path) -> set[str]:
    slugs = set()
    for f in list(site_data.glob("forecast-examples/*.ts")) + [
        site_data / "forecast-cells.ts"
    ]:
        if f.resolve() == out_ts.resolve():
            continue  # rerunning over our own previous output is not a collision
        # Both key forms: hand-formatted files use `slug:`, this script's
        # own json.dumps output uses `"slug":`. The left boundary keeps
        # suffix keys (relatedSlug:, "oldslug":) out; escaped JSON inside
        # trace strings (\"slug\") cannot match — the backslash breaks
        # the pattern. KNOWN BLINDNESS: slugs constructed dynamically in
        # TS code (OEWS, SNAP) never appear as literals, so this scan is
        # a collision HEURISTIC only — any publication decision must use
        # the evaluated catalog (scripts/dump_published_cells.ts).
        slugs |= set(
            re.findall(r'(?<![A-Za-z0-9_])"?slug"?:\s*"([^"]+)"', f.read_text())
        )
    return slugs


def valid_generation_ticket_context(value: object) -> bool:
    """Accept the runner's nonce context or its sealed manifest projection."""

    if not isinstance(value, dict):
        return False
    ticket_id = value.get("ticketId")
    if not isinstance(ticket_id, str):
        return False
    match = re.fullmatch(r"(?P<day>\d{4}-\d{2}-\d{2})-[0-9a-f]+", ticket_id)
    if match is None:
        return False
    if value.get("ticketPath") != (
        f"records/tickets/{match.group('day')}/{ticket_id}.json"
    ):
        return False
    nonce = value.get("nonce")
    nonce_sha256 = value.get("nonceSha256")
    return bool(
        (isinstance(nonce, str) and re.fullmatch(r"[0-9a-f]{64}", nonce))
        or (
            isinstance(nonce_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", nonce_sha256)
        )
    )


def registration_authenticated_unit(target_context: dict | None) -> str | None:
    """The registration-proven unit for this context, or None.

    Trusting a bare ``targetUnit`` claim would let any forged context
    smuggle an arbitrary unit past ALLOWED_UNITS. The context must name a
    registration snapshot inside ``records/targets`` whose bytes hash to
    the recorded content hash (which the filename must also carry), whose
    single contract binds the same catalog slug when the context names
    one, and whose contract unit equals the claimed targetUnit. Any
    failure returns None and the exploratory allowlist applies unchanged.
    """

    if not isinstance(target_context, dict):
        return None
    claimed = target_context.get("targetUnit")
    relative = target_context.get("targetRegistrationPath")
    content_hash = target_context.get("targetContentHash")
    if not (
        isinstance(claimed, str)
        and claimed
        and isinstance(relative, str)
        and isinstance(content_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", content_hash)
    ):
        return None
    parts = pathlib.PurePosixPath(relative)
    if (
        parts.is_absolute()
        or ".." in parts.parts
        or pathlib.PurePosixPath("records/targets") not in parts.parents
        or not parts.name.endswith(f"-{content_hash}.json")
    ):
        return None
    snapshot_path = ROOT.joinpath(*parts.parts)
    if not snapshot_path.is_file():
        return None
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from register_targets import RegistrationError, registration_content_hash
    finally:
        sys.path.pop(0)
    try:
        snapshot = json.loads(snapshot_path.read_text())
        actual_hash = registration_content_hash(snapshot)
    except (OSError, ValueError, RegistrationError):
        return None
    if actual_hash != content_hash:
        return None
    targets = snapshot.get("targets")
    if not isinstance(targets, list) or len(targets) != 1:
        return None
    contract = targets[0]
    context_slug = target_context.get("catalogSlug")
    if context_slug is not None and contract.get("catalogSlug") != context_slug:
        return None
    if contract.get("unit") != claimed:
        return None
    return claimed


def validate(
    cell: dict,
    taken: set[str],
    *,
    target_context: dict | None = None,
    generation_ticket: dict | None = None,
    agent_version: object = None,
    trusted_history_authorization: dict | None = None,
    trusted_strategy_target: dict | None = None,
) -> list[str]:
    if target_context is None:
        carried_context = cell.get(SEALED_TARGET_CONTEXT_KEY)
        target_context = carried_context if isinstance(carried_context, dict) else None
    if generation_ticket is None:
        carried_ticket = cell.get(SEALED_VALIDATION_TICKET_KEY)
        generation_ticket = carried_ticket if isinstance(carried_ticket, dict) else None
    errs = []
    for k in REQUIRED:
        if k not in cell:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if not SLUG_RE.match(cell["slug"]):
        errs.append("bad slug format")
    if cell["slug"] in taken:
        errs.append("slug collides with existing catalog")
    if cell["unit"] not in ALLOWED_UNITS:
        # A registered target's unit is part of the immutable contract and
        # must be echoed byte-for-byte even when it is not a member of the
        # exploratory allowlist (the 2026-08-07 DoD pair's "billions USD").
        # The exemption admits exactly the registration-authenticated
        # string and nothing else — a bare context claiming a matching
        # targetUnit is not trusted; the named snapshot must exist, hash
        # to the recorded content hash, and carry the claimed unit.
        registered_unit = registration_authenticated_unit(target_context)
        if not (registered_unit and cell["unit"] == registered_unit):
            errs.append(f"unit {cell['unit']!r} not allowed")
    if cell["country"] not in ALLOWED_COUNTRIES:
        errs.append(f"country {cell['country']!r} not allowed")
    if cell["type"] not in ALLOWED_TYPES:
        errs.append(f"type {cell['type']!r} not allowed")
    # Discrete-outcome cells (e.g. policy-rate decisions) may legitimately put
    # the modal point at an interval edge; the interval itself must be real.
    if not (
        cell["ciLow"] <= cell["pointEstimate"] <= cell["ciHigh"]
        and cell["ciLow"] < cell["ciHigh"]
    ):
        errs.append("CI does not bracket point estimate")
    if cell["confidence"] != 0.8:
        errs.append("confidence must be 0.8")
    for key in ("resolutionDate",):
        try:
            datetime.strptime(cell[key], "%Y-%m-%d")
        except ValueError:
            errs.append(f"{key} not YYYY-MM-DD")
    try:
        run_at = datetime.fromisoformat(cell["runAt"].replace("Z", "+00:00"))
        if run_at > datetime.now(timezone.utc):
            errs.append("runAt is in the future")
        if run_at < datetime(2026, 6, 1, tzinfo=timezone.utc):
            errs.append("runAt predates the pipeline")
    except ValueError:
        errs.append("runAt not ISO-8601")
    if not str(cell["resolutionSourceUrl"]).startswith("https://"):
        errs.append("resolutionSourceUrl not https")
    history = cell["historicalContext"]
    if isinstance(history, list):
        for h in history:
            if not isinstance(h, dict):
                continue
            if isinstance(h.get("value"), str):
                cleaned = h["value"].replace("%", "").replace(",", "").strip()
                try:
                    h["value"] = float(cleaned)
                except ValueError:
                    errs.append(f"non-numeric historical value: {h['value']!r}")
            if isinstance(h.get("value"), float) and h["value"].is_integer():
                h["value"] = int(h["value"])
    errs.extend(
        history_floor_errors(
            cell,
            agent_version=agent_version,
            trusted_history_authorization=trusted_history_authorization,
        )
    )
    if len(cell["sourceContext"]) < 2:
        errs.append("needs >=2 source URLs")
    # Mirror of trace-depth.test.ts: sourceContext entries are public URLs,
    # never local repo paths (a sibling run's artifacts are context, not
    # citable provenance).
    for url in cell["sourceContext"]:
        if not re.match(r"^https?://", str(url)):
            errs.append(f"sourceContext entry is not an http(s) URL: {url}")
    private_hits = private_source_hits(cell)
    if private_hits:
        errs.append(
            "private-source provenance is not allowed in " + ", ".join(private_hits)
        )

    steps = cell["reasoning"]
    if len(steps) < 7:
        errs.append(f"only {len(steps)} reasoning steps (need >=7)")
    tools = [s for s in steps if s.get("kind") == "tool"]
    if len(tools) < 2:
        errs.append(f"only {len(tools)} tool steps (need >=2)")
    for t in tools:
        if not re.search(r"\d", str(t.get("result", ""))):
            errs.append(f"tool step without numeric result: {t.get('tool')}")
    if not any(s.get("kind") == "math" for s in steps):
        errs.append("no math step")
    # Interval width must be derived, not vibed: the math step has to show
    # sigma (or the 1.28 z-multiplier) so the width is auditable. Applies to
    # cells run on/after 2026-07-05, same cutoff as trace-depth.test.ts —
    # earlier cells were valid under their run date's rubric and republishing
    # a wave must not retro-reject them. Keep the regex byte-identical to
    # the test.
    # Raw spawned cells carry the sealed runAt at the TOP level; the
    # predictionRun object only exists after this converter builds it.
    # Reading only predictionRun.runAt left run_at empty for every fresh
    # cell, silently skipping the leakage and sigma gates until vitest
    # bounced the staged wave (caught live 2026-07-10, Canada June LFS
    # forecast on LFS release day).
    run_at = str(
        cell.get("runAt") or (cell.get("predictionRun") or {}).get("runAt") or ""
    )
    basis = (
        target_context.get("resolutionDateBasis", "release-calendar")
        if isinstance(target_context, dict)
        else "release-calendar"
    )
    if basis not in {"release-calendar", "resolve-by-bound"}:
        errs.append(f"unsupported target resolutionDateBasis {basis!r}")
    if basis == "resolve-by-bound":
        # This argument is supplied only by the trusted strategy runner or
        # publisher after authenticating the complete selection. Never read
        # strategy authority from the model cell or its carried metadata.
        from canonical_json import canonical_bytes

        strategy_authorized = (
            isinstance(trusted_strategy_target, dict)
            and isinstance(target_context, dict)
            and trusted_strategy_target.get("comparisonTarget") is True
            and bool(trusted_strategy_target.get("conditional"))
            and canonical_bytes(trusted_strategy_target)
            == canonical_bytes(target_context)
        )
        if (
            not valid_generation_ticket_context(generation_ticket)
            and not strategy_authorized
        ):
            errs.append("resolve-by-bound target requires generation ticket context")
        source_binding = target_context.get("sourceBinding")
        window = (
            source_binding.get("expectedReleaseWindow")
            if isinstance(source_binding, dict)
            else None
        )
        window_start = window.get("start") if isinstance(window, dict) else None
        try:
            release_start = datetime.strptime(str(window_start), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            if release_start.date().isoformat() != window_start:
                raise ValueError
        except ValueError:
            errs.append(
                "resolve-by-bound target requires canonical "
                "sourceBinding.expectedReleaseWindow.start"
            )
        else:
            for field in ("runStartedAt", "runAt"):
                value = cell.get(field)
                if not isinstance(value, str) or not value:
                    errs.append(f"resolve-by-bound cell is missing {field}")
                    continue
                try:
                    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    errs.append(f"resolve-by-bound cell {field} is not ISO-8601")
                    continue
                if instant.tzinfo is None:
                    errs.append(f"resolve-by-bound cell {field} is not timezone-aware")
                    continue
                if instant >= release_start:
                    errs.append(
                        f"{field} {value} must precede expectedReleaseWindow.start "
                        f"{window_start}"
                    )
    # A forecast of an already-published number is leakage, not a forecast:
    # the resolution date must postdate the run. Caught live 2026-07-07 (a
    # "2025 provisional infant mortality" cell whose release was 2026-05-26).
    # Mirrors trace-depth.test.ts; same cutoff.
    if run_at >= "2026-07-07" and cell["resolutionDate"] <= run_at[:10]:
        errs.append(
            f"resolutionDate {cell['resolutionDate']} is not after runAt "
            f"{run_at[:10]} — target already published (leakage)"
        )
    if run_at >= "2026-07-05":
        math_text = " ".join(
            s.get("text") or "" for s in steps if s.get("kind") == "math"
        )
        prompt_mode = str(
            cell.get("promptMode")
            or (cell.get("predictionRun") or {}).get("promptMode")
            or ""
        )
        if prompt_mode == "ladder_v2":
            # ladder_v2's pre-registered derivation contract (2026-07-10) is
            # quantile-native: the ladder rungs plus the interpolated tail
            # percentiles stated literally, no parametric sigma disclosure.
            # Keep byte-identical to trace-depth.test.ts.
            if not (
                len(re.findall(r"P\(X\s*<=", math_text)) >= 3
                and re.search(r"10th percentile", math_text, re.IGNORECASE)
                and re.search(r"90th percentile", math_text, re.IGNORECASE)
            ):
                errs.append(
                    "ladder_v2 math step must list P(X <= t) rungs and state "
                    "the interpolated 10th and 90th percentiles"
                )
        elif not re.search(r"sigma\s*[=≈:]|1\.28", math_text, re.IGNORECASE):
            errs.append(
                "math step does not show interval derivation (sigma = X or 1.28)"
            )
    # Mirror site/src/__tests__/trace-depth.test.ts exactly: CI requires an
    # explicit reference-class phrase and interval-falsification wording, and
    # cells that validated here but failed there have shipped-then-bounced.
    # Keep these three regexes byte-identical to the test.
    trace_text = " ".join(
        s.get("text") or f"{s.get('call', '')} {s.get('result', '')}" for s in steps
    ).lower()
    base_rate_re = (
        r"base rate|reference class|last \d+ (prints|releases|months|meetings|"
        r"weeks|weekly|monthly|obs)|distribution of|(trailing|past|realized) "
        r"\d+|\d+-(week|month) (range|distribution|history)|realized "
        r"(volatility|distribution)|historical (range|distribution)|"
        r"trailing-?\d+|month-to-month volatility|std_samp|modal outcome|"
        r"market-implied|implied probabilit|p_hold"
    )
    falsification_re = (
        r"outside (the|our|this) interval|outside \[|would (push|put|land|"
        r"break)|upside risk|downside risk|miss(es)? (high|low)|surprise|tail "
        r"(scenario|risk)|break (the|this) (model|forecast)|breach|lands? "
        r"(above|below)|(above|below) the (interval|band|range)|forecast "
        r"(high|low)|probability would (fall|rise)|would (fail|flip)|fails? "
        r"(only )?if|wrong if|blow past|revert (into|to)|exceed (my|the) "
        r"central|right-skewed|saturation tail"
    )
    if not re.search(base_rate_re, trace_text):
        errs.append("no explicit base-rate/reference-class phrasing (CI regex)")
    if not re.search(falsification_re, trace_text):
        errs.append(
            "no interval-falsification phrasing (CI regex — say what would "
            "land outside the 80% interval / upside risk / downside risk)"
        )
    if not steps:
        # An empty trace must FAIL validation, not crash it: the length and
        # content errors above already describe the failure.
        return errs
    last = steps[-1]
    if last.get("kind") != "forecast":
        errs.append("last step is not the forecast")
    elif (last.get("point"), last.get("ciLow"), last.get("ciHigh")) != (
        cell["pointEstimate"],
        cell["ciLow"],
        cell["ciHigh"],
    ):
        errs.append("forecast step numbers do not match cell numbers")
    return errs


# Key under which load_cells carries a run's SEALED agent metadata (from its
# manifest) alongside the cell, so the published stamp names the agent that
# actually produced the forecast.
SEALED_AGENT_KEY = "_sealedAgentMeta"
# Private carrier for the public ticket identity sealed into a run manifest.
# The nonce hash remains in the records manifest; the site only needs the
# ticket record link that explains which trusted local-generation lane ran.
SEALED_GENERATION_TICKET_KEY = "_sealedGenerationTicket"
# Validation-only carriers read from the sealed run manifest. They never
# reach the published ForecastCell, and unlike the public provenance stamp
# they are populated even before a converter is told which provenance label
# to render. This lets the same validator fail closed for bounded cells in
# runner, replay, and converter paths.
SEALED_TARGET_CONTEXT_KEY = "_sealedTargetContext"
SEALED_VALIDATION_TICKET_KEY = "_sealedValidationGenerationTicket"
# Validation-only reviewed docket authorization resolved from the sealed Git
# checkout named by the run manifest. Never accept this key from input JSON.
SEALED_HISTORY_AUTHORIZATION_KEY = "_sealedHistoryFloorAuthorization"


def agent_stamp() -> dict:
    """Version/hash metadata from the live agent definition.

    Metadata utility only, never a publication fallback. A run's stamp must
    come from its own sealed manifest (SEALED_AGENT_KEY) — stamping live
    metadata made published provenance track HEAD instead of the run: editing
    any skill silently restamped every previously published cell with a version
    that never produced it, and broke wave reproducibility until the wave was
    regenerated into that same untruth (2026-07-25).
    """
    builder = (
        pathlib.Path(__file__).resolve().parents[1]
        / "agents/thesis-analyst/build_prompt.py"
    )
    meta = json.loads(
        subprocess.check_output([sys.executable, str(builder), "--metadata"])
    )
    return meta


def _analyst_record_relative_path(path: pathlib.Path) -> pathlib.PurePosixPath:
    """Return a canonical records-tree path or fail closed."""

    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(ROOT.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(
            f"legacy grandfather input is outside the repository records tree: {path}"
        ) from exc
    if not resolved.is_file() or relative.parts[:2] != ("records", "thesis-analyst"):
        raise ValueError(
            f"legacy grandfather input is outside the analyst records tree: {path}"
        )
    return pathlib.PurePosixPath(relative.as_posix())


def _require_legacy_committed_bytes(
    actual_bytes: bytes,
    relative: pathlib.PurePosixPath,
) -> None:
    """Bind one legacy artifact to the immutable pre-floor Git tree."""

    committed = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-C",
            str(ROOT),
            "show",
            f"{LEGACY_HISTORY_RECORDS_COMMIT}:{relative.as_posix()}",
        ],
        capture_output=True,
        check=False,
    )
    if committed.returncode != 0:
        raise ValueError(
            "legacy grandfather input is not a known committed record at "
            f"{LEGACY_HISTORY_RECORDS_COMMIT}: {relative.as_posix()}"
        )
    if committed.stdout != actual_bytes:
        raise ValueError(
            "legacy grandfather input bytes differ from the known committed record: "
            f"{relative.as_posix()}"
        )


def authenticate_legacy_record(
    path: pathlib.Path,
    manifest_path: pathlib.Path,
    manifest: dict,
    *,
    cells_bytes: bytes,
    manifest_bytes: bytes,
) -> None:
    """Authenticate a custody-less pre-floor manifest/cells pair."""

    cells_relative = _analyst_record_relative_path(path)
    manifest_relative = _analyst_record_relative_path(manifest_path)
    if (
        manifest_relative.name != "manifest.json"
        or manifest_relative.parent != cells_relative.parent
    ):
        raise ValueError(
            "legacy grandfather manifest and cells are not siblings in one "
            "committed analyst record"
        )
    declared = manifest.get("cellsPath")
    if not isinstance(declared, str) or declared != cells_relative.as_posix():
        raise ValueError(
            "legacy manifest cellsPath does not name converter input: "
            f"{declared!r} != {cells_relative.as_posix()!r}"
        )
    _require_legacy_committed_bytes(manifest_bytes, manifest_relative)
    _require_legacy_committed_bytes(cells_bytes, cells_relative)


def sealed_agent_meta(
    run_dir: pathlib.Path,
    *,
    manifest: object | None = None,
) -> dict | None:
    """Agent identity recorded in a run's manifest, if it has one."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    if manifest is None:
        manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError(f"run manifest is not an object: {manifest_path}")
    if manifest.get("ok") is not True:
        raise ValueError(f"run manifest is not successful: {manifest_path}")
    meta = manifest.get("agent")
    if not isinstance(meta, dict):
        raise ValueError(f"run manifest has no sealed agent metadata: {manifest_path}")
    required = ("agent", "agentVersion", "promptHash", "toolPolicyHash")
    if not all(isinstance(meta.get(key), str) and meta[key] for key in required):
        raise ValueError(f"run manifest agent metadata is incomplete: {manifest_path}")
    if not valid_agent_version(meta["agentVersion"]):
        raise ValueError(f"run manifest agentVersion is malformed: {manifest_path}")
    for key in ("promptHash", "toolPolicyHash"):
        if re.fullmatch(r"[0-9a-f]{64}", meta[key]) is None:
            raise ValueError(f"run manifest {key} is malformed: {manifest_path}")
    return meta


def sealed_generation_ticket(
    run_dir: pathlib.Path,
    *,
    manifest: object | None = None,
) -> dict | None:
    """Return the publishable ticket identity sealed into a run manifest."""

    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    if manifest is None:
        manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError(f"run manifest is not an object: {manifest_path}")
    ticket = manifest.get("generationTicket")
    if ticket is None:
        return None
    if not isinstance(ticket, dict) or not all(
        isinstance(ticket.get(key), str) and ticket[key]
        for key in ("ticketId", "ticketPath", "nonceSha256")
    ):
        raise ValueError(
            f"manifest generationTicket is incomplete or invalid: {manifest_path}"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", ticket["nonceSha256"]):
        raise ValueError(
            f"manifest generationTicket nonceSha256 is invalid: {manifest_path}"
        )
    return {"ticketId": ticket["ticketId"], "ticketPath": ticket["ticketPath"]}


def carry_sealed_run_metadata(
    cells: list[dict],
    run_dir: pathlib.Path,
    *,
    provenance: str | None = None,
    manifest: object | None = None,
) -> None:
    """Replace input claims with already-authenticated manifest metadata.

    This low-level carrier deliberately cannot resolve or attach reviewed
    docket authorizations. Publication callers must authenticate the
    manifest/cells pair through ``load_cells``; only that boundary may attach
    an authorization resolved from a custody-bound current-version manifest.
    """

    if provenance is not None and provenance not in PROVENANCE_VALUES:
        raise ValueError(f"unsupported prediction-run provenance: {provenance!r}")
    for cell in cells:
        cell.pop(SEALED_AGENT_KEY, None)
        cell.pop(SEALED_GENERATION_TICKET_KEY, None)
        cell.pop(SEALED_TARGET_CONTEXT_KEY, None)
        cell.pop(SEALED_VALIDATION_TICKET_KEY, None)
        cell.pop(SEALED_HISTORY_AUTHORIZATION_KEY, None)
        # Review metadata is runner-authored, never agent-authored: an
        # agent-planted preSubmitReview would otherwise be excluded from
        # private_source_hits and then masked as if a reviewer wrote it.
        # Only the sealed manifest may attach it, below.
        cell.pop("preSubmitReview", None)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"cell input lacks manifest.json: {run_dir}")
    if manifest is None:
        manifest = json.loads(manifest_path.read_bytes())
    sealed_agent = sealed_agent_meta(run_dir, manifest=manifest)
    if sealed_agent is None:
        raise ValueError(f"run manifest has no sealed agent metadata: {manifest_path}")
    if not isinstance(manifest, dict):
        raise ValueError(f"run manifest is not an object: {manifest_path}")
    sealed_review = manifest.get("preSubmitReview")
    if sealed_review is not None and not isinstance(sealed_review, dict):
        raise ValueError(f"manifest preSubmitReview is invalid: {manifest_path}")
    if isinstance(sealed_review, dict):
        for cell in cells:
            cell["preSubmitReview"] = sealed_review
    has_ticket = manifest.get("generationTicket") is not None
    sealed_target_context = manifest.get("targetContext")
    if sealed_target_context is not None and not isinstance(
        sealed_target_context, dict
    ):
        raise ValueError(f"manifest targetContext is invalid: {manifest_path}")
    validation_ticket = manifest.get("generationTicket")
    if provenance == "ci" and has_ticket:
        raise ValueError(
            "ticketed runs must be converted with --provenance local_operator_attested"
        )
    sealed_ticket = None
    if provenance == "local_operator_attested":
        try:
            sealed_ticket = sealed_generation_ticket(run_dir, manifest=manifest)
        except ValueError as exc:
            raise ValueError(
                "--provenance local_operator_attested requires a valid "
                f"generationTicket in {manifest_path}"
            ) from exc
        if sealed_ticket is None:
            raise ValueError(
                "--provenance local_operator_attested requires a valid "
                f"generationTicket in {manifest_path}"
            )
    for cell in cells:
        cell[SEALED_AGENT_KEY] = sealed_agent
        if sealed_ticket:
            cell[SEALED_GENERATION_TICKET_KEY] = sealed_ticket
        if sealed_target_context is not None:
            cell[SEALED_TARGET_CONTEXT_KEY] = sealed_target_context
        if isinstance(validation_ticket, dict):
            cell[SEALED_VALIDATION_TICKET_KEY] = validation_ticket


def to_forecast_cell(
    cell: dict,
    *,
    provenance: str | None = None,
) -> dict:
    if provenance is not None and provenance not in PROVENANCE_VALUES:
        raise ValueError(f"unsupported prediction-run provenance: {provenance!r}")
    out = {
        k: cell[k]
        for k in (
            "slug",
            "country",
            "type",
            "title",
            "question",
            "unit",
            "pointEstimate",
            "ciLow",
            "ciHigh",
            "confidence",
            "resolutionDate",
            "resolutionSource",
            "resolutionSourceUrl",
            "resolutionRule",
            "historicalContext",
            "drivers",
        )
    }
    if cell.get("dataPointId"):
        out["dataPointId"] = cell["dataPointId"]
    if cell.get("conditionalOn"):
        out["conditionalOn"] = cell["conditionalOn"]
    if cell.get("predictionDistribution"):
        out["predictionDistribution"] = cell["predictionDistribution"]
    stamp = cell.get(SEALED_AGENT_KEY)
    required_stamp = ("agent", "agentVersion", "promptHash", "toolPolicyHash")
    if not isinstance(stamp, dict) or not all(
        isinstance(stamp.get(key), str) and stamp[key] for key in required_stamp
    ):
        raise ValueError("cell lacks sealed agent metadata")
    out["predictionRun"] = {
        "kind": "recorded-agent-run",
        "runAt": cell["runAt"],
        "agent": stamp["agent"],
        "model": cell.get("model", stamp.get("model")),
        "agentVersion": stamp["agentVersion"],
        "promptHash": stamp["promptHash"],
        "toolPolicyHash": stamp["toolPolicyHash"],
        "sourceContext": cell["sourceContext"],
    }
    ticket = cell.get(SEALED_GENERATION_TICKET_KEY)
    if provenance == "ci":
        if ticket is not None:
            raise ValueError(
                "ticketed runs must be converted with --provenance "
                "local_operator_attested"
            )
        out["predictionRun"]["provenance"] = "ci"
    elif provenance == "local_operator_attested":
        if not isinstance(ticket, dict) or not all(
            isinstance(ticket.get(key), str) and ticket[key]
            for key in ("ticketId", "ticketPath")
        ):
            raise ValueError(
                "--provenance local_operator_attested requires a valid generationTicket"
            )
        out["predictionRun"]["provenance"] = "local_operator_attested"
        out["predictionRun"]["generationTicket"] = {
            "ticketId": ticket["ticketId"],
            "ticketPath": ticket["ticketPath"],
        }
    if cell.get("promptMode"):
        out["predictionRun"]["promptMode"] = cell["promptMode"]
    if cell.get("activityLog"):
        out["predictionRun"]["activityLog"] = cell["activityLog"]
    if cell.get("custodyRootSha256"):
        out["predictionRun"]["custodyRootSha256"] = cell["custodyRootSha256"]
    if cell.get("preSubmitReview"):
        out["predictionRun"]["preSubmitReview"] = screen_pre_submit_review(
            cell["preSubmitReview"]
        )
    out["reasoning"] = cell["reasoning"]
    return out


def load_cells(
    path: pathlib.Path,
    *,
    provenance: str | None = None,
) -> list[dict]:
    from normalize_spawn_json import scrub_signed_zeros

    cells_bytes = path.read_bytes()
    cells = scrub_signed_zeros(json.loads(cells_bytes))
    if not isinstance(cells, list):
        raise ValueError(f"cell input must be a JSON list: {path}")
    manifest_path = path.parent / "manifest.json"
    custody_path = path.parent / "custody_root.json"
    if not manifest_path.exists():
        raise ValueError(f"cell input lacks manifest.json: {path}")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    sealed_agent = sealed_agent_meta(path.parent, manifest=manifest)
    if sealed_agent is None:
        raise ValueError(f"run manifest has no sealed agent metadata: {manifest_path}")
    agent_version = sealed_agent["agentVersion"]
    if custody_path.exists():
        from verify_custody import verify_run

        verify_run(path.parent)
        declared = pathlib.Path(manifest["cellsPath"])
        if not declared.is_absolute():
            declared = ROOT / declared
        if declared.resolve() != path.resolve():
            raise ValueError(
                "manifest cellsPath does not name converter input: "
                f"{declared} != {path}"
            )
    elif agent_version_enforces_history_floor(agent_version):
        raise ValueError(
            "history-floor-enforcing agentVersion "
            f"{agent_version} requires custody_root.json: {path}"
        )
    else:
        authenticate_legacy_record(
            path,
            manifest_path,
            manifest,
            cells_bytes=cells_bytes,
            manifest_bytes=manifest_bytes,
        )

    trusted_history_authorization = None
    if any(history_floor_requires_authorization(cell, agent_version) for cell in cells):
        try:
            trusted_history_authorization = reviewed_history_floor_authorization(
                ROOT,
                checkout_sha=manifest.get("checkoutSha"),
                series=manifest.get("series"),
                target_period=manifest.get("period"),
            )
        except ValueError as exc:
            raise ValueError(
                "cannot authenticate reviewed history-floor authorization from "
                f"{manifest_path}: {exc}"
            ) from exc
    carry_sealed_run_metadata(
        cells,
        path.parent,
        provenance=provenance,
        manifest=manifest,
    )
    if trusted_history_authorization is not None:
        for cell in cells:
            cell[SEALED_HISTORY_AUTHORIZATION_KEY] = trusted_history_authorization
    if custody_path.exists():
        for cell in cells:
            cell["custodyRootSha256"] = manifest["custodyRootSha256"]
    return cells


def repo_path(path: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out_ts")
    parser.add_argument("const_name")
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--batch-manifest", action="append", default=[])
    parser.add_argument("--replace-module")
    parser.add_argument("--provenance", choices=sorted(PROVENANCE_VALUES))
    args = parser.parse_args()
    out_ts = args.out_ts
    const_name = args.const_name
    inputs = args.inputs
    site_data = ROOT / "site/src/data"
    collision_exclusion = pathlib.Path(args.replace_module or out_ts)
    taken = existing_slugs(site_data, collision_exclusion)
    cells, failed = [], []
    seen = set()
    for path in inputs:
        for cell in load_cells(pathlib.Path(path), provenance=args.provenance):
            sealed_agent = cell.get(SEALED_AGENT_KEY)
            sealed_authorization = cell.get(SEALED_HISTORY_AUTHORIZATION_KEY)
            errs = validate(
                cell,
                taken | seen,
                agent_version=(
                    sealed_agent.get("agentVersion")
                    if isinstance(sealed_agent, dict)
                    else None
                ),
                trusted_history_authorization=(
                    sealed_authorization
                    if isinstance(sealed_authorization, dict)
                    else None
                ),
            )
            if errs:
                failed.append((cell.get("slug", "?"), errs))
            else:
                seen.add(cell["slug"])
                cells.append(to_forecast_cell(cell, provenance=args.provenance))
    cells.sort(key=lambda c: c["resolutionDate"])

    body = ",\n".join(
        "  " + json.dumps(c, indent=2, ensure_ascii=False).replace("\n", "\n  ")
        for c in cells
    )
    provenance = ""
    if args.batch_manifest:
        batch_paths = [repo_path(pathlib.Path(path)) for path in args.batch_manifest]
        provenance = f"// Batch manifests: {json.dumps(batch_paths)}\n"
    header = (
        "// Generated by scripts/spawned_cells_to_ts.py from recorded\n"
        "// thesis.analyst agent runs. Every tool-step result was fetched from\n"
        "// the named source at predictionRun.runAt; regenerate, don't hand-edit.\n"
        + provenance
        + 'import type { ForecastCell } from "../forecast-cells";\n\n'
        f"export const {const_name}: ForecastCell[] = [\n{body},\n];\n"
    )
    pathlib.Path(out_ts).write_text(header)
    print(f"wrote {len(cells)} cells -> {out_ts}")
    for slug, errs in failed:
        print(f"REJECTED {slug}: {'; '.join(errs)}")
    return 1 if failed and not cells else 0


if __name__ == "__main__":
    sys.exit(main())
