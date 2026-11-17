# PolicyEngine tool — correctness checklist

Audit gates for every agent PolicyEngine call in the bills lane (issue #45),
strongest first. A run is **admissible** only if gates 1–2 pass; gate 3
corroborates the magnitude. Worked examples below are real and reproducible;
commands assume the certified stack from `scripts/tools/requirements-tax.txt` is installed.

---

## Gate 0 — certification: model version matches the build

A Populace build certifies exactly one `policyengine-us` version (in its
`release_manifest.json`). Running any other version against it is uncertified.

```python
pe.certified_model_version("populace-us-2024-buildp-…")   # -> "1.764.6"
pe.certification_note(build, running_version)["certified"]  # must be True
```

✅ build P + `policyengine-us==1.764.6` → certified.
❌ build P + `1.784.3` → **rejected**: "UNCERTIFIED PAIRING … Install the certified version."
(1.784.3 has no released certified build — the model outran the data.)

Checklist:
- [ ] the running/installed model version == the build's `certified_model_version`
- [ ] `compute_block(...)["certification"]["certified"]` is `true`
- [ ] national runs go through Modal on the certified stack (`scripts/tools/modal_economy.py`), not a laptop

## Gate 1 — parameter existence (offline, against `policyengine-us`)

The public API accepts garbage silently (see "Known API traps"), so existence is
checked against the installed model, not the API.

```bash
python scripts/tools/policyengine.py validate \
  '{"gov.irs.credits.ctc.refundable.phase_in.threshold": {"2026-01-01.2100-12-31": 0}}'
```
✅ **PASS** → `VALID [policyengine-us@1.784.3]: all parameters resolve, dates and value types well-formed.`

Negative control — invented parameter, bare-year date, string value:
```bash
python scripts/tools/policyengine.py validate '{"gov.irs.credits.ctc.made_up":{"2026":"lots"}}'
```
✅ **Correctly rejected** with three problems:
- `unknown parameter: 'gov.irs.credits.ctc.made_up'`
- `bad date range '2026' (want 'YYYY-MM-DD.YYYY-MM-DD')`
- `value must be number/bool, got str`

Checklist:
- [ ] every parameter path resolves (`checked_existence == true`, source `policyengine-us@…`)
- [ ] date ranges are `YYYY-MM-DD.YYYY-MM-DD`
- [ ] values are number/bool, never string
- [ ] if source is `structural-only`, the run is flagged unverified — **not** admissible for a published number

## Gate 2 — household arithmetic (offline point-check, exact)

Pick a household where the provision's effect is hand-computable and assert it.

Example (test `test_household_ctc_phase_in_point_check`): single parent, one
child age 4, **$2,000** earnings. Current law: refundable CTC phases in only
above **$2,500**, so the household gets ≈ $0 refundable CTC. Strike the threshold
to $0 and the credit phases in from the first dollar → refundable CTC **rises**.

```bash
PE_LIVE=1 pytest tests/test_policyengine_tool.py -k household_ctc
```
✅ **PASS** — `reform refundable_ctc > baseline refundable_ctc`.

Checklist:
- [ ] the direction of the household change matches the statute
- [ ] the magnitude matches hand arithmetic within rounding

## Gate 3 — external anchor (corroboration, not a gate)

Compare the economy number to published scores. Agreement within the
static-vs-official band corroborates the calibration; a large gap is an
**INVESTIGATE**, never a silent pass.

**Stronger Start for Working Families Act (S.3596)** — eliminate the refundable
CTC earnings threshold:

| Source | 10-yr cost | ~annual | notes |
|--------|-----------:|--------:|-------|
| **This run — build P, certified stack** (Modal, 2026-07-31; re-run 2026-10-22 with versions measured in-container, identical to the cent; federal aggregation) | **$17.07B** | **$1.83B (2026)** | child poverty −1.2%; 6.5% gain; Gini −0.02%; per-year cost declines $1.86B→$1.53B as nominal earnings clear the old floor |
| PolicyEngine published (older data build) | $14.6B | $1.6B (2026) | child poverty −0.4%; 5.9% benefit — **stale, superseded** |
| Tax Policy Center | ~$9.5B | ~$1.0B/yr | ~$100 avg gain, bottom quintile; 3.5M families |

Same order of magnitude across all three, low-single-digit $B/yr →
**corroborated** (10-yr: $17.1B vs published PE $14.6B (+17%) vs TPC $9.5B —
consistent with the +14% single-year gap; artifact
`bills/stronger-start-working-families-act/buildP-sweep-2026-2035.json`,
assembled sum matches the sweep run's printed total to the cent). The build-P refresh moved the cost +14% vs the stale
published figure and tripled the measured child-poverty effect (−0.4% → −1.2%)
— the reason fresh certified runs are mandatory before publication.
(Tax Foundation, Urban, and Yale Budget Lab also score this provision in the
same band.) Internal consistency on this run: net-income-delta vs tax-delta
agree to ~$400 in $1.8B; benefit_spending_impact 0.0 for a pure tax provision.

Checklist:
- [ ] economy number is within the expected band of ≥1 independent scorer
- [ ] the static-vs-official calibration note is applied if the cell resolves to an official score

---

## Provenance recorded on every run (the audit trail)

`bills/compute-log/<ts>-<country>-<year>-<reformhash>.json` captures: `reform`,
`reform_policy_id`, `baseline_policy_id`, `param_source`, `checked_existence`,
`pe_us_version`, `api_version`, `status`, normalized `impact`, `computed_at`.
Re-running the logged reform at the same `pe_us_version` reproduces the number —
that reproduction is the audit.

## The exactness finding (why hand-auditing matters)

The statute (S.3596 §2) strikes IRC §24(d)(1)(B)(i) `"$3,000" → "$1"` and
removes the §24(h)(6) override that sets the threshold to **$2,500** (the value
in effect for 2026, confirmed:
`CountryTaxBenefitSystem().parameters.gov.irs.credits.ctc.refundable.phase_in.threshold("2026-01-01") == 2500`).
Net statutory threshold = **$1**. PolicyEngine policy **85587** encodes it as
**$0**. Economically identical (essentially everyone with a qualifying child and
earnings clears $1), but a precise audit **records the $1-vs-$0 choice** rather
than assuming the reform dict equals the bill text.

## Known API traps (encoded in the tool so agents can't hit them)

- `POST /us/policy` returns **201** for an invented parameter and for a string
  value — it does **not** validate. → Gate 1 runs against the model, not the API.
- `/us/metadata` can be **500** (observed 2026-07-31). → validation falls back to
  the API only if the model is absent, and flags `structural-only` loudly.
- `/us/calculate` returns only variables **present** in the payload. → seed the
  output variable null (e.g. `"refundable_ctc": {"2026": null}`) to read it back.
- Economy runs are **minutes** long. → `status: pending` at timeout is normal;
  widen the interval, never treat pending as zero.

## Operational traps (running the compute — learned 2026-07-31, the hard way, twice)

- **Never pipe a compute driver through `tail`/`head`/`grep`.** The 10-year
  sweep's only copy of its printed results went through `| tail -60`, which
  silently discarded the first three year-rows. Capture full stdout to a file;
  filter afterwards.
- **Result writes use absolute (script-anchored) paths.** Both sweep drivers
  wrote artifacts with cwd-relative paths and died on `FileNotFoundError`
  after computing successfully. `modal run`'s local entrypoint cwd is not
  guaranteed — resolve output paths from `__file__`.
- **Print the full result JSON BEFORE writing any file.** That ordering is why
  both failures above were recoverable from the log instead of costing a
  re-run.
- **Deterministic microsim ⇒ sum-check assembled artifacts.** Rows recovered
  from logs/backfills must re-sum to the original run's printed total exactly
  (the 2026-2035 assembly matched to the cent) — commit the artifact only if
  it does.
