"""`scripts/resolution_alert.py` says which kind of red a resolve run is.

The fixtures are the resolver's real stdout from the three runs of
2026-09-29: 00:33Z (Actions run 36503673388) crashed importing receipt's
``PinnedSigner``; 11:14Z (36560463620) died when Chronicle's append gate
failed on chronicle#300; 11:55Z (36564793248) appended eight observations,
published them, and failed only on two CATALOG REFUSED Table A-19 rows.
Until this change all three opened or fed the same "Resolution loop failed"
issue.

Invariants (property-tested below):
- the kind is "refused_rows" exactly when the refused-rows gate failed;
- the loop-failed title is the old title, unchanged;
- the refused list is exactly the rows behind exit 3 (CATALOG REFUSED,
  PROVENANCE REFUSED, LEDGER UNIT CONFLICT), checked against a reference
  reader of the resolver's own print formats;
- resolver text reaches the issue only inside single-line code spans;
- it never raises on any log text.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolution_alert as ra  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "resolution_alert"
CRASH_LOG = (FIXTURES / "resolver-run-36503673388.log").read_text()
GATE_LOG = (FIXTURES / "resolver-run-36560463620.log").read_text()
PUBLISHED_LOG = (FIXTURES / "resolver-run-36564793248.log").read_text()
WORKFLOW = ROOT / ".github/workflows/resolve-and-rebuild.yml"
URL = "https://github.com/ThesisInstitute/thesis/actions/runs/36564793248"
DATE = "2026-09-29"
SAFE = r"[A-Za-z0-9 =,.()/_+@'\-]"


def test_the_published_run_is_refused_rows_and_names_both_a19_rows() -> None:
    alert = ra.build_alert(
        PUBLISHED_LOG, refused_gate="failure", run_url=URL, date=DATE
    )
    assert alert["kind"] == "refused_rows"
    assert alert["title"] == "Resolution rows refused 2026-09-29"
    assert alert["refused"] == [
        "bls.cps.employed_people_by_occupation.production.august_2026.first_print",
        "bls.cps.employed_people_by_occupation.transportation_material_moving"
        ".august_2026.first_print",
    ]
    body = alert["body"]
    assert "It appended 8 observation(s)" in body
    assert "`598f394d797728f298cdd405099419a00ce94e18`" in body
    assert "The resolver refused 2 row(s):" in body
    assert "unit conflict within identity" in body
    # The window-missed and binding refusals in the same log do not set
    # exit 3, so they are not listed.
    assert "statcan" not in body and "qcew" not in body


@pytest.mark.parametrize(
    ("log", "stopped_on"),
    [
        (GATE_LOG, "append gate did not pass for PolicyEngine/chronicle 300"),
        (CRASH_LOG, "cannot import name 'PinnedSigner'"),
    ],
)
def test_the_two_crashes_keep_the_loop_failed_title(log: str, stopped_on: str) -> None:
    alert = ra.build_alert(log, refused_gate="skipped", run_url=URL, date=DATE)
    assert alert["kind"] == "loop_failed"
    assert alert["title"] == "Resolution loop failed 2026-09-29"
    assert alert["refused"] == []
    assert alert["body"].startswith(
        f"The resolve-pending loop failed: {URL}. Unresolved cells stay pending"
    )
    assert "The resolver stopped on: `" in alert["body"]
    assert stopped_on in alert["body"]


def test_an_empty_log_says_the_resolver_printed_nothing() -> None:
    alert = ra.build_alert("", refused_gate="", run_url=URL, date=DATE)
    assert alert["kind"] == "loop_failed"
    assert "printed nothing" in alert["body"]


def test_a_refused_run_that_appended_nothing_says_so() -> None:
    log = (
        "  CATALOG REFUSED (excluded from append): a.b.c — conflict\n"
        "every fetched row was refused; nothing to append\n"
        "  refused: a.b.c: conflict\n"
    )
    alert = ra.build_alert(log, refused_gate="failure", run_url=URL, date=DATE)
    assert alert["refused"] == ["a.b.c"]
    assert "It appended nothing this run" in alert["body"]


@pytest.mark.parametrize(
    ("date", "url"),
    [
        ("2026-9-29", URL),
        (DATE, "https://example.com/actions/runs/1"),
        (DATE, URL + "\n@someone"),
    ],
)
def test_a_malformed_date_or_run_url_raises_so_the_workflow_falls_back(
    date: str, url: str
) -> None:
    with pytest.raises(ValueError):
        ra.build_alert(PUBLISHED_LOG, refused_gate="failure", run_url=url, date=date)


# ---- properties -----------------------------------------------------------

REFS = st.from_regex(r"[a-z]{2,6}(\.[a-z0-9_]{1,8}){1,4}", fullmatch=True)
ONE_LINE = st.text(
    st.characters(blacklist_categories=("Cs",), blacklist_characters="\n\r"),
    max_size=80,
)
KINDS = {
    "resolve": lambda ref, why: f"  resolve {ref} -> 1.0 thousands",
    "catalog": lambda ref, why: (
        f"  CATALOG REFUSED (excluded from append): {ref} — {why}"
    ),
    "provenance": lambda ref, why: (
        f"  PROVENANCE REFUSED (excluded from append): {ref} — {why}"
    ),
    "unit": lambda ref, why: f"  LEDGER UNIT CONFLICT (refusing): {ref} — {why}",
    "window": lambda ref, why: f"  FIRST-PRINT WINDOW MISSED (refusing): {ref}",
    "binding": lambda ref, why: (
        f"  BINDING/ADAPTER MISMATCH (refusing, registry drift?): {ref} — adapter"
    ),
    "deferred": lambda ref, why: f"  release 2026-10-01 not reached: {ref}",
    "recorded": lambda ref, why: f"  already recorded: {ref}",
}
EXIT_3_KINDS = {"catalog", "provenance", "unit"}


@st.composite
def resolver_logs(draw: st.DrawFn) -> tuple[str, set[str]]:
    """A log naming each reference once, and the references behind exit 3."""
    refs = draw(st.lists(REFS, unique=True, max_size=12))
    lines, expected = [], set()
    for ref in refs:
        kind = draw(st.sampled_from(sorted(KINDS)))
        lines.append(KINDS[kind](ref, draw(ONE_LINE)))
        if kind in EXIT_3_KINDS:
            expected.add(ref)
    if draw(st.booleans()):
        sha = draw(st.from_regex(r"[0-9a-f]{40}", fullmatch=True))
        lines.append(
            f"appended {len(refs)} observation(s) to o/r@b:l.jsonl via "
            f"reviewed proposal (merged at {sha})"
        )
    return "\n".join(lines) + "\n", expected


GATES = st.sampled_from(["failure", "skipped", "success", "cancelled", "", "FAILURE"])


@settings(max_examples=300, deadline=None)
@given(resolver_logs(), GATES)
def test_the_kind_follows_the_gate_and_the_list_is_exactly_the_exit_3_rows(
    drawn: tuple[str, set[str]], gate: str
) -> None:
    log, expected = drawn
    alert = ra.build_alert(log, refused_gate=gate, run_url=URL, date=DATE)
    if gate == "failure":
        assert alert["kind"] == "refused_rows"
        assert alert["title"] == f"Resolution rows refused {DATE}"
        assert set(alert["refused"]) == expected
        assert alert["refused"] == sorted(alert["refused"])
    else:
        assert alert["kind"] == "loop_failed"
        assert alert["title"] == f"Resolution loop failed {DATE}"
        assert alert["refused"] == []


def _outside_code_spans(body: str) -> str:
    return re.sub(r"`[^`\n]*`", "", body)


@settings(max_examples=300, deadline=None)
@given(
    st.lists(
        st.tuples(REFS, st.text(max_size=120)), max_size=6, unique_by=lambda t: t[0]
    ),
    st.text(max_size=200),
    GATES,
)
def test_resolver_text_reaches_the_issue_only_inside_code_spans(
    refusals: list[tuple[str, str]], tail: str, gate: str
) -> None:
    # Arbitrary text, newlines, backticks, @mentions and markdown links
    # included, in every place the resolver's words can appear: refusal
    # reasons, a crash's last line, and stray lines of any shape.
    log = "".join(
        f"  CATALOG REFUSED (excluded from append): {ref} — {why}\n"
        for ref, why in refusals
    )
    log += f"{tail}\nTraceback (most recent call last):\nValueError: {tail}\n"
    alert = ra.build_alert(log, refused_gate=gate, run_url=URL, date=DATE)
    body = alert["body"]
    fixed = _outside_code_spans(body).replace(URL, "")
    assert "@" not in fixed
    assert "](" not in fixed and "<" not in fixed and "`" not in fixed
    for span in re.findall(r"`([^`\n]*)`", body):
        assert re.fullmatch(f"{SAFE}*", span), span
    for line in body.splitlines():
        if line.startswith("- `"):
            assert re.fullmatch(f"- `{SAFE}*`: `{SAFE}*`", line), line


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=400), GATES)
def test_it_never_raises_on_any_log(log: str, gate: str) -> None:
    alert = ra.build_alert(log, refused_gate=gate, run_url=URL, date=DATE)
    assert alert["kind"] in {"refused_rows", "loop_failed"}
    assert alert["body"].endswith("\n")


# ---- the workflow ------------------------------------------------------------


def _steps() -> list[dict]:
    parsed = yaml.safe_load(WORKFLOW.read_text())
    return parsed["jobs"]["resolve"]["steps"]


def _step(name: str) -> dict:
    return next(step for step in _steps() if step.get("name") == name)


def test_the_alert_reads_the_refused_gate_and_keeps_its_place() -> None:
    names = [step.get("name") for step in _steps()]
    assert names[-2:] == ["Fail the run on refused rows", "Alert on failure"]
    gate = _step("Fail the run on refused rows")
    assert gate["id"] == "refused_gate"
    # No status function in `if`, so the gate runs only after every earlier
    # step succeeded: its failure means the run published.
    assert gate["if"] == "steps.resolve.outputs.resolver_rc == '3'"
    alert = _step("Alert on failure")
    assert alert["if"] == "failure()"
    assert alert["env"]["REFUSED_GATE"] == "${{ steps.refused_gate.outcome }}"
    assert "scripts/resolution_alert.py" in alert["run"]
    assert "gh issue comment" in alert["run"]


def _run_alert_step(
    tmp_path: pathlib.Path,
    *,
    log: str,
    gate: str,
    run_url: str,
    open_issues: list[dict],
) -> tuple[list[list[str]], str]:
    """Run the workflow's own alert script against a fake ``gh``."""
    if shutil.which("jq") is None:
        pytest.skip("jq is needed to apply the step's --jq filter")
    script = _step("Alert on failure")["run"].replace("/tmp/", f"{tmp_path}/")
    (tmp_path / "resolve-out.log").write_text(log)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "gh-calls.jsonl"
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        f"#!{sys.executable}\n"
        "import json, os, subprocess, sys\n"
        "args = sys.argv[1:]\n"
        f"open({str(calls)!r}, 'a').write(json.dumps(args) + '\\n')\n"
        "if args[:2] == ['issue', 'list']:\n"
        "    expr = args[args.index('--jq') + 1]\n"
        "    issues = os.environ['FAKE_ISSUES']\n"
        "    out = subprocess.run(['jq', '-r', expr], input=issues,\n"
        "                         capture_output=True, text=True, check=True)\n"
        "    sys.stdout.write(out.stdout)\n"
    )
    fake_gh.chmod(0o755)
    (bin_dir / "python3").symlink_to(sys.executable)
    summary = tmp_path / "summary.md"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "REFUSED_GATE": gate,
        "RUN_URL": run_url,
        "GITHUB_STEP_SUMMARY": str(summary),
        "FAKE_ISSUES": json.dumps(open_issues),
    }
    subprocess.run(
        ["bash", "-e", "-c", script], cwd=ROOT, env=env, check=True, timeout=60
    )
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    return recorded, summary.read_text()


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def test_the_step_opens_a_refused_rows_issue_for_the_published_run(
    tmp_path: pathlib.Path,
) -> None:
    calls, summary = _run_alert_step(
        tmp_path, log=PUBLISHED_LOG, gate="failure", run_url=URL, open_issues=[]
    )
    create = calls[-1]
    assert create[:2] == ["issue", "create"]
    assert create[create.index("--title") + 1] == f"Resolution rows refused {_today()}"
    body = pathlib.Path(create[create.index("--body-file") + 1]).read_text()
    assert "production.august_2026.first_print" in body
    assert body in summary


