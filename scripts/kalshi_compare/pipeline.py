"""End-to-end comparison: inventory, prices, outcomes, scores, inference."""

from __future__ import annotations

import dataclasses
import datetime as dt
import gzip
import json
import pathlib
import re
from collections import Counter
from decimal import Decimal
from typing import Any

from . import contracts, kalshi, official, scoring, thesis
from .fetch import FetchCache

HORIZONS = ("at_registration", "release_minus_7d", "release_minus_1d")
# The eight series in the plan as first committed (98940ca4).
ORIGINAL_SERIES = frozenset(
    {
        "KXCPI",
        "KXCPICORE",
        "KXU3",
        "KXPAYROLLS",
        "KXJOBLESSCLAIMS",
        "KXCONTCLAIMS",
        "KXJOLTSOPEN",
        "KXPCECORE",
    }
)
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


def partition_runs(
    in_scope: list[thesis.ThesisRun],
) -> tuple[
    list[tuple[thesis.ThesisRun, contracts.SeriesSpec, str, contracts.ThesisPattern]],
    list[thesis.ThesisRun],
]:
    """Split in-scope runs into matched (one row per matching series) and the rest.

    Every in-scope run lands in exactly one side; the assert keeps the
    inventory complete if the matching rules change.
    """
    matched = []
    unmatched_runs = []
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
    matched_ids = {r.run_id for r, *_ in matched}
    unmatched_ids = {r.run_id for r in unmatched_runs}
    if matched_ids & unmatched_ids or matched_ids | unmatched_ids != {
        r.run_id for r in in_scope
    }:
        raise ValueError("in-scope runs are not split into matched and unmatched")
    return matched, unmatched_runs


def candle_window(market: dict) -> tuple[int, int]:
    """Request candles over the market's whole life, from an hour before it opened.

    A narrower window drops a market whose book last changed before the window
    starts (the first version used 14 days and lost two strikes).
    """
    return kalshi.to_ts(market["open_time"]) - 3600, kalshi.to_ts(market["close_time"])


TICKER_YEAR = re.compile(r"-(\d{2})[A-Z]{3}")


