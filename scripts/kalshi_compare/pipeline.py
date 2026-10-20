"""End-to-end comparison: inventory, prices, outcomes, scores, inference."""

from __future__ import annotations

import dataclasses
import datetime as dt
import gzip
import json
import pathlib
from decimal import Decimal
from typing import Any

from . import contracts, kalshi, official, scoring, thesis
from .fetch import FetchCache

HORIZONS = ("at_registration", "release_minus_7d", "release_minus_1d")
PRIMARY_SPEC = {"price": "mid", "reading": "rounded", "floor": 0.001}
SENSITIVITY_SPECS = {
    "primary": PRIMARY_SPEC,
    "last_trade_price": {"price": "last", "reading": "rounded", "floor": 0.001},
    "literal_cdf_reading": {"price": "mid", "reading": "literal", "floor": 0.001},
    "floor_0.01": {"price": "mid", "reading": "rounded", "floor": 0.01},
    "liquid_markets_only": {
        "price": "mid",
        "reading": "rounded",
        "floor": 0.001,
        "max_spread": 0.20,
    },
}


@dataclasses.dataclass
class EventUnit:
    spec: contracts.SeriesSpec
    period: str
    event: dict | None
    markets: list[dict]
    runs: list[tuple[thesis.ThesisRun, contracts.ThesisPattern]]
    period_check: str = ""
    settled: bool = False
    official: official.OfficialPrint | None = None
    official_error: str | None = None
    result_mismatches: list[str] = dataclasses.field(default_factory=list)
    candles: dict[str, list[kalshi.Candle]] = dataclasses.field(default_factory=dict)
    candle_tiers: dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.spec.series}:{self.period}"

    @property
    def event_ticker(self) -> str | None:
        return None if self.event is None else self.event["event_ticker"]


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def close_date_et(market: dict) -> dt.date:
    instant = dt.datetime.fromisoformat(market["close_time"].replace("Z", "+00:00"))
    return instant.astimezone(official.ET).date()


def latest_observations(ledger_entries: list[dict]) -> dict[str, dict]:
    """dataPointId -> the last observation row for it (later rows supersede)."""
    out: dict[str, dict] = {}
    for entry in ledger_entries:
        if entry.get("kind") == "observation_recorded":
            out[entry["dataPointId"]] = entry
    return out


