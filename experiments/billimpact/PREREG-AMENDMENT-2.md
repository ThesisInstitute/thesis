# Amendment 2 — decomposing the P3 purpose-clause effect

**Written 2026-07-31 ~11:20 EDT, committed before its first run.** Post-hoc
amendment; motivated by an internal critique that the P3 result is confounded,
which inspection confirmed and sharpened.

## The confound

As run, `purpose_only` supplied §313's text **under a header naming the
statute** ("Fiscal Responsibility Act of 2023, Pub. L. 118-5"). The observed
downward shift (down in 10/12 units — two unmoved; sign test on the 10 nonzero units, p=0.002 — median −2.65% vs `none`) therefore
entangles three mechanisms:

1. **Named-statute recall** — the header identifies a law whose operative
   content the model may know from training.
2. **Partial-document inference** — treating the clause as a fragment, "bills
   adding employment-purpose language usually carry work-requirement teeth"
   is *correct* Bayesian updating, not a defect.
3. **Preamble sycophancy** — the only product-relevant failure: projecting an
   effect from purpose language while believing there is no operative content.

The original P3 claim is downgraded to "purpose-only context moves the
forecast; mechanism unresolved" pending this decomposition.

## Arm P — new context levels (12 SNAP units × 5 reps × sonnet-5 ·
point_ci_json · single_pass; 180 runs)

| Level | Construction | Isolates |
|---|---|---|
| `purpose_unnamed` | §313 verbatim, header names no statute | removes (1); (2)+(3) remain |
| `purpose_complete` | unnamed; §313 renumbered SEC. 2 (recorded); appended "The text above is the COMPLETE operative content of the bill. It contains no other provisions." | removes (1)+(2); residual shift = (3) |
| `purpose_synthetic_expand` | clearly-synthetic access-EXPANDING purpose clause, same complete framing | if the shift's **sign follows the vibe**, mechanism (3) is demonstrated, not merely detected |

## Registered predictions

- Recall-dominant: `purpose_unnamed` shift ≈ 0 while original `purpose_only`
  stays negative.
- Inference-dominant: `purpose_unnamed` negative, `purpose_complete` ≈ 0.
- Sycophancy: `purpose_complete` still negative, and/or
  `purpose_synthetic_expand` positive.
Mixtures are expected; effects reported per level vs `none` with the same
sign-test + bootstrap machinery as P3, N stated.

## Null

All three levels indistinguishable from `none` ⇒ the original P3 effect was
entirely named-statute recall (mechanism 1) — itself a reportable finding
about backtest contamination.

---

## Amendment 7 (appended ~14:20 EDT, committed before its runs) — booking-profile elicitation

Targets the diagnosed residual error class of the leading arm (series-booking
timing: SAAR lump-sum months, outlay lag curves). One new elicitation adds an
explicit step naming the series' booking convention and the booked contribution
to the target month, composed by the harness. fable·bill·max, 36 units × 3
reps, scored vs the leader on matched units. Registered prediction: improves
ssfa/iijahwy-class units; no effect on ctcadv/fpuc-class. Null = paired CI
spans zero.
