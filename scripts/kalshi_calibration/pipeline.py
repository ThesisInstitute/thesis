"""End-to-end study: events, prices at each horizon, calibration and scores."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import datetime as dt
from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any

from kalshi_compare import contracts, kalshi, official, scoring
from kalshi_compare import pipeline as compare_pipeline
from kalshi_compare.fetch import FetchCache

from . import calibration, history

DAY = 86_400
HORIZONS: tuple[tuple[str, str, float], ...] = (
    ("anchor_30d", "fixed", 30 * DAY),
    ("anchor_7d", "fixed", 7 * DAY),
    ("anchor_1d", "fixed", 1 * DAY),
    ("life_25", "life", 0.25),
    ("life_50", "life", 0.50),
    ("life_75", "life", 0.75),
)
HORIZON_NAMES = tuple(h[0] for h in HORIZONS)
FIXED_DAYS = {"anchor_30d": 30, "anchor_7d": 7, "anchor_1d": 1}
FLOOR = 0.001
LIQUID_SPREAD = 0.20
PAPER_VOLUME = 20_000.0
LEGACY_CUTOFF = "2025-01-01"
WORKERS = 4  # the shared host's cap on local parallelism
INTERIOR = (0.05, 0.95)


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def et_date(ts: int) -> str:
    return (
        dt.datetime.fromtimestamp(ts, dt.timezone.utc)
        .astimezone(official.ET)
        .date()
        .isoformat()
    )


@dataclasses.dataclass
class Scored:
    """A settled event with a readable period and its market candles."""

    event: history.Event
    candles: dict[str, list[kalshi.Candle]]
    tiers: dict[str, str]
    has_official: bool
    anchor: int
    release_ts: int  # when the outcome became public (release, or settlement)
    cluster: str  # release date, ET
    kalshi_realized_ok: bool

    @property
    def key(self) -> str:
        return self.event.ticker


def settlement_ts(event: history.Event) -> int:
    stamps = [m.get("settlement_ts") for m in event.markets if m.get("settlement_ts")]
    return (
        max(kalshi.to_ts(s[:19] + "Z") for s in stamps) if stamps else event.last_close
    )


# Loading -------------------------------------------------------------------


def load(
    cache: FetchCache, as_of: str, series_list: tuple[str, ...] = history.SERIES
) -> tuple[list[history.Event], list[dict]]:
    """Every in-scope event of the twelve series, built and (if settled) resolved."""
    events: list[history.Event] = []
    outside_rows: list[dict] = []
    for series in series_list:
        inside, outside = history.scoped_events(cache, series)
        for raw in outside:
            outside_rows.append(
                {
                    "series": series,
                    "eventTicker": raw["event_ticker"],
                    "title": raw.get("title"),
                    "reason": "outside scope (KXUE events for other countries)",
                }
            )
        for raw in inside:
            event = history.build_event(cache, series, raw)
            if event.settled and event.period is not None:
                history.locate_print(cache, event)
                if event.official is not None and event.official.release_at > as_of:
                    raise ValueError(f"{event.ticker}: release after the data cutoff")
            events.append(event)
    return events, outside_rows


def attach_candles(cache: FetchCache, events: list[history.Event]) -> list[Scored]:
    scored = []
    for event in events:
        if not event.settled or event.period is None:
            continue
        candles, tiers = {}, {}
        for market in event.markets:
            start, end = compare_pipeline.candle_window(market)
            candles[market["ticker"]], tiers[market["ticker"]] = kalshi.market_candles(
                cache, event.series, market, start, end
            )
        has_official = event.official is not None
        anchor = event.anchor if has_official else event.last_close
        release_ts = (
            kalshi.to_ts(event.official.release_at)
            if has_official
            else settlement_ts(event)
        )
        cluster = (
            et_date(kalshi.to_ts(event.official.release_at))
            if has_official
            else et_date(anchor)
        )
        scored.append(
            Scored(
                event,
                candles,
                tiers,
                has_official,
                anchor,
                release_ts,
                cluster,
                kalshi_realized_ok=kalshi_results_monotone(event),
            )
        )
    return scored


def kalshi_results_monotone(event: history.Event) -> bool:
    """Kalshi's yes results fall with the strike (needed for its realized bracket)."""
    ordered = sorted(event.markets, key=lambda m: event.strikes[m["ticker"]].value)
    results = [m["result"] == "yes" for m in ordered]
    return all(a or not b for a, b in zip(results, results[1:]))


