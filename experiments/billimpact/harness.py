"""Ablation harness for bill-conditioned forecasting (Leg B).

Design is frozen in PREREGISTRATION.md. This module only *runs* the grid; it
holds no analysis logic and it does not modify any existing repo scoring code.

Every configuration dimension is a pure function of the config dict, so a run
record is fully reproducible from (unit, config, seed) plus the frozen corpus.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).parent
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TRANSPORT = "anthropic_api"

# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------


def _load_anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    env = Path.home() / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("ANTHROPIC_API_KEY not found in env or ~/.env")


_KEY: Optional[str] = None
_KEY_LOCK = threading.Lock()


def _key() -> str:
    global _KEY
    with _KEY_LOCK:
        if _KEY is None:
            _KEY = _load_anthropic_key()
    return _KEY


@dataclass
class CallResult:
    text: str
    ok: bool
    duration_s: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    error: Optional[str] = None


def call_model(
    prompt: str,
    model: str,
    temperature: float = 1.0,
    max_tokens: int = 2000,
    timeout: float = 180.0,
    retries: int = 4,
    effort: Optional[str] = None,
) -> CallResult:
    """One completion through the Anthropic Messages API. Errors returned, not raised.

    `effort` sets reasoning effort ("low"/"medium"/"high"/"max") via adaptive
    thinking + output_config — an elicitation dimension. None = provider default.
    """
    transport = os.environ.get("BILLIMPACT_TRANSPORT", "anthropic")
    payload: dict = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if transport == "openrouter":
        # Model-id mapping + unified reasoning param. "max" maps to "high"
        # (OpenRouter's ceiling); the run record carries transport so arms are
        # never silently mixed across transports.
        payload["model"] = {
            "claude-opus-5": "anthropic/claude-opus-5",
            "claude-fable-5": "anthropic/claude-fable-5",
            "claude-sonnet-5": "anthropic/claude-sonnet-5",
            "claude-haiku-4-5-20251001": "anthropic/claude-haiku-4.5",
        }.get(model, model)
        if effort is not None:
            payload["reasoning"] = {"effort": effort}  # verified passthrough incl. "max"
            payload["temperature"] = 1.0
            payload["max_tokens"] = max(max_tokens, 32000)
    elif effort is not None:
        payload["thinking"] = {"type": "adaptive"}
        payload["output_config"] = {"effort": effort}
        payload["temperature"] = 1.0
        payload["max_tokens"] = max(max_tokens, 32000)
    body = json.dumps(payload).encode()
    start = time.time()
    last = ""
    for attempt in range(retries + 1):
        try:
            if transport == "openrouter":
                or_key = None
                for line in (Path.home() / ".env").read_text().splitlines():
                    if line.startswith("OPENROUTER_API_KEY"):
                        or_key = line.split("=", 1)[1].strip()
                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=body,
                    headers={"Authorization": f"Bearer {or_key}",
                             "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    resp = json.loads(r.read().decode())
                text = resp["choices"][0]["message"]["content"] or ""
                usage = resp.get("usage") or {}
                return CallResult(text=text, ok=True, duration_s=time.time() - start,
                                  prompt_tokens=usage.get("prompt_tokens"),
                                  completion_tokens=usage.get("completion_tokens"))
            req = urllib.request.Request(
                ANTHROPIC_URL,
                data=body,
                headers={
                    "x-api-key": _key(),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = json.loads(r.read().decode())
            blocks = payload.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            usage = payload.get("usage") or {}
            return CallResult(
                text=text,
                ok=True,
                duration_s=time.time() - start,
                prompt_tokens=usage.get("input_tokens"),
                completion_tokens=usage.get("output_tokens"),
            )
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()[:300]
            except Exception:  # noqa: BLE001
                pass
            last = f"HTTP {e.code}: {detail}"
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(min(2.0 * (2**attempt), 20.0) * (0.5 + random.random()))
    return CallResult(text="", ok=False, duration_s=time.time() - start, error=last)


# ---------------------------------------------------------------------------
# D5 — magnitude perturbation (contamination arm)
# ---------------------------------------------------------------------------

MAGNITUDE_SUBSTITUTIONS = {
    "actual": [],
    # DIRECTION, corrected 2026-07-31 ~10:45 EDT (the original comment here had
    # it BACKWARDS): sec. 6(o)(3) lists who is EXEMPT from the ABAWD time
    # limit. Lowering the age cap ("over 31") EXPANDS the exemption -> more
    # people exempt -> participation HIGHER. Raising it ("over 71") SHRINKS the
    # exemption -> participation LOWER. Expected sign of (severe - inert) is
    # therefore POSITIVE. Arm labels are frozen in the pre-registered grid;
    # read "severe" as low_caps and "inert" as high_caps. Data unaffected —
    # substitutions were applied and logged; only this label/comment was wrong.
    "severe": [
        ("over 51 years of age", "over 31 years of age"),
        ("over 53 years of age", "over 33 years of age"),
        ("over 55 years of age", "over 35 years of age"),
    ],
    "inert": [
        ("over 51 years of age", "over 71 years of age"),
        ("over 53 years of age", "over 73 years of age"),
        ("over 55 years of age", "over 75 years of age"),
    ],
}


def apply_magnitude(text: str, magnitude: str) -> tuple[str, int]:
    subs = MAGNITUDE_SUBSTITUTIONS[magnitude]
    n = 0
    for old, new in subs:
        text, k = re.subn(re.escape(old), new, text)
        n += k
    return text, n


# ---------------------------------------------------------------------------
# D1 — policy context
# ---------------------------------------------------------------------------

OPERATIONAL_SUMMARY = (
    "A federal statute enacted on 3 June 2023 modifies the work-requirement "
    "rules for the Supplemental Nutrition Assistance Program. It raises the "
    "upper age bound of the age-based exemption from the able-bodied-adults-"
    "without-dependents time limit in annual steps over fiscal years 2023-2025, "
    "adds categorical exemptions for homeless individuals, veterans, and people "
    "aged 24 or under who were in foster care at 18, and reduces the share of "
    "its caseload a state may exempt at discretion. The new exemption rules "
    "apply to applications for initial certification or recertification "
    "received starting 90 days after enactment."
)


def build_policy_context(provisions: dict[str, str], level: str, magnitude: str) -> tuple[str, dict]:
    """Return (context_block, provenance) for a D1 level."""
    meta = {"level": level, "magnitude": magnitude, "substitutions": 0}
    if level == "none":
        return "", meta
    if level == "summary":
        return (
            "POLICY CONTEXT (operational description):\n" + OPERATIONAL_SUMMARY,
            meta,
        )

    # Amendment-2 levels (PREREG-AMENDMENT-2.md): decompose the P3 effect into
    # named-statute recall / partial-document inference / pure preamble effect.
    SYNTHETIC_EXPAND_PURPOSE = (
        'SEC. 2. PURPOSES. Section 2 of the Food and Nutrition Act of 2008 '
        '(7 U.S.C. 2011) is amended by adding at the end the following: '
        '"That program includes as a purpose to improve access to nutrition '
        'assistance and to increase participation among households eligible '
        'for benefits, so that eligible low-income households more fully '
        'obtain a nutritious diet through normal channels of trade.".'
    )
    COMPLETE_NOTE = (
        "\n\nThe text above is the COMPLETE operative content of the bill. "
        "It contains no other provisions."
    )
    if level == "purpose_unnamed":
        return ("POLICY CONTEXT (verbatim text of an enacted federal statute):\n\n"
                + provisions["sec313_purpose"], meta)
    if level == "purpose_complete":
        # SEC. 313 -> SEC. 2: the original number leaks "this bill has 300+
        # sections", contradicting the complete-text framing. Renumbering is a
        # recorded transformation (meta), not silent editing.
        renumbered = provisions["sec313_purpose"].replace("SEC. 313.", "SEC. 2.", 1)
        meta["renumbered"] = "sec313->sec2"
        return ("POLICY CONTEXT (verbatim text of an enacted federal statute):\n\n"
                + renumbered + COMPLETE_NOTE, meta)
    if level == "purpose_synthetic_expand":
        return ("POLICY CONTEXT (verbatim text of a bill):\n\n"
                + SYNTHETIC_EXPAND_PURPOSE + COMPLETE_NOTE, meta)

    operative_keys = ["sec311_operative", "sec312_operative", "sec314_transparency"]
    purpose_keys = ["sec313_purpose"]
    if level == "operative_only":
        keys = operative_keys
    elif level == "purpose_only":
        keys = purpose_keys
    elif level == "operative_plus_purpose":
        keys = operative_keys + purpose_keys
    else:
        raise ValueError(f"unknown policy_context level: {level}")

    parts = []
    total_subs = 0
    for k in keys:
        text = provisions[k]
        if k == "sec311_operative":
            text, n = apply_magnitude(text, magnitude)
            total_subs += n
        parts.append(text)
    meta["substitutions"] = total_subs
    meta["provisions"] = keys
    header = (
        "POLICY CONTEXT (verbatim statutory text, Fiscal Responsibility Act of "
        "2023, Pub. L. 118-5, enacted 3 June 2023):"
    )
    return header + "\n\n" + "\n\n".join(parts), meta


# ---------------------------------------------------------------------------
# D2 — elicitation format
# ---------------------------------------------------------------------------

BASE_TASK = """You are forecasting a US public-benefit program indicator.

