"""Fetch first-print ground truth for the bill-impact backtest from ALFRED.

House rule (AGENTS.md): FRED/ALFRED is a *history mirror*, never the final
resolution source when an official agency source exists. Here it is used only
as a vintage archive to recover the value **as first published**, which the
originating agency (USDA FNS via Census) does not itself archive. Every value
carries the vintage date it was read at, so any reader can reproduce it.

First-print discovery is empirical: we walk vintage dates forward from the
observation month and take the earliest vintage at which the observation is
present and non-missing. We never assume a publication lag.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ALFRED_CSV = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
USER_AGENT = "thesis-billimpact/0.1 (+https://github.com/PolicyEngine)"


def _fetch(url: str, timeout: float = 45.0, retries: int = 4) -> str:
    last = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed after {retries}: {url} :: {last}")


def series_at_vintage(series_id: str, vintage: str) -> dict[str, float]:
    """Return {observation_date: value} for a series as published at `vintage`."""
    url = f"{ALFRED_CSV}?" + urllib.parse.urlencode(
        {"id": series_id, "vintage_date": vintage}
    )
    text = _fetch(url)
    out: dict[str, float] = {}
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2:
        return out
    for row in reader:
        if len(row) < 2:
            continue
        raw = row[1].strip()
        if raw in {"", ".", "NA"}:
            continue
        try:
            out[row[0].strip()] = float(raw)
        except ValueError:
            continue
    return out


def month_add(iso_month: str, months: int) -> str:
    y, m, _ = (int(p) for p in iso_month.split("-"))
    total = (y * 12 + (m - 1)) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}-01"


def discover_first_print(
    series_id: str,
    observation_month: str,
    max_lag_months: int = 40,
) -> dict:
    """Walk vintages forward; return the earliest vintage carrying the value.

    Returns a dict with `first_print_value`, `first_print_vintage`, and the
    `latest_value` at today's vintage so revision size is visible.
    """
    trail: list[dict] = []
    first_value = None
    first_vintage = None
    for lag in range(1, max_lag_months + 1):
        vintage = month_add(observation_month, lag)
        # ALFRED vintage dates must be real published vintages; the graph
        # endpoint snaps to the latest vintage <= the requested date, so a
        # mid-month probe is safe.
        try:
            obs = series_at_vintage(series_id, vintage)
        except urllib.error.HTTPError:
            return {"series_id": series_id, "error": "series_not_found"}
        value = obs.get(observation_month)
        trail.append({"vintage": vintage, "present": value is not None, "value": value})
        if value is not None:
            first_value = value
            first_vintage = vintage
            break

    latest = series_at_vintage(series_id, date.today().isoformat()).get(observation_month)
    return {
        "series_id": series_id,
        "observation_month": observation_month,
        "first_print_value": first_value,
        "first_print_vintage": first_vintage,
        "latest_value": latest,
        "revision": None if (first_value is None or latest is None) else round(latest - first_value, 6),
        "vintage_trail": trail,
        "source": "ALFRED vintage archive (history mirror of Census/USDA-FNS SNAP series)",
        "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def history_at_origin(series_id: str, origin_vintage: str, months_back: int, through: str) -> list[dict]:
    """Series history as it stood at the forecast origin — no lookahead.

    `through` is the last observation month the forecaster may see.
    """
    obs = series_at_vintage(series_id, origin_vintage)
    keys = sorted(k for k in obs if k <= through)
    keys = keys[-months_back:]
    return [{"month": k, "value": obs[k]} for k in keys]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=Path, required=True, help="JSON list of units")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    units = json.loads(args.spec.read_text())

    def work(unit: dict) -> dict:
        sid = unit["series_id"]
        target = unit["target_month"]
        rec = dict(unit)
        try:
            rec["truth"] = discover_first_print(sid, target)
        except Exception as e:  # noqa: BLE001
            rec["truth"] = {"series_id": sid, "error": f"{type(e).__name__}: {e}"}
        try:
            rec["history"] = history_at_origin(
                sid,
                unit["origin_vintage"],
                unit.get("months_back", 36),
                unit["history_through"],
            )
        except Exception as e:  # noqa: BLE001
            rec["history"] = []
            rec["history_error"] = f"{type(e).__name__}: {e}"
        return rec

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(work, units))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2))
    ok = sum(1 for r in results if r.get("truth", {}).get("first_print_value") is not None)
    print(f"units={len(results)} with_first_print={ok}")
    for r in results:
        t = r.get("truth", {})
        print(
            f"  {r['unit_id']:26s} {t.get('first_print_value')!s:>12s} "
            f"@{t.get('first_print_vintage')} latest={t.get('latest_value')} "
            f"hist={len(r.get('history', []))} {t.get('error','')}"
        )


if __name__ == "__main__":
    main()
