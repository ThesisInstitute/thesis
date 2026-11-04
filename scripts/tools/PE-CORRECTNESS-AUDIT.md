# PE correctness audit — evidence catalogue (issue #45)

**Question this file answers:** are the agents actually using PolicyEngine
correctly?
**Method:** every claim below was produced by an executed check on
**2026-07-31** — a runnable assertion in `scripts/tools/_assert_correctness.py`
(machine-readable results in `_assert_results.json`), a pytest, or a captured
CLI/HTTP call from this session. Nothing here is asserted from memory or
documentation alone. Where something is **not yet verified**, it is listed in
§7 as pending — not assumed.

Reproduce the battery:

```bash
PYTHONPATH=scripts/tools python scripts/tools/_assert_correctness.py   # network required
```

Result: **14/14 PASS** (verbatim evidence quoted per row below).

---

## 1. Environment provenance (state it, don't assume it)

| id | claim | evidence (verbatim) |
|----|-------|---------------------|
| ENV | Installed model version is recorded on every run | `policyengine_us_version() = '1.784.3'` |

Consequence recorded in CERT-4: this locally installed version is **not**
certified for build P, so no build-P economy number may come from this laptop's
install (national runs go through Modal on the certified stack — §5).

## 2. Reform validation — the agent cannot invent parameters

| id | claim | evidence (verbatim) |
|----|-------|---------------------|
| VAL-1 | The real Stronger Start reform validates | `ok=True, source=policyengine-us@1.784.3, problems=[]` |
| VAL-2 | Invented param + bad date + string value are **all** rejected | `ok=False; problems=["unknown parameter: 'gov.irs.credits.ctc.made_up' (base 'gov.irs.credits.ctc.made_up' not in policyengine-us@1.784.3)", "'gov.irs.credits.ctc.made_up': bad date range '2026' (want 'YYYY-MM-DD.YYYY-MM-DD')", "'gov.irs.credits.ctc.made_up'[2026]: value must be number/bool, got str"]` |
| VAL-3 | The exact parameter the bill edits exists in the model | `'gov.irs.credits.ctc.refundable.phase_in.threshold' in policyengine-us@1.784.3: True` |

Validation runs against the **installed model's parameter tree** (source label
is carried in the result), falling back to the metadata API, then flagging
`structural-only` loudly if neither is reachable. It never silently passes an
unverified reform.

## 3. Why tool-side validation is mandatory: the hosted API is not a validator

Both of these were **accepted** by the public API. First observed 2026-07-31
~09:57 with `201 "Policy created"` (policy ids 98076, 98077); the battery re-run
returned `200 "Policy already exists"` (98081, 98082) because the garbage
policies now exist server-side — which is itself the point: they were stored.

| id | claim | evidence (verbatim) |
|----|-------|---------------------|
| API-1 | `POST /us/policy` silently accepts an **invented parameter** | `HTTP 200, body={"status": "ok", "message": "Policy already exists", "result": {"policy_id": 98081}}` |
| API-2 | `POST /us/policy` silently accepts a **string** where a number belongs | `HTTP 200, body={"status": "ok", "message": "Policy already exists", "result": {"policy_id": 98082}}` |

Also captured this session (not in the battery):

- `GET /us/metadata` returned `http=500 size=0` on three consecutive tries
  (curl, ~09:55) — the API cannot be the primary existence oracle.
- `GET /us/economy/85587/over/2?...&dataset=<hf://… URI>` → gateway
  `400 Bad Request`; the **bare build tag** form was accepted (`status: computing`).
- The same economy run pinned to build P later flipped to `status: error`
  with `message: None` — consistent with the hosted executor not running the
  build's certified model version (§4). The tool therefore treats hosted runs
  as one engine, never the only one, and surfaces `pending`/`error` rather than
  blocking or zeroing.

## 4. Certification — the model↔data pairing is enforced, not assumed

The build's own `release_manifest.json` on HuggingFace is the source of truth
(fetched live by `certified_model_version()`).

| id | claim | evidence (verbatim) |
|----|-------|---------------------|
| CERT-1 | Build P certifies exactly one model version | `certified_model_version(build P) = '1.764.6'` |
| CERT-2 | Running 1.784.3 on build P is flagged UNCERTIFIED | `{'build': 'populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z', 'certified_model_version': '1.764.6', 'running_model_version': '1.784.3', 'certified': False, 'warning': 'UNCERTIFIED PAIRING: build certifies policyengine-us==1.764.6, running 1.784.3. Install the certified version.'}` |
| CERT-3 | Running 1.764.6 on build P is certified | `certified=True` |
| CERT-4 | The locally installed version is NOT certified for build P | `installed='1.784.3' != certified='1.764.6' -> local build-P runs would be uncertified` |

