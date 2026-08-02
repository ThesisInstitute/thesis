"""Offline reparse + quarantine for the knowledge probe.

Root cause (found 2026-07-31, post-run): harness._last_json_object requires
"point" in the object — it is a forecast extractor, not a generic one — so
probe responses keyed "value"/"basis" never parsed through it; the regex
fallback recovered `value` only, and `basis` was lost everywhere. Separately,
opus at max_tokens=400 returned EMPTY content on 98 calls (cap swallowed by
deliberation, worst on the longer anchored prompts).

This script: (1) reparses every stored text with a generic balanced-object
scanner, recovering recall+basis; (2) quarantines rows with empty/unparseable
text to runs_probe.quarantined.jsonl (never deleted) so the fixed runner can
re-execute those cells at a workable token cap.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent


def generic_last_json(text: str):
    """Last balanced top-level JSON object, no key requirement."""
    candidates, depth, start, in_str, esc = [], 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start:i + 1])
    for blob in reversed(candidates):
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def to_float(raw):
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.replace(",", "").replace("$", "").strip())
        except ValueError:
            return None
    return None


def main() -> None:
    src = HERE / "runs_probe.jsonl"
    rows = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
    keep, quarantine = [], []
    fixed_basis = refixed_recall = 0
    for r in rows:
        if r.get("error"):
            quarantine.append(r)
            continue
        obj = generic_last_json(r.get("text", "") or "")
        if obj is not None and to_float(obj.get("value")) is not None:
            new_recall = to_float(obj.get("value"))
            if r.get("recall") != new_recall:
                refixed_recall += 1
            r["recall"] = new_recall
            if r.get("basis") != obj.get("basis"):
                fixed_basis += 1
            r["basis"] = obj.get("basis")
            keep.append(r)
        elif r.get("recall") is not None:
            # regex-recovered value with truncated/absent JSON; keep, basis unknown
            keep.append(r)
        else:
            quarantine.append(r)
    (HERE / "runs_probe.quarantined.jsonl").open("a").write(
        "".join(json.dumps(r) + "\n" for r in quarantine))
    src.write_text("".join(json.dumps(r) + "\n" for r in keep))
    print(f"kept={len(keep)} quarantined={len(quarantine)} "
          f"basis_recovered={fixed_basis} recall_changed={refixed_recall}")


if __name__ == "__main__":
    main()
