# Wave-2 cross-type corpus — tariffs, student-loan restart, ARPA premium tax credits

**Built:** 2026-07-31. **Status:** slices verified against fetched source text (`wave2_verify.py`,
negative-tested); ground truth resolved with first prints for all 4 scored units; 1 unit
classified dose-response-only (unscored) rather than dropped.

Adds 2 scored policy events / 4 units plus 1 unscored event, stretching the type axis beyond
the existing corpus (transfer-to-persons parameter changes + one tax-refundability parameter):
a **trade/tariff administrative action hitting a business-side tax receipt**, an
**administrative sunset** (statutorily forced termination of an executive forbearance), and a
**subsidy-parameter expansion** (premium tax credit schedule). Files:

- `corpus_wave2.json` (4 scored units) / `corpus_wave2_unscored.json` (1 unscored unit)
- `provisions_wave2.json` (verbatim slices, sha256_12 per slice)
- `ground_truth_wave2.json` (existing fetcher, unmodified)
- `bills/USTR-301-L{1,2,3}-83FR{28710,40823,47974}.txt` (Federal Register raw text, as fetched)
- `wave2_verify.py` (no-network re-verification: slices verbatim-in-source, hashes, no-lookahead)
- `wave2_sweep.py` (accuracy arms; injects wave-2 series descriptions + provisions at runtime,
  `extended_harness.py` untouched) → `runs_wave2.jsonl`

Reproduce ground truth:

```
python3 fetch_ground_truth.py --spec corpus_wave2.json --out ground_truth_wave2.json --workers 4
python3 wave2_verify.py
```

---

## 0. Method notes and environment constraints

**Legal text.** The two statutes were read from the files already on disk (`bills/FRA-2023-118publ5.txt`,
`bills/ARPA-2021-117publ2.txt`, both govinfo enrolled text). The three Federal Register notices
were fetched 2026-07-31 from the federalregister.gov API (`/api/v1/documents.json` search for
USTR notices, then each document's `raw_text_url`). All slices are cut from HTML-unescaped,
whitespace-collapsed text (`re.sub(r'\s+',' ')`, wave-1 convention) by exact marker match with
uniqueness asserted, so every quote below and every `operative` entry is byte-identical to the
normalised source. `wave2_verify.py` re-checks all six slices and hashes; it was negative-tested
(a corrupted slice makes it exit 1 on both the verbatim and hash checks).

**Series identity.** `fred.stlouisfed.org/series/<ID>` pages remain unreachable from this
environment (the wave-1 constraint persists; only the `/graph/*.csv` endpoints respond).
Identity was established the wave-1 way: (a) retrieved search results carrying the canonical
FRED/ALFRED page title against the exact `/series/<ID>` (or `alfred.../series?seid=<ID>`) URL —
both searches returned full link sets, not empty-query synthesis; (b) the event signature in the
data (below). Units/SA fields could not be read from the blocked metadata pages; magnitudes are
consistent with billions of dollars at annual rate, and — as in wave 1 — nothing depends on the
unit label because first print and history come from the same series on the same basis.

- `B235RC1Q027SBEA` → "Federal government current tax receipts: Taxes on production and imports:
  Customs duties" (fred.stlouisfed.org/series/B235RC1Q027SBEA and alfred.stlouisfed.org/series?seid=B235RC1Q027SBEA
  both in the returned result set). Quarterly, SAAR per the result snippet.
- `B069RC1` → "Personal interest payments" (fred.stlouisfed.org/series/B069RC1 and
  alfred.stlouisfed.org/series?seid=B069RC1 in the returned result set). Monthly, BEA.

**Elicitation string.** The shared `point_ci_json` instruction says `<number of persons>` — a
corpus-A artefact that every corpus-B bake-off run already carried on dollar series. It is
inherited UNCHANGED here for comparability; the task template separately states "Values are in
the same units as the history shown below."

