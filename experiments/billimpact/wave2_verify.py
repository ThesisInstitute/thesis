"""Wave-2 self-check: every legal slice is byte-identical to its normalised
source, every hash matches, and the ground truth obeys no-lookahead. Run after
any regeneration of the wave-2 files. No network.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).parent


def norm(raw: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", raw))


def main() -> None:
    provisions = json.loads((HERE / "provisions_wave2.json").read_text())
    corpus = json.loads((HERE / "corpus_wave2.json").read_text())
    truth = json.loads((HERE / "ground_truth_wave2.json").read_text())
    unscored = json.loads((HERE / "corpus_wave2_unscored.json").read_text())
    failures = []

    # 1. slices verbatim-in-source + hashes
    for ev, entry in provisions.items():
        files = entry.get("bill_text_files", {})
        for key, slice_ in entry["operative"].items():
            src = files.get(key, entry["bill_text_file"])
            n = norm((HERE / src).read_text())
            c = n.count(slice_)
            if c != 1:
                failures.append(f"{ev}/{key}: slice occurs {c}x in {src}")
            h = hashlib.sha256(slice_.encode()).hexdigest()[:12]
            if h != entry["sha256_12"][key]:
                failures.append(f"{ev}/{key}: sha256_12 mismatch ({h} != {entry['sha256_12'][key]})")
        sp = entry.get("stated_purpose")
        if sp is not None:
            n = norm((HERE / entry["bill_text_file"]).read_text())
            if n.count(sp) != 1:
                failures.append(f"{ev}: stated_purpose not found verbatim in {entry['bill_text_file']}")

    # 2. corpus <-> truth consistency, no-lookahead
    tmap = {u["unit_id"]: u for u in truth}
    for c in corpus:
        u = tmap.get(c["unit_id"])
        if u is None:
            failures.append(f"{c['unit_id']}: missing from ground truth")
            continue
        for f in ("policy_event", "series_id", "target_month", "origin_vintage", "history_through"):
            if u.get(f) != c.get(f):
                failures.append(f"{c['unit_id']}: field {f} differs corpus vs truth")
        if c["policy_event"] not in provisions:
            failures.append(f"{c['unit_id']}: policy_event not in provisions_wave2.json")
        t = u.get("truth", {})
        if t.get("first_print_value") is None:
            failures.append(f"{c['unit_id']}: no first print")
        if t.get("first_print_vintage") and t["first_print_vintage"] <= c["origin_vintage"]:
            failures.append(f"{c['unit_id']}: first-print vintage precedes origin (lookahead)")
        hist = u.get("history", [])
        if not hist:
            failures.append(f"{c['unit_id']}: empty history")
        else:
            if max(r["month"] for r in hist) > c["history_through"]:
                failures.append(f"{c['unit_id']}: history extends past history_through (lookahead)")
            if c["target_month"] <= c["history_through"]:
                failures.append(f"{c['unit_id']}: target inside history window")

    # 3. unscored units carry no fabricated resolution
    for u in unscored:
        if u.get("classification") != "dose_response_only":
            failures.append(f"{u['unit_id']}: unscored unit missing classification")
        if u.get("series_id") is not None or "truth" in u:
            failures.append(f"{u['unit_id']}: unscored unit carries a series/truth")

    if failures:
        print(f"FAIL ({len(failures)}):")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    n_slices = sum(len(e["operative"]) for e in provisions.values())
    print(f"OK: {n_slices} slices verbatim+hashed across {len(provisions)} events; "
          f"{len(corpus)} scored units consistent, no lookahead; "
          f"{len(unscored)} unscored unit(s) clean.")


if __name__ == "__main__":
    main()