TARGET
  Series: monthly count of SNAP (Supplemental Nutrition Assistance Program) recipients in {state_name} ({state}).
  Units: persons.
  Target month: {target_month_label}.

WHAT YOU KNOW
  The published history of this series, as it stood at the forecast origin, is
  given below. Nothing after the last row was available at the origin.
  Forecast origin: {origin_label}.

HISTORY (month, persons)
{history_block}
"""

ELICITATION_INSTRUCTIONS = {
    "point_ci_json": """Give your forecast for the target month.

Respond with ONLY a JSON object, no prose before or after:
{"point": <number of persons>, "ci_low": <number>, "ci_high": <number>, "rationale": "<one sentence>"}
where [ci_low, ci_high] is your 80% central credible interval.""",
    "free_text": """Give your forecast for the target month in plain prose. State your
central estimate and your 80% credible interval explicitly, in persons. Do not
use JSON, bullet points, or headings — write it as a short paragraph.""",
    "cot_then_json": """Think through the forecast step by step first: establish the base rate from
the history, note the trend and seasonality, then consider any adjustment.
Write your reasoning, then on the FINAL line emit only a JSON object:
{"point": <number of persons>, "ci_low": <number>, "ci_high": <number>, "rationale": "<one sentence>"}
where [ci_low, ci_high] is your 80% central credible interval.""",
    "forced_choice_bins": """Choose exactly one bin for the target month's value, and give an 80% interval
