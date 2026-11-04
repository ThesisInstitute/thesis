"""PolicyEngine tool — the audited call path ingest/forecast agents use to price
federal tax provisions.

Scope (issue #45, plan #43): FEDERAL, TAX provisions only. This wraps the
PolicyEngine REST API so an agent calls a computational model instead of
estimating by analogy. Every call is validated before it runs and logged after,
so it can be audited against a hand-built invocation.

Design choices
- stdlib only (urllib): the API path needs no extra dependencies, so plain
  `uv sync` stays fast. The certified stack (scripts/tools/requirements-tax.txt) is
  only for the local hand-built cross-check, not for this module.
- One code path for agents and auditors: the CLI subcommands call the same
  functions the agents do, so "hand-built" == "re-run the logged reform".

Contract: see POLICYENGINE.md. Result attaches to a bill.json provision via the
`compute` block (compute_block()).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE_URL = "https://api.policyengine.org"
COUNTRY = "us"
# Current-law baseline policy ids (PolicyEngine convention). Confirmed live: /us/policy/2.
CURRENT_LAW_ID = {"us": 2, "uk": 1}
DATE_RANGE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d{4}-\d{2}-\d{2}$")

# Default federal projection window. Tax provisions are scored per year; the
# window matches the standard 10-year budget window agents should sweep.
DEFAULT_WINDOW = list(range(2026, 2036))

DEFAULT_LOG_DIR = Path("bills/compute-log")

# Populace build to price against locally. Pin the immutable build tag — do NOT
# resolve `latest.json`/`main` (it regressed to a stale build on 2026-07-2x).
# Build P is the current certified release (latest.json, 2026-07-28).
POPULACE_BUILD = "populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z"


def populace_dataset_uri(build: str = POPULACE_BUILD) -> str:
    return f"hf://datasets/policyengine/populace-us/populace_us_2024.h5@{build}"


_CERT_CACHE: dict[str, Optional[dict]] = {}

MODEL_PACKAGE = "policyengine-us"
CORE_PACKAGE = "policyengine-core"


def _exact_pin(packages: Any) -> Optional[str]:
    """The version an exact `==x.y.z` specifier names, else None. A range or a
    missing specifier certifies nothing."""
    spec = ((packages or [{}])[0] or {}).get("specifier", "")
    return spec[2:] if isinstance(spec, str) and spec.startswith("==") and spec[2:] else None


def certified_stack(build: str = POPULACE_BUILD) -> Optional[dict]:
    """The package versions a Populace build is CERTIFIED for, read from the
    build's own release_manifest.json: {"policyengine-us": x, "policyengine-core":
    y or None}. None when the manifest is unreachable or names no exact model pin.
    Build P certifies us==1.764.6 + core==3.26.11; us==1.784.3 has no released
    certified build."""
    if build not in _CERT_CACHE:
        url = ("https://huggingface.co/datasets/policyengine/populace-us/raw/main/"
               f"releases/{build}/release_manifest.json")
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as r:
                man = json.loads(r.read())
            model = _exact_pin(man.get("compatible_model_packages"))
            core = _exact_pin(man.get("compatible_core_packages"))
            _CERT_CACHE[build] = {MODEL_PACKAGE: model, CORE_PACKAGE: core} if model else None
        except Exception:
            _CERT_CACHE[build] = None
    return _CERT_CACHE[build]


def certified_model_version(build: str = POPULACE_BUILD) -> Optional[str]:
    """The policyengine-us version a Populace build is CERTIFIED for. Running any
    other model version against the build is an uncertified pairing — the #45
    audit's core check."""
    stack = certified_stack(build)
    return stack[MODEL_PACKAGE] if stack else None


