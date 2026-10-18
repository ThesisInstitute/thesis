"""Weekly claims resolve at the first ALFRED vintage that holds the week.

The registered releasePolicy for both weekly claims series is advance_vintage.
The claims leg used to read the ALFRED vintage dated the forecast's published
resolutionDate. When registered windows drifted (2026-08 to 2026-10) that date
fell a release or more after DOL's print, and four ledger rows took the revised
figure (docs/weekly-claims-release-window-drift.md). The leg now bisects ALFRED
for the first vintage holding the week, and a reviewed table supersedes the
rows read from a later release.

Fixtures are real data:
- tests/fixtures/alfred_claims_vintages_2026.json: ICSA and CCSA as each
  Thursday vintage from 2026-08-20 to 2026-10-15 printed them, fetched
  2026-10-12 and 2026-10-18 from alfred.stlouisfed.org, and the vintage dates
  whose ALFRED response named another day's vintage in its header ("labels").
- tests/fixtures/alfred_icsa_2026-09-2{3,4,5}.csv.gz: ALFRED's complete ICSA
  responses for those vintage dates, fetched 2026-10-18; the 2026-09-25
  response is byte-identical to the 2026-09-24 one, header included.
- tests/fixtures/chronicle_late_release_claims_rows.jsonl: the six rows in
  PolicyEngine/chronicle ledger/official_observations.jsonl (branch
  codex/thesis-ledger-facts) that CLAIMS_FIRST_PRINT_CORRECTIONS names: lines
  222, 223, 225, 232 and 233 at d7e45bc5751357fdac1cfc182e1abaa414b675f3, and
  line 239 at 86da0233a28e926da052effe93a66e2d9e3d77c2.
Tests that need releases outside that range build SYNTHETIC vintages and say so.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import register_targets  # noqa: E402
import resolve_pending  # noqa: E402
import verify_custody  # noqa: E402
from receipt import append_gate  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
ALFRED = json.loads((FIXTURES / "alfred_claims_vintages_2026.json").read_text())
LATE_ROWS = [
    json.loads(line)
    for line in (FIXTURES / "chronicle_late_release_claims_rows.jsonl")
    .read_text()
    .splitlines()
    if line.strip()
]
SCHEDULE_PROVENANCE = {
    "source": register_targets.WEEKLY_CLAIMS_SCHEDULE_URL,
    "releaseExceptions": dict(register_targets.WEEKLY_CLAIMS_RELEASE_EXCEPTIONS),
}
GATE_SPEC = types.SimpleNamespace(
    assertion_content_keys=resolve_pending.ASSERTION_CONTENT_KEYS
)


FIXTURE_FIRST_WEEK = "2026-08-08"


@pytest.fixture(autouse=True)
def fixture_series_start(monkeypatch):
    """The fixture holds weeks from 2026-08-08: treat that as the first week.

    A real ALFRED vintage starts at 1967-01-07; parse_claims_vintage requires
    every response to run weekly from the series' first week.
    """

    monkeypatch.setattr(
        verify_custody,
        "CLAIMS_SERIES_FIRST_WEEK",
        {"ICSA": FIXTURE_FIRST_WEEK, "CCSA": FIXTURE_FIRST_WEEK},
    )


def weeks_through(last: str) -> list[str]:
    day, out = dt.date.fromisoformat(FIXTURE_FIRST_WEEK), []
    while day.isoformat() <= last:
        out.append(day.isoformat())
        day += dt.timedelta(days=7)
    return out


def filled(rows: dict[str, float], through: str | None = None) -> dict[str, float]:
    """SYNTHETIC filler (value 1) for weeks a synthetic release does not set."""

    last = max([*rows, *([through] if through else [])])
    return {week: rows.get(week, 1.0) for week in weeks_through(last)}


def csv_bytes(series_id: str, vintage: str, rows: dict[str, float]) -> bytes:
    header = f"observation_date,{series_id}_{vintage.replace('-', '')}\n"
    return (
        header + "".join(f"{d},{int(v)}\n" for d, v in sorted(rows.items()))
    ).encode()


def fetch_from(
    releases_by_series: dict[str, dict[str, dict[str, float]]],
    corrupt=None,
    before_first_release: str = FIXTURE_FIRST_WEEK,
    labels: dict[str, dict[str, str]] | None = None,
):
    """An ALFRED stand-in: a vintage date returns the latest release on or before it.

    Before its first release a series holds the weeks through
    ``before_first_release`` (the earliest real release's rows for those
    weeks, else SYNTHETIC filler). ``labels[series][vintage]`` names the day
    whose vintage ALFRED answers that date with, as its header says (real
    ALFRED does this; see ALFRED["labels"]). ``corrupt(series, vintage, raw,
    attempt)`` may replace a response.
    """

    attempts: dict[tuple[str, str], int] = {}

    def fetch(series_id: str, vintage: str):
        releases = releases_by_series[series_id]
        label = ((labels or {}).get(series_id) or {}).get(vintage, vintage)
        printed = [day for day in sorted(releases) if day <= label]
        if printed:
            rows = filled(dict(releases[printed[-1]]))
        else:
            earliest = releases[min(releases)]
            rows = {
                week: earliest.get(week, 1.0)
                for week in weeks_through(before_first_release)
            }
        raw = csv_bytes(series_id, label, rows)
        attempt = attempts.get((series_id, vintage), 0)
        attempts[(series_id, vintage)] = attempt + 1
        if corrupt is not None:
            raw = corrupt(series_id, vintage, raw, attempt)
        return raw, "2026-10-13T00:00:00Z"

    return fetch


def real_vintages(corrupt=None) -> resolve_pending.ClaimsVintages:
    return resolve_pending.ClaimsVintages(
        fetch_from(ALFRED["series"], corrupt, labels=ALFRED["labels"])
    )


def synthetic_vintages(week: dt.date, first: dt.date) -> resolve_pending.ClaimsVintages:
    """SYNTHETIC: `week` is present from `first` on, with the value 1000."""

    previous = (week - dt.timedelta(days=7)).isoformat()

    def fetch(series_id: str, vintage: str):
        rows = filled({}, previous)
        if vintage >= first.isoformat():
            rows[week.isoformat()] = 1000.0
        return csv_bytes(series_id, vintage, rows), "2026-10-13T00:00:00Z"

    return resolve_pending.ClaimsVintages(fetch)


# Invariant 1: the first print is ALFRED's vintage of DOL's scheduled release
# day, for every week, found in exactly four requests (the day before, read
# twice; the day; the day after). The schedule decides the day; ALFRED only
# confirms it.
def test_every_week_resolves_on_dols_scheduled_day_in_four_requests() -> None:
    week = dt.date(2026, 8, 15)
    checked = 0
    while week <= dt.date(2026, 12, 26):
        scheduled = register_targets.weekly_claims_release_day(
            "us.dol.initial_claims.sa", f"week_{week.isoformat()}"
        )
        vintages = synthetic_vintages(week, scheduled)
        found = vintages.first_print(
            "initial", week.isoformat(), scheduled + dt.timedelta(days=1)
        )
        assert found is not None and found[0] == scheduled, week
        assert vintages.requests == 4
        assert [(role, day) for role, day, _raw, _at in found[4]] == [
            ("vintage_before_release", scheduled - dt.timedelta(days=1)),
            ("vintage_before_release_reread", scheduled - dt.timedelta(days=1)),
            ("vintage_after_release", scheduled + dt.timedelta(days=1)),
        ]
        checked += 1
        week += dt.timedelta(days=7)
    assert checked == 20  # includes Thanksgiving week's Wednesday release


def test_nothing_before_the_scheduled_day_and_a_wait_on_it() -> None:
    week = dt.date(2026, 9, 26)
    scheduled = dt.date(2026, 10, 1)
    vintages = synthetic_vintages(week, scheduled)
    assert (
        vintages.first_print("initial", week.isoformat(), dt.date(2026, 9, 30)) is None
    )
    assert vintages.requests == 0
    with pytest.raises(resolve_pending.ClaimsFirstPrintUncorroboratedError):
        vintages.first_print("initial", week.isoformat(), scheduled)


def test_a_week_printed_before_dols_scheduled_day_is_refused() -> None:
    week = dt.date(2026, 9, 26)
    vintages = synthetic_vintages(week, dt.date(2026, 9, 30))
    with pytest.raises(resolve_pending.ClaimsVintageError, match="before DOL's"):
        vintages.first_print("initial", week.isoformat(), dt.date(2026, 10, 5))


def first_release(series_id: str, week: str) -> tuple[str, int]:
    for release, rows in sorted(ALFRED["series"][series_id].items()):
        if week in rows:
            return release, rows[week]
    raise AssertionError(f"{series_id} {week} not in the fixture")


# Invariant 2 (differential against the source): for every real week whose
# first print is in the fixture, the leg records the value of the first
# release that holds it, however late the forecast's resolutionDate falls.
@pytest.mark.parametrize("kind", ["initial", "continued"])
def test_every_real_week_resolves_to_its_first_release(kind) -> None:
    series_id = resolve_pending.CLAIMS_SERIES_IDS[kind]
    releases = ALFRED["series"][series_id]
    oldest = min(releases)
    weeks = sorted(
        {week for rows in releases.values() for week in rows} - set(releases[oldest])
    )
    assert len(weeks) >= 6
    for week in weeks:
        expected_day, expected_raw = first_release(series_id, week)
        fetched = resolve_pending.resolve_claims_ref(
            f"ref.{week}",
            week,
            kind,
            "2026-10-08",
            dt.date(2026, 10, 18),
            real_vintages(),
        )
        assert fetched is not None, week
        row, fetched_series, vintage, raw, _retrieved_at, extension = fetched
        divisor, digits = (1_000, 1) if kind == "initial" else (1_000_000, 3)
        assert row["value"] == round(expected_raw / divisor, digits)
        assert row["observed_at"] == vintage == expected_day
        assert (fetched_series, extension) == (series_id, "csv")
        assert raw == csv_bytes(series_id, expected_day, releases[expected_day])


def test_the_pending_drifted_week_resolves_to_its_first_print(capsys) -> None:
    # Continued claims, week ending 2026-09-26: the one claims forecast still
    # pending on 2026-10-12. Printed 1.716 on 2026-10-08; resolutionDate 10-18.
    # The old leg recorded the revised 1.714 that day (Chronicle line 239).
    ref = "dol.eta.continued_claims.sa.week_2026-09-26.first_print"
    fetched = resolve_pending.resolve_claims_ref(
        ref,
        "2026-09-26",
        "continued",
        "2026-10-18",
        dt.date(2026, 10, 18),
        real_vintages(),
    )
    assert fetched is not None
    row = fetched[0]
    assert (row["value"], row["observed_at"]) == (1.716, "2026-10-08")
    note = row["measure"]["concept_evidence_notes"]
    assert "first ALFRED vintage that holds the week, 2026-10-08" in note
    assert "resolutionDate is 2026-10-18" in note
    assert "first vintage 2026-10-08" in capsys.readouterr().out


def test_the_live_case_now_records_the_advance_print() -> None:
    # Initial claims, week ending 2026-08-29: DOL printed 206.0 on 2026-09-03;
    # the forecast's resolutionDate 2026-09-11 vintage reads the revised 207.0.
    fetched = resolve_pending.resolve_claims_ref(
        "us.dol.initial_claims.sa.week_2026-08-29",
        "2026-08-29",
        "initial",
        "2026-09-11",
        dt.date(2026, 9, 20),
        real_vintages(),
    )
    assert fetched is not None
    assert (fetched[0]["value"], fetched[0]["observed_at"]) == (206.0, "2026-09-03")


def test_no_note_when_the_resolution_date_is_the_first_vintage() -> None:
    fetched = resolve_pending.resolve_claims_ref(
        "us.dol.initial_claims.sa.week_2026-09-12",
        "2026-09-12",
        "initial",
        "2026-09-17",
        dt.date(2026, 9, 18),
        real_vintages(),
    )
    assert fetched is not None
    notes = fetched[0]["measure"]["concept_evidence_notes"]
    assert "resolutionDate" not in notes
    assert fetched[0]["value"] == 196.0


def test_unreached_and_unprinted_cells_wait(capsys) -> None:
    vintages = real_vintages()
    assert (
        resolve_pending.resolve_claims_ref(
            "ref",
            "2026-09-26",
            "continued",
            "2026-10-18",
            dt.date(2026, 10, 12),
            vintages,
        )
        is None
    )
    assert vintages.requests == 0
    assert "not reached" in capsys.readouterr().out
    assert (
        resolve_pending.resolve_claims_ref(
            "ref", "2026-10-10", "initial", "2026-10-08", dt.date(2026, 10, 8), vintages
        )
        is None
    )
    assert "not yet published" in capsys.readouterr().out


def test_a_holiday_wednesday_release_is_the_first_vintage() -> None:
    # SYNTHETIC values: DOL lists Wednesday 2026-11-25 for the Thanksgiving week.
    week = dt.date(2026, 11, 21)
    vintages = synthetic_vintages(week, dt.date(2026, 11, 25))
    fetched = resolve_pending.resolve_claims_ref(
        "ref",
        week.isoformat(),
        "initial",
        "2026-11-26",
        dt.date(2026, 11, 30),
        vintages,
    )
    assert fetched is not None and fetched[0]["observed_at"] == "2026-11-25"


def test_a_catch_up_release_waits_for_dols_listed_day(monkeypatch, capsys) -> None:
    # SYNTHETIC: one release prints two weeks at once, a week late (as after
    # the Oct-Nov 2025 lapse in appropriations). The schedule says 2026-12-03,
    # so the week defers, naming the exception table; once DOL's day is
    # listed, it resolves to that release's value.
    releases = {
        "ICSA": {"2026-12-10": {"2026-11-28": 220000.0, "2026-12-05": 230000.0}}
    }

    def resolve():
        return resolve_pending.resolve_claims_ref(
            "ref",
            "2026-11-28",
            "initial",
            "2026-12-10",
            dt.date(2026, 12, 11),
            resolve_pending.ClaimsVintages(
                fetch_from(releases, before_first_release="2026-11-21")
            ),
        )

    assert resolve() is None
    assert "WEEKLY_CLAIMS_RELEASE_EXCEPTIONS" in capsys.readouterr().out
    monkeypatch.setitem(
        register_targets.WEEKLY_CLAIMS_RELEASE_EXCEPTIONS, "2026-12-03", "2026-12-10"
    )
    fetched = resolve()
    assert fetched is not None
    assert (fetched[0]["value"], fetched[0]["observed_at"]) == (220.0, "2026-12-10")


EXPECTED_CORRECTIONS = {
    "us.dol.initial_claims.sa.week_2026-08-29": (207.0, 206.0, "2026-09-03"),
    "us.dol.initial_claims.sa.week_2026-09-05": (206.0, 206.0, "2026-09-10"),
    "us.dol.initial_claims.sa.week_2026-09-12": (198.0, 196.0, "2026-09-17"),
    "us.dol.initial_claims.sa.week_2026-09-19": (198.0, 197.0, "2026-09-24"),
    "dol.eta.continued_claims.sa.week_2026-09-19.first_print": (
        1.699,
        1.701,
        "2026-10-01",
    ),
    "dol.eta.continued_claims.sa.week_2026-09-26.first_print": (
        1.714,
        1.716,
        "2026-10-08",
    ),
}


def test_the_table_names_exactly_the_six_real_rows() -> None:
    table = resolve_pending.CLAIMS_FIRST_PRINT_CORRECTIONS
    assert table == {
        row["source_record_id"]: row["assertionVersion"]["id"] for row in LATE_ROWS
    }
    assert set(table) == set(EXPECTED_CORRECTIONS)
    for ref, version_id in table.items():
        assert resolve_pending.CLAIMS_REF.match(ref), ref
        assert version_id.startswith("av2:") and len(version_id) == 4 + 64


# Invariant 3: after the corrections, every listed record's current row holds
# the first print, read from the first vintage, and names what it replaces.
def test_corrections_supersede_the_six_real_rows_with_first_prints() -> None:
    fetched, supersedes, refusals = resolve_pending.claims_corrections(
        LATE_ROWS, real_vintages()
    )
    assert refusals == []
    assert supersedes == resolve_pending.CLAIMS_FIRST_PRINT_CORRECTIONS
    by_ref = {
        row["source_record_id"]: (row, vintage) for row, _s, vintage, *_ in fetched
    }
    assert set(by_ref) == set(EXPECTED_CORRECTIONS)
    for ref, (old_value, new_value, first_day) in EXPECTED_CORRECTIONS.items():
        row, vintage = by_ref[ref]
        assert (row["value"], row["observed_at"], vintage) == (
            new_value,
            first_day,
            first_day,
        )
        note = row["measure"]["concept_evidence_notes"]
        assert f"Supersedes {supersedes[ref]}" in note
        assert f"recorded {old_value}" in note


def test_corrections_are_a_no_op_once_superseded() -> None:
    done = [
        *LATE_ROWS,
        *(
            {
                "source_record_id": row["source_record_id"],
                "assertionVersion": {
                    "id": f"av2:{index:064x}",
                    "supersedes": row["assertionVersion"]["id"],
                },
            }
            for index, row in enumerate(LATE_ROWS)
        ),
    ]
    vintages = real_vintages()
    assert resolve_pending.claims_corrections(done, vintages) == ([], {}, [])
    assert vintages.requests == 0


def test_a_record_the_ledger_never_held_is_skipped_without_requests() -> None:
    vintages = real_vintages()
    assert resolve_pending.claims_corrections([], vintages) == ([], {}, [])
    assert vintages.requests == 0


def test_a_stale_table_entry_is_refused() -> None:
    rows = [dict(row) for row in LATE_ROWS]
    rows[0] = {
        **rows[0],
        "assertionVersion": {"id": "av2:" + "0" * 64, "supersedes": None},
    }
    fetched, _supersedes, refusals = resolve_pending.claims_corrections(
        rows, real_vintages()
    )
    assert len(fetched) == len(LATE_ROWS) - 1
    assert len(refusals) == 1 and "is not the record's active row" in refusals[0]


def test_the_row_a_late_run_appended_on_2026_10_18_is_corrected() -> None:
    # Chronicle line 239: resolver run 39147142911 (main 992b15b2, before the
    # guard in #344) read continued claims week 2026-09-26 from ALFRED's
    # 2026-10-18 vintage, which carries DOL's 2026-10-15 revision (1.714).
    # DOL first printed it on 2026-10-08 as 1.716.
    ref = "dol.eta.continued_claims.sa.week_2026-09-26.first_print"
    row = next(row for row in LATE_ROWS if row["source_record_id"] == ref)
    assert (row["value"], row["sourceVintage"]) == (1.714, "2026-10-18")
    vintages = real_vintages()
    fetched, supersedes, refusals = resolve_pending.claims_corrections([row], vintages)
    assert refusals == []
    [(corrected, series_id, vintage, *_rest)] = fetched
    assert (corrected["value"], corrected["observed_at"], vintage, series_id) == (
        1.716,
        "2026-10-08",
        "2026-10-08",
        "CCSA",
    )
    assert supersedes == {ref: row["assertionVersion"]["id"]}
    note = corrected["measure"]["concept_evidence_notes"]
    assert f"Supersedes {row['assertionVersion']['id']}" in note
    assert "read from ALFRED vintage 2026-10-18" in note and "recorded 1.714" in note
    assert [
        (role, day.isoformat()) for role, day, _raw, _at in vintages.evidence[ref]
    ] == [
        ("vintage_before_release", "2026-10-07"),
        ("vintage_before_release_reread", "2026-10-07"),
        ("vintage_after_release", "2026-10-09"),
        ("superseded_row_vintage", "2026-10-18"),
    ]


def test_a_row_read_inside_the_first_release_is_refused() -> None:
    # The week 2026-08-29 first printed on 2026-09-03 and was revised on
    # 2026-09-10; a row read on 2026-09-09 holds the first print already.
    ref = "us.dol.initial_claims.sa.week_2026-08-29"
    row = next(row for row in LATE_ROWS if row["source_record_id"] == ref)
    early = {**row, "sourceVintage": "2026-09-09"}
    fetched, _supersedes, refusals = resolve_pending.claims_corrections(
        [early], real_vintages(), {ref: row["assertionVersion"]["id"]}
    )
    assert fetched == []
    assert len(refusals) == 1 and "nothing to correct" in refusals[0]


# Invariant 4 (differential against Chronicle's append gate): a correction row
# built by the resolver's own provenance path passes receipt's check_rows
# after the real row it replaces, and only because it names that row.
def test_a_correction_row_passes_chronicles_append_gate(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    old = next(
        row
        for row in LATE_ROWS
        if row["source_record_id"] == "us.dol.initial_claims.sa.week_2026-08-29"
    )
    assert (
        append_gate.expected_assertion_version_id(old, GATE_SPEC)
        == (old["assertionVersion"]["id"])
    )
    fetched, supersedes, _refusals = resolve_pending.claims_corrections(
        [old], real_vintages()
    )
    [(row, series_id, vintage, raw, retrieved_at, extension)] = fetched
    attached = resolve_pending.attach_resolution_provenance(
        row,
        run_dir=tmp_path / "run",
        series_id=series_id,
        vintage=vintage,
        raw=raw,
        retrieved_at="2026-10-12T15:00:00Z",
        ledger_repo_sha="d7e45bc5751357fdac1cfc182e1abaa414b675f3",
        target_contracts={},
        extension=extension,
    )
    assert attached["assertionVersion"][
        "id"
    ] == append_gate.expected_assertion_version_id(attached, GATE_SPEC)
    unlinked = json.dumps(attached, separators=(",", ":"))
    attached["assertionVersion"] = {
        **attached["assertionVersion"],
        "supersedes": supersedes[row["source_record_id"]],
    }
    linked = json.dumps(attached, separators=(",", ":"))
    old_line = json.dumps(old, separators=(",", ":"))

    append_gate.check_rows([old_line, linked], 1, GATE_SPEC)
    with pytest.raises(append_gate.AppendError, match="corrections must be explicit"):
        append_gate.check_rows([old_line, unlinked], 1, GATE_SPEC)
    current = append_gate.effective_current_rows([old, attached], GATE_SPEC)
    assert [(r["value"], r["observed_at"]) for r in current] == [(206.0, "2026-09-03")]


HTML = b"<!DOCTYPE html><html><body>Service temporarily unavailable</body></html>"


def complete_vintage(series_id: str, vintage: str, through: str) -> bytes:
    return csv_bytes(series_id, vintage, filled({}, through))


@pytest.mark.parametrize(
    ("label", "raw"),
    [
        ("an error page", HTML),
        ("a later vintage date", complete_vintage("ICSA", "2026-09-04", "2026-08-29")),
        ("another series", complete_vintage("CCSA", "2026-09-03", "2026-08-22")),
        (
            "a malformed label",
            b"observation_date,ICSA_2026093\n2026-08-08,1\n2026-08-15,1\n",
        ),
        (
            "an impossible label date",
            b"observation_date,ICSA_20260231\n2026-08-08,1\n2026-08-15,1\n",
        ),
        (
            "a label with a suffix",
            b"observation_date,ICSA_20260903_x\n2026-08-08,1\n2026-08-15,1\n",
        ),
        (
            "a missing week",
            b"observation_date,ICSA_20260903\n2026-08-08,1\n2026-08-22,1\n",
        ),
        (
            "a late first week",
            b"observation_date,ICSA_20260903\n2026-08-15,1\n2026-08-22,1\n",
        ),
        (
            "a non-numeric value",
            b"observation_date,ICSA_20260903\n2026-08-08,1\n2026-08-15,.\n",
        ),
        ("a cut row", b"observation_date,ICSA_20260903\n2026-08-08,1\n2026-08-1"),
        ("no rows", b"observation_date,ICSA_20260903\n"),
        # Review of #345, round 12: date.fromisoformat accepts both of these
        # spellings of 2026-08-15, which then sort wrongly as week keys.
        (
            "a basic-format week",
            b"observation_date,ICSA_20260903\n2026-08-08,1\n20260815,1\n",
        ),
        (
            "an ISO-week week",
            b"observation_date,ICSA_20260903\n2026-08-08,1\n2026-W33-6,1\n",
        ),
    ],
)
def test_parse_refuses_anything_but_a_complete_vintage(label, raw) -> None:
    with pytest.raises(resolve_pending.ClaimsVintageError):
        resolve_pending.parse_claims_vintage(raw, "ICSA", dt.date(2026, 9, 3))


def test_parse_reads_a_complete_vintage() -> None:
    raw = complete_vintage("ICSA", "2026-09-03", "2026-08-29").replace(b"\n", b"\r\n")
    rows = resolve_pending.parse_claims_vintage(raw, "ICSA", dt.date(2026, 9, 3))
    assert list(rows) == weeks_through("2026-08-29")


def real_icsa_response(day: str) -> bytes:
    return gzip.decompress((FIXTURES / f"alfred_icsa_{day}.csv.gz").read_bytes())


def test_alfred_answers_a_later_date_with_an_earlier_days_vintage(
    monkeypatch,
) -> None:
    # Real ALFRED bytes (fetched 2026-10-18), read from the series' real first
    # week: its ICSA response for vintage date 2026-09-25 is its 2026-09-24
    # file, header and all. Before this was handled, the exact-header rule
    # refused it, so initial claims week 2026-09-19 could never resolve or be
    # corrected, and the refusal stopped ICSA for the rest of the run.
    monkeypatch.setattr(
        verify_custody,
        "CLAIMS_SERIES_FIRST_WEEK",
        {"ICSA": "1967-01-07", "CCSA": "1967-01-07"},
    )
    after = real_icsa_response("2026-09-25")
    release = real_icsa_response("2026-09-24")
    before = real_icsa_response("2026-09-23")
    assert after == release
    assert after.split(b"\n", 1)[0] == b"observation_date,ICSA_20260924"
    label, rows = verify_custody.read_alfred_claims_vintage(after, "ICSA", "2026-09-25")
    assert label == dt.date(2026, 9, 24)
    assert next(iter(rows)) == "1967-01-07" and rows["2026-09-19"] == 197000.0
    assert verify_custody.judge_claims_first_print(
        "ICSA",
        "2026-09-19",
        {
            "vintage_before_release": (dt.date(2026, 9, 23), before),
            "vintage_before_release_reread": (dt.date(2026, 9, 23), before),
            "release_day": (dt.date(2026, 9, 24), release),
            "vintage_after_release": (dt.date(2026, 9, 25), after),
        },
    ) == (dt.date(2026, 9, 24), 197000.0)


def test_the_fixture_labels_are_one_day_back() -> None:
    # Every vintage date ALFRED answered with another day's vintage (survey of
    # 2026-01-01 to 2026-10-18) named the day before; none named a later day.
    labels = [
        (dt.date.fromisoformat(day), dt.date.fromisoformat(label))
        for series in ALFRED["labels"].values()
        for day, label in series.items()
    ]
    assert len(labels) == 7
    assert all(day - label == dt.timedelta(days=1) for day, label in labels)


# Each first-print read must be ALFRED's vintage of the day it shows. A read
# answered with an earlier day's vintage defers the week (the series is not
# refused: the response is an honest vintage of another day), except the day
# after, which may be the release day's own vintage.
LABEL_CASES = {
    # role: (vintage date answered with an earlier day's file, defers?)
    "vintage_before_release": ("2026-09-02", True),
    "release_day": ("2026-09-03", True),
    "vintage_after_release": ("2026-09-04", False),
}


@pytest.mark.parametrize("role", sorted(LABEL_CASES))
def test_each_read_must_be_the_vintage_of_the_day_it_shows(role, capsys) -> None:
    day, defers = LABEL_CASES[role]
    previous = (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()
    vintages = resolve_pending.ClaimsVintages(
        fetch_from(ALFRED["series"], labels={"ICSA": {day: previous}})
    )
    fetched = resolve_pending.resolve_claims_ref(
        "us.dol.initial_claims.sa.week_2026-08-29",
        "2026-08-29",
        "initial",
        "2026-09-11",
        dt.date(2026, 9, 20),
        vintages,
    )
    out = capsys.readouterr().out
    if defers:
        assert fetched is None
        assert f"vintage of {previous}, which cannot show" in out
        # The series still reads: one honest earlier vintage refuses nothing.
        assert vintages.read("ICSA", dt.date(2026, 9, 10))[1] is not None
    else:
        assert fetched is not None
        assert (fetched[0]["value"], fetched[0]["observed_at"]) == (206.0, "2026-09-03")


@pytest.mark.parametrize(
    ("role", "day", "label"),
    [
        ("vintage_before_release", "2026-09-02", "2026-09-01"),
        ("vintage_before_release_reread", "2026-09-02", "2026-09-01"),
        ("release_day", "2026-09-03", "2026-09-02"),
        ("vintage_after_release", "2026-09-04", "2026-09-02"),
    ],
)
def test_the_judge_holds_each_read_to_its_label(role, day, label) -> None:
    def body(as_of):
        """ALFRED's ICSA vintage of ``as_of``, labeled so."""
        releases = ALFRED["series"]["ICSA"]
        latest = max(release for release in releases if release <= as_of)
        return csv_bytes("ICSA", as_of, filled(dict(releases[latest])))

    reads = {
        "vintage_before_release": ("2026-09-02", "2026-09-02"),
        "vintage_before_release_reread": ("2026-09-02", "2026-09-02"),
        "release_day": ("2026-09-03", "2026-09-03"),
        "vintage_after_release": ("2026-09-04", "2026-09-04"),
    }
    reads[role] = (day, label)
    if role.startswith("vintage_before"):
        # The two reads of the day before are one answer, read twice.
        reads["vintage_before_release"] = reads["vintage_before_release_reread"] = (
            day,
            label,
        )
    with pytest.raises(ValueError, match=f"vintage of {label}, which cannot show"):
        verify_custody.judge_claims_first_print(
            "ICSA",
            "2026-08-29",
            {
                name: (dt.date.fromisoformat(read_day), body(as_of))
                for name, (read_day, as_of) in reads.items()
            },
        )