# Prices at an instant -----------------------------------------------------------


@dataclasses.dataclass
class Quote:
    ticker: str
    strike: Decimal
    state: kalshi.MarketState
    market: dict


def quotes_at(item: Scored, at: int) -> tuple[list[Quote], list[str]]:
    """Markets open and quoted at ``at``, by strike; and those open but unquoted."""
    quotes, unquoted = [], []
    for market in item.event.markets:
        if kalshi.to_ts(market["open_time"]) > at:
            continue
        state = kalshi.state_at(item.candles[market["ticker"]], at)
        if state.candle_end is None:
            unquoted.append(market["ticker"])
            continue
        if state.candle_end > at:
            raise AssertionError(f"{market['ticker']}: candle after the horizon")
        quotes.append(
            Quote(
                market["ticker"],
                item.event.strikes[market["ticker"]].value,
                state,
                market,
            )
        )
    quotes.sort(key=lambda q: q.strike)
    if len({q.strike for q in quotes}) != len(quotes):
        raise ValueError(f"{item.key}: duplicate strikes")
    return quotes, unquoted


def event_instant(item: Scored, horizon: str) -> int:
    kind, value = next((k, v) for name, k, v in HORIZONS if name == horizon)
    if kind == "fixed":
        return int(item.anchor - value)
    return int(item.event.first_open + value * (item.anchor - item.event.first_open))


def market_end(item: "Scored", market: dict) -> int:
    """A market's close, or the release if the market closed after it.

    A market still trading after the release would price a known outcome;
    ``late_closes`` lists any such market.
    """
    return min(kalshi.to_ts(market["close_time"]), item.release_ts)


def market_instant(item: "Scored", market: dict, fraction: float) -> int:
    start = kalshi.to_ts(market["open_time"])
    return int(start + fraction * (market_end(item, market) - start))


def late_closes(scored: list["Scored"]) -> list[dict]:
    return [
        {
            "eventTicker": item.key,
            "ticker": m["ticker"],
            "closeTime": m["close_time"],
            "releaseAt": item.event.official.release_at,
        }
        for item in scored
        if item.has_official
        for m in item.event.markets
        if kalshi.to_ts(m["close_time"]) > item.release_ts
    ]


def first_trade_start(candles: list[kalshi.Candle]) -> int | None:
    """Start of the first hourly candle with a trade (Themis starts at the first)."""
    for candle in candles:
        if candle.trade_close is not None:
            return candle.end - 3600
    return None


# Rows ----------------------------------------------------------------------


def outcome(item: Scored, market: dict) -> dict:
    strike = item.event.strikes[market["ticker"]]
    official_yes = None
    if item.has_official:
        official_yes = contracts.market_yes(
            "ladder", strike.strike_type, strike.value, item.event.official.value
        )
    return {
        "yOfficial": None if official_yes is None else int(official_yes),
        "yKalshi": int(market["result"] == "yes"),
    }


def base_row(item: Scored) -> dict:
    event = item.event
    return {
        "series": event.series,
        "family": event.family,
        "generation": event.generation,
        "eventTicker": event.ticker,
        "period": event.period,
        "cluster": item.cluster,
        "releaseTs": item.release_ts,
        "hasOfficial": item.has_official,
        "era": "before 2025" if item.cluster < LEGACY_CUTOFF else "2025 on",
    }


