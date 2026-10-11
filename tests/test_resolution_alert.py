"""`scripts/resolution_alert.py` says which kind of red a resolve run is.

The fixtures are the resolver's real stdout from the four runs of
2026-09-29: 00:33Z (Actions run 36503673388) crashed importing receipt's
``PinnedSigner``; 11:14Z (36560463620) printed six CATALOG REFUSED rows and
then died when Chronicle's append gate failed on chronicle#300; 11:55Z
(36564793248) appended eight observations, published them, and failed only
on two CATALOG REFUSED Table A-19 rows; 18:51Z (36615097061) had every
fetched row refused and nothing new to publish. Until this change all four
opened or fed the same "Resolution loop failed" issue.

Invariants (property-tested below):
- the kind is "refused_rows" exactly when the refused-rows gate failed;
- the loop-failed title is the old title, unchanged;
- on generated logs mixing every line shape the resolver prints, the
  refused list is exactly the references whose line is one of the three
  exit-3 lines (the generator's own labels are the expectation; a separate
  test ties those three line heads to ``resolve_pending.py``'s source);
- resolver text reaches the issue only inside single-line code spans;
- the body stays under GitHub's limit however many rows are refused;
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
import resolution_status as rs  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "resolution_alert"
CRASH_LOG = (FIXTURES / "resolver-run-36503673388.log").read_text()
GATE_LOG = (FIXTURES / "resolver-run-36560463620.log").read_text()
PUBLISHED_LOG = (FIXTURES / "resolver-run-36564793248.log").read_text()
ALL_REFUSED_LOG = (FIXTURES / "resolver-run-36615097061.log").read_text()
WORKFLOW = ROOT / ".github/workflows/resolve-and-rebuild.yml"
URL = "https://github.com/ThesisInstitute/thesis/actions/runs/36564793248"
DATE = "2026-09-29"
SAFE = r"[A-Za-z0-9 =,.()/_+@'\-]"
A19 = "bls.cps.employed_people_by_occupation"


def test_the_published_run_is_refused_rows_and_names_both_a19_rows() -> None:
    alert = ra.build_alert(
        PUBLISHED_LOG,
        refused_gate="failure",
        run_url=URL,
        date=DATE,
        resolve_outcome="success",
        needs_publish="1",
    )
    assert alert["kind"] == "refused_rows"
    assert alert["title"] == "Resolution rows refused 2026-09-29"
    assert alert["refused"] == [
        f"{A19}.production.august_2026.first_print",
        f"{A19}.transportation_material_moving.august_2026.first_print",
    ]
    body = alert["body"]
    assert body.startswith("The resolve run published what was new, then failed")
    assert "It appended 8 observation(s)" in body
    assert "`598f394d797728f298cdd405099419a00ce94e18`" in body
    assert "The resolver refused 2 row(s):" in body
    assert "unit conflict within identity" in body
    # The window-missed and binding refusals in the same log do not set
    # exit 3, so they are not listed.
    assert "statcan" not in body and "qcew" not in body


def test_a_run_with_nothing_new_to_publish_does_not_claim_it_published() -> None:
    alert = ra.build_alert(
        ALL_REFUSED_LOG,
        refused_gate="failure",
        run_url=URL,
        date=DATE,
        resolve_outcome="success",
        needs_publish="0",
    )
    assert alert["kind"] == "refused_rows"
    assert alert["body"].startswith(
        "The resolve run had nothing new to publish, then failed on refused rows"
    )
    assert "It appended nothing this run." in alert["body"]
    # The "  refused:" summary lines restate the CATALOG REFUSED lines; they
    # neither add rows nor replace the reasons.
    assert alert["refused"] == [
        f"{A19}.{occupation}.august_2026.first_print"
        for occupation in (
            "business_financial_operations",
            "computer_mathematical",
            "healthcare_support",
            "office_administrative_support",
        )
    ]


def test_the_gate_crash_keeps_its_title_and_still_names_the_refused_rows() -> None:
    alert = ra.build_alert(
        GATE_LOG,
        refused_gate="skipped",
        run_url=URL,
        date=DATE,
        resolve_outcome="failure",
    )
    assert alert["kind"] == "loop_failed"
    assert alert["title"] == "Resolution loop failed 2026-09-29"
    assert alert["body"].startswith(
        f"The resolve-pending loop failed: {URL}. Unresolved cells stay pending"
    )
    assert "append gate did not pass for PolicyEngine/chronicle 300" in alert["body"]
    assert "Before that, the resolver refused 6 row(s):" in alert["body"]
    assert len(alert["refused"]) == 6


def test_the_receipt_crash_names_the_import_error() -> None:
    alert = ra.build_alert(
        CRASH_LOG,
        refused_gate="skipped",
        run_url=URL,
        date=DATE,
        resolve_outcome="failure",
    )
    assert alert["kind"] == "loop_failed"
    assert "The resolver stopped on: `" in alert["body"]
    assert "cannot import name 'PinnedSigner'" in alert["body"]
    assert alert["refused"] == []


@pytest.mark.parametrize(
    ("log", "outcome", "says"),
    [
        ("", "", "printed nothing"),
        ("  resolve a.b -> 1.0 thousands\n", "failure", "failed without a traceback"),
        (
            "  resolve a.b -> 1.0 thousands\n",
            "success",
            "finished; a later step failed",
        ),
        ("  resolve a.b -> 1.0 thousands\n", "", "Read the run's log"),
        (
            "appended 1 observation(s) to o/r@b:l.jsonl via reviewed proposal "
            f"(merged at {'a' * 40})\n",
            "success",
            "may not be on the site yet",
        ),
    ],
)
def test_a_broken_loop_says_only_what_it_knows(
    log: str, outcome: str, says: str
) -> None:
    alert = ra.build_alert(
        log, refused_gate="skipped", run_url=URL, date=DATE, resolve_outcome=outcome
    )
    assert alert["kind"] == "loop_failed"
    assert says in alert["body"]


def test_a_clean_resolver_exit_is_not_read_as_a_crash() -> None:
    # A refusal reason can quote a generator traceback; when the resolve
    # step itself succeeded, that text is not the resolver stopping.
    log = (
        "  resolve a.b.c -> 1.0 thousands\n"
        "  CATALOG REFUSED (excluded from append): a.b.c — series-catalog "
        "generator exit 1: Traceback (most recent call last):   File gen.py "
        "KeyError: 'unit'\n"
        "appended 1 observation(s) to o/r@b:l.jsonl via reviewed proposal "
        f"(merged at {'b' * 40})\n"
    )
    alert = ra.build_alert(
        log, refused_gate="skipped", run_url=URL, date=DATE, resolve_outcome="success"
    )
    assert "stopped on" not in alert["body"]
    assert "may not be on the site yet" in alert["body"]
    assert alert["refused"] == ["a.b.c"]


def test_truncation_drops_whole_lines_and_stays_within_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ra, "MAX_BODY_CHARS", 500)
    lines = [f"- `row {n}`: `{'x' * 40}`" for n in range(100)]
    body = ra._bounded(lines)
    assert len(body) <= 500
    assert body.endswith("(truncated; see the run)\n")
    assert body.count("`") % 2 == 0
    kept = [line for line in body.splitlines() if line.startswith("- ")]
    assert kept == lines[: len(kept)]
    # One line longer than the limit is dropped, not cut.
    body = ra._bounded(["head", "`" + "y" * 600 + "`"])
    assert len(body) <= 500 and "y" not in body and body.count("`") == 0


@pytest.mark.parametrize(
    ("date", "url"),
    [
        ("2026-9-29", URL),
        ("2026-09-29\n", URL),
        ("２０２６-09-29", URL),
        (DATE, "https://example.com/actions/runs/1"),
        (DATE, URL + "\n"),
        (DATE, URL + "\n@someone"),
    ],
)
def test_a_malformed_date_or_run_url_raises_so_the_workflow_falls_back(
    date: str, url: str
) -> None:
    with pytest.raises(ValueError):
        ra.build_alert(PUBLISHED_LOG, refused_gate="failure", run_url=url, date=date)


def test_a_long_refusal_list_is_capped_below_githubs_limit() -> None:
    reason = "series-catalog generator exit 1: unit conflict " + "x" * 400
    log = "".join(
        f"  CATALOG REFUSED (excluded from append): a.row_{n:04d} — {reason}\n"
        for n in range(400)
    )
    alert = ra.build_alert(log, refused_gate="failure", run_url=URL, date=DATE)
    assert len(alert["refused"]) == 400
    assert len(alert["body"]) <= ra.MAX_BODY_CHARS < 65536
    listed = [line for line in alert["body"].splitlines() if line.startswith("- `")]
    assert len(listed) == ra.MAX_LISTED_ROWS
    assert f"- and {400 - ra.MAX_LISTED_ROWS} more" in alert["body"]


def test_code_spans_carry_only_the_safe_characters() -> None:
    raw = "see [x](http://e) @someone `rm` <b>bold</b>\nnext line"
    span = ra._code(raw)
    assert re.fullmatch(f"`{SAFE}*`", span), span
    assert ra._code("") == "`(none)`"


def test_the_three_exit_3_lines_are_the_ones_resolve_pending_prints() -> None:
    source = (ROOT / "scripts" / "resolve_pending.py").read_text()
    heads = {
        "CATALOG REFUSED (excluded from append)": "LEDGER_CATALOG_REFUSED",
        "PROVENANCE REFUSED (excluded from append)": "PROVENANCE_REFUSED",
        "LEDGER UNIT CONFLICT (refusing)": "LEDGER_UNIT_CONFLICT",
    }
    for head, code in heads.items():
        assert f'print(f"  {head}: {{ref}} — ' in source, head
        assert rs._classify(head) == ("refused", code)
    assert set(heads.values()) == ra.EXIT_REFUSED_CODES
    # If the resolver grows another way to exit 3, this list and
    # EXIT_REFUSED_CODES must be revisited.
    assert source.count("return EXIT_REFUSED_ROWS") == 3


# ---- properties -----------------------------------------------------------

REFS = st.from_regex(r"[a-z]{2,6}(\.[a-z0-9_]{1,8}){1,4}", fullmatch=True)
ADVERSARIAL = st.sampled_from(
    ["@someone", "`", "[a](http://e)", "<b>", "</details>", ": x.y.z", " — ", "**"]
)
ONE_LINE = st.lists(
    st.one_of(
        ADVERSARIAL,
        st.text(
            st.characters(blacklist_categories=("Cs",), blacklist_characters="\n\r"),
            max_size=20,
        ),
    ),
    max_size=4,
).map("".join)
KINDS = {
    "resolve": lambda ref, why: f"  resolve {ref} -> 1.0 thousands",
    "catalog": lambda ref, why: (
        f"  CATALOG REFUSED (excluded from append): {ref} — {why}"
    ),
    "provenance": lambda ref, why: (
        f"  PROVENANCE REFUSED (excluded from append): {ref} — {why}"
    ),
    "unit": lambda ref, why: f"  LEDGER UNIT CONFLICT (refusing): {ref} — {why}",
    "unit_mismatch": lambda ref, why: (
        f"  UNIT MISMATCH (refusing): {ref} cell='millions' adapter='thousands'"
    ),
    "window": lambda ref, why: f"  FIRST-PRINT WINDOW MISSED (refusing): {ref}",
    "a19_missed": lambda ref, why: (
        "  A-19 FIRST-PRINT WINDOW MISSED (refusing): the Archive's index lists 0 "
        f"capture(s) dated inside the registered window: {ref}"
    ),
    "a19_wayback": lambda ref, why: (
        "  A-19 WAYBACK INDEX FETCH FAILED (deferring): HTTPError: HTTP Error 503: "
        f"Service Unavailable: {ref}"
    ),
    "binding": lambda ref, why: (
        f"  BINDING/ADAPTER MISMATCH (refusing, registry drift?): {ref} — adapter"
    ),
    "not_open": lambda ref, why: (
        f"  RELEASE WINDOW NOT OPEN (deferring): {ref} — opens 2027-12-01"
    ),
    "deferred": lambda ref, why: f"  release 2026-10-01 not reached: {ref}",
    "recorded": lambda ref, why: f"  already recorded: {ref}",
    "fatal": lambda ref, why: f"  fatal: {ref}: {why}",
}
EXIT_3_KINDS = {"catalog", "provenance", "unit"}


@st.composite
def resolver_logs(draw: st.DrawFn) -> tuple[str, set[str]]:
    """A log naming each reference once (plus the end-of-run restatements),
    and the references behind exit 3."""
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
    if expected and draw(st.booleans()):
        # resolve_pending restates exit-3 rows at the end of some runs.
        lines.append("every fetched row was refused; nothing to append")
        lines += [f"  refused: {ref}: {draw(ONE_LINE)}" for ref in sorted(expected)]
    return "\n".join(lines) + "\n", expected


GATES = st.sampled_from(["failure", "skipped", "success", "cancelled", "", "FAILURE"])
OUTCOMES = st.sampled_from(["success", "failure", "skipped", ""])


@settings(max_examples=400, deadline=None)
@given(resolver_logs(), GATES, OUTCOMES, st.sampled_from(["0", "1", ""]))
def test_the_kind_follows_the_gate_and_the_list_is_exactly_the_exit_3_rows(
    drawn: tuple[str, set[str]], gate: str, outcome: str, needs_publish: str
) -> None:
    log, expected = drawn
    alert = ra.build_alert(
        log,
        refused_gate=gate,
        run_url=URL,
        date=DATE,
        resolve_outcome=outcome,
        needs_publish=needs_publish,
    )
    assert set(alert["refused"]) == expected
    assert alert["refused"] == sorted(alert["refused"])
    if gate == "failure":
        assert alert["kind"] == "refused_rows"
        assert alert["title"] == f"Resolution rows refused {DATE}"
    else:
        assert alert["kind"] == "loop_failed"
        assert alert["title"] == f"Resolution loop failed {DATE}"


def _outside_code_spans(body: str) -> str:
    return re.sub(r"`[^`\n]*`", "", body)


@settings(max_examples=400, deadline=None)
@given(
    st.lists(st.tuples(REFS, ONE_LINE), max_size=6, unique_by=lambda t: t[0]),
    st.lists(st.one_of(ADVERSARIAL, st.text(max_size=40)), max_size=6).map("".join),
    GATES,
    OUTCOMES,
)
def test_resolver_text_reaches_the_issue_only_inside_code_spans(
    refusals: list[tuple[str, str]], tail: str, gate: str, outcome: str
) -> None:
    # Adversarial tokens (mentions, backticks, links, HTML) and arbitrary
    # text in every place the resolver's words can appear: refusal reasons,
    # a crash's last line, and stray lines of any shape.
    log = "".join(
        f"  CATALOG REFUSED (excluded from append): {ref} — {why}\n"
        for ref, why in refusals
    )
    log += f"{tail}\nTraceback (most recent call last):\nValueError: {tail}\n"
    alert = ra.build_alert(
        log, refused_gate=gate, run_url=URL, date=DATE, resolve_outcome=outcome
    )
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
@given(st.text(max_size=400), GATES, OUTCOMES)
def test_it_never_raises_on_any_log(log: str, gate: str, outcome: str) -> None:
    alert = ra.build_alert(
        log, refused_gate=gate, run_url=URL, date=DATE, resolve_outcome=outcome
    )
    assert alert["kind"] in {"refused_rows", "loop_failed"}
    assert alert["body"].endswith("\n")
    assert len(alert["body"]) <= ra.MAX_BODY_CHARS


# ---- the workflow ------------------------------------------------------------


def _steps() -> list[dict]:
    parsed = yaml.safe_load(WORKFLOW.read_text())
    return parsed["jobs"]["resolve"]["steps"]


def _step(name: str) -> dict:
    return next(step for step in _steps() if step.get("name") == name)


def test_the_alert_reads_the_refused_gate_and_keeps_its_place() -> None:
    steps = _steps()
    names = [step.get("name") for step in steps]
    assert names[-2:] == ["Fail the run on refused rows", "Alert on failure"]
    gate = _step("Fail the run on refused rows")
    assert gate["id"] == "refused_gate"
    # No status function in `if`, so the gate runs only after every earlier
    # step succeeded or was skipped.
    assert gate["if"] == "steps.resolve.outputs.resolver_rc == '3'"
    alert = _step("Alert on failure")
    assert alert["if"] == "failure()"
    assert alert["env"]["REFUSED_GATE"] == "${{ steps.refused_gate.outcome }}"
    assert alert["env"]["RESOLVE_OUTCOME"] == "${{ steps.resolve.outcome }}"
    assert alert["env"]["NEEDS_PUBLISH"] == "${{ steps.ledger.outputs.needs_publish }}"
    assert "scripts/resolution_alert.py" in alert["run"]
    assert "gh issue comment" in alert["run"]


def test_no_step_before_the_gate_can_hide_a_failure_from_it() -> None:
    # The gate's failure means "the loop worked" only while every earlier
    # step that publishes fails the job when it fails. The one exception is
    # the status page, which runs always() and may not fail the job.
    status_page = "Publish why each overdue forecast has not resolved"
    for step in _steps():
        if step.get("name") == "Fail the run on refused rows":
            break
        condition = str(step.get("if", ""))
        if step.get("name") == status_page:
            assert step.get("continue-on-error") is True
            assert condition == "always()"
            continue
        assert not step.get("continue-on-error"), step.get("name")
        assert not re.search(r"\b(always|failure|cancelled)\(\)", condition), step
    else:  # pragma: no cover - the gate must exist
        pytest.fail("no refused-rows gate")


def _run_alert_step(
    tmp_path: pathlib.Path,
    *,
    log: str,
    gate: str,
    run_url: str,
    open_issues: list[dict],
    fail_body_file: bool = False,
) -> list[list[str]]:
    """Run the workflow's own alert script against a fake ``gh``.

    The fake narrows ``issue list`` by the ``"<phrase>" in:title`` search
    the way GitHub does (phrase contained in the title), then applies the
    step's ``--jq``; for a null result it prints nothing, which ``$(...)``
    reads the same as real gh's blank line.
    """
    if shutil.which("jq") is None:
        pytest.skip("jq is needed to apply the step's --jq filter")
    script = _step("Alert on failure")["run"].replace("/tmp/", f"{tmp_path}/")
    # Actions expands ${{ }} before bash runs; do the same for the run URL.
    script = script.replace(
        "${{ github.server_url }}/${{ github.repository }}/actions/runs/"
        "${{ github.run_id }}",
        run_url,
    )
    assert "${{" not in script
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
        "if os.environ.get('FAKE_FAIL_BODY_FILE') and '--body-file' in args:\n"
        "    sys.exit(1)\n"
        "if args[:2] == ['issue', 'list']:\n"
        "    expr = args[args.index('--jq') + 1]\n"
        "    issues = json.loads(os.environ['FAKE_ISSUES'])\n"
        "    search = args[args.index('--search') + 1]\n"
        "    phrase = search.split('\"')[1].lower()\n"
        "    issues = [i for i in issues if phrase in i['title'].lower()]\n"
        "    issues = json.dumps(issues)\n"
        "    out = subprocess.run(['jq', '-r', expr], input=issues,\n"
        "                         capture_output=True, text=True, check=True)\n"
        "    lines = [line for line in out.stdout.splitlines() if line != 'null']\n"
        "    sys.stdout.write(''.join(line + '\\n' for line in lines))\n"
    )
    fake_gh.chmod(0o755)
    (bin_dir / "python3").symlink_to(sys.executable)
    summary = tmp_path / "summary.md"
    summary.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "REFUSED_GATE": gate,
        "RESOLVE_OUTCOME": "success" if gate == "failure" else "failure",
        "NEEDS_PUBLISH": "1",
        "RUN_URL": run_url,
        "GITHUB_STEP_SUMMARY": str(summary),
        "FAKE_ISSUES": json.dumps(open_issues),
    }
    if fail_body_file:
        env["FAKE_FAIL_BODY_FILE"] = "1"
    subprocess.run(
        ["bash", "-e", "-c", script], cwd=ROOT, env=env, check=True, timeout=60
    )
    return [json.loads(line) for line in calls.read_text().splitlines()]


def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def test_the_step_opens_a_refused_rows_issue_for_the_published_run(
    tmp_path: pathlib.Path,
) -> None:
    calls = _run_alert_step(
        tmp_path, log=PUBLISHED_LOG, gate="failure", run_url=URL, open_issues=[]
    )
    create = calls[-1]
    assert create[:2] == ["issue", "create"]
    assert create[create.index("--title") + 1] == f"Resolution rows refused {_today()}"
    body = pathlib.Path(create[create.index("--body-file") + 1]).read_text()
    assert "production.august_2026.first_print" in body
    assert body in (tmp_path / "summary.md").read_text()


def test_a_second_red_run_the_same_day_comments_on_the_open_issue(
    tmp_path: pathlib.Path,
) -> None:
    title = f"Resolution loop failed {_today()}"
    calls = _run_alert_step(
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
    calls = _run_alert_step(
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
    calls = _run_alert_step(
        tmp_path, log=PUBLISHED_LOG, gate="failure", run_url=bad_url, open_issues=[]
    )
    create = calls[-1]
    assert create[create.index("--title") + 1] == f"Resolution loop failed {_today()}"
    if "--body-file" in create:
        body = pathlib.Path(create[create.index("--body-file") + 1]).read_text()
    else:
        body = create[create.index("--body") + 1] + "\n"
    assert body == (
        f"The resolve-pending loop failed: {bad_url}. Unresolved cells stay "
        "pending — fix before the next release day.\n"
    )


@pytest.mark.parametrize("open_issue", [False, True])
def test_if_the_issue_call_fails_a_one_line_issue_still_goes_out(
    tmp_path: pathlib.Path, open_issue: bool
) -> None:
    title = f"Resolution rows refused {_today()}"
    calls = _run_alert_step(
        tmp_path,
        log=PUBLISHED_LOG,
        gate="failure",
        run_url=URL,
        open_issues=[{"number": 5, "title": title}] if open_issue else [],
        fail_body_file=True,
    )
    last = calls[-1]
    assert last[:2] == ["issue", "create"]
    # The degraded path keeps the classification.
    assert last[last.index("--title") + 1] == title
    assert last[last.index("--body") + 1] == (
        f"The alert body could not be posted; see {URL}"
    )