def test_a_day_after_answered_two_days_back_defers_without_refusing(capsys) -> None:
    # Review of #345, round 12, P3: a day after answered with the day before's
    # vintage ends earlier than the release day, so once it joined the run's
    # consistency check it refused ICSA for the rest of the run. The label is
    # now checked first: the week waits and the series still resolves.
    vintages = resolve_pending.ClaimsVintages(
        fetch_from(ALFRED["series"], labels={"ICSA": {"2026-09-04": "2026-09-02"}})
    )
    args = ("2026-08-29", "initial", "2026-09-11", dt.date(2026, 9, 20), vintages)
    assert (
        resolve_pending.resolve_claims_ref(
            "us.dol.initial_claims.sa.week_2026-08-29", *args
        )
        is None
    )
    assert "vintage of 2026-09-02, which cannot show" in capsys.readouterr().out
    fetched = resolve_pending.resolve_claims_ref(
        "us.dol.initial_claims.sa.week_2026-09-05",
        "2026-09-05",
        "initial",
        "2026-09-20",
        dt.date(2026, 9, 20),
        vintages,
    )
    assert fetched is not None
    assert (fetched[0]["value"], fetched[0]["observed_at"]) == (206.0, "2026-09-10")


def test_a_correction_answered_with_another_days_vintage_waits(capsys) -> None:
    # Review of #345, round 12, P3: a too-early label in the corrections path
    # was reported as a refused table entry (exit 3, "fix the table"). The
    # entry still matches the ledger, so it waits.
    vintages = resolve_pending.ClaimsVintages(
        fetch_from(
            ALFRED["series"],
            labels={"ICSA": {**ALFRED["labels"]["ICSA"], "2026-09-03": "2026-09-02"}},
        )
    )
    fetched, supersedes, refusals = resolve_pending.claims_corrections(
        LATE_ROWS, vintages
    )
    ref = "us.dol.initial_claims.sa.week_2026-08-29"
    assert refusals == []
    assert ref not in supersedes and len(fetched) == len(LATE_ROWS) - 1
    out = capsys.readouterr().out
    assert f"correction waits, ALFRED answered another day's vintage: {ref}" in out