def run(
    *,
    repo: pathlib.Path,
    ref: str,
    cache: FetchCache,
    as_of: str,
) -> dict[str, Any]:
    commit = thesis.resolve_ref(repo, ref)
    body_dir = thesis.latest_log_body(repo, commit)
    entries = thesis.load_log_collection(repo, commit, body_dir, "entries")
    timeline = json.loads(thesis.show(repo, commit, "records/witnessed-timeline.json"))
    ledger = json.loads(
        gzip.decompress(thesis.show(repo, commit, f"{body_dir}/ledger.json.gz"))
    )
    observations = latest_observations(ledger["entries"])
    status = thesis.resolution_status(repo, commit)
    resolved = thesis.resolution_events(entries)

    all_runs = thesis.published_runs(entries, timeline)
    in_scope = [r for r in all_runs if r.recorded_at >= thesis.SCOPE_START]

    matched: list[
        tuple[thesis.ThesisRun, contracts.SeriesSpec, str, contracts.ThesisPattern]
    ] = []
    unmatched_runs: list[thesis.ThesisRun] = []
    for run_ in in_scope:
        hits = contracts.match_target(run_.data_point_id)
        if not hits:
            unmatched_runs.append(run_)
            continue
        for spec, period, pattern in hits:
            if run_.unit not in pattern.units:
                raise ValueError(
                    f"{run_.run_id}: unit {run_.unit} not in {pattern.units}"
                )
            matched.append((run_, spec, period, pattern))

    cdfs, distribution_meta = thesis.load_distributions(
        cache, {run_.run_id for run_, *_ in matched}
    )
    for run_, *_ in matched:
        run_.cdf = cdfs.get(run_.run_id)
        run_.cdf_check = thesis.rebuild_check(run_)

    catalog_url = kalshi.build_url(kalshi.API, "/series")
    catalog = cache.get_json(catalog_url)["series"]
    unmatched = unmatched_rows(cache, unmatched_runs)

    # Kalshi events by (series, period).
    units: dict[str, EventUnit] = {}
    events_by_series: dict[str, list[dict]] = {}
    for run_, spec, period, pattern in matched:
        if spec.series not in events_by_series:
            events_by_series[spec.series] = [
                event
                for event in kalshi.series_events(cache, spec.series)
                if not spec.event_prefix
                or event["event_ticker"].startswith(spec.event_prefix)
            ]
        key = f"{spec.series}:{period}"
        if key not in units:
            units[key] = EventUnit(spec, period, None, [], [])
        units[key].runs.append((run_, pattern))

    candidate_periods: dict[str, set[str]] = {}
    for unit in units.values():
        candidate_periods.setdefault(unit.spec.series, set()).add(unit.period)
    for series, events in events_by_series.items():
        cadence = next(
            u.spec.cadence for u in units.values() if u.spec.series == series
        )
        for event in events:
            title_periods = contracts.text_periods(
                f"{event.get('title', '')} {event.get('sub_title', '')}", cadence
            )
            if not title_periods & candidate_periods[series]:
                continue
            markets = kalshi.event_markets(cache, event["event_ticker"])
            period, check = contracts.event_period(event, markets, cadence)
            if period is None:
                continue
            unit = units.get(f"{series}:{period}")
            if unit is None:
                continue
            if unit.event is not None:
                raise ValueError(f"two Kalshi events for {unit.key}")
            unit.event, unit.markets, unit.period_check = event, markets, check

    today = dt.date.fromisoformat(as_of[:10])
    for unit in units.values():
        if unit.event is None or not unit.markets:
            continue
        unit.settled = all(m.get("result") in ("yes", "no") for m in unit.markets)
        release_dates = {close_date_et(m) for m in unit.markets}
        if len(release_dates) != 1:
            unit.official_error = (
                f"markets close on several dates: {sorted(release_dates)}"
            )
            continue
        (release_date,) = release_dates
        if release_date > today:
            continue
        try:
            unit.official = official.fetch_print(
                cache, unit.spec.official, unit.period, release_date
            )
        except (official.OfficialParseError, Exception) as error:  # noqa: BLE001
            unit.official_error = f"{type(error).__name__}: {error}"
            continue
        value = unit.official.value
        for market in unit.markets:
            strike = contracts.strike_of(market, unit.spec)
            yes = contracts.market_yes(
                unit.spec.kind, market.get("strike_type", ""), strike, value
            )
            if market.get("result") not in ("yes" if yes else "no",):
                unit.result_mismatches.append(
                    f"{market['ticker']}: official {value} implies"
                    f" {'yes' if yes else 'no'}, Kalshi result {market.get('result')!r}"
                )
        release_ts = kalshi.to_ts(unit.official.release_at)
        late = [
            m["ticker"]
            for m in unit.markets
            if kalshi.to_ts(m["close_time"]) > release_ts
        ]
        if late:
            unit.result_mismatches.append(f"markets close after the release: {late}")

    # Candles for scored units, over each market's whole life, so the last
    # book before a horizon is found however long ago it changed.
    for unit in units.values():
        if unit.official is None:
            continue
        for market in unit.markets:
            start = kalshi.to_ts(market["open_time"]) - 3600
            end = kalshi.to_ts(market["close_time"])
            candles, tier = kalshi.market_candles(
                cache, unit.spec.series, market, start, end
            )
            unit.candles[market["ticker"]] = candles
            unit.candle_tiers[market["ticker"]] = tier

    scores, market_rows, exclusions = score_units(units)
    pairs = build_pairs(scores)
    summary = summarize_pairs(pairs)

    return {
        "meta": {
            "asOf": as_of,
            "generatedAt": utc_now(),
            "repoRef": ref,
            "commit": commit,
            "logBody": body_dir,
            "distributions": distribution_meta,
            "resolutionStatusAsOf": status.get("asOf"),
            "scopeStart": thesis.SCOPE_START,
            "publishedRuns": len(all_runs),
            "publishedRunsInScope": len(in_scope),
            "ledgerPin": ledger.get("source", {}).get("pin"),
            "kalshiCatalog": {
                "url": catalog_url,
                "sha256": cache.sha256_of(catalog_url),
                "series": len(catalog),
                "economicsSeries": sum(
                    1 for item in catalog if item.get("category") == "Economics"
                ),
            },
            "specs": SENSITIVITY_SPECS,
        },
        "inventory": inventory_rows(units, observations, status, resolved),
        "unmatched": unmatched,
        "withdrawn": withdrawn_cells(repo, commit, all_runs, cache),
        "outcomes": outcome_rows(units, observations),
        "markets": market_rows,
        "scores": scores,
        "pairs": pairs,
        "exclusions": exclusions,
        "summary": summary,
    }


