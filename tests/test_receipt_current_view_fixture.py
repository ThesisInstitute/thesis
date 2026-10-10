"""The site's current-view port is held to receipt through a committed fixture.

site/src/__tests__/ledger-current-view.test.ts replays
site/src/__tests__/fixtures/receipt-current-view.json against the TypeScript
port. These tests keep that fixture honest: it must be exactly what the
installed receipt produces today, over rows whose content keys are the ones
the resolver writes assertion versions with.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

receipt_append_gate = pytest.importorskip("receipt.append_gate")

import generate_receipt_current_view_fixture as fixture_gen  # noqa: E402
import resolve_pending  # noqa: E402


def test_committed_fixture_is_what_receipt_produces() -> None:
    committed = fixture_gen.FIXTURE.read_text()
    assert committed == fixture_gen.render(fixture_gen.build_fixture()), (
        "site/src/__tests__/fixtures/receipt-current-view.json is stale; run "
        "uv run --extra custody python "
        "scripts/generate_receipt_current_view_fixture.py"
    )


def test_content_keys_match_the_resolver_writer() -> None:
    assert (
        fixture_gen.CHRONICLE_ASSERTION_CONTENT_KEYS
        == resolve_pending.ASSERTION_CONTENT_KEYS
    )


def test_writer_projection_matches_receipt_on_every_fixture_row() -> None:
    # The resolver mints ids with its own projection; receipt recomputes them
    # at the gate. Both must address every row identically.
    fixture = json.loads(fixture_gen.FIXTURE.read_text())
    compared = 0
    for line in fixture["lines"]:
        if line["contentAddress"] is None:
            continue
        row = json.loads(line["line"])
        assert resolve_pending.assertion_version(row)["id"] == line["contentAddress"]
        compared += 1
    assert compared > 300


def test_real_chronicle_rows_carry_receipt_ids() -> None:
    sample = json.loads(fixture_gen.CHRONICLE_ROWS.read_text())
    assert sample["sha"] == "598f394d797728f298cdd405099419a00ce94e18"
    versioned = 0
    for line in sample["lines"].values():
        row = json.loads(line)
        version = row.get("assertionVersion")
        if version:
            assert version["id"] == receipt_append_gate.expected_assertion_version_id(
                row, fixture_gen.SPEC
            )
            versioned += 1
    assert 0 < versioned < len(sample["lines"])


def test_every_gated_ledger_passes_the_gate() -> None:
    fixture = json.loads(fixture_gen.FIXTURE.read_text())
    gated = [ledger for ledger in fixture["ledgers"] if ledger["kind"] != "arbitrary"]
    assert len(gated) == 61
    for ledger in gated:
        lines = [fixture["lines"][index]["line"] for index in ledger["lines"]]
        receipt_append_gate.check_rows(lines, len(lines), fixture_gen.SPEC)
        assert ledger["checkRows"] == "accept"