Corroborating manifest lines (read from the installed `policyengine==5.0.1`
bundle, `policyengine/data/bundle/manifest.json`):
`"certified_for_model_version": "1.764.6"`,
`"install_requirement": "policyengine-us==1.764.6"`, and the JSON-LD trace:
`"Certification of build populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z for policyengine-us 1.764.6."`
The `policyengine` package refused to even import against 1.784.3:
`ValueError: Data release manifest is not certified for the runtime model version 1.784.3 in country 'us'.` (captured ~10:31).

`compute_block()` now attaches a `certification` object to every emitted
result; `certified: false` ⇒ the number is inadmissible for publication.

## 5. Execution environment — where a national run may actually happen

Observed, not theorized:

- **Laptop (16 GB): OOM.** First national attempt died in
  `de_income_tax_if_claiming_refundable_eitc → simulation.get_branch(...)` with
  `numpy._core._exceptions._ArrayMemoryError: Unable to allocate 234. KiB for an array with shape (59900,)`
  — every state's refundable-EITC logic clones the population; two arms peaked
  past the box (~98% memory, killed at user request; second sequential-arm
  attempt still climbed to ~8 GB and was killed).
- **Hosted API pinned to build P: errored** (`status: error`, `message: None`).
- **Modal, certified stack: image built clean.**
  `policyengine-us==1.764.6` + `policyengine-core==3.26.11` on
  `debian_slim(python_version="3.12")`, 32 GB / 4 CPU:
  `Successfully installed … policyengine-core-3.26.11 … policyengine-us-1.764.6 …`,
  `Built image im-ns1xZ2juc3D0d93cToBZe9 in 56.99s`, function `economy` created
  (app `stronger-start-buildp-economy`, run
  `https://modal.com/apps/policyengine/main/ap-h8MkCPV0VxseeURiPlckQE`).
  Full-metric result: **pending** at time of writing (§7).

Windows operational gotchas captured: Modal CLI crashed on `'charmap' codec
can't encode character '✓'` until `PYTHONIOENCODING=utf-8` was set (same
class of failure as the brier CLI emoji crash).

## 6. Call-parameter correctness (baseline, dataset, statute fidelity)

| id | claim | evidence (verbatim) |
|----|-------|---------------------|
| CALL-1 | Current-law baseline is policy id 2 | `baseline_id('us') = 2` |
| CALL-2 | Policy 2 is a real current-law record | `policy/2 label='Current law', keys=['id', 'country_id', 'label', 'api_version', 'policy_json', 'policy_hash']` |
| STAT-1 | The baseline value the bill removes is $2,500 | `param('2026-01-01') = 2500` (`gov.irs.credits.ctc.refundable.phase_in.threshold`, 1.784.3 tree; also `2500` at 2025-01-01 and 2027-01-01, captured ~10:52) |
| STAT-2 | Statute-vs-encoding discrepancy is **recorded**, not hidden | S.3596 §2(a) strikes `"$3,000"→"$1"`, §2(b) removes §24(h)(6) ($2,500) ⇒ statutory threshold **$1**; PE policy 85587 `policy_json` (fetched live) and `bills/…/reform.json` encode **0**. Economically identical; the $1-vs-$0 choice is catalogued in the bill artifact and CHECKLIST. |

Dataset pinning facts (captured earlier today): HF tag list shows
`populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z` as the
newest tag, and `latest.json` points to it (`release_id` field, updated
2026-07-28) — but per direction the tool pins the **immutable tag**, never
`latest.json`/`main` (a `latest.json` regression occurred days earlier).
Also captured: `policyengine-us==1.784.3`'s bundled default is the **June-19
pre-lettering build** (`Microsimulation.default_dataset =
hf://…populace_us_2024.h5@populace-us-2024-c86a631-6e1bcd0271a5-20260619T002242Z`)
— i.e. relying on defaults silently prices months-old data; the tool always
names the build.

Hand-built arithmetic check (live pytest, `PE_LIVE=1`, passed ~10:20):
single parent, one child (4), **$2,000** earnings, TX 2026 —
baseline refundable CTC ≈ $0 (earnings below the $2,500 phase-in floor);
under the reform the credit phases in from the first dollar and the test
asserts `reform refundable_ctc > baseline refundable_ctc`:
`1 passed (test_household_ctc_phase_in_point_check)`. The `/calculate`
endpoint only returns variables present in the payload — the output variable
must be seeded null (`"refundable_ctc": {"2026": null}`), which the test does.

## 7. Full build-P run — VERIFIED (Modal, certified stack, 2026-07-31 11:27)