def test_two_reads_with_one_label_must_hold_the_same_rows() -> None:
    # Review of #345, round 12, P3: a day after answered with the release day's
    # vintage is that vintage again, so it must hold the same rows, not only
    # the same value for the week.
    releases = ALFRED["series"]["ICSA"]
    before = csv_bytes("ICSA", "2026-09-02", filled(dict(releases["2026-08-27"])))
    release = csv_bytes("ICSA", "2026-09-03", filled(dict(releases["2026-09-03"])))
    reads = {
        "vintage_before_release": (dt.date(2026, 9, 2), before),
        "vintage_before_release_reread": (dt.date(2026, 9, 2), before),
        "release_day": (dt.date(2026, 9, 3), release),
        "vintage_after_release": (dt.date(2026, 9, 4), release),
    }
    assert verify_custody.judge_claims_first_print("ICSA", "2026-08-29", reads) == (
        dt.date(2026, 9, 3),
        206000.0,
    )
    altered = release.replace(b"2026-08-08,212000", b"2026-08-08,211000")
    reads["vintage_after_release"] = (dt.date(2026, 9, 4), altered)
    with pytest.raises(ValueError, match="but with different rows"):
        verify_custody.judge_claims_first_print("ICSA", "2026-08-29", reads)


def corrupt_at(day: str, replace):
    """Replace every response for one vintage date (a deterministic fault)."""

    def corrupt(series_id, vintage, raw, attempt):
        return replace(raw) if vintage == day else raw

    return corrupt


