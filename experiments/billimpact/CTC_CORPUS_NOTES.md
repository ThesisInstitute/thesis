# S.3596 refundable-CTC corpus: construction notes

`corpus_ctc.json` holds 14 household cases with PolicyEngine-US ground truth for the
Stronger Start for Working Families Act (S.3596, 119th Congress; Hassan, Young) in tax year
2026. Every credit amount in that file and in this one was read off `pe_server.py`; none was
computed by hand.

PolicyEngine-US **1.784.3** (policyengine-core 3.30.3), version read from
`importlib.metadata.version('policyengine-us')` — the package exposes no `__version__`
attribute, so that is the authority.

## The mechanism, and why one subsection is not enough

Section 2 of the bill has two operative parts, and each alone gives the wrong answer.

**§2(a)** strikes `"$3,000"` in IRC §24(d)(1)(B)(i) and inserts `"$1"`. That subsection sets
the earned-income floor above which the refundable portion of the child tax credit phases in
at 15 cents on the dollar. Read alone it looks like a cut from $3,000 — but $3,000 is not the
number in force for 2026.

**§2(b)** strikes IRC §24(h)(6). That is the TCJA-era paragraph which overrides
§24(d)(1)(B)(i) and substitutes $2,500 for the period §24(h) governs. Repealing it removes
the override and lets the amended §24(d)(1)(B)(i) figure control.

Together they move the operative threshold from **$2,500 to $1**. A reader who takes only
§2(a) baselines against $3,000 and overstates the change; a reader who takes only §2(b) sees
a repeal with no replacement figure and cannot price it at all. §2(c) makes the amendments
effective for taxable years beginning after December 31, 2025, so TY2026 is the first
affected year.

Modeled as `gov.irs.credits.ctc.refundable.phase_in.threshold`: 2500 under
current law, 1 under the reform.

The 15% phase-in rate is untouched, which is why every household in the interior of the
phase-in range gains exactly the same amount — **$374.85**, or 15% of the $2,499 the threshold
drops by — no matter its earnings or composition. (Arithmetic stated for orientation only;
$374.85 is what the tool returns.) The interesting cases gain less than that, or nothing.

## Where the delta is not $374.85

Measured, not assumed: a broad sweep first, then a fine probe around each kink to pin the
boundaries. Every figure here is tool output.

**The refundable cap is $1,700 per child** in 2026 ($1,700 / $3,400 / $5,100 for one, two and
three children), against a total credit of $2,200 per child. The cap, not the threshold, is
what binds for a large stretch of the earnings distribution, and it accounts for half the
zero-delta cases here.

**Bottom edge — narrower than it looks.** Because the reform sets the floor at $1 rather than
zero, the only households with no gain at the bottom are those with *no earnings at all*:
delta is 0.00 at earnings of $0 and $1, and 0.15 at earnings of $2. There is no band of
low-earning families left behind by this bill; there is a knife edge at zero. Between $2 and
$2,500 the gain is positive but partial, because current law pays nothing there while the
reform pays 15% of everything above $1.

**Top edge — a partial band before the cap.** The reform pushes a household onto the
refundable cap at lower earnings than current law does, so between those two points only part
of the $374.85 survives. Measured boundaries, with the last positive reading beside the first
zero:

| Children | Last positive delta | First zero delta |
|---|---|---|
| 1 | $13,800 -> 5.00 | $13,834 -> 0.00 |
| 2 | $25,166 -> 0.10 | $25,200 -> 0.00 |
| 3 | $36,400 -> 15.00 | $36,500 -> 0.00 |

**Partial-delta cases exist** — two structurally distinct kinds, and the corpus carries four.
Below the current-law threshold: `very_low_earnings_1kid` at $2,000 gains $299.85. Against
the cap: `near_cap_1kid`, `near_cap_2kid` and `near_cap_3kid` gain $125.00, $175.00 and
$75.00. That upper band is not a hairline — with one child the delta was still the full
$374.85 at $11,334 and had only fallen to $5.00 by $13,800; with two, still full at $22,667
and $0.10 at $25,166. A corpus sampling earnings uniformly would land in it by accident,
which is a good reason to have sampled it on purpose.

**Filing status does not enter the phase-in.** Single and married-with-a-nonworking-spouse
returned identical refundable credits at every earnings level in the phase-in range across
the whole sweep. They diverge higher up, where income-tax liability and the credit's own
income phase-out differ by filing status — which is why `at_cap_3kid_married` sits at the
$5,100 cap while a single filer at the same $45,000 has dropped to $4,452 (also zero-delta,
for reason 3 below).

**State does not move these numbers.** `refundable_ctc` was identical across TX, CA, NY, MS
and WA at both a full-delta point ($8,000, two children) and a zero-delta point ($30,000, two
children). The corpus varies `state` for surface realism only.

## The zero-delta cases and why each is zero

6 of 14 cases have a zero delta, in four distinct kinds. These are the cases that matter:
a model pattern-matching "this bill raises the refundable child credit" reports a gain on all
of them.

1. **No earned income** (`no_earnings_2kid`, $0). Both regimes phase in from a positive
   floor, so a household with no earnings clears neither. The bill's binding limitation is
   that it remains an *earnings* phase-in.
2. **At the refundable cap** (`at_cap_1kid`, `at_cap_2kid`, `at_cap_3kid_married`). Earnings
   are high enough that both regimes deliver the full $1,700 per child. Lowering the point
   where a phase-in starts cannot raise a credit that has already topped out.
