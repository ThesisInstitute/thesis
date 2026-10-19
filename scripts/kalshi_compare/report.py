"""CSV tables and a Markdown report from a results dictionary."""

from __future__ import annotations

import csv
import json
import pathlib


def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: json.dumps(v) if isinstance(v, (list, dict)) else v
                    for k, v in row.items()
                }
            )


def write(results: dict, out: pathlib.Path) -> None:
    for name in (
        "inventory",
        "unmatched",
        "withdrawn",
        "outcomes",
        "markets",
        "pairs",
        "exclusions",
    ):
        write_csv(out / f"{name}.csv", results[name])
    scores = [{k: v for k, v in row.items()} for row in results["scores"]]
    write_csv(out / "scores.csv", scores)
    (out / "summary.json").write_text(json.dumps(results["summary"], indent=1) + "\n")