# Review of #345 (GPT-6.1 Sol), P1: an HTML body at one probe read as absence
# made initial claims week 2026-08-29 resolve to the revised 207.0.
def test_an_error_page_at_a_probe_defers_instead_of_recording_207(capsys) -> None:
    fetched = resolve_pending.resolve_claims_ref(
        "us.dol.initial_claims.sa.week_2026-08-29",
        "2026-08-29",
        "initial",
        "2026-09-11",
        dt.date(2026, 9, 20),
        real_vintages(corrupt_at("2026-09-09", lambda raw: HTML)),
    )
    out = capsys.readouterr().out
    assert fetched is None or fetched[0]["value"] == 206.0
    if fetched is None:
        assert "ALFRED RESPONSE REFUSED (deferring)" in out


def test_error_pages_during_a_correction_refuse_it() -> None:
    ref = "us.dol.initial_claims.sa.week_2026-09-19"
    pages = {"2026-09-28", "2026-09-30"}

    def corrupt(series_id, vintage, raw, attempt):
        return HTML if vintage in pages else raw

    fetched, supersedes, refusals = resolve_pending.claims_corrections(
        LATE_ROWS,
        real_vintages(corrupt),
        {ref: resolve_pending.CLAIMS_FIRST_PRINT_CORRECTIONS[ref]},
    )
    rows = {row["source_record_id"]: row for row, *_ in fetched}
    assert ref not in rows or rows[ref]["value"] == 197.0
    if ref not in rows:
        assert supersedes == {} and len(refusals) == 1


def test_a_boundary_that_answers_two_ways_is_refused() -> None:
    # The day before the first print (2026-09-02) answers an error page once,
    # then the real vintage: a decision must not rest on either reading alone.
    def flapping(series_id, vintage, raw, attempt):
        if vintage != "2026-09-02":
            return raw
        return complete_vintage(series_id, vintage, "2026-08-15") if attempt else raw

    vintages = real_vintages(flapping)
    with pytest.raises(resolve_pending.ClaimsVintageError, match="two different"):
        vintages.first_print("initial", "2026-08-29", dt.date(2026, 9, 20))


CORRUPTIONS = {
    "error page": lambda raw: HTML,
    "last row dropped": lambda raw: (
        b"\n".join(raw.rstrip(b"\n").split(b"\n")[:-1]) + b"\n"
    ),
    "two rows dropped": lambda raw: (
        b"\n".join(raw.rstrip(b"\n").split(b"\n")[:-2]) + b"\n"
    ),
    "middle row dropped": lambda raw: (
        b"\n".join((lines := raw.rstrip(b"\n").split(b"\n"))[:2] + lines[3:]) + b"\n"
    ),
    "cut mid-row": lambda raw: raw[: len(raw) - 4],
    "next week appended": lambda raw: (
        raw
        + (
            (
                dt.date.fromisoformat(raw.rstrip(b"\n").split(b"\n")[-1][:10].decode())
                + dt.timedelta(days=7)
            )
            .isoformat()
            .encode()
            + b",1999000\n"
        )
    ),
    "last value changed": lambda raw: (
        raw.rstrip(b"\n").rsplit(b",", 1)[0] + b",1888000\n"
    ),
}


def corrupt_once(day: str, replace):
    """Replace only the first response for one vintage date (a transient fault)."""

    def corrupt(series_id, vintage, raw, attempt):
        return replace(raw) if vintage == day and attempt == 0 else raw

    return corrupt


# Invariant 5: no single vintage date answering wrongly, in any of these ways,
# once or on every read, on any run date, can make the leg record anything but
# the first print on DOL's release day. It records exactly that, or defers.
# Exhaustive over every vintage date from the week's end to the run date.
@pytest.mark.parametrize(
    ("kind", "week", "resolution_date", "first_value"),
    [
        ("initial", "2026-08-29", "2026-09-11", 206.0),
        ("initial", "2026-09-12", "2026-09-29", 196.0),
        ("continued", "2026-09-19", "2026-10-09", 1.701),
    ],
)
def test_no_single_faulty_vintage_records_anything_but_the_first_print(
    kind, week, resolution_date, first_value, capsys
) -> None:
    scheduled = register_targets.weekly_claims_release_day(
        resolve_pending.CLAIMS_SERIES_NAMES[kind], f"week_{week}"
    )
    start = dt.date.fromisoformat(week)
    deferred = recorded = 0
    for today_offset in (1, 2, 6, 7, 8, 14):
        today = max(
            scheduled + dt.timedelta(days=today_offset),
            dt.date.fromisoformat(resolution_date),
        )
        days = [
            (start + dt.timedelta(days=offset)).isoformat()
            for offset in range((today - start).days + 1)
        ]
        for name, replace in CORRUPTIONS.items():
            for make in (corrupt_at, corrupt_once):
                for day in days:
                    fetched = resolve_pending.resolve_claims_ref(
                        f"ref.{week}",
                        week,
                        kind,
                        resolution_date,
                        today,
                        real_vintages(make(day, replace)),
                    )
                    if fetched is None:
                        deferred += 1
                        continue
                    recorded += 1
                    row = fetched[0]
                    label = (name, make.__name__, day, today)
                    assert row["value"] == first_value, (label, row["value"])
                    assert row["observed_at"] == scheduled.isoformat(), label
    capsys.readouterr()
    # Both outcomes occur: faults away from the four reads change nothing.
    assert deferred > 0 and recorded > 0


def test_a_deferral_names_the_target_in_the_status_surface(capsys) -> None:
    import resolution_status

    ref = "us.dol.initial_claims.sa.week_2026-08-29"
    assert (
        resolve_pending.resolve_claims_ref(
            ref,
            "2026-08-29",
            "initial",
            "2026-09-11",
            dt.date(2026, 9, 20),
            real_vintages(corrupt_at("2026-09-02", lambda raw: HTML)),
        )
        is None
    )
    targets, _summary = resolution_status.parse_resolver_log(
        capsys.readouterr().out, {ref}
    )
    assert targets[ref]["state"] == "deferred"
    assert "not a vintage CSV" in targets[ref]["detail"]


