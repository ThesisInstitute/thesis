# Corpus extension — four additional policy events

**Built:** 2026-07-31. **Status:** verified against fetched statutory text; ground truth resolved.

Adds 4 policy events / 8 units to the 1 event / 12 units in `corpus_spec.json`. Nothing
here touches the existing SNAP/FRA corpus. Files: `corpus_extra.json` (units),
`ground_truth_extra.json` (fetcher output), `provisions_extra.json` (verbatim slices),
`bills/*.txt` (fetched law text).

Reproduce with the existing fetcher, unmodified:

```
python3 fetch_ground_truth.py --spec corpus_extra.json --out ground_truth_extra.json --workers 4
```

---

## 0. Method and one environment constraint you need to know about

**Statutory text.** Every law was pulled from govinfo
(`https://www.govinfo.gov/content/pkg/PLAW-<congress>publ<num>/html/PLAW-<congress>publ<num>.htm`),
HTML-stripped, HTML-unescaped, and whitespace-normalised (`re.sub(r'\s+',' ',t)`) *before*
any phrase search — govinfo hard-wraps at ~72 characters, so multi-word phrases do not match
raw. Every block quote below is byte-identical to the normalised source text, including
govinfo's own editorial markers (`<<NOTE: …>>`, `[[Page 134 STAT. 209]]`); they are retained
rather than tidied away so the quotes can be grep-verified against `bills/*.txt`. A machine
check of all ten quotes against the fetched files is the last thing run before this file
ships. The slices in `provisions_extra.json` are cut from the normalised text by exact index,
so they are verbatim modulo that whitespace collapse and HTML unescaping. No claim below is
made from memory; each is quoted from the file named beside it.

**Indicator identification — and what could not be done here.** The brief specifies
confirming each series id by fetching `https://fred.stlouisfed.org/series/<ID>` and reading
the `og:title` meta tag. **That is not possible from this environment.** Every
`fred.stlouisfed.org` and `alfred.stlouisfed.org` path *except* `/graph/*.csv` hangs and
times out (tested: `/series/<ID>`, `/data/<ID>.txt`, `/graph/*.xls`, `/graph/*.png`,
`/search`, at 25s/40s/110s timeouts, with browser and plain user agents, both inside and
outside the command sandbox). `WebFetch` on the same URL returns HTTP 403. Only the CSV
graph endpoint — the one the fetcher already uses — responds. Series identity was therefore
established three other ways, all of which agree:

1. **Retrieved search results** carrying the canonical FRED page title against the exact
   `/series/<ID>` URL (10 links returned, so the result set is real, not empty-query
   synthesis). Every id used as a unit indicator was confirmed this way:
   - `W823RC1` → "Personal current transfer receipts: Government social benefits to persons: Social security"
   - `W729RC1` → "Personal current transfer receipts: Government social benefits to persons: Medicaid"
   - `W825RC1` → "Personal current transfer receipts: Government social benefits to persons: Unemployment insurance"
   - `W826RC1` → "Personal current transfer receipts: Government social benefits to persons: Veterans' benefits"
   - `A063RC1` → "Personal current transfer receipts: Government social benefits to persons" (the aggregate, used only for the check below)
2. **Adding-up identity.** Six component series sum to `A063RC1` to within 0.1 in every month
   checked — 2019-06, 2021-01, 2023-06, 2024-06, 2025-03 — which pins them as the components
   of one NIPA table rather than six unrelated series. Two of the six, `W824RC1` and
   `W827RC1`, did **not** come back in the search result set, so their titles are *not*
   confirmed and are not asserted here; they enter only as unnamed addends. Neither is used
   as a unit indicator.
3. **Magnitude and event signature.** `W825RC1` runs 27.1 (2019-06) → **619.2 (2021-01)** →
   33.8 (2023-06); a 23× spike concentrated in January 2021 is the pandemic-UI signature and
   is not something Social Security, Medicaid or Veterans' benefits could produce. `W823RC1`
   at 1,570.5 (2025-03) matches Social Security's scale; `W826RC1` at 128.8 (2019-06) matches
   VA compensation's.