def horizon_times(unit: EventUnit, run_: thesis.ThesisRun) -> dict[str, int]:
    release_ts = kalshi.to_ts(unit.official.release_at)
    return {
        "at_registration": kalshi.to_ts(run_.registration.at),
        "release_minus_7d": release_ts - 7 * 24 * 3600,
        "release_minus_1d": release_ts - 24 * 3600,
    }


def score_units(
    units: dict[str, EventUnit],
) -> tuple[list[dict], list[dict], list[dict]]:
    scores: list[dict] = []
    market_rows: list[dict] = []
    exclusions: list[dict] = []
    for unit in sorted(units.values(), key=lambda u: u.key):
        if unit.official is None:
            continue
        value = unit.official.value
        kind = unit.spec.kind
        strike_types = {m.get("strike_type") for m in unit.markets}
        if kind == "ladder" and len(strike_types) != 1:
            raise ValueError(f"{unit.key}: mixed strike types {strike_types}")
        strike_type = next(iter(strike_types)) if kind == "ladder" else "exact"
        seen_market_rows: set[tuple[str, str, int]] = set()
        for run_, pattern in unit.runs:
            registered = kalshi.to_ts(run_.registration.at)
            for horizon, at in horizon_times(unit, run_).items():
                base = {
                    "eventKey": unit.key,
                    "series": unit.spec.series,
                    "primarySeries": unit.spec.primary,
                    "period": unit.period,
                    "eventTicker": unit.event_ticker,
                    "horizon": horizon,
                    "horizonAt": kalshi.iso(at),
                    "runId": run_.run_id,
                    "forecaster": run_.forecaster,
                    "releaseAt": unit.official.release_at,
                    "releaseDate": unit.official.release_at[:10],
                    "registrationHeadlineEligible": run_.registration.headline_eligible,
                }
                if at < registered:
                    exclusions.append(
                        {**base, "reason": "horizon precedes the Thesis registration"}
                    )
                    continue
                admitted = []
                for market in unit.markets:
                    if kalshi.to_ts(market["open_time"]) > at:
                        continue
                    candles = unit.candles.get(market["ticker"], [])
                    state = kalshi.state_at(candles, at)
                    if state.candle_end is None:
                        exclusions.append(
                            {
                                **base,
                                "ticker": market["ticker"],
                                "reason": "market open but no candle by then",
                            }
                        )
                        continue
                    strike = contracts.strike_of(market, unit.spec)
                    admitted.append((strike, market, state))
                    row_key = (market["ticker"], horizon, at)
                    if row_key not in seen_market_rows:
                        seen_market_rows.add(row_key)
                        market_rows.append(
                            {
                                "eventKey": unit.key,
                                "horizon": horizon,
                                "horizonAt": kalshi.iso(at),
                                "ticker": market["ticker"],
                                "strike": str(strike),
                                "strikeType": market.get("strike_type"),
                                "bid": state.bid,
                                "ask": state.ask,
                                "mid": state.mid,
                                "lastTrade": state.last,
                                "spread": state.spread,
                                "candleAgeHours": (at - state.candle_end) / 3600,
                                "openInterest": state.open_interest,
                                "volume7d": state.volume_7d,
                                "volumeToHorizon": sum(
                                    c.volume for c in candles if c.end <= at
                                ),
                                "lifetimeVolume": kalshi.market_volume(market),
                                "result": market.get("result"),
                                "tier": unit.candle_tiers.get(market["ticker"]),
                            }
                        )
                if not admitted:
                    exclusions.append(
                        {**base, "reason": "no Kalshi market quoted by then"}
                    )
                    continue
                admitted.sort(key=lambda item: item[0])
                strikes = [s for s, _, _ in admitted]
                if len(set(strikes)) != len(strikes):
                    raise ValueError(f"{unit.key}: duplicate strikes {strikes}")
                for spec_name, spec in SENSITIVITY_SPECS.items():
                    chosen = admitted
                    if "max_spread" in spec:
                        chosen = [
                            item
                            for item in admitted
                            if item[2].spread is not None
                            and item[2].spread <= spec["max_spread"] + 1e-9
                        ]
                        if not chosen:
                            exclusions.append(
                                {
                                    **base,
                                    "spec": spec_name,
                                    "reason": (
                                        "no market quoted within the spread limit"
                                    ),
                                }
                            )
                            continue
                    scores.append(
                        score_one(
                            base,
                            spec_name,
                            spec,
                            unit,
                            run_,
                            pattern,
                            kind,
                            strike_type,
                            [s for s, _, _ in chosen],
                            chosen,
                            value,
                        )
                    )
    return scores, market_rows, exclusions


