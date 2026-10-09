#!/usr/bin/env python3
"""Run the Sol 6.1 shadow horizon waves on spare Codex quota.

Wave 1 is the original three-by-three design (web, net and full arms, three
rollouts each) run on 2026-10-06/07. Waves 2 to 7 repeat it once a day, at
13:00Z from 2026-10-08 to 2026-10-13, on every validatable target whose
release window opens after that day. The same model and prompts at
successive dates measure how one forecaster's accuracy changes as release
day approaches.

Each wave submits rollout 1 of every arm before rollout 2, and rollout 2
before rollout 3, so a quota shortfall trims depth rather than whole arms.
A chunk of at most CHUNK jobs is submitted per check, at most one chunk per
POLL_S, and only while all of these hold (Fleet ops' limits, 2026-10-09):

- this session's unfinished Subfleet jobs plus the chunk stay at or under
  MAX_INFLIGHT;
- free disk has not fallen more than MAX_DISK_DROP_GB since the previous
  check;
- the 5-minute load average is under LOAD_CAP;
- the data volume has at least MIN_FREE_GB free (the d636 floor);
- the mean seven-day utilization of the Codex lanes is under budget(now),
  which rises linearly to BUDGET_CAP by the 2026-10-14 reset. Other work on
  the lanes, Axiom's first, counts against the same budget, so it is served
  first.

The driver picks work by run, not by batch label: a run whose output path
already has a submission receipt is done, so a restart, a cancelled batch
whose receipts were set aside, or a change of chunk size resubmits exactly
the runs still missing. Runs still unsubmitted when the next wave starts are
skipped and logged.
When a wave's jobs finish, the driver collects them, re-dispatches once any
run a network outage stopped, prunes, commits and pushes, so the branch's
push time witnesses every forecast before its target's window opens.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

EXP = pathlib.Path(__file__).resolve().parent
ROOT = EXP.parents[1]
SHADOW = EXP / "shadow.py"
sys.path.insert(0, str(EXP))
import shadow  # noqa: E402

MAX_INFLIGHT = 15
CHUNK = 5
MAX_DISK_DROP_GB = 5.0
LOAD_CAP = 108.0
MIN_FREE_GB = 40.0
BUDGET_START = datetime(2026, 10, 7, 13, tzinfo=timezone.utc)
BUDGET_FLOOR = 0.13  # mean lane utilization when this phase began
BUDGET_PER_DAY = 0.12
BUDGET_CAP = 0.85
FIRST_HORIZON_DAY = date(2026, 10, 8)  # wave 2
WAVE_HOUR = 13
LAST_WAVE_END = datetime(2026, 10, 14, 3, tzinfo=timezone.utc)  # before the reset
POLL_S = 300


def wave_day(wave: int) -> date:
    if wave < 2:
        raise ValueError("horizon waves start at 2; wave 1 is the original design")
    return FIRST_HORIZON_DAY + timedelta(days=wave - 2)


def wave_window(wave: int, last_wave: int) -> tuple[datetime, datetime]:
    """When a wave may start submitting and when its submissions stop."""
    start = datetime.combine(wave_day(wave), datetime.min.time(), timezone.utc)
    start += timedelta(hours=WAVE_HOUR)
    end = LAST_WAVE_END if wave == last_wave else start + timedelta(days=1)
    return start, end


def budget(now: datetime) -> float:
    days = max((now - BUDGET_START).total_seconds(), 0) / 86400
    return min(BUDGET_CAP, BUDGET_FLOOR + BUDGET_PER_DAY * days)


def chunked(items: list[str], size: int = CHUNK) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def wave_plan(wave: int, slugs: list[str]) -> list[tuple[str, int, list[str]]]:
    """(arm, rollout, chunk) in submission order: every arm's rollout 1 first."""
    plan = []
    for rollout in range(1, 4):
        for arm in shadow.ARMS:
            if rollout > shadow.ARMS[arm]["rollouts"]:
                continue
            for chunk in chunked(slugs):
                plan.append((arm, rollout, chunk))
    return plan