def build_rows(scored: list[Scored]) -> dict[str, list[dict]]:
    """Binary rows (primary, raw, liquid, paper-matched), event rows, exclusions."""
    binary: list[dict] = []
    liquid: list[dict] = []
    paper: list[dict] = []
    events: list[dict] = []
    liquid_events: list[dict] = []
    exclusions: list[dict] = []
    for item in scored:
        base = base_row(item)
        strike_type = item.event.strike_type
        if strike_type is None:
            exclusions.append({**base, "reason": "markets disagree on direction"})
            continue
        for horizon, kind, value in HORIZONS:
            at = event_instant(item, horizon)
            quotes, unquoted = quotes_at(item, at)
            for ticker in unquoted:
                exclusions.append(
                    {
                        **base,
                        "horizon": horizon,
                        "ticker": ticker,
                        "reason": "market open but no candle by then",
                    }
                )
            if not quotes:
                exclusions.append(
                    {**base, "horizon": horizon, "reason": "no market quoted by then"}
                )
            else:
                row = event_row(item, base, horizon, at, quotes, strike_type)
                events.append(row)
                liquid_quotes = liquid_only(quotes)
                if liquid_quotes:
                    liquid_events.append(
                        event_row(item, base, horizon, at, liquid_quotes, strike_type)
                    )
                if kind == "fixed":
                    for quote, p in zip(quotes, row["repaired"]):
                        binary.append(binary_row(item, base, horizon, at, quote, p))
                    for quote, p in zip(liquid_quotes, repair(liquid_quotes)):
                        liquid.append(binary_row(item, base, horizon, at, quote, p))
            if kind == "life":
                # Each market at its own life fraction, priced within the
                # event's ladder at that instant.
                for market in item.event.markets:
                    t = market_instant(item, market, value)
                    market_quotes, _ = quotes_at(item, t)
                    tickers = [q.ticker for q in market_quotes]
                    if market["ticker"] not in tickers:
                        exclusions.append(
                            {
                                **base,
                                "horizon": horizon,
                                "ticker": market["ticker"],
                                "reason": "market not quoted at its life fraction",
                            }
                        )
                        continue
                    index = tickers.index(market["ticker"])
                    binary.append(
                        binary_row(
                            item,
                            base,
                            horizon,
                            t,
                            market_quotes[index],
                            repair(market_quotes)[index],
                        )
                    )
                    liquid_quotes = liquid_only(market_quotes)
                    liquid_tickers = [q.ticker for q in liquid_quotes]
                    if market["ticker"] in liquid_tickers:
                        index = liquid_tickers.index(market["ticker"])
                        liquid.append(
                            binary_row(
                                item,
                                base,
                                horizon,
                                t,
                                liquid_quotes[index],
                                repair(liquid_quotes)[index],
                            )
                        )
            paper.extend(paper_rows(item, base, horizon, kind, value, at, exclusions))
    return {
        "binary": binary,
        "liquid": liquid,
        "paper": paper,
        "events": events,
        "liquidEvents": liquid_events,
        "exclusions": exclusions,
    }


def repair(quotes: list[Quote]) -> list[float]:
    return scoring.isotonic_nonincreasing([q.state.mid for q in quotes])


def liquid_only(quotes: list[Quote]) -> list[Quote]:
    return [
        q
        for q in quotes
        if q.state.spread is not None and q.state.spread <= LIQUID_SPREAD + 1e-9
    ]


def binary_row(
    item: Scored, base: dict, horizon: str, at: int, quote: Quote, p: float
) -> dict:
    market = quote.market
    return {
        **base,
        **outcome(item, market),
        "horizon": horizon,
        "at": at,
        "ticker": quote.ticker,
        "strike": str(quote.strike),
        "p": p,
        "raw": quote.state.mid,
        "spread": quote.state.spread,
        "candleEnd": quote.state.candle_end,
        "candleAgeHours": (at - quote.state.candle_end) / 3600,
        "lifetimeVolume": kalshi.market_volume(market) or 0.0,
    }