**Unverified residue, stated rather than papered over:** the *units* and *seasonal
adjustment* fields could not be read, because they live only on the blocked metadata page.
Magnitudes are consistent with billions of dollars at an annual rate (UI at $27B in mid-2019
is an annual rate, not a monthly level), and an empirical month-of-year test on 2005–2019
`W825RC1` month-over-month changes shows no clean seasonal pattern — but neither is proof,
and I am not asserting "SAAR" as a fact. It does not affect the backtest: first print and
realised value are read from the same series on the same basis.

**Publication lag.** All four series print at **lag 2** — the observation for month *M* first
appears at the vintage *M*+2 and is absent at *M*+1, uniformly across all 8 units. This is a
sharp contrast with the Census/FNS state SNAP series in the base corpus (~2-year lag, annual
bulk updates), and it is why the horizons here are 3–14 months rather than 30+.

---

## 1. Veterans' Compensation Cost-of-Living Adjustment Act of 2023 — **KEPT**

**Law.** Pub. L. 118-6, 137 Stat. 50, approved June 14, 2023.
**Source.** https://www.govinfo.gov/content/pkg/PLAW-118publ6/html/PLAW-118publ6.htm
**Text file.** `bills/VETCOLA-2023-118publ6.txt`

Verbatim, establishing the parameter change and its date (§2(a), (c)):

> (a) <<NOTE: 38 USC 1114 note.>> Rate Adjustment.--Effective on December 1, 2023, the
> Secretary of Veterans Affairs
> shall increase, in accordance with subsection (c), the dollar amounts in effect on
> November 30, 2023, for the payment of disability compensation and dependency and indemnity
> compensation under the provisions specified in subsection (b).

> (c) Determination of Increase.--Each dollar amount described in subsection (b) shall be
> increased by the same percentage as the percentage by which benefit amounts payable under
> title II of the Social Security Act (42 U.S.C. 401 et seq.) are increased effective
> December 1, 2023, as a result of a determination under section 215(i) of such Act
> (42 U.S.C. 415(i)).

§2(b) enumerates exactly which dollar amounts move: wartime disability compensation
(38 U.S.C. 1114), additional compensation for dependents (1115(1)), the clothing allowance
(1162), DIC to surviving spouses (1311(a)–(d)), and DIC to children (1313(a), 1314).

Why this is a good unit: it is obscure (a four-section act nobody cites), it is a
*program-level benefit parameter* rather than an eligibility rule, the effective date is
hard-coded, and — the useful part — the *magnitude* was genuinely unknown at enactment,
because §2(c) delegates it to a Social Security determination not made until October 2023.
A forecaster at the June 2023 origin has real uncertainty, not a memorisable number.

**Indicator.** `W826RC1` — "Personal current transfer receipts: Government social benefits
to persons: Veterans' benefits" (see §0 for how the id was confirmed).

| unit | target | first print | vintage | latest (2026-07-31) | revision | horizon |
|---|---|---|---|---|---|---|
| `vetcola.us.2023-12` | 2023-12 | **173.9** | 2024-02-01 | 208.6 | +34.7 | **8 mo** |
| `vetcola.us.2024-03` | 2024-03 | **175.0** | 2024-05-01 | 215.1 | +40.1 | **11 mo** |

Origin vintage 2023-06-01 (13 days before enactment); history 2018-05 … 2023-04, 60 months.
The +35 to +40 revision is by far the largest in the extension: today's vintage puts these
months 20–23% above what was first published. I have not traced which revision cycle produced
it — the measured first-print/latest gap is the fact; the mechanism is not something I
verified. It is precisely why resolving against first print matters here.

---

## 2. Social Security Fairness Act of 2023 — **KEPT**

**Law.** Pub. L. 118-273, 138 Stat. 3232, approved January 5, 2025.
**Source.** https://www.govinfo.gov/content/pkg/PLAW-118publ273/html/PLAW-118publ273.htm
**Text file.** `bills/SSFA-2023-118publ273.txt`

Verbatim (§2(a), §3(a), §4):

> SEC. 2. REPEAL OF GOVERNMENT PENSION OFFSET PROVISION. (a) In General.--Section 202(k) of
> the Social Security Act (42 U.S.C. 402(k)) is amended by striking paragraph (5).

