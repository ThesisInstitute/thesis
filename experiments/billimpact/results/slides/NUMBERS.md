# NUMBERS.md — provenance manifest for the slide visuals

Every number plotted or printed on the four figures, with its source. Sources
are `experiments/billimpact/RESULTS.md` (line numbers below, as of this
afternoon's version, §§1–5 final) or a recomputation from the frozen artifacts
in `experiments/billimpact/` (exact command + output reproduced here). Nothing
else. Line numbers refer to the file as read at ~15:15 EDT (git-tracked copy on
`hack/david-billimpact`; file unchanged at 19,991 bytes since 15:14).

---

## fig1_harness_dimensions.png — "The biggest knob in the harness is the model itself"

| Plotted | Value | Source |
|---|---|---|
| model tier spread | 9.3% (bar: 9.31) | RESULTS.md L41 (table "D4 · model tier · 9.3%"); recomputation below gives 9.314 |
| elicitation format spread | 8.1% (8.10) | L43; recomputation 8.100 |
| policy context spread | 3.5% (3.54) | L42; recomputation 3.540 |
| statutory magnitude spread | 2.1% (2.13) | L45; recomputation 2.133 |
| debate pipeline spread | 1.0% (1.04) | L44; recomputation 1.044 |
| IQR whiskers (per dimension) | D4 [4.89, 12.69] · D2 [5.91, 10.77] · D1 [2.86, 4.69] · D5 [1.06, 2.86] · D3 [0.52, 1.73] | recomputed from `results/summary.json` (`spread_pp_iqr`), command below |
| "12.4× its permutation null — survives Bonferroni and state clustering; most defensible number" | | L41 verbatim |
| naive ratio 4.65 [2.11, 6.46] | | L41. **Attribution note:** this CI belongs to the *naive spread ratio* 4.65, not to the 12.4× permutation multiple — the figure prints it beside "naive ratio", which is the correct attachment |
| "4.8× its null, fragile to state clustering, suggestive" · 1.73 [1.17, 2.92] | | L43 |
| "4.1× its null (p<0.0003), carried entirely by the purpose-clause arm" · 1.81 [1.11, 2.65] | | L42; purpose-clause = named-statute recall per §2 (L59–79) |
| "null — 0.97 after a red-team denominator fix" | | L45 |
| "null on magnitude — shifts forecasts up in 8/9 moving units (p=0.039); variance ×5.4" | | L44 |
| footer: expected ratio 0.12–0.52 under a true null | | L47–51 |
| subtitle: 12 SNAP units = 6 states × 2 target months; Pub. L. 118-5 §§311–314; 2,520 runs | | L33–34 (units), L32 (statute), L20–21 (2,520 corpus-A grid runs), L11–12 (pre-registered), L26–27 (first prints frozen) |

Recomputation (spread medians + IQRs), run from `experiments/billimpact/`:

```
python3 -c "
import json
S = json.load(open('results/summary.json'))
for dim in ['D1','D2','D3','D4','D5']:
    d = S['dispersion'][dim]
    print(dim, d['field'], round(d['spread_pp_median'],3), [round(x,2) for x in d['spread_pp_iqr']])
"
# D1 policy_context 3.54  [2.86, 4.69]
# D2 elicitation    8.1   [5.91, 10.77]
# D3 pipeline       1.044 [0.52, 1.73]
# D4 model          9.314 [4.89, 12.69]
# D5 magnitude      2.133 [1.06, 2.86]
```

---

## fig2_effort_context_interaction.png — "Bill text hurts at default effort — and pays at max"

| Plotted | Value | Source |
|---|---|---|
| fable · bill · default effort | 0.339 | RESULTS.md L198 (0.339); `final_multimetric.json` mean_ncrps 0.3390 |
| fable · bill · effort=max | 0.208 | L190 (0.208); json 0.2079 |
| fable · no-bill (naive) | 0.292 | L197 (0.292); json 0.2923 |
| opus · bill · default effort | **0.261** | **not printed in RESULTS.md** — recomputed: `final_multimetric.json` arm "opus bill" mean_ncrps 0.2606. Consistency check against RESULTS L232: opus effort-only delta −0.014 ⇒ 0.2470 − 0.2606 = −0.0136 ≈ −0.014 ✓ |
| opus · bill · effort=max | 0.247 | L192 (0.247); json 0.2470 |
| opus · no-bill (naive) | 0.253 | L191 (0.253); json 0.2533 |
| +0.047 (fable bill@default vs fable naive) | | L198 ("+0.047 vs fable naive") and L214; also 0.339 − 0.292 = +0.047. No CI printed in RESULTS.md, so none is shown |
| −0.131 [−0.205, −0.062], 39% lower error, 19/28 units (fable, effort only) | | L228–231 |
| −0.084 [−0.164, −0.008] (fable bill@max vs naive) | | L190, L202–203 |
| −0.014 [−0.038, +0.015], n.s. (opus, effort only) | | L232 |
| "best arm in the study" | | L190 (bold row, lowest nCRPS & Winkler in the §5 table) + L221 ("the recipe leads the board") |
| mechanism text (overshoot; SAAR ×12 worst case; effort disciplines magnitude not direction) | | L215–221 |
| naive arms are default-effort | | §5 table labels naive rows without an effort tag while max-effort arms are tagged (L190–198); the arm names in `final_multimetric.json` match |

---

## fig3_ranking_inversion.png — "Same models, same bills — elicitation inverts the ranking"

| Plotted | Value | Source |
|---|---|---|
| naive column: opus 0.253 vs fable 0.292 | | L191, L197 (json 0.2533 / 0.2923) |
| tuned column: fable 0.208 vs opus 0.247 | | L190, L192 (json 0.2079 / 0.2470) |
| "opus wins the naive comparison by 0.039" | 0.292 − 0.253 = 0.039 | arithmetic on L191/L197 values |
| "fable wins the tuned one by 0.039" | 0.247 − 0.208 = 0.039 | arithmetic on L190/L192 values |
| −0.084 [−0.164, −0.008] vs its naive arm | | L190, L202–203 (20/28 units at L203; figure cites the CI only) |
| −0.118 [−0.211, −0.035] vs persistence, 22/28 units | | L203–204 |
| "leading the Winkler interval score at 0.75 coverage" | | L204–205 ("no metric traded away"), L190 (Winkler 1.30, cov80 0.75) |
| persistence 0.326 | | L195 (json 0.3258) |
| caveat: naive-arm CI nominal, marginal under multiplicity; persistence comparison is the robust one | | L208–210 |
| nCRPS definition (CRPS normalized by each unit's history dispersion) | | L184–185 |

Recomputation (all §5 arm means), run from `experiments/billimpact/`:

```
python3 -c "
import json
for r in json.load(open('results/final_multimetric.json'))['rows']:
    print(f\"{r['arm']:42s} mean_ncrps={r['mean_ncrps']:.4f}\")
"
# fable bill effort=max   0.2079      # opus bill            0.2606
# opus bill effort=max    0.2470      # fable no-bill        0.2923
# opus no-bill            0.2533      # persistence          0.3258
# fable bill              0.3390      # (12 other arms omitted here; full output kept in session log)
```

---

## hero_named_statute_recall(.png / _dark.png) — "Redact the law's name and the model starts reading the bill"

All line points are **medians of 5 runs** (point+CI elicitation) recomputed
from the frozen run files by `recompute_hero_medians.py` (in this folder; reads
`runs_amend3.jsonl`, `runs_deconfound.jsonl`, `ground_truth_extra.json`
read-only). Full output:

```
== NAMED retro Jan-2021 (runs_amend3, period=retro2021) ==
fable-5  derivation  $100: 363.2  $300: 524.6  $900: 977.0   monotone: True
fable-5  point_ci    $100: 540.0  $300: 540.0  $900: 950.0   monotone: False
opus-5   derivation  $100: 378.0  $300: 553.0  $900: 1085.6  monotone: True
opus-5   point_ci    $100: 510.0  $300: 545.0  $900: 540.0   monotone: False
sonnet-5 derivation  $100: 323.6  $300: 355.6  $900: 1020.6 (n=4)  monotone: True
sonnet-5 point_ci    $100: 380.0  $300: 400.0  $900: 380.0   monotone: False
== REDACTED retro Jan-2021 (runs_deconfound) ==
fable-5  derivation  $100: 348.6  $300: 514.0  $900: 945.2   monotone: True
fable-5  point_ci    $100: 420.0  $300: 550.0  $900: 1000.0  monotone: True
opus-5   derivation  $100: 353.6  $300: 544.6  $900: 1055.6  monotone: True
opus-5   point_ci    $100: 460.0  $300: 505.0  $900: 900.0   monotone: True
== FUTURE Nov-2026 (runs_amend3, period=future2026) ==
(all 6 model × elicitation cells strictly monotone — not plotted, cited in footnote)
realized first print, fpuc300.us.2021-01: 570.6
last history value before target: 2020-10, 306.0
```

All cells n=5 except sonnet-5 named/derivation $900 (n=4; not plotted — the
plotted point+CI cells are all n=5).

| Plotted | Value | Source |
|---|---|---|
| named panel lines (point+CI): sonnet 380/400/380 · opus 510/545/540 · fable 540/540/950 | | recomputation above |
| redacted panel lines (point+CI): opus 460/505/900 · fable 420/550/1000 | | recomputation above |
| realized Jan-2021 first print 570.6 (dashed line) | | `ground_truth_extra.json` → `fpuc300.us.2021-01.truth.first_print_value` = 570.6; corroborated by RESULTS.md L140–141 ("its retro forecast is 570, the realized first print to within rounding") |
| tag "strictly monotone in dose: 0 / 3 models" (named, point+CI) | | RESULTS.md L113 (table row "retro 2021 · point+CI · 0/3"); recomputation confirms all three named point+CI cells non-monotone |
| tag "monotone in dose: 4 / 4 cells" (redacted) | | L126–128 ("monotone in 4/4 cells"); recomputation confirms (2 models × 2 elicitations). Panel plots the 2 point+CI cells; footnote states the count includes the derivation cells |
| noise chips "0.2–2.0×" (named) and "3.0–8.1×" (redacted) | | L113 (0.2–2.0×); L127 (point+CI 8.1×/3.0×) — the redacted chip spans the two point+CI values printed there |
| doses $100 / $300 / $900 per week | | L91–92 ("rewrites a $300/week supplement to $100 / $900"); dose keys third/actual/tripled in `amend3_sweep.py` L23 + `apply_dollar_magnitude` |
| statute = Pub. L. 116-260 §203 (FPUC) | | `extended_harness.py` PROVISIONS_B law string: "Consolidated Appropriations Act, 2021, Pub. L. 116-260, div. N … sec. 203"; RESULTS.md L91 calls it the FPUC arm |
| series W825RC1, $B SAAR, Jan-2021 target | | `extended_harness.py` SERIES_DESC["W825RC1"] = "US personal current transfer receipts: government social benefits to persons: unemployment insurance"; unit `fpuc300.us.2021-01`, target_month 2021-01, origin vintage 2020-12-15, last history value 306.0 (Oct 2020) |
| footnote "derivation elicitation restores dose-response even named (3/3)" | | L114 (table row "retro 2021 · directed derivation · 3/3"); recomputation confirms 3/3 |
| footnote "raising effort does not (§3b)" | | L136–142 ("Retro-period dose-response stays flat at every effort level … restructuring the elicitation does") |
| footnote "the 2026 window: 6/6 monotone" | | L112 (future 2026 row, 6/6); recomputation confirms all 6 future cells monotone |
| footnote "sonnet-5 ran in the named arm only" | | `deconfound_sweep.py` L9: MODELS = opus, fable only |
| footnote "redaction arm registered before its runs" | | L124–125 ("the reviewer's objection was registered as a new arm"); deconfound_sweep.py docstring "Registered before run" |
| "the only change is deleting the statute's name" | | L126 ("with the statute name redacted from the header (nothing else changed)") |

**Framing guard (if asked on stage):** RESULTS.md L129–131 withdraws the
original *period* claim — the honest claim is exactly what the figure titles
say: recall is keyed by statutory identity (hide the name and the model derives
from the text even inside its training window). A named-future cell was not
run, so a residual period effect is not excluded (L131–132) — hence the panels
compare named vs redacted on the *same* retro target and the future window is
only a footnote.

---

## Dropped / adjusted claims

- **Nothing from the four requested headlines was dropped.** One adjustment:
  the task brief described "12.4× has CI [2.11, 6.46]"; in RESULTS.md L41 that
  CI belongs to the **naive spread ratio 4.65**, not the 12.4× permutation
  multiple. fig1 attaches it to "naive ratio 4.65 [2.11, 6.46]" accordingly.
- opus · bill · default effort (0.261) appears in no RESULTS.md row; it is
  taken from the frozen `results/final_multimetric.json` (0.2606) and passes
  the consistency check against the printed opus effort-delta (−0.014, L232).
- fig2's +0.047 is shown without a CI because RESULTS.md prints none for it.
- Hero panels plot point+CI cells only; the 4/4 and 0/3 tags follow RESULTS.md's
  own cell definitions, and the footnote discloses that 4/4 includes the two
  derivation cells and that sonnet-5 has no redacted counterpart.

## Files

- `make_slide_visuals.py` — renders all five PNGs (2400×1350 @180dpi, 16:9).
- `recompute_hero_medians.py` — re-derives every hero data point from raw runs.
- Figures: `fig1_harness_dimensions.png`, `fig2_effort_context_interaction.png`,
  `fig3_ranking_inversion.png`, `hero_named_statute_recall.png`,
  `hero_named_statute_recall_dark.png`.
