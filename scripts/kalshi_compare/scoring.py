"""Brackets, probabilities, proper scores and paired inference.

Pure functions over floats and Decimals; no I/O. Invariants (tested):

- bracket probabilities are non-negative and sum to 1 for any CDF, any strike
  set and either rounding reading;
- the repaired ladder never increases with the strike and is idempotent;
- the floor-and-renormalize step keeps a distribution and never lowers a
  bracket below the floor;
- log score <= 0 and 0 <= Brier <= 2; both are proper;
- the realized bracket agrees with each binary market's outcome rule.
"""

from __future__ import annotations

import itertools
import math
import random
from decimal import Decimal
from typing import Callable, Sequence

Cdf = Callable[[float], float]


def isotonic_nonincreasing(values: Sequence[float]) -> list[float]:
    """Unweighted pooled-adjacent-violators fit, non-increasing in index."""
    blocks: list[list[float]] = []  # [sum, count]
    for value in values:
        blocks.append([value, 1.0])
        while (
            len(blocks) > 1
            and blocks[-2][0] / blocks[-2][1] < blocks[-1][0] / blocks[-1][1]
        ):
            total, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += count
    out: list[float] = []
    for total, count in blocks:
        out.extend([total / count] * int(count))
    return out


def ladder_violations(values: Sequence[float]) -> int:
    return sum(1 for a, b in zip(values, values[1:]) if b > a + 1e-12)


def ladder_to_brackets(p_yes: Sequence[float]) -> list[float]:
    """P(bracket) from non-increasing P(Y beyond strike_i), n strikes -> n+1 brackets."""
    clipped = [min(1.0, max(0.0, p)) for p in p_yes]
    brackets = [1.0 - clipped[0]]
    brackets += [a - b for a, b in zip(clipped, clipped[1:])]
    brackets.append(clipped[-1])
    return [max(0.0, b) for b in brackets]


def thesis_ladder(
    cdf: Cdf,
    strikes: Sequence[Decimal],
    strike_type: str,
    grid: Decimal,
    to_strike: Decimal,
    reading: str = "rounded",
) -> list[float]:
    """Thesis's P(YES) per ladder market.

    ``reading="rounded"``: the agency publishes Y = round(L, grid) and the CDF
    describes L, so P(Y > s) = 1 - F(s + g/2) and P(Y >= s) = 1 - F(s - g/2).
    ``reading="literal"``: P(Y > s) = P(Y >= s) = 1 - F(s).
    Strikes and grid are in contract units; the CDF is in Thesis units.
    """
    out = []
    for strike in strikes:
        if reading == "literal":
            edge = strike
        elif strike_type == "greater":
            edge = strike + grid / 2
        elif strike_type == "greater_or_equal":
            edge = strike - grid / 2
        else:
            raise ValueError(strike_type)
        out.append(1.0 - cdf(float(edge / to_strike)))
    return out


def thesis_exact(
    cdf: Cdf, values: Sequence[Decimal], grid: Decimal, to_strike: Decimal
) -> list[float]:
    """P(Y == v) for each listed value, then P(any other value)."""
    probs = [
        max(
            0.0,
            cdf(float((v + grid / 2) / to_strike))
            - cdf(float((v - grid / 2) / to_strike)),
        )
        for v in values
    ]
    probs.append(max(0.0, 1.0 - sum(probs)))
    return probs


def market_exact(mids: Sequence[float]) -> list[float]:
    """Listed exact-value prices plus an "any other value" bracket."""
    total = sum(mids)
    if total <= 1.0:
        return list(mids) + [1.0 - total]
    return [m / total for m in mids] + [0.0]


def realized_ladder_bracket(
    value: Decimal, strikes: Sequence[Decimal], strike_type: str
) -> int:
    """Index of the bracket holding ``value`` (0 = below the first strike)."""
    if strike_type == "greater":
        return sum(1 for s in strikes if value > s)
    if strike_type == "greater_or_equal":
        return sum(1 for s in strikes if value >= s)
    raise ValueError(strike_type)


def realized_exact_bracket(value: Decimal, values: Sequence[Decimal]) -> int:
    for index, listed in enumerate(values):
        if value == listed:
            return index
    return len(values)


