# Cross-type corpus extension — three bill types the corpus did not cover

**Built:** 2026-07-31. **Status:** verified against fetched statutory text; ground truth
resolved for all scoreable units. Implements IDEATION.md §1.4 items 1–3.

Adds 3 policy events / 6 units across three previously uncovered bill TYPES:
tax-parameter-with-advance-payment (ARPA §9611), appropriations (IIJA div. J), and
program creation (IIJA §60502). Four units are accuracy-scoreable; two (ACP) are
**dose-response-only** — reclassified, not dropped, for the reason in §3. Files:
`corpus_crosstype.json` (units), `provisions_crosstype.json` (verbatim slices),
`ground_truth_crosstype.json` (fetcher output), `bills/IIJA-2021-117publ58.txt`
(newly fetched law text; ARPA and CAA-2021 texts were already on disk).

Reproduce with the existing fetcher, unmodified (the spec filter drops the two
units that have no FRED series — see §3):

```
python3 -c "import json; json.dump([u for u in json.load(open('corpus_crosstype.json')) if u.get('series_id')], open('/tmp/crosstype_spec.json','w'))"
python3 fetch_ground_truth.py --spec /tmp/crosstype_spec.json --out ground_truth_crosstype.json --workers 4
```

---

## 0. Method, and the same environment constraint as before

**Statutory text.** Same convention as CORPUS_EXTRA_NOTES §0: govinfo HTML
(`https://www.govinfo.gov/content/pkg/PLAW-<congress>publ<num>/html/…`), tag-stripped,
HTML-unescaped, whitespace-normalised (`re.sub(r'\s+',' ',t)`) before any phrase search,
because govinfo hard-wraps at ~72 characters. Every quote below and every slice in
`provisions_crosstype.json` is byte-identical to the normalised text of the named file,
editorial markers (`<<NOTE: …>>`, `[[Page 135 STAT. …]]`) retained. The build script
asserted, for all 15 slices: (a) the slice re-locates verbatim in the normalised source,
and (b) a single-character mutation of it does **not** (negative test, so the check has
been seen red). No statutory claim below is from memory.

**Series identity.** The FRED constraint documented in CORPUS_EXTRA_NOTES §0 still holds:
every `fred.stlouisfed.org` path except `/graph/*.csv` hangs from this environment
(re-confirmed today: a direct `fredgraph.csv?id=TLHWYCONS` read timed out at 45 s while
`alfred.stlouisfed.org/graph/alfredgraph.csv` answered in under a second), so `og:title`
cannot be read directly. Identity was established the same three ways as before, and all
three agree per series:

1. **Retrieved search results carrying the canonical FRED page title against the exact
   `/series/<ID>` URL** (each query returned a real, non-empty link set):
   - `W827RC1` → "Personal current transfer receipts: Government social benefits to
     persons: Other" — this closes the one gap CORPUS_EXTRA_NOTES §0 left open (`W827RC1`
     had entered the adding-up check there only as an unnamed addend).
   - `PBHWYCONS` → "Total Public Construction Spending: Highway and Street in the United
     States" (U.S. Census Bureau).
   - `TLHWYCONS` → "Total Construction Spending: Highway and Street in the United States"
     (fetched and verified as the total-scope alternative; not used as a unit indicator —
     see §2).
2. **Structural cross-checks in the data.** `PBHWYCONS ≤ TLHWYCONS` in every month
   checked, with the gap (private highway construction) under 1.5% of the total —
   consistent with public vs total scope of one Census VIP table. `W827RC1` was already
   pinned as a component of the `A063RC1` adding-up identity in CORPUS_EXTRA_NOTES §0.
3. **Event signatures** (§1, §2 below): the March-2021 EIP spike and the July-2021 step
   in `W827RC1`; scale and post-2022 ramp in `PBHWYCONS`.

**Unverified residue, stated:** units and seasonal-adjustment basis come from the search
result snippets (secondary), not from a fetched FRED metadata page — "millions of dollars,
seasonally adjusted annual rate, monthly" for the construction pair; BEA monthly since 1959
for `W827RC1`. As before, this does not affect the backtest: first print and realised value
are read from the same series on the same basis.