def score_one(
    base,
    spec_name,
    spec,
    unit,
    run_,
    pattern,
    kind,
    strike_type,
    strikes,
    admitted,
    value,
):
    def price(state: kalshi.MarketState) -> float:
        if spec["price"] == "last" and state.last is not None:
            return state.last
        return state.mid

    raw = [price(state) for _, _, state in admitted]
    cdf = lambda x: thesis.cdf_at(run_.cdf, x)  # noqa: E731
    if kind == "ladder":
        repaired = scoring.isotonic_nonincreasing(raw)
        kalshi_brackets = scoring.ladder_to_brackets(repaired)
        thesis_yes = scoring.thesis_ladder(
            cdf,
            strikes,
            strike_type,
            unit.spec.grid,
            pattern.to_strike,
            spec["reading"],
        )
        thesis_brackets = scoring.ladder_to_brackets(thesis_yes)
        realized = scoring.realized_ladder_bracket(value, strikes, strike_type)
        outcomes = [contracts.market_yes(kind, strike_type, s, value) for s in strikes]
        ladder = {
            "thesisLadderBrier": scoring.ladder_brier(thesis_yes, outcomes),
            "kalshiLadderBrier": scoring.ladder_brier(repaired, outcomes),
        }
        violations = scoring.ladder_violations(raw)
    else:
        kalshi_brackets = scoring.market_exact(raw)
        thesis_brackets = scoring.thesis_exact(
            cdf, strikes, unit.spec.grid, pattern.to_strike
        )
        realized = scoring.realized_exact_bracket(value, strikes)
        ladder = {"thesisLadderBrier": None, "kalshiLadderBrier": None}
        violations = 0
        repaired = raw
    floor = spec["floor"]
    thesis_floored = scoring.floor_renormalize(thesis_brackets, floor)
    kalshi_floored = scoring.floor_renormalize(kalshi_brackets, floor)
    return {
        **base,
        "spec": spec_name,
        "nMarkets": len(strikes),
        "strikes": [str(s) for s in strikes],
        "officialValue": str(value),
        "realizedBracket": realized,
        "thesisBrackets": thesis_brackets,
        "kalshiBrackets": kalshi_brackets,
        "kalshiRawPrices": raw,
        "kalshiRepairedPrices": repaired,
        "ladderViolations": violations,
        "thesisRealizedProb": thesis_brackets[realized],
        "kalshiRealizedProb": kalshi_brackets[realized],
        "thesisFloored": thesis_brackets[realized] < floor,
        "kalshiFloored": kalshi_brackets[realized] < floor,
        "thesisLog": scoring.log_score(thesis_floored, realized),
        "kalshiLog": scoring.log_score(kalshi_floored, realized),
        "thesisBrier": scoring.brier_score(thesis_brackets, realized),
        "kalshiBrier": scoring.brier_score(kalshi_brackets, realized),
        **ladder,
        "registrationCoverage": run_.registration.coverage,
        "registeredAt": run_.registration.at,
    }