The Modal run completed (`✓ App completed`, run
`https://modal.com/apps/policyengine/main/ap-h8MkCPV0VxseeURiPlckQE`); artifact:
`bills/stronger-start-working-families-act/buildP-economy-2026.json`. Verbatim
headline values from the artifact:

- `budgetary_impact: -1826396338.82` (−$1.83B, 2026)
- child poverty `0.17017 → 0.16821` (`pct_change: -0.011553`)
- all poverty `0.13173 → 0.13110` (`pct_change: -0.004807`)
- deep child poverty `pct_change: -0.008493`
- winners `gain_less_5pct: 0.064758` (6.5%), `no_change: 0.935052`,
  `lose_more_5pct: 0.0`
- decile average change: D1 `31.90` … D10 `0.30` (bottom-concentrated)
- Gini `0.469885 → 0.469790` (`pct_change: -0.000202`)
- provenance in-artifact: `engine: modal`, `dataset: populace-us-2024-buildp-…`,
  `pe_us_version: 1.764.6`, `pe_core_version: 3.26.11`

**Internal consistency (captured):** `tax_revenue_impact: -1826395934.07` vs
net-income-delta `-1826396338.82` — two independent computations agree to
~$400 in $1.8B; `benefit_spending_impact: 0.0` as expected for a pure
tax-credit provision.

**Anchor comparison (fresh vs external):** stale published PE figure (older
build) was −$1.6B/2026 with child poverty −0.4%; TPC ~$1.0B/yr. Fresh certified
build-P: −$1.83B (+14% vs stale PE; same order as TPC) and child poverty −1.2%
(≈3× the stale figure) — the data refresh materially moved the poverty result,
which is why stale numbers were inadmissible.

## 7a. Ten-year sweep — VERIFIED (Modal, certified stack, 2026-07-31 ~13:00–13:35)

Full 2026–2035 sweep, one 32 GB container per year in parallel, certified stack
(us==1.764.6 + core==3.26.11) on build P. **Ten-year budgetary impact:
−$17,072,622,631.78 (−$17.1B)**, per-year cost declining $1.86B (2027) →
$1.53B (2035) — coherent: nominal earnings growth organically lifts families
past the old $2,500 floor, shrinking the provision's bite. Child-poverty effect
−0.7% to −1.8% in every year. Anchors: +17% vs the stale published PE $14.6B
(older build; consistent with the +14% 2026-only gap), same order as TPC $9.5B.
Artifact: `bills/stronger-start-working-families-act/buildP-sweep-2026-2035.json`.

**Assembly + integrity (captured):** the driver's file-write failed twice
(cwd-relative path under `modal run`) and the launch pipeline's `tail -60`
truncated the log copy of three year-rows — the results survived because the
driver prints the full JSON before writing. Rows were recovered from the log
(2029–35 + total), the 2026 row from the single-year run, 2027–28 from a
two-container backfill; the assembled sum matches the sweep run's printed
total with **diff $0.000000**. Operational rules distilled into
`CHECKLIST.md` § "Operational traps".

## 7b. Still not verified (pending — explicitly NOT claimed)

1. **`economy_local` end-to-end on a certified pairing** — code path exists and
   is unit-tested for validation/normalization, but a full local national run
   has only been attempted on this laptop (OOM) and with an uncertified pairing
   (killed); treat `--local` as big-memory-box-only, certified-stack-only.
2. **Winners/losers denominators vs app-v2** — our intra-decile shares are
   person-weighted via `household_count_people`; app-v2's exact grouping code
   was not diffed line-by-line. Magnitudes match the published shape (6.5% vs
   5.9% beneficiaries) but treat sub-point differences as method variance.

## 8. External review findings (Max, 2026-07-31 — all three CONFIRMED and fixed)

The lane's own reviewer found three defects in the auditor. Recorded here in
the same evidence discipline the audit demands of everyone else:

1. **Fail-open validation/certification.** `validate_reform` passed (`ok=True`)
   with only a WARNING when parameter existence could not be checked (no
   policyengine-us + metadata API down), and `certification_note` returned
   `certified: False` with a **silent `warning: None`** when the release
   manifest was unreachable — a PE failure validated instead of refusing.
   *Fixed:* unverifiable existence now REFUSES unless `allow_unverified=True`
   is passed explicitly; certification refusals always carry an explicit
   CANNOT CERTIFY reason (manifest unreachable / running version unknown);
   the hosted-API engine's certification passes `running_version=None`
   (api_version is the service version, not the model) and therefore refuses
   rather than confusing the two. Tests: `test_unverifiable_existence_REFUSES_by_default`,
   `test_certification_refuses_when_manifest_unreachable`, and siblings.