def floor_renormalize(probs: Sequence[float], floor: float) -> list[float]:
    """Raise every bracket to at least ``floor`` and renormalize.

    Mass is taken proportionally from brackets above the floor, so no bracket
    ends below it and the result sums to 1.
    """
    k = len(probs)
    if floor * k >= 1:
        raise ValueError("floor too large for the number of brackets")
    probs = [max(0.0, p) for p in probs]
    total = sum(probs)
    probs = [p / total for p in probs] if total > 0 else [1.0 / k] * k
    low = [p < floor for p in probs]
    while True:
        need = floor * sum(low)
        free = sum(p for p, is_low in zip(probs, low) if not is_low)
        scale = (1.0 - need) / free
        out = [floor if is_low else p * scale for p, is_low in zip(probs, low)]
        newly_low = [not is_low and o < floor for o, is_low in zip(out, low)]
        if not any(newly_low):
            return out
        low = [a or b for a, b in zip(low, newly_low)]


def log_score(probs: Sequence[float], realized: int) -> float:
    return math.log(probs[realized])


def brier_score(probs: Sequence[float], realized: int) -> float:
    return sum((p - (1.0 if i == realized else 0.0)) ** 2 for i, p in enumerate(probs))


def ladder_brier(p_yes: Sequence[float], outcomes: Sequence[bool]) -> float:
    return sum((p - (1.0 if o else 0.0)) ** 2 for p, o in zip(p_yes, outcomes)) / len(
        p_yes
    )


# Inference -----------------------------------------------------------------

SEED = 20261019
BOOTSTRAP_DRAWS = 10_000
EXACT_LIMIT = 16
MONTE_CARLO_DRAWS = 100_000


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def sign_flip_p(values: Sequence[float], seed: int = SEED) -> float:
    """Two-sided randomization p-value for mean zero under sign symmetry."""
    n = len(values)
    if n == 0:
        return float("nan")
    observed = abs(mean(values)) - 1e-12
    if n <= EXACT_LIMIT:
        hits = 0
        for signs in itertools.product((1, -1), repeat=n):
            if abs(sum(s * v for s, v in zip(signs, values))) / n >= observed:
                hits += 1
        return hits / 2**n
    rng = random.Random(seed)
    hits = 1  # count the observed assignment (Phipson and Smyth)
    for _ in range(MONTE_CARLO_DRAWS):
        total = sum(v if rng.random() < 0.5 else -v for v in values)
        if abs(total) / n >= observed:
            hits += 1
    return hits / (MONTE_CARLO_DRAWS + 1)


def bootstrap_ci(
    values: Sequence[float],
    clusters: Sequence[str] | None = None,
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = SEED,
    level: float = 0.95,
) -> tuple[float, float]:
    """Percentile interval for the mean, resampling clusters if given."""
    if not values:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    if clusters is None:
        clusters = [str(i) for i in range(len(values))]
    groups: dict[str, list[float]] = {}
    for cluster, value in zip(clusters, values):
        groups.setdefault(cluster, []).append(value)
    keys = sorted(groups)
    means = []
    for _ in range(draws):
        sample: list[float] = []
        for _ in keys:
            sample.extend(groups[keys[rng.randrange(len(keys))]])
        means.append(sum(sample) / len(sample))
    means.sort()
    lo_index = int(math.floor((1 - level) / 2 * draws))
    hi_index = int(math.ceil((1 + level) / 2 * draws)) - 1
    return means[lo_index], means[min(hi_index, draws - 1)]


def summarize(values: Sequence[float], clusters: Sequence[str] | None = None) -> dict:
    n = len(values)
    if n == 0:
        return {"n": 0}
    lo, hi = bootstrap_ci(values, clusters)
    wins = sum(1 for v in values if v > 0)
    return {
        "n": n,
        "mean": mean(values),
        "median": (
            sorted(values)[n // 2]
            if n % 2
            else sum(sorted(values)[n // 2 - 1 : n // 2 + 1]) / 2
        ),
        "ci95": [lo, hi],
        "signFlipP": sign_flip_p(values),
        "thesisBetter": wins,
        "kalshiBetter": sum(1 for v in values if v < 0),
        "ties": n - wins - sum(1 for v in values if v < 0),
    }