**Publication lag.** All 4 scoreable units print at **lag 2** (observation absent at the
*M*+1 vintage, present at *M*+2 — visible in each unit's `vintage_trail` in
`ground_truth_crosstype.json`), matching the four BEA series in the first extension.

---

## 1. ARPA §9611 — 2021 CTC expansion + advance monthly payments — **KEPT**

Type: **tax-parameter change with an advance-payment delivery mechanism** — the demo
bill's (S.3596) own statute family, retrospective.

**Law.** American Rescue Plan Act of 2021, Pub. L. 117-2, tit. IX, subtit. G
(Promoting Economic Security), pt. 2 (Child Tax Credit), §9611, 135 Stat. 144
(approved March 11, 2021 — "Approved March 11, 2021." is on the face of the fetched text).
IDEATION's "(verify section)" flag resolves TRUE: §9611 is the right section.
**Source.** https://www.govinfo.gov/content/pkg/PLAW-117publ2/html/PLAW-117publ2.htm
**Text file.** `bills/ARPA-2021-117publ2.txt` (already in the repo)

Verbatim, the credit parameters (§9611(a), adding IRC §24(i)(3)):

> ``(3) Credit amount.--Subsection (h)(2) shall not apply and subsection (a) shall be
> applied by substituting `$3,000 ($3,600 in the case of a qualifying child who has not
> attained age 6 as of the close of the calendar year in which the taxable year of the
> taxpayer begins)' for `$1,000'.

Verbatim, the advance-payment program (§9611(b)(1), adding IRC §7527A(a)):

> ``(a) <<NOTE: Determination.>> In General.--The Secretary shall establish a program for
> making periodic payments to taxpayers which, in the aggregate during any calendar year,
> equal the annual advance amount determined with respect to such taxpayer for such
> calendar year. Except as provided in subsection (b)(3)(B), the periodic payments made to
> any taxpayer for any calendar year shall be in equal amounts.

— where the annual advance amount is "50 percent of the amount which would be treated as
allowed" (§7527A(b)(1)), and the payment window is hard-dated (§7527A(f)):

> ``(f) <<NOTE: Time periods.>> Application.--No payments shall be made under the program
> established under subsection (a) with respect to-- ``(1) any period before July 1, 2021,
> or ``(2) any period after December 31, 2021.

So the statute itself specifies the pulse the indicator must show: equal periodic payments,
half the credit, inside July–December 2021 only.

**Indicator.** `W827RC1` — "Personal current transfer receipts: Government social benefits
to persons: Other" (title verification in §0). Three independent confirmations that this
series carries the advance-CTC pulse:

1. **BEA's own classification statement.** BEA FAQ 1465 ("How does the Child Tax Credit
   provision of the American Rescue Plan Act of 2021 impact the NIPAs?",
   https://www.bea.gov/help/faq/1465, fetched 2026-07-31): "Refundable income tax credits
   are classified as government social benefits to persons"; "Prepaid refundable tax
   credits are recorded as government social benefits in the months in which they are
   paid"; recorded "in July 2021 through December 2021 based on data from the Department
   of Treasury's Monthly Treasury Statement". The FAQ also states the remainder claimed at
   2022 filing "will be allocated evenly across the 12 months of calendar year 2022" —
   which is why the series does NOT fall by the full pulse height in January 2022, a fact
   a forecaster of the 2021-12 unit's successor months would need.