> SEC. 3. REPEAL OF WINDFALL ELIMINATION PROVISIONS. (a) In General.--Section 215 of the
> Social Security Act (42 U.S.C. 415) is amended-- (1) in subsection (a), by striking
> paragraph (7); (2) in subsection (d), by striking paragraph (3); and (3) in subsection (f),
> by striking paragraph (9).

> SEC. 4. <<NOTE: 42 USC 402 note.>> EFFECTIVE DATE. <<NOTE: Applicability.>> The amendments
> made by this Act shall apply with respect to monthly insurance benefits payable under title
> II of the Social Security Act for months after December 2023. <<NOTE: Adjustment.>>
> Notwithstanding section 215(f) of the Social Security Act, the Commissioner of Social
> Security shall adjust primary insurance amounts to the extent [[Page 138 STAT. 3233]]
> necessary to take into account the amendments made by section 3.

Note the structure: the Act was approved 2025-01-05 but reaches back to months after
December 2023, so it forces a retroactive true-up on top of a permanent level shift. That is
a two-component forecasting problem (a transitory catch-up and a permanent increase) stated
entirely in five lines of statute.

**Indicator.** `W823RC1` — "Personal current transfer receipts: Government social benefits
to persons: Social security".

| unit | target | first print | vintage | latest (2026-07-31) | revision | horizon |
|---|---|---|---|---|---|---|
| `ssfa.us.2025-03` | 2025-03 | **1516.2** | 2025-05-01 | 1570.5 | +54.3 | **5 mo** |
| `ssfa.us.2025-06` | 2025-06 | **1583.9** | 2025-08-01 | 1587.9 | +4.0 | **8 mo** |

Origin vintage 2024-12-15 (21 days before enactment); history 2019-11 … 2024-10, 60 months.

---

## 3. Continued Assistance for Unemployed Workers Act of 2020, §203 — **KEPT**

**Law.** Consolidated Appropriations Act, 2021, Pub. L. 116-260, div. N, tit. II, subtit. A,
ch. 1, §203, 134 Stat. 1953, approved December 27, 2020.
**Source.** https://www.govinfo.gov/content/pkg/PLAW-116publ260/html/PLAW-116publ260.htm
**Text file.** `bills/CAA-2021-116publ260.txt`

Placement verified structurally, not from memory: `DIVISION N--ADDITIONAL CORONAVIRUS
RESPONSE AND RELIEF` is the enclosing division, and §200 reads "This chapter may be cited as
the ``Continued Assistance for Unemployed Workers Act of 2020''."

Verbatim (§203(a), §203(b)(1)):

> (a) In General.--Section 2104(e) of the CARES Act (15 U.S.C. 9023(e)) is amended to read as
> follows: ``(e) <<NOTE: Time periods.>> Applicability.--An agreement entered into under this
> section shall apply--
> ``(1) to weeks of unemployment beginning after the date on which such agreement is entered
> into and ending on or before July 31, 2020; and ``(2) to weeks of unemployment beginning
> after December 26, 2020 (or, if later, the date on which such agreement is entered into),
> and ending on or before March 14, 2021.''.

> ``(3) Amount of federal pandemic unemployment compensation.-- ``(A) <<NOTE: Time periods.>>
> In general.--The amount specified in this paragraph is the following amount: ``(i) For weeks of unemployment
> beginning after the date on which an agreement is entered into under this section and
> ending on or before July 31, 2020, $600. ``(ii) For weeks of unemployment beginning after
> December 26, 2020 (or, if later, the date on which such agreement is entered into), and
> ending on or before March 14, 2021, $300.''.