2. **Federal budget aggregation computed wrong.** `economy_local` and the Modal
   runner derived "budgetary impact" from the `household_net_income` delta,
   which lumps **state** tax/benefit spillovers into a federal number (the
   observed ~0.02% "losers" were state-credit interactions polluting the
   federal aggregate). *Fixed:* federal = engine's own federal variables —
   `income_tax` delta (federal 1040 net liability incl. refundable credits)
   minus `household_benefits` delta; `state_income_tax` delta reported
   separately as `state_tax_revenue_impact`; the net-income delta demoted to a
   labeled cross-check field.

3. **The audit artifact bypassed the wrapper it audits.** The committed S.3596
   numbers were produced by `modal_economy.py` calling `Microsimulation`
   directly — no `validate_reform` gate, no `compute_block`, no
   `bills/compute-log` entry. *Fixed:* the Modal entrypoints now validate
   FAIL-CLOSED through the wrapper before submitting, and every completed run
   is recorded via `pe.EconomyRun -> pe._log_call` with the bill.json row
   emitted by `pe.compute_block`.

**Consequence — resolved:** the corrected federal re-runs landed 2026-07-31
~14:35–15:00 ET. 2026: **−$1,826,050,568.80** federal (old proxy
−$1,826,396,338.82; delta = the −$0.35M state spillover, now itemized).
Ten-year: **−$17.069B** federal (old proxy −$17.073B; delta = $3.5M spillover
across ten years, −$0.30M..−$0.43M/yr). `benefit_spending_impact` measured
**0.0** in all ten years — previously assumed. Poverty/winners/Gini identical,
as expected. Headline unchanged to rounding (−$1.83B / −$17.1B) — but now
proven federal-only instead of assumed. Bonus catch: the wrapper's own emitted
row initially REFUSED certification (`running model version unknown`) because
the compute_block fix had silently rolled back in an aborted edit script — the
fail-closed gate fired correctly at its own author on first real use; fixed
with two regression tests (18 passing).

## 8a. Certification was asserted, not measured (prb4 round 3, fixed 2026-10-22)

After #64 merged, the Sol round-3 review found the certification chain itself
unproven: the committed evidence validated against `policyengine-us@1.784.3`
(the 2026 row; the sweep against `@1.661.0`) while the Modal artifact recorded
1.764.6. That 1.764.6 was the driver's own `PE_US` pin constant echoed back,
never read in the container. So `certified: true` could not fail. The row was
then hand-flipped to `certified: false` and published anyway, with the note
"Figure retained as claimed-tier evidence" — which §0.2 forbids, since an
uncertified run is inadmissible for a published number.

*Fixed (#392):*
1. **Measured, not asserted.** `certification_note` certifies only when the
   running `policyengine-us` and `policyengine-core`, measured from package
   metadata in the process that computed (`pe.runtime_stack`), match the
   build's manifest pins, and the reform was validated against that same
   running model. `modal_economy.py` ships the wrapper into the container,
   which runs `pe.require_runtime_stack` and `pe.validate_reform` before any
   microsim and reports what it measured. The local preflight is never
   recorded. Hosted-API runs no longer record the local machine's version.
2. **Published pages withhold uncertified figures.** One gate,
   `isPublishableCompute` / `publishable_compute_row`, pinned to
   `tests/fixtures/compute_publishability_cases.json`. A failing row lists its
   provenance and reason, and no figure.
3. **No hand-typed certification.** `attach_compute.py` requires the registry
   row's certification to equal the `compute_block` output of its grounding run,
   with versions and `param_source` equal to the measured artifact values. Tests
   require every committed bill row to be a registered, verified row.

**Re-run, 2026-10-22, Modal** (2026: `ap-3hNH8qQe8MgQudwigCL6fh`; sweep:
`ap-pC0HjguLRapdnimfkCfcEV`): measured `policyengine-us==1.764.6` +
`policyengine-core==3.26.11`, validated in-container on `policyengine-us@1.764.6`,
certified. Every metric reproduces the 2026-07-31 run bit for bit: 2026
**−$1,826,050,568.80**; ten-year **−$17,069,142,980.93**; all ten sweep years,
poverty, deciles, winners/losers and Gini identical. The headline did not move;
only now is it proven at exact runtime. Edit record:
`bills/provenance/s3596-119/compute-recertification-2026-10-22.json`.

## 9. Verdict

With the tool in place, an agent **cannot**: invent a parameter (VAL-2 blocks it
where the API would accept it — API-1/2), run an uncertified model↔data pairing
without a recorded warning (CERT-2/4), price against an unnamed or stale
dataset (build pinned + recorded; defaults proven stale), mistake the baseline
(CALL-1/2), or silently treat a queued/failed run as zero (pending/error are
first-class statuses). Every run emits provenance (engine, dataset, model
version, param-source, certification) in `bills/compute-log/` and in the
`compute` block attached to the provision it prices.