def test_a_second_red_run_the_same_day_comments_on_the_open_issue(
    tmp_path: pathlib.Path,
) -> None:
    title = f"Resolution loop failed {_today()}"
    calls, _summary = _run_alert_step(
        tmp_path,
        log=GATE_LOG,
        gate="",
        run_url=URL,
        open_issues=[
            {"number": 7, "title": f"{title} (older)"},
            {"number": 301, "title": title},
        ],
    )
    assert calls[-1][:3] == ["issue", "comment", "301"]


def test_a_title_that_only_contains_this_one_is_not_reused(
    tmp_path: pathlib.Path,
) -> None:
    title = f"Resolution loop failed {_today()}"
    calls, _summary = _run_alert_step(
        tmp_path,
        log=GATE_LOG,
        gate="skipped",
        run_url=URL,
        open_issues=[{"number": 7, "title": f"{title} (older)"}],
    )
    assert calls[-1][:2] == ["issue", "create"]


def test_if_the_script_fails_the_old_alert_still_goes_out(
    tmp_path: pathlib.Path,
) -> None:
    bad_url = "https://example.com/not-a-run"
    calls, _summary = _run_alert_step(
        tmp_path, log=PUBLISHED_LOG, gate="failure", run_url=bad_url, open_issues=[]
    )
    create = calls[-1]
    assert create[create.index("--title") + 1] == f"Resolution loop failed {_today()}"
    body = pathlib.Path(create[create.index("--body-file") + 1]).read_text()
    assert body == (
        f"The resolve-pending loop failed: {bad_url}. Unresolved cells stay "
        "pending — fix before the next release day.\n"
    )
