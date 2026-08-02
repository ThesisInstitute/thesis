"""Closing multi-metric comparison across every accuracy arm on corpus B.

Rule (set 2026-07-31): no arm is crowned on a single metric. Reported per arm:
mean/median nCRPS, 80% coverage, median interval width / level, median |error|
/ level, and per-event nCRPS. A recommended arm must be non-inferior across
metrics and across events, vs the plain strong-model baseline.
"""
from __future__ import annotations
import argparse, json, statistics as st, sys, collections
from pathlib import Path
HERE = Path(__file__).parent; sys.path.insert(0, str(HERE))
import scoring as S

def main():
    units = {u["unit_id"]: u for u in json.loads((HERE / "ground_truth_B_all.json").read_text())}
    sd = {u: st.pstdev([h["value"] for h in v["history"]]) for u, v in units.items()}
    ev = {u: u.split(".")[0] for u in units}

    arms: dict[str, dict[str, list]] = collections.defaultdict(lambda: collections.defaultdict(list))

    def add(arm, uid, f):
        if f.get("point") is None or f.get("ci_low") is None: return
        arms[arm][uid].append(f)

    # The bake-off file holds two batches under different cell_key formats
    # (6-field pre-effort, 7-field with effort slot) — 789 logical duplicates
    # (CHECK2.md). Canonical = the 7-field batch, which is the superset design;
    # this filter pins it explicitly.
    for line in (HERE / "runs_bakeoff.jsonl").read_text().splitlines():
        if not line.strip(): continue
        r = json.loads(line)
        if r.get("cell_key", "").count("|") != 6:  # 7 fields = 6 separators
            continue
        c = r["config"]; f = r.get("forecast") or {}
        name = None
        if c["elicitation"] == "point_ci_json" and c.get("effort") is None:
            name = f"{c['model'].split('-')[1]} {'bill' if c['policy_context']=='operative_only' else 'no-bill'}"
        elif c["elicitation"] == "point_ci_json" and c.get("effort") == "max":
            name = f"{c['model'].split('-')[1]} bill effort=max"
        elif c["elicitation"] == "decomposed_json":
            name = f"{c['model'].split('-')[1]} bill decomposed"
        if name: add(name, r["unit_id"], f)

    p = HERE / "runs_instr.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            if not line.strip(): continue
            r = json.loads(line); f = r.get("forecast") or {}
            add(f"opus no-bill max [{r['style']}]", r["unit_id"], f)

    p = HERE / "runs_mas.jsonl"
    if p.exists():
        for line in p.read_text().splitlines():
            if not line.strip(): continue
            r = json.loads(line); f = r.get("forecast") or {}
            add(f"opus no-bill max [{r['arm']}]", r["unit_id"], f)

    for b in json.loads((HERE / "baselines_B_all.json").read_text()):
        if b.get("error"): continue
        for k in ("persistence", "drift"):
            blk = b[k]
            if "crps" in blk:
                add(k, b["unit_id"], {"point": blk["point"], "ci_low": blk["ci_low"], "ci_high": blk["ci_high"]})

    # Winkler interval score (alpha=0.2, proper for the 80% interval):
    # width + (2/alpha)*(lo-y if y<lo) + (2/alpha)*(y-hi if y>hi), divided by sd.
    def winkler(f, y):
        w = f["ci_high"] - f["ci_low"]
        if y < f["ci_low"]: w += 10.0 * (f["ci_low"] - y)
        if y > f["ci_high"]: w += 10.0 * (y - f["ci_high"])
        return w

    rows = []
    for name, per in arms.items():
        nc, cov, wid, ae, wk = {}, [], [], [], {}
        ev_nc = collections.defaultdict(list)
        n_runs = 0
        for uid, fs in per.items():
            t = units[uid]["truth"]["first_print_value"]
            scores = [S.score_forecast(f["point"], f["ci_low"], f["ci_high"], t) for f in fs]
            n_runs += len(fs)
            nc[uid] = st.mean([s["crps"] for s in scores]) / sd[uid]
            ev_nc[ev[uid]].append(nc[uid])
            cov += [s["covered80"] for s in scores]
            wk.setdefault(uid, st.mean([winkler(f, t) for f in fs]) / sd[uid])
            wid += [(f["ci_high"] - f["ci_low"]) / t for f in fs]
            ae += [abs(f["point"] - t) / t for f in fs]
        if not nc: continue
        rows.append({
            "arm": name, "n_units": len(nc), "n_runs": n_runs,
            "mean_ncrps": st.mean(nc.values()), "median_ncrps": st.median(nc.values()),
            "mean_winkler": st.mean(wk.values()),
            "cov80": st.mean(cov), "med_width_pct": st.median(wid) * 100,
            "med_abserr_pct": st.median(ae) * 100,
            "per_event": {e: round(st.mean(v), 3) for e, v in sorted(ev_nc.items())},
            "per_unit": nc,
        })
    rows.sort(key=lambda r: r["mean_ncrps"])

    # matched-unit head-to-head vs the reference arm, on common units only
    ref = next((r for r in rows if r["arm"] == "opus no-bill"), None)
    if ref:
        print("\n=== matched-unit comparison vs 'opus no-bill' (common units only) ===")
        print(f"{'arm':38s} {'nCommon':>7s} {'ΔnCRPS':>8s} {'ΔWinkler':>9s}")
        for r in rows:
            if r["arm"] == "opus no-bill": continue
            common = [u for u in r["per_unit"] if u in ref["per_unit"]]
            if len(common) < 5: continue
            d1 = st.mean([r["per_unit"][u] - ref["per_unit"][u] for u in common])
            print(f"{r['arm']:38s} {len(common):>7d} {d1:>+8.3f} {'':>9s}")
    out = {"rows": [{k: v for k, v in r.items() if k != "per_unit"} for r in rows]}
    (HERE / "results" / "final_multimetric.json").write_text(json.dumps(out, indent=1))
    print(f"{'arm':38s} {'nU':>3s} {'nR':>4s} {'nCRPS':>7s} {'med':>6s} {'wink':>6s} {'cov80':>6s} {'width%':>7s} {'|err|%':>7s}")
    for r in rows:
        print(f"{r['arm']:38s} {r['n_units']:>3d} {r['n_runs']:>4d} {r['mean_ncrps']:>7.3f} "
              f"{r['median_ncrps']:>6.3f} {r['mean_winkler']:>6.2f} {r['cov80']:>6.2f} "
              f"{r['med_width_pct']:>7.2f} {r['med_abserr_pct']:>7.2f}")
    print("\nper-event nCRPS for top arms:")
    for r in rows[:6]:
        print(f"  {r['arm']:36s} {r['per_event']}")

if __name__ == "__main__":
    main()
