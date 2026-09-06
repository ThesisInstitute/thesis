#!/usr/bin/env python3
"""Run the versioned thesis.analyst agent and persist full run activity.

The runner is intentionally thin:

1. Build the prompt from agents/thesis-analyst/build_prompt.py, or use the
   inline fast prompt for high-volume release-series runs.
2. Execute Codex CLI through subscription auth, run a custom headless command,
   or read a saved response / mock cell.
3. Extract JSON, normalize the cell shape, and validate the spawned-cell
   contract.
4. Write every activity artifact: prompt, command, stdout, stderr, raw
   response, parsed cells, normalized cells, materialized distribution,
   validation report, and manifest.
5. Launch agent subprocesses with a minimal allowlisted environment and
   redact credential patterns from every captured stream before artifacts
   are written (2026-07-21 env-dump incident).

Usage:
  python3 scripts/run_thesis_analyst.py \
      --series ons.labour.unemployment_rate --period 2026-Q4 \
      --prompt-mode fast \
      --codex-model gpt-5.5

  python3 scripts/run_thesis_analyst.py \
      --series ons.labour.unemployment_rate --period 2026-Q4 \
      --response-file /tmp/codex-output.txt

  python3 scripts/run_thesis_analyst.py \
      --series test.series --period 2030-01 --mock-cell
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from canonical_json import canonical_bytes, canonical_sha256
from generation_tickets import TicketError, ticket_manifest_binding
from history_floor import (
    HISTORY_AVAILABILITY_STATUS,
    HISTORY_FLOOR_AGENT_VERSION,
    canonical_period_identity,
    history_floor_requires_authorization,
    reviewed_history_floor_authorization,
)

# thesis_core also has to import when this file runs as a plain checkout script
# (`python3 scripts/run_thesis_analyst.py`, including by absolute path from
# another working directory), where only scripts/ is on sys.path.
_CHECKOUT_ROOT = str(pathlib.Path(__file__).resolve().parents[1])
if _CHECKOUT_ROOT not in sys.path:
    sys.path.insert(0, _CHECKOUT_ROOT)

from thesis_core.diagnostics import safe_exception_text  # noqa: E402
from thesis_core.security import (  # noqa: E402
    AGENT_ENV_ALLOWLIST,  # noqa: F401 - re-exported for callers and tests
    ENV_SECRET_ASSIGNMENT_RE,  # noqa: F401 - re-exported
    JSON_SECRET_FIELD_RE,  # noqa: F401 - re-exported
    REDACTED_PLACEHOLDER,  # noqa: F401 - re-exported
    SECRET_TOKEN_RE,  # noqa: F401 - re-exported
    RedactionError,
    agent_subprocess_env,
    is_credential_key,  # noqa: F401 - re-exported
    redact_headers,  # noqa: F401 - re-exported
    redact_json_value,  # noqa: F401 - re-exported
    redact_response_text,
    redact_stream_line,  # noqa: F401 - re-exported
    redact_stream_text,
    redact_text,
    redact_url,  # noqa: F401 - re-exported
    redact_value,  # noqa: F401 - re-exported
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_ROOT = ROOT / "agents" / "thesis-analyst"
SCRIPTS = ROOT / "scripts"
DEFAULT_RECORD_ROOT = ROOT / "records" / "thesis-analyst"
CDF_POINT_COUNT = 201
INTERVAL_ANCHOR_TRANSFORM_VERSION = "interval_anchor_v1"
AGENT_CDF_TRANSFORM_VERSION = "agent_cdf_v1"
HISTORY_AVAILABILITY_PROMPT_EXAMPLE = {
    "historyAvailability": {
        "status": HISTORY_AVAILABILITY_STATUS,
        "availablePrintCount": 5,
        "detail": (
            "Series began recently; the official source exposes only these five prints."
        ),
    }
}
ANNOUNCEMENT_MCP_SERVER = "thesis_announcement_fetch"
ANNOUNCEMENT_MCP_TOOL = "fetch_official_announcement"
ANNOUNCEMENT_MCP_SCRIPT = SCRIPTS / "announcement_fetch_mcp.py"
ANNOUNCEMENT_MCP_STARTUP_TIMEOUT_SECONDS = 10
ANNOUNCEMENT_MCP_TOOL_TIMEOUT_SECONDS = 30


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug or "run"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_equal(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/number loose equality."""

    return canonical_bytes(left) == canonical_bytes(right)


