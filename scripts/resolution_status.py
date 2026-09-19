#!/usr/bin/env python3
"""Say why each overdue forecast has not resolved.

On 2026-09-19 the public pending list opened with 75 forecasts labelled
"resolves Jul 2026" or "resolves Aug 2026" and no explanation; 116 pending
targets were past their resolution date. The resolver had explained almost
all of them, one line per target, in a workflow log nobody reads. This
turns that log, the published Thesis log and the target registrations into
one row per overdue target, which the site prints on the forecast.

It reports; it decides nothing. Every row restates a line the resolver
printed, or the fact that it printed none. A line shape this file does not
know becomes ``UNCLASSIFIED`` with the resolver's own words, so a new
refusal shows up as itself and is never dropped.

Usage:
    python3 scripts/resolution_status.py --resolver-log /tmp/resolve-out.log \\
        --out site/src/data/resolution-status.json [--workflow-run ID]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
from typing import Any

SCHEMA_VERSION = "thesis_resolution_status_v1"

# (state, code) for each line the resolver prints about a target, matched
# against the text before the reference. Order matters: first match wins.
_LINE_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (re.compile(pattern), state, code)
    for pattern, state, code in (
        (r"^resolve$", "resolved_this_run", "RESOLVED_AWAITING_RECORD"),
        (
            r"^already recorded$",
            "recorded_awaiting_publish",
            "RECORDED_AWAITING_PUBLISH",
        ),
        (
            r"^release \d{4}-\d{2}-\d{2} not reached$",
            "deferred",
            "RELEASE_DAY_NOT_REACHED",
        ),
        (r"^not yet published", "deferred", "NOT_YET_PUBLISHED"),
        (r"WINDOW NOT OPEN \(deferring\)$", "deferred", "WINDOW_NOT_OPEN"),
        (r"FETCH FAILED \(deferring\)$", "fetch_failed", "SOURCE_UNREACHABLE"),
        (r"^UNIT MISMATCH \(refusing\)$", "refused", "UNIT_MISMATCH"),
        (
            r"^BINDING/ADAPTER MISMATCH \(skipping, registered adapter='generic-url'",
            "refused",
            "REGISTERED_WITHOUT_EXECUTOR",
        ),
        (r"^BINDING/ADAPTER MISMATCH", "refused", "BINDING_MISMATCH"),
        (
            r"^FIRST-PRINT WINDOW (MISSED|CLOSED)",
            "refused",
            "FIRST_PRINT_WINDOW_MISSED",
        ),
        (
            r"^FORECAST/REGISTERED RELEASE DATE MISMATCH",
            "refused",
            "RELEASE_DATE_MISMATCH",
        ),
        (
            r"^SOURCE PUBLISHES NO NATIONAL AGGREGATE",
            "refused",
            "SOURCE_DOES_NOT_PUBLISH_FIGURE",
        ),
        (r"\(refusing", "refused", "UNCLASSIFIED"),
        (r"\(skipping", "refused", "UNCLASSIFIED"),
        (r"\(deferring", "deferred", "UNCLASSIFIED"),
        (r"\(fatal", "fetch_failed", "ENVIRONMENT_FAILURE"),
    )
)

REASONS = {
    "RESOLVED_AWAITING_RECORD": (
        "The resolver read the official figure on its last run. It is not yet "
        "recorded in the ledger."
    ),
    "RESOLVED_BUT_RUN_FAILED": (
        "The resolver read the official figure on its last run, but the run "
        "failed before recording it."
    ),
    "RECORDED_AWAITING_PUBLISH": (
        "The official figure is recorded in the ledger. The site has not yet "
        "been rebuilt against that ledger state."
    ),
    "RELEASE_DAY_NOT_REACHED": (
        "The resolver's verified release day for this figure is later than "
        "the date shown on the forecast."
    ),
    "NOT_YET_PUBLISHED": (
        "The official source had not published this period at the last run."
    ),
    "WINDOW_NOT_OPEN": "The registered release window for this figure has not opened.",
    "SOURCE_UNREACHABLE": (
        "The official source, or the archive that corroborates it, could not "
        "be reached on the last run."
    ),
    "UNIT_MISMATCH": (
        "The forecast is registered in one unit and the official source "
        "publishes another. The resolver does not convert between them."
    ),
    "REGISTERED_WITHOUT_EXECUTOR": (
        "This target was registered with a generic source link rather than "
        "a resolver binding, and a registration cannot be changed. The "
        "resolver will not substitute a different route to the number."
    ),
    "BINDING_MISMATCH": (
        "The resolver reports that this target's registered source binding "
        "differs from the one it reads for this series, in the fields "
        "listed, and refuses it."
    ),
    "BINDING_MISMATCH_UNEXPLAINED": (
        "The resolver refused this target as a binding mismatch but named "
        "no field that differs."
    ),
    "FIRST_PRINT_WINDOW_MISSED": (
        "The first official print was not captured inside its registered "
        "window. Later figures may be revised, so the resolver will not "
        "score against them."
    ),
    "RELEASE_DATE_MISMATCH": (
        "The forecast's resolution date falls outside the release window "
        "its registration committed to."
    ),
    "SOURCE_DOES_NOT_PUBLISH_FIGURE": (
        "The registered source does not publish the figure this forecast "
        "names, so it cannot resolve mechanically."
    ),
    "ENVIRONMENT_FAILURE": (
        "The resolver's environment failed before it could read this source."
    ),
    "NO_EXECUTOR_GENERIC_URL": (
        "No resolver covers this series. The target was registered with a "
        "generic source link rather than a resolver binding."
    ),
    "NO_EXECUTOR_UNREGISTERED": (
        "No resolver covers this series. The forecast predates target registration."
    ),
    "NO_EXECUTOR_SERIES_NOT_COVERED": (
        "No resolver covers this series, although its registration names a "
        "resolver family."
    ),
    "NO_REPORT": (
        "A resolver covers this series, but its last run printed nothing "
        "about this target."
    ),
    "NO_RESOLVER_RUN": ("No resolver log was available when this status was written."),
}

_REF_RE = re.compile(r"(?<![A-Za-z0-9_.\-])([a-z][a-z0-9_]*(?:\.[A-Za-z0-9_\-]+)+)")
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9 =,.()/_+@'\-]")


def _plain(text: str, limit: int = 240) -> str:
    """Resolver text made safe to reprint (page, JSON, Actions log)."""
    return _UNSAFE_RE.sub(" ", text).strip()[:limit]


def parse_resolver_log(text: str) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """({ref: {state, code, detail}}, run summary) from resolver stdout.

    Target lines are the two-space-indented ones the main loop prints:
    ``  <message>: <ref>[ — detail]``, ``  resolve <ref> -> value unit``,
    ``  already recorded: <ref>``, ``  release <date> not reached: <ref>``.
    The last line about a reference wins.
    """
    targets: dict[str, dict[str, str]] = {}
    for raw in text.splitlines():
        if not raw.startswith("  ") or raw.startswith("   "):
            continue
        line = raw.strip()
        resolved = re.match(r"^resolve (\S+) -> (.+)$", line)
        if resolved:
            targets[resolved.group(1)] = {
                "state": "resolved_this_run",
                "code": "RESOLVED_AWAITING_RECORD",
                "detail": "",
            }
            continue
        head, separator, tail = line.partition(": ")
        if not separator:
            continue
        ref_match = _REF_RE.match(tail)
        if not ref_match:
            continue
        ref = ref_match.group(1)
        detail = tail[ref_match.end() :].lstrip(" —-")
        for pattern, state, code in _LINE_RULES:
            if pattern.search(head):
                break
        else:
            state, code = "refused", "UNCLASSIFIED"
        if code == "BINDING_MISMATCH" and not detail.strip():
            # "registry drift? — " followed by nothing. Saying the binding
            # differs would claim more than the resolver did.
            code = "BINDING_MISMATCH_UNEXPLAINED"
        targets[ref] = {
            "state": state,
            "code": code,
            "detail": _plain(f"{head}. {detail}" if code == "UNCLASSIFIED" else detail),
        }
    crashed = "Traceback (most recent call last):" in text
    error = ""
    if crashed:
        tail_lines = [
            line for line in text.splitlines() if line and not line.startswith(" ")
        ]
        error = _plain(tail_lines[-1] if tail_lines else "", 300)
    run = {
        "logAvailable": bool(text.strip()),
        "completed": bool(text.strip()) and not crashed,
        "error": error,
    }
    return targets, run


def build_status(
    log: dict[str, Any],
    resolver_targets: dict[str, dict[str, str]],
    run: dict[str, Any],
    *,
    claimed_refs: set[str],
    registrations: dict[str, dict[str, Any]],
    as_of: dt.date,
) -> dict[str, Any]:
    """One row per pending target whose resolution date is before `as_of`."""
    forecasts = {
        entry["forecastSlug"]: entry
        for entry in log.get("entries", [])
        if entry.get("kind") == "prediction_recorded" and entry.get("forecastSlug")
    }
    rows: dict[str, dict[str, Any]] = {}
    for link in log.get("resolutionLinks", []):
        if link.get("status") != "pending":
            continue
        ref, slug = link.get("targetFactRef"), link.get("forecastSlug")
        due = str((forecasts.get(slug) or {}).get("resolutionDate") or "")
        if not ref or not slug or not due or due >= as_of.isoformat():
            continue
        seen = resolver_targets.get(ref)
        detail = ""
        if seen:
            state, code, detail = seen["state"], seen["code"], seen["detail"]
            if state == "resolved_this_run" and not run["completed"]:
                code = "RESOLVED_BUT_RUN_FAILED"
        elif not run["logAvailable"]:
            state, code = "unknown", "NO_RESOLVER_RUN"
        elif ref in claimed_refs:
            state, code = "unknown", "NO_REPORT"
        else:
            state = "no_executor"
            contract = (registrations.get(ref) or {}).get("contract") or {}
            adapter = (contract.get("sourceBinding") or {}).get("adapter")
            if ref not in registrations:
                code = "NO_EXECUTOR_UNREGISTERED"
            elif adapter in (None, "", "generic-url"):
                code = "NO_EXECUTOR_GENERIC_URL"
            else:
                code = "NO_EXECUTOR_SERIES_NOT_COVERED"
                detail = _plain(f"registered adapter {adapter}")
        reason = REASONS.get(code) or "The resolver declined this target."
        rows[ref] = {
            "forecastSlug": slug,
            "resolutionDate": due,
            "state": state,
            "code": code,
            "reason": reason,
            **({"detail": detail} if detail else {}),
        }
    ordered = dict(
        sorted(rows.items(), key=lambda item: (item[1]["resolutionDate"], item[0]))
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": as_of.isoformat(),
        "run": run,
        "targets": ordered,
    }


def _same_apart_from_stamp(path: pathlib.Path, status: dict[str, Any]) -> bool:
    try:
        existing = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    volatile = ("generatedAtUtc", "workflowRun")
    strip = lambda doc: {k: v for k, v in doc.items() if k not in volatile}  # noqa: E731
    return strip(existing) == strip(status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--resolver-log", type=pathlib.Path)
    parser.add_argument(
        "--thesis-log", help="directory holding log.json and its chunks"
    )
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--as-of", help="YYYY-MM-DD (default: today, UTC)")
    parser.add_argument("--workflow-run", default="")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import resolve_pending
    from thesis_log_client import load_thesis_log, load_thesis_log_from_directory

    log = (
        load_thesis_log_from_directory(pathlib.Path(args.thesis_log))
        if args.thesis_log
        else load_thesis_log(resolve_pending.LOG_URL)
    )
    text = ""
    if args.resolver_log and args.resolver_log.is_file():
        text = args.resolver_log.read_text(errors="replace")
    resolver_targets, run = parse_resolver_log(text)
    claimed = {item[0] for item in resolve_pending.pending_claims_refs(log)}
    claimed |= {item[0] for item in resolve_pending.pending_adapter_refs(log)}
    as_of = (
        dt.date.fromisoformat(args.as_of)
        if args.as_of
        else dt.datetime.now(dt.timezone.utc).date()
    )
    status = build_status(
        log,
        resolver_targets,
        run,
        claimed_refs=claimed,
        registrations=resolve_pending.registration_contracts(),
        as_of=as_of,
    )
    status["generatedAtUtc"] = dt.datetime.now(dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    status["workflowRun"] = _plain(args.workflow_run, 40)
    counts: dict[str, int] = {}
    for row in status["targets"].values():
        counts[row["code"]] = counts.get(row["code"], 0) + 1
    for code, count in sorted(counts.items(), key=lambda item: -item[1]):
        print(f"  {count:4d}  {code}")
    print(f"{len(status['targets'])} overdue pending target(s) as of {as_of}")
    if _same_apart_from_stamp(args.out, status):
        print(f"unchanged: {args.out}")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