consistent with your choice.

BINS (persons, relative to the last observed value L in the history):
  A: below 0.90 x L
  B: 0.90 x L to 0.95 x L
  C: 0.95 x L to 1.00 x L
  D: 1.00 x L to 1.05 x L
  E: 1.05 x L to 1.10 x L
  F: above 1.10 x L

Respond with ONLY a JSON object:
{"bin": "<A-F>", "point": <number of persons>, "ci_low": <number>, "ci_high": <number>, "rationale": "<one sentence>"}""",
}

STATE_NAMES = {
    "CA": "California", "FL": "Florida", "NY": "New York",
    "TX": "Texas", "PA": "Pennsylvania", "OH": "Ohio",
}

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def month_label(iso: str) -> str:
    y, m, _ = iso.split("-")
    return f"{MONTH_NAMES[int(m) - 1]} {y}"


def format_history(history: list[dict], max_rows: int = 60) -> str:
    rows = history[-max_rows:]
    return "\n".join(f"  {r['month'][:7]}  {int(r['value']):,}" for r in rows)


def build_prompt(unit: dict, provisions: dict, config: dict) -> tuple[str, dict]:
    ctx, ctx_meta = build_policy_context(
        provisions, config["policy_context"], config.get("magnitude", "actual")
    )
    base = BASE_TASK.format(
        state=unit["state"],
        state_name=STATE_NAMES[unit["state"]],
        target_month_label=month_label(unit["target_month"]),
        origin_label=month_label(unit["origin_vintage"]),
        history_block=format_history(unit["history"]),
    )
    parts = [base]
    if ctx:
        parts.append(ctx)
    parts.append(ELICITATION_INSTRUCTIONS[config["elicitation"]])
    return "\n\n".join(parts), ctx_meta


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


PARSER_VERSION = "parse_forecast_v2"

# Cap for the three debate roles; recorded on each call record.
DEBATE_MAX_TOKENS = 2500

# Prose-path scale band, as a multiple of the unit's last OBSERVED history value.
# This is a SCALE filter, not an accuracy filter: it rejects "2023" against a
# series in the millions and accepts any forecast within a factor of five in
# either direction, so a model predicting a 3x collapse is still parsed and then
# scored badly on merit. It is applied to the prose path ONLY — never to the
# JSON path, because D5 (magnitude_elasticity) runs entirely at
# elicitation=point_ci_json and a band on that path would mute the very signal
# D5 exists to measure.
PROSE_BAND_LO, PROSE_BAND_HI = 0.2, 5.0


def _last_json_object(text: str) -> Optional[dict]:
    """Extract the last balanced top-level JSON object in the text."""
    candidates = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start : i + 1])
    for blob in reversed(candidates):
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "point" in obj:
            return obj
    return None


_NUM = r"[-+]?\$?\s*\d[\d,]*(?:\.\d+)?\s*(?:million|thousand|billion|m|k)?"

# ---------------------------------------------------------------------------
# prose extraction
#
# The v1 prose fallback filtered candidate numbers with `n > 1000` and returned
# the FIRST 3-wide window satisfying an ordering test. Calendar years clear
# 1000, and a prose forecast discusses the series history before it states an
# answer, so the first matching window was routinely a run of years: a target
# whose truth is ~5.3 million recipients parsed as point=2021, ci=[2020, 2023].
# 214 of 2520 runs carried a point in [1900, 2100]; 9 carried no interval at all.
# That fired only on prose, which is one LEVEL of a measured dimension (D2
# elicitation), so it did not add noise — it manufactured a difference between
# free_text and JSON that had nothing to do with elicitation format, which is
# precisely the artefact this experiment exists to detect.
#
# v2 replaces the heuristic with four rules:
#   1. reject year-shaped tokens (bare 4-digit integer in [1900, 2100] carrying
#      no thousands separator, decimal point, or scale word);
#   2. keep only candidates within PROSE_BAND of the unit's own last observed
#      value (see the band note above);
#   3. locate the interval from explicit interval LANGUAGE ("80% credible
#      interval ... 4,650,000 to 5,150,000"), taking the LAST such statement,
#      since prose reasons first and answers last;
#   4. take the point from the cue-marked candidate nearest that interval,
#      preferring one that falls inside it.
#
# The parser is strictly EXTRACTIVE. Where a response states an interval but no
# point, or is truncated before it answers, the parse FAILS and is counted; it
# is never repaired by imputing a midpoint the model did not write.
# ---------------------------------------------------------------------------

_MANTISSA = r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?"
_SCALE = r"billions?|millions?|thousands?"
SCALE_WORDS = {
    "billion": 1e9, "billions": 1e9,
    "million": 1e6, "millions": 1e6,
    "thousand": 1e3, "thousands": 1e3,
}

_TOKEN_RE = re.compile(rf"(?<![\w.,])({_MANTISSA})\s*({_SCALE})?\b", re.I)
_RANGE_RE = re.compile(
    rf"(?<![\w.,])({_MANTISSA})\s*({_SCALE})?\s*(?:to|and|through|–|—|-)\s*"
    rf"({_MANTISSA})\s*({_SCALE})?\b",
    re.I,
)
_INTERVAL_CUE = re.compile(
    r"(80\s*%|80\s*percent|credible\s+interval|confidence\s+interval|"
    r"\binterval\b|\brange\b|\bbetween\b|\bfrom\b)",
    re.I,
)
_POINT_CUE = re.compile(
    r"(central\s+estimate|point\s+estimate|best\s+estimate|my\s+estimate|"
    r"\bestimate\b|\bforecast\b|\bexpect\b|\bproject\b|\banticipate\b|"
    r"approximately|roughly|around|about|\bwill\s+be\b)",
    re.I,
)
_CUE_LOOKBACK = 160
_POINT_LOOKBACK = 110

# Numeric literal as it appears as a JSON *value*, for the key-scan recovery.
_KEY_NUM = r"[-+]?\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?"


def _json_keyscan(text: str) -> Optional[dict]:
    """Recover point/ci_low/ci_high from a trailing JSON object that will not parse.

    A response truncated at max_tokens loses its closing brace, and a rationale
    containing a doubled quote breaks `json.loads` outright — in both cases the
    numbers themselves are intact and already written by the model. Reading them
    by key is extraction, not reconstruction: all three keys are required, so a
    partial object fails rather than being completed by inference.
    """
    out: dict[str, float] = {}
    for key in ("point", "ci_low", "ci_high"):
        matches = list(re.finditer(rf'"{key}"\s*:\s*"?({_KEY_NUM})"?', text))
        if not matches:
            return None
        try:
            out[key] = float(matches[-1].group(1).replace(",", ""))
        except ValueError:
            return None
    return out


def _token_value(mantissa: str, scale: Optional[str]) -> Optional[tuple[float, bool]]:
    """Return (value, is_year_shaped), or None if the token is not numeric."""
    try:
        val = float(mantissa.replace(",", ""))
    except ValueError:
        return None
    if scale:
        return val * SCALE_WORDS[scale.lower()], False
    year_shaped = "," not in mantissa and "." not in mantissa and 1900 <= val <= 2100
    return val, year_shaped


def _prose_candidates(text: str, anchor: Optional[float]) -> list[tuple[float, int, int]]:
    lo = anchor * PROSE_BAND_LO if anchor else None
    hi = anchor * PROSE_BAND_HI if anchor else None
    out = []
    for m in _TOKEN_RE.finditer(text):
        parsed = _token_value(m.group(1), m.group(2))
        if parsed is None or parsed[1]:
            continue
        if lo is not None and not (lo <= parsed[0] <= hi):
            continue
        out.append((parsed[0], m.start(), m.end()))
    return out


def _prose_ranges(text: str, anchor: Optional[float]) -> list[tuple[float, float, int, int]]:
    """Numeric ranges preceded by explicit interval language."""
    lo_b = anchor * PROSE_BAND_LO if anchor else None
    hi_b = anchor * PROSE_BAND_HI if anchor else None
    out = []
    for m in _RANGE_RE.finditer(text):
        a = _token_value(m.group(1), m.group(2))
        b = _token_value(m.group(3), m.group(4))
        if a is None or b is None:
            continue
        (av, a_year), (bv, b_year) = a, b
        # "4.65 to 5.15 million": the low bound inherits the high bound's scale.
        if not m.group(2) and m.group(4) and av < 1000:
            av, a_year = av * SCALE_WORDS[m.group(4).lower()], False
        if a_year or b_year or av == bv:
            continue
        if lo_b is not None and not (lo_b <= av <= hi_b and lo_b <= bv <= hi_b):
            continue
        if not _INTERVAL_CUE.search(text[max(0, m.start() - _CUE_LOOKBACK): m.start()]):
            continue
        out.append((min(av, bv), max(av, bv), m.start(), m.end()))
    return out


def parse_prose(text: str, anchor: Optional[float]) -> dict:
    """Extract {point, ci_low, ci_high} from a prose forecast. Never imputes."""
    flat = text.replace("\n", " ")
    cands = _prose_candidates(flat, anchor)
    ranges = _prose_ranges(flat, anchor)

    if ranges:
        lo, hi, r_start, r_end = ranges[-1]
        pool = [c for c in cands if c[2] <= r_start or c[1] >= r_end]
        if not pool:
            return {"parse_error": "interval_without_point", "ci_low": lo,
                    "ci_high": hi, "parse_mode": "failed"}

        def rank(c: tuple[float, int, int]) -> tuple[bool, bool, int]:
            cued = bool(_POINT_CUE.search(flat[max(0, c[1] - _POINT_LOOKBACK): c[1]]))
            inside = lo <= c[0] <= hi
            distance = r_start - c[2] if c[2] <= r_start else c[1] - r_end
            return (not cued, not inside, distance)

        best = min(pool, key=rank)
        out = {"point": best[0], "ci_low": lo, "ci_high": hi, "parse_mode": "prose_cued"}
        if not (lo <= best[0] <= hi):
            out["point_outside_interval"] = True
        return out

    # No interval language: fall back to a bracketing triple, scanned from the
    # TAIL so the answer wins over the reasoning that precedes it.
    for i in range(len(cands) - 3, -1, -1):
        a, b, c = cands[i][0], cands[i + 1][0], cands[i + 2][0]
        if b < a < c or c < a < b:
            return {"point": a, "ci_low": min(b, c), "ci_high": max(b, c),
                    "parse_mode": "prose_bracketed"}
        if a < b < c:
            return {"point": b, "ci_low": a, "ci_high": c, "parse_mode": "prose_ordered"}

    uniq = sorted({c[0] for c in cands})
    if len(uniq) >= 2:
        return {"parse_error": "no_interval_structure", "parse_mode": "failed"}
    if uniq:
        return {"parse_error": "single_value_no_interval", "point_candidate": uniq[0],
                "parse_mode": "failed"}
    return {"parse_error": "no_scale_candidates", "parse_mode": "failed"}


def _to_float(raw: Any) -> Optional[float]:
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower().replace("$", "").replace(",", "").replace("persons", "").strip()
    mult = 1.0
    for suffix, factor in (("billion", 1e9), ("million", 1e6), ("thousand", 1e3), ("m", 1e6), ("k", 1e3)):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            mult = factor
            break
    try:
        return float(s) * mult
    except ValueError:
        return None


def parse_forecast(text: str, elicitation: str, anchor: Optional[float] = None) -> dict:
    """Return {point, ci_low, ci_high, parse_mode} or {'parse_error': ...}.

    `anchor` is the unit's last OBSERVED history value — the scale the answer
    must be on. It gates the prose path only. Callers that cannot supply it get
    year rejection and interval-language anchoring but no scale filter, which is
    strictly weaker; `run_single` always supplies it.
    """
    obj = _last_json_object(text)
    if obj is not None:
        point = _to_float(obj.get("point"))
        lo = _to_float(obj.get("ci_low"))
        hi = _to_float(obj.get("ci_high"))
        if point is not None and lo is not None and hi is not None:
            if lo > hi:
                lo, hi = hi, lo
            out = {"point": point, "ci_low": lo, "ci_high": hi, "parse_mode": "json"}
            if "bin" in obj:
                out["bin"] = obj.get("bin")
            return out

    # A trailing JSON object truncated at max_tokens or broken by a stray quote
    # still carries the model's own numbers; read them by key before falling
    # back to prose heuristics, which would otherwise mine the reasoning.
    scanned = _json_keyscan(text)
    if scanned is not None:
        lo, hi = scanned["ci_low"], scanned["ci_high"]
        if lo > hi:
            lo, hi = hi, lo
        return {"point": scanned["point"], "ci_low": lo, "ci_high": hi,
                "parse_mode": "json_keyscan"}

    return parse_prose(text, anchor)


# ---------------------------------------------------------------------------
# D3 — pipeline
# ---------------------------------------------------------------------------

SKEPTIC_TEMPLATE = """Below is a forecasting task and a draft forecast produced by another analyst.