def certification_note(build: str, running_version: Optional[str], *,
                       running_core_version: Optional[str] = None,
                       validated_against: Optional[str] = None) -> dict:
    """Certify a run's model/data pairing. FAIL-CLOSED: certified only when ALL hold —
      1. the build's release manifest is reachable and pins a policyengine-us version;
      2. the MEASURED running policyengine-us equals that pin;
      3. the measured running policyengine-core equals the manifest's core pin
         (when the manifest pins one);
      4. the reform was validated against that same running model
         (validated_against == "policyengine-us@<running>") — a reform checked on
         another version can name a parameter the running model silently ignores.
    Every refusal carries an explicit reason; nothing yields certified by default.
    `running_*` must be measured in the process that computed (importlib.metadata
    there), never the version a driver asked its installer for."""
    stack = certified_stack(build)
    certified = stack[MODEL_PACKAGE] if stack else None
    certified_core = stack[CORE_PACKAGE] if stack else None
    reasons: list[str] = []
    if certified is None:
        reasons.append(f"CANNOT CERTIFY: release manifest for {build} unreachable or pins no "
                       "exact policyengine-us version — refusing to certify; retry with "
                       "network access to the build manifest.")
    elif running_version is None:
        reasons.append(f"CANNOT CERTIFY: running model version unknown (build certifies "
                       f"policyengine-us=={certified}) — refusing to certify.")
    elif running_version != certified:
        reasons.append(f"UNCERTIFIED PAIRING: build certifies policyengine-us=={certified}, "
                       f"running {running_version}. Install the certified version.")
    if certified_core is not None:
        if running_core_version is None:
            reasons.append(f"CANNOT CERTIFY: running policyengine-core version unknown (build "
                           f"certifies policyengine-core=={certified_core}).")
        elif running_core_version != certified_core:
            reasons.append(f"UNCERTIFIED PAIRING: build certifies policyengine-core=={certified_core}, "
                           f"running {running_core_version}. Install the certified version.")
    if running_version is not None and validated_against != f"{MODEL_PACKAGE}@{running_version}":
        reasons.append(f"CANNOT CERTIFY: reform validated against {validated_against or 'nothing'}, "
                       f"not the running {MODEL_PACKAGE}@{running_version}.")
    return {
        "build": build,
        "certified_model_version": certified,
        "running_model_version": running_version,
        "certified_core_version": certified_core,
        "running_core_version": running_core_version,
        "validated_against": validated_against,
        "certified": not reasons,
        "warning": " ".join(reasons) or None,
    }