**Quarterly series in a month-keyed pipeline.** `B235RC1Q027SBEA` observations are keyed by the
first month of their quarter, which is exactly how the ALFRED CSV emits them, so the fetcher
works unmodified. The prompt's series description states the convention explicitly ("'October
2018' is 2018Q4"). `months_back: 60` slices the last 60 *observations* (fetcher semantics), i.e.
60 quarters ≈ 15 years for this one series — row-count parity with the rest of the corpus rather
than calendar parity; the 60-row history block is the same size the other units show.

---

## 1. 2018 Section 301 China tariffs → customs duties — **KEPT** (2 units)

**Instrument.** USTR action under §§301(b), 301(c), 304(a) and 307(a)(1) of the Trade Act of
1974 (19 U.S.C. 2411(b), (c), 2414(a)) — an administrative action, not a statute; the
"provision text" is the Federal Register notices, fetched from the federalregister.gov API:

| tranche | citation | FR doc | published | operative content (verbatim in `provisions_wave2.json`) |
|---|---|---|---|---|
| List 1 | 83 FR 28710 | 2018-13248 | 2018-06-20 | 818 subheadings, ~$34B/yr, +25% ad valorem, effective July 6, 2018 |
| List 2 | 83 FR 40823 | 2018-17709 | 2018-08-16 | 279 subheadings, ~$16B/yr, +25% ad valorem, effective Aug. 23, 2018 |
| List 3 | 83 FR 47974 | 2018-20610 | 2018-09-21 | 5,745 subheadings, ~$200B/yr, +10% effective Sept. 24, 2018, "will increase to 25 percent ad valorem on January 1, 2019" as published |

Verbatim, the List 3 determination core (from §C of 83 FR 47974):

> Pursuant to Section 307(a)(1) of the Trade Act, the Trade Representative, in accordance with
> the direction of the President, has determined to modify the prior action in this
> investigation by imposing additional duties on products of China classified in the full and
> partial subheadings of the HTSUS set out in Annex A to this notice, while maintaining the
> prior action. As set out in Annex A to this notice, the rate of additional duty is initially
> 10 percent ad valorem, effective September 24, 2018. As set out in Annex B to this notice,
> the rate of additional duty will increase to 25 percent ad valorem on January 1, 2019.

And List 1 (from 83 FR 28710): "the Trade Representative determines that appropriate and
feasible action in this investigation includes the imposition of an additional ad valorem duty
of 25 percent on products of China covered in the tariff subheadings listed in Annex A to this
notice", implemented "effective July 6, 2018".

**Design: origin and scope.** Origin vintage **2018-09-22** — the day after the List 3 notice
published (Sept 21) and two days before its duties took effect (Sept 24), so the tested
instrument is strictly pre-effect. Lists 1 and 2 were already in force at origin, but the last
quarterly observation published at origin is **2018Q2 (44.634 at the 2018-09-22 vintage)**,
which ends June 30 — six days before List 1's effective date — so the published history contains
**zero tariffed quarters** and all three notices sit legitimately in the operative context with
no lookahead. This is why all three determinations are `operative` entries rather than List 3
alone: the realised target quarters carry all three tranches, and every notice predates origin.