def build_pairs(scores: list[dict]) -> list[dict]:
    pairs = []
    for row in scores:
        pair = {
            k: row[k]
            for k in (
                "eventKey",
                "series",
                "primarySeries",
                "period",
                "eventTicker",
                "horizon",
                "horizonAt",
                "runId",
                "forecaster",
                "spec",
                "releaseDate",
                "nMarkets",
                "officialValue",
                "thesisRealizedProb",
                "kalshiRealizedProb",
                "thesisLog",
                "kalshiLog",
                "thesisBrier",
                "kalshiBrier",
                "thesisLadderBrier",
                "kalshiLadderBrier",
                "registrationCoverage",
                "registeredAt",
                "registrationHeadlineEligible",
            )
        }
        pair["deltaLog"] = row["thesisLog"] - row["kalshiLog"]
        pair["deltaBrier"] = row["kalshiBrier"] - row["thesisBrier"]
        if row["thesisLadderBrier"] is not None:
            pair["deltaLadderBrier"] = (
                row["kalshiLadderBrier"] - row["thesisLadderBrier"]
            )
        else:
            pair["deltaLadderBrier"] = None
        pairs.append(pair)
    return pairs


def primary_pairs(pairs: list[dict], forecaster: str = "thesis_headline") -> list[dict]:
    """One pair per (event, horizon, spec): the earliest-registered run of a role."""
    chosen: dict[tuple, dict] = {}
    for pair in sorted(pairs, key=lambda p: (p["registeredAt"], p["runId"])):
        if pair["forecaster"] != forecaster:
            continue
        key = (pair["eventKey"], pair["horizon"], pair["spec"])
        current = chosen.get(key)
        if current is None:
            chosen[key] = pair
    return list(chosen.values())


def two_stage_ci(groups: dict[str, list[float]]) -> tuple[float, float]:
    """Series-balanced mean: resample series, then events within each series.

    Treating series as fixed strata ignores between-series variation and is
    far too narrow when most series hold two or three events.
    """
    import random

    rng = random.Random(scoring.SEED)
    keys = sorted(groups)
    means = []
    for _ in range(scoring.BOOTSTRAP_DRAWS):
        series_means = []
        for _ in keys:
            values = groups[keys[rng.randrange(len(keys))]]
            sample = [values[rng.randrange(len(values))] for _ in values]
            series_means.append(sum(sample) / len(sample))
        means.append(sum(series_means) / len(series_means))
    means.sort()
    return means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]