def paper_rows(item, base, horizon, kind, value, at, exclusions) -> list[dict]:
    """Last traded price, no repair; life from the first trade to close."""
    out = []
    for market in item.event.markets:
        candles = item.candles[market["ticker"]]
        start = first_trade_start(candles)
        if start is None:
            # Never traded: excluded from this variant, as in the paper.
            exclusions.append(
                {
                    **base,
                    "horizon": horizon,
                    "ticker": market["ticker"],
                    "variant": "paper",
                    "reason": "never traded",
                }
            )
            continue
        if kind == "fixed":
            t = at
            if kalshi.to_ts(market["open_time"]) > t:
                continue
        else:
            close = market_end(item, market)
            if close <= start:
                continue
            t = int(start + value * (close - start))
        state = kalshi.state_at(candles, t)
        if state.candle_end is not None and state.candle_end > t:
            raise AssertionError(f"{market['ticker']}: candle after the horizon")
        if state.last is None:
            exclusions.append(
                {
                    **base,
                    "horizon": horizon,
                    "ticker": market["ticker"],
                    "variant": "paper",
                    "reason": "no trade by then",
                }
            )
            continue
        out.append(
            {
                **base,
                **outcome(item, market),
                "horizon": horizon,
                "at": t,
                "ticker": market["ticker"],
                "strike": str(item.event.strikes[market["ticker"]].value),
                "p": state.last,
                "lifetimeVolume": kalshi.market_volume(market) or 0.0,
            }
        )
    return out


def event_row(
    item: Scored,
    base: dict,
    horizon: str,
    at: int,
    quotes: list[Quote],
    strike_type: str,
) -> dict:
    strikes = [q.strike for q in quotes]
    raw = [q.state.mid for q in quotes]
    repaired = scoring.isotonic_nonincreasing(raw)
    brackets = scoring.ladder_to_brackets(repaired)
    row = {
        **base,
        "horizon": horizon,
        "at": at,
        "nMarkets": len(quotes),
        "strikes": [str(s) for s in strikes],
        "strikeType": strike_type,
        "raw": raw,
        "repaired": repaired,
        "brackets": brackets,
        "violations": scoring.ladder_violations(raw),
        "officialValue": (
            None if not item.has_official else str(item.event.official.value)
        ),
    }
    for source in ("official", "kalshi"):
        if source == "official":
            if not item.has_official:
                continue
            value = item.event.official.value
            realized = scoring.realized_ladder_bracket(value, strikes, strike_type)
            outcomes = [
                contracts.market_yes("ladder", strike_type, s, value) for s in strikes
            ]
        else:
            if not item.kalshi_realized_ok:
                continue
            outcomes = [q.market["result"] == "yes" for q in quotes]
            realized = sum(outcomes)
        row.update(
            score_brackets(brackets, repaired, realized, outcomes, suffix=source)
        )
    return row


def score_brackets(brackets, ladder, realized, outcomes, suffix: str) -> dict:
    floored = scoring.floor_renormalize(brackets, FLOOR)
    return {
        f"realized_{suffix}": realized,
        f"realizedProb_{suffix}": brackets[realized],
        f"floorHit_{suffix}": brackets[realized] < FLOOR,
        f"log_{suffix}": scoring.log_score(floored, realized),
        f"brier_{suffix}": scoring.brier_score(brackets, realized),
        f"ladderBrier_{suffix}": scoring.ladder_brier(ladder, outcomes),
    }


# Analyses -------------------------------------------------------------------

GROUPS = ("all",) + history.FAMILY_ORDER


def in_group(row: dict, group: str) -> bool:
    return group == "all" or row["family"] == group


def outcome_key(source: str) -> str:
    return "yOfficial" if source == "official" else "yKalshi"


def usable(row: dict, source: str) -> bool:
    return row[outcome_key(source)] is not None


def reliability_tables(
    rows, source="official", draws=calibration.MEAN_DRAWS, split=None
):
    out: dict[str, Any] = {}
    y = outcome_key(source)
    groups = GROUPS if split is None else sorted({r[split] for r in rows})
    for horizon in HORIZON_NAMES:
        out[horizon] = {}
        for group in groups:
            chosen = [
                r
                for r in rows
                if r["horizon"] == horizon
                and usable(r, source)
                and (in_group(r, group) if split is None else r[split] == group)
            ]
            clusters: dict[str, list] = defaultdict(list)
            events = set()
            for r in chosen:
                clusters[r["cluster"]].append((r["p"], r[y]))
                events.add(r["eventTicker"])
            stats = {k: calibration.cluster_stats(v) for k, v in clusters.items()}
            summary = calibration.bootstrap_reliability(stats, draws=draws)
            summary["events"] = len(events)
            out[horizon][group] = summary
    return out