**Stated purpose.** Unlike every wave-1 statute (all had `stated_purpose: null`), the FR notice
carries real purpose language; one sentence is captured verbatim in `stated_purpose` ("Near the
end of the one-year period of investigation, China's statements and conduct indicated that
action at a $50 billion level might not be sufficient to obtain the elimination of China's
unfair and harmful policies."). Wave-2 arms don't use it; it is there for the
operative-vs-purpose axis if this event ever joins that comparison.

**Residual scope caveat, stated loudly.** The Section 201 safeguard and Section 232
steel/aluminium tariffs (early/mid-2018 actions, separate statutes, NOT in the provision text)
were also collecting duties in the target quarters. Their effect is partially visible to both
arms in the origin history (2018Q1 41.266, 2018Q2 44.634 vs 2017Q4 39.977 at the origin
vintage), and it is identical across arms, but the operative text does not cover them: the text
arm holds the §301 instruments only. Also note the List 3 escalation to 25% was *postponed*
twice in reality and took effect May 10, 2019 — a model reading the notice as published would
expect 25% from Jan. 1, 2019. That divergence between announced schedule and realised schedule
is genuine forecast uncertainty at origin, not a corpus defect; it mainly affects the 2019Q2
unit.

**Indicator and signature.** `B235RC1Q027SBEA` runs 37-40 through 2016-2017, then 41.3 → 46.7 →
53.2 → 71.9 → 75.7 → 70.0 → 79.9 → 85.4 across 2018Q1-2019Q4 (latest vintage) — a near-doubling
concentrated exactly in the tariff quarters, which Social-Security-style transfer series cannot
produce. Signature also present in first prints (Q4-2018 first print 72.387).

| unit | target | first print | vintage | latest (2026-07-31) | revision | horizon (origin→print) |
|---|---|---|---|---|---|---|
| `tariff301.us.2018-10` | 2018Q4 | **72.387** | 2019-03-01 | 71.898 | -0.489 | ~5.3 mo |
| `tariff301.us.2019-04` | 2019Q2 | **71.536** | 2019-08-01 | 70.030 | -1.506 | ~10.3 mo |

First-print discovery is empirical (vintage walk). Note the Q4-2018 print at the 2019-03-01
probe: the advance GDP cycle that would ordinarily have printed it in late January 2019 was
delayed by the December 2018-January 2019 appropriations lapse; the value first appears at the
March-1 probe (walk table in `ground_truth_wave2.json` — vintage 2019-02-01 absent,
2019-03-01 present). BEA quarterly revisions here are small (-0.5, -1.5) compared to the
monthly BEA units below.

History at origin: 60 quarterly observations, 2003Q3-2018Q2, at the 2018-09-22 vintage.

---

## 2. FRA 2023 §271 student-loan payment restart → personal interest payments — **KEPT** (2 units)

**The brief said "§320" — the enrolled law has no §320.** `bills/FRA-2023-118publ5.txt`
contains sections ...270, **271**, then Division C; the only "320" strings in the act are
cross-references to "section 3207(a)" / "section 3208(a)" of Pub. L. 117-2 inside the
rescissions list. The student-loan provision is **Pub. L. 118-5, div. B, tit. IV, §271** —
"TERMINATION OF SUSPENSION OF PAYMENTS ON FEDERAL STUDENT LOANS; RESUMPTION OF ACCRUAL OF
INTEREST AND COLLECTIONS" (title heading = the whole of title IV). Verbatim, the operative core:

> (a) <<NOTE: Time period.>> In General.--Sixty days after June 30, 2023, the waivers and
> modifications described in subsection (c) shall cease to be effective. (b) Prohibition.--
> Except as expressly authorized by an Act of Congress enacted after the date of enactment of
> this Act, the Secretary of Education may not use any authority to implement an extension of
> any executive action or rule specified in subsection (c).

Subsection (c) identifies the terminated waivers as those "relating to an extension of the
suspension of payments on certain loans and waivers of interest on such loans under section
3513 of the CARES Act (20 U.S.C. 1001 note)" as described in 87 Fed. Reg. 61513 (Oct. 12, 2022)
and last extended Nov. 22, 2022. Type: **administrative sunset** — a statute forcing an
executive forbearance to terminate on a date certain (Aug. 29, 2023) and barring re-extension.

**Indicator choice.** `B069RC1` — "Personal interest payments" (BEA, monthly). Mechanism match
is documented by BEA itself: FAQ 1407 ("How did provisions of the 2020 Coronavirus Aid, Relief,
and Economic Security Act (CARES) Act related to student loan debt affect BEA's estimates of
personal interest payments?", https://www.bea.gov/help/faq/1407) states that "the student loan
forbearance program concluded on August 31, 2023, after which interest accruals resumed. BEA
ceased implementing a downward adjustment to personal interest payments beginning with
estimates for September 2023." So the §271 sunset enters this exact series, in the exact target
month, by the agency's own account.

**Signature — in the first print, not just today's vintage.** At the first-print vintage
(2023-11-01): July +2.5, August +1.3, **September +36.0** (503.6 → 539.6) — the discontinuity
is in the print being scored. At today's vintage the step reads +46.2 (515.7 → 561.9).

**Rejected indicator, reported loudly:** `SLOAS` ("Student Loans Owned and Securitized",
quarterly) was probed and rejected. Its 2023Q4 change (-3.4) is indistinguishable from ordinary
quarters (2021Q4 -6.0, 2020Q4 -2.6), while its big 2023 moves (Q2 -13.7, Q3 -28.7) are timed
with the mid-2023 IDR-adjustment discharge waves — a different policy — so the restart signature
fails the identification bar there. G.19 owner-component monthly series were not pursued after
`B069RC1` passed both title and signature checks with a BEA-documented mechanism.

**Honest caveats.** (1) Student-loan interest is one component inside a larger household
interest aggregate (BEA FAQ 1407 describes a student-loan *adjustment within* personal interest
payments, not a student-loan series), and the series climbed steeply through 2022 (278.5 →
421.2 at today's vintage) while student-loan interest was waived the whole year — so a strong
non-policy trend (the rate environment) drives what both arms see, and the policy step rides
on it. (I did not verify the series' exact NIPA definitional boundary — e.g. mortgage
treatment — from a primary source this session; nothing here depends on it.) (2) The September 2023
annual NIPA update shifted the level basis down between origin and first print (March 2023 reads
455.1 at the origin vintage but 424.7 at the 2023-11-01 vintage), which happens to offset a
large part of the +36 policy step relative to a naive continuation from the origin-basis
history: a drift forecast from origin lands near the first print by this coincidence of
opposing effects. Both arms face identical conditions, and first-print resolution is the
protocol, but this unit is a weaker discriminator between arms than its clean mechanism
suggests. (3) Revisions are enormous and two-signed: Sept-2023 first print 539.6 → 561.9 today
(+22.3); Dec-2023 first print 564.2 → 519.1 today (**-45.1**). First-print resolution genuinely
binds.

| unit | target | first print | vintage | latest (2026-07-31) | revision | horizon (origin→print) |
|---|---|---|---|---|---|---|
| `loanrestart.us.2023-09` | 2023-09 | **539.6** | 2023-11-01 | 561.9 | +22.3 | ~5.2 mo |
| `loanrestart.us.2023-12` | 2023-12 | **564.2** | 2024-02-01 | 519.1 | -45.1 | ~8.2 mo |

Origin vintage **2023-05-25** (nine days before enactment, June 3, 2023 — same
just-before-enactment convention as wave 1's vetcola/fpuc units); history 2018-04 … 2023-03,
60 months, ending 455.1. Lag-2 publication (observation month M first present at the M+2
probe), consistent with the other monthly BEA series in the corpus.

---

## 3. ARPA §9661/§9662 premium tax credit expansion → marketplace enrollment —
**DOSE-RESPONSE-ONLY (unscored)**, not dropped

**Law.** American Rescue Plan Act of 2021, Pub. L. 117-2 (approved March 11, 2021), tit. IX,
subtit. G ("Promoting Economic Security"), pt. 7 ("PREMIUM TAX CREDIT"), §§9661-9662. Enrolled
text on disk (`bills/ARPA-2021-117publ2.txt`); §9661 spans 135 Stat. 182-183 by the text's own
page markers. Verbatim core of §9661 (full slice in `provisions_wave2.json`):

> ``(iii) Temporary percentages for 2021 and 2022.--In the case of a taxable year beginning in
> 2021 or 2022-- ``(I) clause (ii) shall not apply for purposes of adjusting premium
> percentages under this subparagraph, and ``(II) <<NOTE: Applicability.>> the following table
> shall be applied in lieu of the table contained in clause (i):

with the substituted applicable-percentage table running 0.0/0.0 ("Up to 150.0 percent") to
8.5/8.5 ("400.0 percent and higher"), and §9661(b) applying §36B(c)(1)(A) "without regard to
`but does not exceed 400 percent'" — the subsidy cliff removal — effective (per §9661(c)) "to
taxable years beginning after December 31, 2020". §9662 (ancillary slice) suspends the
§36B(f)(2)(B) repayment limitation for taxable year 2020.

**Why unscored.** The natural indicator is CMS Health Insurance Marketplace **effectuated
enrollment**. Two searches (one site-restricted to fred.stlouisfed.org) surfaced no
FRED/ALFRED-mirrored series for it — every returned link is a CMS snapshot product
("Quarterly Marketplace Effectuated Enrollment Snapshots by State", cms.gov fact sheets).
CMS publishes these as point-in-time reports, not as a vintage-archived series the house
ALFRED walker can resolve, so **no candidate passes the first-print bar**. Per the wave-2
brief, the unit is classified **dose-response-only (unscored)** in
`corpus_wave2_unscored.json` (provision text fully archived and hashed; `series_id: null`;
no fabricated resolution values anywhere) rather than silently dropped. A future
dose-response arm can perturb the §9661 table (e.g. the 8.5% cap) without needing first-print
resolution; scored use would require building a CMS-snapshot resolution path, which is outside
the ALFRED pipeline.

---

## 4. Accuracy arms on the survivors (`wave2_sweep.py` → `runs_wave2.jsonl`)

4 units × claude-opus-5 × {none, operative_only} × point_ci_json × 5 reps, plus
operative_only × decomposed_json × 5 reps — 60 runs, record schema identical to
`runs_bakeoff.jsonl` (config `corpus: "B2"`, `cell_key` prefix `W2`, truth = first print).
Series descriptions and wave-2 provisions are injected into `extended_harness` dicts at
runtime by the runner; no existing file was modified.

**BLOCKED 2026-07-31 ~16:20 UTC — workspace API quota exhausted.** All 60 calls returned
`HTTP 400: "You have reached your specified workspace API usage limits. You will regain
access on 2026-08-01 at 00:00 UTC."` (same ~/.env key that completed the corpus-B bake-off
earlier today; no env-var key shadowing — verified). The all-errored `runs_wave2.jsonl` was
archived out of the repo (scratchpad, `runs_wave2.QUOTA-ERRORED.jsonl`) so the resume logic
starts clean, and `wave2_sweep.py`'s resume filter now ignores errored records in any case.
**Rerun after the reset with:** `python3 wave2_sweep.py` (resume-safe), then score. No wave-2
model-arm numbers exist yet; nothing below substitutes for them.

**Mechanical baselines (no LLM — these DID run):** `wave2_baselines.py` →
`baselines_wave2.json`, same persistence/drift construction as `baselines.py` with the horizon
expressed in native observation steps (quarterly h = month-gap/3; the month-count convention
would have applied 6 quarters of drift to a 2-quarter horizon). nCRPS = CRPS / pstdev(history),
the `analyze_final.py` convention:

| unit | h (obs) | persistence nCRPS | drift nCRPS |
|---|---|---|---|
| `tariff301.us.2018-10` | 2 | 4.385 | 4.254 |
| `tariff301.us.2019-04` | 4 | 4.080 | 3.817 |
| `loanrestart.us.2023-09` | 6 | 1.029 | 0.789 |
| `loanrestart.us.2023-12` | 9 | 1.397 | 1.040 |

Read: the tariff units are far outside mechanical reach (the ~+28 SAAR step above a ~40-45
baseline is invisible to extrapolation) — exactly where provision text has headroom to show
value. The loanrestart units sit near mechanical reach because the Sept-2023 basis revision
happens to offset much of the policy step (§2 caveat 2), so expect compressed arm separation
there.