A clean weekly-dollar parameter with both a start and an end date — $600, a lapse visible on
the face of the statute (window (1) ends July 31, 2020; window (2) opens after December 26,
2020), then $300. That makes the March target month diagnostically interesting: it straddles
the March 14, 2021 expiry, which ARPA later overrode. Verified, not recalled — American
Rescue Plan Act of 2021, Pub. L. 117-2, 135 Stat. 4, fetched to `bills/ARPA-2021-117publ2.txt`
from https://www.govinfo.gov/content/pkg/PLAW-117publ2/html/PLAW-117publ2.htm,
`<<NOTE: Mar. 11, 2021 - [H.R. 1319]>>`,
"Approved March 11, 2021", §9013: "(a) In General.--Section 2104(e)(2) of the CARES Act
(15 U.S.C. 9023(e)(2)) is amended by striking ``March 14, 2021'' and inserting ``September 6,
2021''. (b) Amount.--Section 2104(b)(3)(A)(ii) of such Act … is amended by striking ``March
14, 2021'' and inserting ``September 6, 2021''." ARPA is enacted three months *after* the
forecast origin, so it is correctly invisible to the forecaster and correctly present in the
realised value — which is the point of the March unit.

**Indicator.** `W825RC1` — "Personal current transfer receipts: Government social benefits to
persons: Unemployment insurance".

| unit | target | first print | vintage | latest (2026-07-31) | revision | horizon |
|---|---|---|---|---|---|---|
| `fpuc300.us.2021-01` | 2021-01 | **570.6** | 2021-03-01 | 619.2 | +48.6 | **3 mo** |
| `fpuc300.us.2021-03` | 2021-03 | **541.3** | 2021-05-01 | 568.5 | +27.2 | **5 mo** |

Origin vintage 2020-12-15 (12 days before enactment); history 2015-11 … 2020-10, 60 months.

---

## 4. Consolidated Appropriations Act, 2023, §5131 — **KEPT**

**Law.** Pub. L. 117-328, div. FF (Health and Human Services), tit. V (Medicaid), subtit. D
("Transitioning From Medicaid FMAP Increase Requirements"), §5131, 136 Stat. 5949. The
enrolled text carries `<<NOTE: Dec. 29, 2022 - [H.R. 2617]>>`; this law's govinfo HTML has no
"Approved …" line, so the enactment date is cited from that note, not from an approval line.
**Source.** https://www.govinfo.gov/content/pkg/PLAW-117publ328/html/PLAW-117publ328.htm
**Text file.** `bills/CAA-2023-117publ328.txt` (already in the repo)

This one needs two documents, because §5131 is purely amendatory and the operative parameter
lives in the law it edits. Verbatim from §5131(a)(2)(C):

> (C) in paragraph (3)-- (i) by striking ``as of the date of enactment of this section'' and
> inserting ``as of March 18, 2020,''; (ii) by striking ``such date of enactment'' and
> inserting ``March 18, 2020,''; (iii) by striking ``the last day of the month in which the
> emergency period described in subsection (a) ends'' and inserting ``March 31, 2023,''; and
> (iv) by striking ``the end of the month in which such emergency period ends'' and inserting
> ``March 31, 2023,'';

"Paragraph (3)" is FFCRA §6008(b)(3) — fetched to `bills/FFCRA-2020-116publ127.txt` from
https://www.govinfo.gov/content/pkg/PLAW-116publ127/html/PLAW-116publ127.htm — and it is the
Medicaid continuous-enrolment condition, verbatim:

> (3) the State fails to provide that an individual who is enrolled for benefits under such
> plan (or waiver) as of the date of enactment of this section or enrolls for benefits under
> [[Page 134 STAT. 209]] such plan (or waiver) during the period beginning on such date of enactment and ending the
> last day of the month in which the emergency period described in subsection (a) ends shall
> be treated as eligible for such benefits through the end of the month in which such
> emergency period ends unless the individual requests a voluntary termination of eligibility
> or the individual ceases to be a resident of the State;

So the composite effect is exact: continuous enrolment, previously open-ended and tied to the
public-health emergency, terminates **March 31, 2023**. §5131 also sets the FMAP step-down on
a quarterly schedule — "6.2 percentage points" through March 31, 2023, then 5, then 2.5, then
1.5 — and closes with "(c) <<NOTE: 42 USC 1396a note.>> Effective Date.--The amendments made by this
section take effect on April 1, 2023."

Note the phrase "continuous enrollment" appears **nowhere** in Pub. L. 117-328. Anyone
searching for it by name in the statute finds nothing; the provision is identifiable only by
following the amendment into FFCRA. That is a useful property for a backtest of a
bill-reading tool.

