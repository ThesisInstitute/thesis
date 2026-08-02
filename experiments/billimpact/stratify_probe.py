"""Registered payoff analysis: stratify EXISTING forecast results by probe-
measured knowledge (PREREG-AMENDMENT-3.md appendix, classifier fixed before
the probe ran).

KNOWN(model, unit) iff median over that model's ANCHORED probe reps of
|recall − first print| / history pstdev < 0.5 (sensitivity 0.25 / 1.0; bare
variant reported as a stricter secondary). Sanity gate first: the recomputed
36-unit head-to-heads must reproduce the published 26/36 (vs naive) and
29/36 (vs persistence) before any stratified number is reported.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import scoring as S  # noqa: E402

GT_FILES = ("ground_truth_B_all.json", "ground_truth_crosstype.json", "ground_truth_wave2.json")
BASELINE_FILES = ("baselines_B_all.json", "baselines_newtypes.json", "baselines_wave2.json")


def load_units():
    units = {}
    for f in GT_FILES:
        for u in json.loads((HERE / f).read_text()):
            if u.get("truth", {}).get("first_print_value") is not None:
                units[u["unit_id"]] = u
    return units


def main() -> None:
    units = load_units()
    assert len(units) == 36
    truth = {u: v["truth"]["first_print_value"] for u, v in units.items()}
    sd = {u: st.pstdev([h["value"] for h in v["history"]]) for u, v in units.items()}

    # --- probe classification -------------------------------------------------
    probe = [json.loads(l) for l in (HERE / "runs_probe.jsonl").read_text().splitlines() if l.strip()]
    rel = {"anchored": {}, "bare": {}}  # variant -> (model, unit) -> relative recall errors
    for r in probe:
        if r.get("recall") is None:
            continue
        rel[r["variant"]].setdefault((r["model"], r["unit_id"]), []).append(
            abs(r["recall"] - truth[r["unit_id"]]) / sd[r["unit_id"]])

    def known_set(model, thresh, variant="anchored"):
        ks, unresolved = set(), []
        for u in units:
            errs = rel[variant].get((model, u), [])
            if len(errs) < 2:
                unresolved.append(u)
            elif st.median(errs) < thresh:
                ks.add(u)
        return ks, unresolved

    # --- existing forecast arms ----------------------------------------------
    def add_run(store, uid, f):
        if f.get("point") is None or f.get("ci_low") is None or f.get("ci_high") is None:
            return
        store.setdefault(uid, []).append(f)

    fbm, fnaive = {}, {}
    for line in (HERE / "runs_bakeoff.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("cell_key", "").count("|") != 6:
            continue
        c = r["config"]
        f = r.get("forecast") or {}
        if c["model"] != "claude-fable-5" or c["elicitation"] != "point_ci_json":
            continue
        if c["policy_context"] == "operative_only" and c.get("effort") == "max":
            add_run(fbm, r["unit_id"], f)
        elif c["policy_context"] == "none" and c.get("effort") is None:
            add_run(fnaive, r["unit_id"], f)
    for line in (HERE / "runs_newtypes.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        c = r.get("config", {})
        f = r.get("forecast") or {}
        if c.get("model") != "claude-fable-5" or c.get("elicitation") != "point_ci_json":
            continue
        if c.get("policy_context") == "operative_only" and c.get("effort") == "max":
            add_run(fbm, r["unit_id"], f)
        elif c.get("policy_context") == "none" and c.get("effort") is None:
            add_run(fnaive, r["unit_id"], f)

    pers = {}
    for bf in BASELINE_FILES:
        for b in json.loads((HERE / bf).read_text()):
            if b.get("error") or b["unit_id"] not in units:
                continue
            blk = b["persistence"]
            pers[b["unit_id"]] = {"point": blk["point"], "ci_low": blk["ci_low"], "ci_high": blk["ci_high"]}

    def ncrps(store):
        out = {}
        for uid, fs in store.items():
            if uid not in units:
                continue
            scores = [S.score_forecast(f["point"], f["ci_low"], f["ci_high"], truth[uid])["crps"] for f in fs]
            out[uid] = st.mean(scores) / sd[uid]
        return out

    nc_fbm, nc_naive = ncrps(fbm), ncrps(fnaive)
    nc_pers = {u: S.score_forecast(p["point"], p["ci_low"], p["ci_high"], truth[u])["crps"] / sd[u]
               for u, p in pers.items()}

    common = sorted(set(nc_fbm) & set(nc_naive) & set(nc_pers))
    print(f"units with all three arms: {len(common)} (fbm={len(nc_fbm)} naive={len(nc_naive)} pers={len(nc_pers)})")

    wins_naive = sum(1 for u in common if nc_fbm[u] < nc_naive[u])
    wins_pers = sum(1 for u in common if nc_fbm[u] < nc_pers[u])
    print(f"SANITY GATE — reproduce published head-to-heads on N={len(common)}: "
          f"vs naive {wins_naive}/{len(common)} (published 26/36), "
          f"vs persistence {wins_pers}/{len(common)} (published 29/36)")
    if len(common) != 36 or wins_naive != 26 or wins_pers != 29:
        print("*** GATE MISMATCH — stratified numbers below are provisional; reconcile before publishing ***")

    # --- stratification -------------------------------------------------------
    out = {"gate": {"n": len(common), "vs_naive": wins_naive, "vs_pers": wins_pers}}
    for model in ("claude-fable-5", "claude-opus-5"):
        out[model] = {}
        for thresh in (0.5, 0.25, 1.0):
            ks, unresolved = known_set(model, thresh)
            known = [u for u in common if u in ks]
            unknown = [u for u in common if u not in ks and u not in unresolved]
            row = {"thresh": thresh, "n_known": len(known), "n_unknown": len(unknown),
                   "n_unresolved": len(unresolved)}
            for label, stratum in (("KNOWN", known), ("UNKNOWN", unknown)):
                if not stratum:
                    row[label] = None
                    continue
                row[label] = {
                    "n": len(stratum),
                    "wins_vs_naive": sum(1 for u in stratum if nc_fbm[u] < nc_naive[u]),
                    "wins_vs_pers": sum(1 for u in stratum if nc_fbm[u] < nc_pers[u]),
                    "mean_d_naive": st.mean([nc_fbm[u] - nc_naive[u] for u in stratum]),
                    "mean_d_pers": st.mean([nc_fbm[u] - nc_pers[u] for u in stratum]),
                    "mean_ncrps_fbm": st.mean([nc_fbm[u] for u in stratum]),
                }
            out[model][str(thresh)] = row
            if thresh == 0.5:
                print(f"\n{model} @ thresh 0.5: KNOWN={row['n_known']} UNKNOWN={row['n_unknown']} "
                      f"unresolved={row['n_unresolved']}")
                for label in ("KNOWN", "UNKNOWN"):
                    s = row[label]
                    if s:
                        print(f"  {label:8s} n={s['n']:2d}  vs-naive {s['wins_vs_naive']}/{s['n']}  "
                              f"vs-pers {s['wins_vs_pers']}/{s['n']}  "
                              f"dNaive {s['mean_d_naive']:+.3f}  dPers {s['mean_d_pers']:+.3f}  "
                              f"nCRPS {s['mean_ncrps_fbm']:.3f}")

    # --- bare-variant (no history shown): the stricter memory measure ---------
    print("\nBARE variant (no history shown — pure recall):")
    for model in ("claude-fable-5", "claude-opus-5"):
        for thresh in (0.5, 0.25, 1.0):
            ks, unresolved = known_set(model, thresh, variant="bare")
            known = [u for u in common if u in ks]
            unknown = [u for u in common if u not in ks and u not in unresolved]
            row = {"variant": "bare", "thresh": thresh, "n_known": len(known),
                   "n_unknown": len(unknown), "n_unresolved": len(unresolved)}
            for label, stratum in (("KNOWN", known), ("UNKNOWN", unknown)):
                if not stratum:
                    row[label] = None
                    continue
                row[label] = {
                    "n": len(stratum),
                    "wins_vs_naive": sum(1 for u in stratum if nc_fbm[u] < nc_naive[u]),
                    "wins_vs_pers": sum(1 for u in stratum if nc_fbm[u] < nc_pers[u]),
                    "mean_d_naive": st.mean([nc_fbm[u] - nc_naive[u] for u in stratum]),
                    "mean_d_pers": st.mean([nc_fbm[u] - nc_pers[u] for u in stratum]),
                    "mean_ncrps_fbm": st.mean([nc_fbm[u] for u in stratum]),
                }
            out[model][f"bare_{thresh}"] = row
            if thresh == 0.5:
                print(f"{model} @ bare 0.5: KNOWN={row['n_known']} UNKNOWN={row['n_unknown']} "
                      f"unresolved={row['n_unresolved']}")
                for label in ("KNOWN", "UNKNOWN"):
                    s = row[label]
                    if s:
                        print(f"  {label:8s} n={s['n']:2d}  vs-naive {s['wins_vs_naive']}/{s['n']}  "
                              f"vs-pers {s['wins_vs_pers']}/{s['n']}  "
                              f"dNaive {s['mean_d_naive']:+.3f}  dPers {s['mean_d_pers']:+.3f}  "
                              f"nCRPS {s['mean_ncrps_fbm']:.3f}")

    # --- recall-error vs forecast-error correlation (fable) -------------------
    xs, ys = [], []
    for u in common:
        errs = rel["anchored"].get(("claude-fable-5", u), [])
        if len(errs) >= 2:
            xs.append(st.median(errs))
            ys.append(nc_fbm[u])
    if len(xs) >= 5:
        mx, my = st.mean(xs), st.mean(ys)
        cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
        vx = sum((a - mx) ** 2 for a in xs) ** 0.5
        vy = sum((b - my) ** 2 for b in ys) ** 0.5
        r = cov / (vx * vy) if vx and vy else float("nan")
        conc = sum(1 for i in range(len(xs)) for j in range(i + 1, len(xs))
                   if (xs[i] - xs[j]) * (ys[i] - ys[j]) > 0)
        tot = len(xs) * (len(xs) - 1) // 2
        out["fable_recall_forecast_corr"] = {"n": len(xs), "pearson": r, "concordant_pairs": f"{conc}/{tot}"}
        print(f"\nfable recall-error vs forecast-error: n={len(xs)} pearson r={r:+.3f} "
              f"concordant {conc}/{tot}")

    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "probe_stratification.json").write_text(json.dumps(out, indent=1))
    print("\nwrote results/probe_stratification.json")


if __name__ == "__main__":
    main()