def summarize_pairs(pairs: list[dict]) -> dict:
    out: dict[str, Any] = {}
    for forecaster in sorted({p["forecaster"] for p in pairs}):
        chosen = primary_pairs(pairs, forecaster)
        by_spec: dict[str, Any] = {}
        for spec_name in SENSITIVITY_SPECS:
            by_horizon: dict[str, Any] = {}
            spec_rows = [p for p in chosen if p["spec"] == spec_name]
            at_registration = {
                p["eventKey"] for p in spec_rows if p["horizon"] == "at_registration"
            }
            for horizon in HORIZONS:
                rows = [p for p in spec_rows if p["horizon"] == horizon]
                summary = summarize_rows(rows)
                # Subsets the review asked for: the same events as the
                # registration comparison, and runs whose custody root
                # Thesis's own verifier marks headline eligible.
                summary["sameEventsAsRegistration"] = summarize_rows(
                    [r for r in rows if r["eventKey"] in at_registration]
                )["pooled"]
                summary["headlineEligibleOnly"] = summarize_rows(
                    [
                        r
                        for r in rows
                        if r.get("registrationHeadlineEligible") is not False
                    ]
                )["pooled"]
                by_horizon[horizon] = summary
            by_spec[spec_name] = by_horizon
        out[forecaster] = by_spec
    out["thesis_vs_persistence"] = thesis_vs_baseline(pairs)
    return out


def thesis_vs_baseline(pairs: list[dict]) -> dict:
    """Thesis headline minus the persistence baseline on identical brackets.

    Only release-anchored horizons qualify: there both runs face the same
    Kalshi strike set at the same instant. Positive favors Thesis.
    """
    head = {
        (p["eventKey"], p["horizon"], p["spec"]): p
        for p in primary_pairs(pairs, "thesis_headline")
    }
    base = {
        (p["eventKey"], p["horizon"], p["spec"]): p
        for p in primary_pairs(pairs, "persistence_baseline")
    }
    out: dict[str, Any] = {}
    for spec_name in SENSITIVITY_SPECS:
        by_horizon: dict[str, Any] = {}
        for horizon in ("release_minus_7d", "release_minus_1d"):
            keys = sorted(
                k for k in head.keys() & base.keys() if k[1:] == (horizon, spec_name)
            )
            rows = []
            for key in keys:
                h, b = head[key], base[key]
                rows.append(
                    {
                        "series": h["series"],
                        "deltaLog": h["thesisLog"] - b["thesisLog"],
                        "deltaBrier": b["thesisBrier"] - h["thesisBrier"],
                    }
                )
            by_series: dict[str, Any] = {}
            for series in sorted({r["series"] for r in rows}):
                items = [r for r in rows if r["series"] == series]
                by_series[series] = {
                    metric: scoring.summarize([r[metric] for r in items])
                    for metric in ("deltaLog", "deltaBrier")
                }
            by_horizon[horizon] = {
                "bySeries": by_series,
                "pooled": (
                    {
                        metric: scoring.summarize([r[metric] for r in rows])
                        for metric in ("deltaLog", "deltaBrier")
                    }
                    if rows
                    else {}
                ),
            }
        out[spec_name] = by_horizon
    return out


def summarize_rows(rows: list[dict]) -> dict:
    result: dict[str, Any] = {"bySeries": {}, "pooled": {}}
    for metric in ("deltaLog", "deltaBrier", "deltaLadderBrier"):
        usable = [r for r in rows if r[metric] is not None]
        groups: dict[str, list[dict]] = {}
        for row in usable:
            groups.setdefault(row["series"], []).append(row)
        for series, items in sorted(groups.items()):
            result["bySeries"].setdefault(series, {})[metric] = scoring.summarize(
                [r[metric] for r in items]
            )
        primary = [r for r in usable if r["primarySeries"]]
        if primary:
            values = [r[metric] for r in primary]
            pooled = scoring.summarize(values)
            pooled["ci95ReleaseClustered"] = list(
                scoring.bootstrap_ci(values, [r["releaseDate"] for r in primary])
            )
            series_groups: dict[str, list[float]] = {}
            for row in primary:
                series_groups.setdefault(row["series"], []).append(row[metric])
            balanced = sum(sum(v) / len(v) for v in series_groups.values()) / len(
                series_groups
            )
            pooled["seriesBalancedMean"] = balanced
            pooled["seriesBalancedCi95TwoStage"] = list(two_stage_ci(series_groups))
            pooled["nSeries"] = len(series_groups)
            result["pooled"][metric] = pooled
    return result