def compression(rows, source="official", draws=calibration.REFIT_DRAWS):
    out: dict[str, Any] = {}
    y = outcome_key(source)
    for horizon in HORIZON_NAMES:
        out[horizon] = {}
        for group in GROUPS:
            tables: dict[str, list] = defaultdict(list)
            for r in rows:
                if r["horizon"] == horizon and usable(r, source) and in_group(r, group):
                    tables[r["cluster"]].append((r["p"], r[y]))
            if len(tables) < 2:
                out[horizon][group] = {"clusters": len(tables)}
                continue
            aggregated = {k: calibration.aggregate(v) for k, v in tables.items()}
            fit = calibration.bootstrap_logistic(aggregated, draws=draws)
            fit["verdict"] = calibration.verdict(fit["betaCi95"])
            fit["n"] = sum(len(v) for v in tables.values())
            out[horizon][group] = fit
    return out


def event_scores(event_rows, source="official", cluster_key="cluster"):
    out: dict[str, Any] = {}
    for horizon in HORIZON_NAMES:
        out[horizon] = {}
        groups = list(GROUPS) + list(history.SERIES)
        for group in groups:
            chosen = [
                r
                for r in event_rows
                if r["horizon"] == horizon
                and f"log_{source}" in r
                and (in_group(r, group) if group in GROUPS else r["series"] == group)
            ]
            entry = {"events": len(chosen)}
            for metric in ("log", "brier", "ladderBrier"):
                by: dict[str, list[float]] = defaultdict(list)
                for r in chosen:
                    by[r[cluster_key]].append(r[f"{metric}_{source}"])
                entry[metric] = calibration.bootstrap_mean(by)
            entry["floorHits"] = sum(1 for r in chosen if r[f"floorHit_{source}"])
            out[horizon][group] = entry
    return out


def out_of_sample(binary_rows, event_rows, source="official", pooled=True):
    """Forward-chained logistic and beta recalibration against identity."""
    y = outcome_key(source)
    out: dict[str, Any] = {}
    for horizon in HORIZON_NAMES:
        out[horizon] = {}
        for group in (GROUPS if pooled else ("all",)):
            rows = [
                r
                for r in binary_rows
                if r["horizon"] == horizon and usable(r, source) and in_group(r, group)
            ]
            if not rows:
                out[horizon][group] = {"folds": 0}
                continue
            folds, skipped = calibration.forward_folds(
                [r["cluster"] for r in rows],
                [r["at"] for r in rows],
                [r["releaseTs"] for r in rows],
            )
            evs = defaultdict(list)
            for r in event_rows:
                if (
                    r["horizon"] == horizon
                    and f"log_{source}" in r
                    and in_group(r, group)
                ):
                    evs[r["cluster"]].append(r)
            per_model: dict[str, dict[str, dict[str, float]]] = {
                m: defaultdict(dict) for m in calibration.FITTERS
            }
            maps_out = []
            for fold in folds:
                table = calibration.aggregate(
                    (rows[i]["p"], rows[i][y]) for i in fold.train
                )
                test = [rows[i] for i in fold.test]
                base_log = sum(
                    calibration.binary_log_loss(r["p"], r[y]) for r in test
                ) / len(test)
                base_brier = sum(
                    calibration.binary_brier(r["p"], r[y]) for r in test
                ) / len(test)
                fold_events = evs.get(fold.cluster, [])
                for name, fitter in calibration.FITTERS.items():
                    mapping = fitter(table)
                    maps_out.append(
                        {
                            "cluster": fold.cluster,
                            "model": name,
                            "params": mapping.params,
                            "converged": mapping.converged,
                        }
                    )
                    log = sum(
                        calibration.binary_log_loss(mapping(r["p"]), r[y]) for r in test
                    ) / len(test)
                    brier = sum(
                        calibration.binary_brier(mapping(r["p"]), r[y]) for r in test
                    ) / len(test)
                    per_model[name]["binaryLog"][fold.cluster] = base_log - log
                    per_model[name]["binaryBrier"][fold.cluster] = base_brier - brier
                    if fold_events:
                        d_log, d_brier = [], []
                        for e in fold_events:
                            ladder = calibration.recalibrated_ladder(
                                e["repaired"], mapping
                            )
                            brackets = scoring.ladder_to_brackets(ladder)
                            realized = e[f"realized_{source}"]
                            floored = scoring.floor_renormalize(brackets, FLOOR)
                            d_log.append(
                                scoring.log_score(floored, realized)
                                - e[f"log_{source}"]
                            )
                            d_brier.append(
                                e[f"brier_{source}"]
                                - scoring.brier_score(brackets, realized)
                            )
                        per_model[name]["bracketLog"][fold.cluster] = sum(d_log) / len(
                            d_log
                        )
                        per_model[name]["bracketBrier"][fold.cluster] = sum(
                            d_brier
                        ) / len(d_brier)
            out[horizon][group] = {
                "folds": len(folds),
                "skippedFolds": len(skipped),
                "testMarkets": sum(len(f.test) for f in folds),
                "models": {
                    name: {
                        metric: calibration.bootstrap_fold_means(values)
                        for metric, values in metrics.items()
                    }
                    for name, metrics in per_model.items()
                },
                "lastMaps": maps_out[-2:],
            }
    return out