3. **No refundable component at all** (`higher_earner_2kid`, $75,000 with two children). The
   household receives the entire $4,400 credit — but as a nonrefundable offset against income
   tax, so the refundable figure is $0.00 under both regimes. Conflating "the child tax
   credit" with "the refundable child tax credit" gets this one wrong in a way that reads as
   reasonable.
4. **Credit phased out on income** (`phase_out_2kid`, $250,000). The income phase-out has cut
   the total credit to $1,900 and the refundable component is $0.00 either way.

Breakdown across the corpus: **4 full ($374.85)**, **4 partial**, **6 zero**.

## Tool invocation

```
$PE_PYTHON \
  experiments/billimpact/pe_server.py
```

Newline-delimited JSON in, one JSON object per line out. Current law omits `threshold`; the
reform passes `threshold: 1`.

```json
{"earnings": 8000, "children": 2, "state": "TX", "married": false}
{"earnings": 8000, "children": 2, "state": "TX", "married": false, "threshold": 1}
```

`married: true` adds a spouse with zero employment income; children are modeled at ages 8+,
all credit-eligible. Three batches produced this corpus — a 492-call sweep (41 earnings
levels x {1,2,3} children x {single, married} x both regimes), a 90-call fine probe around
the kinks, and a 34-call final build (6 self-check + 28 for the cases). Each batch held one
warm server process open for its whole duration: the first reform-threshold request rebuilds
the tax-benefit system at ~5s and every request after costs ~0.1s, so a process per query
would have been prohibitive.

### Self-check

The three pre-verified reference cases, re-measured against the tool when this document was
generated. The corpus build aborts on any mismatch.

| Earnings | Children | Regime | Expected | Observed | Match |
|---|---|---|---|---|---|
| 8,000 | 2 | current law | 825.00 | 825.00 | yes |
| 8,000 | 2 | reform | 1,199.85 | 1,199.85 | yes |
| 3,000 | 1 | current law | 75.00 | 75.00 | yes |
| 3,000 | 1 | reform | 449.85 | 449.85 | yes |
| 20,000 | 2 | current law | 2,625.00 | 2,625.00 | yes |
| 20,000 | 2 | reform | 2,999.85 | 2,999.85 | yes |

## Schema

Top level is a bare list of case objects, matching `ground_truth.json` (the SNAP arm's
corpus) and the load in `ctc_sweep.py` (`{c["case_id"]: c for c in json.loads(...)}`).
Per-case fields `case_id`, `earnings`, `children`, `married`, `state` and
`truth.{refundable_ctc_current_law, refundable_ctc_reform, delta}` are what
`ctc_harness.run_ctc_single` reads; the rest are additive. Provenance rides inside each
record's `truth` (PolicyEngine version, parameter path, both parameter values), so a single
record is self-describing once separated from the file — the same convention
`ground_truth.json` uses for vintage.

`band` classifies each case for analysis: `full_phase_in_range`,
`partial_below_current_threshold`, `partial_reform_capped`, `zero_below_phase_in`,
`zero_at_refundable_cap`, `zero_no_refundable_component`, `zero_credit_phased_out`.

## Cases

`delta` = `refundable_ctc_reform` - `refundable_ctc_current_law`. `CTC total` is the
household's full child tax credit under current law, refundable and nonrefundable together —
included because two of the zero-delta cases are only interpretable next to it.

| case_id | Earnings | Kids | Filing | State | Refundable, current law | Refundable, reform | Delta | CTC total | Band |
|---|---|---|---|---|---|---|---|---|---|
| `no_earnings_2kid` | 0 | 2 | single | TX | 0.00 | 0.00 | **0.00** | 4,400 | zero (no earnings) |
| `very_low_earnings_1kid` | 2,000 | 1 | single | MS | 0.00 | 299.85 | **299.85** | 2,200 | partial (below current threshold) |
| `low_earnings_1kid` | 4,000 | 1 | single | OH | 225.00 | 599.85 | **374.85** | 2,200 | full |
| `phase_in_2kid` | 8,000 | 2 | single | TX | 825.00 | 1,199.85 | **374.85** | 4,400 | full |
| `phase_in_2kid_married` | 18,000 | 2 | married | GA | 2,325.00 | 2,699.85 | **374.85** | 4,400 | full |
| `phase_in_3kid` | 30,000 | 3 | single | AZ | 4,125.00 | 4,499.85 | **374.85** | 6,600 | full |
| `near_cap_1kid` | 13,000 | 1 | single | FL | 1,575.00 | 1,700.00 | **125.00** | 2,200 | partial (reform capped) |
| `near_cap_2kid` | 24,000 | 2 | single | TX | 3,225.00 | 3,400.00 | **175.00** | 4,400 | partial (reform capped) |
| `near_cap_3kid` | 36,000 | 3 | single | NC | 5,025.00 | 5,100.00 | **75.00** | 6,600 | partial (reform capped) |
| `at_cap_1kid` | 16,000 | 1 | single | PA | 1,700.00 | 1,700.00 | **0.00** | 2,200 | zero (at cap) |
| `at_cap_2kid` | 30,000 | 2 | single | CA | 3,400.00 | 3,400.00 | **0.00** | 4,400 | zero (at cap) |
| `at_cap_3kid_married` | 45,000 | 3 | married | TX | 5,100.00 | 5,100.00 | **0.00** | 6,600 | zero (at cap) |
| `higher_earner_2kid` | 75,000 | 2 | single | NY | 0.00 | 0.00 | **0.00** | 4,400 | zero (no refundable component) |
| `phase_out_2kid` | 250,000 | 2 | single | WA | 0.00 | 0.00 | **0.00** | 1,900 | zero (credit phased out) |

No case was dropped; the tool returned `ok: true` for all 28 requests behind this table.