def alternate_venue_rows(cache: FetchCache, units: dict) -> list[dict]:
    """Events other Kalshi series list for the periods matched here."""
    rows = []
    by_series: dict[str, tuple[contracts.SeriesSpec, set[str]]] = {}
    for unit in units.values():
        if unit.spec.series in contracts.ALTERNATE_VENUES:
            spec, periods = by_series.setdefault(unit.spec.series, (unit.spec, set()))
            periods.add(unit.period)
    for series, (spec, periods) in sorted(by_series.items()):
        for venue in contracts.ALTERNATE_VENUES[series]:
            listed: dict[str, list[str]] = {}
            venue_events = kalshi.series_events(cache, venue)
            for event in venue_events:
                text = f"{event.get('title', '')} {event.get('sub_title', '')}"
                for period in contracts.text_periods(text, spec.cadence):
                    listed.setdefault(period, []).append(event["event_ticker"])
            overlap = sorted(periods & set(listed))
            readable = sum(len(v) for v in listed.values())
            ticker_years = [
                2000 + int(found.group(1))
                for event in venue_events
                if (found := TICKER_YEAR.search(event["event_ticker"]))
            ]
            period_years = [int(p[:4]) for p in listed]
            latest_year = max(ticker_years + period_years, default=None)
            unreadable = len(venue_events) - readable
            if unreadable and (
                latest_year is None or latest_year >= min(int(p[:4]) for p in periods)
            ):
                raise ValueError(
                    f"{venue}: {unreadable} event titles name no readable period "
                    "and the events may cover a matched period"
                )
            rows.append(
                {
                    "series": series,
                    "venue": venue,
                    "events": len(venue_events),
                    "eventsWithReadablePeriod": readable,
                    "latestYear": latest_year,
                    "matchedPeriodsListed": overlap,
                    "matchedPeriodEvents": [t for p in overlap for t in listed[p]],
                }
            )
    return rows


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

    matched, unmatched_runs = partition_runs(in_scope)

    cdfs, distribution_meta = thesis.load_distributions(
        cache, {run_.run_id for run_, *_ in matched}
    )
    for run_, *_ in matched:
        run_.cdf = cdfs.get(run_.run_id)
        run_.cdf_check = thesis.rebuild_check(run_)

    catalog_url = kalshi.build_url(kalshi.API, "/series")
    catalog = cache.get_json(catalog_url)["series"]
    unmatched = unmatched_rows(cache, unmatched_runs)
    screen = catalog_screen(cache, catalog, unmatched_runs)

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
            start, end = candle_window(market)
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
        "catalogScreen": screen,
        "withdrawn": withdrawn_cells(repo, commit, all_runs, cache),
        "alternateVenues": alternate_venue_rows(cache, units),
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
                "kalshiFloored",
                "thesisFloored",
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
                summary["originalSeries"] = summarize_rows(
                    [r for r in rows if r["series"] in ORIGINAL_SERIES]
                )["pooled"]
                # Descriptive only: which events hit the floor depends on the
                # outcome, so this is not a test.
                summary["excludingKalshiFloorHits"] = summarize_rows(
                    [r for r in rows if not r.get("kalshiFloored")]
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
    reason says what Kalshi lists rather than asserting it. Every run names
    the catalog screen group whose search backs its reason.
    """
    events_by_series: dict[tuple[str, str], tuple[dict, list]] = {}
    unit = {"monthly": "month", "quarterly": "quarter", "annual": "year"}

    def periods_for(series: str, cadence: str) -> tuple[dict, list]:
        """Event tickers by the period each names, and the events naming none.

        Periods are read with spans, so a range ("August 2026 through July
        2027"), "any 2026 quarter" or a day date counts for every period it
        covers. Events still naming no period are returned with the years
        their text names, so absence is never claimed for them.
        """
        if (series, cadence) not in events_by_series:
            by_period: dict[str, list[str]] = {}
            unread = []
            for event in kalshi.series_events(cache, series):
                text = f"{event.get('title', '')} {event.get('sub_title', '')}"
                periods = contracts.text_periods(text, cadence, spans=True)
                for found in periods:
                    by_period.setdefault(found, []).append(event["event_ticker"])
                if not periods:
                    unread.append((event["event_ticker"], " ".join(text.split())))
            events_by_series[(series, cadence)] = (by_period, unread)
        return events_by_series[(series, cadence)]

    rows = []
    for run_ in runs:
        period = contracts.period_of(run_.data_point_id)
        group = contracts.screen_group(run_.data_point_id)
        related = contracts.related_series(run_.data_point_id)
        if related is None:
            reason = "no Kalshi series for this statistic found in the catalog screen"
            detail = ""
        else:
            found_notes, other_notes, listed, open_series = [], [], [], []
            cadence = contracts.period_cadence(period) if period else "monthly"
            run_year = int(period[:4]) if period else None
            for series, note in related:
                periods, unread = periods_for(series, cadence)
                shown = sorted(p for p in periods if p[:4] >= "2026")
                text = f"{series}: " + (
                    ", ".join(shown) or f"no event names a 2026 {unit[cadence]}"
                )
                # Unread events that could cover the run's period: those
                # naming no year, the run's year, or a span reaching it
                # ("before 2029", "through 2027").
                could_cover = [
                    u for u in unread if contracts.could_cover_year(u[1], run_year)
                ]
                if unread:
                    text += (
                        f"; {len(unread)} event{'s' if len(unread) > 1 else ''} name"
                        f"{'' if len(unread) > 1 else 's'} no {unit[cadence]} ("
                        + "; ".join(f"{t}: {title}" for t, title in unread[:2])
                        + ("; …" if len(unread) > 2 else "")
                        + ")"
                    )
                listed.append(text)
                if period and period in periods:
                    if note == contracts.SAME:
                        raise ValueError(
                            f"{run_.data_point_id}: {series} {periods[period]} lists"
                            " the period; add a SeriesSpec"
                        )
                    found_notes.append(note)
                    continue
                if could_cover:
                    if note == contracts.SAME:
                        raise ValueError(
                            f"{run_.data_point_id}: {series} has events whose period"
                            f" cannot be read ({[u[0] for u in could_cover]}); read"
                            " them before calling the period absent"
                        )
                    open_series.append(series)
                if note != contracts.SAME:
                    other_notes.append(note)
            # Series that share a note (an older ticker) are named once.
            found_notes = list(dict.fromkeys(found_notes))
            other_notes = list(dict.fromkeys(other_notes))
            if found_notes:
                reason = "Kalshi lists the period, but " + "; ".join(found_notes)
            else:
                reason = (
                    "no related Kalshi event names this period"
                    if open_series
                    else "Kalshi's related series has no event for this period"
                )
                if other_notes:
                    reason += f" ({'; '.join(other_notes)})"
                if open_series:
                    names = (
                        ", ".join(open_series[:-1]) + " and " + open_series[-1]
                        if len(open_series) > 1
                        else open_series[0]
                    )
                    verb = "list" if len(open_series) > 1 else "lists"
                    reason += (
                        f"; {names} also {verb} events that span several periods"
                        " or name none, shown in the evidence"
                    )
            detail = "; ".join(listed)
        rows.append(
            {
                "runId": run_.run_id,
                "dataPointId": run_.data_point_id,
                "country": run_.country,
                "recordedAt": run_.recorded_at,
                "period": period,
                "catalogScreen": group.label if group else "",
                "reason": reason,
                "kalshiEvidence": detail,
            }
        )
    return rows


def screen_events(cache: FetchCache, catalog: list[dict]) -> dict[str, list[dict]]:
    """Every event of every series in the event-screened categories.

    A series such as KXUE ("Monthly Unemployment") names its countries only in
    its event titles, so its events are screened as well as its title.
    """
    return {
        item["ticker"]: kalshi.series_events(cache, item["ticker"])
        for item in catalog
        if item.get("category") in contracts.EVENT_SCREEN_CATEGORIES
    }


def screen_verdict(
    series: str, event_ticker: str | None, group_ids: list[str]
) -> tuple[str, str] | None:
    """How a catalog screen hit is accounted for, or None if it is not.

    ``group_ids`` are the data point ids of the screen group's unmatched runs:
    a related series counts as checked only if one of those runs checks it.
    """
    spec = {s.series: s for s in contracts.SPECS}.get(series)
    if event_ticker is not None:
        if spec and spec.event_prefix:
            # Multi-country series: each country's events need their own verdict.
            if event_ticker.startswith(spec.event_prefix):
                return "matched", f"scored as {spec.series} ({spec.statistic})"
            reason = contracts.screen_verdict_reason(event_ticker, event=True)
            return ("different statistic", reason) if reason else None
        reason = contracts.screen_verdict_reason(event_ticker, event=True)
        if reason:
            return "different statistic", reason
    if spec:
        return "matched", f"scored as {spec.series} ({spec.statistic})"
    for matched, venues in contracts.ALTERNATE_VENUES.items():
        if series in venues:
            return "alternate venue", (
                f"older ticker or second venue for {matched}; its events are listed"
                " for every matched period"
            )
    checked, elsewhere = [], []
    for regex, pairs in contracts.RELATED:
        for related, note in pairs:
            if related != series:
                continue
            text = "same statistic" if note == contracts.SAME else note
            if any(regex.match(data_point) for data_point in group_ids):
                checked.append(text)
            else:
                elsewhere.append(f"{text} (checked for `{regex.pattern}` runs)")
    if checked:
        return "related", "; ".join(dict.fromkeys(checked)) + (
            "; its events are checked for each run's period"
        )
    if elsewhere:
        return "related to another family", "; ".join(dict.fromkeys(elsewhere))
    reason = contracts.screen_verdict_reason(series)
    return ("different statistic", reason) if reason else None


def catalog_screen(
    cache: FetchCache, catalog: list[dict], runs: list[thesis.ThesisRun]
) -> dict:
    """Search the whole Kalshi catalog for every statistic left unmatched.

    Every unmatched run must belong to a screen group, and every hit must be
    accounted for (matched, alternate venue, related, or a reviewed different
    statistic); either gap stops the run, so the "no Kalshi series" reasons
    rest on a recorded search rather than an assertion. Hits are recorded one
    row per group, series and verdict, with the number of events that hit.
    """
    uncovered = sorted(
        {
            r.data_point_id
            for r in runs
            if contracts.screen_group(r.data_point_id) is None
        }
    )
    if uncovered:
        raise ValueError(f"unmatched runs outside the catalog screen: {uncovered}")
    ids_by_group: dict[str, list[str]] = {}
    countries_by_group: dict[str, set[str]] = {}
    for run_ in runs:
        label = contracts.screen_group(run_.data_point_id).label
        ids_by_group.setdefault(label, []).append(run_.data_point_id)
        countries_by_group.setdefault(label, set()).add(run_.country)
    events = screen_events(cache, catalog)
    texts = []
    for item in catalog:
        title = item.get("title") or ""
        texts.append(
            (item, None, title, contracts.normalize_text(f"{item['ticker']} {title}"))
        )
        for event in events.get(item["ticker"], []):
            event_title = f"{event.get('title', '')} / {event.get('sub_title', '')}"
            texts.append(
                (
                    item,
                    event["event_ticker"],
                    event_title,
                    contracts.normalize_text(
                        f"{event['event_ticker']} {event.get('title', '')}"
                        f" {event.get('sub_title', '')}"
                    ),
                )
            )
    hits: dict[tuple, dict] = {}
    groups, unaccounted = [], []
    for group in contracts.CATALOG_SCREEN:
        group_ids = ids_by_group.get(group.label, [])
        for item, event_ticker, title, text in texts:
            if not group.keywords.search(text):
                continue
            verdict = screen_verdict(item["ticker"], event_ticker, group_ids)
            if verdict is None:
                unaccounted.append(f"{group.label}: {event_ticker or item['ticker']}")
                continue
            key = (group.label, item["ticker"], verdict[0])
            row = hits.setdefault(
                key,
                {
                    "screen": group.label,
                    "series": item["ticker"],
                    "category": item.get("category"),
                    "seriesTitle": item.get("title") or "",
                    "seriesTitleHit": False,
                    "eventsHit": 0,
                    "exampleEvents": [],
                    "verdict": verdict[0],
                    "reason": [],
                },
            )
            if verdict[1] not in row["reason"]:
                row["reason"].append(verdict[1])
            if event_ticker is None:
                row["seriesTitleHit"] = True
            else:
                row["eventsHit"] += 1
                if len(row["exampleEvents"]) < 3:
                    row["exampleEvents"].append(f"{event_ticker}: {title}")
        rows = [r for k, r in hits.items() if k[0] == group.label]
        counts = Counter(r["verdict"] for r in rows)
        groups.append(
            {
                "screen": group.label,
                "thesisFamilies": group.families.pattern,
                "keywords": group.keywords.pattern,
                "thesisRuns": len(group_ids),
                "thesisCountries": sorted(countries_by_group.get(group.label, ())),
                "seriesHit": len({r["series"] for r in rows}),
                "eventsHit": sum(r["eventsHit"] for r in rows),
                "verdicts": dict(sorted(counts.items())),
            }
        )
    if unaccounted:
        raise ValueError(
            "catalog screen hits with no verdict (add a SeriesSpec, RELATED,"
            f" ALTERNATE_VENUES or SCREEN_VERDICTS entry): {unaccounted}"
        )
    for row in hits.values():
        row["exampleEvents"] = "; ".join(row["exampleEvents"])
        row["reason"] = " | ".join(row["reason"])
    return {
        "seriesSearched": len(catalog),
        "eventScreenCategories": list(contracts.EVENT_SCREEN_CATEGORIES),
        "eventSeriesSearched": len(events),
        "eventsSearched": sum(len(e) for e in events.values()),
        "groups": groups,
        "hits": list(hits.values()),
    }


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