def inventory_rows(units, observations, status, resolved) -> list[dict]:
    rows = []
    for unit in sorted(units.values(), key=lambda u: u.key):
        for run_, pattern in unit.runs:
            target_status = status["targets"].get(run_.data_point_id, {})
            observation = observations.get(run_.data_point_id)
            rows.append(
                {
                    "runId": run_.run_id,
                    "slug": run_.slug,
                    "dataPointId": run_.data_point_id,
                    "forecaster": run_.forecaster,
                    "agent": run_.agent,
                    "model": run_.model,
                    "label": run_.label,
                    "recordedAt": run_.recorded_at,
                    "registeredAt": run_.registration.at,
                    "registrationCoverage": run_.registration.coverage,
                    "witnessDigest": run_.registration.witness_digest,
                    "headlineEligibleRoot": run_.registration.headline_eligible,
                    "unit": run_.unit,
                    "pointEstimate": run_.point,
                    "interval80Low": run_.ci_low,
                    "interval80High": run_.ci_high,
                    "distributionProvenance": run_.provenance,
                    "transformVersion": run_.transform_version,
                    "publishedCdfCheck": run_.cdf_check,
                    "kalshiSeries": unit.spec.series,
                    "primarySeries": unit.spec.primary,
                    "period": unit.period,
                    "kalshiEvent": unit.event_ticker,
                    "kalshiEventCheck": (
                        unit.period_check or "no Kalshi event for this period"
                    ),
                    "kalshiSettled": unit.settled,
                    "officialRelease": (
                        None if unit.official is None else unit.official.release_at
                    ),
                    "officialValue": (
                        None if unit.official is None else str(unit.official.value)
                    ),
                    "officialError": unit.official_error,
                    "thesisResolverState": (
                        target_status.get("state")
                        or ("resolved" if run_.data_point_id in resolved else None)
                    ),
                    "thesisResolverCode": target_status.get("code"),
                    "thesisLedgerValue": (
                        None if observation is None else observation.get("value")
                    ),
                    "thesisResolved": run_.data_point_id in resolved,
                }
            )
    return rows


def outcome_rows(units, observations) -> list[dict]:
    rows = []
    for unit in sorted(units.values(), key=lambda u: u.key):
        if unit.event is None:
            continue
        expiration = sorted({str(m.get("expiration_value")) for m in unit.markets})
        data_points = sorted({r.data_point_id for r, _ in unit.runs})
        thesis_values = {
            dp: observations[dp].get("value")
            for dp in data_points
            if dp in observations
        }
        scale = unit.runs[0][1].to_strike
        thesis_in_strike_units = {
            dp: str(Decimal(str(v)) * scale) for dp, v in thesis_values.items()
        }
        official_value = None if unit.official is None else unit.official.value
        agrees = None
        if official_value is not None and thesis_in_strike_units:
            agrees = all(
                Decimal(v) == official_value for v in thesis_in_strike_units.values()
            )
        rows.append(
            {
                "eventKey": unit.key,
                "eventTicker": unit.event_ticker,
                "period": unit.period,
                "settled": unit.settled,
                "officialValue": (
                    None if official_value is None else str(official_value)
                ),
                "officialSecondReading": (
                    None if unit.official is None else unit.official.second_reading
                ),
                "releaseAt": (
                    None if unit.official is None else unit.official.release_at
                ),
                "sourceUrl": (
                    None if unit.official is None else unit.official.source_url
                ),
                "sourceSha256": (
                    None if unit.official is None else unit.official.source_sha256
                ),
                "officialError": unit.official_error,
                "kalshiExpirationValues": expiration,
                "kalshiResultMismatches": unit.result_mismatches,
                "thesisLedgerValues": thesis_in_strike_units,
                "thesisLedgerAgreesWithOfficial": agrees,
                "nMarkets": len(unit.markets),
                "expectedRelease": (
                    close_date_et(unit.markets[0]).isoformat() if unit.markets else None
                ),
                "lifetimeVolume": sum(
                    kalshi.market_volume(m) or 0.0 for m in unit.markets
                ),
            }
        )
    return rows


