"""Calibration, recalibration maps, forward-chained folds and cluster bootstrap.

Pure functions over floats; no I/O. Invariants (tested):

- every recalibration map is non-decreasing in p, for any training data;
- a recalibrated ladder is still non-increasing in the strike, so its brackets
  are non-negative and sum to 1;
- a forward-chained fold never trains on a market whose release instant is at
  or after the fold's earliest horizon instant;
- bootstrap intervals resample whole clusters and are deterministic for a seed.
"""

from __future__ import annotations

import dataclasses
import math
import random
from collections import defaultdict
from typing import Callable, Iterable, Sequence

EPS = 0.001
BINS = 10
SEED = 20261022
MEAN_DRAWS = 10_000
REFIT_DRAWS = 2_000
MIN_TRAIN_CLUSTERS = 20


def clip(p: float) -> float:
    return min(1.0 - EPS, max(EPS, p))


def logit(p: float) -> float:
    p = clip(p)
    return math.log(p / (1.0 - p))


def expit(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


# Fitting -------------------------------------------------------------------


def aggregate(pairs: Iterable[tuple[float, int]]) -> dict[float, list[float]]:
    """p -> [count, successes]; prices sit on a cent or half-cent grid."""
    table: dict[float, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for p, y in pairs:
        cell = table[p]
        cell[0] += 1
        cell[1] += y
    return dict(table)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for a small dense system."""
    n = len(vector)
    a = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-300:
            raise ArithmeticError("singular system")
        a[col], a[pivot] = a[pivot], a[col]
        for row in range(col + 1, n):
            factor = a[row][col] / a[col][col]
            for k in range(col, n + 1):
                a[row][k] -= factor * a[col][k]
    out = [0.0] * n
    for row in range(n - 1, -1, -1):
        out[row] = (a[row][n] - sum(a[row][k] * out[k] for k in range(row + 1, n))) / a[
            row
        ][row]
    return out


def fit_binomial_logit(
    rows: Sequence[tuple[Sequence[float], float, float]], max_iter: int = 200
) -> tuple[list[float], bool]:
    """Maximum-likelihood logistic regression on aggregated rows.

    ``rows`` are (features, count, successes); returns (coefficients,
    converged). Newton steps with step halving on the log-likelihood.
    """
    width = len(rows[0][0])
    beta = [0.0] * width

    def loglik(b: list[float]) -> float:
        total = 0.0
        for x, n, k in rows:
            eta = sum(bi * xi for bi, xi in zip(b, x))
            # log q = -log(1 + e^-eta); log(1 - q) = -log(1 + e^eta)
            total -= k * _log1pexp(-eta) + (n - k) * _log1pexp(eta)
        return total

    current = loglik(beta)
    for _ in range(max_iter):
        grad = [0.0] * width
        hess = [[0.0] * width for _ in range(width)]
        for x, n, k in rows:
            q = expit(sum(bi * xi for bi, xi in zip(beta, x)))
            w = n * q * (1 - q)
            r = k - n * q
            for i in range(width):
                grad[i] += r * x[i]
                for j in range(width):
                    hess[i][j] += w * x[i] * x[j]
        try:
            step = _solve(hess, grad)
        except ArithmeticError:
            return beta, False
        scale = 1.0
        while True:
            trial = [b + scale * s for b, s in zip(beta, step)]
            value = loglik(trial)
            if value >= current - 1e-12 or scale < 1e-8:
                break
            scale /= 2
        delta = max(abs(t - b) for t, b in zip(trial, beta))
        beta, current = trial, value
        if delta < 1e-10:
            return beta, True
    return beta, False


def _log1pexp(x: float) -> float:
    return x + math.log1p(math.exp(-x)) if x > 0 else math.log1p(math.exp(x))


@dataclasses.dataclass(frozen=True)
class Map:
    """A recalibration map p -> q, non-decreasing in p by construction."""

    kind: str  # identity | logistic | beta
    params: tuple[float, ...] = ()
    converged: bool = True

    def __call__(self, p: float) -> float:
        if self.kind == "identity":
            return p
        if self.kind == "logistic":
            a, b = self.params
            return expit(a + b * logit(p))
        if self.kind == "beta":
            c, a, b = self.params
            q = clip(p)
            return expit(c + a * math.log(q) - b * math.log(1.0 - q))
        raise ValueError(self.kind)


IDENTITY = Map("identity")


def fit_logistic(table: dict[float, list[float]]) -> Map:
    """Logistic calibration logit q = a + b logit(p), with b held at 0 if negative."""
    rows = [([1.0, logit(p)], n, k) for p, (n, k) in sorted(table.items())]
    (a, b), converged = fit_binomial_logit(rows)
    if b < 0:
        (a,), converged = fit_binomial_logit([([1.0], n, k) for _, n, k in rows])
        b = 0.0
    return Map("logistic", (a, b), converged)


def fit_beta(table: dict[float, list[float]]) -> Map:
    """Beta calibration (Kull, Silva Filho and Flach 2017) with a, b >= 0.

    logit q = c + a ln p - b ln(1 - p). A coefficient that comes out negative
    is set to 0 and the rest refitted, most negative first.
    """
    items = sorted(table.items())
    active = [True, True]  # a, b
    while True:
        rows = []
        for p, (n, k) in items:
            q = clip(p)
            features = [1.0]
            if active[0]:
                features.append(math.log(q))
            if active[1]:
                features.append(-math.log(1.0 - q))
            rows.append((features, n, k))
        coefs, converged = fit_binomial_logit(rows)
        full = [coefs[0], 0.0, 0.0]
        index = 1
        for slot in (0, 1):
            if active[slot]:
                full[1 + slot] = coefs[index]
                index += 1
        negatives = [(full[1 + s], s) for s in (0, 1) if active[s] and full[1 + s] < 0]
        if not negatives:
            return Map("beta", (full[0], full[1], full[2]), converged)
        active[min(negatives)[1]] = False


FITTERS: dict[str, Callable[[dict], Map]] = {"logistic": fit_logistic, "beta": fit_beta}


# Scores --------------------------------------------------------------------


def binary_log_loss(q: float, y: int) -> float:
    q = clip(q)
    return -math.log(q if y else 1.0 - q)


def binary_brier(q: float, y: int) -> float:
    return (q - y) ** 2


def recalibrated_ladder(ladder: Sequence[float], mapping: Map) -> list[float]:
    """g applied to a repaired (non-increasing) ladder; stays non-increasing."""
    return [mapping(p) for p in ladder]


# Reliability ----------------------------------------------------------------


def bin_of(p: float, bins: int = BINS) -> int:
    return min(bins - 1, max(0, int(p * bins)))


@dataclasses.dataclass
class ClusterStats:
    """Sufficient statistics of one cluster's binary markets."""

    n: list[float]
    sum_p: list[float]
    sum_y: list[float]
    sum_sq: float  # sum of (p - y)^2
    sum_log: float  # sum of binary log loss
    below: list[float]  # [count, sum(y - p)] over p < 0.5
    above: list[float]  # [count, sum(y - p)] over p > 0.5


def cluster_stats(rows: Iterable[tuple[float, int]], bins: int = BINS) -> ClusterStats:
    stats = ClusterStats(
        [0.0] * bins, [0.0] * bins, [0.0] * bins, 0.0, 0.0, [0, 0], [0, 0]
    )
    for p, y in rows:
        b = bin_of(p, bins)
        stats.n[b] += 1
        stats.sum_p[b] += p
        stats.sum_y[b] += y
        stats.sum_sq += (p - y) ** 2
        stats.sum_log += binary_log_loss(p, y)
        if p < 0.5:
            stats.below[0] += 1
            stats.below[1] += y - p
        elif p > 0.5:
            stats.above[0] += 1
            stats.above[1] += y - p
    return stats


def combine(stats: Sequence[ClusterStats], bins: int = BINS) -> ClusterStats:
    out = ClusterStats(
        [0.0] * bins, [0.0] * bins, [0.0] * bins, 0.0, 0.0, [0, 0], [0, 0]
    )
    for s in stats:
        for b in range(bins):
            out.n[b] += s.n[b]
            out.sum_p[b] += s.sum_p[b]
            out.sum_y[b] += s.sum_y[b]
        out.sum_sq += s.sum_sq
        out.sum_log += s.sum_log
        out.below[0] += s.below[0]
        out.below[1] += s.below[1]
        out.above[0] += s.above[0]
        out.above[1] += s.above[1]
    return out


def summary_of(stats: ClusterStats) -> dict:
    """Reliability, Brier and its binned Murphy decomposition, ECE, pattern."""
    total = sum(stats.n)
    if total == 0:
        return {"n": 0}
    base = sum(stats.sum_y) / total
    reliability = (
        sum(
            (stats.sum_p[b] - stats.sum_y[b]) ** 2 / stats.n[b]
            for b in range(len(stats.n))
            if stats.n[b]
        )
        / total
    )
    resolution = (
        sum(
            stats.n[b] * (stats.sum_y[b] / stats.n[b] - base) ** 2
            for b in range(len(stats.n))
            if stats.n[b]
        )
        / total
    )
    brier = stats.sum_sq / total
    return {
        "n": total,
        "brier": brier,
        "logLoss": stats.sum_log / total,
        "baseRate": base,
        "reliability": reliability,
        "resolution": resolution,
        "uncertainty": base * (1 - base),
        "withinBin": brier - (reliability - resolution + base * (1 - base)),
        "ece": (
            sum(abs(stats.sum_p[b] - stats.sum_y[b]) for b in range(len(stats.n)))
            / total
        ),
        "belowHalf": None if not stats.below[0] else stats.below[1] / stats.below[0],
        "aboveHalf": None if not stats.above[0] else stats.above[1] / stats.above[0],
        "bins": [
            {
                "bin": b,
                "lo": b / len(stats.n),
                "hi": (b + 1) / len(stats.n),
                "n": stats.n[b],
                "meanP": None if not stats.n[b] else stats.sum_p[b] / stats.n[b],
                "freq": None if not stats.n[b] else stats.sum_y[b] / stats.n[b],
            }
            for b in range(len(stats.n))
        ],
    }


def percentile_interval(values: list[float], level: float = 0.95) -> list[float]:
    if not values:
        return [float("nan"), float("nan")]
    values = sorted(values)
    lo = int(math.floor((1 - level) / 2 * len(values)))
    hi = min(len(values) - 1, int(math.ceil((1 + level) / 2 * len(values))) - 1)
    return [values[lo], values[hi]]


def bootstrap_reliability(
    clusters: dict[str, ClusterStats], draws: int = MEAN_DRAWS, seed: int = SEED
) -> dict:
    """Point summary plus cluster-bootstrap intervals for its ratio statistics."""
    keys = sorted(clusters)
    point = summary_of(combine([clusters[k] for k in keys]))
    if not keys:
        return point
    rng = random.Random(seed)
    collected: dict[str, list[float]] = defaultdict(list)
    bins = len(point["bins"])
    for _ in range(draws):
        sample = combine([clusters[keys[rng.randrange(len(keys))]] for _ in keys])
        summary = summary_of(sample)
        for name in ("brier", "logLoss", "reliability", "resolution", "ece"):
            collected[name].append(summary[name])
        for name in ("belowHalf", "aboveHalf"):
            if summary[name] is not None:
                collected[name].append(summary[name])
        for b in range(bins):
            if summary["bins"][b]["freq"] is not None:
                collected[f"freq{b}"].append(summary["bins"][b]["freq"])
    point["ci95"] = {
        name: percentile_interval(collected[name])
        for name in (
            "brier",
            "logLoss",
            "reliability",
            "resolution",
            "ece",
            "belowHalf",
            "aboveHalf",
        )
    }
    for b in range(bins):
        point["bins"][b]["ci95"] = percentile_interval(collected[f"freq{b}"])
    point["clusters"] = len(keys)
    return point


def bootstrap_logistic(
    clusters: dict[str, dict[float, list[float]]],
    draws: int = REFIT_DRAWS,
    seed: int = SEED,
) -> dict:
    """Logistic calibration (alpha, beta) with release-date cluster bootstrap.

    The slope here is unconstrained: it is the compression statistic, not a
    recalibration map.
    """
    keys = sorted(clusters)

    def fit(tables: list[dict[float, list[float]]]) -> tuple[float, float, bool]:
        merged: dict[float, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for table in tables:
            for p, (n, k) in table.items():
                merged[p][0] += n
                merged[p][1] += k
        rows = [([1.0, logit(p)], n, k) for p, (n, k) in sorted(merged.items())]
        (a, b), converged = fit_binomial_logit(rows)
        return a, b, converged

    alpha, slope, converged = fit([clusters[k] for k in keys])
    rng = random.Random(seed)
    alphas, slopes, failures = [], [], 0
    for _ in range(draws):
        a, b, ok = fit([clusters[keys[rng.randrange(len(keys))]] for _ in keys])
        if not ok:
            failures += 1
            continue
        alphas.append(a)
        slopes.append(b)
    return {
        "alpha": alpha,
        "beta": slope,
        "converged": converged,
        "alphaCi95": percentile_interval(alphas),
        "betaCi95": percentile_interval(slopes),
        "draws": draws,
        "nonConvergedDraws": failures,
        "clusters": len(keys),
    }


def verdict(beta_ci: Sequence[float]) -> str:
    lo, hi = beta_ci
    if lo > 1:
        return "compressed toward 50%"
    if hi < 1:
        return "too extreme"
    return "neither shown"


def bootstrap_mean(
    values_by_cluster: dict[str, list[float]],
    draws: int = MEAN_DRAWS,
    seed: int = SEED,
) -> dict:
    """Mean over all values, resampling clusters, with a percentile interval."""
    keys = sorted(values_by_cluster)
    values = [v for k in keys for v in values_by_cluster[k]]
    if not values:
        return {"n": 0, "clusters": 0}
    sums = {k: (sum(values_by_cluster[k]), len(values_by_cluster[k])) for k in keys}
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        total = count = 0.0
        for _ in keys:
            s, c = sums[keys[rng.randrange(len(keys))]]
            total += s
            count += c
        means.append(total / count)
    return {
        "n": len(values),
        "clusters": len(keys),
        "mean": sum(values) / len(values),
        "ci95": percentile_interval(means),
    }


def bootstrap_fold_means(
    by_fold: dict[str, float], draws: int = MEAN_DRAWS, seed: int = SEED
) -> dict:
    """Average of per-fold values (folds are release dates), resampling folds."""
    keys = sorted(by_fold)
    if not keys:
        return {"folds": 0}
    rng = random.Random(seed)
    means = [
        sum(by_fold[keys[rng.randrange(len(keys))]] for _ in keys) / len(keys)
        for _ in range(draws)
    ]
    return {
        "folds": len(keys),
        "mean": sum(by_fold.values()) / len(keys),
        "ci95": percentile_interval(means),
    }


# Forward-chained folds -------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Fold:
    cluster: str
    first_instant: int
    train: tuple[int, ...]  # indices into the rows
    test: tuple[int, ...]


def forward_folds(
    clusters: Sequence[str],
    instants: Sequence[int],
    releases: Sequence[int],
    min_clusters: int = MIN_TRAIN_CLUSTERS,
    other_instants: dict[str, int] | None = None,
) -> tuple[list[Fold], list[str]]:
    """One fold per cluster; train on rows released before its first instant.

    ``other_instants`` gives, per cluster, the earliest instant of anything
    else scored in the fold (event-level brackets), so the cutoff also
    precedes those. Returns (evaluated folds, clusters skipped for too little
    history).
    """
    by_cluster: dict[str, list[int]] = defaultdict(list)
    for index, cluster in enumerate(clusters):
        by_cluster[cluster].append(index)
    order = sorted(range(len(releases)), key=lambda i: releases[i])
    folds, skipped = [], []
    for cluster in sorted(by_cluster):
        test = tuple(by_cluster[cluster])
        first = min(instants[i] for i in test)
        if other_instants and cluster in other_instants:
            first = min(first, other_instants[cluster])
        train = tuple(i for i in order if releases[i] < first)
        if len({clusters[i] for i in train}) < min_clusters:
            skipped.append(cluster)
            continue
        folds.append(Fold(cluster, first, train, test))
    return folds, skipped
