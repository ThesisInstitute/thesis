#!/usr/bin/env python3
"""Join reviewed bill metrics to existing, immutable conditional pairs.

Extraction and Chronicle matching produce proposals. Only this committed
review registry authorizes a bill forecast, and it pins the reviewed analysis
and source text. No model-supplied slug, legal premise, or proposed mapping can
create authority here. The strategy selector independently authenticates the
two registrations; this module binds why those outcomes belong to this bill.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import subprocess
from typing import Any

from canonical_json import canonical_bytes

BINDINGS_PATH = pathlib.Path("scripts/bill_forecast_bindings.json")
PLAN_SCHEMA = "thesis_bill_forecast_selection_v1"


class BillSelectionError(ValueError):
    """The bill's reviewed source, metric, or legal-state pair is not eligible."""


def _read(root: pathlib.Path, relative: pathlib.Path) -> tuple[bytes, dict]:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise BillSelectionError(f"unsafe bill input: {relative}")
    try:
        content = path.read_bytes()
        data = json.loads(content)
    except (OSError, ValueError) as exc:
        raise BillSelectionError(f"cannot read bill input {relative}: {exc}") from exc
    if not isinstance(data, dict):
        raise BillSelectionError(f"bill input must be an object: {relative}")
    return content, data


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _build_bill_selection(
    root: pathlib.Path, bill_slug: str, series: str = ""
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", bill_slug):
        raise BillSelectionError("invalid bill slug")
    bindings_bytes, registry = _read(root, BINDINGS_PATH)
    if registry.get("schemaVersion") != "thesis_bill_forecast_bindings_v1":
        raise BillSelectionError("unsupported bill forecast bindings schema")
    reviewed = registry.get("bills", {}).get(bill_slug)
    if not isinstance(reviewed, dict):
        raise BillSelectionError(
            f"bill has no reviewed conditional bindings: {bill_slug}"
        )
    bill_bytes, bill = _read(root, pathlib.Path(f"bills/{bill_slug}.json"))
    if _sha(bill_bytes) != reviewed.get("artifactSha256"):
        raise BillSelectionError(
            "bill analysis changed since conditional mapping review"
        )
    if bill.get("bill", {}).get("slug") != bill_slug:
        raise BillSelectionError("bill artifact identity differs from reviewed slug")
    meta_bytes, meta = _read(root, pathlib.Path(f"bills/raw/{bill_slug}.meta.json"))
    text_path = root / "bills" / "raw" / f"{bill_slug}.txt"
    if text_path.is_symlink() or not text_path.resolve().is_relative_to(root.resolve()):
        raise BillSelectionError("bill source text must not be a symlink")
    try:
        text_hash = _sha(text_path.read_bytes())
    except OSError as exc:
        raise BillSelectionError("reviewed bill source text is missing") from exc
    if (
        text_hash != reviewed.get("sourceTextSha256")
        or text_hash != meta.get("text_sha256")
        or meta.get("source_url") != reviewed.get("sourceUrl")
        or meta.get("slug") != bill_slug
    ):
        raise BillSelectionError("bill source identity or content differs from review")
    _, docket = _read(root, pathlib.Path("scripts/docket_series.json"))
    pairs = reviewed.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise BillSelectionError("bill has no reviewed pairs")
    if series:
        pairs = [pair for pair in pairs if pair.get("series") == series]
        if len(pairs) != 1:
            raise BillSelectionError("requested series is not one reviewed bill pair")
    metrics = [
        (pi, mi, metric)
        for pi, provision in enumerate(bill.get("provisions", []))
        for mi, metric in enumerate(provision.get("metrics", []))
    ]
    selected: list[dict] = []
    slugs: list[str] = []
    conditions = load_conditions(root)
    for pair in pairs:
        entries = [
            entry
            for entry in docket.get("series", [])
            if entry.get("series") == pair.get("series")
            and entry.get("period") == pair.get("period")
        ]
        if len(entries) != 1:
            raise BillSelectionError("bill pair needs one exact reviewed docket entry")
        entry = entries[0]
        ledger = entry.get("ledger", {})
        if ledger.get("uuid") != pair.get("ledgerUuid") or ledger.get(
            "concept"
        ) != pair.get("series"):
            raise BillSelectionError(
                "bill metric Chronicle identity differs from docket"
            )
        hints = pair.get("seriesHints")
        if not isinstance(hints, list) or pair.get("series") not in hints:
            raise BillSelectionError("reviewed metric hints omit the canonical series")
        matched = [
            (pi, mi) for pi, mi, metric in metrics if metric.get("series_hint") in hints
        ]
        if not matched:
            raise BillSelectionError("reviewed outcome is absent from bill analysis")
        conditional_pair = entry.get("conditionalPair", {})
        arms = conditional_pair.get("arms")
        if not isinstance(arms, list) or len(arms) != 2:
            raise BillSelectionError("bill metric lacks two reviewed conditional arms")
        arm_slugs = [arm.get("catalogSlug") for arm in arms]
        if len(set(arm_slugs)) != 2 or not all(
            isinstance(s, str) and s for s in arm_slugs
        ):
            raise BillSelectionError("conditional pair has duplicate or missing slugs")
        if arm_slugs != pair.get("catalogSlugs") or [
            arm.get("conditionId") for arm in arms
        ] != pair.get("conditionIds"):
            raise BillSelectionError(
                "docket pair differs from reviewed bill arm identities"
            )
        contracts = []
        for arm in arms:
            matches = [
                row
                for row in conditions
                if row.get("conditionId") == arm.get("conditionId")
            ]
            if len(matches) != 1:
                raise BillSelectionError("bill arm needs one recorded condition")
            # Status and its narrative evidence may advance. The meaning of
            # the legal premise must remain byte-identical across generation.
            contracts.append(
                {
                    key: value
                    for key, value in matches[0].items()
                    if key not in {"status", "evidenceUrl", "note"}
                }
            )
        selected.append(
            {
                "series": pair["series"],
                "period": pair["period"],
                "groupSlug": pair["groupSlug"],
                "metricLabel": pair["metricLabel"],
                "ledgerUuid": ledger["uuid"],
                "metricLocations": [
                    {"provision": pi, "metric": mi} for pi, mi in matched
                ],
                "catalogSlugs": arm_slugs,
                "arms": arms,
                "conditionContracts": contracts,
                "conditionDeadline": conditional_pair.get("conditionDeadline"),
                "expectedReleaseWindow": entry.get("extras", {}).get(
                    "expectedReleaseWindow"
                ),
            }
        )
        slugs.extend(arm_slugs)
    if len(slugs) != len(set(slugs)):
        raise BillSelectionError("reviewed bill pairs overlap")
    return {
        "schemaVersion": PLAN_SCHEMA,
        "billSlug": bill_slug,
        "series": series,
        "billSha256": _sha(bill_bytes),
        "bindingsSha256": _sha(bindings_bytes),
        "sourceTextSha256": text_hash,
        "sourceMetadataSha256": _sha(meta_bytes),
        "sourceUrl": reviewed["sourceUrl"],
        "pairs": selected,
        "catalogSlugs": sorted(slugs),
    }


def build_bill_selection(
    root: pathlib.Path, bill_slug: str, series: str = ""
) -> dict[str, Any]:
    try:
        return _build_bill_selection(root, bill_slug, series)
    except (AttributeError, KeyError, TypeError) as exc:
        raise BillSelectionError("malformed reviewed bill mapping input") from exc


def load_conditions(root: pathlib.Path) -> list[dict]:
    """Evaluate the same registry the site uses; never regex-parse TypeScript."""
    try:
        result = subprocess.run(
            ["bun", "scripts/dump_conditions.ts"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        conditions = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise BillSelectionError("cannot evaluate trusted condition registry") from exc
    if not isinstance(conditions, list):
        raise BillSelectionError("condition registry must be an array")
    return conditions


def require_open_bill_selection(
    root: pathlib.Path, plan: dict[str, Any], checked_at: dt.datetime
) -> None:
    expected = build_bill_selection(
        root, plan.get("billSlug", ""), plan.get("series", "")
    )
    if canonical_bytes(expected) != canonical_bytes(plan):
        raise BillSelectionError("reviewed bill mapping changed since selection")
    if checked_at.tzinfo is None:
        raise BillSelectionError("bill eligibility cutoff needs a timezone")
    day = checked_at.astimezone(dt.timezone.utc).date()
    conditions = load_conditions(root)
    for pair in plan["pairs"]:
        try:
            deadline = dt.date.fromisoformat(pair["conditionDeadline"])
            window = pair["expectedReleaseWindow"]
            start = dt.date.fromisoformat(window["start"])
            end = dt.date.fromisoformat(window["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BillSelectionError(
                "bill pair lacks exact deadline and release window"
            ) from exc
        if start <= deadline or end < start:
            raise BillSelectionError(
                "bill release window must follow the condition deadline"
            )
        if day >= deadline or day >= start:
            raise BillSelectionError(
                "bill condition deadline or release boundary reached"
            )
        for arm in pair["arms"]:
            matches = [
                row
                for row in conditions
                if row.get("conditionId") == arm.get("conditionId")
            ]
            if len(matches) != 1:
                raise BillSelectionError("bill arm needs one recorded condition")
            condition = matches[0]
            if (
                condition.get("status") != "open"
                or condition.get("resolvesBy") != pair["conditionDeadline"]
                or arm.get("conditional") not in condition.get("matchStrings", [])
            ):
                raise BillSelectionError(
                    "bill arm condition is closed or differs from registry"
                )
