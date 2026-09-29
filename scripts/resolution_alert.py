#!/usr/bin/env python3
"""Title and body of the issue a failed resolve run opens.

The resolve job ends red in two different ways. Either the loop broke
(the resolver crashed, or a publish step failed) and nothing it found
reached the site, or it published and then failed on purpose because the
resolver refused rows (exit 3, "Fail the run on refused rows"). Until
2026-09-29 both opened the same issue, "Resolution loop failed <date>",
with the same body. That day the 00:33Z run crashed importing receipt, the
11:14Z run died on Chronicle's append gate, and the 11:55Z run appended
eight observations, published them, and was red only because Chronicle's
catalog refused two Table A-19 rows. One open issue said the loop had
failed; the second crash and the recovery added nothing to it.

This keeps the red and the issue, and says which kind of red it is:
"Resolution rows refused <date>" names each row that set exit 3 and the
resolver's reason; "Resolution loop failed <date>" keeps its title and
adds the resolver's last error. The workflow comments on an open issue of
the same title, so a second run on the same day is recorded too.

The rows listed are exactly the ones behind exit 3: CATALOG REFUSED,
PROVENANCE REFUSED and LEDGER UNIT CONFLICT lines (see
``resolve_pending.main``). Other refusals (a missed first-print window, a
binding mismatch) do not change the exit code and are on the public
resolution-status page instead. Resolver text is reprinted through
``resolution_status._plain`` and inside code spans, so a fetched page's
words cannot mention anyone or link anywhere in the issue.

Usage:
    python3 scripts/resolution_alert.py --resolver-log /tmp/resolve-out.log \\
        --refused-gate "${{ steps.refused_gate.outcome }}" \\
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
_APPENDED_RE = re.compile(
    r"^appended (\d+) observation\(s\) to (\S+) via reviewed proposal "
    r"\(merged at ([0-9a-f]{40})\)"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_URL_RE = re.compile(r"^https://github\.com/[\w.\-]+/[\w.\-]+/actions/runs/\d+$")


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


def build_alert(
    log_text: str, *, refused_gate: str, run_url: str, date: str
) -> dict[str, Any]:
    """{kind, title, body} for this run's failure issue.

    ``refused_gate`` is the outcome of the "Fail the run on refused rows"
    step. That step runs only when every step before it succeeded and the
    resolver exited 3, and it always fails, so "failure" there means the
    run published and then failed on refused rows. Any other outcome
    ("skipped", "", or anything unexpected) means the loop itself broke.
    """

    if not _DATE_RE.match(date):
        raise ValueError(f"date must be YYYY-MM-DD, not {date!r}")
    if not _RUN_URL_RE.match(run_url):
        raise ValueError(f"not an Actions run URL: {run_url!r}")
    targets, run = parse_resolver_log(log_text)
    appended = None
    for line in log_text.splitlines():
        match = _APPENDED_RE.match(line)
        if match:
            appended = match
    if refused_gate == "failure":
        rows = refused_rows(targets)
        lines = [
            f"The resolve run published, then failed on refused rows: {run_url}",
            "",
        ]
        if appended:
            lines.append(
                f"It appended {appended.group(1)} observation(s) to "
                f"{_code(appended.group(2))} (merged at "
                f"{_code(appended.group(3))}) and published them."
            )
        else:
            lines.append(
                "It appended nothing this run; any ledger rows not yet on the "
                "site were published."
            )
        lines += ["", f"The resolver refused {len(rows)} row(s):"]
        lines += [f"- {_code(ref)}: {_code(reason)}" for ref, reason in rows]
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
            "body": "\n".join(lines) + "\n",
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
    elif appended:
        lines.append(
            f"The resolver appended {appended.group(1)} observation(s) (merged at "
            f"{_code(appended.group(3))}); a later step failed, so they may not "
            "be on the site yet."
        )
    else:
        lines.append("The resolver finished; a later step failed.")
    return {
        "kind": "loop_failed",
        "title": f"{FAILED_TITLE} {date}",
        "body": "\n".join(lines) + "\n",
        "refused": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--resolver-log", type=pathlib.Path, required=True)
    parser.add_argument("--refused-gate", default="")
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    text = ""
    if args.resolver_log.is_file():
        text = args.resolver_log.read_text(errors="replace")
    alert = build_alert(
        text, refused_gate=args.refused_gate, run_url=args.run_url, date=args.date
    )
    args.out.write_text(json.dumps(alert, indent=2, ensure_ascii=False) + "\n")
    print(f"{alert['kind']}: {alert['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
