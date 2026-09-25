"""Hold the Python interval_anchor_v1 port to the TypeScript builders.

site/src/data/prediction-distribution.ts buildNumericCdfFromInterval defines
the immutable interval_anchor_v1 transform; scripts/run_thesis_analyst.py
interval_distribution is its Python port and seals distribution.json at
generation time. Until 2026-09-24 the port rounded with format(x, ".12g"),
which rounds exact decimal ties half-to-even, while ECMAScript toPrecision
picks the larger magnitude: 100000.0078125 became 100000.007812 in Python and
100000.007813 in TypeScript. Parity rested on one fixture at magnitude 5
(test_thesis_analyst_runner.py::test_interval_distribution_matches_typescript_
fixture), whose 404 rounding calls include no exact tie. The 2026-09-24
adversarial review found 1,174 of 40,000 synthetic inputs diverging, every one
at |p| >= 1e5; none of the 390 sealed interval_seeded records had diverged.
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import struct
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_thesis_analyst as analyst_runner  # noqa: E402
from canonical_json import canonical_stringify  # noqa: E402

TS_ORACLE = ROOT / "tests" / "fixtures" / "interval_cdf_parity.ts"
# On 2026-09-24 the seeded corpus drove 39,785 rounding calls (in 735 of its
# 1,805 inputs) through exact ties that the legacy body rounded differently.
# The floor keeps a future corpus edit from quietly losing that bite.
LEGACY_DIVERGENCE_FLOOR = 20_000


def _legacy_round(value: float) -> float:
    # The pre-2026-09-24 body, kept only to prove the corpus below would have
    # caught it. Never call this from production code.
    return float(format(value, ".12g")) + 0.0


def _is_exact_tie(value: float) -> bool:
    # A double sits exactly between two 12-significant-digit neighbours iff
    # its exact decimal expansion has 13 significant digits ending in 5.
    digits = Decimal(value).as_tuple().digits
    return len(digits) == 13 and digits[-1] == 5


def _require_bun() -> str:
    bun = shutil.which("bun")
    if bun is None:
        # GitHub Actions sets CI=true, and both python-tests and bill-pipeline
        # install bun: a silent skip there would retire the only cross-language
        # check on the sealed transform.
        if os.environ.get("CI"):
            pytest.fail("bun is required in CI for the TS/Python parity oracle")
        pytest.skip("bun not on PATH; the TS/Python parity oracle needs it")
    return bun


# Expected values were produced 2026-09-24 by running the site's
# roundDistributionNumber body, Number(x.toPrecision(12)) + 0, under bun 1.3.12
# and printing String(result); test_rounding_table_matches_live_javascript
# re-derives them whenever bun is present so the table cannot drift.
EXACT_TIES = [
    # (input, JavaScript result). Each input is an exact 13-digit tie; the
    # ones whose kept digit is even are where half-to-even disagreed.
    (100000.0078125, 100000.007813),
    (-100000.0078125, -100000.007813),
    (100000.0234375, 100000.023438),
    (-100000.0234375, -100000.023438),
    (1000000.015625, 1000000.01563),
    (-1000000.015625, -1000000.01563),
    (12345678.03125, 12345678.0313),
    (-12345678.03125, -12345678.0313),
    (123456789.0625, 123456789.063),
    (-123456789.0625, -123456789.063),
    (1234567890.125, 1234567890.13),
    (-1234567890.125, -1234567890.13),
    (12345678901.25, 12345678901.3),
    (-12345678901.25, -12345678901.3),
    (98765432109.75, 98765432109.8),
    (-98765432109.75, -98765432109.8),
    (1000000000005.0, 1000000000010.0),
    (-1000000000005.0, -1000000000010.0),
    # Rounding up carries into the next decade (toPrecision -> "1.00...e+13").
    (9999999999995.0, 10000000000000.0),
    (-9999999999995.0, -10000000000000.0),
    # Ties are not confined to large magnitudes: for e <= 11 every odd
    # multiple of 2**(e - 12) inside [10**e, 10**(e + 1)) is one. (Below e = -6
    # no such multiple fits in the decade, so tiny doubles never tie.)
    (12345.00390625, 12345.0039063),
    (-12345.00390625, -12345.0039063),
    (0.1221923828125, 0.122192382813),
    (-0.1221923828125, -0.122192382813),
    (0.001007080078125, 0.00100708007813),
    (-0.001007080078125, -0.00100708007813),
]

NON_TIES = [
    (0.1 + 0.2, 0.3),
    (2.5, 2.5),
    (-2.5, -2.5),
    (181.3625, 181.3625),
    (1 / 3, 0.333333333333),
    (-2 / 3, -0.666666666667),
    # Written as a tie in decimal, but the nearest double is not one.
    (1234567.890125, 1234567.89012),
    (0.00172619047619047, 0.00172619047619),
    (123456789012345680000.0, 123456789012000000000.0),
    (1e21, 1e21),
    (1.5e-7, 1.5e-7),
    (0.0, 0.0),
    (-0.0, 0.0),
    # Subnormals and the extremes of the double range.
    (5e-324, 5e-324),
    (-5e-324, -5e-324),
    (2.2250738585072014e-308, 2.22507385851e-308),
    (1.2345678901234e-310, 1.23456789012e-310),
    (1e-300 / 3, 3.33333333333e-301),
    (1.7976931348623157e308, 1.79769313486e308),
    (-1.7976931348623157e308, -1.79769313486e308),
    (1e300 / 3, 3.33333333333e299),
]


@pytest.mark.parametrize(("value", "expected"), EXACT_TIES + NON_TIES)
def test_round_distribution_number_matches_javascript(
    value: float, expected: float
) -> None:
    actual = analyst_runner.round_distribution_number(value)
    assert actual == expected
    # Same double, not merely an equal one: -0.0 == 0.0 would hide a sign.
    assert json.dumps(actual) == json.dumps(expected)


def test_tie_table_contains_real_ties_that_half_even_got_wrong() -> None:
    assert all(_is_exact_tie(value) for value, _ in EXACT_TIES)
    assert not any(_is_exact_tie(value) for value, _ in NON_TIES)
    legacy_misses = [
        value for value, expected in EXACT_TIES if _legacy_round(value) != expected
    ]
    # Half-to-even and half-away agree when the kept digit is odd, so only a
    # subset diverged; the table must keep both kinds.
    assert 0 < len(legacy_misses) < len(EXACT_TIES)
    assert 100000.0078125 in legacy_misses


def test_non_finite_values_pass_through_like_javascript() -> None:
    # Number(NaN.toPrecision(12)) is NaN and Infinity round-trips; the
    # builders never feed these in, but the port must not raise on them.
    assert math.isnan(analyst_runner.round_distribution_number(math.nan))
    assert analyst_runner.round_distribution_number(math.inf) == math.inf
    assert analyst_runner.round_distribution_number(-math.inf) == -math.inf


def _round_in_javascript(values: list[float]) -> list[float]:
    # The site's roundDistributionNumber body, evaluated by bun. String() is
    # the shortest round-tripping rendering, so float() recovers the double.
    script = (
        "const xs = JSON.parse(await Bun.stdin.text());"
        "console.log(JSON.stringify("
        "xs.map((x) => String(Number(x.toPrecision(12)) + 0))));"
    )
    completed = subprocess.run(
        [_require_bun(), "-e", script],
        input=json.dumps(values),
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return [float(text) for text in json.loads(completed.stdout)]


def test_rounding_table_matches_live_javascript() -> None:
    live = _round_in_javascript([value for value, _ in EXACT_TIES + NON_TIES])
    assert live == [expected for _, expected in EXACT_TIES + NON_TIES]


def test_rounding_matches_javascript_across_the_double_range() -> None:
    rng = random.Random(20260924)
    # Uniform 64-bit patterns cover every exponent, subnormals included.
    values: list[float] = []
    while len(values) < 20_000:
        bits = rng.getrandbits(64).to_bytes(8, "little")
        value = struct.unpack("<d", bits)[0]
        if math.isfinite(value):
            values.append(value)
    # Random patterns almost never land on a tie, so add odd multiples of
    # 2**(e - 12) for decades 1e-6..1e11 (see EXACT_TIES). In the smallest
    # decades an odd multiple can spill into a neighbouring decade, where it
    # is no longer a tie, so keep only the ones that are.
    while len(values) < 40_000:
        exponent = rng.randint(-6, 11)
        g = 2.0 ** (exponent - 12)
        odd = round(rng.uniform(1, 9.9) * 10**exponent / g) | 1
        value = rng.choice((-1, 1)) * odd * g
        if _is_exact_tie(value):
            values.append(value)
    live = _round_in_javascript(values)
    mismatches = [
        (value, expected)
        for value, expected in zip(values, live, strict=True)
        if json.dumps(analyst_runner.round_distribution_number(value))
        != json.dumps(expected)
    ]
    assert mismatches == [], f"{len(mismatches)} differ; first: {mismatches[:3]}"
    # 10,282 of the 20,000 constructed ties split the legacy half-to-even body
    # from JavaScript on 2026-09-24 (the ones whose kept digit is even).
    legacy_misses = sum(
        _legacy_round(value) != expected
        for value, expected in zip(values[20_000:], live[20_000:], strict=True)
    )
    assert legacy_misses >= 5_000


def _parity_corpus() -> list[dict[str, float]]:
    rng = random.Random(20260924)
    cases: list[dict[str, float]] = []

    # Agent-shaped triples: log-uniform magnitudes 1e-3..1e9, both signs,
    # rounded to a few significant digits the way forecasts are written, plus
    # some full-precision doubles.
    def written(value: float) -> float:
        if rng.random() < 0.15:
            return value
        return float(f"{value:.{rng.randint(2, 8)}g}")

    for _ in range(1000):
        magnitude = 10 ** rng.uniform(-3, 9)
        point = written(rng.choice((-1, 1)) * magnitude)
        lower = written(magnitude * 10 ** rng.uniform(-4, -0.3))
        upper = written(magnitude * 10 ** rng.uniform(-4, -0.3))
        cases.append(
            {"pointEstimate": point, "ciLow": point - lower, "ciHigh": point + upper}
        )

    # Constructed exact ties. In the decade [10**e, 10**(e + 1)) every odd
    # multiple of g = 2**(e - 12) is a 13-digit tie. With spreads 2ga and 2gb
    # where a + b = 40c, the support is point - 5ga .. point + 5gb and the
    # grid step (support width / 200) is exactly g*c, so every grid value is
    # an exact multiple of g and, for odd c, every other one is an odd
    # multiple: a tie wherever it stays inside that decade.
    for exponent in range(-3, 12):
        g = 2.0 ** (exponent - 12)
        for _ in range(50):
            point = (
                rng.choice((-1, 1)) * round(rng.uniform(1, 9.9) * 10**exponent / g) * g
            )
            c = rng.choice((1, 1, 3, 5, 7, 2))
            a = rng.randint(1, 40 * c - 1)
            b = 40 * c - a
            cases.append(
                {
                    "pointEstimate": point,
                    "ciLow": point - 2 * g * a,
                    "ciHigh": point + 2 * g * b,
                }
            )

    # In [1e12, 1e13) the ties are the odd multiples of 5. Spreads 10a and
    # 10(80 - a) give support point - 25a .. and a grid step of exactly 10.
    for _ in range(40):
        point = rng.choice((-1, 1)) * 5.0 * rng.randint(2 * 10**11, 19 * 10**11)
        a = rng.randint(1, 79)
        cases.append(
            {
                "pointEstimate": point,
                "ciLow": point - 10.0 * a,
                "ciHigh": point + 10.0 * (80 - a),
            }
        )

    # Branch coverage: degenerate intervals (the 1e-9 spread floor), points
    # outside or between reversed bounds (the abs() spreads), a degenerate
    # interval large enough that the 1.5e-9 floor rounds away and the support
    # collapses (the max(|p|, 1) * 0.1 fallback, hit at 5e7 and 1e20), an
    # overflowing support (the non-finite fallback, then the collapse),
    # signed zeros, and extremes.
    cases.extend(
        [
            {"pointEstimate": 5.0, "ciLow": 5.0, "ciHigh": 5.0},
            {"pointEstimate": 0.0, "ciLow": 0.0, "ciHigh": 0.0},
            {"pointEstimate": -0.0, "ciLow": -0.1, "ciHigh": 0.1},
            {"pointEstimate": 250000.0, "ciLow": 250000.0, "ciHigh": 250000.0},
            {"pointEstimate": 5e7, "ciLow": 5e7, "ciHigh": 5e7},
            {"pointEstimate": 1e20, "ciLow": 1e20, "ciHigh": 1e20},
            {"pointEstimate": 1e308, "ciLow": 9e307, "ciHigh": 1.7e308},
            {"pointEstimate": 3.0, "ciLow": 4.0, "ciHigh": 6.0},
            {"pointEstimate": 10.0, "ciLow": 12.0, "ciHigh": 8.0},
            {"pointEstimate": 1_000_000.0, "ciLow": 1_200_000.0, "ciHigh": 800_000.0},
            {"pointEstimate": -7.5, "ciLow": -2.0, "ciHigh": -9.0},
            {"pointEstimate": 1e15, "ciLow": 9.99e14, "ciHigh": 1.002e15},
            {"pointEstimate": 3e-9, "ciLow": 1e-9, "ciHigh": 7e-9},
            {"pointEstimate": 216.0, "ciLow": 202.0, "ciHigh": 231.0},
            {"pointEstimate": 5.1, "ciLow": 4.6, "ciHigh": 5.8},
        ]
    )
    return cases


def _materialize_python(cases: list[dict[str, float]]) -> list[str]:
    rendered = []
    for case in cases:
        distribution = analyst_runner.interval_distribution(dict(case))
        rendered.append(
            canonical_stringify(
                {"points": distribution["points"], "support": distribution["support"]}
            )
        )
    return rendered


def _numbers(canonical: str) -> list[float]:
    document = json.loads(canonical)
    numbers = [document["support"]["lower"], document["support"]["upper"]]
    for point in document["points"]:
        numbers.extend((point["value"], point["probability"]))
    return [float(number) for number in numbers]


def _materialize_typescript(
    cases: list[dict[str, float]],
) -> tuple[list[str], list[str]]:
    bun = _require_bun()
    completed = subprocess.run(
        [bun, "run", str(TS_ORACLE)],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert len(lines) == 2 * len(cases)
    return lines[0::2], lines[1::2]


def test_interval_builders_agree_byte_for_byte_across_languages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = _parity_corpus()
    assert len({json.dumps(case) for case in cases}) == len(cases)
    site, forecast_api = _materialize_typescript(cases)

    # Count every rounding call the corpus drives through an exact tie that
    # the legacy half-to-even body would have sealed differently: the corpus
    # must keep proving it would catch the 2026-09-24 regression.
    fixed_round = analyst_runner.round_distribution_number
    legacy_divergences = []

    def spy(value: float) -> float:
        rounded = fixed_round(value)
        if _legacy_round(value) != rounded:
            legacy_divergences.append(value)
        return rounded

    monkeypatch.setattr(analyst_runner, "round_distribution_number", spy)
    python = _materialize_python(cases)
    monkeypatch.undo()

    mismatches = []
    for index, case in enumerate(cases):
        expected_numbers = _numbers(site[index])
        for label, rendered in (
            ("python", python[index]),
            ("api", forecast_api[index]),
        ):
            if rendered != site[index] or _numbers(rendered) != expected_numbers:
                mismatches.append((label, case))
    assert mismatches == [], (
        f"{len(mismatches)} of {2 * len(cases)} builds differ from the site "
        f"reference; first: {mismatches[:3]}"
    )
    assert all(_is_exact_tie(value) for value in legacy_divergences)
    assert len(legacy_divergences) >= LEGACY_DIVERGENCE_FLOOR


def test_near_coincident_knots_coalesce_like_typescript() -> None:
    # pointEstimate - ciLow = 1e-13 is nonzero but inside the 1e-12 tolerance,
    # so the knots merge; which value survives moves the whole lower segment
    # (site probability 0.5044029997 vs Python 0.50440296014 at grid point 1
    # before 2026-09-24, when Python kept the LATER knot's value and the
    # site's coalesceCdfKnots the earlier one). No sealed record had
    # near-coincident knots, so aligning the port moved no recorded byte.
    case = {"pointEstimate": 1e-13, "ciLow": 0.0, "ciHigh": 1e-6}
    site, forecast_api = _materialize_typescript([case])
    assert site == forecast_api
    assert _materialize_python([case]) == site


def _rematerialize(distribution: dict) -> dict:
    if distribution.get("provenance") != "interval_seeded":
        return distribution
    summary = distribution["summary"]
    return analyst_runner.interval_distribution(
        {
            "pointEstimate": summary["pointEstimate"],
            "ciLow": summary["interval80"]["lower"],
            "ciHigh": summary["interval80"]["upper"],
        }
    )


def test_recorded_interval_seeded_distributions_rematerialize_byte_for_byte() -> None:
    # Every sealed interval_seeded distribution.json must be exactly what the
    # current port writes (run_thesis_analyst.py serializes with indent=2 and
    # a trailing newline) from its own summary. A rounding change that moved
    # any sealed byte would silently fork the immutable transform.
    checked = 0
    for path in sorted((ROOT / "records").glob("**/distribution.json")):
        raw = path.read_text()
        document = json.loads(raw)
        distributions = document if isinstance(document, list) else [document]
        seeded = sum(d.get("provenance") == "interval_seeded" for d in distributions)
        if not seeded:
            continue
        rebuilt = [_rematerialize(distribution) for distribution in distributions]
        payload = rebuilt if isinstance(document, list) else rebuilt[0]
        assert json.dumps(payload, indent=2) + "\n" == raw, path
        checked += seeded
    # 390 on 2026-09-24; the sealed archive only grows.
    assert checked >= 390