def settlement_rows(events: list[history.Event]) -> list[dict]:
    rows = []
    for event in events:
        if not event.settled or event.period is None:
            continue
        for row in history.settlement_agreement(event):
            row["series"] = event.series
            row["period"] = event.period
            rows.append(row)
    return rows


def inventory(events: list[history.Event]) -> list[dict]:
    rows = []
    for event in events:
        rows.append(
            {
                "series": event.series,
                "family": event.family,
                "eventTicker": event.ticker,
                "generation": event.generation,
                "title": event.event.get("title"),
                "settled": event.settled,
                "period": event.period,
                "periodCheck": event.period_check,
                "periodRelaxed": event.period_relaxed,
                "markets": len(event.markets),
                "droppedMarkets": event.dropped,
                "officialValue": (
                    None if event.official is None else str(event.official.value)
                ),
                "officialSecondReading": (
                    None if event.official is None else event.official.second_reading
                ),
                "releaseAt": (
                    None if event.official is None else event.official.release_at
                ),
                "sourceUrl": (
                    None if event.official is None else event.official.source_url
                ),
                "sourceSha256": (
                    None if event.official is None else event.official.source_sha256
                ),
                "officialNote": event.official_note,
                "officialDelayed": event.official_delayed,
                "kalshiExpirationValue": (
                    None
                    if history.expiration_value(event) is None
                    else str(history.expiration_value(event))
                ),
                "expirationAgrees": history.expiration_agrees(event),
                "candidatesTried": event.candidates_tried,
            }
        )
    return rows