def unmatched_rows(cache: FetchCache, runs: list[thesis.ThesisRun]) -> list[dict]:
    """Every in-scope run with no matching Kalshi event, with the evidence.

    For statistics where the catalog screen found a related Kalshi series,
    the series' events are fetched and the run's period looked up, so the
    reason says what Kalshi lists rather than asserting it.
    """
    events_by_series: dict[str, dict[str, list[str]]] = {}

    def periods_for(series: str) -> dict[str, list[str]]:
        if series not in events_by_series:
            by_period: dict[str, list[str]] = {}
            for event in kalshi.series_events(cache, series):
                text = f"{event.get('title', '')} {event.get('sub_title', '')}"
                for period in contracts.text_periods(text, "monthly"):
                    by_period.setdefault(period, []).append(event["event_ticker"])
            events_by_series[series] = by_period
        return events_by_series[series]

    rows = []
    for run_ in runs:
        period = contracts.period_of(run_.data_point_id)
        related = contracts.related_series(run_.data_point_id)
        if related is None:
            reason = "no Kalshi series for this statistic found in the catalog screen"
            detail = ""
        else:
            series_list, note = related
            found = []
            listed = []
            for series in series_list:
                periods = periods_for(series)
                listed.append(
                    f"{series}: "
                    + (
                        ", ".join(sorted(p for p in periods if p >= "2026-06"))
                        or "no 2026 events"
                    )
                )
                if period and period in periods:
                    found.append(f"{series} {periods[period]}")
            if found and note == "same statistic":
                raise ValueError(
                    f"{run_.data_point_id}: {found} lists the period; add a SeriesSpec"
                )
            if found:
                reason = f"Kalshi lists the period, but {note}"
            else:
                reason = "Kalshi's related series has no event for this period"
                if note != "same statistic":
                    reason += f" ({note})"
            detail = "; ".join(listed)
        rows.append(
            {
                "runId": run_.run_id,
                "dataPointId": run_.data_point_id,
                "country": run_.country,
                "recordedAt": run_.recorded_at,
                "period": period,
                "reason": reason,
                "kalshiEvidence": detail,
            }
        )
    return rows


NO_FORECAST_TEXT = "No forecast available"


def withdrawn_cells(repo, commit, all_runs, cache: FetchCache) -> list[dict]:
    published = {(r.data_point_id, r.recorded_at) for r in all_runs}
    published_slugs = {r.slug for r in all_runs}
    out = []
    for cell in thesis.catalog_cells(repo, commit):
        if not contracts.match_target(cell["dataPointId"]):
            continue
        for run_at in cell["runAts"]:
            if run_at < thesis.SCOPE_START:
                continue
            if (cell["dataPointId"], run_at) in published:
                continue
            page = cache.get(
                f"{thesis.SITE}/{cell['slug']}", accept="text/html", allow_404=True
            )
            out.append(
                {
                    "slug": cell["slug"],
                    "dataPointId": cell["dataPointId"],
                    "claimedRunAt": run_at,
                    "file": cell["file"],
                    "slugHasPublishedRun": cell["slug"] in published_slugs,
                    "livePageSaysNoForecast": (
                        None if page is None else NO_FORECAST_TEXT.encode() in page
                    ),
                }
            )
    return out
