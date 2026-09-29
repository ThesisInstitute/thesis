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
# against the verdict's head (the text before the reference, or before the
# message's first ": " when the reference comes last), then, only when no
# rule knows the head, against the whole message. First match wins.
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
        (
            r"release window opens \d{4}-\d{2}-\d{2} \(deferring\)$",
            "deferred",
            "WINDOW_NOT_OPEN",
        ),
        # "fetch/parse failed" is not matched: it may be a parse failure.
        (r"(?i)\bfetch failed\b", "fetch_failed", "SOURCE_UNREACHABLE"),
        (r"^UNIT MISMATCH \(refusing\)$", "refused", "UNIT_MISMATCH"),
        (r"^LEDGER UNIT CONFLICT \(refusing\)$", "refused", "LEDGER_UNIT_CONFLICT"),
        (
            r"^CATALOG REFUSED \(excluded from append\)$",
            "refused",
            "LEDGER_CATALOG_REFUSED",
        ),
        (
            r"^PROVENANCE REFUSED \(excluded from append\)$",
            "refused",
            "PROVENANCE_REFUSED",
        ),
        (
            r"^BINDING/ADAPTER MISMATCH \(skipping, registered adapter='generic-url'",
            "refused",
            "REGISTERED_WITHOUT_EXECUTOR",
        ),
        (r"^BINDING/ADAPTER MISMATCH", "refused", "BINDING_MISMATCH"),
        (
            # Also "A-19 FIRST-PRINT WINDOW MISSED (refusing)".
            r"(^|\s)FIRST-PRINT WINDOW (MISSED|CLOSED)",
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
        "The resolver read the official figure on its last run. That run's log "
        "does not show the figure recorded in the ledger."
    ),
    "RESOLVED_BUT_RUN_FAILED": (
        "The resolver read the official figure on its last run, but the run "
        "failed, and its log does not show the figure recorded in the ledger."
    ),
    "RECORDED_AWAITING_PUBLISH": (
        "The official figure is recorded in the ledger. The site has not yet "
        "been rebuilt against that ledger state."
    ),
    "RELEASE_DAY_NOT_REACHED": (
        "The resolver's last run came before the release day it expects for "
        "this figure."
    ),
    "NOT_YET_PUBLISHED": (
        "The resolver did not get this period's figure on its last run and "
        "reported it as not yet published."
    ),
    "WINDOW_NOT_OPEN": "The registered release window for this figure has not opened.",
    "SOURCE_UNREACHABLE": (
        "The resolver's last attempt to fetch this target's source data, or "
        "an archive record of it, did not return usable data."
    ),
    "UNIT_MISMATCH": (
        "The forecast is in a different unit from the one the resolver's "
        "adapter produces for this series, and the resolver does not convert "
        "between them."
    ),
    "REGISTERED_WITHOUT_EXECUTOR": (
        "This target was registered with a generic source link rather than "
        "a resolver binding, and a registration cannot be changed. The "
        "resolver will not substitute a different route to the number."
    ),
    "LEDGER_UNIT_CONFLICT": (
        "The ledger already holds this series in a different unit from the "
        "one the resolver's adapter produces for it. Recording this figure "
        "would give the series two units, so the resolver refused it before "
        "fetching."
    ),
    "LEDGER_CATALOG_REFUSED": (
        "The resolver read the official figure, but the ledger's series "
        "catalog refused the row, so it was not recorded. The catalog refuses, "
        "for example, a row that would give one series two units or two "
        "cadences."
    ),
    "PROVENANCE_REFUSED": (
        "The resolver read the official figure, but refused to record it "
        "when attaching the target's registered provenance."
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
        "The resolver refused this target at its first-print check."
    ),
    "RELEASE_DATE_MISMATCH": (
        "The resolver refused this target because its registered release "
        "window does not agree with the release date or window the resolver "
        "checks it against."
    ),
    "SOURCE_DOES_NOT_PUBLISH_FIGURE": (
        "The registered source does not publish the figure this forecast "
        "names, so it cannot resolve mechanically."
    ),
    "ENVIRONMENT_FAILURE": (
        "The resolver reported an environment failure for this target on its last run."
    ),
    "NO_EXECUTOR_GENERIC_URL": (
        "The resolver has no route for this target's reference. The target "
        "was registered with a generic source link rather than a resolver "
        "binding."
    ),
    "NO_EXECUTOR_UNREGISTERED": (
        "The resolver has no route for this target's reference, and the "
        "target has no registered resolution contract."
    ),
    "NO_EXECUTOR_SERIES_NOT_COVERED": (
        "The resolver has no route for this target's reference, although its "
        "registration names a resolver family."
    ),
    "NO_REPORT": (
        "A resolver covers this series, but its last run printed no line "
        "naming this target."
    ),
    "NO_RESOLVER_RUN": ("No resolver log was available when this status was written."),
}