def run(
    *, cache: FetchCache, as_of: str, series_list: tuple[str, ...] = history.SERIES
) -> dict[str, Any]:
    events, outside = load(cache, as_of, series_list)
    scored = attach_candles(cache, events)
    rows = build_rows(scored)
    binary, events_rows = rows["binary"], rows["events"]
    duplicates = Counter((s.event.series, s.event.period) for s in scored)
    results: dict[str, Any] = {
        "meta": {
            "asOf": as_of,
            "generatedAt": utc_now(),
            "horizons": HORIZONS,
            "floor": FLOOR,
            "liquidSpread": LIQUID_SPREAD,
            "paperVolume": PAPER_VOLUME,
            "seed": calibration.SEED,
            "meanDraws": calibration.MEAN_DRAWS,
            "refitDraws": calibration.REFIT_DRAWS,
            "minTrainClusters": calibration.MIN_TRAIN_CLUSTERS,
        },
        "inventory": inventory(events),
        "outsideScope": outside,
        "settlement": settlement_rows(events),
        "duplicatePeriods": [
            {
                "series": k[0],
                "period": k[1],
                "events": [
                    s.key for s in scored if (s.event.series, s.event.period) == k
                ],
            }
            for k, n in duplicates.items()
            if n > 1
        ],
        "exclusions": rows["exclusions"],
        "lateCloses": late_closes(scored),
        "eventRows": events_rows,
        "binaryRows": binary,
        "paperRows": rows["paper"],
        "liquidRows": rows["liquid"],
        "liquidEventRows": rows["liquidEvents"],
    }
    official_binary = [r for r in binary if r["hasOfficial"]]
    raw_rows = [dict(r, p=r["raw"]) for r in official_binary]
    liquid_official = [r for r in rows["liquid"] if r["hasOfficial"]]
    paper_official = [r for r in rows["paper"] if r["hasOfficial"]]
    paper_volume = [r for r in paper_official if r["lifetimeVolume"] > PAPER_VOLUME]
    volume_rows = [
        dict(
            r,
            volumeClass=(
                "above 20,000"
                if r["lifetimeVolume"] > PAPER_VOLUME
                else "at most 20,000"
            ),
        )
        for r in official_binary
    ]
    interior = [r for r in official_binary if INTERIOR[0] <= r["p"] <= INTERIOR[1]]
    jobs = {
        "reliability": (reliability_tables, (official_binary,), {}),
        "compression": (compression, (official_binary,), {}),
        # Secondary: clusters are events rather than release dates.
        "compressionByEvent": (
            compression,
            ([dict(r, cluster=r["eventTicker"]) for r in official_binary],),
            {},
        ),
        "eventScores": (event_scores, (events_rows,), {}),
        "eventScoresByEvent": (
            event_scores,
            (events_rows,),
            {"cluster_key": "eventTicker"},
        ),
        "outOfSample": (out_of_sample, (official_binary, events_rows), {}),
        # Sensitivities and secondary splits.
        "reliabilityRaw": (reliability_tables, (raw_rows,), {}),
        "compressionRaw": (compression, (raw_rows,), {}),
        "reliabilityLiquid": (reliability_tables, (liquid_official,), {}),
        "compressionLiquid": (compression, (liquid_official,), {}),
        "eventScoresLiquid": (event_scores, (rows["liquidEvents"],), {}),
        "reliabilityPaper": (reliability_tables, (paper_official,), {}),
        "compressionPaper": (compression, (paper_official,), {}),
        "reliabilityPaperVolume": (reliability_tables, (paper_volume,), {}),
        "compressionPaperVolume": (compression, (paper_volume,), {}),
        "reliabilityKalshiResults": (
            reliability_tables,
            (binary,),
            {"source": "kalshi"},
        ),
        "compressionKalshiResults": (compression, (binary,), {"source": "kalshi"}),
        "eventScoresKalshiResults": (
            event_scores,
            (events_rows,),
            {"source": "kalshi"},
        ),
        # Added after the CPI test run (deviation 6): prices away from the
        # one-cent floor and ceiling only.
        "reliabilityInterior": (reliability_tables, (interior,), {}),
        "compressionInterior": (compression, (interior,), {}),
        "reliabilityBy_generation": (
            reliability_tables,
            (official_binary,),
            {"split": "generation"},
        ),
        "reliabilityBy_era": (reliability_tables, (official_binary,), {"split": "era"}),
        "reliabilityBy_volume": (
            reliability_tables,
            (volume_rows,),
            {"split": "volumeClass"},
        ),
    }
    # Each job seeds its own generator, so threads do not change any number.
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {name: pool.submit(f, *a, **k) for name, (f, a, k) in jobs.items()}
        analyses: dict[str, Any] = {name: futures[name].result() for name in jobs}
    results["analyses"] = analyses
    results["_events"] = events  # for fixtures; removed before serializing
    return results
