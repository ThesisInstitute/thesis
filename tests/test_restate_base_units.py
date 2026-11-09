"""The resolver's base-unit writer and its one-time restatement run.

Chronicle stores plain numbers (Max, 2026-10-21). The resolver writes a new row
in its unit's base unit once the ledger holds no current row in a scaled unit,
and ``--restate-base-units`` brings that about: one release that restates every
current scaled row, all or none. These tests hold both to the site's reader
(site/src/data/ledger-restatements.ts), through the resolver's port of it, and
to Chronicle's append gate (receipt 0.6.2).

Invariants:

* A row written in base units, and every restatement, states the quantity its
  recorded pair states: the stored value is the recorded value's shortest
  decimal with its digits moved by the unit's power of ten.
* Its method notes say the stored value is only as precise as that figure.
* A restatement differs from the row it restates only in the fields the site
  lets it change, and archives that row's exact line.
* After a restatement run no current row holds a scale, so a second run
  appends nothing.
* A restatement run that merged but never reached Thesis rebuilds to the byte.
* The resolver's current view is receipt's.
"""

from __future__ import annotations

import argparse
import copy
import decimal
import gzip
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

receipt_append_gate = pytest.importorskip("receipt.append_gate")

import generate_ledger_restatement_fixture as fixture_gen  # noqa: E402
import ledger_units  # noqa: E402
import resolve_pending  # noqa: E402
from generate_receipt_current_view_fixture import SPEC  # noqa: E402
from verify_custody import verify_run  # noqa: E402

WORKFLOW = ROOT / ".github/workflows/resolve-and-rebuild.yml"
RECEIPT_FIXTURE = ROOT / "site/src/__tests__/fixtures/receipt-current-view.json"
RETRIEVED_AT = fixture_gen.RETRIEVED_AT
SAMPLE_SHA = "fd83eec28bf90d852d6495fd0c1f8e0fa47291d1"
UNITS = sorted(ledger_units.SCALED_UNITS)

# Each scaled unit's power of ten, written out rather than read from
# ledger_units, so the value checks below do not grade the converter by itself.
POWERS = {
    "thousands": 3,
    "millions": 6,
    "usd_millions": 6,
    "usd_billions": 9,
    "billions USD": 9,
    "gbp_billions": 9,
    "million_cubic_feet": 6,
}


def _moved(value: float | int, unit: str) -> decimal.Decimal:
    """``value`` in its unit's base unit: its shortest decimal's digits, moved.

    Chronicle's ``_moved_by_power_of_ten`` reads a pair the same way.
    """

    sign, digits, exponent = decimal.Decimal(repr(value)).as_tuple()
    return decimal.Decimal((sign, digits, exponent + POWERS[unit]))


def _stores(value: float | int, moved: decimal.Decimal) -> bool:
    """``value`` is ``moved``, an int when ``moved`` is whole, else a float."""

    whole = moved == moved.to_integral_value()
    return (
        type(value) is (int if whole else float)
        and decimal.Decimal(repr(value)) == moved
    )


# Every decimal of at most 15 significant digits reads back from a double.
short_decimals = st.builds(
    lambda digits, exponent: float(f"{digits}e{exponent}"),
    st.integers(min_value=-(10**15) + 1, max_value=10**15 - 1),
    st.integers(min_value=-12, max_value=0),
)


def _fixture() -> dict:
    return json.loads(fixture_gen.FIXTURE.read_text())


def _sample() -> list[str]:
    fixture = _fixture()
    return [fixture["lines"][index] for index in fixture["sample"]]


def _writer() -> list[str]:
    fixture = _fixture()
    return [fixture["lines"][index] for index in fixture["writer"]]


def _scaled_lines(lines: list[str]) -> list[str]:
    rows = [json.loads(line) for line in lines]
    scaled = {id(row) for row in resolve_pending.scaled_current_rows(rows)}
    return [line for line, row in zip(lines, rows) if id(row) in scaled]


# The committed fixture the site replays.


def test_committed_fixture_is_what_the_writer_and_port_return() -> None:
    assert fixture_gen.FIXTURE.read_text() == fixture_gen.render(
        fixture_gen.build_fixture()
    ), (
        "site/src/__tests__/fixtures/ledger-restatements.json is stale; run "
        "uv run python scripts/generate_ledger_restatement_fixture.py"
    )


def test_the_sample_is_the_ledger_the_older_samples_saw() -> None:
    # Chronicle only appends, so a line an older sample holds is the same line
    # at the pin.
    sample = json.loads(fixture_gen.CHRONICLE_ROWS.read_text())
    assert sample["sha"] == SAMPLE_SHA
    shared = 0
    for older in ("chronicle_rows_598f394d.json", "chronicle_rows_8722b2da.json"):
        lines = json.loads((ROOT / "tests" / "fixtures" / older).read_text())["lines"]
        for number, line in lines.items():
            if number in sample["lines"]:
                assert sample["lines"][number] == line, (older, number)
                shared += 1
    assert shared == 12