def gate(
    *,
    inflight: int,
    size: int,
    load5: float,
    free_gb: float,
    utilization: float | None,
    allowed: float,
    free_drop_gb: float = 0.0,
) -> str | None:
    """None when a chunk of `size` may be submitted, else the reason to hold."""
    if inflight + size > MAX_INFLIGHT:
        return f"inflight {inflight}+{size} > {MAX_INFLIGHT}"
    if free_drop_gb > MAX_DISK_DROP_GB:
        return f"free disk fell {free_drop_gb:.0f} GB since the last check"
    if load5 >= LOAD_CAP:
        return f"load5 {load5:.0f} >= {LOAD_CAP:.0f}"
    if free_gb < MIN_FREE_GB:
        return f"free {free_gb:.0f} GB < {MIN_FREE_GB:.0f}"
    if utilization is None:
        return "lane utilization unreadable"
    if utilization >= allowed:
        return f"utilization {utilization:.2f} >= budget {allowed:.2f}"
    return None


# ---------------------------------------------------------------- readings


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp} {message}", flush=True)


def inflight() -> int:
    out = subprocess.run(
        ["subfleet", "runs", "--mine", "--running", "--last", "1000", "--json"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return sum(1 for line in out.splitlines() if '"job_id"' in line)


def lane_utilization() -> float | None:
    """Mean seven-day utilization across enabled Codex lanes, or None."""
    out = subprocess.run(
        ["subfleet", "status", "--json"], capture_output=True, text=True, check=False
    ).stdout
    try:
        lanes = json.loads(out)["lanes"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    values = []
    for lane in lanes:
        if not str(lane.get("lane_id", "")).startswith("codex") or not lane.get(
            "enabled"
        ):
            continue
        for reading in (lane.get("probe") or {}).get("readings", []):
            if (
                reading.get("window") == "seven_day"
                and reading.get("utilization") is not None
            ):
                values.append(float(reading["utilization"]))
                break
    return sum(values) / len(values) if values else None


def free_gb() -> float:
    return shutil.disk_usage("/System/Volumes/Data").free / 1e9


def shadow_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SHADOW), *args], cwd=ROOT, capture_output=True, text=True
    )


def submitted(ops: pathlib.Path, label: str) -> bool:
    receipts = ops / "submissions" / f"{label}.jsonl"
    return receipts.is_file() and '"job_id": "' in receipts.read_text()


def pending_batches(
    wave: int, plan: list[tuple[str, int, list[str]]], done: set[str]
) -> list[tuple[str, int, list[str]]]:
    """The plan's runs with no submission yet, rechunked in plan order."""
    batches: list[tuple[str, int, list[str]]] = []
    for arm, rollout, chunk in plan:
        missing = [
            s for s in chunk if shadow.run_key(arm, s, rollout, wave) not in done
        ]
        if batches and batches[-1][:2] == (arm, rollout):
            missing = batches.pop()[2] + missing
        for piece in chunked(missing):
            batches.append((arm, rollout, piece))
    return batches


_last_free: list[float] = []  # free disk at the previous check


def submit_when_open(ops: pathlib.Path, label: str, size: int, end: datetime) -> bool:
    while datetime.now(timezone.utc) < end:
        now = datetime.now(timezone.utc)
        free = free_gb()
        drop = (_last_free[0] - free) if _last_free else 0.0
        _last_free[:] = [free]
        reason = gate(
            inflight=inflight(),
            size=size,
            load5=os.getloadavg()[1],
            free_gb=free,
            utilization=lane_utilization(),
            allowed=budget(now),
            free_drop_gb=drop,
        )
        if reason is None:
            result = shadow_cli("submit", "--label", label)
            log(f"submit {label} ({size} jobs): {result.stdout.strip()}")
            # Ramp: one chunk per check.
            time.sleep(POLL_S)
            return True
        log(f"hold {label}: {reason}")
        time.sleep(POLL_S)
    return False


