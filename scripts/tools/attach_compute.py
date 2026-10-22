"""Attach an audited PolicyEngine compute row to a bill.json provision.

The compute block is the #45 leg of the bill.json contract (plan #43): model
runs attached to the provisions they price. Extraction regens (ingest_bill.py)
rewrite bills/<slug>.json WITHOUT compute rows — re-run this after any regen to
re-attach them. Idempotent: matching rows (same model+reform+year+dataset) are
replaced in place, never duplicated.

Usage:
    python scripts/tools/attach_compute.py <slug> [--provision 0] [--row path.json]

Without --row, uses the row registry below (checked in next to the runs that
produced it). Row provenance should come from the audited call path
(scripts/tools/policyengine.py compute_block / modal_economy.py output).

Certification is never typed here: a registry row's `certification` must equal,
key for key, the block pe.compute_block emitted for the grounding run, and its
versions and validation must equal what that run measured in-container. A row
whose certification is not certified may still attach (the page lists it with
its reason and withholds every figure — POLICYENGINE.md §0.2), but a row that
claims `certified: true` without consistent provenance is refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BILLS_DIR = Path(__file__).resolve().parents[2] / "bills"

# Registry of audited compute rows, keyed by (slug, provision index).
# S.3596 row: certified build-P run, Modal, 2026-07-31 — full artifact at
# bills/stronger-start-working-families-act/buildP-economy-2026.json.
ROWS: dict[tuple[str, int], list[dict]] = {
    ("s3596-119", 0): [
        {
            "model": "policyengine-us",
            "reform": {
                "gov.irs.credits.ctc.refundable.phase_in.threshold": {
                    "2026-01-01.2100-12-31": 0
                }
            },
            "result_summary": (
                "Gains concentrate in the lowest income deciles (decile 1 averages "
                "+$32/yr vs +$0.30 for decile 10); Gini falls 0.02%. The annual cost "
                "declines from $1.86B to $1.53B across the window as earnings growth "
                "lifts families past the old $2,500 floor. State income-tax revenue "
                "falls about $0.35M per year — itemized separately and excluded from "
                "the federal figures above."
            ),
            "engine": "modal",
            "pe_us_version": "1.764.6",
            "pe_core_version": "3.26.11",
            "dataset": "populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z",
            "certification": {
                "certified_model_version": "1.764.6",
                "running_model_version": "1.764.6",
                "certified": True,
            },
            "year": 2026,
            "region": "us",
            "status": "ok",
            "budgetary_impact": -1826050568.80,
            "ten_year_budgetary_impact": -17069142980.93,
            "ten_year_window": "2026-2035",
            "poverty_child_pct_change": -0.0115527,
            "beneficiaries_share": 0.0648,
            "note": (
                "Static microsim, one evidence stream with its own error bars. "
                "Anchors: PolicyEngine -$1.6B/yr on an older data build; Tax Policy "
                "Center ~$1.0B/yr."
            ),
            "source": (
                "Audited call path scripts/tools/policyengine.py per POLICYENGINE.md; "
                "run scripts/tools/modal_economy.py 2026-07-31 on the certified stack; "
                "full artifacts bills/stronger-start-working-families-act/"
                "buildP-economy-2026.json and buildP-sweep-2026-2035.json "
                "(sum-checked; PR #64)."
            ),
        }
    ],
}


# Run artifacts that ground the registry rows (land via PR #64). When present,
# attach VERIFIES the registry numbers against them and dies loudly on drift —
# a hand-transcribed number that no longer matches its source run must never
# ship silently (that is how the published -$1.6B went stale).
ARTIFACT_DIR = BILLS_DIR / "stronger-start-working-families-act"
GROUNDING = {
    ("s3596-119", 0): {
        "economy": ARTIFACT_DIR / "buildP-economy-2026.json",
        "sweep": ARTIFACT_DIR / "buildP-sweep-2026-2035.json",
        "compute_row": ARTIFACT_DIR / "compute-row-2026.json",
    },
}


def publishable_compute_row(row: dict) -> bool:
    """POLICYENGINE.md §0.2 gate: may a page publish this row's figures? Python
    mirror of site/src/lib/compute-publishability.ts (isPublishableCompute); both
    are pinned to tests/fixtures/compute_publishability_cases.json. Fail-closed:
    the certification must be certified AND agree with the row it certifies."""
    c = row.get("certification")
    if not isinstance(c, dict) or c.get("certified") is not True:
        return False
    if row.get("status") != "ok":
        return False
    dataset = row.get("dataset")
    if not dataset or c.get("build") != dataset:
        return False
    running = c.get("running_model_version")
    if not running or running != row.get("pe_us_version"):
        return False
    if c.get("certified_model_version") != running:
        return False
    if c.get("validated_against") != f"policyengine-us@{running}":
        return False
    if row.get("param_source") is not None and row.get("param_source") != c.get("validated_against"):
        return False
    if c.get("certified_core_version") is not None:
        if c.get("running_core_version") != c.get("certified_core_version"):
            return False
        if row.get("pe_core_version") != c.get("running_core_version"):
            return False
    return c.get("warning") is None


def _drift(name: str, registry_val, artifact_val) -> None:
    if registry_val != artifact_val:
        raise SystemExit(f"DRIFT in {name}: registry {registry_val!r} != artifact {artifact_val!r} "
                         "— re-transcribe from the run artifact before attaching")


def _verify_against_artifacts(slug: str, provision_index: int, rows: list[dict]) -> None:
    ground = GROUNDING.get((slug, provision_index))
    if not ground:
        return
    row = rows[0]
    checks: list[tuple[str, float, float]] = []
    econ_path, sweep_path, block_path = ground["economy"], ground["sweep"], ground["compute_row"]
    if econ_path.exists():
        econ = json.loads(econ_path.read_text(encoding="utf-8"))
        checks.append(("budgetary_impact", row["budgetary_impact"],
                       econ["budget"]["budgetary_impact"]))
        checks.append(("poverty_child_pct_change", row["poverty_child_pct_change"],
                       econ["poverty"]["child"]["pct_change"]))
        if econ.get("dataset") != row.get("dataset"):
            raise SystemExit(f"DRIFT: dataset {row.get('dataset')} != artifact {econ.get('dataset')}")
        # Provenance is exact, not rounded: what the container measured.
        _drift("pe_us_version", row.get("pe_us_version"), econ.get("pe_us_version"))
        _drift("pe_core_version", row.get("pe_core_version"), econ.get("pe_core_version"))
        _drift("param_source", row.get("param_source"), (econ.get("validation") or {}).get("param_source"))
    if block_path.exists():
        block = json.loads(block_path.read_text(encoding="utf-8"))
        # The certification is the one compute_block emitted for the run.
        _drift("certification", row.get("certification"), block.get("certification"))
        for key in ("dataset", "pe_us_version", "pe_core_version", "param_source", "engine", "reform", "year"):
            _drift(key, row.get(key), block.get(key))
    elif "certification" in row:
        raise SystemExit("certification cannot be verified: compute-row artifact missing")
    if sweep_path.exists():
        sweep = json.loads(sweep_path.read_text(encoding="utf-8"))
        checks.append(("ten_year_budgetary_impact", row["ten_year_budgetary_impact"],
                       sweep["ten_year_budgetary_impact"]))
        for key in ("dataset", "pe_us_version", "pe_core_version"):
            _drift(f"sweep {key}", row.get(key), sweep.get(key))
        # A certified row carries the ten-year figure only if the sweep certified too.
        sweep_cert = sweep.get("certification") or {}
        if publishable_compute_row(row) and sweep_cert.get("certified") is not True:
            raise SystemExit("REFUSED: row is certified but the ten-year sweep is not — "
                             f"{sweep_cert.get('warning') or 'sweep carries no certification'}")
    verified = []
    for name, registry_val, artifact_val in checks:
        tol = max(abs(artifact_val) * 1e-4, 1e-6)  # transcriptions are rounded
        if abs(registry_val - artifact_val) > tol:
            raise SystemExit(f"DRIFT in {name}: registry {registry_val} != artifact {artifact_val} "
                             f"— re-transcribe from the run artifact before attaching")
        verified.append(name)
    if verified:
        print(f"verified against run artifacts: {', '.join(verified)}")
    else:
        print("note: run artifacts not present on this branch — registry values unverified "
              "(they verify automatically once PR #64's artifacts land)")


def _row_key(row: dict) -> tuple:
    return (
        row.get("model"),
        json.dumps(row.get("reform", {}), sort_keys=True),
        row.get("year"),
        row.get("dataset"),
    )


def _check_certification_claims(rows: list[dict]) -> None:
    for row in rows:
        cert = row.get("certification")
        if isinstance(cert, dict) and cert.get("certified") is True and not publishable_compute_row(row):
            raise SystemExit("REFUSED: row claims certified: true but its certification does not "
                             f"match its provenance: {json.dumps(cert, sort_keys=True)}")
        if not publishable_compute_row(row):
            print("note: attaching an UNCERTIFIED row — the page withholds its figures "
                  "(POLICYENGINE.md §0.2)", file=sys.stderr)


def attach(slug: str, provision_index: int, rows: list[dict]) -> Path:
    _check_certification_claims(rows)
    _verify_against_artifacts(slug, provision_index, rows)
    path = BILLS_DIR / f"{slug}.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    provisions = artifact["provisions"]
    if provision_index >= len(provisions):
        raise SystemExit(f"{slug}: provision {provision_index} out of range ({len(provisions)})")
    existing = provisions[provision_index].get("compute") or []
    keep = [r for r in existing if _row_key(r) not in {_row_key(n) for n in rows}]
    provisions[provision_index]["compute"] = keep + rows
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Attach audited compute rows to bill.json")
    ap.add_argument("slug")
    ap.add_argument("--provision", type=int, default=0)
    ap.add_argument("--row", help="path to a JSON file holding one compute row (or a list)")
    args = ap.parse_args(argv)

    if args.row:
        loaded = json.loads(Path(args.row).read_text(encoding="utf-8"))
        rows = loaded if isinstance(loaded, list) else [loaded]
    else:
        rows = ROWS.get((args.slug, args.provision))
        if not rows:
            print(f"no registered rows for ({args.slug}, {args.provision}); pass --row", file=sys.stderr)
            return 1
    path = attach(args.slug, args.provision, rows)
    print(f"attached {len(rows)} compute row(s) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