def test_the_sample_holds_every_scaled_unit_the_ledger_restates() -> None:
    units = {json.loads(line)["measure"]["unit"] for line in _scaled_lines(_sample())}
    assert units == {
        "thousands",
        "millions",
        "usd_millions",
        "usd_billions",
        "billions USD",
        "gbp_billions",
    }


# Writing a row in base units.


def test_the_powers_are_the_converters() -> None:
    assert POWERS == {
        unit: power for unit, (_base, power) in ledger_units.SCALED_UNITS.items()
    }


@given(
    st.sampled_from(UNITS),
    st.one_of(short_decimals, st.integers(-(10**12), 10**12)),
)
def test_a_base_row_states_the_quantity_it_was_recorded_as(
    unit: str, value: float
) -> None:
    row = {
        "source_record_id": "test.series",
        "value": value,
        "measure": {"concept": "test", "unit": unit},
        "source": {"url": "https://official.example/"},
    }
    try:
        expected = ledger_units.to_base(value, unit)
    except ledger_units.LedgerUnitError:
        with pytest.raises(ledger_units.LedgerUnitError):
            resolve_pending.base_unit_row(row)
        return
    based = resolve_pending.base_unit_row(row)
    assert based["value"] == expected
    assert _stores(based["value"], _moved(value, unit))
    assert based["measure"] == {"concept": "test", "unit": ledger_units.base_unit(unit)}
    assert based["source"] == {
        "url": "https://official.example/",
        "recorded_value": value,
        "recorded_unit": unit,
        "method_notes": (
            f"Stores {value!r} {unit} in base units, at that figure's "
            "precision, so the archived response may hold more digits."
        ),
    }
    assert based["source_record_id"] == "test.series"
    resolve_pending.check_recorded_pair(based)
    # The row it was given is left as it was.
    assert row["measure"]["unit"] == unit and "recorded_unit" not in row["source"]


def test_a_row_without_a_scale_is_written_as_it_is() -> None:
    row = {"value": 4.2, "measure": {"unit": "percent"}, "source": {}}
    assert resolve_pending.base_unit_row(row) is row


def test_a_base_rows_notes_drop_the_scale_they_named() -> None:
    row = {
        "source_record_id": "test.series",
        "value": 3189.0,
        "measure": {"unit": "thousands"},
        "source": {"method_notes": "Labor force, expressed in thousands"},
    }
    assert resolve_pending.base_unit_row(row)["source"]["method_notes"] == (
        "Labor force. Stores 3189.0 thousands in base units, at that figure's "
        "precision, so the archived response may hold more digits."
    )


def test_a_base_row_refuses_notes_that_still_name_a_scale() -> None:
    # A ValueError, so the run refuses this row alone.
    row = {
        "source_record_id": "test.series",
        "value": 3189.0,
        "measure": {"unit": "thousands"},
        "source": {"method_notes": "Labor force, in thousands."},
    }
    with pytest.raises(ledger_units.LedgerUnitError, match="still name a scale"):
        resolve_pending.base_unit_row(row)


def test_a_row_that_already_records_a_pair_is_refused() -> None:
    row = {
        "source_record_id": "test.series",
        "value": 7.5,
        "measure": {"unit": "thousands"},
        "source": {"recorded_unit": "thousands"},
    }
    with pytest.raises(ledger_units.LedgerUnitError, match="already records a pair"):
        resolve_pending.base_unit_row(row)


@pytest.mark.parametrize(
    ("value", "stored", "pair", "refusal"),
    [
        (
            7500,
            "count",
            {"recorded_value": 7.5, "recorded_unit": "percent"},
            "not a number in a scaled unit",
        ),
        (
            7500,
            "count",
            {"recorded_value": True, "recorded_unit": "thousands"},
            "not a number in a scaled unit",
        ),
        (
            7500,
            "count",
            {"recorded_value": "7.5", "recorded_unit": "thousands"},
            "not a number in a scaled unit",
        ),
        (
            7500,
            "count",
            {"recorded_unit": "thousands"},
            "not a number in a scaled unit",
        ),
        (
            7500,
            "thousands",
            {"recorded_value": 7.5, "recorded_unit": "thousands"},
            "but stores 'thousands'",
        ),
        (
            7500,
            "usd",
            {"recorded_value": 7.5, "recorded_unit": "thousands"},
            "but stores 'usd'",
        ),
        (
            7501,
            "count",
            {"recorded_value": 7.5, "recorded_unit": "thousands"},
            "but stores 7501",
        ),
        (
            "7500",
            "count",
            {"recorded_value": 7.5, "recorded_unit": "thousands"},
            "but stores '7500'",
        ),
    ],
)
def test_a_recorded_pair_must_state_the_stored_value(
    value: object, stored: str, pair: dict, refusal: str
) -> None:
    row = {
        "source_record_id": "test.series",
        "value": value,
        "measure": {"unit": stored},
        "source": pair,
    }
    with pytest.raises(ledger_units.LedgerUnitError, match=refusal):
        resolve_pending.check_recorded_pair(row)