def drain(end: datetime) -> None:
    while inflight() and datetime.now(timezone.utc) < end:
        time.sleep(POLL_S)


def commit_and_push(message: str) -> None:
    git = ["git", "-C", str(ROOT)]
    subprocess.run(git + ["add", "experiments/sol61_shadow"], check=False)
    if subprocess.run(git + ["diff", "--cached", "--quiet"]).returncode == 0:
        log("nothing to commit")
        return
    body = f"{message}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
    subprocess.run(git + ["commit", "-q", "-m", body], check=False)
    for attempt in range(1, 6):
        if subprocess.run(git + ["push", "-q"]).returncode == 0:
            log(f"pushed: {message}")
            return
        log(f"push attempt {attempt} failed")
        time.sleep(60 * attempt)


def collect_wave(ops: pathlib.Path, wave: int, end: datetime) -> None:
    log(shadow_cli("collect").stdout.strip())
    retry = shadow_cli("outage-retry", "--label-prefix", f"sol61-shadow-w{wave}-outage")
    labels = [line.split()[0] for line in retry.stdout.splitlines() if line.strip()]
    for label in labels:
        if submitted(ops, label):
            continue
        manifest = json.loads((ops / "batches" / f"{label}.json").read_text())
        submit_when_open(ops, label, len(manifest["jobs"]), end)
    if labels:
        drain(end)
        log(shadow_cli("collect").stdout.strip())
    log(shadow_cli("prune").stdout.strip())
    log(shadow_cli("pack", "--wave", str(wave)).stdout.strip())


def run_wave(ops: pathlib.Path, wave: int, last_wave: int) -> None:
    start, end = wave_window(wave, last_wave)
    while datetime.now(timezone.utc) < start:
        time.sleep(
            min(POLL_S, max((start - datetime.now(timezone.utc)).total_seconds(), 1))
        )
    day = wave_day(wave).isoformat()
    targets = [
        row for row in shadow.load_targets() if shadow.validatable(row["target"])
    ]
    slugs = [row["slug"] for row in targets if row["windowStart"] > day]
    plan = wave_plan(wave, slugs)
    done = {shadow.receipt_key(row) for row in shadow.load_submissions(ops)}
    batches = pending_batches(wave, plan, done)
    runs = sum(len(chunk) for _, _, chunk in batches)
    log(f"wave {wave} ({day}): {len(slugs)} open targets, {runs} runs to submit")
    for index, (arm, rollout, chunk) in enumerate(batches, 1):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        label = f"sol61-shadow-w{wave}-{arm}-r{rollout}-{stamp}-b{index}"
        result = shadow_cli(
            "batch", "--arm", arm, "--rollout", str(rollout), "--wave", str(wave),
            "--slugs", ",".join(chunk), "--open-after", day, "--label", label,
        )  # fmt: skip
        if result.returncode != 0:
            log(f"batch {label} failed: {result.stderr[-400:]}")
            continue
        if not submit_when_open(ops, label, len(chunk), end):
            left = sum(len(c) for _, _, c in batches[index - 1 :])
            log(f"wave {wave}: {left} runs unsubmitted at {end:%FT%TZ}")
            break
    drain(end)
    collect_wave(ops, wave, end)
    commit_and_push(f"Collect Sol 6.1 shadow horizon wave {wave} ({day})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ops", type=pathlib.Path, default=shadow.DEFAULT_OPS)
    parser.add_argument("--first-wave", type=int, default=2)
    parser.add_argument("--last-wave", type=int, default=7)
    args = parser.parse_args(argv)
    if not os.environ.get("CLAUDE_CODE_SESSION_ID"):
        raise SystemExit("CLAUDE_CODE_SESSION_ID is needed for `subfleet runs --mine`")
    for wave in range(args.first_wave, args.last_wave + 1):
        run_wave(args.ops, wave, args.last_wave)
    log("all waves done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