# Review of #345, round 2 (GPT-6.1 Sol), P1: one faulty *positive* response
# won. A September 29 CCSA response with week 2026-09-19 appended (read once)
# made the correction write 1.699 dated September 29.
def test_an_appended_week_cannot_win_a_correction() -> None:
    def appended(series_id, vintage, raw, attempt):
        if series_id == "CCSA" and vintage == "2026-09-29" and attempt == 0:
            return raw + b"2026-09-19,1699000\n"
        return raw

    ref = "dol.eta.continued_claims.sa.week_2026-09-19.first_print"
    fetched, _supersedes, refusals = resolve_pending.claims_corrections(
        LATE_ROWS, real_vintages(appended)
    )
    rows = {row["source_record_id"]: row for row, *_ in fetched}
    assert ref not in rows or (rows[ref]["value"], rows[ref]["observed_at"]) == (
        1.701,
        "2026-10-01",
    )
    assert ref in rows or any(ref in line for line in refusals)


def test_a_changed_winning_value_cannot_be_recorded() -> None:
    # ICSA's September 17 response printing week 2026-09-12 as 198000, not
    # its first print 196000, on every read.
    def changed(series_id, vintage, raw, attempt):
        if series_id == "ICSA" and vintage == "2026-09-17":
            return raw.replace(b"2026-09-12,196000", b"2026-09-12,198000")
        return raw

    for today in (dt.date(2026, 9, 17), dt.date(2026, 9, 20)):
        fetched = resolve_pending.resolve_claims_ref(
            "us.dol.initial_claims.sa.week_2026-09-12",
            "2026-09-12",
            "initial",
            "2026-09-17",
            today,
            real_vintages(changed),
        )
        assert fetched is None or fetched[0]["value"] == 196.0


# Round 2, P2: a rejected response stayed in the cache and a repeated call
# trusted it.
def test_a_rejected_response_refuses_the_series_for_the_rest_of_the_run() -> None:
    def changed_once(series_id, vintage, raw, attempt):
        if series_id == "ICSA" and vintage == "2026-09-24" and attempt == 0:
            return raw.replace(b"2026-09-19,197000", b"2026-09-19,198000")
        return raw

    vintages = real_vintages(changed_once)
    for _ in range(2):
        assert (
            resolve_pending.resolve_claims_ref(
                "us.dol.initial_claims.sa.week_2026-09-19",
                "2026-09-19",
                "initial",
                "2026-09-24",
                dt.date(2026, 9, 25),
                vintages,
            )
            is None
        )
    with pytest.raises(resolve_pending.ClaimsVintageError, match="rest of this run"):
        vintages.read("ICSA", dt.date(2026, 9, 3))


def test_a_history_correction_without_a_new_week_is_consistent() -> None:
    """ALFRED re-issued history on 2017-03-24 without adding a week.

    Its ICSA vintage of 2017-03-24 differs from 2017-03-23 in 238 rows back to
    2012 but keeps week 2017-03-18 at 258000 (both fetched 2026-10-13). That
    must not refuse a first print. SYNTHETIC values in the same shape.
    """

    releases = {
        "ICSA": {
            "2026-09-03": {"2026-08-22": 204000.0, "2026-08-29": 206000.0},
            "2026-09-04": {
                "2026-08-08": 5.0,
                "2026-08-22": 205000.0,
                "2026-08-29": 206000.0,
            },
        }
    }
    vintages = resolve_pending.ClaimsVintages(
        fetch_from(releases, before_first_release="2026-08-22")
    )
    found = vintages.first_print("initial", "2026-08-29", dt.date(2026, 9, 6))
    assert found is not None
    assert (found[0], found[1]) == (dt.date(2026, 9, 3), 206000.0)


def test_a_release_day_resolution_waits_for_the_next_vintage_day(capsys) -> None:
    import resolution_status

    ref = "us.dol.initial_claims.sa.week_2026-09-12"
    args = (ref, "2026-09-12", "initial", "2026-09-17")
    assert (
        resolve_pending.resolve_claims_ref(*args, dt.date(2026, 9, 17), real_vintages())
        is None
    )
    targets, _summary = resolution_status.parse_resolver_log(
        capsys.readouterr().out, {ref}
    )
    assert targets[ref]["state"] == "deferred"
    assert "must corroborate it" in targets[ref]["detail"]
    fetched = resolve_pending.resolve_claims_ref(
        *args, dt.date(2026, 9, 18), real_vintages()
    )
    assert fetched is not None and fetched[0]["value"] == 196.0


def test_a_revision_on_the_very_next_day_refuses_rather_than_choosing() -> None:
    # SYNTHETIC: releases on consecutive days, the second revising the week.
    # Only the corroboration check sees it: the two vintages end at different
    # weeks, so neither consistency rule applies.
    releases = {
        "ICSA": {
            "2026-09-03": {"2026-08-22": 204000.0, "2026-08-29": 206000.0},
            "2026-09-04": {
                "2026-08-22": 204000.0,
                "2026-08-29": 207000.0,
                "2026-09-05": 210000.0,
            },
        }
    }
    vintages = resolve_pending.ClaimsVintages(
        fetch_from(releases, before_first_release="2026-08-22")
    )
    with pytest.raises(resolve_pending.ClaimsVintageError, match="next day's vintage"):
        vintages.first_print("initial", "2026-08-29", dt.date(2026, 9, 6))


# Review of #345, round 3 (GPT-6.1 Sol). Each faulted one date persistently
# and steered bisection; the schedule-anchored check never reads those dates
# or refuses on them.
def test_a_stale_older_release_on_one_date_cannot_steer_the_answer() -> None:
    def stale(series_id, vintage, raw, attempt):
        if series_id == "ICSA" and vintage == "2026-09-09":
            header = raw.split(b"\n", 1)[0]
            older = filled(ALFRED["series"]["ICSA"]["2026-08-27"])
            return header + b"\n" + csv_bytes("ICSA", vintage, older).split(b"\n", 1)[1]
        return raw

    fetched = resolve_pending.resolve_claims_ref(
        "us.dol.initial_claims.sa.week_2026-08-29",
        "2026-08-29",
        "initial",
        "2026-09-11",
        dt.date(2026, 9, 20),
        real_vintages(stale),
    )
    assert fetched is not None
    assert (fetched[0]["value"], fetched[0]["observed_at"]) == (206.0, "2026-09-03")


def test_a_truncated_altered_body_on_one_date_cannot_steer_the_answer() -> None:
    def altered(series_id, vintage, raw, attempt):
        if series_id == "ICSA" and vintage == "2026-09-23":
            lines = raw.rstrip(b"\n").split(b"\n")[:-1]
            return (
                b"\n".join(lines).replace(b"2026-08-08,212000", b"2026-08-08,211000")
                + b"\n"
            )
        return raw

    fetched = resolve_pending.resolve_claims_ref(
        "us.dol.initial_claims.sa.week_2026-09-12",
        "2026-09-12",
        "initial",
        "2026-09-29",
        dt.date(2026, 10, 4),
        real_vintages(altered),
    )
    assert fetched is not None
    assert (fetched[0]["value"], fetched[0]["observed_at"]) == (196.0, "2026-09-17")


def test_an_early_presence_cannot_move_the_correction_date() -> None:
    def early(series_id, vintage, raw, attempt):
        if series_id == "CCSA" and vintage == "2026-09-30" and attempt == 0:
            return raw + b"2026-09-19,1701000\n"
        return raw

    ref = "dol.eta.continued_claims.sa.week_2026-09-19.first_print"
    fetched, supersedes, refusals = resolve_pending.claims_corrections(
        LATE_ROWS, real_vintages(early)
    )
    rows = {row["source_record_id"]: row for row, *_ in fetched}
    assert ref not in rows
    assert ref not in supersedes
    assert any(ref in line and "before DOL's" in line for line in refusals)


def test_the_supporting_reads_are_kept_for_the_run() -> None:
    vintages = real_vintages()
    ref = "us.dol.initial_claims.sa.week_2026-08-29"
    resolve_pending.resolve_claims_ref(
        ref, "2026-08-29", "initial", "2026-09-11", dt.date(2026, 9, 20), vintages
    )
    assert [
        (role, day.isoformat()) for role, day, _raw, _at in vintages.evidence[ref]
    ] == [
        ("vintage_before_release", "2026-09-02"),
        ("vintage_before_release_reread", "2026-09-02"),
        ("vintage_after_release", "2026-09-04"),
    ]
    _fetched, _supersedes, _refusals = resolve_pending.claims_corrections(
        LATE_ROWS, vintages
    )
    assert set(resolve_pending.CLAIMS_FIRST_PRINT_CORRECTIONS) <= set(vintages.evidence)