def test_a_row_without_a_pair_passes_the_pair_check() -> None:
    resolve_pending.check_recorded_pair(
        {"value": 7.5, "measure": {"unit": "thousands"}, "source": {}}
    )


def _registration(ref: str, unit: str) -> dict:
    return {
        "targetContentHash": "a" * 64,
        "contract": {
            "dataPointId": ref,
            "series": "test.series",
            "period": "2030",
            "unit": unit,
            "sourceBinding": {
                "allowedHosts": ["official.example"],
                "releasePolicy": "first_print",
                "table": "Official table",
                "field": "value",
                "transform": {"operation": "identity", "factor": 1},
            },
        },
        "ledgerPin": None,
    }


ROW = {
    "source_record_id": "test.series.2030.first_print",
    "value": 7.716,
    "observed_at": "2030-01-02",
    "period": {"type": "year", "value": 2030},
    "measure": {"concept": "test.series", "unit": "millions"},
    "source": {"url": "https://official.example/table.csv", "method_notes": "Level."},
}
RAW = b"value\n7.716\n"
WRITTEN_AT = "2030-01-02T12:00:00Z"


def _attach(
    tmp_path: pathlib.Path, monkeypatch, row: dict, *, base_units: bool
) -> dict:
    monkeypatch.setattr(resolve_pending, "ROOT", tmp_path)
    ref = row["source_record_id"]
    return resolve_pending.attach_resolution_provenance(
        copy.deepcopy(row),
        run_dir=resolve_pending.resolution_run_dir(WRITTEN_AT),
        series_id="TEST",
        vintage="2030-01-02",
        raw=RAW,
        retrieved_at=WRITTEN_AT,
        ledger_repo_sha="b" * 40,
        target_contracts={ref: _registration(ref, "millions")},
        base_units=base_units,
    )