class PolicyEngineError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# HTTP (stdlib)                                                                #
# --------------------------------------------------------------------------- #
def _get(path: str, timeout: int = 120) -> tuple[int, Any]:
    req = urllib.request.Request(BASE_URL + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")}


def _post(path: str, body: dict, timeout: int = 120) -> tuple[int, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE_URL + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")}


# --------------------------------------------------------------------------- #
# Parameter source of truth (local-first) + validation                        #
# --------------------------------------------------------------------------- #
# The public API does NOT validate reforms: POST /us/policy returns 201 for
# invented parameters and bad value types, and the economy run then silently
# ignores them. So parameter existence MUST be checked before the run. The
# authoritative offline source is the installed policyengine-us package (see
# requirements-tax.txt). The /us/metadata API is a fallback; structural-only is the last
# resort and is flagged so the auditor knows existence was NOT verified.
_PARAM_CACHE: dict[str, tuple[Optional[set[str]], str]] = {}


def _base_param(path: str) -> str:
    """The dotted parameter name before any bracket index
    (e.g. gov...ctc.amount.base[0].amount -> gov...ctc.amount.base)."""
    return path.split("[", 1)[0]


def policyengine_us_version() -> Optional[str]:
    try:
        from importlib.metadata import version
        return version("policyengine-us")
    except Exception:
        try:
            import policyengine_us  # type: ignore
            return getattr(policyengine_us, "__version__", "unknown")
        except Exception:
            return None


def runtime_stack() -> dict[str, Optional[str]]:
    """The policyengine-us / policyengine-core versions INSTALLED in this process,
    measured from package metadata. None means not measurable — never a guess, and
    never a `__version__` fallback. This is the only admissible source for a
    certification's running versions: a driver's own pin constant is what it asked
    the installer for, not what ran."""
    from importlib.metadata import PackageNotFoundError, version

    out: dict[str, Optional[str]] = {}
    for package in (MODEL_PACKAGE, CORE_PACKAGE):
        try:
            out[package] = version(package)
        except PackageNotFoundError:
            out[package] = None
    return out


def require_runtime_stack(expected: dict[str, str]) -> dict[str, Optional[str]]:
    """Measure the running stack and REFUSE (raise) unless every expected package
    is installed at exactly the expected version. Compute drivers call this in the
    process that prices the reform, before any microsim, and record what it
    returns."""
    stack = runtime_stack()
    bad = {p: (want, stack.get(p)) for p, want in expected.items() if stack.get(p) != want}
    if bad:
        raise PolicyEngineError("runtime stack differs from the certified pins: " + ", ".join(
            f"{p} expected {want}, running {got or 'not installed'}" for p, (want, got) in bad.items()))
    return stack


def _collect_param_names(node, acc: set[str]) -> None:
    name = getattr(node, "name", None)
    if isinstance(name, str) and name:
        acc.add(name)
    for child in getattr(node, "children", {}).values() if hasattr(node, "children") else []:
        _collect_param_names(child, acc)
    for bracket in getattr(node, "brackets", []) or []:
        _collect_param_names(bracket, acc)


def _local_parameters() -> Optional[set[str]]:
    """Every parameter node name in the installed policyengine-us, or None if the
    package is not installed. No microdata needed — just the parameter tree."""
    try:
        from policyengine_us import CountryTaxBenefitSystem  # type: ignore
        params = CountryTaxBenefitSystem().parameters
    except Exception:
        return None
    acc: set[str] = set()
    try:
        for d in params.get_descendants():  # proven path in policyengine-us 1.784
            name = getattr(d, "name", None)
            if isinstance(name, str) and name:
                acc.add(name)
    except Exception:
        try:
            _collect_param_names(params, acc)  # manual-walk fallback
        except Exception:
            return None
    return acc or None


def _api_parameters(country: str) -> Optional[set[str]]:
    status, body = _get(f"/{country}/metadata")
    if status != 200 or not isinstance(body, dict) or "result" not in body:
        return None
    return set(body["result"].get("parameters", {}).keys()) or None


def known_parameters(country: str = COUNTRY) -> tuple[Optional[set[str]], str]:
    """(set of known parameter names, source label). set is None if no
    authoritative source is reachable (structural-only validation)."""
    if country not in _PARAM_CACHE:
        local = _local_parameters()
        if local is not None:
            ver = policyengine_us_version() or "unknown"
            _PARAM_CACHE[country] = (local, f"policyengine-us@{ver}")
        else:
            api = _api_parameters(country)
            _PARAM_CACHE[country] = (api, "metadata-api" if api else "structural-only")
    return _PARAM_CACHE[country]


@dataclass
class ValidationResult:
    ok: bool
    problems: list[str]
    param_source: str          # policyengine-us@x.y | metadata-api | structural-only
    checked_existence: bool    # False when neither package nor metadata was reachable

    def __bool__(self) -> bool:
        return self.ok


def validate_reform(reform: dict, country: str = COUNTRY,
                    allow_unverified: bool = False) -> ValidationResult:
    """First audit gate. Structural checks always run; parameter existence is
    checked against policyengine-us (preferred) or the metadata API. FAIL-CLOSED:
    if existence cannot be verified, the reform is REFUSED (ok=False) unless the
    caller explicitly passes allow_unverified=True — a PE failure must never
    validate by default."""
    problems: list[str] = []
    if not isinstance(reform, dict) or not reform:
        return ValidationResult(False, ["reform must be a non-empty object mapping "
                                        "parameter paths to {date_range: value}"],
                                "structural-only", False)
    known, source = known_parameters(country)
    checked = known is not None
    for path, periods in reform.items():
        if checked:
            base = _base_param(path)
            if base not in known and path not in known:
                problems.append(f"unknown parameter: {path!r} (base {base!r} not in {source})")
        if not isinstance(periods, dict) or not periods:
            problems.append(f"{path!r}: value must be an object {{'YYYY-MM-DD.YYYY-MM-DD': value}}")
            continue
        for drange, value in periods.items():
            if not DATE_RANGE_RE.match(drange):
                problems.append(f"{path!r}: bad date range {drange!r} (want 'YYYY-MM-DD.YYYY-MM-DD')")
            if isinstance(value, bool):
                continue  # in_effect-style booleans are fine
            if not isinstance(value, (int, float)):
                problems.append(f"{path!r}[{drange}]: value must be number/bool, "
                                f"got {type(value).__name__}")
    if not checked:
        if allow_unverified:
            problems.append("WARNING: parameter existence NOT verified (no policyengine-us "
                            "and metadata API unreachable) — proceeding ONLY because "
                            "allow_unverified=True was passed explicitly")
        else:
            problems.append("REFUSED: parameter existence cannot be verified (no "
                            "policyengine-us installed and metadata API unreachable). "
                            "Install the certified stack (scripts/tools/requirements-tax.txt) "
                            "or pass allow_unverified=True to override explicitly.")
    hard_problems = [p for p in problems if not p.startswith("WARNING:")]
    return ValidationResult(not hard_problems, problems, source, checked)


# --------------------------------------------------------------------------- #
# Policies                                                                     #
# --------------------------------------------------------------------------- #
def create_policy(reform: dict, country: str = COUNTRY, validate: bool = True) -> int:
    if validate:
        result = validate_reform(reform, country)
        if not result.ok:
            raise PolicyEngineError(
                f"reform failed validation [{result.param_source}]:\n  - "
                + "\n  - ".join(result.problems)
            )
    status, body = _post(f"/{country}/policy", {"data": reform})
    if status not in (200, 201) or "result" not in body:
        raise PolicyEngineError(f"policy creation failed: {status} {body}")
    return int(body["result"]["policy_id"])


def baseline_id(country: str = COUNTRY) -> int:
    return CURRENT_LAW_ID.get(country, 2)


# --------------------------------------------------------------------------- #
# Result normalization                                                         #
# --------------------------------------------------------------------------- #
def _norm_poverty(pov: dict, group: str) -> dict:
    node = (pov or {}).get(group, {})
    base = node.get("baseline")
    ref = node.get("reform")
    change = None
    if base not in (None, 0) and ref is not None:
        change = (ref - base) / base
    return {"baseline": base, "reform": ref, "pct_change": change}


def normalize_economy(result: dict) -> dict:
    """Collapse the raw economy result into the stable schema agents consume.
    Defensive: tolerates missing sub-keys across PolicyEngine versions."""
    budget = result.get("budget", {}) or {}
    pov = result.get("poverty", {}).get("poverty", {}) if isinstance(result.get("poverty"), dict) else {}
    deep = result.get("poverty", {}).get("deep_poverty", {}) if isinstance(result.get("poverty"), dict) else {}
    decile = result.get("decile", {}) or {}
    intra = result.get("intra_decile", {}) or {}
    return {
        "budgetary_impact": budget.get("budgetary_impact"),
        "tax_revenue_impact": budget.get("tax_revenue_impact"),
        "benefit_spending_impact": budget.get("benefit_spending_impact"),
        "households": budget.get("households"),
        "poverty": {
            "all": _norm_poverty(pov, "all"),
            "child": _norm_poverty(pov, "child"),
            "adult": _norm_poverty(pov, "adult"),
            "senior": _norm_poverty(pov, "senior"),
        },
        "deep_poverty": {"all": _norm_poverty(deep, "all"), "child": _norm_poverty(deep, "child")},
        "decile_average_change": decile.get("average"),
        "decile_relative_change": decile.get("relative"),
        "winners_losers": intra.get("all"),
    }


# --------------------------------------------------------------------------- #
# Economy run (the mechanical cost/distribution call)                         #
# --------------------------------------------------------------------------- #
@dataclass
class EconomyRun:
    status: str  # "ok" | "pending" | "error"
    year: int
    country: str
    region: str
    reform: dict
    reform_policy_id: Optional[int]
    baseline_policy_id: int
    api_version: Optional[str] = None
    impact: dict = field(default_factory=dict)  # normalized (empty if not ok)
    raw: Optional[dict] = None
    message: str = ""
    computed_at: str = ""
    # audit provenance: how the reform was validated + what microdata priced it
    param_source: str = ""            # policyengine-us@x.y | metadata-api | structural-only
    checked_existence: bool = False
    pe_us_version: Optional[str] = None   # MEASURED in the computing process; None when unknowable
    engine: str = "api"               # "api" (hosted, opaque dataset) | "local" | "modal" (pinned build)
    dataset: Optional[str] = None     # Populace build id when engine == "local"
    pe_core_version: Optional[str] = None  # MEASURED, like pe_us_version


def economy_impact(
    reform: dict,
    year: int,
    country: str = COUNTRY,
    region: str = "us",
    baseline: Optional[int] = None,
    dataset: Optional[str] = POPULACE_BUILD,
    timeout_s: int = 900,
    poll_s: int = 20,
    validate: bool = True,
    log_dir: Optional[Path] = DEFAULT_LOG_DIR,
    now: Optional[str] = None,
) -> EconomyRun:
    """Run the reform through PolicyEngine's economy-wide microsim over current law,
    SERVER-SIDE, pinned to a specific Populace build (`dataset`). This is the path
    for full app-v2 metrics: the hosted service returns the same schema app-v2
    renders, on a big enough box, with the baseline cached per-dataset. Local
    national microsim OOMs a laptop; this does not.

    Pass `dataset` as the Populace BUILD TAG (not the hf:// URI — the gateway
    400s on the URI). Returns status 'pending' (not an exception) if still
    computing at timeout — a pending run WIDENS the interval; say so, don't block.
    """
    base = baseline if baseline is not None else baseline_id(country)
    stamp = now or datetime.now(timezone.utc).isoformat()

    # Audit gate: validate BEFORE the run and record how existence was checked.
    v = validate_reform(reform, country) if validate else ValidationResult(True, [], "unvalidated", False)

    def _finish(status: str, **kw) -> EconomyRun:
        # pe_us_version stays None: the hosted service's model version is not
        # knowable from here, and this process's installed version did not price it.
        run = EconomyRun(status, year, country, region, reform, kw.pop("reform_id", None), base,
                         param_source=v.param_source, checked_existence=v.checked_existence,
                         pe_us_version=None, engine="api", dataset=dataset,
                         computed_at=stamp, **kw)
        _log_call(run, log_dir)
        return run

    if not v.ok:
        return _finish("error", message="reform failed validation:\n  - " + "\n  - ".join(v.problems))

    reform_id = create_policy(reform, country, validate=False)
    path = f"/{country}/economy/{reform_id}/over/{base}?region={region}&time_period={year}"
    if dataset:
        path += f"&dataset={urllib.parse.quote(dataset, safe='')}"
    deadline = time.monotonic() + timeout_s
    while True:
        code, body = _get(path)
        if code != 200:
            return _finish("error", reform_id=reform_id, message=f"HTTP {code}: {str(body)[:200]}")
        status_seen = body.get("status", "unknown")
        if status_seen == "ok":
            raw = body["result"]
            return _finish("ok", reform_id=reform_id,
                           api_version=body.get("version") or (raw or {}).get("api_version"),
                           impact=normalize_economy(raw), raw=raw, message="ok")
        if status_seen == "error":
            return _finish("error", reform_id=reform_id, message=str(body.get("message") or body)[:300])
        if time.monotonic() >= deadline:
            return _finish("pending", reform_id=reform_id,
                           message=f"still {status_seen} after {timeout_s}s — widen interval, do not block")
        time.sleep(poll_s)


# --------------------------------------------------------------------------- #
# Local economy run (pinned Populace build — the auditable path)              #
# --------------------------------------------------------------------------- #
def _weighted_child_poverty(sim, year: int) -> float:
    pov = sim.calculate("in_poverty", period=year, map_to="person")
    age = sim.calculate("age", period=year)
    return float(pov[age < 18].mean())


def _weighted_deep_child_poverty(sim, year: int) -> float:
    pov = sim.calculate("in_deep_poverty", period=year, map_to="person")
    age = sim.calculate("age", period=year)
    return float(pov[age < 18].mean())


def economy_local(
    reform: dict,
    year: int,
    build: str = POPULACE_BUILD,
    validate: bool = True,
    log_dir: Optional[Path] = DEFAULT_LOG_DIR,
    now: Optional[str] = None,
) -> EconomyRun:
    """Price the reform LOCALLY on a pinned Populace build. Unlike the hosted API,
    the microdata version is explicit and recorded (`dataset`), so the number is
    reproducible and auditable. Requires the `tax` group (policyengine-us)."""
    stamp = now or datetime.now(timezone.utc).isoformat()
    v = validate_reform(reform, COUNTRY) if validate else ValidationResult(True, [], "unvalidated", False)

    stack = runtime_stack()

    def _finish(status: str, **kw) -> EconomyRun:
        run = EconomyRun(status, year, COUNTRY, "us", reform, None, baseline_id(COUNTRY),
                         param_source=v.param_source, checked_existence=v.checked_existence,
                         pe_us_version=stack[MODEL_PACKAGE], engine="local",
                         dataset=build, computed_at=stamp,
                         pe_core_version=stack[CORE_PACKAGE], **kw)
        _log_call(run, log_dir)
        return run

    if not v.ok:
        return _finish("error", message="reform failed validation:\n  - " + "\n  - ".join(v.problems))

    try:
        import gc
        from policyengine_us import Microsimulation  # type: ignore
        from policyengine_core.reforms import Reform  # type: ignore
    except Exception as e:  # pragma: no cover
        return _finish("error", message=f"policyengine-us not installed (scripts/tools/requirements-tax.txt): {e}")

    ds = populace_dataset_uri(build)

    def _arm_metrics(sim) -> dict:
        # FEDERAL aggregation through the engine's own variables — NOT a
        # household_net_income proxy, which lumps state tax/benefit spillovers
        # into a "federal" number (review finding, #64). income_tax is the
        # federal 1040 net liability including refundable credits. One national
        # microsim resident at a time (16GB box can't hold two).
        fed_tax = float(sim.calculate("income_tax", year).sum())
        try:
            state_tax = float(sim.calculate("state_income_tax", year).sum())
        except Exception:
            state_tax = None
        benefits = float(sim.calculate("household_benefits", year).sum())
        net = float(sim.calculate("household_net_income", year).sum())  # cross-check only
        all_pov = float(sim.calculate("in_poverty", period=year, map_to="person").mean())
        cp = _weighted_child_poverty(sim, year)
        dcp = _weighted_deep_child_poverty(sim, year)
        return {"fed_tax": fed_tax, "state_tax": state_tax, "benefits": benefits,
                "net": net, "all": all_pov, "child": cp, "deep_child": dcp}

    base = _arm_metrics(Microsimulation(dataset=ds))
    gc.collect()  # free the baseline sim before building the reform arm — peak = one sim
    ref = _arm_metrics(Microsimulation(dataset=ds, reform=Reform.from_dict(reform, country_id=COUNTRY)))
    gc.collect()

    tax_revenue_impact = ref["fed_tax"] - base["fed_tax"]            # negative = revenue falls
    benefit_spending_impact = ref["benefits"] - base["benefits"]     # positive = spending rises
    budgetary_impact = tax_revenue_impact - benefit_spending_impact  # negative = cost
    state_spillover = (ref["state_tax"] - base["state_tax"]
                       if ref["state_tax"] is not None and base["state_tax"] is not None else None)
    impact = {
        "budgetary_impact": budgetary_impact,
        "tax_revenue_impact": tax_revenue_impact,
        "benefit_spending_impact": benefit_spending_impact,
        "state_tax_revenue_impact": state_spillover,
        "household_net_income_delta": ref["net"] - base["net"],  # incl. state spillover; cross-check
        "poverty": {
            "all": _pov_block(base["all"], ref["all"]),
            "child": _pov_block(base["child"], ref["child"]),
        },
        "deep_poverty": {"child": _pov_block(base["deep_child"], ref["deep_child"])},
    }
    return _finish("ok", impact=impact, message="ok")


def _pov_block(base: float, ref: float) -> dict:
    change = (ref - base) / base if base else None
    return {"baseline": base, "reform": ref, "pct_change": change}


# --------------------------------------------------------------------------- #
# Household calc (fast, hand-verifiable point checks — no dataset)            #
# --------------------------------------------------------------------------- #
def household_under(household: dict, reform: Optional[dict], country: str = COUNTRY,
                    baseline: bool = False) -> dict:
    """Compute one household under current law (reform=None or baseline=True) or
    under a reform. Fast; used for hand-computed arithmetic checks in the
    correctness checklist."""
    payload = {"household": household}
    if reform and not baseline:
        payload["policy"] = reform
    status, body = _post(f"/{country}/calculate", payload)
    if status != 200 or "result" not in body:
        raise PolicyEngineError(f"household calc failed: {status} {str(body)[:200]}")
    return body["result"]


# --------------------------------------------------------------------------- #
# Audit log                                                                    #
# --------------------------------------------------------------------------- #
def _reform_hash(reform: dict) -> str:
    return hashlib.sha256(json.dumps(reform, sort_keys=True).encode()).hexdigest()[:12]


def _log_call(run: EconomyRun, log_dir: Optional[Path]) -> Optional[Path]:
    if log_dir is None:
        return None
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    h = _reform_hash(run.reform)
    fname = f"{run.computed_at.replace(':', '').replace('-', '')[:15]}-{run.country}-{run.year}-{h}.json"
    record = {k: v for k, v in asdict(run).items() if k != "raw"}
    record["reform_hash"] = h
    path = log_dir / fname
    path.write_text(json.dumps(record, indent=2))
    return path


# --------------------------------------------------------------------------- #
# bill.json compute block                                                      #
# --------------------------------------------------------------------------- #
def compute_block(run: EconomyRun, provision_title: str = "") -> dict:
    """Emit the bill.json `compute` entry that attaches this run to the provision
    it prices. Matches the schema in plan #43."""
    imp = run.impact
    summary = ""
    if run.status == "ok" and imp.get("budgetary_impact") is not None:
        b = imp["budgetary_impact"]
        cp = imp.get("poverty", {}).get("child", {}).get("pct_change")
        cp_txt = f", child poverty {cp*100:+.1f}%" if isinstance(cp, (int, float)) else ""
        src = (f"Populace {run.dataset}, engine={run.engine}"
               if run.engine in ("local", "modal")
               else f"hosted API, region={run.region}")
        summary = f"{run.year}: budgetary impact ${b/1e9:,.1f}B{cp_txt} (PolicyEngine static; {src})"
    elif run.status == "pending":
        summary = f"{run.year}: PolicyEngine run pending — interval widened, not blocked"
    else:
        summary = f"{run.year}: PolicyEngine {run.status} — {run.message}"
    # local/modal runs measure their model + core versions in the process that
    # computed; the hosted API's model version is NOT knowable from api_version
    # (that is the service version) — pass None so certification REFUSES explicitly.
    measured = run.engine in ("local", "modal")
    return {
        "model": "policyengine-us",
        "engine": run.engine,
        "dataset": run.dataset,
        "pe_us_version": run.pe_us_version,
        "pe_core_version": run.pe_core_version,
        "reform": run.reform,
        "year": run.year,
        "region": run.region,
        "reform_policy_id": run.reform_policy_id,
        "baseline_policy_id": run.baseline_policy_id,
        "status": run.status,
        "budgetary_impact": imp.get("budgetary_impact"),
        "poverty_child_pct_change": imp.get("poverty", {}).get("child", {}).get("pct_change"),
        "result_summary": summary,
        "provision_title": provision_title,
        "param_source": run.param_source,
        "certification": certification_note(
            run.dataset,
            run.pe_us_version if measured else None,
            running_core_version=run.pe_core_version if measured else None,
            validated_against=run.param_source if run.checked_existence else None,
        ) if run.dataset else None,
        "caveat": "Static microsim; differs from CBO/JCT by behavioral+timing effects. One evidence stream with its own error bars.",
    }


# --------------------------------------------------------------------------- #
# CLI — same code path agents and auditors use                                #
# --------------------------------------------------------------------------- #
def _load_reform(arg: str) -> dict:
    p = Path(arg)
    return json.loads(p.read_text()) if p.exists() else json.loads(arg)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="PolicyEngine tool for federal tax provisions (issue #45)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Validate a reform dict against live metadata (no run)")
    v.add_argument("reform", help="path to reform JSON or inline JSON")
    v.add_argument("--country", default=COUNTRY)

    e = sub.add_parser("economy", help="Run economy-wide cost/distribution for a reform")
    e.add_argument("reform")
    e.add_argument("--year", type=int, required=True)
    e.add_argument("--country", default=COUNTRY)
    e.add_argument("--region", default="us")
    e.add_argument("--timeout", type=int, default=600)
    e.add_argument("--out", help="write normalized result JSON here")
    e.add_argument("--provision", default="", help="provision title for the compute block")
    e.add_argument("--dataset", default=POPULACE_BUILD,
                   help="Populace build tag pinned server-side for the API run (default: build P)")
    e.add_argument("--local", action="store_true",
                   help="price locally on a pinned Populace build instead of the hosted API (needs a big-memory box)")
    e.add_argument("--build", default=POPULACE_BUILD, help="Populace build id for --local")

    h = sub.add_parser("household", help="Compute a household under baseline and reform")
    h.add_argument("household", help="path to household JSON")
    h.add_argument("--reform", help="path to reform JSON or inline JSON")
    h.add_argument("--country", default=COUNTRY)

    args = ap.parse_args(argv)

    if args.cmd == "validate":
        result = validate_reform(_load_reform(args.reform), args.country)
        tag = f"[{result.param_source}]"
        if result.problems:
            print(f"{'INVALID' if not result.ok else 'OK (with warnings)'} {tag}:\n  - "
                  + "\n  - ".join(result.problems))
            return 0 if result.ok else 1
        print(f"VALID {tag}: all parameters resolve, dates and value types well-formed.")
        return 0

    if args.cmd == "economy":
        reform = _load_reform(args.reform)
        if args.local:
            run = economy_local(reform, args.year, build=args.build)
        else:
            run = economy_impact(reform, args.year, country=args.country,
                                 region=args.region, dataset=args.dataset, timeout_s=args.timeout)
        block = compute_block(run, args.provision)
        print(json.dumps(block, indent=2))
        if args.out:
            Path(args.out).write_text(json.dumps({"run": {k: v for k, v in asdict(run).items() if k != "raw"},
                                                  "compute_block": block}, indent=2))
        return 0 if run.status in ("ok", "pending") else 1

    if args.cmd == "household":
        household = _load_reform(args.household)
        reform = _load_reform(args.reform) if args.reform else None
        base = household_under(household, None, args.country, baseline=True)
        out = {"baseline": base}
        if reform:
            out["reform"] = household_under(household, reform, args.country)
        print(json.dumps(out, indent=2)); return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