def build_claims_run(tmp_path, monkeypatch, mutate=None):
    """A sealed resolver run for one claims fact and its first-print evidence."""

    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    vintages = real_vintages()
    ref = "us.dol.initial_claims.sa.week_2026-08-29"
    row, series_id, vintage, raw, retrieved_at, extension = (
        resolve_pending.resolve_claims_ref(
            ref, "2026-08-29", "initial", "2026-09-11", dt.date(2026, 9, 20), vintages
        )
    )
    run_dir = resolve_pending.resolution_run_dir("2026-10-13T03:00:00Z")
    run_dir.mkdir(parents=True)
    attached = resolve_pending.attach_resolution_provenance(
        row,
        run_dir=run_dir,
        series_id=series_id,
        vintage=vintage,
        raw=raw,
        retrieved_at="2026-10-13T03:00:00Z",
        ledger_repo_sha="d7e45bc5751357fdac1cfc182e1abaa414b675f3",
        target_contracts={},
        extension=extension,
    )
    evidence = [
        {
            "role": role,
            "vintageDate": day.isoformat(),
            "retrievedAt": at,
            "responseArchive": resolve_pending.archive_response(
                run_dir, series_id=series_id, vintage=day.isoformat(), raw=body
            ),
        }
        for role, day, body, at in vintages.evidence[ref]
    ]
    manifest = {
        "schemaVersion": "thesis_resolution_run_v1",
        "retrievedAt": "2026-10-13T03:00:00Z",
        "firstPrintEvidenceRequired": True,
        "weeklyClaimsSchedule": SCHEDULE_PROVENANCE,
        "ledgerRepo": "PolicyEngine/chronicle",
        "ledgerBranch": "codex/thesis-ledger-facts",
        "ledgerRepoSha": "d7e45bc5751357fdac1cfc182e1abaa414b675f3",
        "facts": [
            {
                "dataPointId": ref,
                "sourceVintage": attached["sourceVintage"],
                "retrievedAt": attached["retrievedAt"],
                "targetContentHash": None,
                "responseArchive": attached["responseArchive"],
                "firstPrintEvidence": evidence,
            }
        ],
    }
    if mutate is not None:
        mutate(run_dir, manifest)
    return run_dir, resolve_pending.finalize_resolution_manifest(run_dir, manifest)


def test_a_claims_run_seals_its_evidence_and_custody_verifies(
    tmp_path, monkeypatch
) -> None:
    from verify_custody import verify_run

    run_dir, manifest = build_claims_run(tmp_path, monkeypatch)
    archived = sorted(path.name for path in (run_dir / "responses").iterdir())
    # The day-before read twice is one archive: identical bytes, one file.
    assert len(archived) == 3
    assert {a["path"].rsplit("/", 1)[1] for a in manifest["artifacts"][:-1]} == set(
        archived
    )
    assert verify_run(run_dir).run_mode == "resolver"


def evidence_mutation(change):
    """Edit the manifest before sealing, then drop archives it no longer names,
    so custody judges the evidence rule rather than an orphaned file."""

    def mutate(run_dir, manifest):
        change(manifest["facts"][0], manifest)
        named = {
            archive["path"].rsplit("/", 1)[1]
            for fact in manifest["facts"]
            for archive in (
                fact["responseArchive"],
                *(
                    item["responseArchive"]
                    for item in fact.get("firstPrintEvidence", [])
                ),
            )
        }
        for path in (run_dir / "responses").iterdir():
            if path.name not in named:
                path.unlink()

    return mutate


@pytest.mark.parametrize(
    ("label", "change", "message"),
    [
        (
            "an unknown role",
            lambda fact, m: fact["firstPrintEvidence"][0].update(role="anything"),
            "must hold each",
        ),
        (
            "the re-read dropped",
            lambda fact, m: fact["firstPrintEvidence"].pop(1),
            "must hold each",
        ),
        (
            "a role repeated",
            lambda fact, m: fact["firstPrintEvidence"][1].update(
                role="vintage_before_release"
            ),
            "must hold each",
        ),
        (
            "a wrong date",
            lambda fact, m: fact["firstPrintEvidence"][2].update(
                vintageDate="9999-99-99"
            ),
            "no valid date",
        ),
        (
            "no retrieval instant",
            lambda fact, m: fact["firstPrintEvidence"][0].update(retrievedAt=""),
            "retrievedAt",
        ),
        (
            "the day after standing in for the day before",
            lambda fact, m: fact["firstPrintEvidence"][0].update(
                vintageDate="2026-09-02",
                responseArchive=fact["firstPrintEvidence"][2]["responseArchive"],
            ),
            "is not ICSA 2026-09-02",
        ),
        (
            "the primary response standing in for the day after",
            lambda fact, m: fact["firstPrintEvidence"][2].update(
                responseArchive=fact["responseArchive"]
            ),
            "is not ICSA 2026-09-04",
        ),
        (
            "no evidence at all on a new run",
            lambda fact, m: fact.pop("firstPrintEvidence"),
            "lacks firstPrintEvidence",
        ),
    ],
)
def test_custody_replays_and_refuses_bad_evidence(
    label, change, message, tmp_path, monkeypatch
) -> None:
    from verify_custody import CustodyError

    with pytest.raises(CustodyError, match=message):
        build_claims_run(tmp_path, monkeypatch, evidence_mutation(change))


def test_custody_still_accepts_a_historical_claims_run_without_evidence(
    tmp_path, monkeypatch
) -> None:
    def historical(run_dir, manifest):
        fact = manifest["facts"][0]
        for item in fact.pop("firstPrintEvidence"):
            path = resolve_pending.ROOT / item["responseArchive"]["path"]
            if (
                path.exists()
                and path.resolve()
                != (resolve_pending.ROOT / fact["responseArchive"]["path"]).resolve()
            ):
                path.unlink()
        manifest.pop("firstPrintEvidenceRequired")

    _run_dir, manifest = build_claims_run(tmp_path, monkeypatch, historical)
    assert "firstPrintEvidenceRequired" not in manifest


def test_custody_refuses_an_unlisted_evidence_response(tmp_path, monkeypatch) -> None:
    from verify_custody import CustodyError

    def unlisted(run_dir, manifest):
        dropped = manifest["facts"][0]["firstPrintEvidence"].pop()
        assert (resolve_pending.ROOT / dropped["responseArchive"]["path"]).exists()

    with pytest.raises(CustodyError, match="inventory mismatch"):
        build_claims_run(tmp_path, monkeypatch, unlisted)


def test_a_correction_archives_the_vintage_its_row_was_read_from() -> None:
    vintages = real_vintages()
    resolve_pending.claims_corrections(LATE_ROWS, vintages)
    ref = "us.dol.initial_claims.sa.week_2026-09-12"
    assert [
        (role, day.isoformat()) for role, day, _raw, _at in vintages.evidence[ref]
    ] == [
        ("vintage_before_release", "2026-09-16"),
        ("vintage_before_release_reread", "2026-09-16"),
        ("vintage_after_release", "2026-09-18"),
        ("superseded_row_vintage", "2026-09-29"),
    ]


def test_a_later_date_ending_earlier_is_refused() -> None:
    releases = {"ICSA": ALFRED["series"]["ICSA"]}

    def stale_later(series_id, vintage, raw, attempt):
        if vintage == "2026-09-20":
            older = ALFRED["series"]["ICSA"]["2026-09-03"]
            return csv_bytes("ICSA", vintage, filled(older))
        return raw

    vintages = resolve_pending.ClaimsVintages(fetch_from(releases, stale_later))
    vintages.read("ICSA", dt.date(2026, 9, 18))
    with pytest.raises(resolve_pending.ClaimsVintageError, match="vintages disagree"):
        vintages.read("ICSA", dt.date(2026, 9, 20))


def test_two_dates_ending_at_one_week_must_print_it_the_same() -> None:
    def changed(series_id, vintage, raw, attempt):
        if vintage == "2026-09-05":
            return raw.replace(b"2026-08-29,206000", b"2026-08-29,205000")
        return raw

    vintages = real_vintages(changed)
    vintages.read("ICSA", dt.date(2026, 9, 4))
    with pytest.raises(resolve_pending.ClaimsVintageError, match="print it as"):
        vintages.read("ICSA", dt.date(2026, 9, 5))


def build_correction_run(tmp_path, monkeypatch, mutate=None):
    """A sealed resolver run holding all six corrections and their evidence."""

    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    vintages = real_vintages()
    fetched, supersedes, refusals = resolve_pending.claims_corrections(
        LATE_ROWS, vintages
    )
    assert refusals == [] and len(fetched) == 6
    run_dir = resolve_pending.resolution_run_dir("2026-10-13T04:00:00Z")
    run_dir.mkdir(parents=True)
    facts = []
    for row, series_id, vintage, raw, _at, extension in fetched:
        attached = resolve_pending.attach_resolution_provenance(
            row,
            run_dir=run_dir,
            series_id=series_id,
            vintage=vintage,
            raw=raw,
            retrieved_at="2026-10-13T04:00:00Z",
            ledger_repo_sha="d7e45bc5751357fdac1cfc182e1abaa414b675f3",
            target_contracts={},
            extension=extension,
        )
        facts.append(
            {
                "dataPointId": row["source_record_id"],
                "sourceVintage": attached["sourceVintage"],
                "retrievedAt": attached["retrievedAt"],
                "targetContentHash": None,
                "responseArchive": attached["responseArchive"],
                "supersedes": supersedes[row["source_record_id"]],
                "firstPrintEvidence": [
                    {
                        "role": role,
                        "vintageDate": day.isoformat(),
                        "retrievedAt": "2026-10-13T04:00:00Z",
                        "responseArchive": resolve_pending.archive_response(
                            run_dir,
                            series_id=series_id,
                            vintage=day.isoformat(),
                            raw=body,
                        ),
                    }
                    for role, day, body, _at in vintages.evidence[
                        row["source_record_id"]
                    ]
                ],
            }
        )
    manifest = {
        "schemaVersion": "thesis_resolution_run_v1",
        "retrievedAt": "2026-10-13T04:00:00Z",
        "firstPrintEvidenceRequired": True,
        "weeklyClaimsSchedule": SCHEDULE_PROVENANCE,
        "ledgerRepo": "PolicyEngine/chronicle",
        "ledgerBranch": "codex/thesis-ledger-facts",
        "ledgerRepoSha": "d7e45bc5751357fdac1cfc182e1abaa414b675f3",
        "facts": facts,
    }
    if mutate is not None:
        mutate(run_dir, manifest)
    resolve_pending.finalize_resolution_manifest(run_dir, manifest)
    return run_dir


def test_a_correction_run_seals_and_replays_its_four_reads(
    tmp_path, monkeypatch
) -> None:
    run_dir = build_correction_run(tmp_path, monkeypatch)
    assert verify_custody.verify_run(run_dir).run_mode == "resolver"


