"""Apply each mutant to a scratch copy of the thesis tree and run the label tests.

A mutant is killed only when pytest exits 1 (tests ran and failed). Exit 2
(collection or import error) or anything else is reported as not killed by an
assertion. Run it in a copy, never in the working tree: it edits files in
place and restores each one after its run.

usage: python3 run_mutants.py <tree> <out.json> [pytest args...]
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

tree = pathlib.Path(sys.argv[1]).resolve()
out_path = pathlib.Path(sys.argv[2])
pytest_cmd = sys.argv[3:] or [
    sys.executable,
    "-m",
    "pytest",
    "-q",
    "-x",
    "-p",
    "no:cacheprovider",
    "tests/test_alfred_vintage_labels.py",
    "tests/test_claims_first_vintage.py",
]

RP = "scripts/resolve_pending.py"
AV = "scripts/alfred_vintage.py"
VC = "scripts/verify_custody.py"
MUTANTS = [
    # The generic leg's read (resolve_pending).
    (
        "lag check >= becomes >",
        RP,
        "if label >= day - dt.timedelta(days=ALFRED_VINTAGE_LABEL_LAG):",
        "if label > day - dt.timedelta(days=ALFRED_VINTAGE_LABEL_LAG):",
    ),
    (
        "accept any label <= day",
        RP,
        "if label >= day - dt.timedelta(days=ALFRED_VINTAGE_LABEL_LAG):",
        "if True:",
    ),
    (
        "no reordered retry",
        RP,
        "spellings: tuple[str, ...] = (FRED_CSV, ALFRED_VINTAGE_CSV_REORDERED),",
        "spellings: tuple[str, ...] = (FRED_CSV,),",
    ),
    (
        "retry after a later label",
        RP,
        "            return AlfredVintageRead(\n"
        "                {}, raw, url, retrieved_at, (ALFRED_READ_FAILED, str(exc))\n"
        "            )",
        "            continue",
    ),
    (
        "no future-day guard",
        RP,
        "    if day > today:\n        return AlfredVintageRead(",
        "    if False:\n        return AlfredVintageRead(",
    ),
    # The shared reader (alfred_vintage).
    (
        "alfred_today on UTC",
        AV,
        "ST_LOUIS_STANDARD_TIME = dt.timezone(dt.timedelta(hours=-6))",
        "ST_LOUIS_STANDARD_TIME = dt.timezone.utc",
    ),
    (
        "alfred_today on a naive clock",
        AV,
        "    current = now or dt.datetime.now(dt.timezone.utc)",
        "    current = now or dt.datetime.now()",
    ),
    (
        "header regex accepts any series",
        AV,
        'rf"observation_date,{re.escape(series_id)}_([0-9]{{8}})", header',
        'r"observation_date,[A-Za-z0-9]+_([0-9]{8})", header',
    ),
    (
        "header label takes any script's digits",
        AV,
        'rf"observation_date,{re.escape(series_id)}_([0-9]{{8}})", header',
        'rf"observation_date,{re.escape(series_id)}_(\\d{{8}})", header',
    ),
    (
        "values take any script's digits",
        AV,
        '_VALUE = re.compile(r"-?[0-9]+(?:\\.[0-9]+)?")',
        '_VALUE = re.compile(r"-?\\d+(?:\\.\\d+)?")',
    ),
    (
        "header strips one CR",
        AV,
        'header = first.decode("utf-8").rstrip("\\r")',
        'header = first.decode("utf-8").removesuffix("\\r")',
    ),
    (
        "no later-label refusal",
        AV,
        "    if label > day:\n        raise AlfredVintageError(",
        "    if False:\n        raise AlfredVintageError(",
    ),
    (
        "rows may repeat or go back",
        AV,
        "or observation <= previous",
        "or observation < previous",
    ),
    (
        "order not kept across a missing mark",
        AV,
        "        previous = observation\n        if value in _MISSING:\n"
        "            continue\n",
        "        if value in _MISSING:\n            continue\n"
        "        previous = observation\n",
    ),
    # Custody (verify_custody).
    (
        "custody check skipped",
        VC,
        '    judged = 0\n    for fact in manifest["facts"]:',
        '    return 0\n    judged = 0\n    for fact in manifest["facts"]:',
    ),
    (
        "verify_run skips the label check",
        VC,
        "            _verify_resolver_v2(run_dir, manifest, normalized_entries)\n"
        "            _verify_resolver_alfred_labels(run_dir, manifest)\n",
        "            _verify_resolver_v2(run_dir, manifest, normalized_entries)\n",
    ),
    (
        "custody accepts an earlier label",
        VC,
        "        if label < vintage - timedelta(days=days):",
        "        if label > vintage:",
    ),
    (
        "custody ignores the archive's name",
        VC,
        '        if not name.startswith(f"{series.lower()}-{vintage.isoformat()}-"):',
        "        if False:",
    ),
    (
        "custody ignores the archive's day",
        VC,
        '        if not name.startswith(f"{series.lower()}-{vintage.isoformat()}-"):',
        '        if not name.startswith(f"{series.lower()}-"):',
    ),
    (
        "custody header without digits",
        VC,
        'rb"observation_date,([A-Za-z0-9._-]+)_[0-9]{8}"',
        'rb"observation_date,([A-Za-z]+)_[0-9]{8}"',
    ),
    (
        "custody header keeps a CR",
        VC,
        '        header = raw.split(b"\\n", 1)[0].rstrip(b"\\r")',
        '        header = raw.split(b"\\n", 1)[0]',
    ),
    (
        "custody skips a fact with no sourceVintage",
        VC,
        "        except ValueError as exc:\n            raise CustodyError(\n"
        '                f"resolver fact {record} has no sourceVintage date',
        "        except ValueError:\n            continue\n            raise CustodyError(\n"
        '                f"resolver fact {record} has no sourceVintage date',
    ),
    (
        "custody gives claims facts the day-after lag",
        VC,
        'CLAIMS_LABEL_LAG["release_day"][0]\n            if CLAIMS_RECORD_RE',
        'CLAIMS_LABEL_LAG["vintage_after_release"][0]\n            if CLAIMS_RECORD_RE',
    ),
]

results = []
for name, path, old, new in MUTANTS:
    target = tree / path
    original = target.read_text()
    if original.count(old) != 1:
        results.append({"mutant": name, "applied": False})
        print(f"NOT APPLIED  {name}", flush=True)
        continue
    target.write_text(original.replace(old, new))
    try:
        run = subprocess.run(pytest_cmd, cwd=tree, capture_output=True, text=True)
    finally:
        target.write_text(original)
    tail = (run.stdout + run.stderr).strip().splitlines()[-6:]
    killed = run.returncode == 1
    results.append(
        {"mutant": name, "applied": True, "rc": run.returncode, "killed": killed,
         "tail": tail}
    )
    print(f"{'KILLED' if killed else 'SURVIVED'} rc={run.returncode}  {name}", flush=True)
    for line in tail:
        print("    " + line, flush=True)
baseline = subprocess.run(pytest_cmd, cwd=tree, capture_output=True, text=True)
summary = {
    "baselineRc": baseline.returncode,
    "baselineTail": (baseline.stdout + baseline.stderr).strip().splitlines()[-3:],
    "mutants": results,
    "allKilled": all(r.get("killed") for r in results),
}
out_path.write_text(json.dumps(summary, indent=1) + "\n")
print(json.dumps({k: summary[k] for k in ("baselineRc", "baselineTail", "allKilled")}))
sys.exit(0 if summary["allKilled"] and baseline.returncode == 0 else 1)
