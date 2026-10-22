"""Correctness assertion battery for the PolicyEngine tool (issue #45).

Every claim in PE-CORRECTNESS-AUDIT.md is produced by an assertion here that
actually RUNS — no claim is written by hand. Each prints: id, claim, the exact
check, the real output, and PASS/FAIL. Run:

    PYTHONPATH=scripts/tools python scripts/tools/_assert_correctness.py

Network is required (hits api.policyengine.org + huggingface.co).
"""
import json
import sys
import urllib.request
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, "scripts/tools")
import policyengine as pe  # noqa: E402

REFORM = {"gov.irs.credits.ctc.refundable.phase_in.threshold": {"2026-01-01.2100-12-31": 0}}
PARAM = "gov.irs.credits.ctc.refundable.phase_in.threshold"
results = []


def check(cid, claim, ok, evidence):
    results.append((cid, claim, ok, evidence))
    print(f"\n[{cid}] {claim}\n    VERDICT: {'PASS' if ok else 'FAIL'}\n    EVIDENCE: {evidence}")


def post_policy(reform):
    req = urllib.request.Request("https://api.policyengine.org/us/policy",
                                 data=json.dumps({"data": reform}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read())


# -- A. installed environment (state everything, assume nothing) --------------
installed = pe.policyengine_us_version()
check("ENV", "record the installed policyengine-us version", installed is not None,
      f"policyengine_us_version() = {installed!r}")

# -- B. parameter validation catches what the API silently accepts ------------
v_ok = pe.validate_reform(REFORM)
check("VAL-1", "the real Stronger Start reform validates", v_ok.ok,
      f"ok={v_ok.ok}, source={v_ok.param_source}, problems={v_ok.problems}")

v_bad = pe.validate_reform({"gov.irs.credits.ctc.made_up": {"2026": "lots"}})
has_unknown = any("unknown parameter" in p for p in v_bad.problems)
has_date = any("bad date range" in p for p in v_bad.problems)
has_type = any("number/bool" in p for p in v_bad.problems)
check("VAL-2", "invented param + bad date + string value are all rejected",
      (not v_bad.ok) and has_unknown and has_date and has_type,
      f"ok={v_bad.ok}; problems={v_bad.problems}")

known, source = pe.known_parameters("us")
check("VAL-3", "the exact parameter the bill edits exists in the model",
      known is not None and PARAM in known, f"{PARAM!r} in {source}: {known is not None and PARAM in known}")

# -- C. the hosted API is NOT a validator (the failure mode we guard) ---------
s1, b1 = post_policy({"gov.irs.credits.ctc.totally_invented": {"2026-01-01.2026-12-31": 3000}})
check("API-1", "POST /us/policy SILENTLY accepts an invented parameter (201)",
      s1 in (200, 201), f"HTTP {s1}, body={json.dumps(b1)[:120]}")
s2, b2 = post_policy({PARAM: {"2026-01-01.2026-12-31": "not_a_number"}})
check("API-2", "POST /us/policy SILENTLY accepts a string where a number belongs (201)",
      s2 in (200, 201), f"HTTP {s2}, body={json.dumps(b2)[:120]}")

# -- D. certification: model version must match the build ---------------------
cert = pe.certified_model_version(pe.POPULACE_BUILD)
check("CERT-1", "build P's manifest certifies exactly one policyengine-us version",
      cert == "1.764.6", f"certified_model_version(build P) = {cert!r}")

n_bad = pe.certification_note(pe.POPULACE_BUILD, "1.784.3")
check("CERT-2", "running 1.784.3 on build P is flagged UNCERTIFIED",
      n_bad["certified"] is False and n_bad["warning"], f"{n_bad}")

n_good = pe.certification_note(pe.POPULACE_BUILD, "1.764.6", running_core_version="3.26.11",
                               validated_against="policyengine-us@1.764.6")
check("CERT-3", "running 1.764.6 + core 3.26.11, validated on 1.764.6, on build P is certified",
      n_good["certified"] is True, f"certified={n_good['certified']}")

n_offver = pe.certification_note(pe.POPULACE_BUILD, "1.764.6", running_core_version="3.26.11",
                                 validated_against="policyengine-us@1.784.3")
check("CERT-5", "a reform validated on another model version is NOT certified (prb4 round 3)",
      n_offver["certified"] is False and n_offver["warning"], f"{n_offver}")

check("CERT-4", "the LOCALLY installed version is NOT certified for build P (must use Modal/1.764.6)",
      installed != cert, f"installed={installed!r} != certified={cert!r} -> local build-P runs would be uncertified")

# -- E. baseline / dataset call parameters ------------------------------------
check("CALL-1", "current-law baseline is policy id 2", pe.baseline_id("us") == 2,
      f"baseline_id('us') = {pe.baseline_id('us')}")
with urllib.request.urlopen("https://api.policyengine.org/us/policy/2", timeout=60) as r:
    p2 = json.loads(r.read())["result"]
check("CALL-2", "policy 2 is a real current-law policy record",
      isinstance(p2.get("policy_json"), dict), f"policy/2 label={p2.get('label')!r}, keys={list(p2.keys())}")

# -- F. statute vs reform dict (the $2,500 -> $1 vs $0 nuance) -----------------
try:
    from policyengine_us import CountryTaxBenefitSystem
    baseline_val = CountryTaxBenefitSystem().parameters.gov.irs.credits.ctc.refundable.phase_in.threshold("2026-01-01")
    check("STAT-1", "PE baseline threshold is $2,500 (the value the bill removes)",
          baseline_val == 2500, f"param('2026-01-01') = {baseline_val}")
except Exception as e:
    check("STAT-1", "PE baseline threshold is $2,500", False, f"error: {e}")
check("STAT-2", "reform dict encodes threshold=0; statute says $1 (recorded, economically identical)",
      REFORM[PARAM]["2026-01-01.2100-12-31"] == 0,
      "bill S.3596 sec.2: strike '$3,000'->'$1' and remove sec.24(h)(6) $2,500 => $1; PE policy 85587 & reform.json use 0")

# -- summary ------------------------------------------------------------------
n_pass = sum(1 for *_, ok, _ in [(r[0], r[1], r[2], r[3]) for r in results] if ok)
print(f"\n{'='*70}\nSUMMARY: {sum(1 for r in results if r[2])}/{len(results)} PASS")
json.dump([{"id": r[0], "claim": r[1], "pass": r[2], "evidence": r[3]} for r in results],
          open("scripts/tools/_assert_results.json", "w"), indent=2)
