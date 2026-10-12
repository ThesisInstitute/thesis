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
  Thursday vintage from 2026-08-20 to 2026-10-08 printed them, fetched
  2026-10-12 from alfred.stlouisfed.org.
- tests/fixtures/chronicle_late_release_claims_rows.jsonl: the five rows in
  PolicyEngine/chronicle ledger/official_observations.jsonl (branch
  codex/thesis-ledger-facts at d7e45bc5751357fdac1cfc182e1abaa414b675f3,
  lines 222, 223, 225, 232 and 233) that CLAIMS_FIRST_PRINT_CORRECTIONS names.
Tests that need releases outside that range build SYNTHETIC vintages and say so.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import resolve_pending  # noqa: E402
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
GATE_SPEC = types.SimpleNamespace(
    assertion_content_keys=resolve_pending.ASSERTION_CONTENT_KEYS
)


def csv_bytes(series_id: str, vintage: str, rows: dict[str, float]) -> bytes:
    header = f"observation_date,{series_id}_{vintage.replace('-', '')}\n"
    return (
        header + "".join(f"{d},{int(v)}\n" for d, v in sorted(rows.items()))
    ).encode()


def fetch_from(releases_by_series: dict[str, dict[str, dict[str, float]]]):
    """An ALFRED stand-in: a vintage date returns the latest release on or before it."""

    def fetch(series_id: str, vintage: str):
        releases = releases_by_series[series_id]
        printed = [day for day in sorted(releases) if day <= vintage]
        rows = dict(releases[printed[-1]]) if printed else {}
        raw = csv_bytes(series_id, vintage, rows)
        parsed = resolve_pending.parse_fred_vintage_csv(raw, series_id, vintage)
        return parsed, raw, f"https://alfred.example/{series_id}/{vintage}", "t"

    return fetch


def real_vintages() -> resolve_pending.ClaimsVintages:
    return resolve_pending.ClaimsVintages(fetch_from(ALFRED["series"]))


def synthetic_vintages(week: dt.date, first: dt.date) -> resolve_pending.ClaimsVintages:
    """SYNTHETIC: `week` is present from `first` on, with the value 1000."""

    def fetch(series_id: str, vintage: str):
        rows = {week.isoformat(): 1000.0} if vintage >= first.isoformat() else {}
        return rows, csv_bytes(series_id, vintage, rows), "u", "t"

    return resolve_pending.ClaimsVintages(fetch)


# Invariant 1: bisection returns the first vintage that holds the week, the
# same day a linear scan finds, in at most 2 + ceil(log2(span)) requests.
def test_bisection_equals_a_linear_scan_for_every_span_and_first_day() -> None:
    week = dt.date(2026, 9, 26)
    for first_offset in range(1, 22):
        for extra in range(0, 15):
            first = week + dt.timedelta(days=first_offset)
            upper = first + dt.timedelta(days=extra)
            vintages = synthetic_vintages(week, first)
            found = vintages.first_vintage("ICSA", week.isoformat(), upper)
            assert found is not None
            linear = next(
                week + dt.timedelta(days=offset)
                for offset in range(1, (upper - week).days + 1)
                if week + dt.timedelta(days=offset) >= first
            )
            assert found[0] == linear == first
            span = (upper - week).days
            assert vintages.requests <= 2 + math.ceil(math.log2(span))


def test_first_vintage_is_none_until_the_week_is_printed() -> None:
    week = dt.date(2026, 9, 26)
    vintages = synthetic_vintages(week, dt.date(2026, 10, 1))
    assert (
        vintages.first_vintage("ICSA", week.isoformat(), dt.date(2026, 9, 30)) is None
    )
    assert vintages.first_vintage("ICSA", week.isoformat(), week) is None


def test_a_week_present_on_the_day_it_ends_is_refused() -> None:
    week = dt.date(2026, 9, 26)
    vintages = synthetic_vintages(week, week)
    with pytest.raises(
        resolve_pending.ClaimsVintageError, match="the day the week ends"
    ):
        vintages.first_vintage("ICSA", week.isoformat(), dt.date(2026, 10, 1))


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
            dt.date(2026, 10, 12),
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
        dt.date(2026, 9, 17),
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


def test_a_catch_up_release_still_yields_each_weeks_first_print() -> None:
    # SYNTHETIC: one release prints two weeks at once (as after the
    # Oct-Nov 2025 lapse in appropriations). It is the first print of both,
    # though it already holds the following week.
    releases = {
        "ICSA": {"2026-12-10": {"2026-11-28": 220000.0, "2026-12-05": 230000.0}}
    }
    fetched = resolve_pending.resolve_claims_ref(
        "ref",
        "2026-11-28",
        "initial",
        "2026-12-10",
        dt.date(2026, 12, 10),
        resolve_pending.ClaimsVintages(fetch_from(releases)),
    )
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
}


def test_the_table_names_exactly_the_five_real_rows() -> None:
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
def test_corrections_supersede_the_five_real_rows_with_first_prints() -> None:
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
    assert len(fetched) == 4
    assert len(refusals) == 1 and "is not the record's active row" in refusals[0]


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
