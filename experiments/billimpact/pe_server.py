"""Warm PolicyEngine tool server.

Runs inside the isolated policyengine-us venv, keeps the tax-benefit system
loaded, and answers newline-delimited JSON requests on stdin. Cold-starting a
Simulation costs ~4s; warm it is a fraction of that, which is what makes
PolicyEngine usable as a tool inside an LLM loop.

Protocol (one JSON object per line, one JSON response per line):
  {"id": 1, "earnings": 8000, "children": 2, "threshold": 2500, "state": "TX"}
  -> {"id": 1, "ok": true, "refundable_ctc": 825.0, "ctc": 825.0, ...}

`threshold` is the value of gov.irs.credits.ctc.refundable.phase_in.threshold
(current law for 2026 = 2500; the Stronger Start for Working Families Act,
S.3596, sets the underlying IRC 24(d)(1)(B)(i) figure to $1). Omit it for
current law.
"""
from __future__ import annotations

import json
import sys

YEAR = 2026
PARAM = "gov.irs.credits.ctc.refundable.phase_in.threshold"


def build_situation(earnings: float, children: int, state: str, married: bool) -> dict:
    kids = {f"child{i}": {"age": {YEAR: 8 + i}} for i in range(children)}
    adults = {"parent": {"age": {YEAR: 35}, "employment_income": {YEAR: earnings}}}
    marital_members = ["parent"]
    if married:
        adults["spouse"] = {"age": {YEAR: 35}, "employment_income": {YEAR: 0}}
        marital_members.append("spouse")
    members = list(adults) + list(kids)
    return {
        "people": {**adults, **kids},
        "tax_units": {"tu": {"members": members}},
        "families": {"f": {"members": members}},
        "spm_units": {"s": {"members": members}},
        "households": {"h": {"members": members, "state_name": {YEAR: state}}},
        "marital_units": {"mu": {"members": marital_members}},
    }


def main() -> None:
    from policyengine_us import Simulation
    from policyengine_us.system import system as baseline_system
    from policyengine_core.reforms import Reform

    # Cache the *reformed tax-benefit system*, not just the Reform object.
    # Simulation(reform=...) rebuilds the whole system on every call (~6.5s);
    # applying the reform once and reusing the system drops that to ~0.1s.
    system_cache: dict[object, object] = {None: baseline_system}

    def get_system(threshold):
        if threshold not in system_cache:
            reform = Reform.from_dict(
                {PARAM: {f"{YEAR}-01-01.{YEAR}-12-31": threshold}}, country_id="us"
            )
            system_cache[threshold] = reform(baseline_system)
        return system_cache[threshold]

    sys.stdout.write(json.dumps({"ready": True}) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps({"ok": False, "error": f"bad json: {e}"}) + "\n")
            sys.stdout.flush()
            continue
        if req.get("cmd") == "quit":
            break
        try:
            earnings = float(req.get("earnings", 0))
            children = int(req.get("children", 0))
            state = str(req.get("state", "TX")).upper()
            married = bool(req.get("married", False))
            threshold = req.get("threshold")
            threshold = None if threshold is None else float(threshold)

            sim = Simulation(
                situation=build_situation(earnings, children, state, married),
                tax_benefit_system=get_system(threshold),
            )
            out = {
                "id": req.get("id"),
                "ok": True,
                "year": YEAR,
                "inputs": {
                    "earnings": earnings, "children": children, "state": state,
                    "married": married,
                    "phase_in_threshold": threshold if threshold is not None else "current law (2500)",
                },
                "refundable_ctc": round(float(sim.calculate("refundable_ctc", YEAR)[0]), 2),
                "ctc": round(float(sim.calculate("ctc", YEAR)[0]), 2),
            }
        except Exception as e:  # noqa: BLE001
            out = {"id": req.get("id"), "ok": False, "error": f"{type(e).__name__}: {e}"}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