2. **Event signature, first-print space.** At the 2021-09-01 vintage (the July
   observation's own first print): 2021-06 = 735.6 → 2021-07 = 907.1, a +171.5 step
   landing exactly at the statutory window opening; the plateau holds through 2021-12 and
   decays (not cliffs — see 1. above) in 2022-01. Nothing else in the statute book opens
   on July 1, 2021 and closes on December 31, 2021 at this scale, and BEA's FAQ names the
   payments and the category.
3. **Same-series EIP signature.** 2021-03 = 4,734.5 at today's vintage vs 763.4 in
   2021-06 — the third Economic Impact Payment, ARPA §9601, paid March–April 2021. The
   provisions file records §9601's operative amount verbatim as
   `context_same_bill_series_confound` because it sits between origin and target: the
   forecaster reads one bill carrying both a giant one-shot pulse (§9601) and the
   six-month advance-CTC pulse (§9611) landing in the same series.

**No dedicated line-item alternative exists on FRED:** the Monthly Treasury Statement
release on FRED carries 6 aggregate series only (total receipts/outlays/deficit family —
searched 2026-07-31), and no IRS/Treasury advance-CTC monthly series is mirrored. `W827RC1`
is the only FRED/ALFRED-vintaged monthly series carrying the pulse, and per BEA FAQ 1465 it
is itself built from the MTS for these months — so the "Treasury MTS or BEA" fork in the
brief collapses to one answer.

| unit | target | first print | vintage | latest (2026-07-31) | revision | horizon |
|---|---|---|---|---|---|---|
| `ctcadv.us.2021-07` | 2021-07 | **907.1** | 2021-09-01 | 932.5 | +25.4 | **6 mo** |
| `ctcadv.us.2021-12` | 2021-12 | **916.6** | 2022-02-01 | 907.5 | −9.1 | **11 mo** |

Origin vintage 2021-03-01 (10 days before enactment); history 2016-02 … 2021-01, 60 months.
The last visible observation is itself a payment spike: 2021-01 = 2,336.9 at the origin
vintage, immediately following the $600-per-person additional 2020 recovery rebates enacted
December 27, 2020 (CAA-2021, div. N, §272 — "``(1) $600 ( $1,200 in the case of eligible
individuals filing a joint return), plus ``(2) an amount equal to the product of $600
multiplied by the number of qualifying children", verified in the fetched
`bills/CAA-2021-116publ260.txt`). Informative precedent for what a payment pulse looks
like in this series, without leaking anything post-origin.

