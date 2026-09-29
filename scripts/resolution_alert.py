#!/usr/bin/env python3
"""Title and body of the issue a failed resolve run opens.

The resolve job ends red in two different ways. Either the loop broke (the
resolver crashed, or a later step failed), so what it found may not have
reached the site, or every step succeeded and the job then failed on purpose
because the resolver refused rows (exit 3, "Fail the run on refused rows").
Until 2026-09-29 both opened the same issue, "Resolution loop failed
<date>", with the same body. That day the 00:33Z run crashed importing
receipt, the 11:14Z run died on Chronicle's append gate, the 11:55Z run
appended eight observations, published them, and was red only because
Chronicle's catalog refused two Table A-19 rows, and the 18:51Z run had
nothing new to publish and was red for four more. The first crash opened one
issue; the other three runs added nothing to it.

This keeps the red and the issue, and says which kind of red it is:
"Resolution rows refused <date>" names each row that set exit 3 and the
resolver's reason; "Resolution loop failed <date>" keeps its title, adds
the resolver's last error, and still names any exit-3 rows the resolver
printed before the loop broke. The workflow comments on an open issue of the
same title, so a second run on the same day is recorded too.

The rows listed are the ones behind exit 3: CATALOG REFUSED, PROVENANCE
REFUSED and LEDGER UNIT CONFLICT lines (see ``resolve_pending.main``). Other
refusals (a missed first-print window, a binding mismatch) do not change the
exit code and are on the public resolution-status page instead. The list
is read from the resolver's log, so a line it cannot parse is not listed;
the body then says how many it found and where the full log is. Resolver
text is reprinted through ``resolution_status._plain`` and inside code
spans, so a fetched page's words cannot mention anyone or link anywhere in
the issue.

Usage:
    python3 scripts/resolution_alert.py --resolver-log /tmp/resolve-out.log \\
        --refused-gate "${{ steps.refused_gate.outcome }}" \\
        --resolve-outcome "${{ steps.resolve.outcome }}" \\
        --needs-publish "${{ steps.ledger.outputs.needs_publish }}" \\
        --run-url URL --date YYYY-MM-DD --out /tmp/alert.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from resolution_status import _plain, parse_resolver_log  # noqa: E402

REFUSED_TITLE = "Resolution rows refused"
FAILED_TITLE = "Resolution loop failed"
# The resolver lines whose rows make resolve_pending.main return
# EXIT_REFUSED_ROWS, by the code resolution_status gives them.
EXIT_REFUSED_CODES = frozenset(
    {"LEDGER_CATALOG_REFUSED", "PROVENANCE_REFUSED", "LEDGER_UNIT_CONFLICT"}
)
# GitHub refuses an issue or comment body over 65536 characters; the step
# must not lose the alert to a long list.
MAX_LISTED_ROWS = 50
MAX_BODY_CHARS = 60000
_APPENDED_RE = re.compile(
    r"^appended ([0-9]+) observation\(s\) to (\S+) via reviewed proposal "
    r"\(merged at ([0-9a-f]{40})\)"
)
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_RUN_URL_RE = re.compile(
    r"https://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+/actions/runs/[0-9]+"
)


def _code(text: str) -> str:
    """Resolver text as an inline code span: no mention, link or markup."""
    plain = _plain(text, 300)
    return f"`{plain}`" if plain else "`(none)`"


def refused_rows(targets: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """(reference, reason) for each row that set the refused-rows exit."""
    return sorted(
        (ref, row["detail"])
        for ref, row in targets.items()
        if row["code"] in EXIT_REFUSED_CODES
    )


def _row_lines(rows: list[tuple[str, str]]) -> list[str]:
    lines = [
        f"- {_code(ref)}: {_code(reason)}" for ref, reason in rows[:MAX_LISTED_ROWS]
    ]
    if len(rows) > MAX_LISTED_ROWS:
        lines.append(
            f'- and {len(rows) - MAX_LISTED_ROWS} more; see the "Resolve pending '
            "cells\" step's log"
        )
    return lines


def _bounded(lines: list[str]) -> str:
    body = "\n".join(lines) + "\n"
    if len(body) <= MAX_BODY_CHARS:
        return body
    return body[:MAX_BODY_CHARS].rsplit("\n", 1)[0] + "\n\n(truncated; see the run)\n"


def build_alert(
    log_text: str,
    *,
    refused_gate: str,
    run_url: str,
    date: str,
    resolve_outcome: str = "",
    needs_publish: str = "",
) -> dict[str, Any]:
    """{kind, title, body, refused} for this run's failure issue.

    ``refused_gate`` is the outcome of the "Fail the run on refused rows"
    step. Its ``if`` names no status function, so it runs only when every
    earlier step succeeded or was skipped, and it always exits 1. "failure"
    there therefore means the loop worked and the job failed on refused rows;
    ``needs_publish`` then says whether anything new was published or there
    was nothing new to publish. Any other gate outcome ("skipped", "", or
    anything unexpected) means the loop itself broke; ``resolve_outcome``
    ("success"/"failure") says whether the resolver was the step that broke.
    """

    if not _DATE_RE.fullmatch(date):
        raise ValueError(f"date must be YYYY-MM-DD, not {date!r}")
    if not _RUN_URL_RE.fullmatch(run_url):
        raise ValueError(f"not an Actions run URL: {run_url!r}")
    targets, run = parse_resolver_log(log_text)
    rows = refused_rows(targets)
    appended = None
    for line in log_text.splitlines():
        match = _APPENDED_RE.match(line)
        if match:
            appended = match
    if refused_gate == "failure":
        if needs_publish == "1":
            head = "The resolve run published what was new"
        else:
            head = "The resolve run had nothing new to publish"
        lines = [f"{head}, then failed on refused rows: {run_url}", ""]
        if appended:
            lines.append(
                f"It appended {appended.group(1)} observation(s) to "
                f"{_code(appended.group(2))} (merged at "
                f"{_code(appended.group(3))})."
            )
        else:
            lines.append("It appended nothing this run.")
        lines += ["", f"The resolver refused {len(rows)} row(s):"]
        lines += _row_lines(rows)
        if not rows:
            lines.append(
                '- none named in the log; read the "Resolve pending cells" step'
            )
        lines += [
            "",
            "A refused row stays pending until its registration or the ledger "
            "lineage is fixed. Every overdue forecast's reason is on the "
            "resolution-status page.",
        ]
        return {
            "kind": "refused_rows",
            "title": f"{REFUSED_TITLE} {date}",
            "body": _bounded(lines),
            "refused": [ref for ref, _reason in rows],
        }
    lines = [
        f"The resolve-pending loop failed: {run_url}. Unresolved cells stay "
        "pending — fix before the next release day.",
        "",
    ]
    if not run["logAvailable"]:
        lines.append(
            "The resolver printed nothing: it did not start or its log was lost."
        )
    elif run["error"]:
        lines.append(f"The resolver stopped on: {_code(run['error'])}")
    elif resolve_outcome == "failure":
        lines.append(
            "The resolve step failed without a traceback; read its log for the "
            "exit status."
        )
    elif appended:
        lines.append(
            f"The resolver appended {appended.group(1)} observation(s) (merged "
            f"at {_code(appended.group(3))}); a later step failed, so they may "
            "not be on the site yet."
        )
    elif resolve_outcome == "success":
        lines.append("The resolver finished; a later step failed.")
    else:
        lines.append("Read the run's log for the step that failed.")
    if rows:
        lines += ["", f"Before that, the resolver refused {len(rows)} row(s):"]
        lines += _row_lines(rows)
    return {
        "kind": "loop_failed",
        "title": f"{FAILED_TITLE} {date}",
        "body": _bounded(lines),
        "refused": [ref for ref, _reason in rows],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--resolver-log", type=pathlib.Path, required=True)
    parser.add_argument("--refused-gate", default="")
    parser.add_argument("--resolve-outcome", default="")
    parser.add_argument("--needs-publish", default="")
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    text = ""
    if args.resolver_log.is_file():
        text = args.resolver_log.read_text(errors="replace")
    alert = build_alert(
        text,
        refused_gate=args.refused_gate,
        run_url=args.run_url,
        date=args.date,
        resolve_outcome=args.resolve_outcome,
        needs_publish=args.needs_publish,
    )
    args.out.write_text(json.dumps(alert, indent=2, ensure_ascii=False) + "\n")
    print(f"{alert['kind']}: {alert['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