def prune(run_dir, manifest):
    named = {
        archive["path"].rsplit("/", 1)[1]
        for fact in manifest["facts"]
        for archive in (
            fact["responseArchive"],
            *(item["responseArchive"] for item in fact.get("firstPrintEvidence", [])),
        )
    }
    for path in (run_dir / "responses").iterdir():
        if path.name not in named:
            path.unlink()


def replace_archive(run_dir, item, series, day, body):
    path = resolve_pending.ROOT / item["responseArchive"]["path"]
    if path.exists():
        path.unlink()
    item["responseArchive"] = resolve_pending.archive_response(
        run_dir, series_id=series, vintage=day, raw=body
    )


@pytest.mark.parametrize(
    ("label", "change", "message"),
    [
        (
            "a correction without the superseded row's read",
            lambda run_dir, m: [
                fact.update(
                    firstPrintEvidence=[
                        item
                        for item in fact["firstPrintEvidence"]
                        if item["role"] != "superseded_row_vintage"
                    ]
                )
                for fact in m["facts"]
            ],
            "exactly when the fact supersedes",
        ),
        (
            "the read without a supersedes",
            lambda run_dir, m: m["facts"][0].pop("supersedes"),
            "exactly when the fact supersedes",
        ),
        (
            "an unparseable superseded date",
            lambda run_dir, m: [
                item.update(vintageDate="9999-99-99")
                for item in m["facts"][0]["firstPrintEvidence"]
                if item["role"] == "superseded_row_vintage"
            ],
            "no valid date",
        ),
        (
            "the superseded read dated on the release day",
            lambda run_dir, m: [
                item.update(
                    vintageDate=m["facts"][0]["sourceVintage"],
                    responseArchive=m["facts"][0]["responseArchive"],
                )
                for item in m["facts"][0]["firstPrintEvidence"]
                if item["role"] == "superseded_row_vintage"
            ],
            "is not a later release",
        ),
        (
            "a date-only retrieval instant",
            lambda run_dir, m: m["facts"][0]["firstPrintEvidence"][0].update(
                retrievedAt="2026-10-13"
            ),
            "retrievedAt",
        ),
        (
            "a retrieval instant without an offset",
            lambda run_dir, m: m["facts"][0]["firstPrintEvidence"][0].update(
                retrievedAt="2026-10-13T04:00:00"
            ),
            "retrievedAt",
        ),
    ],
)
def test_custody_refuses_a_correction_missing_its_proof(
    label, change, message, tmp_path, monkeypatch
) -> None:
    def mutate(run_dir, manifest):
        change(run_dir, manifest)
        prune(run_dir, manifest)

    with pytest.raises(verify_custody.CustodyError, match=message):
        build_correction_run(tmp_path, monkeypatch, mutate)


def test_custody_replays_bodies_by_the_resolvers_rules(tmp_path, monkeypatch) -> None:
    # Review of #345, round 5: an empty day-before body and a non-numeric
    # target both sealed. Custody now parses with the resolver's own parser.
    def empty_before(run_dir, manifest):
        fact = manifest["facts"][0]
        for item in fact["firstPrintEvidence"][:2]:
            stamp = item["vintageDate"].replace("-", "")
            header_only = f"observation_date,ICSA_{stamp}\n".encode()
            replace_archive(run_dir, item, "ICSA", item["vintageDate"], header_only)
        prune(run_dir, manifest)

    with pytest.raises(verify_custody.CustodyError, match="holds no weeks"):
        build_claims_run(tmp_path, monkeypatch, empty_before)


def test_custody_refuses_a_non_numeric_target(tmp_path, monkeypatch) -> None:
    def not_a_number(run_dir, manifest):
        fact = manifest["facts"][0]
        after = fact["firstPrintEvidence"][2]
        path = resolve_pending.ROOT / after["responseArchive"]["path"]
        body = gzip.decompress(path.read_bytes()).replace(
            b"2026-08-29,206000", b"2026-08-29,not-a-number"
        )
        replace_archive(run_dir, after, "ICSA", "2026-09-04", body)
        prune(run_dir, manifest)

    with pytest.raises(verify_custody.CustodyError, match="breaks the weekly"):
        build_claims_run(tmp_path, monkeypatch, not_a_number)


def test_an_early_print_names_the_exception_table(capsys) -> None:
    week = dt.date(2026, 9, 26)
    vintages = synthetic_vintages(week, dt.date(2026, 9, 30))
    assert (
        resolve_pending.resolve_claims_ref(
            "ref",
            week.isoformat(),
            "initial",
            "2026-10-01",
            dt.date(2026, 10, 5),
            vintages,
        )
        is None
    )
    assert "WEEKLY_CLAIMS_RELEASE_EXCEPTIONS" in capsys.readouterr().out


def test_custody_refuses_a_day_after_that_prints_another_value(
    tmp_path, monkeypatch
) -> None:
    # The day after serving a later release (September 10's rows, which add
    # week September 5 and revise week August 29 to 207000) under its own
    # header: no consistency rule applies, so only the day-after check can
    # refuse it.
    def later_release(run_dir, manifest):
        after = manifest["facts"][0]["firstPrintEvidence"][2]
        rows = filled(ALFRED["series"]["ICSA"]["2026-09-10"])
        replace_archive(
            run_dir, after, "ICSA", "2026-09-04", csv_bytes("ICSA", "2026-09-04", rows)
        )
        prune(run_dir, manifest)

    with pytest.raises(verify_custody.CustodyError, match="next day's vintage"):
        build_claims_run(tmp_path, monkeypatch, later_release)


def seal_claims_fact(tmp_path, monkeypatch, ref, series, release_day, bodies):
    """Seal a run holding one weekly claims fact built from the given bodies.

    ``bodies`` maps each role (release_day included) to (vintage date, raw).
    """

    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    run_dir = resolve_pending.resolution_run_dir("2026-10-13T05:00:00Z")
    run_dir.mkdir(parents=True)

    def archive(day, raw):
        return resolve_pending.archive_response(
            run_dir, series_id=series, vintage=day, raw=raw
        )

    manifest = {
        "schemaVersion": "thesis_resolution_run_v1",
        "retrievedAt": "2026-10-13T05:00:00Z",
        "firstPrintEvidenceRequired": True,
        "weeklyClaimsSchedule": SCHEDULE_PROVENANCE,
        "ledgerRepo": "PolicyEngine/chronicle",
        "ledgerBranch": "codex/thesis-ledger-facts",
        "ledgerRepoSha": "d7e45bc5751357fdac1cfc182e1abaa414b675f3",
        "facts": [
            {
                "dataPointId": ref,
                "sourceVintage": release_day,
                "retrievedAt": "2026-10-13T05:00:00Z",
                "targetContentHash": None,
                "responseArchive": archive(*bodies["release_day"]),
                "firstPrintEvidence": [
                    {
                        "role": role,
                        "vintageDate": day,
                        "retrievedAt": "2026-10-13T05:00:00Z",
                        "responseArchive": archive(day, raw),
                    }
                    for role, (day, raw) in bodies.items()
                    if role != "release_day"
                ],
            }
        ],
    }
    return resolve_pending.finalize_resolution_manifest(run_dir, manifest)


def icsa_body(day, release, extra=None):
    rows = filled(dict(ALFRED["series"]["ICSA"][release], **(extra or {})))
    return day, csv_bytes("ICSA", day, rows)


# Review of #345, round 6 (GPT-6.1 Sol): custody replayed each body alone and
# trusted the fact's release day. It now re-decides with the resolver's judge.
def test_custody_refuses_a_release_body_ending_after_the_day_after(
    tmp_path, monkeypatch
) -> None:
    bodies = {
        "vintage_before_release": icsa_body("2026-09-02", "2026-08-27"),
        "vintage_before_release_reread": icsa_body("2026-09-02", "2026-08-27"),
        "release_day": icsa_body("2026-09-03", "2026-09-03", {"2026-09-05": 1.0}),
        "vintage_after_release": icsa_body("2026-09-04", "2026-09-03"),
    }
    with pytest.raises(verify_custody.CustodyError, match="vintages disagree"):
        seal_claims_fact(
            tmp_path,
            monkeypatch,
            "us.dol.initial_claims.sa.week_2026-08-29",
            "ICSA",
            "2026-09-03",
            bodies,
        )


def test_custody_refuses_two_bodies_printing_one_last_week_two_ways(
    tmp_path, monkeypatch
) -> None:
    bodies = {
        "vintage_before_release": icsa_body("2026-09-02", "2026-08-27"),
        "vintage_before_release_reread": icsa_body("2026-09-02", "2026-08-27"),
        "release_day": icsa_body("2026-09-03", "2026-09-03", {"2026-09-05": 1.0}),
        "vintage_after_release": icsa_body(
            "2026-09-04", "2026-09-03", {"2026-09-05": 2.0}
        ),
    }
    with pytest.raises(verify_custody.CustodyError, match="print it as"):
        seal_claims_fact(
            tmp_path,
            monkeypatch,
            "us.dol.initial_claims.sa.week_2026-08-29",
            "ICSA",
            "2026-09-03",
            bodies,
        )


def test_custody_refuses_a_release_day_off_dols_schedule(tmp_path, monkeypatch) -> None:
    # SYNTHETIC: week 2026-09-26 first printed a day late, 2026-10-02, with
    # honest reads around that day. DOL's schedule says 2026-10-01, and no
    # exception is listed, so the resolver defers and custody must refuse.
    late = {"2026-09-26": 197000.0}
    bodies = {
        "vintage_before_release": icsa_body("2026-10-01", "2026-09-24"),
        "vintage_before_release_reread": icsa_body("2026-10-01", "2026-09-24"),
        "release_day": icsa_body("2026-10-02", "2026-09-24", late),
        "vintage_after_release": icsa_body("2026-10-03", "2026-09-24", late),
    }
    with pytest.raises(verify_custody.CustodyError, match="DOL's release of week"):
        seal_claims_fact(
            tmp_path,
            monkeypatch,
            "us.dol.initial_claims.sa.week_2026-09-26",
            "ICSA",
            "2026-10-02",
            bodies,
        )