Recall-anchoring note (IDEATION §1.3 called this "the maximal recall-anchoring stress
test"): the advance CTC is probably the most-reported transfer of 2021 H2; the A5
future-move protocol applies unchanged (relocate the window, watch the dose-response).

---

## 2. IIJA div. J — Highway Infrastructure Programs appropriation — **KEPT**

Type: **appropriation, agency-paced outlays** — first unit in the corpus whose primary
effect is NOT a transfer to persons and has no persons-side series.

**Law.** Infrastructure Investment and Jobs Act, Pub. L. 117-58, div. J (whose own enrolled
note reads "Infrastructure Investments and Jobs Appropriations Act" — note the extra "s",
verbatim in both places), tit. VIII (Transportation, Housing and Urban Development, and
Related Agencies), Federal Highway Administration — highway infrastructure program heading,
135 Stat. 1419–1421 (approved November 15, 2021 — "Approved November 15, 2021." on the face
of the text). IDEATION's "(verify division/section)" resolves TRUE for div. J.
**Source.** https://www.govinfo.gov/content/pkg/PLAW-117publ58/html/PLAW-117publ58.htm
**Text file.** `bills/IIJA-2021-117publ58.txt` (fetched today, 3.84 MB HTML → stripped)

Verbatim, the dated appropriation (heading text):

> For an additional amount for ``Highway Infrastructure Programs'', $47,272,000,000, to
> remain available until expended except as otherwise provided under this heading:
> Provided, That of the amount provided under this heading in this Act, $9,454,400,000, to
> remain available until September 30, 2025, shall be made available for fiscal year 2022,
> $9,454,400,000, to remain available until September 30, 2026, shall be made available for
> fiscal year 2023, …

— five equal tranches of $9,454,400,000 for fiscal years 2022–2026 (5 × 9,454.4M =
47,272M exactly), general-fund derivation, additionality ("shall be in addition to any
other amounts made available for such purpose"), and — directly relevant to outlay pacing —
exemption from obligation limitations ("shall not be subject to any limitation on
obligations for Federal-aid highways … set forth in any Act making annual appropriations").
The sliced provision runs through the end of paragraph (1), the $27,500,000,000 bridge
program. The heading's nine enumerated set-asides sum to **exactly $47,272,000,000** — an
internal consistency check run on the fetched text (see the de-duplication caveat below).

**A govinfo rendering artifact, documented so nobody trips on it:** the HTML edition of
this law repeats a ~4,150-character stretch of this very heading once (tail of paragraph
(1) + opening of paragraph (2), spanning the page break at `[[Page 135 STAT. 1422]]`,
which is the only page marker appearing twice in the entire file; the copies differ only
by hard-wrap artifacts like "federally- recognized"). No slice includes the repeated copy.
A naive enumeration scan double-counts the $5,000,000,000 EV paragraph and gets
52,272,000,000; de-duplicated, the sum closes exactly.

**Indicator.** `PBHWYCONS` — "Total Public Construction Spending: Highway and Street in
the United States" (Census Value of Construction Put in Place, public scope; title
verification in §0). Chosen over `TLHWYCONS` (total scope, also verified and first-print
recoverable: 2022-06 first-prints 98,026 @ 2022-08-01) because div. J money is public
spending and the public series exists with identical vintage behaviour; the two differ by
under 1.5% (private highway construction).

Honest indicator caveat, stated up front rather than discovered on stage: VIP measures
**construction put in place** — activity value including state/local and pre-IIJA federal
money — not federal obligations or outlays. There is no arithmetic identity from the
appropriation to the monthly series; the chain runs through agency apportionment,
obligation, letting, and construction seasons. That is precisely why IDEATION §1.3
registered the prediction that directed-derivation rescue **fails** on this type; this
unit is the instrument for that bet, and the indicator's distance from the statute is the
design, not a defect.

| unit | target | first print | vintage | latest (2026-07-31) | revision | horizon |
|---|---|---|---|---|---|---|
| `iijahwy.us.2022-06` | 2022-06 | **97,403** | 2022-08-01 | 109,786 | +12,383 (+12.7%) | **9 mo** |
| `iijahwy.us.2022-12` | 2022-12 | **117,290** | 2023-02-01 | 122,108 | +4,818 (+4.1%) | **15 mo** |

Origin vintage 2021-11-01 (14 days before enactment); history 2016-10 … 2021-09, 60 months
(2021-09 = 99,806 at the origin vintage). The +12.7% revision on the June-2022 print is
the largest relative revision in either extension — the "heavily revised" property IDEATION
flagged for this family, and the reason first-print resolution is load-bearing here.
15 months is the longest horizon in the corpus (previous max: 14, `medicaid.us.2023-12`),
chosen deliberately: appropriations ramp slowly, and a 9-month target that mostly
pre-dates the ramp plus a 15-month target inside it bracket the pacing question.

---

## 3. IIJA §60502 — Affordable Connectivity Program — **RECLASSIFIED, not dropped: dose-response arms only**

Type: **program creation / conversion, empty-history regime.**

**Law.** Pub. L. 117-58, div. F (Broadband), tit. V (Broadband Affordability), §60502,
135 Stat. 1238; companion appropriation in div. J, tit. IV, Federal Communications
Commission — Affordable Connectivity Fund, 135 Stat. 1382. IDEATION's "§60502 (verify)"
resolves TRUE.
**Source.** https://www.govinfo.gov/content/pkg/PLAW-117publ58/html/PLAW-117publ58.htm

Verbatim, the conversion (§60502(a)(1)–(2)): §904 of div. N of CAA-2021 "is amended-- (A)
in the heading, by striking ``during emergency period relating to covid-19''" and — the
rename — "(D) by striking ``Emergency Broadband Benefit'' each place the term appears and
inserting ``Affordable Connectivity''". Verbatim, the benefit parameter and its date
(§60502(b)(1)):

> (b) Delayed Amendments to Affordable Connectivity Program.-- (1) <<NOTE: Effective
> date.>> In general.--Effective on the date on which the Commission submits the
> certification required under paragraph (4), or December 31, 2021, whichever is earlier,
> section 904 … is amended-- …

> (II) by striking ``$50'' and inserting ``$30'';

— against the pre-amendment definition, quoted in the provisions file from the fetched
CAA-2021 text ("…but not more than $50, or, if an internet service offering is provided to
an eligible household on Tribal land, not more than $75"). Verbatim, the money (div. J,
tit. IV):

> For an additional amount for the ``Affordable Connectivity Fund'', $14,200,000,000, to
> remain available until expended, for the Affordable Connectivity Program, as authorized
> under section 904(b)(1) of division N of the Consolidated Appropriations Act, 2021
> (Public Law 116-260), as amended by section 60502 of division F of this Act

**Indicator, and why this unit cannot be scored.** Checked empirically 2026-07-31:

- **No FRED/ALFRED mirror of ACP enrollment exists.** Searches for an ACP/EBB enrollment
  series return no FRED series; FRED's Monthly Treasury Statement release carries 6
  aggregate series; a deliberately-invalid id probe confirms missing series 404 cleanly,
  so absence of a hit is absence of a series, not a transport failure.
- **USAC is the only source**: the ACP Enrollment and Claims Tracker
  (https://www.usac.org/about/affordable-connectivity-program/acp-enrollment-and-claims-tracker/,
  fetched 2026-07-31) publishes national weekly enrollment snapshots covering 2022-01-03
  through the 2024-02-08 enrollment freeze (23,269,550 total households at the freeze, per
  the page as published today), plus monthly zip-code and quarterly county files.
- **But it has no vintage archive.** The page carries a single current publication
  vintage — "All claims data is as of 8/1/2024" — and no archive of previously published
  versions. Whether any given week's enrollment figure was later restated is not
  recoverable, so the first-print recoverability test that gates the accuracy arms
  **cannot be run**, and per the brief's own decision rule the unit is classified
  **dose-response-only (no scoring)** rather than dropped: dose-response arms measure the
  spread of forecasts under statutory-parameter rewrites ($30 → other values, window moves)
  and need no realised truth.

The two `acp.us.*` rows in `corpus_crosstype.json` therefore carry `"series_id": null`,
`"regime": "dose_response_only"`, `"scoring_eligible": false`, and an `exclusion_reason`
string, and are excluded from the fetcher spec (the reproduce command's filter). Any
downstream consumer that iterates the corpus must respect `scoring_eligible` — the null
`series_id` is deliberate so that feeding these rows to the fetcher fails loudly rather
than fabricating a resolution.

Empty-history note: the program §60502 creates is a conversion of the EBB, the
differently-parameterised ($50) predecessor established by CAA-2021 div. N §904 (approved
December 27, 2020); ACP-as-such has no pre-origin series. The provisions file carries the
pre-amendment §904(a)(7) definition so the dose arms can move a parameter against its true
baseline.

---

## 4. Operative vs stated purpose

| event | `FINDINGS` | `PURPOSE` | `SENSE OF CONGRESS` | scanned scope |
|---|---|---|---|---|
| PL 117-2 §9611 | 0 | 1* | 0 | all of tit. IX subtit. G (chars 384022–524602 of the normalised law) |
| PL 117-58 div. J tit. VIII | 0 | 0 | 0 | whole title (chars 2702121–2807081) |
| PL 117-58 div. F tit. V | 0 | 0 | 0 | whole title (chars 2188347–2220896) |

\* the one hit is the §9626 heading "…FOR PURPOSES OF EARNED INCOME TAX CREDIT" — a
purposes-of phrase, not a purpose clause. So ARPA §9611 and the div. J appropriation add
two more verified nulls to CORPUS_EXTRA_NOTES §5's table, and the purpose-clause ablation
stays anchored on FRA §313 — with one genuine addition: **div. F opens with a real findings
section**, §60101 (codified 47 U.S.C. 1701, "Congress finds the following: (1) Access to
affordable, reliable, high-speed broadband is essential to full participation in modern
life in the United States. …"), recorded as the ACP event's `stated_purpose` with an
explicit placement caveat (it sits in tit. I, is division-level, and attaches to no
specific section of tit. V). It is the first stated-purpose text in the corpus that is
real rather than absent; treat it as division-level findings, never as a §60502 purpose
clause.

---

## 5. Provision hashes

`sha256[:12]` of each normalised slice, matching the PREREGISTRATION.md convention:

| event | slice | role | sha256[:12] |
|---|---|---|---|
| PL 117-2 §9611 | §9611(a) credit parameters | operative | `a05e752ac0a2` |
| PL 117-2 §9611 | §9611(b)(1) advance program (IRC §7527A) | operative | `0bd4a5a733cd` |
| PL 117-2 §9611 | §9611(b)(2) reconciliation (IRC §24(j)) | operative | `9296eb9906d2` |
| PL 117-2 §9611 | §9611(c) effective date | operative | `a9223687b5db` |
| PL 117-58 div. J | FHWA Highway Infrastructure Programs appropriation | operative | `e0c5f57a1d93` |
| PL 117-58 §60502 | (a)(1)–(2) extension + rename | operative | `975990bea3f5` |
| PL 117-58 §60502 | (b)(1) delayed amendments incl. $50→$30 | operative | `d2e38b769ee8` |
| PL 117-58 §60502 | (b)(3) transition | operative | `d7e833106e4d` |
| PL 117-58 div. J | FCC Affordable Connectivity Fund appropriation | operative | `1f1e4dcf48c2` |
| PL 117-58 §60101 | div. F findings | stated purpose (division-level) | `db1cf7ddd7a0` |

---

## 6. What was dropped, what nearly went wrong, and residue

**(a) Nothing was dropped outright.** All three IDEATION candidates survived verification;
every "(verify)" flag resolved to the proposed identifier being correct (§9611, div. J,
§60502 — for once, recall was right, and now it is also checked). The one classification
change: **the ACP unit is excluded from the accuracy arms** — exact reason in §3 (USAC
publishes at a single current vintage; first-print recoverability untestable). That is a
scoring-eligibility drop and it is loud: `scoring_eligible: false` on both rows.

**(b) The govinfo duplication artifact (§2)** would have silently corrupted any
"enumerated amounts sum to the total" check (52,272 vs 47,272) — caught because the
consistency check was asserted, failed, and was investigated rather than papered over. The
duplicated stretch is excluded from all slices.

**(c) TLHWYCONS was verified but not used** (total scope; `PBHWYCONS` is the public-scope
series matching a federal appropriation). Recorded so the next session doesn't re-derive
the choice.

**(d) Residue.** (i) Units/SA basis for all three series read from search snippets, not
FRED metadata (blocked) — same standing caveat as CORPUS_EXTRA_NOTES §0. (ii) The EBB
predecessor series (USAC EBB tracker) was not ingested; if a dose arm ever wants the
$50-era baseline it needs the same direct-ingestion decision as ACP. (iii) The advance-CTC
pulse in `W827RC1` is not isolatable from whatever else moves the "other" component in
those months — the unit forecasts the series level, as every corpus unit does; nothing
here claims component attribution beyond BEA's own FAQ statement.

---

## 7. No-lookahead verification

Checked programmatically over `ground_truth_crosstype.json`: for every unit, no history
row is at or after the target month, and every history ends at or before its declared
`history_through`. Origins are strictly pre-enactment in all three events (10–14 days
before), so the forecaster is conditioned on a bill it can read but on no data that
reflects it. First prints are all lag-2 (absent at *M*+1, present at *M*+2, per the
stored `vintage_trail`).

| unit | origin vintage | last history obs | target | horizon |
|---|---|---|---|---|
| `ctcadv.us.2021-07` | 2021-03-01 | 2021-01-01 | 2021-07-01 | 6 |
| `ctcadv.us.2021-12` | 2021-03-01 | 2021-01-01 | 2021-12-01 | 11 |
| `iijahwy.us.2022-06` | 2021-11-01 | 2021-09-01 | 2022-06-01 | 9 |
| `iijahwy.us.2022-12` | 2021-11-01 | 2021-09-01 | 2022-12-01 | 15 |
| `acp.us.2022-06` | 2021-11-01 | — (no vintaged series; dose-response only) | 2022-06-01 | — |
| `acp.us.2022-12` | 2021-11-01 | — (no vintaged series; dose-response only) | 2022-12-01 | — |

Horizon is counted from the last observation the forecaster can see to the target month,
the same convention as the base corpus.

With §1–§2 landed as scoreable units and §3 as dose-response substrate, the corpus's honest
scope statement upgrades from "five transfer programs read through persons-side series" to
"transfer, tax-credit-with-advance-delivery, appropriations, and program-creation types" —
regulatory mandates and reporting duties remain named exclusions (IDEATION §1.2).