**Indicator.** `W729RC1` — "Personal current transfer receipts: Government social benefits to
persons: Medicaid".

| unit | target | first print | vintage | latest (2026-07-31) | revision | horizon |
|---|---|---|---|---|---|---|
| `medicaid.us.2023-06` | 2023-06 | **879.0** | 2023-08-01 | 905.5 | +26.5 | **8 mo** |
| `medicaid.us.2023-12` | 2023-12 | **861.7** | 2024-02-01 | 868.7 | +7.0 | **14 mo** |

Origin vintage 2022-12-15 (14 days before enactment); history 2017-11 … 2022-10, 60 months.
14 months is the longest horizon in the extension and is a design choice, not a data
constraint — the target was picked to sit three quarters into the unwinding.

---

## 5. Operative vs stated purpose — the split, and an honest null

The brief asks for provisions split into OPERATIVE and STATED PURPOSE, because an ablation
tests whether a model reads a purpose clause as if it were the statute. **None of the four
events supplies stated-purpose language.** This is a verified null, not an oversight:

| event | `FINDINGS` | `PURPOSE` | `SENSE OF CONGRESS` | scanned scope |
|---|---|---|---|---|
| PL 118-6 | 0 | 0 | 0 | whole Act |
| PL 118-273 | 0 | 0 | 0 | whole Act |
| PL 116-260 §203 | 0 | 0 | 0 | all of div. N, tit. II |
| PL 117-328 §5131 | — | — | — | §5131 is amendatory throughout; no purpose clause attaches to it or to subtit. D |

(The one `purpose` hit in PL 118-6 is "for purposes of", not a purpose clause.) I also
checked the PACT Act, Pub. L. 117-168 — fetched to `bills/PACT-2022-117publ168.txt` as a
candidate purpose-clause donor — and it has no FINDINGS, PURPOSE or SENSE OF CONGRESS section
either.

**Consequence, stated plainly: the purpose-clause ablation remains anchored on FRA §313 and
gains no new material from this extension.** Do not synthesise a purpose clause for these
events; a written-by-us preamble is not the treatment FRA §313 is.