def test_the_writer_keeps_recorded_units_while_the_ledger_holds_them(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    scaled = _attach(tmp_path, monkeypatch, ROW, base_units=False)
    assert {key: scaled[key] for key in ROW} == ROW
    assert scaled["sourceBindingProjection"] == (
        resolve_pending.source_binding_projection(
            _registration(ROW["source_record_id"], "millions"), ROW, RAW
        )
    )
    assert scaled["assertionVersion"] == resolve_pending.assertion_version(scaled)


def test_the_writer_stores_base_units_with_the_pair_it_recorded(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    based = _attach(tmp_path, monkeypatch, ROW, base_units=True)
    assert based["value"] == 7716000 and type(based["value"]) is int
    assert based["measure"] == {"concept": "test.series", "unit": "count"}
    assert based["source"] == {
        **ROW["source"],
        "recorded_value": 7.716,
        "recorded_unit": "millions",
        "method_notes": (
            "Level. Stores 7.716 millions in base units, at that figure's "
            "precision, so the archived response may hold more digits."
        ),
    }
    projection = based["sourceBindingProjection"]
    assert projection["unit"] == "count"
    assert projection["responseSha256"] == based["responseArchive"]["sha256"]
    # The id addresses what the row stores.
    assert based["assertionVersion"] == resolve_pending.assertion_version(based)
    line = resolve_pending.ledger_line(based)
    assert resolve_pending.check_restatements([line]) == []
    receipt_append_gate.check_rows([line], 0, SPEC)
    receipt_append_gate.check_binding_shapes([line], 0)
    run_dir = resolve_pending.resolution_run_dir(WRITTEN_AT)
    assert len(list((run_dir / "responses").iterdir())) == 1


def test_a_value_with_no_exact_base_form_is_refused_before_its_archive(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    # 1e13 millions is 1e19, past 2**53 - 1. The run refuses the row alone, as
    # it does a contract mismatch, so the refusal must be a ValueError.
    assert issubclass(ledger_units.LedgerUnitError, ValueError)
    with pytest.raises(ledger_units.LedgerUnitError):
        _attach(tmp_path, monkeypatch, {**ROW, "value": 1e13}, base_units=True)
    assert not (resolve_pending.resolution_run_dir(WRITTEN_AT) / "responses").exists()


def test_the_contract_check_still_reads_the_registered_unit(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    row = {**ROW, "measure": {"concept": "test.series", "unit": "count"}}
    with pytest.raises(ValueError, match="does not match registered unit"):
        _attach(tmp_path, monkeypatch, row, base_units=True)


def test_the_run_says_which_units_it_writes(capsys) -> None:
    sample = [json.loads(line) for line in _sample()]
    assert resolve_pending.print_ledger_units_mode(sample) is False
    assert capsys.readouterr().out == (
        "ledger units: as recorded; 19 current row(s) still carry a scale "
        "word, so new rows keep theirs until --restate-base-units restates "
        "them\n"
    )
    restated = sample + [json.loads(line) for line in _writer()]
    assert resolve_pending.print_ledger_units_mode(restated) is True
    assert capsys.readouterr().out == (
        "ledger units: base; no current row carries a scale word\n"
    )


# The current view the writer switch and the planner read.


def test_the_current_view_is_receipts_on_every_ledger_receipt_reads() -> None:
    fixture = json.loads(RECEIPT_FIXTURE.read_text())
    compared = 0
    for ledger in fixture["ledgers"]:
        rows = [
            json.loads(fixture["lines"][index]["line"]) for index in ledger["lines"]
        ]
        try:
            expected = receipt_append_gate.effective_current_rows(rows, SPEC)
        except Exception:  # receipt refuses a malformed ledger outright
            continue
        mine = resolve_pending.current_ledger_rows(rows)
        assert [id(row) for row in mine] == [id(row) for row in expected]
        compared += 1
    assert compared > 100
    ids = 0
    for line in fixture["lines"]:
        row = json.loads(line["line"])
        try:
            expected_id = receipt_append_gate._effective_assertion_id(row, SPEC)
        except Exception:
            continue
        assert resolve_pending.effective_assertion_id(row) == expected_id
        ids += 1
    assert ids > 300


@settings(max_examples=200, deadline=None)
@given(st.data())
def test_the_current_view_is_receipts_on_real_rows_with_any_links(data) -> None:
    pool = [json.loads(line) for line in _sample()]
    ledger: list[dict] = []
    for index in data.draw(
        st.lists(st.integers(0, len(pool) - 1), min_size=1, max_size=8)
    ):
        row = copy.deepcopy(pool[index])
        if data.draw(st.booleans()):
            names = [resolve_pending.effective_assertion_id(other) for other in ledger]
            row["assertionVersion"] = {
                "id": data.draw(
                    st.sampled_from(
                        [
                            None,
                            f"v{len(ledger)}",
                            resolve_pending.assertion_version(row)["id"],
                        ]
                    )
                ),
                "supersedes": data.draw(
                    st.sampled_from([None, "", "av2:" + "0" * 64, *names])
                ),
            }
        ledger.append(row)
    expected = receipt_append_gate.effective_current_rows(ledger, SPEC)
    mine = resolve_pending.current_ledger_rows(ledger)
    assert [id(row) for row in mine] == [id(row) for row in expected]


# What a restatement run writes.


def test_the_writers_restatements_pass_the_site_port_and_the_gate() -> None:
    sample = _sample()
    built = resolve_pending.restatement_rows(
        sample, retrieved_at=RETRIEVED_AT, ledger_repo_sha="f" * 40
    )
    lines = sample + [resolve_pending.ledger_line(row) for row, _ in built]
    restatements = resolve_pending.check_restatements(lines)
    assert len(restatements) == len(built) == len(_scaled_lines(sample)) == 19
    receipt_append_gate.check_rows(lines, len(sample), SPEC)
    receipt_append_gate.check_binding_shapes(lines, len(sample))
    # Nothing is left to restate.
    assert not resolve_pending.scaled_current_rows([json.loads(line) for line in lines])
    assert (
        resolve_pending.restatement_rows(
            lines, retrieved_at=RETRIEVED_AT, ledger_repo_sha="f" * 40
        )
        == []
    )
    scaled = _scaled_lines(sample)
    for (row, compressed), prior_line in zip(built, scaled):
        archive = row["responseArchive"]
        # Each archive holds the exact line it restates, gzipped with mtime 0.
        assert gzip.decompress(compressed) == prior_line.encode()
        assert compressed == gzip.compress(prior_line.encode(), mtime=0)
        assert archive["sha256"] == hashlib.sha256(prior_line.encode()).hexdigest()
        assert archive["gzipSha256"] == hashlib.sha256(compressed).hexdigest()
        prior = json.loads(prior_line)
        assert row["assertionVersion"] == {
            "id": resolve_pending.assertion_version(row)["id"],
            "supersedes": resolve_pending.effective_assertion_id(prior),
            "relation": "unit_restatement",
        }
        # The pair is the row's own value and unit, and the stored value is
        # its digits moved: checked here without ledger_units.
        recorded, unit = row["source"]["recorded_value"], row["source"]["recorded_unit"]
        assert recorded == prior["value"] and type(recorded) is type(prior["value"])
        assert unit == prior["measure"]["unit"]
        assert _stores(row["value"], _moved(recorded, unit))
        assert row["source"]["method_notes"].endswith(
            f"Restates {recorded!r} {unit} (assertion "
            f"{resolve_pending.effective_assertion_id(prior)}) in base units, at "
            "that figure's precision, so the source may print more digits; the "
            "quantity does not change. The row's other notes predate this "
            f"restatement and may give figures in {unit}."
        )
        assert row["retrievedAt"] == RETRIEVED_AT
        assert row["sourceVintage"] == str(
            prior.get("sourceVintage") or prior["observed_at"]
        )
    # Values that keep cents stay floats; whole ones print with no ".0".
    values = [row["value"] for row, _ in built]
    assert any(type(value) is float for value in values)
    assert sum(type(value) is int for value in values) > 15


def test_a_restatement_refuses_a_row_with_no_scale() -> None:
    line = next(
        line for line in _sample() if json.loads(line)["measure"]["unit"] == "percent"
    )
    with pytest.raises(ledger_units.LedgerUnitError, match="holds no scale"):
        resolve_pending.restatement_row(
            json.loads(line),
            line,
            run_dir=resolve_pending.resolution_run_dir(RETRIEVED_AT),
            retrieved_at=RETRIEVED_AT,
            ledger_repo_sha="f" * 40,
        )


@pytest.mark.parametrize(
    ("notes", "expected"),
    [
        (
            "Advance seasonally adjusted initial claims, expressed in thousands.",
            "Advance seasonally adjusted initial claims.",
        ),
        (
            "Total business inventories, end-of-month level, billions of dollars.",
            "Total business inventories, end-of-month level.",
        ),
        (
            "Public sector net borrowing, expressed in GBP billions.",
            "Public sector net borrowing.",
        ),
        (
            "Level, expressed in millions; seasonally adjusted.",
            "Level; seasonally adjusted.",
        ),
        ("Level", "Level."),
        (None, ""),
        ("", ""),
    ],
)
def test_restated_notes_drop_the_scale_they_named(notes: object, expected: str) -> None:
    sentence = (
        "Restates 226 thousands (assertion v1) in base units, at that figure's "
        "precision, so the source may print more digits; the quantity does not "
        "change. The row's other notes predate this restatement and may give "
        "figures in thousands."
    )
    assert resolve_pending.restated_method_notes(notes, 226, "thousands", "v1") == (
        f"{expected} {sentence}".strip()
    )


def test_restated_notes_refuse_a_scale_they_cannot_drop() -> None:
    with pytest.raises(ledger_units.LedgerUnitError, match="still name a scale"):
        resolve_pending.restated_method_notes(
            "Persons, in thousands.", 226, "thousands", "v1"
        )


# The restatement run end to end.

ARGS = {
    "ledger_repo": "PolicyEngine/chronicle",
    "ledger_branch": "codex/thesis-ledger-facts",
    "ledger_path": "ledger/official_observations.jsonl",
}


class Proposals:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs) -> str:
        self.calls.append((args, kwargs))
        return "e" * 40


def _restate(
    root: pathlib.Path,
    monkeypatch,
    content: str,
    *,
    dry_run: bool = False,
    failure: str | None = None,
) -> tuple[int, Proposals]:
    monkeypatch.setattr(resolve_pending, "ROOT", root)
    monkeypatch.setattr(
        resolve_pending, "ledger_state", lambda *_: (content, "c" * 40, SAMPLE_SHA)
    )
    monkeypatch.setattr(resolve_pending, "utc_now", lambda: RETRIEVED_AT)
    monkeypatch.setattr(
        resolve_pending, "restatement_catalog_failure", lambda *_: failure
    )
    monkeypatch.setattr(resolve_pending, "registration_contracts", lambda *_: {})
    monkeypatch.setattr(resolve_pending, "_workflow_run_url", lambda *_: None)
    proposals = Proposals()
    monkeypatch.setattr(resolve_pending, "propose_ledger_append", proposals)
    code = resolve_pending.restate_base_units(
        argparse.Namespace(**ARGS, dry_run=dry_run),
        producer_signing_key=None,
        gate_timeout_seconds=1.0,
    )
    return code, proposals


def _files(directory: pathlib.Path, root: pathlib.Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_a_restatement_run_appends_every_scaled_row_in_one_release(
    tmp_path: pathlib.Path, monkeypatch, capsys
) -> None:
    sample, writer = _sample(), _writer()
    content = "\n".join(sample) + "\n"
    code, proposals = _restate(tmp_path, monkeypatch, content)
    assert code == 0
    ((args, kwargs),) = proposals.calls
    assert args[:3] == tuple(ARGS.values())
    assert args[3] == content + "\n".join(writer) + "\n"
    assert args[4:7] == ("c" * 40, SAMPLE_SHA, 19)
    assert kwargs["arch_checks_policy"] == resolve_pending.ARCH_CHECKS_POLICY_REFUSE
    assert kwargs["what"] == "base-unit restatement(s)"
    out = capsys.readouterr().out
    assert (
        "restate: 19 current row(s) carry a scale word (1 billions USD -> usd, " in out
    )
    assert (
        "appended 19 observation(s) to PolicyEngine/chronicle@"
        "codex/thesis-ledger-facts:ledger/official_observations.jsonl via "
        f"reviewed proposal (merged at {'e' * 40})"
    ) in out
    run_dir = resolve_pending.resolution_run_dir(RETRIEVED_AT)
    verify_run(run_dir)
    responses = sorted((run_dir / "responses").iterdir())
    assert sorted(
        gzip.decompress(path.read_bytes()).decode() for path in responses
    ) == (sorted(_scaled_lines(sample)))
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["firstPrintEvidenceRequired"] is False
    assert [fact["supersedes"] for fact in manifest["facts"]] == [
        json.loads(line)["assertionVersion"]["supersedes"] for line in writer
    ]


def test_a_catalog_refusal_restates_nothing(
    tmp_path: pathlib.Path, monkeypatch, capsys
) -> None:
    content = "\n".join(_sample()) + "\n"
    code, proposals = _restate(
        tmp_path, monkeypatch, content, failure="unit conflict within identity"
    )
    assert code == 1
    assert proposals.calls == []
    assert (
        "RESTATEMENT REFUSED (nothing appended): unit conflict within identity"
        in capsys.readouterr().out
    )
    assert not (tmp_path / "records").exists()


def test_a_dry_run_prints_the_rows_and_writes_nothing(
    tmp_path: pathlib.Path, monkeypatch, capsys
) -> None:
    code, proposals = _restate(
        tmp_path, monkeypatch, "\n".join(_sample()) + "\n", dry_run=True
    )
    out = capsys.readouterr().out
    assert code == 0 and proposals.calls == []
    assert "dry-run: would restate 19 row(s)" in out
    candidates = [
        line.removeprefix("candidate ")
        for line in out.splitlines()
        if line.startswith("candidate ")
    ]
    assert candidates == _writer()
    assert not (tmp_path / "records").exists()


def test_a_ledger_the_port_refuses_stops_the_run_before_it_writes(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    writer = _writer()
    row = json.loads(writer[0])
    row["value"] += 1
    content = "\n".join([*_sample(), resolve_pending.ledger_line(row)]) + "\n"
    with pytest.raises(ledger_units.LedgerUnitError, match="restatement of"):
        _restate(tmp_path, monkeypatch, content)
    assert not (tmp_path / "records").exists()


def test_a_candidate_the_port_refuses_stops_the_run_before_it_writes(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    built_by = resolve_pending.restatement_rows

    def tampered(lines: list[str], **kwargs: object) -> list[tuple[dict, bytes]]:
        (row, compressed), *others = built_by(lines, **kwargs)
        return [({**row, "value": row["value"] + 1}, compressed), *others]

    monkeypatch.setattr(resolve_pending, "restatement_rows", tampered)
    with pytest.raises(ledger_units.LedgerUnitError):
        _restate(tmp_path, monkeypatch, "\n".join(_sample()) + "\n")
    assert not list(tmp_path.iterdir())


def test_a_run_that_would_leave_a_scaled_row_stops_before_it_writes(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    built_by = resolve_pending.restatement_rows
    monkeypatch.setattr(
        resolve_pending,
        "restatement_rows",
        lambda lines, **kwargs: built_by(lines, **kwargs)[1:],
    )
    with pytest.raises(ledger_units.LedgerUnitError, match="would leave 1 current row"):
        _restate(tmp_path, monkeypatch, "\n".join(_sample()) + "\n")
    assert not list(tmp_path.iterdir())


def test_a_line_with_surrounding_whitespace_is_refused(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    sample = _sample()
    content = "\n".join([sample[0] + " ", *sample[1:]]) + "\n"
    with pytest.raises(ledger_units.LedgerUnitError, match="surrounding whitespace"):
        _restate(tmp_path, monkeypatch, content)


def test_a_run_that_never_reached_thesis_is_rebuilt_to_the_byte(
    tmp_path: pathlib.Path, monkeypatch, capsys
) -> None:
    sample, writer = _sample(), _writer()
    first = tmp_path / "first"
    assert _restate(first, monkeypatch, "\n".join(sample) + "\n")[0] == 0
    written = _files(resolve_pending.resolution_run_dir(RETRIEVED_AT), first)
    capsys.readouterr()

    # Chronicle holds the rows; this checkout holds none of their records.
    second = tmp_path / "second"
    restated = "\n".join(sample + writer) + "\n"
    code, proposals = _restate(second, monkeypatch, restated)
    out = capsys.readouterr().out
    assert code == 0 and proposals.calls == []
    run_dir = resolve_pending.resolution_run_dir(RETRIEVED_AT)
    assert (
        f"restored {run_dir.relative_to(second).as_posix()}, the records of a "
        "restatement run that never reached Thesis"
    ) in out
    assert "restate: no current row carries a scale word; nothing to restate" in out
    assert _files(run_dir, second) == written
    verify_run(run_dir)

    # With the records in place there is nothing to rebuild or restate.
    code, proposals = _restate(second, monkeypatch, restated)
    out = capsys.readouterr().out
    assert code == 0 and proposals.calls == []
    assert "restored" not in out
    assert "nothing to restate" in out


def test_a_dry_run_names_the_run_it_would_rebuild(
    tmp_path: pathlib.Path, monkeypatch, capsys
) -> None:
    restated = "\n".join(_sample() + _writer()) + "\n"
    code, _ = _restate(tmp_path, monkeypatch, restated, dry_run=True)
    assert code == 0
    out = capsys.readouterr().out
    assert "dry-run: would restore records/resolutions/2026-11-04/" in out
    assert not out.startswith("restored") and "\nrestored" not in out
    assert not (tmp_path / "records").exists()


def _restore(root: pathlib.Path, monkeypatch, lines: list[str]) -> list[pathlib.Path]:
    monkeypatch.setattr(resolve_pending, "ROOT", root)
    return resolve_pending.restore_restatement_runs(
        lines, ledger_repo=ARGS["ledger_repo"], ledger_branch=ARGS["ledger_branch"]
    )


def test_restore_refuses_a_run_directory_in_part(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    sample, writer = _sample(), _writer()
    assert _restate(tmp_path, monkeypatch, "\n".join(sample) + "\n")[0] == 0
    run_dir = resolve_pending.resolution_run_dir(RETRIEVED_AT)
    next((run_dir / "responses").iterdir()).unlink()
    with pytest.raises(ledger_units.LedgerUnitError, match="in part"):
        _restore(tmp_path, monkeypatch, sample + writer)


def test_restore_refuses_an_archive_its_row_does_not_name(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    sample, writer = _sample(), _writer()
    row = json.loads(writer[0])
    row["responseArchive"]["gzipBytes"] += 1
    lines = sample + [resolve_pending.ledger_line(row), *writer[1:]]
    with pytest.raises(ledger_units.LedgerUnitError, match="the rebuilt archive of"):
        _restore(tmp_path, monkeypatch, lines)
    # A failed rebuild leaves no run behind.
    assert not resolve_pending.resolution_run_dir(RETRIEVED_AT).exists()


def test_restore_refuses_an_archive_outside_its_run(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    sample, writer = _sample(), _writer()
    row = json.loads(writer[0])
    row["responseArchive"]["path"] = "records/resolutions/elsewhere/responses/x.json.gz"
    lines = sample + [resolve_pending.ledger_line(row), *writer[1:]]
    with pytest.raises(ledger_units.LedgerUnitError, match="outside its run"):
        _restore(tmp_path, monkeypatch, lines)


# The catalog preflight.

CATALOG = {
    "observations_sha256": "0" * 64,
    "observation_rows": 1,
    "uuid_registry_sha256": "1" * 64,
    "series": [{"uuid": "u1", "concept": "test.series", "unit": "thousands"}],
}
BASE_FILES = {
    "ledger/series_catalog.json": json.dumps(CATALOG).encode(),
    "ledger/series_uuid_registry.jsonl": b'{"uuid":"u1"}\n',
    "ledger/official_observations.jsonl": b"{}\n",
}
# A stand-in for Chronicle's generator: rewrites the catalog with every
# series in UNIT.
WRITES_CATALOG = """
catalog = json.loads(pathlib.Path("ledger/series_catalog.json").read_text())
ledger = pathlib.Path("ledger/official_observations.jsonl").read_text()
catalog["observation_rows"] = len(ledger.splitlines())
catalog["observations_sha256"] = "2" * 64
for series in catalog["series"]:
    series["unit"] = UNIT
pathlib.Path("ledger/series_catalog.json").write_text(json.dumps(catalog))
"""


def _preflight(monkeypatch, files: dict[str, bytes]) -> str | None:
    tree = resolve_pending.RepositoryTree(
        tree_sha="0" * 40,
        files=files,
        modes={path: "100644" for path in files},
        blob_shas={},
    )
    monkeypatch.setattr(resolve_pending, "_fetch_repository_tree", lambda *_: tree)
    return resolve_pending.restatement_catalog_failure(
        ARGS["ledger_repo"], "a" * 40, ARGS["ledger_path"], "{}\n", [{"value": 1}]
    )


@pytest.mark.parametrize(
    ("generator", "failure"),
    [
        ('UNIT = "count"' + WRITES_CATALOG, None),
        (None, "holds no series-catalog generator"),
        (
            'UNIT = "usd"' + WRITES_CATALOG,
            "restating would change unit of series u1 (test.series): "
            "'thousands' -> 'usd'",
        ),
        (
            'print("unit conflict within identity", file=sys.stderr)\n'
            "raise SystemExit(3)\n",
            "series-catalog generator exit 3: unit conflict within identity",
        ),
        (
            'pathlib.Path("ledger/series_uuid_registry.jsonl").write_text("{}\\n")\n'
            'UNIT = "count"' + WRITES_CATALOG,
            "restating would move the series UUID registry",
        ),
    ],
)
def test_the_catalog_preflight_admits_unit_moves_alone(
    monkeypatch, generator: str | None, failure: str | None
) -> None:
    files = dict(BASE_FILES)
    if generator is not None:
        files["scripts/build_series_catalog.py"] = (
            "import json, pathlib, sys\n" + generator
        ).encode()
    result = _preflight(monkeypatch, files)
    if failure is None:
        assert result is None
    else:
        assert result is not None and failure in result


def test_the_catalog_preflight_needs_a_catalog_and_registry(monkeypatch) -> None:
    for missing in ("ledger/series_catalog.json", "ledger/series_uuid_registry.jsonl"):
        files = {path: body for path, body in BASE_FILES.items() if path != missing}
        assert "holds no series catalog or UUID registry" in _preflight(
            monkeypatch, files
        )


def test_catalog_drift_admits_a_unit_moving_to_its_base_unit_alone() -> None:
    before = {
        "observations_sha256": "a",
        "observation_rows": 1,
        "uuid_registry_sha256": "r",
        "series": [
            {"uuid": "u1", "concept": "c", "unit": "thousands"},
            {"uuid": "u2", "concept": "d", "unit": "percent"},
        ],
    }
    after = copy.deepcopy(before)
    after.update({"observations_sha256": "b", "observation_rows": 2})
    after["series"][0]["unit"] = "count"
    assert resolve_pending.restatement_catalog_drift(before, after) is None
    for change, why in (
        (
            lambda catalog: catalog["series"][1].update(unit="count"),
            "unit of series u2",
        ),
        (lambda catalog: catalog["series"][0].update(unit="usd"), "unit of series u1"),
        (
            lambda catalog: catalog["series"][0].update(concept="e"),
            "concept of series u1",
        ),
        (
            lambda catalog: catalog["series"][0].update(first="2026"),
            "first of series u1",
        ),
        (
            lambda catalog: catalog.update(uuid_registry_sha256="s"),
            "uuid_registry_sha256",
        ),
        (lambda catalog: catalog["series"].pop(), "which series the catalog holds"),
    ):
        moved = copy.deepcopy(after)
        change(moved)
        drift = resolve_pending.restatement_catalog_drift(before, moved)
        assert drift is not None and why in drift, why


# Claims corrections after the migration.


def test_a_claims_correction_must_list_the_restatement_not_its_row() -> None:
    sample = json.loads(
        (ROOT / "tests/fixtures/chronicle_rows_8722b2da.json").read_text()
    )
    prior_line = sample["lines"]["244"]
    prior = json.loads(prior_line)
    ref = prior["source_record_id"]
    restatement, _ = resolve_pending.restatement_row(
        prior,
        prior_line,
        run_dir=resolve_pending.resolution_run_dir(RETRIEVED_AT),
        retrieved_at=RETRIEVED_AT,
        ledger_repo_sha="f" * 40,
    )
    rows = [json.loads(sample["lines"]["222"]), prior, restatement]

    class NoAnswer:
        evidence: dict = {}

        def first_print(self, *_args):
            return None

    listed = prior["assertionVersion"]["id"]
    fetched, supersedes, refusals = resolve_pending.claims_corrections(
        rows, NoAnswer(), {ref: listed}
    )
    assert (fetched, supersedes) == ([], {})
    assert refusals == [
        f"{ref} — listed version {listed} was restated in base units by "
        f"{restatement['assertionVersion']['id']}; list that version instead"
    ]
    # Listing the restatement reaches ALFRED, which here does not answer.
    assert resolve_pending.claims_corrections(
        rows, NoAnswer(), {ref: restatement["assertionVersion"]["id"]}
    ) == ([], {}, [])


# The workflow.


def _steps() -> dict[str, dict]:
    parsed = yaml.safe_load(WORKFLOW.read_text())
    return {step.get("name"): step for step in parsed["jobs"]["resolve"]["steps"]}


def test_the_workflow_restates_only_when_dispatched_to() -> None:
    parsed = yaml.safe_load(WORKFLOW.read_text())
    # PyYAML reads the bare key `on` as True.
    trigger = parsed.get("on", parsed.get(True))
    restate = trigger["workflow_dispatch"]["inputs"]["restate_base_units"]
    assert restate["type"] == "boolean" and restate["default"] is False
    assert "schedule" in trigger
    resolve = _steps()["Resolve pending cells against official prints"]
    assert resolve["env"]["RESTATE_BASE_UNITS"] == (
        "${{ inputs.restate_base_units == true }}"
    )
    assert 'python3 -u scripts/resolve_pending.py "${mode[@]}"' in resolve["run"]
    assert 'grep -q "^restored" /tmp/resolve-out.log' in resolve["run"]
    compare = _steps()["Compare ledger branch with the last successful deployment"]
    assert compare["env"]["RESTORED"] == "${{ steps.resolve.outputs.restored }}"
    assert '[ "$RESTORED" = "1" ]' in compare["run"]


@pytest.mark.parametrize(
    ("rendered", "argv"),
    [("true", ["--restate-base-units"]), ("false", []), ("", [])],
)
def test_the_resolve_step_passes_the_flag_only_for_true(
    rendered: str, argv: list[str]
) -> None:
    # GitHub renders the expression as true or false; a scheduled run has no
    # inputs, and null == true is false.
    script = _steps()["Resolve pending cells against official prints"]["run"]
    start = script.index("mode=()")
    end = script.index("fi\n", start) + len("fi\n")
    out = subprocess.run(
        ["bash", "-c", script[start:end] + 'printf "%s\\n" "${mode[@]}"'],
        env={"PATH": os.environ["PATH"], "RESTATE_BASE_UNITS": rendered},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.split() == argv
