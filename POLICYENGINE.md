# POLICYENGINE.md — the PolicyEngine tool-call contract

The contract every ingest/forecast agent follows when it prices a **federal tax
provision** with PolicyEngine. Scope for the bills lane (issue #45): **federal,
tax only.** Do not use this path for benefit programs a bill doesn't change, for
state provisions, or for series PolicyEngine doesn't model (CPI, claims) — a
decorative microsim call is a defect.

PolicyEngine is a **model input, never ground truth.** Its output is one evidence
stream with its own error bars (static microsim differs from CBO/JCT by
behavioral and timing effects). Attach the number to the provision it prices;
never launder it into a fact.

The tool is `scripts/tools/policyengine.py`. Agents call it; auditors re-run the
logged reform through the same code and diff. "Hand-built invocation" ==
"re-run the reform in the audit log."

---

## 0. Install

```bash
uv venv .venv-tax && uv pip install --python .venv-tax -r scripts/tools/requirements-tax.txt
# (certified exact pins; separate venv — policyengine-core pins pytest<9, which conflicts with brier[dev])
```

Without the certified stack installed the API path still runs, but validation degrades to
structural-only and **says so** — an unverified run is flagged, never silent.

## 0.1 Two engines — pin the build either way

| engine | how | dataset | when |
|--------|-----|---------|------|
| **api, build-pinned** (default) | hosted service, `&dataset=<build tag>` | the build you name | **full national app-v2 metrics.** Server-side, so no local memory ceiling; baseline is cached per-dataset |
| local (`--local`) | `policyengine-us` microsim in-process | a pinned build (recorded) | household point-checks, or a **big-memory box** — a national microsim OOMs a 16 GB laptop |

Do NOT run a national microsim on a laptop: one arm of `household_net_income`
pulls the full state-by-state tree (each state's EITC spawns a population
`get_branch` clone) and peaks past 8 GB — it OOMs 16 GB. Use the API path for
economy numbers; keep `local` for validation and hand-computed household checks.

Either way, **pin the Populace build explicitly** — the hosted default lags the
current build (the published policy-85587 number is months old on an older
build), so name it:

```
POPULACE_BUILD = "populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z"  # build P (current)
```

Pass it as the API `dataset` param as the **build TAG** (the hf:// URI 400s at
the gateway). Pin the immutable tag, never `latest.json`/`main` — `latest.json`
regressed to a stale build on 2026-07-2x. `dataset` is part of the compute
cache key, so the current-law baseline is computed once per build and reused
across every reform (server-side baseline caching — no separate cache to build).

## 0.2 Certification — model version MUST match the build (the core audit)

A Populace build is certified for **one** `policyengine-us` version, named in the
build's `release_manifest.json`. Running any other version against it is an
uncertified pairing — the exact failure this lane exists to catch.

```
build P (populace-us-2024-buildp-…) certifies policyengine-us == 1.764.6  (+ core == 3.26.11)
```

`policyengine-us==1.784.3` (the newest wheel) has **no released certified build**
— the model advanced past the latest certified data. So to price on build P,
install **1.764.6**, not the newest. The tool enforces this, fail-closed:
`certification_note` certifies a run only when ALL of these hold, and every
refusal says which failed.

1. The build's release manifest is reachable and pins an exact
   `policyengine-us` version.
2. The running `policyengine-us`, **measured** in the process that computed
   (package metadata there, `pe.runtime_stack()`), equals that pin. A driver's
   own pin constant is what it asked the installer for, not what ran, and
   never counts.
3. The measured running `policyengine-core` equals the manifest's core pin,
   when the manifest names one.
4. The reform was validated against that same running model
   (`validated_against == "policyengine-us@<running>"`). A reform checked on
   another version can name a parameter the running model silently ignores.

```python
pe.certification_note(build, running_version,
                      running_core_version=core, validated_against=param_source)
# -> {"certified": False, "warning": "UNCERTIFIED PAIRING: build certifies
#     policyengine-us==1.764.6, running 1.784.3. Install the certified version. ..."}
```

`compute_block` carries this `certification` block on every run. A run whose
`certification.certified` is false is **inadmissible** for a published number.

**On published pages.** The bill page passes every compute row through one gate,
`isPublishableCompute` (`site/src/lib/compute-publishability.ts`; its Python
mirror is `publishable_compute_row` in `scripts/tools/attach_compute.py`, and both
are pinned to `tests/fixtures/compute_publishability_cases.json`). A row that is
not certified, or whose certification disagrees with the row's own versions,
validation or build, still lists: model, build, engine, an "uncertified pairing"
chip, the certification's reason, and the reform. It shows **no figure** — no
stats, no summary, no note. There is no "claimed-tier" display for a model
number. Nor is certification ever typed by hand: `attach_compute.py` refuses a
registry row whose certification differs from the block `compute_block` emitted
for its grounding run, and the tests require every committed row to be a
registered, verified one.

## 0.3 Where the national microsim runs — Modal, not a laptop

A national `calculate` OOMs a 16 GB box. Run it on **Modal** (PolicyEngine's own
sim substrate) with the certified stack pinned — see
`scripts/tools/modal_economy.py`: a 32 GB function that installs
`policyengine-us==1.764.6` + `core==3.26.11`, prices the reform on build P, and
returns the full app-v2 metric set (budget, poverty by group, deciles,
winners/losers, inequality). The audited wrapper ships into the container:
before any microsim the container measures its own installed versions
(`pe.require_runtime_stack`, which refuses on any mismatch with the pins) and
validates the reform against that running model, and the result reports those
measured versions and that validation — which is what certification checks.
The local preflight validation is never recorded. Single year:
`modal run scripts/tools/modal_economy.py::main` (set `PYTHONIOENCODING=utf-8`
on Windows or the CLI's `✓` crashes cp1252). Ten-year sweep:
`modal run scripts/tools/modal_economy.py::sweep` — one container per year in
parallel; the sweep refuses unless every container measured the same stack, and
records its own certification.

Capture rules for compute drivers (each violated once on 2026-07-31; both
failures were recoverable only because results print before any file write):
- capture FULL stdout to a file — never pipe the driver through
  `tail`/`head`/`grep`, which silently truncates the only copy of the results;
- write artifacts to absolute, `__file__`-anchored paths (`modal run` cwd is
  not guaranteed);
- print the complete result JSON before writing files;
- when assembling rows from logs or backfills, re-sum against the original
  run's printed total — deterministic microsim means the match must be exact.

---

## 1. The reform dict

A reform is a flat map of **parameter path → {date-range → value}**:

```json
{ "gov.irs.credits.ctc.refundable.phase_in.threshold": { "2026-01-01.2100-12-31": 0 } }
```

Rules:
- **Parameter paths are not free text.** Every path must exist in
  `policyengine-us`. Find it — do not guess — with:
  ```bash
  python scripts/tools/policyengine.py validate '<reform-json>'
  ```
  or by inspecting the model tree (`CountryTaxBenefitSystem().parameters`).
- **Date ranges are `YYYY-MM-DD.YYYY-MM-DD`.** No bare years (`"2026"` is
  invalid). Use the provision's statutory effective window.
- **Values are numbers or booleans.** `in_effect`-style switches are booleans;
  dollar/percent parameters are numbers. Strings are always wrong.
- **Bracketed parameters** (`...max[0].amount`) address one bracket; validate
  against the model, which knows the scale.

### Why validation is mandatory (the failure mode this lane exists to catch)

The public API **does not validate**. `POST /us/policy` returns `201` with a
policy id for an **invented parameter** and for a **string where a number
belongs**; the economy run then silently ignores the bad key and returns a
number that looks fine and prices *nothing*. So:

> **An agent MUST validate a reform before it runs it.** A run whose reform did
> not pass `validate` (against `policyengine-us`, not the API) is inadmissible.

`validate` reports its source — `[policyengine-us@1.784.3]`, `[metadata-api]`,
or `[structural-only]`. Only the first is a full existence check.

---

## 2. Years, region, baseline

- **Region:** federal ⇒ `region=us`. Never a state region for a federal score.
- **Baseline:** current law ⇒ policy id **2** (`CURRENT_LAW_ID["us"]`). The tool
  fills this in; don't hand-pick a baseline.
- **Years:** always pass an explicit `time_period`. Tax provisions are scored
  **per year**; sweep the standard federal **10-year window (2026–2035)** for a
  budget number, and report the years you actually ran. Do not extrapolate a
  single-year run to a decade in your head — run the years.

---

## 3. Running it

```bash
# validate only (fast, offline with the certified stack installed)
python scripts/tools/policyengine.py validate bills/<slug>/reform.json

# full economy metrics for one year, server-side, pinned to build P (default)
python scripts/tools/policyengine.py economy bills/<slug>/reform.json \
    --year 2026 --provision "<provision title>" --out bills/<slug>/compute-2026.json

# ...pin a different build explicitly
python scripts/tools/policyengine.py economy bills/<slug>/reform.json --year 2026 --dataset <build-tag>

# local run instead (needs a big-memory box; a laptop OOMs on national data)
python scripts/tools/policyengine.py economy bills/<slug>/reform.json --year 2026 --local

# household point-check (fast, no dataset) — for hand-computed arithmetic
python scripts/tools/policyengine.py household bills/<slug>/hh.json --reform bills/<slug>/reform.json
```

Python:

```python
import sys; sys.path.insert(0, "scripts/tools")
import policyengine as pe

run = pe.economy_impact(reform, year=2026)      # server-side, pinned to build P (default), full metrics
# run = pe.economy_local(reform, year=2026)     # local alternative (needs a big-memory box)
block = pe.compute_block(run, provision_title="...")   # bill.json compute entry
```

---

## 4. What you get back — the normalized result

`economy_impact` returns an `EconomyRun`. `run.impact` is stable across
PolicyEngine versions:

| field | meaning |
|-------|---------|
| `budgetary_impact` | change in net federal balance, USD (negative = cost) |
| `tax_revenue_impact`, `benefit_spending_impact` | decomposition |
| `poverty.{all,child,adult,senior}` | `{baseline, reform, pct_change}` (SPM) |
| `deep_poverty.{all,child}` | same shape |
| `decile_average_change`, `decile_relative_change` | by income decile 1–10 |
| `winners_losers` | share gaining / losing >5%, <5%, no change |

Provenance on every run (for the audit): `engine` (local/api), `dataset` (the
pinned Populace build for local runs), `pe_us_version` and `pe_core_version`
(measured; `None` for the hosted API, whose model version is unknowable), `param_source`,
`checked_existence`, `reform_policy_id`, `baseline_policy_id`, `computed_at`.

### Status is not always "ok"

- **`pending`** — the run didn't finish inside the timeout. This is **not an
  error**: report it and **widen the forecast interval**. Never block a pipeline
  waiting silently, and never treat a pending run as zero impact.
- **`error`** — validation failed or the API errored; the message says which.

---

## 5. Attaching the result to the provision

Emit the `bill.json` `compute` block (schema from plan #43) and attach it to the
provision it prices — never to the bill as a whole:

```json
{
  "model": "policyengine-us",
  "reform": { "...": {"...": 0} },
  "year": 2026,
  "region": "us",
  "reform_policy_id": 0,
  "baseline_policy_id": 2,
  "status": "ok",
  "budgetary_impact": -1600000000,
  "result_summary": "2026: budgetary impact -$1.6B, child poverty -0.4% (PolicyEngine static, region=us)",
  "provision_title": "...",
  "caveat": "Static microsim; differs from CBO/JCT by behavioral+timing effects."
}
```

`compute_block(run, provision_title)` builds this for you.

---

## 6. The audit trail

Every `economy_impact` call writes a record to `bills/compute-log/` (reform,
ids, param source, pe_us version, result summary, timestamp — everything but the
multi-MB raw payload). Re-running the logged reform reproduces the run: same
reform + same `pe_us_version` ⇒ same number. That reproduction **is** the audit.

Cross-check tiers, strongest first:
1. **Parameter existence** — `validate` against `policyengine-us`.
2. **Household arithmetic** — `household` on a hand-computed case (offline, exact).
3. **External anchor** — compare the economy number to published scores
   (JCT/CBO, Tax Foundation, Urban, TPC, Yale Budget Lab). Agreement within the
   expected static-vs-official band corroborates the calibration; a large gap is
   an INVESTIGATE, not a silent pass.

See `scripts/tools/CHECKLIST.md` for the passing examples.

---

## 7. Calibration caveat (do not skip)

Static PolicyEngine microsim ≠ official score. Keep a stored ratio/additive prior
from past PolicyEngine-vs-official comparisons and show the adjustment as a math
step. A cell whose **resolution source is an official score** (a CBO/JCT number)
must forecast the *official* number, not the raw microsim — the microsim is an
input to that forecast, with the calibration adjustment applied explicitly.