def seal_claims_facts(tmp_path, monkeypatch, facts):
    """Seal a run of claims facts, each (ref, release_day, bodies, supersedes)."""

    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    run_dir = resolve_pending.resolution_run_dir("2026-10-13T06:00:00Z")
    run_dir.mkdir(parents=True)

    def archive(day, raw):
        return resolve_pending.archive_response(
            run_dir, series_id="ICSA", vintage=day, raw=raw
        )

    entries = []
    for ref, release_day, bodies, supersedes in facts:
        entry = {
            "dataPointId": ref,
            "sourceVintage": release_day,
            "retrievedAt": "2026-10-13T06:00:00Z",
            "targetContentHash": None,
            "responseArchive": archive(*bodies["release_day"]),
            "firstPrintEvidence": [
                {
                    "role": role,
                    "vintageDate": day,
                    "retrievedAt": "2026-10-13T06:00:00Z",
                    "responseArchive": archive(day, raw),
                }
                for role, (day, raw) in bodies.items()
                if role != "release_day"
            ],
        }
        if supersedes:
            entry["supersedes"] = supersedes
        entries.append(entry)
    return resolve_pending.finalize_resolution_manifest(
        run_dir,
        {
            "schemaVersion": "thesis_resolution_run_v1",
            "retrievedAt": "2026-10-13T06:00:00Z",
            "firstPrintEvidenceRequired": True,
            "weeklyClaimsSchedule": SCHEDULE_PROVENANCE,
            "ledgerRepo": "PolicyEngine/chronicle",
            "ledgerBranch": "codex/thesis-ledger-facts",
            "ledgerRepoSha": "d7e45bc5751357fdac1cfc182e1abaa414b675f3",
            "facts": entries,
        },
    )


WEEK_0829 = "us.dol.initial_claims.sa.week_2026-08-29"
WEEK_0905 = "us.dol.initial_claims.sa.week_2026-09-05"


def week_0829_bodies(**extra):
    return {
        "vintage_before_release": icsa_body("2026-09-02", "2026-08-27"),
        "vintage_before_release_reread": icsa_body("2026-09-02", "2026-08-27"),
        "release_day": icsa_body("2026-09-03", "2026-09-03"),
        "vintage_after_release": icsa_body("2026-09-04", "2026-09-03"),
        **extra,
    }


def week_0905_bodies(**changes):
    bodies = {
        "vintage_before_release": icsa_body("2026-09-09", "2026-09-03"),
        "vintage_before_release_reread": icsa_body("2026-09-09", "2026-09-03"),
        "release_day": icsa_body("2026-09-10", "2026-09-10"),
        "vintage_after_release": icsa_body("2026-09-11", "2026-09-10"),
    }
    bodies.update(changes)
    return bodies


def test_custody_accepts_a_consistent_run_of_two_claims_facts(
    tmp_path, monkeypatch
) -> None:
    seal_claims_facts(
        tmp_path,
        monkeypatch,
        [
            (WEEK_0829, "2026-09-03", week_0829_bodies(), None),
            (WEEK_0905, "2026-09-10", week_0905_bodies(), None),
        ],
    )


# Review of #345, round 7 (GPT-6.1 Sol): each fact replayed alone, so two
# facts could disagree with each other. The resolver checks its whole run.
def test_custody_refuses_facts_whose_reads_disagree_across_the_run(
    tmp_path, monkeypatch
) -> None:
    # September 9 read as the August 27 release (ending August 22): fine for
    # the September 5 fact alone, but the August 29 fact's September 4 read
    # already ends at August 29.
    stale = icsa_body("2026-09-09", "2026-08-27")
    bodies = week_0905_bodies(
        vintage_before_release=stale, vintage_before_release_reread=stale
    )
    with pytest.raises(verify_custody.CustodyError, match="reads do not agree"):
        seal_claims_facts(
            tmp_path,
            monkeypatch,
            [
                (WEEK_0829, "2026-09-03", week_0829_bodies(), None),
                (WEEK_0905, "2026-09-10", bodies, None),
            ],
        )


def test_custody_refuses_two_archives_of_one_series_date_that_differ(
    tmp_path, monkeypatch
) -> None:
    # The August 29 correction archives September 11 as read; the September
    # 5 fact archives a September 11 that differs only in old history, so
    # both end at September 5 with the same value and pass consistency.
    genuine = icsa_body("2026-09-11", "2026-09-10")
    altered = (
        "2026-09-11",
        genuine[1].replace(b"2026-08-08,212000", b"2026-08-08,211000"),
    )
    with pytest.raises(
        verify_custody.CustodyError, match="vintages of 2026-09-11 differ"
    ):
        seal_claims_facts(
            tmp_path,
            monkeypatch,
            [
                (
                    WEEK_0829,
                    "2026-09-03",
                    week_0829_bodies(superseded_row_vintage=genuine),
                    "av2:" + "a" * 64,
                ),
                (
                    WEEK_0905,
                    "2026-09-10",
                    week_0905_bodies(vintage_after_release=altered),
                    None,
                ),
            ],
        )


def test_the_run_records_the_schedule_it_decided_with() -> None:
    import inspect

    source = inspect.getsource(resolve_pending.main)
    assert '"weeklyClaimsSchedule"' in source
    assert "WEEKLY_CLAIMS_RELEASE_EXCEPTIONS" in source


# Review of #345, round 8: a catalog-refused claims row left its evidence
# archives in the run, so the run's custody check failed and every other
# resolution was lost; and deleting a refused row's archive could remove a
# file a kept row's evidence used.
def test_a_catalog_refused_claims_row_takes_its_evidence_and_nothing_else(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    vintages = real_vintages()
    refused_ref = "us.dol.initial_claims.sa.week_2026-08-29"
    kept_ref = "us.dol.initial_claims.sa.week_2026-09-05"
    fetched = [
        resolve_pending.resolve_claims_ref(
            ref, week, "initial", release, dt.date(2026, 9, 20), vintages
        )
        for ref, week, release in (
            (refused_ref, "2026-08-29", "2026-09-03"),
            (kept_ref, "2026-09-05", "2026-09-10"),
        )
    ]
    run_dir = resolve_pending.resolution_run_dir("2026-10-13T07:00:00Z")
    run_dir.mkdir(parents=True)
    rows, evidence = [], {}
    for row, series_id, vintage, raw, _at, extension in fetched:
        rows.append(
            resolve_pending.attach_resolution_provenance(
                row,
                run_dir=run_dir,
                series_id=series_id,
                vintage=vintage,
                raw=raw,
                retrieved_at="2026-10-13T07:00:00Z",
                ledger_repo_sha="d7e45bc5751357fdac1cfc182e1abaa414b675f3",
                target_contracts={},
                extension=extension,
            )
        )
        record_id = row["source_record_id"]
        evidence[record_id] = [
            {
                "role": role,
                "vintageDate": day.isoformat(),
                "retrievedAt": at,
                "responseArchive": resolve_pending.archive_response(
                    run_dir, series_id=series_id, vintage=day.isoformat(), raw=body
                ),
            }
            for role, day, body, at in vintages.evidence[record_id]
        ]
    refused_archives = {rows[0]["responseArchive"]["path"]} | {
        item["responseArchive"]["path"] for item in evidence[refused_ref]
    }
    kept = resolve_pending.exclude_catalog_refusals(
        rows, {refused_ref: "unit conflict"}, evidence
    )
    assert [row["source_record_id"] for row in kept] == [kept_ref]
    assert refused_ref not in evidence
    assert not any((tmp_path / path).exists() for path in refused_archives)
    for item in evidence[kept_ref]:
        assert (tmp_path / item["responseArchive"]["path"]).exists()
    manifest = resolve_pending.finalize_resolution_manifest(
        run_dir,
        {
            "schemaVersion": "thesis_resolution_run_v1",
            "retrievedAt": "2026-10-13T07:00:00Z",
            "firstPrintEvidenceRequired": True,
            "weeklyClaimsSchedule": SCHEDULE_PROVENANCE,
            "ledgerRepo": "PolicyEngine/chronicle",
            "ledgerBranch": "codex/thesis-ledger-facts",
            "ledgerRepoSha": "d7e45bc5751357fdac1cfc182e1abaa414b675f3",
            "facts": [
                {
                    "dataPointId": row["source_record_id"],
                    "sourceVintage": row["sourceVintage"],
                    "retrievedAt": row["retrievedAt"],
                    "targetContentHash": None,
                    "responseArchive": row["responseArchive"],
                    "firstPrintEvidence": evidence[row["source_record_id"]],
                }
                for row in kept
            ],
        },
    )
    assert manifest["ok"] is True
    assert verify_custody.verify_run(run_dir).run_mode == "resolver"


def test_a_shared_archive_survives_its_refused_owner(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    (tmp_path / "a.csv.gz").write_bytes(b"x")
    (tmp_path / "b.csv.gz").write_bytes(b"y")
    rows = [
        {"source_record_id": "refused", "responseArchive": {"path": "a.csv.gz"}},
        {"source_record_id": "kept", "responseArchive": {"path": "b.csv.gz"}},
    ]
    evidence = {
        "refused": [{"responseArchive": {"path": "b.csv.gz"}}],
        "kept": [{"responseArchive": {"path": "a.csv.gz"}}],
    }
    resolve_pending.exclude_catalog_refusals(rows, {"refused": "r"}, evidence)
    # a.csv.gz is the refused row's response but the kept row's evidence.
    assert (tmp_path / "a.csv.gz").exists() and (tmp_path / "b.csv.gz").exists()
    assert list(evidence) == ["kept"]


def test_custody_requires_the_schedule_on_a_new_claims_run(
    tmp_path, monkeypatch
) -> None:
    def no_schedule(run_dir, manifest):
        manifest.pop("weeklyClaimsSchedule")

    with pytest.raises(verify_custody.CustodyError, match="weeklyClaimsSchedule"):
        build_claims_run(tmp_path, monkeypatch, no_schedule)