# A line the rules do not know keeps its code, UNCLASSIFIED, and the
# resolver's own words as the detail. Its reason says only what the line's
# state says: a deferral is not a refusal.
UNCLASSIFIED_REASONS = {
    "refused": (
        "The resolver refused this target for a reason this page does not yet classify."
    ),
    "deferred": (
        "The resolver deferred this target to a later run, for a reason this "
        "page does not yet classify."
    ),
    "fetch_failed": (
        "The resolver did not get usable data from this target's source on "
        "its last run, for a reason this page does not yet classify."
    ),
    "unknown": (
        "The resolver's last run printed a line about this target that this "
        "page does not yet classify."
    ),
}


def reason_for(code: str, state: str) -> str:
    """The sentence the page prints for a row."""
    return (
        REASONS.get(code)
        or UNCLASSIFIED_REASONS.get(state)
        or "The resolver declined this target."
    )


_REF_RE = re.compile(r"(?<![A-Za-z0-9_.\-])([a-z][a-z0-9_]*(?:\.[A-Za-z0-9_\-]+)+)")
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9 =,.()/_+@'\-]")

# Heads of the lines a run prints at its end to list refusals it already
# reported one by one (``  refused: <ref>: <reason>``, ``  fatal: ...``).
# They never replace the line that reported the target first.
_SUMMARY_HEADS = {
    "refused": ("refused", "UNCLASSIFIED"),
    "fatal": (
        "fetch_failed",
        "ENVIRONMENT_FAILURE",
    ),
}
# A run that stops on this line appended nothing (resolve_pending.main).
_ENVIRONMENT_STOP = "environment failures left admitted references unresolvable"
# resolve_pending.main prints this after the reviewed proposal merged; every
# row it resolved and did not refuse afterwards is then in the ledger.
_APPENDED_RE = re.compile(
    r"^appended \d+ observation\(s\) to \S+ via reviewed proposal"
)


def _plain(text: str, limit: int = 240) -> str:
    """Resolver text made safe to reprint (page, JSON, Actions log)."""
    return _UNSAFE_RE.sub(" ", text).strip()[:limit].rstrip()


def _classify(text: str) -> tuple[str, str] | None:
    """(state, code) of the first rule matching `text`, or None."""
    for pattern, state, code in _LINE_RULES:
        if pattern.search(text):
            return state, code
    return None


def _locate_ref(
    line: str, known_refs: frozenset[str] | set[str] | None
) -> tuple[str, str, str, str] | None:
    """(head, words the rules read, ref, detail) for a target line, or None.

    The resolver puts the reference in one of two places: right after the
    first ": " (``  <message>: <ref>[ — detail]``), or after the last one
    when the message carries its own colons (``  A-19 <verdict>: <ref>``,
    ``  <exception>: <ref>``). In the second shape the head is the text
    before the message's first ": ", the rest of the message is the detail,
    and the whole message is what the rules fall back to when none knows
    the head: an A-19 verdict can say "(deferring)" only at its end. With
    `known_refs`, only a reference in that set counts, so a dotted word
    inside a message cannot pass for the target.
    """
    candidates: list[tuple[str, str, str, str]] = []
    head, separator, tail = line.partition(": ")
    if not separator:
        return None
    first = _REF_RE.match(tail)
    if first:
        detail = tail[first.end() :].lstrip(" —-")
        candidates.append((head, head, first.group(1), detail))
    message, _separator, last = line.rpartition(": ")
    if _REF_RE.fullmatch(last):
        verdict, _colon, rest = message.partition(": ")
        candidates.append((verdict, message, last, rest))
    for candidate in candidates:
        if known_refs is None or candidate[2] in known_refs:
            return candidate
    return None


