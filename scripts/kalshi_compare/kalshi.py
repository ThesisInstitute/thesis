"""Kalshi public market data: events, markets and hourly candlesticks.

Unauthenticated GET requests only. Markets settled before Kalshi's archive
cutoff live in the ``/historical`` tier, which uses different field names
(``close`` rather than ``close_dollars``); ``normalize_candle`` reads both.
"""

from __future__ import annotations

import bisect
import calendar
import dataclasses
import datetime as dt

from .fetch import FetchCache, build_url

API = "https://api.elections.kalshi.com/trade-api/v2"
HOUR = 3600
CANDLE_WINDOW = 30 * 24 * HOUR  # request at most 720 hourly candles at a time


def to_ts(value: str | dt.datetime) -> int:
    if isinstance(value, str):
        value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return calendar.timegm(value.astimezone(dt.timezone.utc).utctimetuple())


def iso(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def series_events(cache: FetchCache, series: str) -> list[dict]:
    events, cursor = [], None
    while True:
        params = {"series_ticker": series, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        payload = cache.get_json(build_url(API, "/events", params))
        events.extend(payload.get("events") or [])
        cursor = payload.get("cursor")
        if not cursor:
            return events


def series_record(cache: FetchCache, series: str) -> dict:
    return cache.get_json(build_url(API, f"/series/{series}"))["series"]


def event_markets(cache: FetchCache, event_ticker: str) -> list[dict]:
    """Markets from the live and historical tiers, one record per ticker.

    Events straddling the archive cutoff appear in both tiers; the live record
    wins and the tier is kept for provenance.
    """
    by_ticker: dict[str, dict] = {}
    for tier, path in (("live", "/markets"), ("historical", "/historical/markets")):
        cursor = None
        while True:
            params = {"event_ticker": event_ticker, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            payload = cache.get_json(build_url(API, path, params))
            for market in payload.get("markets") or []:
                if market["ticker"] not in by_ticker:
                    by_ticker[market["ticker"]] = dict(market, _tier=tier)
            cursor = payload.get("cursor")
            if not cursor:
                break
    return sorted(by_ticker.values(), key=lambda m: m["ticker"])


def _num(block: dict | None, key: str) -> float | None:
    if not block:
        return None
    value = block.get(f"{key}_dollars", block.get(key))
    return None if value is None else float(value)


@dataclasses.dataclass(frozen=True)
class Candle:
    end: int
    bid: float | None
    ask: float | None
    trade_close: float | None
    trade_previous: float | None
    volume: float
    open_interest: float | None


def normalize_candle(raw: dict) -> Candle:
    volume = raw.get("volume_fp", raw.get("volume"))
    interest = raw.get("open_interest_fp", raw.get("open_interest"))
    return Candle(
        end=int(raw["end_period_ts"]),
        bid=_num(raw.get("yes_bid"), "close"),
        ask=_num(raw.get("yes_ask"), "close"),
        trade_close=_num(raw.get("price"), "close"),
        trade_previous=_num(raw.get("price"), "previous"),
        volume=float(volume or 0.0),
        open_interest=None if interest is None else float(interest),
    )


def market_candles(
    cache: FetchCache, series: str, market: dict, start: int, end: int
) -> tuple[list[Candle], str]:
    """Hourly candles for [start, end], from whichever tier holds the market."""
    candles: dict[int, Candle] = {}
    tier_used = None
    tiers = (
        [("historical", f"/historical/markets/{market['ticker']}/candlesticks")]
        if market.get("_tier") == "historical"
        else []
    ) + [
        ("live", f"/series/{series}/markets/{market['ticker']}/candlesticks"),
        ("historical", f"/historical/markets/{market['ticker']}/candlesticks"),
    ]
    for tier, path in tiers:
        got_any = False
        window_start = start
        ok = True
        while window_start < end:
            window_end = min(end, window_start + CANDLE_WINDOW)
            url = build_url(
                API,
                path,
                {"start_ts": window_start, "end_ts": window_end, "period_interval": 60},
            )
            payload = cache.get_json(url, allow_404=True)
            if payload is None:
                ok = False
                break
            for raw in payload.get("candlesticks") or []:
                candle = normalize_candle(raw)
                candles[candle.end] = candle
                got_any = True
            window_start = window_end
        if ok:
            tier_used = tier
            if got_any:
                break
    return [candles[k] for k in sorted(candles)], tier_used or "none"


@dataclasses.dataclass(frozen=True)
class MarketState:
    at: int
    candle_end: int | None
    bid: float | None
    ask: float | None
    mid: float | None
    last: float | None
    spread: float | None
    open_interest: float | None
    volume_7d: float
    traded_ever: bool


def state_at(candles: list[Candle], at: int) -> MarketState:
    """The book as of the latest hourly candle ending at or before ``at``."""
    ends = [c.end for c in candles]
    index = bisect.bisect_right(ends, at) - 1
    volume_7d = sum(c.volume for c in candles if at - 7 * 24 * HOUR < c.end <= at)
    if index < 0:
        return MarketState(
            at, None, None, None, None, None, None, None, volume_7d, False
        )
    candle = candles[index]
    bid = 0.0 if candle.bid is None else candle.bid
    ask = 1.0 if candle.ask is None else candle.ask
    mid = (bid + ask) / 2
    last = (
        candle.trade_close if candle.trade_close is not None else candle.trade_previous
    )
    traded = any(c.trade_close is not None for c in candles[: index + 1]) or (
        last is not None
    )
    return MarketState(
        at=at,
        candle_end=candle.end,
        bid=bid,
        ask=ask,
        mid=mid,
        last=last,
        spread=ask - bid,
        open_interest=candle.open_interest,
        volume_7d=volume_7d,
        traded_ever=traded,
    )


def market_volume(market: dict) -> float | None:
    value = market.get("volume_fp", market.get("volume"))
    return None if value is None else float(value)