=== TASK ===
{prompt}

=== DRAFT FORECAST ===
{draft}

You are the SKEPTIC. Your job is to attack this forecast. Identify, specifically:
- any number asserted that the history does not support;
- any claim about the policy that is not supported verbatim by the text supplied
  (quote the text you are relying on, or say the claim is unsupported);
- whether the interval is too narrow for the stated horizon.
Be concrete and brief. Do not produce your own forecast."""

VERIFIER_TEMPLATE = """You are the VERIFIER. Below is a forecasting task, a draft forecast, and a
skeptic's critique.

=== TASK ===
{prompt}

=== DRAFT FORECAST ===
{draft}

=== SKEPTIC ===
{critique}

For each of the skeptic's points, state whether it is CORRECT or INCORRECT and
why, checking against the history and the supplied policy text only. Be brief."""

JUDGE_TEMPLATE = """You are the JUDGE. Below is a forecasting task, a draft forecast, a skeptic's
critique, and a verifier's assessment.

=== TASK ===
{prompt}

=== DRAFT ===
{draft}

=== SKEPTIC ===
{critique}

=== VERIFIER ===
{verification}

Produce the final forecast. Respond with ONLY a JSON object, no prose:
{{"point": <number of persons>, "ci_low": <number>, "ci_high": <number>, "rationale": "<one sentence>"}}
where [ci_low, ci_high] is your 80% central credible interval."""


def history_anchor(unit: dict) -> Optional[float]:
    """Last OBSERVED value in the history the forecaster was shown.

    This is the scale the answer has to be on. It is read from the supplied
    history, never from the realised outcome, so it carries no information about
    the truth the run is scored against.
    """
    history = unit.get("history") or []
    return float(history[-1]["value"]) if history else None


def run_single(unit: dict, provisions: dict, config: dict) -> dict:
    prompt, ctx_meta = build_prompt(unit, provisions, config)
    anchor = history_anchor(unit)
    model = config["model"]
    temp = config.get("temperature", 1.0)
    record: dict[str, Any] = {
        "unit_id": unit["unit_id"],
        "config": dict(config),
        "context_meta": ctx_meta,
        "prompt_chars": len(prompt),
        "calls": [],
    }

    # Caps raised 2026-07-31 14:05 EDT after 5/1753 runs truncated exactly at the
    # cap and lost their JSON. Truncation correlated with elicitation verbosity —
    # i.e. with a measured dimension — so it was a confound, not just data loss.
    # The cap is RECORDED on the call, not left for a reader to mirror. An
    # analysis that hardcodes its own copy of these numbers silently mis-reports
    # truncation the moment the caps move — which they already have once.
    max_tokens = 6000 if config["elicitation"] == "cot_then_json" else 4000
    first = call_model(prompt, model, temperature=temp, max_tokens=max_tokens)
    record["calls"].append(
        {"role": "draft", "ok": first.ok, "duration_s": round(first.duration_s, 2),
         "prompt_tokens": first.prompt_tokens, "completion_tokens": first.completion_tokens,
         "max_tokens": max_tokens, "error": first.error}
    )
    if not first.ok:
        record["error"] = first.error
        return record
    record["draft_text"] = first.text

    if config["pipeline"] == "single_pass":
        record["final_text"] = first.text
        record["forecast"] = parse_forecast(first.text, config["elicitation"], anchor)
        record["parser_version"] = PARSER_VERSION
        return record

    # debate
    critique = call_model(
        SKEPTIC_TEMPLATE.format(prompt=prompt, draft=first.text),
        model, temperature=temp, max_tokens=DEBATE_MAX_TOKENS,
    )
    record["calls"].append({"role": "skeptic", "ok": critique.ok,
                            "duration_s": round(critique.duration_s, 2),
                            "completion_tokens": critique.completion_tokens,
                            "max_tokens": DEBATE_MAX_TOKENS,
                            "error": critique.error})
    if not critique.ok:
        record["error"] = f"skeptic: {critique.error}"
        return record

    verification = call_model(
        VERIFIER_TEMPLATE.format(prompt=prompt, draft=first.text, critique=critique.text),
        model, temperature=temp, max_tokens=DEBATE_MAX_TOKENS,
    )
    record["calls"].append({"role": "verifier", "ok": verification.ok,
                            "duration_s": round(verification.duration_s, 2),
                            "completion_tokens": verification.completion_tokens,
                            "max_tokens": DEBATE_MAX_TOKENS,
                            "error": verification.error})
    if not verification.ok:
        record["error"] = f"verifier: {verification.error}"
        return record

    judged = call_model(
        JUDGE_TEMPLATE.format(prompt=prompt, draft=first.text,
                              critique=critique.text, verification=verification.text),
        model, temperature=temp, max_tokens=DEBATE_MAX_TOKENS,
    )
    record["calls"].append({"role": "judge", "ok": judged.ok,
                            "duration_s": round(judged.duration_s, 2),
                            "completion_tokens": judged.completion_tokens,
                            "max_tokens": DEBATE_MAX_TOKENS,
                            "error": judged.error})
    if not judged.ok:
        record["error"] = f"judge: {judged.error}"
        return record

    record["skeptic_text"] = critique.text
    record["verifier_text"] = verification.text
    record["final_text"] = judged.text
    record["forecast"] = parse_forecast(judged.text, "point_ci_json", anchor)
    record["parser_version"] = PARSER_VERSION
    return record