def parse_resolver_log(
    text: str, known_refs: frozenset[str] | set[str] | None = None
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """({ref: {state, code, detail}}, run summary) from resolver stdout.

    Target lines are the two-space-indented ones the main loop prints:
    ``  <message>: <ref>[ — detail]``, ``  <message>: <ref>``,
    ``  resolve <ref> -> value unit``, ``  already recorded: <ref>``,
    ``  release <date> not reached: <ref>``. The last line about a
    reference wins, except the summary lines a run prints at its end
    (``  refused: ...``, ``  fatal: ...``), which restate earlier ones.
    """
    targets: dict[str, dict[str, str]] = {}
    for raw in text.splitlines():
        if not raw.startswith("  ") or raw.startswith("   "):
            continue
        line = raw.strip()
        resolved = re.match(r"^resolve (\S+) ->", line)
        if resolved:
            if known_refs is None or resolved.group(1) in known_refs:
                targets[resolved.group(1)] = {
                    "state": "resolved_this_run",
                    "code": "RESOLVED_AWAITING_RECORD",
                    "detail": "",
                }
            continue
        located = _locate_ref(line, known_refs)
        if located is None:
            continue
        head, words, ref, detail = located
        summary = _SUMMARY_HEADS.get(head)
        if summary is not None:
            if ref in targets:
                continue
            state, code = summary
        else:
            # The verdict's own head decides first, so text interpolated
            # after it (an exception message, a URL) cannot overrule it.
            # Only a head no rule knows falls back to the whole message: an
            # A-19 verdict can say "(deferring)" only at its end.
            state, code = (
                _classify(head)
                or _classify(words)
                or (
                    "unknown",
                    "UNCLASSIFIED",
                )
            )
        if code == "BINDING_MISMATCH" and not detail.strip():
            # "(refusing, registered A-19 contract differs in sourceBinding
            # keys): <ref>" and "(skipping, registered adapter='bls-api' is
            # not a alfred family): <ref>" name the difference before the
            # reference.
            named = re.search(
                r"\((?:refusing|skipping), ([^)]*\b(?:differs in|registered "
                r"adapter=)[^)]+)\)",
                words,
            )
            if named:
                detail = named.group(1)
            else:
                # "registry drift? — " followed by nothing. Saying the
                # binding differs would claim more than the resolver did.
                code = "BINDING_MISMATCH_UNEXPLAINED"
        targets[ref] = {
            "state": state,
            "code": code,
            "detail": _plain(f"{head}. {detail}" if code == "UNCLASSIFIED" else detail),
        }
    lines = text.splitlines()
    crashed = "Traceback (most recent call last):" in text
    stopped = any(line.startswith(_ENVIRONMENT_STOP) for line in lines)
    error = ""
    if crashed:
        tail_lines = [line for line in lines if line and not line.startswith(" ")]
        error = _plain(tail_lines[-1] if tail_lines else "", 300)
    elif stopped:
        error = _plain(_ENVIRONMENT_STOP, 300)
    if any(_APPENDED_RE.match(line) for line in lines):
        for row in targets.values():
            if row["code"] == "RESOLVED_AWAITING_RECORD":
                row.update(
                    state="recorded_awaiting_publish",
                    code="RECORDED_AWAITING_PUBLISH",
                )
    run = {
        "logAvailable": bool(text.strip()),
        "completed": bool(text.strip()) and not crashed and not stopped,
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
            # The resolver routes by the reference's own spelling and never
            # reads the registration's `series`. Only routing is known here,
            # so a registered series spelled differently from the reference
            # is shown, not judged (bls.wp.WPSFD4.2026-07 is registered as
            # series bls.ppi.final_demand_monthly_change).
            state = "no_executor"
            contract = (registrations.get(ref) or {}).get("contract") or {}
            adapter = (contract.get("sourceBinding") or {}).get("adapter")
            series = contract.get("series")
            notes = []
            if ref not in registrations:
                code = "NO_EXECUTOR_UNREGISTERED"
            elif adapter in (None, "", "generic-url"):
                code = "NO_EXECUTOR_GENERIC_URL"
            else:
                code = "NO_EXECUTOR_SERIES_NOT_COVERED"
                notes.append(f"registered adapter {adapter}")
            if isinstance(series, str) and series and not ref.startswith(series + "."):
                notes.append(f"registered series {series}")
            detail = _plain(", ".join(notes))
        reason = reason_for(code, state)
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
    pending_refs = {
        link["targetFactRef"]
        for link in log.get("resolutionLinks", [])
        if link.get("status") == "pending" and link.get("targetFactRef")
    }
    resolver_targets, run = parse_resolver_log(text, pending_refs)
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