What the extension *does* add is a second instance of the FRA §314 structure — a provision
that is operative but imposes only a reporting/publication duty with no benefit mechanics.
PL 118-6 §3 ("The <<NOTE: Federal Register, publication.>> Secretary of Veterans Affairs shall
publish in the Federal Register the amounts specified in section 2(b), as increased under that
section…") is the analogue, tagged
`s3_operative_ancillary` in `provisions_extra.json`. If the ablation of interest is
"operative-but-inert text", there are now two events carrying it.

Provision hashes (`sha256[:12]` of the normalised slice, matching the convention in
`PREREGISTRATION.md`):

| event | slice | role | sha256[:12] |
|---|---|---|---|
| PL 118-6 | §2 rate adjustment | operative | `21bb8f733542` |
| PL 118-6 | §3 publication of adjusted rates | operative (ancillary) | `0be03b0ebb74` |
| PL 118-273 | §2 repeal GPO | operative | `c6d766263ec1` |
| PL 118-273 | §3 repeal WEP | operative | `fd1810614a26` |
| PL 118-273 | §4 effective date | operative | `697825f0f1d3` |
| PL 116-260 | §203 FPUC extension + $300 | operative | `ffc7f10d4d87` |
| PL 117-328 | §5131 FMAP transition | operative | `2cab1e7bebb5` |

---

## 6. Candidates DROPPED, and exactly why

**(a) Pub. L. 118-19, believed to be the Veterans' COLA Act of 2023 — DROPPED, wrong law.**
I fetched `PLAW-118publ19` on the assumption it was the 2023 veterans COLA statute. It is
not. Its long title is "To amend title 38, United States Code, to extend and modify certain
authorities and requirements relating to the Department of Veterans Affairs, and for other
purposes"; its four sections extend a contractor-licensure pilot, extend educational-assistance
relief to September 30, 2025, extend an emergency-preparedness appropriation authorisation to
2028, and move a VA housing-loan fee date from November 14 to November 15, 2031. No
compensation rates, no COLA. Kept on disk as
`bills/PL118-19-DROPPED-not-the-cola-act.txt` so the drop is auditable. The correct law is
Pub. L. 118-6, used as event 1. **This is the failure mode the brief warns about — a
confidently recalled public-law number that is simply wrong — and it was caught only by
reading the fetched text.**

**(b) SNAP emergency-allotment sunset, Pub. L. 117-328 div. HH §503(b) — DROPPED on the
indicator, not the provision.** The provision itself is verified and is the most obscure thing
I found (it sits inside a section titled "OFFSETS"):

> (b) Allotments.--Section 2302 of the Families First Coronavirus Response Act (7 U.S.C. 2011
> note; Public Law 116-127) is amended by adding at the end the following: ``(d) Sunset.--The
> authority under subsection (a)(1) shall expire after the issuance of February 2023 benefits
> under that subsection.''.

It is dropped because no suitable indicator exists. The change is to benefit *dollars*, not
caseload, so the `BR<ST><FIPS>M647NCEN` family already in the corpus (SNAP benefit
*recipients*) measures the wrong quantity — and would duplicate the existing indicator family
regardless. The only federal SNAP benefit-dollar series I could confirm on FRED is
`TRP6001A027NBEA`, "Government social benefits: to persons: Federal: Supplemental Nutrition
Assistance Program (SNAP)", which is **annual** — a February 2023 sunset washes out inside a
calendar-year figure. Rather than force a mismatched pairing, the event is recorded here and
left out of the corpus. If someone wants it, the right move is a USDA-FNS monthly benefit-cost
series ingested directly, not a FRED substitute.

**(c) My own recollection of the CAA-2023 SNAP provision was also wrong** and is worth
recording as a near-miss: I looked for it at "div. HH §502", which is actually "INCREASING
ACCESS TO SUMMER MEALS FOR CHILDREN THROUGH EBT AND ALTERNATIVE DELIVERY OPTIONS", and
searched for the phrase "emergency allotment", which returns **zero hits in the entire law**
(Pub. L. 117-328 runs 136 Stat. 4459–6111, i.e. 1,653 pages of the Statutes at Large, counted
from the page markers in the fetched text). The provision was found only by scanning div. HH
for cross-references to Pub. L. 116-127.

**(d) PACT Act, Pub. L. 117-168 — considered, not used.** Fetched and scanned. It is a real
veterans benefit expansion, but (i) it is famous, which the brief asks us to avoid, (ii) its
presumption expansions have no single hard-dated benefit parameter of the kind §2 of PL 118-6
supplies, and (iii) it would land on `W826RC1`, already used. Left on disk at
`bills/PACT-2022-117publ168.txt`; nothing in the corpus depends on it.

---

## 7. No-lookahead verification

Checked programmatically over `ground_truth_extra.json`: for every unit, **no history row is
at or after the target month**, and every history ends at or before its declared
`history_through`. Origins are strictly pre-enactment in all four events (12–21 days before,
matching the FRA precedent of a 2023-06-01 origin against a 2023-06-03 enactment), so the
forecaster is conditioned on a bill it can read but on no data that reflects it.

| unit | origin vintage | last history obs | target | horizon |
|---|---|---|---|---|
| `vetcola.us.2023-12` | 2023-06-01 | 2023-04-01 | 2023-12-01 | 8 |
| `vetcola.us.2024-03` | 2023-06-01 | 2023-04-01 | 2024-03-01 | 11 |
| `ssfa.us.2025-03` | 2024-12-15 | 2024-10-01 | 2025-03-01 | 5 |
| `ssfa.us.2025-06` | 2024-12-15 | 2024-10-01 | 2025-06-01 | 8 |
| `fpuc300.us.2021-01` | 2020-12-15 | 2020-10-01 | 2021-01-01 | 3 |
| `fpuc300.us.2021-03` | 2020-12-15 | 2020-10-01 | 2021-03-01 | 5 |
| `medicaid.us.2023-06` | 2022-12-15 | 2022-10-01 | 2023-06-01 | 8 |
| `medicaid.us.2023-12` | 2022-12-15 | 2022-10-01 | 2023-12-01 | 14 |

Horizon is counted from the last observation the forecaster can see to the target month, the
same convention as the base corpus.