def repo_relative(path: pathlib.Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def write_artifact(
    out_dir: pathlib.Path,
    artifact_type: str,
    filename: str,
    content: str | bytes,
    created_at: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    data = content.encode() if isinstance(content, str) else content
    path.write_bytes(data)
    return {
        "artifactType": artifact_type,
        "path": repo_relative(path),
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "createdAt": created_at,
    }


def round_distribution_number(value: float) -> float:
    """Match JavaScript Number(value.toPrecision(12))."""
    # + 0.0 unifies IEEE signed zeros: Python's json keeps "-0.0" while
    # JSON.stringify drops the sign, so -0 must never reach a sealed record.
    return float(format(value, ".12g")) + 0.0


def unsign_zero(value: Any) -> Any:
    """Map float -0.0 to +0.0 without touching ints or other types."""
    return value + 0.0 if isinstance(value, float) else value


def coalesce_cdf_knots(
    raw_knots: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    knots: list[tuple[float, float]] = []
    for value, probability in sorted(raw_knots):
        if knots and abs(knots[-1][0] - value) < 1e-12:
            knots[-1] = (value, max(knots[-1][1], probability))
        else:
            knots.append((value, probability))
    return knots


def interpolate_cdf_probability(
    value: float, raw_knots: list[tuple[float, float]]
) -> float:
    knots = coalesce_cdf_knots(raw_knots)
    if value <= knots[0][0]:
        return knots[0][1]
    for index in range(1, len(knots)):
        previous_value, previous_probability = knots[index - 1]
        current_value, current_probability = knots[index]
        if value <= current_value:
            width = current_value - previous_value
            if width <= 0:
                return current_probability
            ratio = (value - previous_value) / width
            return previous_probability + ratio * (
                current_probability - previous_probability
            )
    return knots[-1][1]


def interval_distribution(cell: dict[str, Any]) -> dict[str, Any]:
    """Port of site buildNumericCdfFromInterval (interval_anchor_v1)."""
    point = float(cell["pointEstimate"])
    ci_low = float(cell["ciLow"])
    ci_high = float(cell["ciHigh"])
    lower_spread = max(abs(point - ci_low), 1e-9)
    upper_spread = max(abs(ci_high - point), 1e-9)
    support_lower = ci_low - lower_spread * 1.5
    support_upper = ci_high + upper_spread * 1.5

    if not math.isfinite(support_lower) or not math.isfinite(support_upper):
        support_lower = point - 1
        support_upper = point + 1
    if support_upper <= support_lower:
        spread = max(abs(point), 1) * 0.1
        support_lower = point - spread
        support_upper = point + spread

    knots = [
        (support_lower, 0.0),
        (ci_low, 0.1),
        (point, 0.5),
        (ci_high, 0.9),
        (support_upper, 1.0),
    ]
    step = (support_upper - support_lower) / (CDF_POINT_COUNT - 1)
    points = []
    for index in range(CDF_POINT_COUNT):
        value = (
            support_upper
            if index == CDF_POINT_COUNT - 1
            else support_lower + step * index
        )
        points.append(
            {
                "value": round_distribution_number(value),
                "probability": round_distribution_number(
                    interpolate_cdf_probability(value, knots)
                ),
            }
        )

    return {
        "format": "numeric_cdf_v1",
        "pointCount": CDF_POINT_COUNT,
        "support": {
            "lower": round_distribution_number(support_lower),
            "upper": round_distribution_number(support_upper),
        },
        "points": points,
        "summary": {
            "pointEstimate": unsign_zero(cell["pointEstimate"]),
            "median": unsign_zero(cell["pointEstimate"]),
            "interval80": {
                "lower": unsign_zero(cell["ciLow"]),
                "upper": unsign_zero(cell["ciHigh"]),
            },
        },
        "provenance": "interval_seeded",
        "transformVersion": INTERVAL_ANCHOR_TRANSFORM_VERSION,
    }


def ladder_distribution(cell: dict[str, Any]) -> dict[str, Any] | None:
    """Port of strategy_comparisons.ladder_distribution at scale 1."""
    ladder = cell.get("thresholdLadder")
    if not isinstance(ladder, dict):
        return None
    try:
        thresholds = [float(value) for value in ladder["thresholds"]]
        probabilities = [float(value) for value in ladder["cumulativeProbabilities"]]
    except (KeyError, TypeError, ValueError):
        return None
    if len(thresholds) != len(probabilities) or len(thresholds) < 3:
        return None

    point = float(cell["pointEstimate"])
    ci_low = float(cell["ciLow"])
    ci_high = float(cell["ciHigh"])
    lower_spread = max(abs(point - ci_low), 1e-9)
    upper_spread = max(abs(ci_high - point), 1e-9)
    support_lower = min(ci_low - lower_spread * 1.5, thresholds[0])
    support_upper = max(ci_high + upper_spread * 1.5, thresholds[-1])

    knots: list[tuple[float, float]] = [(support_lower, 0.0)]
    previous_probability = 0.0
    for threshold, probability in zip(thresholds, probabilities):
        probability = min(max(probability, previous_probability), 1.0)
        if threshold <= knots[-1][0]:
            continue
        knots.append((threshold, probability))
        previous_probability = probability
    if support_upper > knots[-1][0]:
        knots.append((support_upper, 1.0))
    else:
        knots[-1] = (knots[-1][0], 1.0)

    step = (knots[-1][0] - knots[0][0]) / (CDF_POINT_COUNT - 1)
    points = []
    for index in range(CDF_POINT_COUNT):
        value = (
            knots[-1][0] if index == CDF_POINT_COUNT - 1 else knots[0][0] + step * index
        )
        points.append(
            {
                "value": round(value, 10) + 0.0,
                "probability": round(interpolate_cdf_probability(value, knots), 10)
                + 0.0,
            }
        )

    return {
        "format": "numeric_cdf_v1",
        "pointCount": CDF_POINT_COUNT,
        "support": {
            "lower": points[0]["value"],
            "upper": points[-1]["value"],
        },
        "points": points,
        "summary": {
            "pointEstimate": unsign_zero(cell["pointEstimate"]),
            "median": unsign_zero(cell["pointEstimate"]),
            "interval80": {
                "lower": unsign_zero(cell["ciLow"]),
                "upper": unsign_zero(cell["ciHigh"]),
            },
        },
        "provenance": "agent_reported",
        "transformVersion": AGENT_CDF_TRANSFORM_VERSION,
    }


def materialize_run_distributions(
    cells: list[dict[str, Any]],
) -> dict[str, Any] | list[dict[str, Any]]:
    distributions = []
    for cell in cells:
        distribution = ladder_distribution(cell)
        if distribution is None and "thresholdLadder" in cell:
            # The cell DECLARED a quantile contract; degrading it to the
            # interval_seeded transform would mislabel provenance and discard
            # the distribution the run authored. Fail closed instead.
            raise ValueError(
                "cell declares a thresholdLadder that did not materialize; "
                "refusing to fall back to interval_seeded "
                f"(dataPointId={cell.get('dataPointId')!r})"
            )
        distribution = distribution or interval_distribution(cell)
        cell["predictionDistribution"] = distribution
        distributions.append(distribution)
    return distributions[0] if len(distributions) == 1 else distributions


# manifest.json is necessarily self-referential.  Its `manifest` artifact
# entry hashes canonical JSON after removing (1) every manifest artifact entry
# and (2) custodyRootSha256.  custody_root.json instead hashes the complete
# pre-root manifest, including that explicitly-excluded self entry.  These are
# the only exclusions; verify_custody.py implements the same transformation.
MANIFEST_HASH_MODE = (
    "canonical-json-v1; exclude artifacts where artifactType=manifest and "
    "exclude custodyRootSha256"
)
CUSTODY_INVENTORY_VERSION = 2


def manifest_self_hash_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(manifest)
    payload.pop("custodyRootSha256", None)
    payload["artifacts"] = [
        artifact
        for artifact in payload.get("artifacts", [])
        if artifact.get("artifactType") != "manifest"
    ]
    return payload


def _artifact_path(out_dir: pathlib.Path, ref: dict[str, Any]) -> pathlib.Path:
    path = pathlib.Path(str(ref["path"]))
    candidate = path if path.is_absolute() else ROOT / path
    if candidate.exists():
        return candidate
    return out_dir / path.name


def custody_artifact_entry(
    out_dir: pathlib.Path, ref: dict[str, Any]
) -> dict[str, Any]:
    path = _artifact_path(out_dir, ref)
    raw = path.read_bytes()
    entry: dict[str, Any] = {
        "artifactType": ref["artifactType"],
        "path": path.name,
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }
    if path.suffix == ".json":
        entry["canonicalJsonSha256"] = canonical_sha256(json.loads(raw))
    return entry


def build_custody_root(
    out_dir: pathlib.Path,
    refs: list[dict[str, Any]],
    manifest_without_root: dict[str, Any],
) -> dict[str, Any]:
    entries = [
        custody_artifact_entry(out_dir, ref)
        for ref in refs
        if ref.get("artifactType") != "manifest"
    ]
    return {
        "schemaVersion": "thesis_custody_root_v1",
        "custodyInventoryVersion": CUSTODY_INVENTORY_VERSION,
        "runMode": "analyst",
        "hashAlgorithm": "sha256",
        "canonicalJson": (
            "UTF-16 code-unit key order; ECMAScript JSON number/string encoding"
        ),
        "artifacts": entries,
        "manifestWithoutCustodyRoot": {
            "path": "manifest.json",
            "excludedField": "custodyRootSha256",
            "canonicalJsonSha256": canonical_sha256(manifest_without_root),
        },
    }


def finalize_manifest(
    out_dir: pathlib.Path,
    run_at: str,
    manifest: dict[str, Any],
    refs: list[dict[str, Any]],
    *,
    checkout_sha: str | None = None,
    generation_ticket: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write custody_root.json, then perform the one final manifest write."""

    if checkout_sha is not None:
        manifest["checkoutSha"] = checkout_sha
    if generation_ticket is not None:
        manifest["generationTicket"] = ticket_manifest_binding(generation_ticket)
    manifest["custodyInventoryVersion"] = CUSTODY_INVENTORY_VERSION
    manifest["runMode"] = "analyst"
    manifest["manifestHashSemantics"] = MANIFEST_HASH_MODE
    self_payload = manifest_self_hash_payload(manifest)
    self_bytes = canonical_bytes(self_payload)
    manifest_ref = {
        "artifactType": "manifest",
        "path": repo_relative(out_dir / "manifest.json"),
        "sha256": sha256_bytes(self_bytes),
        "bytes": len(self_bytes),
        "createdAt": run_at,
        "hashMode": MANIFEST_HASH_MODE,
    }
    manifest["artifacts"] = [*refs, manifest_ref]

    custody_root = build_custody_root(out_dir, refs, manifest)
    custody_path = out_dir / "custody_root.json"
    custody_path.write_text(json.dumps(custody_root, indent=2) + "\n")
    manifest["custodyRootSha256"] = canonical_sha256(custody_root)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_prompt_builder():
    sys.path.insert(0, str(AGENT_ROOT))
    try:
        import build_prompt  # type: ignore

        return build_prompt
    finally:
        if sys.path[0] == str(AGENT_ROOT):
            sys.path.pop(0)


def build_prompt(series: str, period: str, conditional: str | None) -> tuple[str, dict]:
    builder = load_prompt_builder()
    return builder.build(series, period, conditional), builder.agent_meta()


def build_run_prompt(
    series: str,
    period: str,
    conditional: str | None,
    mode: str,
    target_context: dict[str, Any] | None = None,
    ticket: dict[str, str] | None = None,
    network_tools: bool = False,
) -> tuple[str, dict]:
    prompt, meta = build_prompt(series, period, conditional)
    target_context_block = format_target_context(target_context)
    ticket_block = format_generation_ticket(ticket)
    if mode == "full":
        if target_context_block:
            prompt = f"{prompt}\n\n{target_context_block}"
        if ticket_block:
            prompt = f"{prompt}\n\n{ticket_block}"
        if network_tools:
            prompt = f"{prompt}\n\n# Network access\n{NETWORK_TOOLS_NOTE.strip()}\n"
        return prompt, meta
    if mode == "fast":
        return (
            build_fast_prompt(
                series,
                period,
                conditional,
                meta,
                target_context,
                ticket,
                network_tools=network_tools,
            ),
            meta,
        )
    if mode == "ladder":
        # The ladder lane is a distinct agent on the scoreboard: same base
        # prompt and tool policy, different elicitation protocol.
        ladder_meta = {**meta, "agent": f"{meta['agent']}.ladder"}
        return (
            build_ladder_prompt(
                series,
                period,
                conditional,
                meta,
                target_context,
                ticket,
            ),
            ladder_meta,
        )
    if mode == "ladder_v2":
        # Same ladder elicitation, quantile-native derivation contract —
        # its own agent identity so the protocols stay separable on the
        # scoreboard.
        ladder_meta = {**meta, "agent": f"{meta['agent']}.ladder_v2"}
        return (
            build_ladder_v2_prompt(
                series,
                period,
                conditional,
                meta,
                target_context,
                ticket,
            ),
            ladder_meta,
        )
    raise ValueError(f"Unsupported prompt mode {mode!r}")


def format_target_context(target_context: dict[str, Any] | None) -> str:
    if not target_context:
        return ""
    keys = [
        "catalogSlug",
        "country",
        "targetUnit",
        "dataPointId",
        "resolutionDate",
        "resolutionDateBasis",
        "expectedReleaseWindow",
        "resolutionSource",
        "resolutionSourceUrl",
        "resolutionRule",
        "resolutionPolicy",
        "sourceBinding",
        "targetRegistrationPath",
        "targetContentHash",
        "registrationCommit",
        "registeredAtUtc",
        "conditional",
    ]
    unit_sentence = (
        "The cell's unit must equal targetUnit below byte-for-byte, even "
        "when it is not a member of the contract's exploratory unit menu. "
        if target_context.get("targetUnit")
        else ""
    )
    lines = [
        "# Canonical ledger target context",
        "Use these ledger fields as the target contract for slug, unit, "
        f"dataPointId, resolutionDate, and resolver text. {unit_sentence}"
        "If you find a "
        "concrete ledger error, keep the forecast tied to the same target and "
        "state the discrepancy in reasoning rather than silently changing the "
        "target.",
    ]
    for key in keys:
        value = target_context.get(key)
        if value not in (None, ""):
            lines.append(f"- {key}: {json.dumps(value, sort_keys=True)}")
    if target_context.get("resolutionDateBasis") == "resolve-by-bound":
        bound = target_context.get("resolutionDate")
        announcement_url = (target_context.get("sourceBinding") or {}).get("sourceUrl")
        lines += [
            "",
            "# Resolve-by-bound target contract (machine checked)",
            f"- registeredResolveByBound: {json.dumps(bound)}",
            f"- officialAnnouncementUrl: {json.dumps(announcement_url)}",
            "The bound and expected release window are Thesis lab "
            "commitments, not timing claims made by the announcement. The "
            "announcement authenticates methodology identity only; it does "
            "not establish the bound or expected release window. This is an "
            "outer bound, not a scheduled release day. resolutionDate must "
            "byte-echo the registered resolve-by bound; never infer a more "
            "specific day from cadence.",
            "resolutionSourceUrl must byte-echo officialAnnouncementUrl. "
            f"Call `{ANNOUNCEMENT_MCP_SERVER}.{ANNOUNCEMENT_MCP_TOOL}` with "
            "that exact URL. The publisher authenticates the structured "
            "draft/final tool event; a reasoning-token claim, search result, "
            "same-host page, or prose citation cannot substitute for it.",
            "Base rate during a methodology transition: while NO official "
            "print under the announced revised methodology exists — "
            "including revised historical or backcast estimates — the "
            "CURRENT official series is the admissible base rate: fetch it "
            "from its official source, name its vintage explicitly, and "
            "state the announced transition as the regime consideration in "
            "the sigma step. Do not refuse for lack of the unpublished "
            "revised series, and do not fabricate or pre-apply revision "
            "adjustments. The moment any revised-methodology official "
            "print exists, revised prints are required and "
            "old-methodology history stops being admissible.",
        ]
    if (target_context.get("sourceBinding") or {}).get(
        "releasePolicy"
    ) == "registered_query_snapshot":
        binding = target_context.get("sourceBinding") or {}
        transform = binding.get("transform") or {}
        request_method = str(transform.get("requestMethod") or "GET").upper()
        if request_method == "GET":
            # GET bindings carry the period slot in the URL itself.
            execution = (
                "substitute each prior period into "
                f"sourceBinding.sourceUrl ({json.dumps(binding.get('sourceUrl'))}) "
                "and GET it"
            )
        else:
            execution = (
                "substitute each prior period into sourceBinding.transform's "
                f"request template and {request_method} it to "
                f"{json.dumps(binding.get('sourceUrl'))}"
            )
        lines += [
            "",
            "# Registered-query series (machine checked)",
            "This series is DEFINED by the registered query in "
            "sourceBinding — no published table or headline page exists "
            "for it, so agency profile totals and search-result summaries "
            "are the WRONG series. Fetch historicalContext by executing "
            f"the exact registered query for each prior period: {execution}, "
            "then read the value at sourceBinding.field and apply "
            "sourceBinding.transform's operation and factor. History "
            "values obtained any other way will fail anchor validation, "
            "and a cell without historicalContext fails normalization — "
            "if the query cannot be executed, refuse with the fetch "
            "evidence rather than omitting history or substituting a "
            "broader aggregate.",
        ]
    adapter = (target_context.get("sourceBinding") or {}).get("adapter")
    fetch_command = BASE_RATE_FETCH_COMMANDS.get(adapter)
    series = target_context.get("series")
    if fetch_command and isinstance(series, str) and series:
        lines += [
            "",
            "# Resolution-grade base-rate fetch (run this — do not substitute)",
            "The registered adapter's own parser is runnable in this "
            "workspace, and its output IS the series this target resolves "
            "against: history fetched any other way (summaries, bulletins, "
            "line-item estimates, adjacent products) fails anchored "
            "validation even when it is a real official series. For each of "
            "the most recent published periods (fetch at least the latest "
            "six), run:",
            fetch_command.format(series=series),
        ]
    return "\n".join(lines)


def format_generation_ticket(ticket: dict[str, str] | None) -> str:
    """Render the nonce block binding post-mint assembly of public artifacts."""

    if ticket is None:
        return ""
    # The exact context shape, canonical path, and nonce are validated before
    # prompt construction. Calling the manifest projection here keeps prompt
    # reconstruction and manifest stamping on one validation contract.
    ticket_manifest_binding(ticket)
    return (
        f"# Generation ticket\nticket: {ticket['ticketId']}\nnonce: {ticket['nonce']}\n"
    )


# Per-adapter, copy-runnable base-rate fetch commands surfaced in the target
# context. Five S.3596 waves (thesis#115) fetched IRS Pub 4801 line-item
# estimates — a real official series for nearly the same concept — instead
# of the registered Table 3.3 print, and prose pointing at the parser did
# not change that; an explicit command does. PERIOD is chosen by the agent
# (recent published periods); anchor values themselves are never injected.
BASE_RATE_FETCH_COMMANDS = {
    "eia-dnav-xls": (
        "  pip install --user xlrd==2.0.1 >/dev/null 2>&1; "
        "python3 -c \"import sys; sys.path.insert(0, 'scripts'); "
        "import resolve_pending as r; "
        "print(r.eia_dnav_fetch_year("
        "r.EIA_DNAV_ADAPTERS['{series}'], 'PERIOD')[0])\""
        "   # PERIOD = an annual reference year like 2024"
    ),
    "irs-soi-pub1304": (
        "  pip install --user xlrd==2.0.1 >/dev/null 2>&1; "
        "python3 -c \"import sys; sys.path.insert(0, 'scripts'); "
        "import resolve_pending as r; "
        "print(r.irs_soi_pub1304_fetch_normalized_year("
        "r.IRS_SOI_PUB1304_ADAPTERS['{series}'], 'PERIOD')[0])\""
        "   # PERIOD = a tax year like 2023"
    ),
    "fsa-crp-monthly-summary": (
        "  python3 -c \"import sys; sys.path.insert(0, 'scripts'); "
        "import resolve_pending as r; "
        "print(r.fsa_crp_fetch_period("
        "r.FSA_CRP_ADAPTERS['{series}'], 'PERIOD')[0])\""
        "   # PERIOD = a month like 2026-04"
    ),
}


# Injected into agent prompts only when the runner grants sandbox network
# access (--codex-network). The 2026-07-24 broadband incident is the origin:
# with network blocked, the hosted web-search tool failing ("Cache miss"),
# and the contract demanding fetched numbers, four consecutive runs invented
# "fetched" ACS values. Those values match no published ACS vintage at all
# (~3.4 points below the true 1-year series, ~1 point above the 5-year),
# and their cited raw counts are wrong by up to 2.3 million — fabrication,
# not a vintage mix-up. The note pairs the capability with the honesty
# contract: values come from echoed fetch output or the run fails honestly.
NETWORK_TOOLS_NOTE = (
    "Outbound network access is enabled for this run: you may also run "
    "curl -sS against official public data endpoints (agency APIs, data "
    "portals, release calendars). Run each fetch so its raw response — or "
    "the exact excerpt containing every value you use — is echoed in the "
    "command output, and read fetched values only from that echoed "
    "content. Never take table values from web-search result summaries or "
    "from memory. If a fetch fails or returns an empty body, say so in a "
    "text step and stop; a run that cannot fetch its base rate must fail "
    "honestly rather than substitute remembered values. "
)


def build_fast_prompt(
    series: str,
    period: str,
    conditional: str | None,
    meta: dict[str, Any],
    target_context: dict[str, Any] | None = None,
    ticket: dict[str, str] | None = None,
    width_discipline: str = "sigma",
    mode_label: str = "fast",
    network_tools: bool = False,
) -> str:
    """Compact prompt for scheduled public-release batches.

    The full prompt is better for one-off reasoning audits. This one is for
    scale: it inlines the contract while allowing optional read-only access to
    local repo context, prior runs, packs, and traces.

    width_discipline picks the machine-checkable interval-derivation contract:
    "sigma" (default) demands the literal "sigma = X" + 1.28*sigma arithmetic;
    "ladder_quantiles" (ladder_v2) demands the interval be read off the
    elicited ladder with the interpolated percentiles stated literally.
    """

    schema = {
        "slug": "kebab-case-unique-vs-catalog",
        "country": "US|UK|CA|AU|EA|JP",
        "type": "conditional" if conditional else "data",
        **(
            {"conditionalOn": "the registered conditional text, byte-for-byte"}
            if conditional
            else {}
        ),
        "title": "Short display title",
        "question": "Exact agency series, period, adjustment, first print",
        # A preregistered target's unit is part of the immutable contract
        # and validation requires the cell to echo it exactly. The enum is
        # only a menu for unregistered exploratory runs — presenting it to
        # a registered run whose unit is not a member (the 2026-08-07 DoD
        # pair's "billions USD") instructs the model to fail validation.
        "unit": (
            "the registered targetUnit, byte-for-byte"
            if target_context and target_context.get("targetUnit")
            else (
                "percent|count|thousands|millions|usd|usd_millions|"
                "usd_billions|gbp_billions|million_cubic_feet|ratio|"
                "percent_growth"
            )
        ),
        "pointEstimate": 0,
        "ciLow": 0,
        "ciHigh": 0,
        "confidence": 0.8,
        "resolutionDate": "YYYY-MM-DD",
        "resolutionSource": "Official agency release",
        "resolutionSourceUrl": "https://official-source.example",
        "resolutionRule": "First-print rule with rounding and revision policy",
        "dataPointId": "agency.dataset.concept.period.first_print",
        "historicalContext": [
            {
                "period": {"type": "month", "value": "2026-04"},
                "label": "Human-readable period label",
                "value": 0,
            }
        ],
        "drivers": ["short driver phrases"],
        "sourceContext": ["https://urls-actually-used"],
        "runAt": "date -u +%Y-%m-%dT%H:%M:%SZ",
        "reasoning": [
            {"kind": "heading", "text": "Forecast title"},
            {"kind": "text", "text": "Framing and exact resolver"},
            {
                "kind": "tool",
                "tool": "official.lookup",
                "call": "source lookup description",
                "result": "fetched numbers",
            },
            {"kind": "math", "text": "point and 80% interval calculation"},
            {"kind": "forecast", "point": 0, "ciLow": 0, "ciHigh": 0},
        ],
    }
    domain_notes = "\n".join(f"- {line}" for line in fast_domain_notes(series))
    # The label matches the cell field exactly: a snake_case conditional_on
    # label taught models to emit a snake_case key, which the byte-exact
    # conditionalOn validation then refused (thesis#115).
    conditional_line = (
        (
            f"- conditionalOn: {conditional}\n"
            "  Your cell's `conditionalOn` field must repeat this text "
            "byte-for-byte; the registry gates on the exact string.\n"
        )
        if conditional
        else "- conditionalOn: null\n"
    )
    target_context_block = format_target_context(target_context)
    target_context_text = f"{target_context_block}\n\n" if target_context_block else ""
    ticket_block = format_generation_ticket(ticket)
    ticket_text = f"{ticket_block}\n" if ticket_block else ""
    bounded_target = (target_context or {}).get(
        "resolutionDateBasis"
    ) == "resolve-by-bound"
    if bounded_target:
        resolution_source_rule = (
            "- resolutionSourceUrl must byte-echo the registered official "
            "methodology-announcement URL shown in the bounded target "
            "context. Use the "
            f"`{ANNOUNCEMENT_MCP_SERVER}.{ANNOUNCEMENT_MCP_TOOL}` tool on "
            "that exact URL; put any separately fetched resolving table or "
            "data-artifact URL in sourceContext.\n"
        )
        resolution_date_rule = (
            "- resolutionDate must byte-echo the registered Thesis "
            "lab-committed resolve-by bound shown in the target context. It "
            "is an outer bound, not a scheduled release day; the official "
            "announcement does not establish it, and you must not infer a "
            "more specific date from cadence.\n"
        )
    else:
        resolution_source_rule = (
            "- resolutionSourceUrl must be the most specific stable page for "
            "the exact series (release page, table, or databrowser query "
            "with the series code), never a portal or theme landing page; "
            "state the series code or table id in a text step when one "
            "exists.\n"
        )
        resolution_date_rule = (
            "- resolutionDate must be verified from an official release "
            "calendar or announcement schedule this run. Do not infer it "
            "from cadence.\n"
        )
    return (
        "# Thesis analyst fast public-release run\n\n"
        "Return exactly one JSON object and no Markdown. Do not wrap it in a "
        "code fence.\n\n"
        "# Context access\n"
        "You may inspect the local repository/workspace when useful. This is "
        "optional, not required. Useful read-only context can include "
        "docs/cell-contract.md, site/src/data/forecast-cells.ts, "
        "site/src/data/ledger-targets.ts, prediction packs, generated "
        "comparison data, records/thesis-analyst run manifests, full activity "
        "artifacts, prior reasoning traces, and model-candidate files. You may "
        "run read-only commands such as rg, sed, cat, find, git log/status/show, "
        "`date -u +%Y-%m-%dT%H:%M:%SZ`, and short inline arithmetic commands. "
        + (NETWORK_TOOLS_NOTE if network_tools else "")
        + "Local context is admissible only when it is a public repository "
        "artifact, a published Thesis record, or a generated file derived from "
        "public official sources. Do not use private meeting notes, call "
        "transcripts, email/chat content, pasted attachments, personal notes, "
        "or other non-public local files as forecast evidence, source context, "
        "or tool-call provenance. If such material is present on disk, ignore "
        "it; if a prior run cites it, treat that run as tainted for evidence "
        "purposes. "
        "Do not modify files. Treat prior forecasts as historical forecasts or "
        "strategy context, not as ground-truth outcomes. If prior runs affect "
        "your forecast, briefly state the update from the previous run; if they "
        "do not matter, ignore them. Existing catalog pointEstimate, ciLow, "
        "and ciHigh values are not official evidence for a new forecast; use "
        "local catalog context to verify target identity/resolver fields only "
        "unless explicitly auditing an existing forecast.\n\n"
        "Goal: produce one auditable forecast for an automatically resolvable "
        "government/public statistical release. Resolve on the first official "
        "print unless the series itself is a policy decision level after an "
        "announcement.\n\n"
        "# Question spec\n"
        f"- series: {series}\n"
        f"- period: {period}\n"
        f"{conditional_line}\n"
        f"{target_context_text}"
        f"{ticket_text}"
        "# Source hints\n"
        f"{domain_notes}\n\n"
        "# Default promoted forecasting practices\n"
        "- Resolve the exact first-print target before inside-view evidence.\n"
        "- Fetch and state the recent official-source reference class: at "
        "least 6 distinct prints are MANDATORY whenever the official source "
        "exposes them.\n"
        "- Anchor on the outside-view base rate before current-release "
        "adjustments.\n"
        "- Separate level, momentum, one-off, and policy-mechanism effects "
        "before combining them.\n"
        "- Include one public reasoning step beginning "
        '"Prior/update/interval:" that names the model or persistence prior, '
        "historical sample, adjustment components, interval method, and final "
        "implied bounds.\n"
        "- For strict first-print or original-vintage targets, keep the "
        "ledger resolver in substance and do not add same-day correction or "
        "release-day grace exceptions unless the target rule includes them.\n"
        + (
            "- Size the 80% interval from realized dispersion and SHOW the "
            "arithmetic in the Prior/update/interval step: compute sigma from "
            "the fetched history (successive changes for level/rate series; "
            "the values themselves for change/flow series), state it "
            'literally as "sigma = X", and derive the half-width as roughly '
            "1.28*sigma. If you widen or narrow beyond about 0.75x-1.75x of "
            "that half-width, state the regime or mechanism reason in the "
            "same step. Never default to a round hedged band.\n"
            if width_discipline == "sigma"
            else "- Size the 80% interval by reading it off your elicited "
            "threshold ladder, and SHOW the derivation in the 'Ladder:' math "
            "step: state the interpolated values literally as '10th "
            "percentile at X', 'median at Y', and '90th percentile at Z'. "
            "Ground the rung placement in the fetched reference-class "
            "history (state which fetched values anchored the rung span in "
            "the Prior/update/interval step). Never default to a round "
            "hedged band.\n"
        )
        + "- When a release has variants (gross vs smoothed/synthetic, SA vs "
        "NSA, flash vs final), the resolution rule must name the variant and "
        "every anchor and historical value must come from that same variant; "
        "say so once in a text step.\n"
        f"{resolution_source_rule}"
        "- Name concrete upside, downside, and outside-the-interval scenarios, "
        'using the literal phrases "upside risk", "downside risk", and '
        '"outside the interval" (or "would land above/below the interval") so '
        "the falsification step is machine-checkable.\n\n"
        "# Required JSON shape\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "# Validation rules\n"
        "- Use confidence 0.8 exactly.\n"
        "- ciLow < pointEstimate < ciHigh, except discrete policy-rate "
        "targets may put the modal point at an interval edge if needed.\n"
        "- historicalContext must contain at least 6 distinct numeric fetched "
        "prints. Every entry needs a canonical period object: type month with "
        "YYYY-MM, quarter with YYYY-Q1..Q4, year/fiscal_year with YYYY, or "
        "week_ending with YYYY-MM-DD. Its label must unambiguously name that "
        "same period. The whole trimmed label must be one closed printable-ASCII "
        "form: YYYY-MM, Month YYYY, YYYY Month, YYYY-QN, YYYY QN, QN YYYY, "
        "YYYY, calendar year YYYY, FY2026, fiscal year YYYY, YYYY-MM-DD, or "
        "week ending YYYY-MM-DD. Never add source names, first-print or revision "
        "prose, ranges, or a second period cue to the label. Relative, "
        "contradictory, non-ASCII, and multi-period labels refuse. Alternate "
        "labels do not make duplicate canonical periods distinct. "
        "Validation refuses fewer unless the sealed checkout carries the "
        "reviewed authorization below.\n"
        "- Only when the official source exposes fewer than 6 prints, fetch "
        "all available prints and add this top-level audit commentary (replace "
        "5 with the actual count and give a nonempty detail): "
        f"{json.dumps(HISTORY_AVAILABILITY_PROMPT_EXAMPLE)}\n"
        "  This model-authored commentary never authorizes an exception: a "
        "reviewed docket entry in the sealed checkout must independently list "
        "the exact target period, available count, and canonical periods.\n"
        "- sourceContext must contain at least 2 source URLs actually used.\n"
        "- sourceContext, reasoning, drivers, and tool calls must not cite or "
        "use private meeting notes, call transcripts, email/chat content, "
        "pasted attachments, personal notes, or non-public local files.\n"
        "- reasoning must contain at least 7 steps, at least 3 tool steps "
        "whose result strings include fetched numbers, one explicit base-rate "
        'or reference-class step (literally say "base rate" or "reference '
        'class"), one math step, one counter-consideration that states what '
        'would land outside the 80% interval (literally use "upside risk", '
        '"downside risk", or "outside the interval"), '
        "one step beginning Prior/update/interval:, and a final forecast step "
        "whose numbers exactly match the cell.\n"
        "- Every tool step result must include at least one fetched numeric "
        "value — an actual statistic from the source, not just field names "
        "or identifiers. Definitional lookups (data dictionaries, field "
        "definitions, methodology pages) belong in text steps, as do other "
        "qualitative source notes. Numbers may come from official public "
        "sources or inspected local run/model artifacts, but the provenance "
        "must be clear.\n"
        f"{resolution_date_rule}"
        "- Do not use existing local catalog point estimates or intervals as "
        "forecast evidence. If inspected, treat them only as non-authoritative "
        "prior strategy context and keep them out of tool-result evidence.\n"
        "- runAt must be the actual UTC date command output from this run.\n"
        "- Slug should be stable and descriptive; if the same target already "
        "exists, reuse the obvious canonical slug rather than inventing a "
        "near-duplicate.\n\n"
        "Emit the final JSON object only. "
        f"(agent {meta['agent']} v{meta['agentVersion']}, "
        f"prompt {meta['promptHash'][:12]}, "
        f"tools {meta['toolPolicyHash'][:12]}, promptMode {mode_label})\n"
    )


def build_ladder_prompt(
    series: str,
    period: str,
    conditional: str | None,
    meta: dict[str, Any],
    target_context: dict[str, Any] | None = None,
    ticket: dict[str, str] | None = None,
) -> str:
    """Fast prompt plus threshold-ladder elicitation.

    The distribution is elicited as a ladder of binary exceedance questions
    (the protocol forecasting-tuned models are trained on — Turtel et al.
    2025, arXiv:2505.17989) and the published point/interval are DERIVED
    from the ladder, instead of stating an interval directly. Everything
    else — research discipline, sigma disclosure, risk steps — is the same
    contract as fast mode.
    """
    base = build_fast_prompt(series, period, conditional, meta, target_context, ticket)
    ladder_schema = {
        "thresholds": ["strictly increasing numeric rungs"],
        "cumulativeProbabilities": ["non-decreasing, within [0.01, 0.99]"],
    }
    return base + (
        "\n# Threshold-ladder elicitation (promptMode ladder)\n"
        "This run elicits the distribution as binary exceedance questions "
        "BEFORE stating any point estimate, then derives the published "
        "numbers from the ladder.\n"
        "- After research, choose 11-15 strictly increasing thresholds t in "
        "the target's print units spanning your genuine uncertainty: the "
        "first rung's cumulative probability must be <= 0.10 and the last "
        ">= 0.90.\n"
        "- For each rung independently answer the binary question 'What is "
        "the probability the first print is <= t?', as if pricing a binary "
        "market. Probabilities must be non-decreasing across rungs and "
        "within [0.01, 0.99].\n"
        "- Add one math reasoning step that begins 'Ladder:' and lists "
        "every rung literally as 'P(X <= t) = p' pairs.\n"
        "- Derive the published numbers FROM the ladder by linear "
        "interpolation between rungs: pointEstimate at cumulative 0.50, "
        "ciLow at 0.10, ciHigh at 0.90, each rounded to the print "
        "precision. The cell fields and the final forecast step must equal "
        "these derived values exactly.\n"
        "- Keep every fast-mode requirement above (sigma arithmetic, base "
        "rate, upside/downside/outside-the-interval risks). In the "
        "Prior/update/interval step, also state how the ladder-implied 80% "
        "width compares to the 1.28*sigma width.\n"
        "- Add this top-level field to the cell JSON, with your actual "
        "rungs as two equal-length numeric arrays:\n"
        f"{json.dumps({'thresholdLadder': ladder_schema}, indent=2)}\n"
    )


def build_ladder_v2_prompt(
    series: str,
    period: str,
    conditional: str | None,
    meta: dict[str, Any],
    target_context: dict[str, Any] | None = None,
    ticket: dict[str, str] | None = None,
) -> str:
    """Ladder elicitation with a quantile-native derivation contract.

    Pre-registered variant of ladder mode (2026-07-10): the 2026-07-10 model
    wave showed gpt-5.6-luna/-terra reliably producing complete
    quantile-inversion derivations while skipping ladder mode's parametric
    sigma cross-check (0/12 ladder compliance vs gpt-5.5's 6/6). ladder_v2
    keeps the identical ladder elicitation, research discipline, and
    structural gates, but the machine-checkable width derivation is the
    ladder itself — the interpolated 10th/50th/90th percentiles stated
    literally — with no "sigma = X" or 1.28 disclosure demanded. Comparing
    the same models across ladder and ladder_v2 separates capability from
    idiom compliance.
    """
    base = build_fast_prompt(
        series,
        period,
        conditional,
        meta,
        target_context,
        ticket,
        width_discipline="ladder_quantiles",
        mode_label="ladder_v2",
    )
    ladder_schema = {
        "thresholds": ["strictly increasing numeric rungs"],
        "cumulativeProbabilities": ["non-decreasing, within [0.01, 0.99]"],
    }
    return base + (
        "\n# Threshold-ladder elicitation (promptMode ladder_v2)\n"
        "This run elicits the distribution as binary exceedance questions "
        "BEFORE stating any point estimate, then derives the published "
        "numbers from the ladder.\n"
        "- After research, choose 11-15 strictly increasing thresholds t in "
        "the target's print units spanning your genuine uncertainty: the "
        "first rung's cumulative probability must be <= 0.10 and the last "
        ">= 0.90.\n"
        "- For each rung independently answer the binary question 'What is "
        "the probability the first print is <= t?', as if pricing a binary "
        "market. Probabilities must be non-decreasing across rungs and "
        "within [0.01, 0.99].\n"
        "- Add one math reasoning step that begins 'Ladder:' and lists "
        "every rung literally as 'P(X <= t) = p' pairs, then states the "
        "interpolated '10th percentile at X', 'median at Y', and '90th "
        "percentile at Z' in the same step.\n"
        "- Derive the published numbers FROM the ladder by linear "
        "interpolation between rungs: pointEstimate at cumulative 0.50, "
        "ciLow at 0.10, ciHigh at 0.90, each rounded to the print "
        "precision. The cell fields and the final forecast step must equal "
        "these derived values exactly.\n"
        "- Keep every other requirement above (base rate, "
        "upside/downside/outside-the-interval risks, "
        "Prior/update/interval step).\n"
        "- Add this top-level field to the cell JSON, with your actual "
        "rungs as two equal-length numeric arrays:\n"
        f"{json.dumps({'thresholdLadder': ladder_schema}, indent=2)}\n"
    )


def ladder_interpolate(
    thresholds: list[float], probs: list[float], q: float
) -> float | None:
    """Linear interpolation of the quantile at cumulative probability q."""
    if not thresholds or probs[0] > q or probs[-1] < q:
        return None
    for index in range(1, len(probs)):
        if probs[index] >= q:
            p0, p1 = probs[index - 1], probs[index]
            t0, t1 = thresholds[index - 1], thresholds[index]
            if p1 == p0:
                return t1
            return t0 + (t1 - t0) * (q - p0) / (p1 - p0)
    return thresholds[-1]


def decimal_places(value: Any) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 6
    if "." not in text:
        return 0
    return min(len(text.split(".")[1].rstrip("0")), 6)


def ladder_validation_errors(cell: dict[str, Any]) -> list[str]:
    ladder = cell.get("thresholdLadder")
    if not isinstance(ladder, dict):
        return ["ladder run must include a thresholdLadder object"]
    thresholds = ladder.get("thresholds")
    probs = ladder.get("cumulativeProbabilities")
    if not isinstance(thresholds, list) or not isinstance(probs, list):
        return [
            "thresholdLadder must contain thresholds and cumulativeProbabilities arrays"
        ]
    errors: list[str] = []
    if len(thresholds) != len(probs):
        return ["thresholdLadder arrays must have equal length"]
    if not (9 <= len(thresholds) <= 21):
        errors.append(f"thresholdLadder has {len(thresholds)} rungs; want 11-15")
    try:
        thresholds = [float(value) for value in thresholds]
        probs = [float(value) for value in probs]
    except (TypeError, ValueError):
        return ["thresholdLadder arrays must be numeric"]
    if any(b <= a for a, b in zip(thresholds, thresholds[1:])):
        errors.append("thresholds must be strictly increasing")
    if any(b < a for a, b in zip(probs, probs[1:])):
        errors.append("cumulativeProbabilities must be non-decreasing")
    if probs and (probs[0] < 0.005 or probs[-1] > 0.995):
        errors.append("cumulative probabilities must stay within [0.01, 0.99]")
    if probs and probs[0] > 0.12:
        errors.append(f"first rung cumulative probability {probs[0]} must be <= 0.10")
    if probs and probs[-1] < 0.88:
        errors.append(f"last rung cumulative probability {probs[-1]} must be >= 0.90")
    if errors:
        return errors
    # The published numbers must be the ladder's own quantiles (to print
    # precision) — the ladder is the forecast, not decoration around one.
    point = cell.get("pointEstimate")
    ci_low = cell.get("ciLow")
    ci_high = cell.get("ciHigh")
    if not all(isinstance(v, (int, float)) for v in (point, ci_low, ci_high)):
        return ["cell is missing numeric pointEstimate/ciLow/ciHigh"]
    step = 10 ** -max(
        decimal_places(point), decimal_places(ci_low), decimal_places(ci_high)
    )
    tolerance = max(0.075 * (float(ci_high) - float(ci_low)), 0.51 * step)
    for label, stated, q in (
        ("ciLow", float(ci_low), 0.10),
        ("pointEstimate", float(point), 0.50),
        ("ciHigh", float(ci_high), 0.90),
    ):
        derived = ladder_interpolate(thresholds, probs, q)
        if derived is None:
            errors.append(f"ladder does not span cumulative {q} for {label}")
        elif abs(derived - stated) > tolerance:
            errors.append(
                f"{label} {stated} deviates from ladder-derived "
                f"q{int(q * 100)} {round(derived, 6)} beyond tolerance "
                f"{round(tolerance, 6)}"
            )
    return errors


def fast_domain_notes(series: str) -> list[str]:
    if series.startswith("boe."):
        return [
            "Use Bank of England MPC pages and monetary-policy summaries.",
            "Target is usually Bank Rate after the named MPC announcement.",
            "Resolution source should be the Bank of England announcement page.",
        ]
    if series.startswith("ons."):
        return [
            "Use ONS time-series pages, ONS API, and ONS release calendar.",
            "UK CPI/CPIH prints to one decimal; labour-market rates print to "
            "one decimal.",
            "Resolution source should be the relevant ONS release or time-series page.",
        ]
    if series.startswith("statcan."):
        return [
            "Use Statistics Canada The Daily and release schedule.",
            "Canada CPI annual rates print to one decimal.",
            "Resolution source should be the Statistics Canada release/table.",
        ]
    if series.startswith("estat."):
        return [
            "Use Statistics Bureau of Japan/e-Stat CPI pages and release schedule.",
            "Japan CPI annual rates print to one decimal.",
            "Resolution source should be the official CPI release/table.",
        ]
    if series.startswith("eurostat."):
        return [
            "Use Eurostat euro-indicators release calendar and official HICP/IP pages.",
            "Euro-area HICP rates print to one decimal.",
            "Resolution source should be the Eurostat release/data page.",
        ]
    if series.startswith("abs."):
        return [
            "Use ABS release calendar and official monthly CPI indicator pages.",
            "Australia CPI indicator rates print to one decimal.",
            "Resolution source should be the ABS release page.",
        ]
    if series.startswith("census."):
        return [
            "Use Census income, poverty, SPM, and health-insurance release "
            "pages, CPS ASEC historical tables, and the Census release calendar.",
            "For official-poverty targets, distinguish the official poverty "
            "measure from SPM and cite the exact Census table or report.",
            "For SPM targets, name the population group, calendar year, and "
            "whether taxes, credits, transfers, medical expenses, or housing "
            "adjustments matter for the forecast.",
            "For ACS table targets, fetch each history year's values from "
            "the keyless JSON endpoint https://data.census.gov/api/access/"
            "data/table?id=<PRODUCT><YEAR>.<TABLE>&g=010XX00US (for example "
            "ACSDT1Y2024.B28005) and read the cited variable columns from "
            "the returned JSON.",
            "api.census.gov requires an API key (keyless requests redirect "
            "to missing_key.html); never rely on it in keyless runs, and "
            "never present remembered values as fetched ones.",
            "ACS vintage discipline: never mix 5-year estimates into a "
            "1-year series — the 5-year file is a five-year average, so "
            "its level trails the 1-year series; the product id in the "
            "fetch URL (ACSDT1Y vs ACSDT5Y) is the vintage authority.",
        ]
    if series.startswith(("bls.", "bea.", "census.", "dol.", "fed.", "us.")):
        return [
            "Use the official agency release calendar, not inferred cadence.",
            "FRED may be used as a history mirror, but resolution cites the agency.",
            "For FOMC targets, resolve to the target range upper bound after "
            "the announcement.",
            "For DOL claims, name the week-ending date and cite the release date.",
        ]
    if series.startswith("cms."):
        return [
            "Use Medicaid.gov enrollment and eligibility-report pages plus "
            "data.medicaid.gov datasets.",
            "For fixed-vintage Medicaid/CHIP targets, name the reporting "
            "period, preliminary/updated status, and whether the target is a "
            "national total, weighted average, or state row.",
            "If the catalog unit is millions, convert official person counts "
            "to millions in the emitted cell.",
        ]
    if series.startswith(("fns.", "usda.fns.")):
        return [
            "Use USDA FNS program-data pages, official data tables, and the "
            "FNS data release calendar.",
            "For SNAP, WIC, and QC targets, distinguish annual fiscal-year "
            "quality-control releases from monthly participation tables.",
            "If the catalog unit is millions, convert official person counts "
            "to millions in the emitted cell.",
        ]
    if series.startswith("treasury."):
        return [
            "Use U.S. Treasury Monthly Treasury Statement pages, fiscal-year "
            "tables, and official release schedules.",
            "For MTS targets, distinguish monthly amounts, fiscal-year-to-date "
            "amounts, receipts, outlays, refunds, and deficit concepts.",
            "Match the catalog unit, usually billions of nominal dollars.",
        ]
    if series.startswith("irs."):
        return [
            "Use IRS filing-season statistics, annual inflation-adjustment "
            "revenue procedures, and official IRS release pages.",
            "For threshold targets, resolve to the first official IRS value "
            "for the named tax year and parameter, not an inferred estimate "
            "once the official figure is available.",
            "Match the catalog unit, usually nominal dollars or billions of "
            "nominal dollars.",
        ]
    return [
        "Use the official agency data page and release calendar.",
        "FRED or sanctioned mirrors may be used only for history, not final "
        "resolution.",
        "Match the agency's published rounding precision.",
    ]


def default_out_dir(series: str, period: str, run_at: str) -> pathlib.Path:
    date = run_at[:10]
    stamp = slugify(run_at.replace(":", "-"))
    return DEFAULT_RECORD_ROOT / date / f"{stamp}-{slugify(series)}-{slugify(period)}"


# --- Credential hygiene -----------------------------------------------------
# The two defenses below now live in thesis_core/security.py so the legacy
# runner, the thesis_core execution path and the source adapters scrub with
# one implementation; the names above are re-exported unchanged for callers
# and tests that import them from this module.
#
# Incident 2026-07-21: during an aging-wave batch, the codex agent ran
# `env | rg -i 'CENSUS|API|KEY'` while hunting for a Census API key, and 18
# credential env vars inherited from the interactive shell landed verbatim in
# recorded trace files; GitHub push protection was the only thing that kept
# them out of the public repo. Two independent layers now guard records/:
#
# 1. Recorded agent subprocesses run under a minimal explicit environment
#    (an allowlist, never a denylist), so an env dump has nothing secret to
#    print. Codex authenticates through CODEX_HOME/auth.json, not env vars.
# 2. Every captured agent stream is redacted before any artifact is written,
#    so a secret read from disk or echoed by a tool still never reaches
#    records/ — and custody roots seal the already-clean bytes, so no
#    post-hoc scrub can break attestation.


def _redact_captured_text(text: str, *, response: bool = False) -> tuple[str, bool]:
    """Preserve an observed result even when one channel cannot be archived."""
    try:
        redactor = redact_response_text if response else redact_stream_text
        return redactor(text), False
    except RedactionError:
        size = len(text.encode("utf-8", errors="replace"))
        return (
            f"[Output omitted: safe redaction was unavailable; {size} bytes.]\n",
            True,
        )


def run_agent_command(
    command: str,
    prompt: str,
    prompt_path: pathlib.Path,
    timeout_seconds: int,
) -> dict:
    rendered = command.format(prompt_path=str(prompt_path), repo_root=str(ROOT))
    argv = shlex.split(rendered)
    if not argv:
        raise SystemExit("--command resolved to an empty command")
    started_at = utc_now()
    try:
        completed = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=agent_subprocess_env(),
        )
        finished_at = utc_now()
        stdout, unsafe_stdout = _redact_captured_text(completed.stdout)
        stderr, unsafe_stderr = _redact_captured_text(completed.stderr)
        refused = [
            name
            for name, unsafe in (("stdout", unsafe_stdout), ("stderr", unsafe_stderr))
            if unsafe
        ]
        return {
            "backend": "external_command",
            "argv": argv,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "returnCode": (completed.returncode or 1)
            if refused
            else completed.returncode,
            "processReturnCode": completed.returncode,
            "timedOut": False,
            "stdout": stdout,
            "stderr": stderr,
            **({"redactionFailures": refused} if refused else {}),
        }
    except subprocess.TimeoutExpired as exc:
        finished_at = utc_now()
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        stdout, unsafe_stdout = _redact_captured_text(stdout)
        stderr, unsafe_stderr = _redact_captured_text(stderr)
        stderr = (
            f"{stderr}\nagent command timed out after {timeout_seconds} seconds\n"
        ).lstrip()
        return {
            "backend": "external_command",
            "argv": argv,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "returnCode": 124,
            "timedOut": True,
            "stdout": stdout,
            "stderr": stderr,
            **(
                {
                    "redactionFailures": [
                        name
                        for name, unsafe in (
                            ("stdout", unsafe_stdout),
                            ("stderr", unsafe_stderr),
                        )
                        if unsafe
                    ]
                }
                if unsafe_stdout or unsafe_stderr
                else {}
            ),
        }
    except OSError as exc:
        finished_at = utc_now()
        return {
            "backend": "external_command",
            "argv": argv,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "returnCode": 127,
            "timedOut": False,
            "stdout": "",
            "stderr": f"agent command could not start: {safe_exception_text(exc)}\n",
        }


def resolve_codex_cli() -> str:
    """Return the Codex executable, preferring the Desktop-bundled CLI."""
    override = os.getenv("THESIS_CODEX_BIN")
    if override:
        return override

    app_binary = pathlib.Path("/Applications/Codex.app/Contents/Resources/codex")
    if app_binary.exists():
        return str(app_binary)

    return shutil.which("codex") or "codex"


def prepare_codex_home(codex_home: pathlib.Path) -> pathlib.Path:
    """Create a minimal CODEX_HOME that reuses subscription auth, not config."""
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "skills").mkdir(exist_ok=True)
    source_home = pathlib.Path(
        os.environ.get("CODEX_HOME") or pathlib.Path.home() / ".codex"
    )
    for filename in ("auth.json", "installation_id"):
        source = source_home / filename
        target = codex_home / filename
        if target.exists() or target.is_symlink() or not source.exists():
            continue
        try:
            target.symlink_to(source)
        except OSError:
            shutil.copy2(source, target)
    return codex_home


def positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def wait_for_codex_process(
    process: subprocess.Popen[str],
    last_message_file: pathlib.Path,
    timeout_seconds: int,
    *,
    heartbeat_paths: list[pathlib.Path],
    settle_seconds: float = 5.0,
    max_output_wait_seconds: float = 30.0,
    max_idle_seconds: float = 120.0,
    poll_interval: float = 0.5,
) -> bool:
    """Wait for Codex, terminating once the last assistant message is stable."""
    start = time.time()
    last_snapshot: tuple[int, int] | None = None
    stable_since: float | None = None
    output_seen_at: float | None = None
    last_activity_at = start
    heartbeat_snapshot: tuple[tuple[int, int, int], ...] | None = None

    def snapshot_activity() -> tuple[tuple[int, int, int], ...]:
        snapshot: list[tuple[int, int, int]] = []
        for path in [last_message_file, *heartbeat_paths]:
            if not path.exists():
                snapshot.append((0, 0, 0))
                continue
            try:
                stat = path.stat()
            except OSError:
                snapshot.append((0, 0, 0))
                continue
            snapshot.append((1, stat.st_size, stat.st_mtime_ns))
        return tuple(snapshot)

    while True:
        if process.poll() is not None:
            return False

        now = time.time()
        if now - start > timeout_seconds:
            raise subprocess.TimeoutExpired(process.args, timeout_seconds)

        current_heartbeat = snapshot_activity()
        if current_heartbeat != heartbeat_snapshot:
            heartbeat_snapshot = current_heartbeat
            last_activity_at = now
        elif now - last_activity_at >= max_idle_seconds:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise subprocess.TimeoutExpired(process.args, max_idle_seconds)

        if last_message_file.exists():
            try:
                text = last_message_file.read_text().strip()
                stat = last_message_file.stat()
            except OSError:
                text = ""
                stat = None

            if text and stat is not None:
                output_seen_at = output_seen_at or now
                snapshot = (stat.st_size, stat.st_mtime_ns)
                if snapshot == last_snapshot:
                    stable_since = stable_since or now
                    if now - stable_since >= settle_seconds:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        return True
                else:
                    last_snapshot = snapshot
                    stable_since = None

                if now - output_seen_at >= max_output_wait_seconds:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    return True

        time.sleep(poll_interval)


def parse_codex_jsonl(stdout_text: str, stderr_text: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    assistant_messages: list[str] = []
    usage_payload: dict[str, Any] | None = None
    last_error: str | None = None
    non_json_lines: list[str] = []

    for stream_name, text in (("stdout", stdout_text), ("stderr", stderr_text)):
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                non_json_lines.append(f"{stream_name}: {line}")
                continue
            if not isinstance(payload, dict):
                continue
            events.append(payload)
            if payload.get("type") == "item.completed":
                item = payload.get("item") or {}
                if item.get("type") == "agent_message" and item.get("text"):
                    assistant_messages.append(str(item["text"]))
            elif payload.get("type") == "turn.completed":
                usage_payload = payload.get("usage") or {}
            elif payload.get("type") == "error":
                last_error = payload.get("message") or "codex exec error"

    events_jsonl = "\n".join(json.dumps(event) for event in events)
    if events_jsonl:
        events_jsonl += "\n"
    return {
        "events": events,
        "eventsJsonl": events_jsonl,
        "assistantText": "\n".join(assistant_messages).strip(),
        "lastAssistantText": (
            assistant_messages[-1].strip() if assistant_messages else ""
        ),
        "usage": usage_payload,
        "lastError": last_error,
        "nonJsonStderr": "\n".join(non_json_lines),
    }


def announcement_mcp_config(
    announcement_url: str,
    *,
    checkout_root: pathlib.PurePath = ROOT,
    python_executable: str = sys.executable,
) -> list[str]:
    """Return the exact trusted MCP overrides for one bounded target URL."""

    server = f"mcp_servers.{ANNOUNCEMENT_MCP_SERVER}"
    script_path = checkout_root / "scripts" / ANNOUNCEMENT_MCP_SCRIPT.name
    return [
        f"{server}.command=" + json.dumps(python_executable),
        f"{server}.args="
        + json.dumps(
            [str(script_path), "--allowed-url", announcement_url],
            separators=(",", ":"),
        ),
        f"{server}.cwd=" + json.dumps(str(checkout_root)),
        f"{server}.required=true",
        f'{server}.enabled_tools=["{ANNOUNCEMENT_MCP_TOOL}"]',
        f"{server}.startup_timeout_sec={ANNOUNCEMENT_MCP_STARTUP_TIMEOUT_SECONDS}",
        f"{server}.tool_timeout_sec={ANNOUNCEMENT_MCP_TOOL_TIMEOUT_SECONDS}",
        f'{server}.tools.{ANNOUNCEMENT_MCP_TOOL}.approval_mode="approve"',
    ]


def target_announcement_url(
    target_context: dict[str, Any] | None,
) -> str | None:
    if not isinstance(target_context, dict) or (
        target_context.get("resolutionDateBasis", "release-calendar")
        != "resolve-by-bound"
    ):
        return None
    binding = target_context.get("sourceBinding")
    url = binding.get("sourceUrl") if isinstance(binding, dict) else None
    return url if isinstance(url, str) and url else None


def enforce_ticket_codex_stream_binding(
    command_result: dict[str, Any],
) -> dict[str, Any]:
    """Fail a ticket stage when raw JSONL and the Codex -o file disagree."""

    if (
        command_result.get("backend") != "codex"
        or command_result.get("returnCode") != 0
    ):
        return command_result
    raw_stdout = command_result.get("codexStdoutRaw")
    raw_stderr = command_result.get("codexStderrRaw")
    last_message = command_result.get("codexLastMessage")
    mismatch = not all(
        isinstance(value, str) for value in (raw_stdout, raw_stderr, last_message)
    )
    if not mismatch:
        try:
            replayed = parse_codex_jsonl(raw_stdout, raw_stderr)
        except Exception:
            mismatch = True
        else:
            mismatch = replayed["lastAssistantText"] != last_message
    if not mismatch:
        return command_result

    message = (
        "ticket mode refused successful Codex stage because raw JSONL and the "
        "codex_last_message artifact disagree"
    )
    failed = copy.deepcopy(command_result)
    failed["returnCode"] = 1
    prior_stderr = str(failed.get("stderr") or "").rstrip()
    failed["stderr"] = f"{prior_stderr}\n{message}".lstrip()
    trace = failed.get("codexTrace")
    if isinstance(trace, dict):
        trace["effectiveReturnCode"] = 1
        trace["lastError"] = message
    return failed


# --- Workspace-mutation guard -----------------------------------------------
# The read-only Codex sandbox denies all sockets (curl inside it exits 6,
# "could not resolve host"), and the hosted web-search tool cannot fetch raw
# JSON from CDN-fronted agency APIs (data.census.gov returns "Cache miss").
# Network-enabled runs therefore use the workspace-write sandbox with
# `sandbox_workspace_write.network_access=true` — which also makes the
# checkout writable. These guards keep the honesty contract mechanical for
# such runs: fingerprint the run dir and the git tree around the agent
# stage, and fail the run closed on any mutation. Additions inside the run
# dir are additionally caught at promotion by custody inventory v2 (which
# rejects unreferenced files), and mid-run edits to sealed artifacts by the
# manifest/custody hash mismatch; this guard fails at run time instead and
# covers the rest of the worktree, which custody never sees.


def git_porcelain_lines(out_dir: pathlib.Path) -> list[str] | None:
    """Sorted `git status --porcelain` lines for ROOT, minus the run dir."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain=v1", "-uall"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    run_dir_token = repo_relative(out_dir)
    lines = []
    for line in proc.stdout.splitlines():
        if run_dir_token and run_dir_token in line:
            continue
        lines.append(line)
    return sorted(lines)


def workspace_guard_snapshot(out_dir: pathlib.Path) -> dict[str, Any]:
    hashes: dict[str, str] = {}
    for path in sorted(out_dir.rglob("*")):
        if path.is_file() and not path.is_symlink():
            hashes[str(path.relative_to(out_dir))] = sha256_bytes(path.read_bytes())
    return {"outDirHashes": hashes, "gitStatus": git_porcelain_lines(out_dir)}


def workspace_guard_violations(
    pre: dict[str, Any],
    out_dir: pathlib.Path,
    allowed_new: set[str],
) -> list[str]:
    post = workspace_guard_snapshot(out_dir)
    pre_hashes: dict[str, str] = pre["outDirHashes"]
    post_hashes: dict[str, str] = post["outDirHashes"]
    violations = []
    for rel, digest in pre_hashes.items():
        if rel not in post_hashes:
            violations.append(f"run artifact deleted during agent stage: {rel}")
        elif post_hashes[rel] != digest:
            violations.append(f"run artifact modified during agent stage: {rel}")
    for rel in post_hashes:
        if rel not in pre_hashes and rel not in allowed_new:
            violations.append(
                f"unexpected file created in run dir during agent stage: {rel}"
            )
    pre_git = pre["gitStatus"]
    post_git = post["gitStatus"]
    if pre_git is not None and post_git is not None:
        for line in sorted(set(post_git) - set(pre_git)):
            violations.append(
                f"workspace tree changed during agent stage: {line.strip()}"
            )
        for line in sorted(set(pre_git) - set(post_git)):
            violations.append(
                f"workspace tree entry cleared during agent stage: {line.strip()}"
            )
    return violations


def run_codex_agent_command(
    *,
    prompt: str,
    timeout_seconds: int,
    model: str,
    out_dir: pathlib.Path,
    prefix: str,
    search: bool,
    sandbox: str,
    reasoning_effort: str | None,
    network: bool = False,
    announcement_url: str | None = None,
) -> dict[str, Any]:
    """Run a prompt through Codex CLI/ChatGPT auth and retain the full trace."""
    out_dir.mkdir(parents=True, exist_ok=True)
    last_message_file = out_dir / f"{prefix}codex_last_message.txt"
    last_message_file.unlink(missing_ok=True)

    cmd = [resolve_codex_cli()]
    if search:
        cmd.append("--search")
    cmd.extend(
        [
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "-o",
            str(last_message_file),
            "-m",
            model,
        ]
    )
    if reasoning_effort:
        cmd.extend(["-c", f'reasoning_effort="{reasoning_effort}"'])
    if network:
        cmd.extend(["-c", "sandbox_workspace_write.network_access=true"])
    if announcement_url is not None:
        for config in announcement_mcp_config(announcement_url):
            cmd.extend(["-c", config])
    cmd.extend(["-C", str(ROOT), "-s", sandbox, prompt])
    logged_cmd = [*cmd[:-1], "<prompt>"]

    guard_pre = workspace_guard_snapshot(out_dir) if sandbox != "read-only" else None

    started_at = utc_now()
    terminated_after_output = False
    timed_out = False
    timeout_reason: str | None = None
    stdout_text = ""
    stderr_text = ""
    process_return_code = 1
    redaction_failures: list[str] = []

    try:
        codex_home_dir = tempfile.mkdtemp(prefix="thesis-codex-home-")
        try:
            with (
                tempfile.NamedTemporaryFile(mode="w+", delete=False) as stdout_file,
                tempfile.NamedTemporaryFile(mode="w+", delete=False) as stderr_file,
            ):
                codex_home = prepare_codex_home(pathlib.Path(codex_home_dir))
                codex_env = agent_subprocess_env({"CODEX_HOME": str(codex_home)})
                stdout_path = pathlib.Path(stdout_file.name)
                stderr_path = pathlib.Path(stderr_file.name)
                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    cwd=ROOT,
                    env=codex_env,
                )
                try:
                    terminated_after_output = wait_for_codex_process(
                        process,
                        last_message_file,
                        timeout_seconds,
                        heartbeat_paths=[stdout_path, stderr_path],
                        max_idle_seconds=positive_int_env(
                            "THESIS_CODEX_IDLE_TIMEOUT_SECONDS",
                            min(timeout_seconds, 120),
                        ),
                    )
                except subprocess.TimeoutExpired as exc:
                    timed_out = True
                    timeout_reason = (
                        "idle"
                        if exc.timeout
                        == positive_int_env(
                            "THESIS_CODEX_IDLE_TIMEOUT_SECONDS",
                            min(timeout_seconds, 120),
                        )
                        else "wall"
                    )
                    process.kill()
                    process.wait()
                process_return_code = process.returncode or 0
        finally:
            shutil.rmtree(codex_home_dir, ignore_errors=True)

        stdout_text, unsafe_stdout = _redact_captured_text(stdout_path.read_text())
        stderr_text, unsafe_stderr = _redact_captured_text(stderr_path.read_text())
        redaction_failures.extend(
            name
            for name, unsafe in (("stdout", unsafe_stdout), ("stderr", unsafe_stderr))
            if unsafe
        )
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)
        workspace_mutations = (
            workspace_guard_violations(
                guard_pre, out_dir, allowed_new={last_message_file.name}
            )
            if guard_pre is not None
            else None
        )
    except FileNotFoundError:
        finished_at = utc_now()
        return {
            "backend": "codex",
            "argv": logged_cmd,
            "networkAccess": network,
            "timeoutSeconds": timeout_seconds,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "returnCode": 127,
            "timedOut": False,
            "stdout": "",
            "stderr": "codex CLI not found",
            "codexStdoutRaw": "",
            "codexStderrRaw": "codex CLI not found",
            "codexEventsJsonl": "",
            "codexLastMessage": "",
            "codexTrace": {
                "provider": "openai",
                "backend": "codex-exec",
                "model": model,
                "timeoutSeconds": timeout_seconds,
                "error": "codex CLI not found",
            },
        }
    except Exception as exc:
        finished_at = utc_now()
        diagnostic = safe_exception_text(exc)
        return {
            "backend": "codex",
            "argv": logged_cmd,
            "networkAccess": network,
            "timeoutSeconds": timeout_seconds,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "returnCode": 1,
            "timedOut": False,
            "stdout": "",
            "stderr": f"Error running codex CLI: {diagnostic}",
            "codexStdoutRaw": "",
            "codexStderrRaw": f"Error running codex CLI: {diagnostic}",
            "codexEventsJsonl": "",
            "codexLastMessage": "",
            "codexTrace": {
                "provider": "openai",
                "backend": "codex-exec",
                "model": model,
                "timeoutSeconds": timeout_seconds,
                "error": diagnostic,
            },
        }

    finished_at = utc_now()
    parsed = parse_codex_jsonl(stdout_text, stderr_text)
    final_text = parsed["lastAssistantText"] or parsed["assistantText"]
    last_message_text = ""
    if last_message_file.exists():
        stripped_last_message = last_message_file.read_text().strip()
        last_message_text, unsafe_last_message = _redact_captured_text(
            stripped_last_message, response=True
        )
        if unsafe_last_message:
            redaction_failures.append("last_message")
        if last_message_text != stripped_last_message:
            # Codex wrote this file directly into the run dir; keep the
            # on-disk copy clean even if sealing fails before the artifact
            # write overwrites it.
            last_message_file.write_text(last_message_text)
        if last_message_text:
            final_text = last_message_text
    if not final_text and parsed["lastError"]:
        final_text = str(parsed["lastError"])

    effective_return_code = process_return_code
    if final_text and (
        process_return_code == 0 or terminated_after_output or timed_out
    ):
        effective_return_code = 0
    if redaction_failures:
        effective_return_code = effective_return_code or 1

    return {
        "backend": "codex",
        "argv": logged_cmd,
        "networkAccess": network,
        "timeoutSeconds": timeout_seconds,
        **(
            {"workspaceMutations": workspace_mutations}
            if workspace_mutations is not None
            else {}
        ),
        "startedAt": started_at,
        "finishedAt": finished_at,
        "returnCode": effective_return_code,
        "processReturnCode": process_return_code,
        "timedOut": timed_out,
        "timeoutReason": timeout_reason,
        "terminatedAfterOutput": terminated_after_output,
        **({"redactionFailures": redaction_failures} if redaction_failures else {}),
        "stdout": final_text,
        "stderr": parsed["nonJsonStderr"] or stderr_text,
        "codexStdoutRaw": stdout_text,
        "codexStderrRaw": stderr_text,
        "codexEventsJsonl": parsed["eventsJsonl"],
        "codexLastMessage": last_message_text,
        "codexTrace": {
            "provider": "openai",
            "backend": "codex-exec",
            "auth": "codex-cli-subscription",
            "model": model,
            "searchEnabled": search,
            "sandbox": sandbox,
            "networkAccess": network,
            "reasoningEffort": reasoning_effort,
            "timeoutSeconds": timeout_seconds,
            "timedOut": timed_out,
            "timeoutReason": timeout_reason,
            "terminatedAfterOutput": terminated_after_output,
            "processReturnCode": process_return_code,
            "effectiveReturnCode": effective_return_code,
            "usage": parsed["usage"],
            "eventCount": len(parsed["events"]),
            "lastError": parsed["lastError"],
            **({"redactionFailures": redaction_failures} if redaction_failures else {}),
        },
    }


def command_hash(command_result: dict[str, Any] | None) -> str | None:
    if not command_result:
        return None
    return sha256_bytes(json.dumps(command_result.get("argv", [])).encode())


def append_command_artifacts(
    refs: list[dict[str, Any]],
    out_dir: pathlib.Path,
    *,
    prefix: str,
    command_result: dict[str, Any],
    created_at: str,
    stdout_artifact_type: str = "stdout",
    generation_ticket: dict[str, str] | None = None,
) -> dict[str, Any]:
    command_ticket = None
    if generation_ticket is not None:
        binding = ticket_manifest_binding(generation_ticket)
        command_ticket = {
            "ticketId": binding["ticketId"],
            "ticketPath": binding["ticketPath"],
        }
    refs.append(
        write_artifact(
            out_dir,
            "command",
            f"{prefix}command.json",
            json.dumps(
                {
                    "backend": command_result["backend"],
                    "argv": [redact_text(str(arg)) for arg in command_result["argv"]],
                    **(
                        {"generationTicket": command_ticket}
                        if command_ticket is not None
                        else {}
                    ),
                    **(
                        {"networkAccess": command_result["networkAccess"]}
                        if "networkAccess" in command_result
                        else {}
                    ),
                    **(
                        {"timeoutSeconds": command_result["timeoutSeconds"]}
                        if "timeoutSeconds" in command_result
                        else {}
                    ),
                    **(
                        {"workspaceMutations": command_result["workspaceMutations"]}
                        if "workspaceMutations" in command_result
                        else {}
                    ),
                    "returnCode": command_result["returnCode"],
                    "processReturnCode": command_result.get("processReturnCode"),
                    **(
                        {"redactionFailures": command_result["redactionFailures"]}
                        if command_result.get("redactionFailures")
                        else {}
                    ),
                    "timedOut": command_result.get("timedOut", False),
                    "timeoutReason": command_result.get("timeoutReason"),
                    "terminatedAfterOutput": command_result.get(
                        "terminatedAfterOutput"
                    ),
                    "startedAt": command_result["startedAt"],
                    "finishedAt": command_result["finishedAt"],
                },
                indent=2,
            ),
            created_at,
        )
    )
    if command_result.get("codexStdoutRaw") is not None:
        refs.append(
            write_artifact(
                out_dir,
                "codex_stdout_jsonl",
                f"{prefix}codex_stdout.jsonl",
                command_result["codexStdoutRaw"],
                created_at,
            )
        )
    if command_result.get("codexStderrRaw") is not None:
        refs.append(
            write_artifact(
                out_dir,
                "codex_stderr_log",
                f"{prefix}codex_stderr.log",
                command_result["codexStderrRaw"],
                created_at,
            )
        )
    if command_result.get("codexEventsJsonl") is not None:
        refs.append(
            write_artifact(
                out_dir,
                "codex_events_jsonl",
                f"{prefix}codex_events.jsonl",
                command_result["codexEventsJsonl"],
                created_at,
            )
        )
    if command_result.get("codexLastMessage") is not None:
        refs.append(
            write_artifact(
                out_dir,
                "codex_last_message",
                f"{prefix}codex_last_message.txt",
                command_result["codexLastMessage"],
                created_at,
            )
        )
    if command_result.get("codexTrace") is not None:
        refs.append(
            write_artifact(
                out_dir,
                "codex_trace",
                f"{prefix}codex_trace.json",
                json.dumps(command_result["codexTrace"], indent=2),
                created_at,
            )
        )
    stdout_ref = write_artifact(
        out_dir,
        stdout_artifact_type,
        f"{prefix}stdout.txt",
        command_result["stdout"],
        created_at,
    )
    refs.append(stdout_ref)
    refs.append(
        write_artifact(
            out_dir,
            "stderr",
            f"{prefix}stderr.txt",
            command_result["stderr"],
            created_at,
        )
    )
    return stdout_ref


def build_pre_submit_review_prompt(
    *,
    series: str,
    period: str,
    conditional: str | None,
    target_context: dict[str, Any] | None,
    original_prompt: str,
    draft_response: str,
) -> str:
    conditional_line = conditional if conditional else "null"
    target_context_block = format_target_context(target_context)
    target_context_text = f"\n{target_context_block}\n" if target_context_block else ""
    return (
        "# Thesis pre-submit forecast review\n\n"
        "You are a reviewer for a forecast before publication. Review the "
        "draft forecast, the target spec, cited public evidence, and any "
        "relevant local repo context or prior traces if useful. This extra "
        "context is optional; do not require it when the draft is already "
        "clear. Do not use future outcomes, private knowledge, or hidden "
        "chain-of-thought. Do not produce a replacement forecast.\n\n"
        "# Target\n"
        f"- series: {series}\n"
        f"- period: {period}\n"
        f"- conditional: {conditional_line}\n\n"
        f"{target_context_text}"
        "# Rubric\n"
        "Check these items and name concrete fixes when needed:\n"
        "1. Exact resolver, source, first-print rule, and resolution date.\n"
        "2. Base-rate or persistence prior stated before inside-view updates.\n"
        "3. Time-series/model prior used or explicitly ruled out.\n"
        "4. Current evidence justifies material movement from the prior.\n"
        "5. Interval size comes from realized volatility or explicit uncertainty.\n"
        "6. A compact Prior/update/interval step names the prior, historical "
        "sample, adjustment components, interval method, and implied bounds.\n"
        "7. Tail scenarios are concrete and tied to the target.\n"
        "8. Point, interval, final forecast step, and JSON fields are coherent.\n"
        "9. No leakage, catalog point/interval circularity, subjective "
        "resolver, or unit ambiguity.\n\n"
        "# Required response\n"
        "Return JSON only, with this shape:\n"
        "{\n"
        '  "summary": "one sentence",\n'
        '  "requiredFixes": [\n'
        "    {\n"
        '      "rubricItem": "resolver|base_rate|model_prior|update|'
        'interval|prior_update_interval|tails|coherence|leakage",\n'
        '      "severity": "warning|blocking",\n'
        '      "summary": "specific issue",\n'
        '      "actionRequested": "specific change requested"\n'
        "    }\n"
        "  ],\n"
        '  "optionalSuggestions": ["short suggestions"]\n'
        "}\n\n"
        "# Original forecaster prompt hash material\n"
        f"{sha256_bytes(original_prompt.encode())}\n\n"
        "# Draft forecast response\n"
        f"{draft_response}\n"
    )


def build_revision_prompt(
    *,
    original_prompt: str,
    draft_response: str,
    review_response: str,
) -> str:
    return (
        f"{original_prompt}\n\n"
        "# Pre-submit review loop\n\n"
        "You already drafted the response below. A reviewer then checked the "
        "draft against the Thesis rubric. Produce the final JSON forecast now.\n\n"
        "Rules for the final submission:\n"
        "- Return exactly one JSON object and no Markdown.\n"
        "- Use only pre-resolution public evidence available to the draft.\n"
        "- Accept reviewer fixes only when they improve resolver clarity, "
        "source grounding, base-rate discipline, uncertainty calibration, or "
        "internal coherence.\n"
        "- Add a public reasoning text step beginning with "
        '"Review disposition:" that states which critique items were accepted '
        "or rejected. Keep this concise; do not reveal hidden chain-of-thought.\n"
        "- Put the Review disposition text step before the final forecast step.\n"
        "- The final reasoning step must be the forecast step, and its numbers "
        "must exactly match pointEstimate, ciLow, and ciHigh.\n\n"
        "# Draft forecast response\n"
        f"{draft_response}\n\n"
        "# Reviewer critique\n"
        f"{review_response}\n\n"
        "Emit the final JSON object only.\n"
    )


def parse_review_payload(text: str) -> dict[str, Any]:
    try:
        payloads = extract_json_payload(text)
    except ValueError:
        return {
            "summary": text.strip().splitlines()[0][:240] if text.strip() else "",
            "requiredFixes": [],
            "optionalSuggestions": [],
        }
    payload = payloads[0] if payloads else {}
    return payload if isinstance(payload, dict) else {}


def build_pre_submit_review_metadata(
    *,
    status: str,
    requested_at: str,
    review_result: dict[str, Any] | None,
    review_payload: dict[str, Any] | None,
    draft_ref: dict[str, Any] | None,
    review_ref: dict[str, Any] | None,
    revision_prompt_ref: dict[str, Any] | None,
    normalized_cells: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    def _review_collection(value: Any) -> list[Any]:
        # Reviewer-agent JSON may hand back a scalar, string, or object
        # where a list belongs: list() on a number raises after
        # validation (losing the run record), and list() on a string
        # explodes it into per-character findings. Anything non-list
        # becomes a single malformed row for the item guard below.
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    fixes = _review_collection((review_payload or {}).get("requiredFixes"))
    suggestions = _review_collection((review_payload or {}).get("optionalSuggestions"))
    findings: list[dict[str, Any]] = []
    for index, fix in enumerate(fixes):
        if not isinstance(fix, dict):
            # Malformed reviewer output (a bare number or string in the
            # list) is still a finding worth keeping — never a crash
            # that loses the run record.
            fix = {"summary": str(fix)}
        findings.append(
            {
                "findingId": f"review.finding.{index + 1}",
                "severity": str(fix.get("severity") or "warning"),
                "rubricItem": str(fix.get("rubricItem") or "review"),
                # A dict row with no usable summary still leaves its
                # content in the record rather than an empty finding.
                "summary": str(fix.get("summary") or "").strip() or str(fix),
                "actionRequested": str(fix.get("actionRequested") or "").strip()
                or None,
            }
        )
    for index, suggestion in enumerate(suggestions):
        findings.append(
            {
                "findingId": f"review.suggestion.{index + 1}",
                "severity": "info",
                "rubricItem": "optional_suggestion",
                "summary": str(suggestion).strip(),
            }
        )

    disposition_text = extract_review_disposition(normalized_cells or [])
    dispositions = [
        {
            "findingId": finding["findingId"],
            "decision": (
                "accepted"
                if disposition_text and finding["severity"] != "info"
                else "not_applicable"
            ),
            "rationale": disposition_text
            or "No explicit review disposition was found in the final public trace.",
            "forecastChanged": bool(disposition_text and finding["severity"] != "info"),
        }
        for finding in findings
    ]

    summary = str((review_payload or {}).get("summary") or "").strip()
    if not summary:
        summary = (
            "Pre-submit review completed and was recorded before publication."
            if status == "completed"
            else f"Pre-submit review status: {status.replace('_', ' ')}."
        )

    return without_none(
        {
            "schemaVersion": "thesis_pre_submit_review_v1",
            "status": status,
            "requestedAt": requested_at,
            "reviewer": {
                "agent": "thesis.pre_submit_reviewer",
                "model": infer_command_model(review_result),
                "promptVersion": "pre-submit-review-v0.1",
                "commandHash": command_hash(review_result),
            },
            "draftArtifactPath": draft_ref.get("path") if draft_ref else None,
            "reviewArtifactPath": review_ref.get("path") if review_ref else None,
            "revisionPromptPath": (
                revision_prompt_ref.get("path") if revision_prompt_ref else None
            ),
            "findings": findings,
            "dispositions": dispositions,
            "summary": summary,
        }
    )


def without_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: without_none(entry)
            for key, entry in value.items()
            if entry is not None
        }
    if isinstance(value, list):
        return [without_none(entry) for entry in value]
    return value


def extract_review_disposition(cells: list[dict[str, Any]]) -> str | None:
    for cell in cells:
        for step in cell.get("reasoning", []):
            if not isinstance(step, dict):
                continue
            text = str(step.get("text") or "")
            if text.lower().startswith("review disposition:"):
                return text
    return None


def infer_command_model(command_result: dict[str, Any] | None) -> str | None:
    if not command_result:
        return None

    argv = command_result.get("argv") or []
    for index, arg in enumerate(argv):
        if arg in {"-m", "--model"} and index + 1 < len(argv):
            return str(argv[index + 1])
        if isinstance(arg, str) and arg.startswith("--model="):
            return arg.split("=", 1)[1]

    stderr = str(command_result.get("stderr") or "")
    match = re.search(r"(?im)^model:\s*(\S+)\s*$", stderr)
    return match.group(1) if match else None


def stamp_runtime_invocation(
    meta: dict[str, Any],
    command_result: dict[str, Any] | None,
) -> dict[str, Any]:
    runtime_meta = dict(meta)
    runtime_model = infer_command_model(command_result)
    if runtime_model and runtime_model != runtime_meta.get("model"):
        runtime_meta["configuredModel"] = runtime_meta.get("model")
        runtime_meta["model"] = runtime_model
    return runtime_meta


def registration_binding(
    target_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not target_context:
        return {}
    return {
        key: target_context[key]
        for key in (
            "registrationCommit",
            "targetContentHash",
            "targetRegistrationPath",
            "registeredAtUtc",
        )
        if target_context.get(key) not in (None, "")
    }


def pin_comparison_contract(
    cell: dict[str, Any],
    target_context: dict[str, Any] | None,
) -> None:
    """Comparison cells are graded against the published target's resolution
    contract, so the sealed cell carries that contract verbatim; the model's
    own resolver wording stays in the parsed cells and trace. Units are
    deliberately not pinned — a unit drift must fail validation rather than
    relabel the forecast numbers."""

    if not target_context or target_context.get("comparisonTarget") is not True:
        return
    for cell_key, context_key in (
        ("slug", "catalogSlug"),
        ("country", "country"),
        ("resolutionDate", "resolutionDate"),
        ("resolutionSource", "resolutionSource"),
        ("resolutionSourceUrl", "resolutionSourceUrl"),
        ("resolutionRule", "resolutionRule"),
    ):
        value = target_context.get(context_key)
        if value not in (None, ""):
            cell[cell_key] = value


def write_failure_manifest(
    out_dir: pathlib.Path,
    run_at: str,
    args: argparse.Namespace,
    meta: dict[str, Any],
    refs: list[dict[str, Any]],
    phase: str,
    message: str,
    command_result: dict[str, Any] | None,
    target_context: dict[str, Any] | None = None,
    *,
    checkout_sha: str | None = None,
    generation_ticket: dict[str, str] | None = None,
) -> dict[str, Any]:
    error = {
        "phase": phase,
        "message": message,
        "command": (
            {
                "returnCode": command_result["returnCode"],
                "timedOut": command_result.get("timedOut", False),
            }
            if command_result
            else None
        ),
    }
    refs.append(
        write_artifact(
            out_dir,
            "error",
            "error.json",
            json.dumps(error, indent=2),
            run_at,
        )
    )
    manifest = {
        "schemaVersion": "thesis_analyst_run_manifest_v1",
        "createdAt": run_at,
        "runStartedAt": run_at,
        "series": args.series,
        "period": args.period,
        "conditional": args.conditional,
        "targetContext": target_context,
        **registration_binding(target_context),
        "promptMode": args.prompt_mode,
        "agent": meta,
        "ok": False,
        "cellsPath": None,
        "artifacts": refs,
        "validation": None,
        "error": error,
    }
    return finalize_manifest(
        out_dir,
        run_at,
        manifest,
        refs,
        checkout_sha=checkout_sha,
        generation_ticket=generation_ticket,
    )


def extract_json_payload(text: str) -> list[dict]:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.S)
    if fenced:
        stripped = fenced.group(1).strip()

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            payload, _end = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list) and all(
            isinstance(item, dict) for item in payload
        ):
            return payload
    raise ValueError("No JSON object or array found in agent output")


def _reject_unencodable_numbers(value: Any, path: str = "cell") -> None:
    """Refuse numbers later stages cannot canonicalize or seal.

    Oversized integers overflow float conversion at seal time and
    non-finite or near-overflow floats crash custody canonicalization —
    both AFTER the guarded stages, leaving no run record. Catching them
    here turns the whole class into ordinary normalize failures.
    """

    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > 2**53:
            raise RuntimeError(
                f"{path} carries an integer outside the exactly representable range"
            )
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise RuntimeError(f"{path} carries a non-finite number")
        if abs(value) > 1e300:
            raise RuntimeError(f"{path} carries a float too large to canonicalize")
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_unencodable_numbers(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unencodable_numbers(item, f"{path}[{index}]")


def normalize_cells(parsed_path: pathlib.Path, normalized_path: pathlib.Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "normalize_spawn_json.py"),
            str(parsed_path),
            str(normalized_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "normalize_spawn_json.py failed:\n"
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )


def seal_normalized_cells(
    cells: list[dict[str, Any]],
    *,
    conditional: str | None,
    run_started_at: str,
    sealed_at: str,
    prompt_mode: str,
    target_context: dict[str, Any] | None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Apply every trusted post-normalization stamp and materialize CDFs."""

    if conditional:
        for cell in cells:
            cell["type"] = "conditional"
    binding = registration_binding(target_context)
    for cell in cells:
        agent_run_at = cell.get("runAt")
        if agent_run_at and agent_run_at != sealed_at:
            cell["agentReportedRunAt"] = agent_run_at
        cell["runStartedAt"] = run_started_at
        cell["runAt"] = sealed_at
        cell["promptMode"] = prompt_mode
        cell.update(binding)
        pin_comparison_contract(cell, target_context)
    return materialize_run_distributions(cells)


def validate_cells(
    cells: list[dict],
    allow_existing_slug: bool = False,
    target_context: dict[str, Any] | None = None,
    prompt_mode: str = "full",
    collision_exclusion: pathlib.Path | None = None,
    generation_ticket: dict[str, Any] | None = None,
    agent_version: Any = HISTORY_FLOOR_AGENT_VERSION,
    checkout_sha: Any = None,
    series: Any = None,
    target_period: Any = None,
    history_registry_root: pathlib.Path | None = None,
) -> dict[str, Any]:
    sys.path.insert(0, str(SCRIPTS))
    try:
        from spawned_cells_to_ts import existing_slugs, validate  # type: ignore
    finally:
        if sys.path[0] == str(SCRIPTS):
            sys.path.pop(0)

    taken = existing_slugs(
        ROOT / "site" / "src" / "data",
        collision_exclusion or ROOT / "__runner__.ts",
    )
    seen: set[str] = set()
    rows = []
    ok = True
    trusted_history_authorization = None
    authorization_error = None
    if any(history_floor_requires_authorization(cell, agent_version) for cell in cells):
        try:
            trusted_history_authorization = reviewed_history_floor_authorization(
                history_registry_root or ROOT,
                checkout_sha=checkout_sha,
                series=series,
                target_period=target_period,
            )
        except ValueError as exc:
            authorization_error = str(exc)
    for cell in cells:
        errors = validate(
            cell,
            taken | seen,
            target_context=target_context,
            generation_ticket=generation_ticket,
            agent_version=agent_version,
            trusted_history_authorization=trusted_history_authorization,
        )
        if allow_existing_slug:
            errors = [error for error in errors if "slug collides" not in error]
        if authorization_error:
            errors.append(
                "cannot authenticate reviewed history-floor authorization: "
                + authorization_error
            )
        errors.extend(target_context_validation_errors(cell, target_context))
        if prompt_mode in {"ladder", "ladder_v2"}:
            errors.extend(ladder_validation_errors(cell))
        if errors:
            ok = False
        else:
            seen.add(cell["slug"])
        rows.append({"slug": cell.get("slug", "?"), "ok": not errors, "errors": errors})
    return {"ok": ok, "cells": rows}


def target_context_validation_errors(
    cell: dict[str, Any],
    target_context: dict[str, Any] | None,
) -> list[str]:
    if not target_context:
        return []
    checks = [
        ("catalogSlug", "slug"),
        ("country", "country"),
        ("targetUnit", "unit"),
        ("dataPointId", "dataPointId"),
        ("resolutionDate", "resolutionDate"),
        ("targetRegistrationPath", "targetRegistrationPath"),
        ("targetContentHash", "targetContentHash"),
        ("registrationCommit", "registrationCommit"),
        ("registeredAtUtc", "registeredAtUtc"),
        # A preregistered conditional arm binds the exact legal-state text;
        # the model must repeat it verbatim in conditionalOn, or the site's
        # exact-match condition registry could not gate the published cell.
        ("conditional", "conditionalOn"),
    ]
    errors = []
    for context_key, cell_key in checks:
        if (
            context_key == "resolutionDate"
            and target_context.get("resolutionDateBasis") == "resolve-by-bound"
        ):
            # The bounded branch below owns the required, canonical bound and
            # its byte equality. Calendar/default targets keep this literal
            # target-context comparison unchanged.
            continue
        expected = target_context.get(context_key)
        if expected in (None, ""):
            continue
        actual = cell.get(cell_key)
        if not canonical_equal(actual, expected):
            errors.append(
                f"{cell_key} {actual!r} does not match target context "
                f"{context_key} {expected!r}"
            )
    binding = target_context.get("sourceBinding")
    if isinstance(binding, dict) and binding.get("sourceUrl"):
        allowed = {
            (urlparse(str(url)).hostname or "").lower()
            for url in (
                binding.get("allowedHosts")
                and [f"https://{h}" for h in binding["allowedHosts"]]
                or [binding["sourceUrl"]]
            )
        }
        allowed.discard("")
        actual_host = (
            urlparse(str(cell.get("resolutionSourceUrl") or "")).hostname or ""
        ).lower()
        if not allowed or actual_host not in allowed:
            errors.append(
                "resolutionSourceUrl host "
                f"{actual_host!r} is not among the preregistered source "
                f"binding hosts {sorted(allowed)!r}"
            )
    errors.extend(first_print_resolution_rule_errors(cell, target_context))
    errors.extend(bounded_announcement_errors(cell, target_context))
    errors.extend(history_anchor_errors(cell, target_context))
    return errors


def bounded_announcement_errors(
    cell: dict[str, Any],
    target_context: dict[str, Any],
) -> list[str]:
    """Require cell byte-echoes for a resolve-by-bound target.

    The attested publisher authenticates the actual announcement fetch from
    raw Codex draft/final events.  Model-authored reasoning tokens are not
    fetch evidence.
    """

    basis = target_context.get("resolutionDateBasis", "release-calendar")
    if basis == "release-calendar":
        return []
    if basis != "resolve-by-bound":
        return [f"unsupported target resolutionDateBasis {basis!r}"]
    errors = []
    registered_bound = target_context.get("resolutionDate")
    canonical_bound = False
    if isinstance(registered_bound, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", registered_bound
    ):
        try:
            canonical_bound = (
                datetime.strptime(registered_bound, "%Y-%m-%d").date().isoformat()
                == registered_bound
            )
        except ValueError:
            canonical_bound = False
    if not canonical_bound:
        errors.append(
            "resolve-by-bound target has no canonical registered resolutionDate bound"
        )
    elif cell.get("resolutionDate") != registered_bound:
        errors.append(
            "resolutionDate must byte-echo the registered resolve-by bound "
            f"{registered_bound!r}"
        )
    binding = target_context.get("sourceBinding")
    announcement_url = binding.get("sourceUrl") if isinstance(binding, dict) else None
    if not isinstance(announcement_url, str) or not announcement_url:
        errors.append(
            "resolve-by-bound target has no registered official announcement "
            "URL in sourceBinding.sourceUrl"
        )
        return errors

    if cell.get("resolutionSourceUrl") != announcement_url:
        errors.append(
            "resolutionSourceUrl must byte-echo the resolve-by-bound official "
            f"announcement URL {announcement_url!r}"
        )
    return errors


def history_anchor_errors(
    cell: dict[str, Any],
    target_context: dict[str, Any],
) -> list[str]:
    """Fail closed when fetched history contradicts operator-verified anchors.

    `anchors` in the target context maps a period token to the official value
    verified out-of-band from the resolver's own source. Current cells match
    that token through their canonical period object. Pre-2.5.10 cells retain
    the hardened label parser below for replay compatibility.
    Anchors are deliberately NOT injected into the prompt
    (format_target_context omits the key): the agent must fetch its base
    rate independently, and this gate refuses runs whose fetched values
    carry a wrong series, vintage, or artifact-derived lineage — the
    spawn-time mirror of the resolve-time anchor checks in
    resolve_pending.py. An anchored period must appear in the history, and
    at least one entry mentioning it must match the anchor within
    max(0.5%, 0.05) — the slack covers rounding, never a vintage swap.
    """
    anchors = target_context.get("anchors")
    if not isinstance(anchors, dict) or not anchors:
        return []
    history = cell.get("historicalContext") or []
    errors = []

    quarter_key = re.compile(r"^(\d{4})[-_ ]?[Qq]([1-4])$|^[Qq]([1-4])[-_ ]?(\d{4})$")
    strict_cluster = re.compile(r"^(\d{4})[- ]?[Qq]([1-4])$|^[Qq]([1-4])[- ]?(\d{4})$")

    # Raw non-ASCII non-letter content folds to this sentinel instead
    # of its NFKC image, so a fullwidth ！ cannot launder into ASCII
    # prose before gap classification (review round eight: 430 of 437
    # compatibility characters bypassed that way). Private-use, so the
    # raw-label guard has already rejected any genuine occurrence.
    poison_mark = "\ue000"

    def fold(label: str) -> str:
        chars = []
        for ch in label:
            if not ch.isascii():
                cat = unicodedata.category(ch)
                if cat == "Nd":
                    # True decimal digits fold to ASCII.
                    chars.append(str(unicodedata.digit(ch)))
                    continue
                if not ch.isalpha():
                    # Symbols, punctuation, and No/Nl numerals keep
                    # their taint through folding.
                    chars.append(poison_mark)
                    continue
                # Letters (including fullwidth Ｑ) fold normally.
                chars.append(unicodedata.normalize("NFKC", ch))
                continue
            chars.append(ch)
        folded = unicodedata.normalize("NFKC", "".join(chars))
        folded = re.sub(r"[‐‑‒–—―−]", "-", folded)
        return re.sub(r"\s+", " ", folded)

    cluster_chars = set("0123456789IVXivxQq")
    cluster_seps = set(" -/._()")

    def quarter_label_tokens(label: str) -> set[str] | None:
        """Whitelist-only quarter reading of a history label.

        Returns the canonical quarter tokens the label names, or None
        to REJECT it. Grammar (review rounds four and five): the folded
        label splits into maximal cluster-alphabet segments; segments
        connected by pure separator RUNS form a group. A group that
        contains a Q and any numeral content (digit or Roman) is
        quarter-relevant, and EVERY segment in it must itself be a
        whitelisted strict token — an orphan numeral, year, or Roman
        chained beside a quarter ("2026 Q1 / 2", "2027 (2026 Q1)")
        rejects the label, while "2026 Q1 (2026Q1)" stays open because
        both segments are strict. A bare Q with no numeral content in
        its group is prose ("Grade Q") and free. Format characters
        reject outright; ANY non-ASCII character immediately beside a
        digit or Q rejects (confusables, fraction slashes, combining
        marks); a Q-bearing segment glued to an ASCII letter (FY2026
        Q1) rejects as a qualified designator.
        """

        # Reject invisible and control machinery outright: format
        # characters split designators; ASCII controls (NUL, ESC, DEL)
        # survive whitespace folding and split "Q2" into ignored
        # pieces. Ordinary \t\n\r are whitespace and fold to spaces.
        for ch in label:
            cat = unicodedata.category(ch)
            if cat == "Cf" or cat in ("Co", "Cs", "Cn"):
                return None
            if cat == "Cc" and ch not in "\t\n\r":
                return None
        folded = fold(label)
        n = len(folded)
        for i, ch in enumerate(folded):
            if ch in "0123456789Qq":
                for j in (i - 1, i + 1):
                    if 0 <= j < n and not folded[j].isascii():
                        return None
                    if 0 <= j < n and folded[j] == poison_mark:
                        return None

        # Segment the label: cluster-alphabet runs, with the prose rule
        # for letter-class members — a Roman-numeral letter (i/v/x) or a
        # Q whose immediate neighbor is an ASCII letter outside the
        # cluster alphabet belongs to a word ("value", "in", "Grade Q"?
        # — Q handles its own rule below), not a designator. Without
        # this, "2026 Q1 value" and the real G.19 label "2026 Q1 in Fed
        # G.19 table" would falsely reject on the 'v'/'i'.
        # Word-level Roman rule (round eight): an i/v/x participates
        # only when its entire maximal ASCII-letter run is Roman/Q
        # material — "vintage" and "via" are words even though they
        # open with Roman letters; "xiv" and "QIV" are designators.
        letter_run_ok = [False] * n
        i0 = 0
        while i0 < n:
            if folded[i0].isascii() and folded[i0].isalpha():
                j0 = i0
                while j0 < n and folded[j0].isascii() and folded[j0].isalpha():
                    j0 += 1
                run_is_roman = all(c in "IVXivxQq" for c in folded[i0:j0])
                for k in range(i0, j0):
                    letter_run_ok[k] = run_is_roman
                i0 = j0
            else:
                i0 += 1

        def is_member(i: int) -> bool:
            ch = folded[i]
            if ch not in cluster_chars:
                return False
            if ch in "IVXivx" and not letter_run_ok[i]:
                return False
            return True

        segments: list[tuple[int, int]] = []  # [start, end) spans
        i = 0
        while i < n:
            if is_member(i):
                j = i
                while j < n and is_member(j):
                    j += 1
                segments.append((i, j))
                i = j
            else:
                i += 1

        def gap_kind(a: int, b: int) -> str:
            """Classify the text between segments: 'chain' (pure
            separators), 'break' (contains an ASCII letter — prose
            boundary), or 'poison' (anything else, e.g. a fraction
            slash or symbol buffered by separators — content we cannot
            read, chaining the sides AND tainting the group)."""
            gap = folded[a:b]
            if all(c in cluster_seps for c in gap):
                return "chain"
            # Poison DOMINATES: the fold sentinel (raw non-ASCII
            # non-letter content) taints the gap even alongside prose —
            # "and ⁄" must not launder the slash. Letters of ANY script
            # are prose (bilingual labels, spaced confusables per the
            # round-eight ruling), and readable ASCII (commas,
            # semicolons) separates like a sentence does.
            if poison_mark in gap:
                return "poison"
            if any(c.isalpha() or (c.isascii() and c not in cluster_seps) for c in gap):
                return "break"
            return "poison"

        groups: list[list[tuple[int, int]]] = []
        poisoned: list[bool] = []
        for span in segments:
            if groups:
                kind = gap_kind(groups[-1][-1][1], span[0])
                if kind in ("chain", "poison"):
                    groups[-1].append(span)
                    if kind == "poison":
                        poisoned[-1] = True
                    continue
            groups.append([span])
            poisoned.append(False)

        tokens: set[str] = set()
        for group, group_poisoned in zip(groups, poisoned):
            text_parts = [folded[a:b] for a, b in group]
            has_q = any(("Q" in part or "q" in part) for part in text_parts)
            has_numeral = any(
                c in "0123456789IVXivx" for part in text_parts for c in part
            )
            if not (has_q and has_numeral):
                continue
            if group_poisoned:
                return None
            first_start = group[0][0]
            last_end = group[-1][1]
            before = folded[first_start - 1] if first_start > 0 else ""
            after = folded[last_end] if last_end < n else ""
            if (before.isascii() and before.isalpha()) or (
                after.isascii() and after.isalpha()
            ):
                return None
            # Greedy pairing: a segment that alone fullmatches a strict
            # token consumes itself; a year+quarter segment pair split
            # by exactly one space/hyphen consumes both; anything left
            # over — orphan numerals, years, Romans — rejects.
            idx = 0
            while idx < len(group):
                a1, b1 = group[idx]
                seg = folded[a1:b1]
                if strict_cluster.fullmatch(seg):
                    m = strict_cluster.fullmatch(seg)
                    year = m.group(1) or m.group(4)
                    quarter = m.group(2) or m.group(3)
                    tokens.add(f"{year}q{quarter}")
                    idx += 1
                    continue
                if idx + 1 < len(group):
                    a2, b2 = group[idx + 1]
                    if b1 + 1 == a2 and folded[b1] in " -":
                        joined = folded[a1:b2]
                        m = strict_cluster.fullmatch(joined)
                        if m:
                            year = m.group(1) or m.group(4)
                            quarter = m.group(2) or m.group(3)
                            tokens.add(f"{year}q{quarter}")
                            idx += 2
                            continue
                return None
            # idx loop consumed everything or rejected.
        return tokens

    def canonical_quarters(match_iter) -> set[str]:
        result = set()
        for m in match_iter:
            year = m.group(1) or m.group(4)
            quarter = m.group(2) or m.group(3)
            result.add(f"{year}q{quarter}")
        return result

    def mentions(key: str, label: str) -> bool:
        # Quarter keys never take the literal shortcut; the label is
        # read by the whitelist-only cluster grammar above and counts
        # only when it names exactly ONE distinct quarter equal to the
        # key's. Motivating case: the 2026-08-12 BEA ITA run fetched
        # the byte-exact official value labeled "2026 Q1" and was
        # refused against "2026-Q1" on hyphen-versus-space. Non-quarter
        # keys keep literal-substring semantics; the value check below
        # is unchanged.
        key_match = quarter_key.fullmatch(key.strip())
        if key_match is None:
            return key in label
        tokens = quarter_label_tokens(label)
        if tokens is None or len(tokens) != 1:
            return False
        return tokens == canonical_quarters([key_match])

    def canonical_period_mentions(key: str, period: Any) -> bool:
        identity = canonical_period_identity(period)
        if identity is None:
            return False
        period_type, period_value = identity
        stripped = key.strip()
        if period_type == "quarter":
            key_match = quarter_key.fullmatch(stripped)
            if key_match is None:
                return False
            year = key_match.group(1) or key_match.group(4)
            quarter = key_match.group(2) or key_match.group(3)
            return period_value == f"{year}-Q{quarter}"
        if period_type in {"month", "year", "fiscal_year", "week_ending"}:
            return period_value == stripped
        return False

    for key, expected_raw in anchors.items():
        try:
            expected = float(expected_raw)
        except (TypeError, ValueError):
            errors.append(f"anchor {key!r}: non-numeric anchor value {expected_raw!r}")
            continue
        tolerance = max(abs(expected) * 0.005, 0.05)
        mentioned = [
            entry
            for entry in history
            if isinstance(entry, dict)
            and (
                canonical_period_mentions(str(key), entry.get("period"))
                if "period" in entry
                else mentions(str(key), str(entry.get("label", "")))
            )
        ]
        if not mentioned:
            errors.append(
                f"anchor {key!r}: no historicalContext entry mentions this "
                "period — anchored periods must appear in the fetched base rate"
            )
            continue
        values = []
        for entry in mentioned:
            try:
                values.append(float(entry.get("value")))
            except (TypeError, ValueError):
                continue
        if not any(abs(value - expected) <= tolerance for value in values):
            errors.append(
                f"anchor {key!r}: history value(s) {values} contradict the "
                f"verified official value {expected} (tolerance {tolerance:g}) "
                "— wrong series, vintage, or source lineage"
            )
    return errors


def first_print_resolution_rule_errors(
    cell: dict[str, Any],
    target_context: dict[str, Any],
) -> list[str]:
    target_rule = str(target_context.get("resolutionRule") or "")
    if not is_strict_first_print_rule(target_rule):
        return []
    cell_rule = str(cell.get("resolutionRule") or "")
    target_lower = target_rule.lower()
    cell_lower = cell_rule.lower()
    forbidden_phrases = [
        "same release day",
        "same-day",
        "release-day grace",
        "corrected before release day ends",
        "unless cms corrects",
        "unless the agency corrects",
    ]
    errors = []
    for phrase in forbidden_phrases:
        if phrase in cell_lower and phrase not in target_lower:
            errors.append(
                "resolutionRule adds correction/grace exception not present "
                f"in target context: {phrase!r}"
            )
    return errors


def is_strict_first_print_rule(rule: str) -> bool:
    lower = rule.lower()
    return any(
        token in lower
        for token in [
            "first print",
            "first-print",
            "first publishes",
            "first published",
            "first-published",
            "original (o)",
        ]
    )


def attach_activity_log(
    cells: list[dict],
    refs: list[dict],
    meta: dict[str, Any],
    pre_submit_review: dict[str, Any] | None = None,
    *,
    force_model: bool = False,
) -> list[dict]:
    output = []
    for cell in cells:
        row = {
            **cell,
            "model": (
                meta.get("model")
                if force_model
                else cell.get("model", meta.get("model"))
            ),
            "activityLog": refs,
        }
        if pre_submit_review:
            row["preSubmitReview"] = pre_submit_review
        output.append(row)
    return output


def write_ts_module(
    cells_path: pathlib.Path,
    out_ts: pathlib.Path,
    const_name: str,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "spawned_cells_to_ts.py"),
            str(out_ts),
            const_name,
            str(cells_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "spawned_cells_to_ts.py failed:\n"
            f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
        )


def mock_cell(series: str, period: str, run_at: str) -> dict[str, Any]:
    slug = f"{slugify(series)}-{slugify(period)}"
    country = "UK" if series.startswith(("ons.", "boe.")) else "US"
    resolution_date = (
        datetime.now(timezone.utc).date() + timedelta(days=90)
    ).isoformat()
    point = 5.1
    ci_low = 4.6
    ci_high = 5.8
    return {
        "slug": slug,
        "country": country,
        "type": "data",
        "title": f"{series} {period}",
        "question": (
            f"What will the first-print value of {series} be for {period}, "
            "as published by the official source?"
        ),
        "unit": "percent",
        "pointEstimate": point,
        "ciLow": ci_low,
        "ciHigh": ci_high,
        "confidence": 0.8,
        "resolutionDate": resolution_date,
        "resolutionSource": "Official statistical release",
        "resolutionSourceUrl": "https://www.ons.gov.uk/",
        "resolutionRule": (
            "Resolves to the first published official value for the target "
            "series and period; later revisions do not change the result."
        ),
        "dataPointId": f"{series}.{slugify(period)}.first_print",
        "historicalContext": [
            {
                "period": {"type": "month", "value": "2025-01"},
                "label": "2025-01",
                "value": 4.9,
            },
            {
                "period": {"type": "month", "value": "2025-02"},
                "label": "2025-02",
                "value": 5.0,
            },
            {
                "period": {"type": "month", "value": "2025-03"},
                "label": "2025-03",
                "value": 5.1,
            },
            {
                "period": {"type": "month", "value": "2025-04"},
                "label": "2025-04",
                "value": 5.0,
            },
            {
                "period": {"type": "month", "value": "2025-05"},
                "label": "2025-05",
                "value": 5.1,
            },
            {
                "period": {"type": "month", "value": "2025-06"},
                "label": "2025-06",
                "value": 5.2,
            },
        ],
        "drivers": ["recent momentum", "release volatility", "labour-market slack"],
        "sourceContext": [
            "https://www.ons.gov.uk/",
            "https://www.nomisweb.co.uk/home/release_dates.asp",
        ],
        "runAt": run_at,
        "reasoning": [
            {"kind": "heading", "text": "Mock thesis.analyst dry run"},
            {
                "kind": "text",
                "text": (
                    "Reference class base rate from the last 6 prints is 5.1, "
                    "with recent values clustered between 4.9 and 5.2."
                ),
            },
            {
                "kind": "tool",
                "tool": "official.lookup",
                "call": f"official.lookup(series='{series}', period='{period}')",
                "result": (
                    "{t_minus_6: 4.9, t_minus_5: 5.0, t_minus_4: 5.1, "
                    "t_minus_3: 5.0, t_minus_2: 5.1, t_minus_1: 5.2}"
                ),
            },
            {
                "kind": "tool",
                "tool": "calendar.lookup",
                "call": f"calendar.lookup(series='{series}', period='{period}')",
                "result": (
                    f"{{resolution_date: '{resolution_date}', first_print: true}}"
                ),
            },
            {
                "kind": "math",
                "text": (
                    "Point = recent center 5.1. Realized month-to-month "
                    "volatility sigma = 0.45; 80% interval = point ± 1.28 × "
                    "sigma → [4.6, 5.8]."
                ),
            },
            {
                "kind": "text",
                "text": (
                    "Outside the interval if hiring weakens abruptly or the "
                    "survey mean-reverts faster than the recent prints imply."
                ),
            },
            {"kind": "forecast", "point": point, "ciLow": ci_low, "ciHigh": ci_high},
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--series", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--conditional")
    parser.add_argument("--target-context-json")
    parser.add_argument("--ticket-id")
    parser.add_argument("--ticket-path")
    parser.add_argument("--ticket-nonce")
    parser.add_argument(
        "--prompt-mode", choices=["full", "fast", "ladder", "ladder_v2"], default="full"
    )
    parser.add_argument("--out-dir")
    parser.add_argument("--command")
    parser.add_argument("--codex-model")
    parser.add_argument("--codex-sandbox", default="read-only")
    parser.add_argument("--codex-reasoning-effort", default="low")
    parser.add_argument("--no-codex-search", action="store_true")
    parser.add_argument(
        "--codex-network",
        action="store_true",
        help=(
            "Enable outbound network inside the Codex sandbox "
            "(sandbox_workspace_write.network_access=true) so the agent can "
            "curl official public data endpoints that the hosted web-search "
            "tool cannot fetch. Requires --codex-sandbox workspace-write; "
            "the runner then guards the workspace and fails the run closed "
            "on any file mutation outside the expected agent outputs. The "
            "fast/full prompts gain a fetch-honesty note; ladder modes do "
            "not (dispatch-only CI lanes keep their sealed contracts)."
        ),
    )
    parser.add_argument("--pre-submit-review-command")
    parser.add_argument("--pre-submit-review-codex-model")
    parser.add_argument("--pre-submit-review-codex-search", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--response-file")
    parser.add_argument("--mock-cell", action="store_true")
    parser.add_argument("--print-prompt", action="store_true")
    parser.add_argument("--allow-existing-slug", action="store_true")
    parser.add_argument("--write-ts")
    parser.add_argument("--const-name", default="SPAWNED_FORECAST_CELLS")
    return parser.parse_args()


def parse_generation_ticket_context(
    args: argparse.Namespace,
) -> dict[str, str] | None:
    values = (args.ticket_id, args.ticket_path, args.ticket_nonce)
    present = [value is not None for value in values]
    if any(present) and not all(present):
        raise SystemExit(
            "ticket mode requires --ticket-id, --ticket-path, and "
            "--ticket-nonce together"
        )
    if not any(present):
        return None
    if args.response_file is not None:
        raise SystemExit("ticket mode refuses --response-file")
    if args.mock_cell:
        raise SystemExit("ticket mode refuses --mock-cell")
    if args.command is not None:
        raise SystemExit("ticket mode refuses --command")
    if args.pre_submit_review_command is not None:
        raise SystemExit("ticket mode refuses --pre-submit-review-command")
    if "THESIS_CODEX_IDLE_TIMEOUT_SECONDS" in os.environ:
        raise SystemExit(
            "ticket mode refuses THESIS_CODEX_IDLE_TIMEOUT_SECONDS because "
            "timeout policy is ticket-sealed"
        )
    codex_override = os.getenv("THESIS_CODEX_BIN")
    if codex_override and pathlib.Path(codex_override).name != "codex":
        raise SystemExit(
            "ticket mode refuses THESIS_CODEX_BIN unless its executable basename "
            "is codex"
        )
    if not args.codex_model and not args.print_prompt:
        raise SystemExit("ticket mode requires --codex-model")
    context = {
        "ticketId": args.ticket_id,
        "ticketPath": args.ticket_path,
        "nonce": args.ticket_nonce,
    }
    try:
        ticket_manifest_binding(context)
    except TicketError as exc:
        raise SystemExit(f"invalid generation ticket context: {exc}") from exc
    return context


def workspace_checkout_sha() -> str:
    """Return the immutable checkout commit recorded at harness start."""

    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise RuntimeError(
            "cannot record workspace checkout SHA" + (f": {detail}" if detail else "")
        ) from exc
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError(f"workspace checkout SHA is not a commit: {sha!r}")
    return sha


def parse_target_context(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid --target-context-json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("--target-context-json must be a JSON object")
    try:
        # Trusted-input gate: a context carrying numbers canonical
        # hashing cannot represent would crash custody in EVERY later
        # stage, including the failure paths. Committed registrations
        # cannot contain them (they are canonical-encoded at creation),
        # so this only fires on operator error — refuse before any run
        # artifacts exist.
        _reject_unencodable_numbers(parsed, "target context")
    except RuntimeError as exc:
        raise SystemExit(f"Invalid --target-context-json: {exc}") from exc
    return parsed


def run_forecaster(
    args: argparse.Namespace,
    *,
    prompt: str,
    prompt_path: pathlib.Path,
    out_dir: pathlib.Path,
    prefix: str,
    announcement_url: str | None = None,
) -> dict[str, Any]:
    if args.codex_model:
        return run_codex_agent_command(
            prompt=prompt,
            timeout_seconds=args.timeout_seconds,
            model=args.codex_model,
            out_dir=out_dir,
            prefix=prefix,
            search=not args.no_codex_search,
            sandbox=args.codex_sandbox,
            reasoning_effort=args.codex_reasoning_effort,
            network=args.codex_network,
            announcement_url=announcement_url,
        )
    return run_agent_command(
        args.command,
        prompt,
        prompt_path,
        args.timeout_seconds,
    )


def run_pre_submit_reviewer(
    args: argparse.Namespace,
    *,
    prompt: str,
    prompt_path: pathlib.Path,
    out_dir: pathlib.Path,
) -> dict[str, Any]:
    if args.pre_submit_review_codex_model:
        return run_codex_agent_command(
            prompt=prompt,
            timeout_seconds=args.timeout_seconds,
            model=args.pre_submit_review_codex_model,
            out_dir=out_dir,
            prefix="pre_submit_review_",
            search=args.pre_submit_review_codex_search,
            sandbox=args.codex_sandbox,
            reasoning_effort=args.codex_reasoning_effort,
            network=args.codex_network,
        )
    return run_agent_command(
        args.pre_submit_review_command,
        prompt,
        prompt_path,
        args.timeout_seconds,
    )


def main() -> int:
    args = parse_args()
    generation_ticket = parse_generation_ticket_context(args)
    if args.codex_network:
        if args.codex_sandbox == "read-only":
            raise SystemExit(
                "--codex-network cannot work under the read-only sandbox "
                "(it denies all sockets, so curl exits 6 before any HTTP "
                "happens); pass --codex-sandbox workspace-write, which "
                "pairs the network grant with the runner's "
                "workspace-mutation guard"
            )
        if not args.codex_model and not args.print_prompt:
            raise SystemExit(
                "--codex-network only applies to --codex-model runs; "
                "--command agents run unsandboxed and already have network"
            )
    run_at = utc_now()
    checkout_sha = workspace_checkout_sha()
    target_context = parse_target_context(args.target_context_json)
    announcement_url = (
        target_announcement_url(target_context)
        if generation_ticket is not None
        else None
    )
    prompt, meta = build_run_prompt(
        args.series,
        args.period,
        args.conditional,
        args.prompt_mode,
        target_context,
        ticket=generation_ticket,
        network_tools=bool(args.codex_network),
    )
    if args.print_prompt:
        print(prompt)
        return 0

    if (
        sum(
            bool(value)
            for value in [
                args.command,
                args.codex_model,
                args.response_file,
                args.mock_cell,
            ]
        )
        != 1
    ):
        raise SystemExit(
            "Choose exactly one of --command, --codex-model, --response-file, "
            "or --mock-cell"
        )
    review_sources = [
        args.pre_submit_review_command,
        args.pre_submit_review_codex_model,
    ]
    if sum(bool(value) for value in review_sources) > 1:
        raise SystemExit(
            "Choose at most one of --pre-submit-review-command or "
            "--pre-submit-review-codex-model"
        )
    if any(bool(value) for value in review_sources) and not (
        args.command or args.codex_model
    ):
        raise SystemExit(
            "Pre-submit review requires --command or --codex-model for the forecaster"
        )

    out_dir = (
        pathlib.Path(args.out_dir)
        if args.out_dir
        else default_out_dir(args.series, args.period, run_at)
    )
    refs: list[dict[str, Any]] = []
    refs.append(write_artifact(out_dir, "prompt", "prompt.md", prompt, run_at))

    command_result: dict[str, Any] | None = None
    review_status: str | None = None
    review_result: dict[str, Any] | None = None
    review_payload: dict[str, Any] | None = None
    draft_ref: dict[str, Any] | None = None
    review_ref: dict[str, Any] | None = None
    revision_prompt_ref: dict[str, Any] | None = None
    hygiene_guarded = False
    hygiene_mutations: list[str] = []

    def collect_hygiene(stage_result: dict[str, Any]) -> dict[str, Any]:
        nonlocal hygiene_guarded
        if generation_ticket is not None:
            stage_result = enforce_ticket_codex_stream_binding(stage_result)
        if "workspaceMutations" in stage_result:
            hygiene_guarded = True
            hygiene_mutations.extend(stage_result["workspaceMutations"])
        return stage_result

    if args.command or args.codex_model:
        if args.pre_submit_review_command or args.pre_submit_review_codex_model:
            draft_result = collect_hygiene(
                run_forecaster(
                    args,
                    prompt=prompt,
                    prompt_path=out_dir / "prompt.md",
                    out_dir=out_dir,
                    prefix="draft_",
                    announcement_url=announcement_url,
                )
            )
            draft_ref = append_command_artifacts(
                refs,
                out_dir,
                prefix="draft_",
                command_result=draft_result,
                created_at=run_at,
                stdout_artifact_type="draft_forecast",
                generation_ticket=generation_ticket,
            )
            if draft_result["returnCode"] != 0:
                review_status = "draft_failed"
                command_result = draft_result
                raw_response = draft_result["stdout"]
            else:
                review_prompt = build_pre_submit_review_prompt(
                    series=args.series,
                    period=args.period,
                    conditional=args.conditional,
                    target_context=target_context,
                    original_prompt=prompt,
                    draft_response=draft_result["stdout"],
                )
                refs.append(
                    write_artifact(
                        out_dir,
                        "review_prompt",
                        "pre_submit_review_prompt.md",
                        review_prompt,
                        run_at,
                    )
                )
                review_result = collect_hygiene(
                    run_pre_submit_reviewer(
                        args,
                        prompt=review_prompt,
                        prompt_path=out_dir / "pre_submit_review_prompt.md",
                        out_dir=out_dir,
                    )
                )
                review_ref = append_command_artifacts(
                    refs,
                    out_dir,
                    prefix="pre_submit_review_",
                    command_result=review_result,
                    created_at=run_at,
                    stdout_artifact_type="pre_submit_review",
                    generation_ticket=generation_ticket,
                )
                review_payload = parse_review_payload(review_result["stdout"])
                if review_result["returnCode"] != 0:
                    review_status = "review_failed"
                    command_result = review_result
                    raw_response = draft_result["stdout"]
                else:
                    revision_prompt = build_revision_prompt(
                        original_prompt=prompt,
                        draft_response=draft_result["stdout"],
                        review_response=review_result["stdout"],
                    )
                    revision_prompt_ref = write_artifact(
                        out_dir,
                        "revision_prompt",
                        "revision_prompt.md",
                        revision_prompt,
                        run_at,
                    )
                    refs.append(revision_prompt_ref)
                    command_result = collect_hygiene(
                        run_forecaster(
                            args,
                            prompt=revision_prompt,
                            prompt_path=out_dir / "revision_prompt.md",
                            out_dir=out_dir,
                            prefix="",
                            announcement_url=announcement_url,
                        )
                    )
                    append_command_artifacts(
                        refs,
                        out_dir,
                        prefix="",
                        command_result=command_result,
                        created_at=run_at,
                        generation_ticket=generation_ticket,
                    )
                    raw_response = command_result["stdout"]
                    review_status = (
                        "completed"
                        if command_result["returnCode"] == 0
                        else "revision_failed"
                    )
        else:
            command_result = collect_hygiene(
                run_forecaster(
                    args,
                    prompt=prompt,
                    prompt_path=out_dir / "prompt.md",
                    out_dir=out_dir,
                    prefix="",
                    announcement_url=announcement_url,
                )
            )
            append_command_artifacts(
                refs,
                out_dir,
                prefix="",
                command_result=command_result,
                created_at=run_at,
                generation_ticket=generation_ticket,
            )
            raw_response = command_result["stdout"]
        if command_result["returnCode"] != 0:
            print(
                f"agent command exited {command_result['returnCode']}", file=sys.stderr
            )
    elif args.response_file:
        raw_response = redact_response_text(
            pathlib.Path(args.response_file).read_text()
        )
        refs.append(
            write_artifact(
                out_dir,
                "command",
                "command.json",
                json.dumps(
                    {"backend": "response_file", "responseFile": args.response_file},
                    indent=2,
                ),
                run_at,
            )
        )
        refs.append(
            write_artifact(out_dir, "stdout", "stdout.txt", raw_response, run_at)
        )
        refs.append(write_artifact(out_dir, "stderr", "stderr.txt", "\n", run_at))
    else:
        raw_response = json.dumps(
            [mock_cell(args.series, args.period, run_at)], indent=2
        )
        refs.append(
            write_artifact(
                out_dir,
                "command",
                "command.json",
                json.dumps({"backend": "mock", "mockCell": True}, indent=2),
                run_at,
            )
        )
        refs.append(
            write_artifact(out_dir, "stdout", "stdout.txt", raw_response, run_at)
        )
        refs.append(write_artifact(out_dir, "stderr", "stderr.txt", "\n", run_at))

    runtime_meta = stamp_runtime_invocation(meta, command_result)

    refs.append(
        write_artifact(
            out_dir, "raw_response", "raw_response.txt", raw_response, run_at
        )
    )

    try:
        parsed_cells = extract_json_payload(raw_response)
    except ValueError as exc:
        manifest = write_failure_manifest(
            out_dir,
            run_at,
            args,
            runtime_meta,
            refs,
            "parse",
            str(exc),
            command_result,
            target_context,
            checkout_sha=checkout_sha,
            generation_ticket=generation_ticket,
        )
        print(json.dumps(manifest, indent=2))
        return 1
    if not parsed_cells:
        # An empty payload is not a forecast and not a refusal record —
        # letting it through produced a green manifest with zero cells.
        manifest = write_failure_manifest(
            out_dir,
            run_at,
            args,
            runtime_meta,
            refs,
            "parse",
            "agent returned an empty cell payload",
            command_result,
            target_context,
            checkout_sha=checkout_sha,
            generation_ticket=generation_ticket,
        )
        print(json.dumps(manifest, indent=2))
        return 1
    try:
        # Before parsed_cells.json becomes a custody artifact: canonical
        # hashing of JSON artifacts cannot represent oversized or
        # non-finite numbers, so a later rejection would crash the
        # failure path itself and leave no record.
        _reject_unencodable_numbers(parsed_cells, "cell payload")
    except RuntimeError as exc:
        manifest = write_failure_manifest(
            out_dir,
            run_at,
            args,
            runtime_meta,
            refs,
            "parse",
            str(exc),
            command_result,
            target_context,
            checkout_sha=checkout_sha,
            generation_ticket=generation_ticket,
        )
        print(json.dumps(manifest, indent=2))
        return 1
    parsed_path = out_dir / "parsed_cells.json"
    refs.append(
        write_artifact(
            out_dir,
            "parsed_cell",
            parsed_path.name,
            json.dumps(parsed_cells, indent=2),
            run_at,
        )
    )

    normalized_path = out_dir / "normalized_cells.json"
    try:
        normalize_cells(parsed_path, normalized_path)
        # Normalization coerces numeric strings ("1e309") into floats
        # the parse-time gate could not see; the parsed artifact holds
        # the original strings, so failing HERE still canonicalizes.
        for index, cell in enumerate(json.loads(normalized_path.read_text())):
            _reject_unencodable_numbers(cell, f"normalized cell {index}")
    except RuntimeError as exc:
        # The subprocess may have written the poisoned file before the
        # sweep rejected it; an unreferenced artifact fails the v2
        # directory inventory, so the failure record must not leave it.
        normalized_path.unlink(missing_ok=True)
        # A malformed cell (a JSON refusal object, a cell missing
        # historicalContext) must still leave a registration-bound
        # failure manifest — the uncaught path left no run record at
        # all, which blocked whole-wave publication ("result N lacks a
        # registration-bound manifest", the B1 rescue failure shape).
        manifest = write_failure_manifest(
            out_dir,
            run_at,
            args,
            runtime_meta,
            refs,
            "normalize",
            str(exc),
            command_result,
            target_context,
            checkout_sha=checkout_sha,
            generation_ticket=generation_ticket,
        )
        print(json.dumps(manifest, indent=2))
        return 1
    normalized_cells = json.loads(normalized_path.read_text())
    # The published runAt is the harness's SEAL time — captured here,
    # after the agent finished — never the agent's claim and never the
    # harness start time. Chronology verification requires the seal to
    # precede the observation, so a run that starts before a release and
    # finishes after it stamps late and classifies as violated instead
    # of sneaking in under its start time (cross-review finding X1).
    # Start time and any differing agent claim are kept for audit.
    sealed_at = utc_now()
    binding = registration_binding(target_context)
    try:
        materialized_distributions = seal_normalized_cells(
            normalized_cells,
            conditional=args.conditional,
            run_started_at=run_at,
            sealed_at=sealed_at,
            prompt_mode=args.prompt_mode,
            target_context=target_context,
        )
        # Post-coercion gate: sealing converts numeric strings with
        # float(), which yields infinity for "1e309" WITHOUT raising —
        # the poison then reaches derived distributions as NaN and
        # crashes custody hashing at the very end, past every failure
        # path. Reject sealed cells and materialized distributions here,
        # while the seal-failure inventory is still exactly satisfiable.
        for index, cell in enumerate(normalized_cells):
            _reject_unencodable_numbers(cell, f"sealed cell {index}")
        _reject_unencodable_numbers(
            materialized_distributions, "materialized distribution"
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        OverflowError,
    ) as exc:
        # Malformed cell values (a non-numeric pointEstimate, a numeric
        # slug) must still leave a registration-bound failure manifest —
        # the uncaught path left no run record and blocked whole-wave
        # publication. normalized_cells.json exists on disk at this
        # point, so reference it before sealing the failure inventory.
        refs.append(
            {
                "artifactType": "normalized_cell",
                "path": repo_relative(normalized_path),
                "sha256": sha256_bytes(normalized_path.read_bytes()),
                "bytes": normalized_path.stat().st_size,
                "createdAt": run_at,
            }
        )
        manifest = write_failure_manifest(
            out_dir,
            run_at,
            args,
            runtime_meta,
            refs,
            "seal",
            f"{type(exc).__name__}: {exc}",
            command_result,
            target_context,
            checkout_sha=checkout_sha,
            generation_ticket=generation_ticket,
        )
        print(json.dumps(manifest, indent=2))
        return 1
    normalized_path.write_text(json.dumps(normalized_cells, indent=2) + "\n")
    refs.append(
        {
            "artifactType": "normalized_cell",
            "path": repo_relative(normalized_path),
            "sha256": sha256_bytes(normalized_path.read_bytes()),
            "bytes": normalized_path.stat().st_size,
            "createdAt": run_at,
        }
    )
    refs.append(
        write_artifact(
            out_dir,
            "run_distribution",
            "distribution.json",
            json.dumps(materialized_distributions, indent=2) + "\n",
            run_at,
        )
    )

    try:
        validation = validate_cells(
            normalized_cells,
            args.allow_existing_slug,
            target_context,
            args.prompt_mode,
            generation_ticket=generation_ticket,
            agent_version=runtime_meta.get("agentVersion"),
            checkout_sha=checkout_sha,
            series=args.series,
            target_period=args.period,
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        OverflowError,
    ) as exc:
        # Same guarantee as the normalize and seal guards: a cell that
        # crashes validation (rather than failing it) still leaves a
        # registration-bound failure manifest.
        manifest = write_failure_manifest(
            out_dir,
            run_at,
            args,
            runtime_meta,
            refs,
            "validate",
            f"{type(exc).__name__}: {exc}",
            command_result,
            target_context,
            checkout_sha=checkout_sha,
            generation_ticket=generation_ticket,
        )
        print(json.dumps(manifest, indent=2))
        return 1
    validation_ref = write_artifact(
        out_dir,
        "validation_report",
        "validation.json",
        json.dumps(validation, indent=2),
        run_at,
    )
    refs.append(validation_ref)

    pre_submit_review = (
        build_pre_submit_review_metadata(
            status=review_status or "not_requested",
            requested_at=run_at,
            review_result=review_result,
            review_payload=review_payload,
            draft_ref=draft_ref,
            review_ref=review_ref,
            revision_prompt_ref=revision_prompt_ref,
            normalized_cells=normalized_cells,
        )
        if args.pre_submit_review_command or args.pre_submit_review_codex_model
        else None
    )
    cells_with_activity = attach_activity_log(
        normalized_cells,
        refs,
        runtime_meta,
        pre_submit_review,
        force_model=generation_ticket is not None,
    )
    cells_path = out_dir / "cells.with_activity.json"
    cells_path.write_text(json.dumps(cells_with_activity, indent=2) + "\n")
    refs.append(
        {
            "artifactType": "cells_with_activity",
            "path": repo_relative(cells_path),
            "sha256": sha256_bytes(cells_path.read_bytes()),
            "bytes": cells_path.stat().st_size,
            "createdAt": run_at,
        }
    )

    if hygiene_mutations:
        print(
            "workspace hygiene: agent stage mutated the workspace "
            f"({len(hygiene_mutations)} violation(s)); failing the run",
            file=sys.stderr,
        )
    manifest = {
        "schemaVersion": "thesis_analyst_run_manifest_v1",
        "createdAt": run_at,
        "runStartedAt": run_at,
        "sealedAt": sealed_at,
        "series": args.series,
        "period": args.period,
        "conditional": args.conditional,
        "targetContext": target_context,
        **binding,
        "promptMode": args.prompt_mode,
        "agent": runtime_meta,
        "preSubmitReview": pre_submit_review,
        **(
            {
                "workspaceHygiene": {
                    "guarded": True,
                    "mutations": hygiene_mutations,
                }
            }
            if hygiene_guarded
            else {}
        ),
        "ok": validation["ok"]
        and (not command_result or command_result["returnCode"] == 0)
        and not hygiene_mutations,
        "cellsPath": repo_relative(cells_path),
        "artifacts": refs,
        "validation": validation,
    }
    manifest = finalize_manifest(
        out_dir,
        run_at,
        manifest,
        refs,
        checkout_sha=checkout_sha,
        generation_ticket=generation_ticket,
    )

    if args.write_ts and manifest["ok"]:
        write_ts_module(cells_path, pathlib.Path(args.write_ts), args.const_name)

    print(json.dumps(manifest, indent=2))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
