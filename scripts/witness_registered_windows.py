#!/usr/bin/env python3
"""Ask the Internet Archive to capture registered source pages while their
release windows are open.

Some published forecasts are registered with a ``sourceBinding`` that no
resolver leg can execute (today: ``adapter == "generic-url"``). Whether such a
forecast is ever scored is a ruling this script does not make. One possible
ruling needs first-print custody: official bytes, dated by someone other than
Thesis, inside the registered ``expectedReleaseWindow``. That custody can only
be made while the window is open, so this script makes it every day and
decides nothing else.

Each run:

1. reads every registration under ``records/targets`` (read-only);
2. keeps the targets that have no executable plan, whose forecast is still
   pending in the Thesis log, and whose window contains today (UTC);
3. asks the Internet Archive to capture each distinct ``sourceUrl``
   (``GET https://web.archive.org/save/<url>``);
4. reads the Archive's CDX index for the window so far and reports, per URL,
   the capture timestamps it lists or the failure;
5. reads the index once more for windows that closed in the last few days,
   so a window that ended without a capture is known at once.

Evidence lives in the Archive's index, which is public, durable and dated by
a third party. This script writes nothing under ``records/**`` and refuses an
output path there; its report is a convenience copy of facts anyone can
re-read from the index with the registration alone (``--audit`` does that).

What a capture proves, and what it does not: it shows the bytes one URL
served to the Archive's crawler at one instant. It does not show that a
figure on that page is the registered statistic, that any executor would
read it the same way, or that the release had been published by then. See
``docs/registered-window-custody.md``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

REPORT_SCHEMA = "thesis_registered_window_witness_report_v1"
# The only adapter name that names a page and no executor. Used until
# ``resolve_pending.execution_plan_refusal`` exists (branch feat/executor-gate).
NO_EXECUTOR_ADAPTER = "generic-url"
# Transparent and distinct from the resolver's agent, so the Archive and any
# publisher can tell this job apart and find who runs it.
WITNESS_USER_AGENT = (
    "Mozilla/5.0 (compatible; thesis-witness/1.0; +https://app.thesisinstitute.org)"
)
# Same string as resolve_pending.WAYBACK_SAVE_URL on fix/a19-registered-scale;
# ``save_url_template`` prefers the resolver's copy once that branch merges.
WAYBACK_SAVE_URL = "https://web.archive.org/save/{url}"
# The resolver's CDX template filters to HTTP 200 and returns two fields. The
# witness must also see refused and redirected captures to report them, and
# the digest to show whether the page changed, so it builds its own query.
WAYBACK_CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
CDX_FIELDS = ("timestamp", "original", "statuscode", "mimetype", "digest", "length")

DEFAULT_MAX_URLS = 20
DEFAULT_MAX_CLOSED_READS = 20
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_SAVE_TIMEOUT = 150.0
DEFAULT_INDEX_TIMEOUT = 90.0
DEFAULT_ATTEMPTS = 3
DEFAULT_SAVE_PAUSE = 20.0
DEFAULT_INDEX_PAUSE = 5.0
DEFAULT_DEADLINE_MINUTES = 90.0
# Share of the time budget kept for reading the index after the captures.
INDEX_SHARE = 0.25
MAX_RETRY_AFTER = 300.0
BACKOFF_SECONDS = (30.0, 90.0, 180.0)
MAX_BODY_BYTES = 2_000_000
_REGISTRATION_NAME = re.compile(r"\d{4}-\d{2}-\d{2}-([0-9a-f]{64})\.json")
_CAPTURE_URL = re.compile(r"https?://web\.archive\.org/web/(\d{14})[a-z_]*/(.+)")


# ---------------------------------------------------------------------------
# Transport


@dataclass(frozen=True)
class Response:
    status: int
    final_url: str
    headers: Mapping[str, str]
    body: bytes


class FetchError(Exception):
    """One request failed. ``status`` is None for a transport failure."""

    def __init__(
        self,
        detail: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status
        self.retry_after = retry_after


Fetcher = Callable[[str, float], Response]


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except ValueError:
        return None


def _one_line(raw: bytes, limit: int = 160) -> str:
    text = re.sub(r"<[^>]+>", " ", raw[:4000].decode("utf-8", errors="replace"))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def http_fetch(url: str, timeout: float) -> Response:
    """GET ``url`` with the witness User-Agent. Raises only FetchError."""

    request = urllib.request.Request(url, headers={"User-Agent": WITNESS_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(
                status=int(response.status),
                final_url=str(response.geturl()),
                headers={k.lower(): v for k, v in response.headers.items()},
                body=response.read(MAX_BODY_BYTES),
            )
    except urllib.error.HTTPError as exc:
        try:
            excerpt = _one_line(exc.read(4000))
        except Exception:  # noqa: BLE001 - the status line is already enough
            excerpt = ""
        raise FetchError(
            f"HTTP {exc.code}" + (f": {excerpt}" if excerpt else ""),
            status=int(exc.code),
            retry_after=_retry_after_seconds(exc.headers.get("Retry-After")),
        ) from exc
    except Exception as exc:  # noqa: BLE001 - every transport fault is one outcome
        raise FetchError(f"{type(exc).__name__}: {str(exc)[:200]}") from exc


@dataclass
class Transport:
    """Bounded, paced requests. Every failure comes back as a value."""

    fetch: Fetcher = http_fetch
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    today: Callable[[], dt.date] = lambda: dt.datetime.now(dt.timezone.utc).date()
    attempts: int = DEFAULT_ATTEMPTS
    deadline_seconds: float = DEFAULT_DEADLINE_MINUTES * 60
    # Seconds of the budget the current phase may not spend. The capture
    # phase holds some back so the index is still read after a slow Archive.
    hold_back: float = 0.0
    started: float = field(init=False)

    def __post_init__(self) -> None:
        self.started = self.clock()

    def remaining(self) -> float:
        spent = self.clock() - self.started
        return self.deadline_seconds - self.hold_back - spent

    def pause(self, seconds: float) -> None:
        if seconds > 0 and self.remaining() > seconds:
            self.sleep(seconds)

    def get(self, url: str, timeout: float) -> tuple[Response | None, dict[str, Any]]:
        """(response, outcome). ``response`` is None when every attempt failed."""

        failures: list[str] = []
        status: int | None = None
        made = 0
        for attempt in range(1, max(1, self.attempts) + 1):
            if self.remaining() <= 0:
                failures.append("time budget exhausted before the attempt")
                break
            made = attempt
            try:
                response = self.fetch(url, min(timeout, max(1.0, self.remaining())))
            except FetchError as exc:
                failures.append(exc.detail)
                status = exc.status
                wait = exc.retry_after
                if wait is None:
                    wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]
                wait = min(wait, MAX_RETRY_AFTER)
                if attempt < self.attempts and self.remaining() > wait + timeout:
                    self.sleep(wait)
                    continue
                if attempt < self.attempts:
                    failures.append("no time left in the budget for another attempt")
                break
            except Exception as exc:  # noqa: BLE001 - an injected fetcher's bug is one failure
                failures.append(f"{type(exc).__name__}: {str(exc)[:200]}")
                break
            return response, {
                "ok": True,
                "attempts": attempt,
                "httpStatus": response.status,
                "earlierFailures": failures,
            }
        return None, {
            "ok": False,
            "attempts": made,
            "httpStatus": status,
            "failures": failures,
        }


# ---------------------------------------------------------------------------
# Selection (offline)


@dataclass(frozen=True)
class Target:
    data_point_id: str
    catalog_slug: str
    source_url: str
    window_start: dt.date
    window_end: dt.date
    registration_file: str
    target_content_hash: str
    no_plan_reason: str
    allowed_hosts: tuple[str, ...]

    def window_state(self, today: dt.date) -> str:
        if today < self.window_start:
            return "future"
        if today > self.window_end:
            return "closed"
        return "open"

    def as_json(self) -> dict[str, Any]:
        return {
            "dataPointId": self.data_point_id,
            "catalogSlug": self.catalog_slug,
            "expectedReleaseWindow": {
                "start": self.window_start.isoformat(),
                "end": self.window_end.isoformat(),
            },
            "registrationFile": self.registration_file,
            "targetContentHash": self.target_content_hash,
            "noExecutablePlan": self.no_plan_reason,
        }


@dataclass(frozen=True)
class Problem:
    """Something that kept a file or a target out of the run.

    ``data_point_id`` None marks a file-level problem, always reported. A
    target-level problem is reported only while it matters: the target is
    pending and its window has not been closed for longer than the lookback.
    """

    text: str
    data_point_id: str | None = None
    window_end: dt.date | None = None

    def matters(
        self, pending: set[str] | None, today: dt.date, lookback_days: int | None
    ) -> bool:
        if self.data_point_id is None:
            return True
        if pending is not None and self.data_point_id not in pending:
            return False
        if self.window_end is None or lookback_days is None:
            return True
        return (today - self.window_end).days <= lookback_days


def _load_resolver() -> tuple[Any | None, str | None]:
    """The resolver module, or the reason it could not be imported.

    The witness must keep running when the resolver does not import (a new
    dependency, a syntax error on main): a missed window cannot be redone.
    """

    try:
        import resolve_pending  # noqa: PLC0415

        return resolve_pending, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:200]}"


def _load_content_hash() -> tuple[Callable[[dict[str, Any]], str] | None, str | None]:
    try:
        from register_targets import registration_content_hash  # noqa: PLC0415

        return registration_content_hash, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:200]}"


def save_url_template(resolver: Any | None) -> str:
    template = getattr(resolver, "WAYBACK_SAVE_URL", None)
    if isinstance(template, str) and "{url}" in template:
        return template
    return WAYBACK_SAVE_URL


def plan_predicate(
    resolver: Any | None,
) -> tuple[Callable[[dict[str, Any]], str | None], str]:
    """(registration -> why it has no executable plan or None, description)."""

    gate = getattr(resolver, "execution_plan_refusal", None)
    if callable(gate):

        def by_gate(registration: dict[str, Any]) -> str | None:
            try:
                refusal = gate(registration)
            except Exception as exc:  # noqa: BLE001
                # Capturing a page the resolver could in fact execute costs
                # one request. Skipping one it could not costs the window.
                return (
                    "execution_plan_refusal raised "
                    f"{type(exc).__name__}: {str(exc)[:160]} (witnessing anyway)"
                )
            return str(refusal) if refusal else None

        return by_gate, "resolve_pending.execution_plan_refusal"

    def by_adapter(registration: dict[str, Any]) -> str | None:
        contract = registration.get("contract") or {}
        binding = contract.get("sourceBinding") or {}
        if binding.get("adapter") == NO_EXECUTOR_ADAPTER:
            return f"sourceBinding.adapter is {NO_EXECUTOR_ADAPTER!r}"
        return None

    return by_adapter, f'sourceBinding.adapter == "{NO_EXECUTOR_ADAPTER}"'


def _url_problem(url: Any) -> str | None:
    if not isinstance(url, str) or not url:
        return "no sourceUrl"
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError as exc:
        return f"unparseable sourceUrl: {exc}"
    if parts.scheme not in ("http", "https"):
        return f"sourceUrl scheme {parts.scheme!r} is not http(s)"
    if not host:
        return "sourceUrl has no host"
    if parts.username or parts.password:
        return "sourceUrl carries credentials"
    if host == "web.archive.org" or host.endswith(".archive.org"):
        return "sourceUrl is already an Internet Archive URL"
    if re.search(r"\s", url):
        return "sourceUrl contains whitespace"
    return None


def scan_registrations(
    targets_dir: pathlib.Path,
    no_plan: Callable[[dict[str, Any]], str | None],
    content_hash: Callable[[dict[str, Any]], str] | None,
) -> tuple[list[Target], list[Problem]]:
    """Every target with no executable plan, and the problems met on the way.

    Reads only. A file that cannot be authenticated is reported and skipped:
    its sourceUrl is not a registered one.
    """

    targets: list[Target] = []
    problems: list[Problem] = []
    if not targets_dir.is_dir():
        return targets, [Problem(f"registration directory not found: {targets_dir}")]
    for path in sorted(targets_dir.glob("*.json")):
        match = _REGISTRATION_NAME.fullmatch(path.name)
        if not match:
            continue
        try:
            snapshot = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            problems.append(Problem(f"{path.name}: unreadable ({type(exc).__name__})"))
            continue
        if not isinstance(snapshot, dict):
            problems.append(Problem(f"{path.name}: not a JSON object"))
            continue
        if content_hash is not None:
            try:
                actual = content_hash(snapshot)
            except Exception as exc:  # noqa: BLE001
                problems.append(
                    Problem(
                        f"{path.name}: content hash failed "
                        f"({type(exc).__name__}: {str(exc)[:120]})"
                    )
                )
                continue
            if actual != match.group(1):
                problems.append(
                    Problem(f"{path.name}: content hash does not match its name")
                )
                continue
        rows = snapshot.get("targets")
        for target in rows if isinstance(rows, list) else []:
            if not isinstance(target, dict):
                continue
            binding = target.get("sourceBinding")
            ref = target.get("dataPointId")
            if not isinstance(binding, dict) or not isinstance(ref, str) or not ref:
                continue
            registration = {
                "targetContentHash": match.group(1),
                "contract": target,
                "ledgerPin": snapshot.get("ledgerPin"),
            }
            try:
                reason = no_plan(registration)
            except Exception as exc:  # noqa: BLE001
                reason = (
                    f"plan predicate raised {type(exc).__name__} (witnessing anyway)"
                )
            if not reason:
                continue
            window = binding.get("expectedReleaseWindow")
            try:
                start = dt.date.fromisoformat(str((window or {})["start"]))
                end = dt.date.fromisoformat(str((window or {})["end"]))
            except (KeyError, TypeError, ValueError):
                problems.append(
                    Problem(
                        f"{path.name}: {ref} has no dated expectedReleaseWindow; "
                        "no window, so no capture is ever requested for it",
                        data_point_id=ref,
                    )
                )
                continue
            if end < start:
                problems.append(
                    Problem(
                        f"{path.name}: {ref} window ends before it starts",
                        data_point_id=ref,
                    )
                )
                continue
            url = binding.get("sourceUrl")
            url_problem = _url_problem(url)
            if url_problem:
                problems.append(
                    Problem(
                        f"{path.name}: {ref}: {url_problem}",
                        data_point_id=ref,
                        window_end=end,
                    )
                )
                continue
            hosts = binding.get("allowedHosts")
            targets.append(
                Target(
                    data_point_id=ref,
                    catalog_slug=str(target.get("catalogSlug") or ""),
                    source_url=str(url),
                    window_start=start,
                    window_end=end,
                    registration_file=path.name,
                    target_content_hash=match.group(1),
                    no_plan_reason=reason,
                    allowed_hosts=tuple(h for h in hosts if isinstance(h, str))
                    if isinstance(hosts, list)
                    else (),
                )
            )
    return targets, problems


def pending_refs(log: Mapping[str, Any]) -> set[str]:
    """dataPointIds whose forecast the Thesis log still lists as pending."""

    refs: set[str] = set()
    for link in log.get("resolutionLinks") or []:
        if not isinstance(link, dict) or link.get("status") != "pending":
            continue
        ref = link.get("targetFactRef")
        if isinstance(ref, str) and ref:
            refs.add(ref)
    return refs


def _dedupe(targets: Iterable[Target]) -> list[Target]:
    """One row per (dataPointId, sourceUrl, window).

    A dataPointId can sit in several snapshots. Identical copies collapse;
    copies that differ in URL or window are all kept, because which one binds
    is the resolver's question and a second capture costs one request.
    """

    seen: dict[tuple[str, str, dt.date, dt.date], Target] = {}
    for target in targets:
        key = (
            target.data_point_id,
            target.source_url,
            target.window_start,
            target.window_end,
        )
        seen.setdefault(key, target)
    return list(seen.values())


@dataclass
class UrlPlan:
    source_url: str
    targets: list[Target]

    @property
    def host(self) -> str:
        return urllib.parse.urlsplit(self.source_url).hostname or ""

    @property
    def earliest_start(self) -> dt.date:
        return min(t.window_start for t in self.targets)

    @property
    def soonest_end(self) -> dt.date:
        return min(t.window_end for t in self.targets)

    @property
    def latest_end(self) -> dt.date:
        return max(t.window_end for t in self.targets)


def _group(targets: Iterable[Target]) -> list[UrlPlan]:
    grouped: dict[str, list[Target]] = {}
    for target in targets:
        grouped.setdefault(target.source_url, []).append(target)
    plans = [
        UrlPlan(url, sorted(rows, key=lambda t: (t.window_end, t.data_point_id)))
        for url, rows in grouped.items()
    ]
    return sorted(plans, key=lambda p: (p.soonest_end, p.source_url))


def _interleave_hosts(plans: Sequence[UrlPlan]) -> list[UrlPlan]:
    """Keep urgency order, but avoid asking for one host twice in a row."""

    remaining = list(plans)
    ordered: list[UrlPlan] = []
    while remaining:
        last = ordered[-1].host if ordered else None
        pick = next((p for p in remaining if p.host != last), remaining[0])
        remaining.remove(pick)
        ordered.append(pick)
    return ordered


@dataclass
class Selection:
    today: dt.date
    open_plans: list[UrlPlan]
    dropped_open: list[UrlPlan]
    closed_plans: list[UrlPlan]
    dropped_closed: list[UrlPlan]
    not_pending_in_window: list[Target]
    future_targets: int
    pending_known: bool


def select(
    targets: Sequence[Target],
    pending: set[str] | None,
    today: dt.date,
    *,
    max_urls: int = DEFAULT_MAX_URLS,
    lookback_days: int | None = DEFAULT_LOOKBACK_DAYS,
    max_closed_reads: int | None = DEFAULT_MAX_CLOSED_READS,
) -> Selection:
    """Split the no-plan targets by window state on ``today``.

    ``pending`` None means the log could not be read. Then every target in an
    open window is kept: an extra capture is harmless and a skipped one is
    not recoverable. ``lookback_days`` None keeps every closed window.
    """

    unique = _dedupe(targets)
    if pending is None:
        live, skipped = unique, []
    else:
        live = [t for t in unique if t.data_point_id in pending]
        skipped = [
            t
            for t in unique
            if t.data_point_id not in pending and t.window_state(today) == "open"
        ]
    open_targets = [t for t in live if t.window_state(today) == "open"]
    closed_targets = [
        t
        for t in live
        if t.window_state(today) == "closed"
        and (lookback_days is None or (today - t.window_end).days <= lookback_days)
    ]
    open_plans = _group(open_targets)
    kept_open = _interleave_hosts(open_plans[: max(0, max_urls)])
    closed_plans = sorted(
        _group(closed_targets), key=lambda p: (p.latest_end, p.source_url), reverse=True
    )
    limit = len(closed_plans) if max_closed_reads is None else max(0, max_closed_reads)
    return Selection(
        today=today,
        open_plans=kept_open,
        dropped_open=open_plans[max(0, max_urls) :],
        closed_plans=closed_plans[:limit],
        dropped_closed=closed_plans[limit:],
        not_pending_in_window=skipped,
        future_targets=sum(1 for t in live if t.window_state(today) == "future"),
        pending_known=pending is not None,
    )


# ---------------------------------------------------------------------------
# Known limits (reported beside each URL; never used to skip one)


def known_limits(url: str) -> list[str]:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    query = parts.query.lower()
    path = parts.path.lower()
    notes: list[str] = []
    if host == "ssa.gov" or host.endswith(".ssa.gov"):
        notes.append(
            "ssa.gov refused Save Page Now with HTTP 520 on every attempt on "
            "2026-08-23 (docs/anchor-verifications.md, SSA official pages). "
            "Expect the save to fail; a capture in the index would come from "
            "the Archive's own crawl."
        )
    if host == "bls.gov" or host.endswith(".bls.gov"):
        notes.append(
            "bls.gov answers non-browser clients with HTTP 403, but the "
            "Archive's crawler has stored HTTP 200 captures of this host "
            "(cpseea19.htm: 20260710110509, 20260819191418, 20260904170006). "
            "A capture with a status other than 200 is not custody of the page."
        )
    api_like = (
        host.startswith(("api.", "data.api."))
        or "/api/" in path
        or "/rest/" in path
        or "/wds/" in path
        or "/sdmx/" in path
        or "format=json" in query
        or "format=jsondata" in query
        or path.endswith((".json", ".csv", ".xml"))
    )
    if api_like:
        notes.append(
            "API URL: a capture holds one response to this exact query "
            "string at one instant. It is a payload, not a release, and says "
            "nothing about what the publisher announced that day."
        )
    return notes


# ---------------------------------------------------------------------------
# The Archive


def cdx_url(url: str, start: dt.date, end: dt.date) -> str:
    query = urllib.parse.urlencode(
        {
            "url": url,
            "from": f"{start:%Y%m%d}000000",
            "to": f"{end:%Y%m%d}235959",
            "output": "json",
            "fl": ",".join(CDX_FIELDS),
        }
    )
    return f"{WAYBACK_CDX_ENDPOINT}?{query}"


def parse_cdx(body: bytes, start: dt.date, end: dt.date) -> list[dict[str, str]]:
    """Index rows dated inside [start, end], oldest first. Raises ValueError."""

    text = body.decode("utf-8", errors="replace").strip()
    payload = json.loads(text or "[]")
    if not isinstance(payload, list) or not all(isinstance(r, list) for r in payload):
        raise ValueError("the Archive index is not a list of rows")
    if not payload:
        return []
    header, *rows = payload
    if "timestamp" not in header or "statuscode" not in header:
        raise ValueError(f"the Archive index header is {header!r}")
    captures: list[dict[str, str]] = []
    for row in rows:
        record = {str(k): str(v) for k, v in zip(header, row)}
        stamp = record.get("timestamp", "")
        if not re.fullmatch(r"\d{14}", stamp):
            continue
        try:
            day = dt.datetime.strptime(stamp, "%Y%m%d%H%M%S").date()
        except ValueError:
            continue
        if start <= day <= end:
            captures.append(record)
    return sorted(captures, key=lambda r: r["timestamp"])


def capture_iso(timestamp: str) -> str:
    return dt.datetime.strptime(timestamp, "%Y%m%d%H%M%S").strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def capture_link(timestamp: str, url: str) -> str:
    return f"https://web.archive.org/web/{timestamp}/{url}"


def _is_page_capture(record: Mapping[str, str]) -> bool:
    return record.get("statuscode") == "200"


def reported_capture(response: Response) -> tuple[str, str] | None:
    """(timestamp, archived URL) the save response names, if it names one.

    A hint only. The index is the evidence; this helps when the index lags.
    """

    location = response.headers.get("content-location", "")
    for candidate in (response.final_url, location):
        if candidate.startswith("/web/"):
            candidate = "https://web.archive.org" + candidate
        match = _CAPTURE_URL.fullmatch(candidate)
        if match:
            return match.group(1), match.group(2)
    return None


def read_index(
    transport: Transport, url: str, start: dt.date, end: dt.date, timeout: float
) -> dict[str, Any]:
    response, outcome = transport.get(cdx_url(url, start, end), timeout)
    result: dict[str, Any] = {
        "queried": {"url": url, "from": start.isoformat(), "to": end.isoformat()},
        "request": outcome,
    }
    if response is None:
        result["ok"] = False
        result["failure"] = "; ".join(outcome.get("failures") or ["no response"])
        return result
    try:
        rows = parse_cdx(response.body, start, end)
    except (ValueError, TypeError) as exc:
        result["ok"] = False
        result["failure"] = f"index unreadable: {type(exc).__name__}: {str(exc)[:160]}"
        return result
    result["ok"] = True
    result["captures"] = rows
    return result


def _window_custody(
    target: Target, rows: Sequence[Mapping[str, str]], upto: dt.date
) -> dict[str, Any]:
    end = min(target.window_end, upto)
    inside = [
        r
        for r in rows
        if _is_page_capture(r)
        and target.window_start
        <= dt.datetime.strptime(r["timestamp"], "%Y%m%d%H%M%S").date()
        <= end
    ]
    return {
        **target.as_json(),
        "http200CapturesInWindow": len(inside),
        "firstCaptureInWindow": capture_iso(inside[0]["timestamp"]) if inside else None,
        "lastCaptureInWindow": capture_iso(inside[-1]["timestamp"]) if inside else None,
        "distinctDigestsInWindow": len({r.get("digest") for r in inside}),
    }


def witness_url(
    plan: UrlPlan,
    today: dt.date,
    transport: Transport,
    *,
    save_template: str,
    save: bool,
    save_timeout: float,
    skip_since: dt.time | None = None,
    index_timeout: float = DEFAULT_INDEX_TIMEOUT,
) -> dict[str, Any]:
    """Ask for one capture. Never raises.

    ``skip_since`` is for a second pass on the same day: a URL the index
    already shows captured today at or after that UTC time is left alone. An
    earlier capture does not count, because it may predate the day's release,
    and an index that cannot be read never excuses the request.
    """

    entry: dict[str, Any] = {
        "sourceUrl": plan.source_url,
        "host": plan.host,
        "knownLimits": known_limits(plan.source_url),
        "registrations": [t.as_json() for t in plan.targets],
    }
    off_list = sorted(
        {t.data_point_id for t in plan.targets if t.allowed_hosts}
        - {t.data_point_id for t in plan.targets if plan.host in t.allowed_hosts}
    )
    if off_list:
        entry["knownLimits"].append(
            f"host {plan.host!r} is outside the registered allowedHosts of "
            + ", ".join(off_list)
        )
    if not save:
        entry["save"] = {"requested": False, "why": "index read only"}
        return entry
    # The invariant this whole script exists to keep. ``select`` already
    # filtered on the run's date; this re-checks on the UTC date at the moment
    # the request leaves, so a run that crosses midnight cannot ask for a
    # capture dated after a window's last day.
    moment = transport.today()
    if not all(
        any(t.window_state(day) == "open" for t in plan.targets)
        for day in (today, moment)
    ):
        entry["save"] = {
            "requested": False,
            "why": f"no registered window contains {moment.isoformat()}",
        }
        return entry
    try:
        if skip_since is not None:
            floor = f"{moment:%Y%m%d}{skip_since:%H%M}00"
            earlier = read_index(
                transport, plan.source_url, moment, moment, index_timeout
            )
            held = [
                r
                for r in earlier.get("captures") or []
                if _is_page_capture(r) and r["timestamp"] >= floor
            ]
            if held:
                entry["save"] = {
                    "requested": False,
                    "why": (
                        "the index already lists an HTTP 200 capture at "
                        f"{capture_iso(held[-1]['timestamp'])}, after the "
                        f"{skip_since:%H:%M} UTC floor of this pass"
                    ),
                }
                return entry
        target_url = save_template.format(url=plan.source_url)
        response, outcome = transport.get(target_url, save_timeout)
        record: dict[str, Any] = {"requested": True, **outcome}
        if response is not None:
            named = reported_capture(response)
            if named:
                record["reportedCapture"] = {
                    "timestamp": named[0],
                    "capturedAt": capture_iso(named[0]),
                    "archivedUrl": named[1],
                    "link": capture_link(named[0], named[1]),
                }
        entry["save"] = record
    except Exception as exc:  # noqa: BLE001 - one URL's fault must not stop the run
        entry["save"] = {
            "requested": True,
            "ok": False,
            "failures": [f"{type(exc).__name__}: {str(exc)[:200]}"],
        }
    return entry


def confirm_url(
    entry: dict[str, Any],
    plan: UrlPlan,
    today: dt.date,
    transport: Transport,
    *,
    index_timeout: float,
    index_pause: float,
) -> None:
    """Read the index for the window so far and set the verdict. Never raises."""

    try:
        # ``today`` is the run's date; the clock may have passed midnight
        # since, and a capture made after it is dated the next day.
        upto = min(max(today, transport.today()), plan.latest_end)
        index = read_index(
            transport, plan.source_url, plan.earliest_start, upto, index_timeout
        )
        entry["index"] = index
        rows = index.get("captures") or []
        entry["registrations"] = [_window_custody(t, rows, upto) for t in plan.targets]
        named = (entry.get("save") or {}).get("reportedCapture")
        # A page that redirects is stored under the URL it redirected to, so
        # the registered URL's index shows a 3xx row and no page. Say where
        # the page went; whether that URL is the registered source is not
        # this script's call.
        if (
            index.get("ok")
            and named
            and named["archivedUrl"] != plan.source_url
            and not any(_is_page_capture(r) and _since(r, today) for r in rows)
        ):
            transport.pause(index_pause)
            entry["redirectTargetIndex"] = read_index(
                transport, named["archivedUrl"], today, upto, index_timeout
            )
    except Exception as exc:  # noqa: BLE001 - one URL's fault must not stop the run
        entry["index"] = {
            "ok": False,
            "failure": f"{type(exc).__name__}: {str(exc)[:200]}",
        }
    entry["verdict"] = _verdict(entry, today)


def _since(record: Mapping[str, str], day: dt.date) -> bool:
    return record.get("timestamp", "")[:8] >= f"{day:%Y%m%d}"


def _save_phrase(save: Mapping[str, Any]) -> str:
    if not save.get("requested"):
        return "no save was requested (" + str(save.get("why") or "no reason") + ")"
    if not save.get("ok"):
        return "the save request failed: " + "; ".join(
            save.get("failures") or ["no detail"]
        )
    named = save.get("reportedCapture")
    status = save.get("httpStatus")
    if named:
        return (
            f"the save request returned HTTP {status} and named a capture at "
            f"{named['capturedAt']}"
        )
    return f"the save request returned HTTP {status} and named no capture"


def _verdict(entry: Mapping[str, Any], today: dt.date) -> dict[str, Any]:
    """What the index says about this run's day, beside what the save said."""

    save = entry.get("save") or {}
    index = entry.get("index") or {}
    phrase = _save_phrase(save)
    todays = [r for r in index.get("captures") or [] if _since(r, today)]
    pages = [r for r in todays if _is_page_capture(r)]
    if pages:
        stamp = pages[-1]["timestamp"]
        return {
            "code": "CAPTURED",
            "capturedAt": capture_iso(stamp),
            "link": capture_link(stamp, entry["sourceUrl"]),
            "digest": pages[-1].get("digest"),
            "text": (
                f"the index lists an HTTP 200 capture at {capture_iso(stamp)}; {phrase}"
            ),
        }
    redirect = entry.get("redirectTargetIndex") or {}
    moved = [
        r
        for r in redirect.get("captures") or []
        if _is_page_capture(r) and _since(r, today)
    ]
    if moved:
        stamp = moved[-1]["timestamp"]
        target = redirect["queried"]["url"]
        return {
            "code": "CAPTURED_UNDER_REDIRECT_TARGET",
            "capturedAt": capture_iso(stamp),
            "link": capture_link(stamp, target),
            "text": (
                "the registered URL redirected; the index lists an HTTP 200 "
                f"capture of {target} at {capture_iso(stamp)} and none of the "
                "registered URL"
            ),
        }
    if not index.get("ok"):
        return {
            "code": "INDEX_UNREAD",
            "text": f"the index could not be read ({index.get('failure')}); {phrase}",
        }
    statuses = sorted({r.get("statuscode", "?") for r in todays})
    if statuses:
        return {
            "code": "CAPTURED_NOT_AS_PAGE",
            "text": (
                "the index lists today's capture only with HTTP status "
                f"{', '.join(statuses)}, which is not custody of the page; {phrase}"
            ),
        }
    if save.get("requested") and save.get("ok"):
        return {
            "code": "SAVE_NOT_YET_INDEXED",
            "text": (
                f"{phrase}; the index does not list it yet. The index can lag, "
                "and the next run re-reads the whole window."
            ),
        }
    if save.get("requested"):
        return {
            "code": "SAVE_FAILED",
            "text": f"{phrase}; the index lists no capture today",
        }
    return {
        "code": "NO_CAPTURE_TODAY",
        "text": f"the index lists no capture today; {phrase}",
    }


def closed_window_report(
    plan: UrlPlan, transport: Transport, *, index_timeout: float
) -> dict[str, Any]:
    """Index read for windows that have closed. Requests no capture."""

    entry: dict[str, Any] = {
        "sourceUrl": plan.source_url,
        "host": plan.host,
        "knownLimits": known_limits(plan.source_url),
    }
    try:
        index = read_index(
            transport,
            plan.source_url,
            plan.earliest_start,
            plan.latest_end,
            index_timeout,
        )
        entry["index"] = index
        rows = index.get("captures") or []
        entry["registrations"] = [
            _window_custody(t, rows, t.window_end) for t in plan.targets
        ]
    except Exception as exc:  # noqa: BLE001
        entry["index"] = {
            "ok": False,
            "failure": f"{type(exc).__name__}: {str(exc)[:200]}",
        }
        entry["registrations"] = [t.as_json() for t in plan.targets]
    return entry


# ---------------------------------------------------------------------------
# Run and report


@dataclass
class Options:
    mode: str = "capture"  # capture | dry-run | audit
    max_urls: int = DEFAULT_MAX_URLS
    max_closed_reads: int = DEFAULT_MAX_CLOSED_READS
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    save_timeout: float = DEFAULT_SAVE_TIMEOUT
    index_timeout: float = DEFAULT_INDEX_TIMEOUT
    save_pause: float = DEFAULT_SAVE_PAUSE
    index_pause: float = DEFAULT_INDEX_PAUSE
    skip_since: dt.time | None = None


def custody_gaps(
    report: Mapping[str, Any], today: dt.date
) -> dict[str, list[dict[str, Any]]]:
    """Windows about to close, or just closed, with no HTTP 200 capture.

    Only counted where the index was read: an unread index is a failure to
    look, reported as such, not a finding that nothing is there. A window on
    its last two days whose save named a capture the index does not list yet
    is kept apart, because index lag is the likelier explanation.
    """

    gaps: dict[str, list[dict[str, Any]]] = {
        "closingWithoutCapture": [],
        "closingAwaitingIndex": [],
        "closedWithoutCapture": [],
    }
    for entry in report.get("openWindows") or []:
        if not (entry.get("index") or {}).get("ok"):
            continue
        code = (entry.get("verdict") or {}).get("code")
        if code == "CAPTURED_UNDER_REDIRECT_TARGET":
            continue
        named = (entry.get("save") or {}).get("reportedCapture")
        for row in entry.get("registrations") or []:
            end = dt.date.fromisoformat(row["expectedReleaseWindow"]["end"])
            if row.get("http200CapturesInWindow") != 0 or (end - today).days > 1:
                continue
            key = (
                "closingAwaitingIndex"
                if code == "SAVE_NOT_YET_INDEXED" and named
                else "closingWithoutCapture"
            )
            gaps[key].append({"sourceUrl": entry["sourceUrl"], **row})
    for entry in report.get("closedWindows") or []:
        if not (entry.get("index") or {}).get("ok"):
            continue
        for row in entry.get("registrations") or []:
            if row.get("http200CapturesInWindow") == 0:
                gaps["closedWithoutCapture"].append(
                    {"sourceUrl": entry["sourceUrl"], **row}
                )
    return gaps


def run(
    *,
    targets: Sequence[Target],
    pending: set[str] | None,
    today: dt.date,
    transport: Transport,
    options: Options,
    save_template: str = WAYBACK_SAVE_URL,
    preamble: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One witness run over already-loaded state. Never raises for a URL."""

    audit = options.mode == "audit"
    selection = select(
        targets,
        pending,
        today,
        max_urls=len(targets) + 1 if audit else options.max_urls,
        lookback_days=None if audit else options.lookback_days,
        max_closed_reads=None if audit else options.max_closed_reads,
    )
    report: dict[str, Any] = {
        "schemaVersion": REPORT_SCHEMA,
        "mode": options.mode,
        "todayUtc": today.isoformat(),
        **(preamble or {}),
        "pendingStateKnown": selection.pending_known,
        "counts": {
            "noPlanTargets": len(_dedupe(targets)),
            "openUrls": len(selection.open_plans),
            "openTargets": sum(len(p.targets) for p in selection.open_plans),
            "openUrlsDroppedByCap": len(selection.dropped_open),
            "closedUrlsRead": len(selection.closed_plans),
            "closedUrlsDroppedByCap": len(selection.dropped_closed),
            "inWindowButNotPending": len(selection.not_pending_in_window),
            "windowsNotYetOpen": selection.future_targets,
        },
        "droppedByCap": [
            {"sourceUrl": p.source_url, "soonestWindowEnd": p.soonest_end.isoformat()}
            for p in selection.dropped_open
        ],
        "closedDroppedByCap": [p.source_url for p in selection.dropped_closed],
        "inWindowButNotPending": [t.as_json() for t in selection.not_pending_in_window],
        "openWindows": [],
        "closedWindows": [],
    }
    if options.mode == "dry-run":
        report["openWindows"] = [
            {
                "sourceUrl": p.source_url,
                "host": p.host,
                "wouldRequest": save_template.format(url=p.source_url),
                "knownLimits": known_limits(p.source_url),
                "registrations": [t.as_json() for t in p.targets],
            }
            for p in selection.open_plans
        ]
        report["closedWindows"] = [
            {
                "sourceUrl": p.source_url,
                "host": p.host,
                "wouldReadIndex": cdx_url(p.source_url, p.earliest_start, p.latest_end),
                "registrations": [t.as_json() for t in p.targets],
            }
            for p in selection.closed_plans
        ]
        return report

    entries: list[tuple[dict[str, Any], UrlPlan]] = []
    transport.hold_back = 0.0 if audit else transport.deadline_seconds * INDEX_SHARE
    for position, plan in enumerate(selection.open_plans):
        if position and not audit:
            transport.pause(options.save_pause)
        entry = witness_url(
            plan,
            today,
            transport,
            save_template=save_template,
            save=not audit,
            save_timeout=options.save_timeout,
            skip_since=options.skip_since,
            index_timeout=options.index_timeout,
        )
        entries.append((entry, plan))
    # Index reads come after every save, which gives the index the longest
    # head start this run can offer.
    transport.hold_back = 0.0
    for position, (entry, plan) in enumerate(entries):
        if position:
            transport.pause(options.index_pause)
        confirm_url(
            entry,
            plan,
            today,
            transport,
            index_timeout=options.index_timeout,
            index_pause=options.index_pause,
        )
        report["openWindows"].append(entry)
    for plan in selection.closed_plans:
        transport.pause(options.index_pause)
        report["closedWindows"].append(
            closed_window_report(plan, transport, index_timeout=options.index_timeout)
        )
    report["custodyGaps"] = custody_gaps(report, today)
    return report


def render_text(report: Mapping[str, Any]) -> str:
    lines = [
        f"Registered-window witness, {report['todayUtc']} UTC, mode {report['mode']}",
        f"  no-plan rule: {report.get('noPlanRule', 'n/a')}",
    ]
    for note in report.get("notes") or []:
        lines.append(f"  NOTE: {note}")
    for problem in report.get("registrationProblems") or []:
        lines.append(f"  REGISTRATION PROBLEM: {problem}")
    counts = report["counts"]
    lines.append(
        f"  {counts['openUrls']} URL(s) in an open window "
        f"({counts['openTargets']} target(s)); {counts['windowsNotYetOpen']} target(s) "
        f"not yet open; {counts['inWindowButNotPending']} in a window but not pending"
    )
    for dropped in report.get("droppedByCap") or []:
        lines.append(
            f"  DROPPED BY DAILY CAP (not requested today): {dropped['sourceUrl']} "
            f"(window ends {dropped['soonestWindowEnd']})"
        )
    for entry in report.get("openWindows") or []:
        lines.append("")
        lines.append(f"  {entry['sourceUrl']}")
        for row in entry.get("registrations") or []:
            window = row["expectedReleaseWindow"]
            custody = (
                f"; {row['http200CapturesInWindow']} HTTP 200 capture(s) in window"
                f" so far, {row['distinctDigestsInWindow']} distinct digest(s)"
                if "http200CapturesInWindow" in row
                else ""
            )
            lines.append(
                f"    {row['dataPointId']}  window {window['start']}..{window['end']}"
                f"{custody}"
            )
        if "wouldRequest" in entry:
            lines.append(f"    WOULD REQUEST: {entry['wouldRequest']}")
        if "verdict" in entry:
            lines.append(f"    {entry['verdict']['code']}: {entry['verdict']['text']}")
            if entry["verdict"].get("link"):
                lines.append(f"    {entry['verdict']['link']}")
        for note in entry.get("knownLimits") or []:
            lines.append(f"    LIMIT: {note}")
    if report.get("closedWindows"):
        lines.append("")
        lines.append(
            "  Windows already closed (index read only, no capture requested):"
        )
    for entry in report.get("closedWindows") or []:
        lines.append(f"  {entry['sourceUrl']}")
        if "wouldReadIndex" in entry:
            lines.append(f"    WOULD READ: {entry['wouldReadIndex']}")
        index = entry.get("index")
        if index is not None and not index.get("ok"):
            lines.append(f"    INDEX UNREAD: {index.get('failure')}")
        for row in entry.get("registrations") or []:
            window = row["expectedReleaseWindow"]
            if "http200CapturesInWindow" not in row:
                span = f"{window['start']}..{window['end']}"
                lines.append(f"    {row['dataPointId']}  window {span}")
                continue
            count = row["http200CapturesInWindow"]
            lines.append(
                f"    {row['dataPointId']}  window {window['start']}..{window['end']}: "
                + (
                    f"{count} HTTP 200 capture(s), first {row['firstCaptureInWindow']}"
                    if count
                    else "WINDOW CLOSED WITHOUT A CAPTURE"
                )
            )
    gaps = report.get("custodyGaps") or {}
    for row in gaps.get("closingWithoutCapture") or []:
        lines.append(
            f"  CUSTODY GAP: {row['dataPointId']} closes "
            f"{row['expectedReleaseWindow']['end']} with no HTTP 200 capture of "
            f"{row['sourceUrl']}"
        )
    return "\n".join(lines) + "\n"


def render_markdown(report: Mapping[str, Any]) -> str:
    out = [
        f"## Registered-window witness, {report['todayUtc']} UTC ({report['mode']})",
        "",
        f"No-plan rule: `{report.get('noPlanRule', 'n/a')}`. "
        "The Archive's index is the record; this table is a copy.",
        "",
    ]
    for note in report.get("notes") or []:
        out.append(f"- **Note:** {note}")
    for problem in report.get("registrationProblems") or []:
        out.append(f"- **Registration problem:** {problem}")
    for dropped in report.get("droppedByCap") or []:
        out.append(f"- **Dropped by the daily cap:** {dropped['sourceUrl']}")
    if report.get("openWindows"):
        out += [
            "",
            "| Source URL | Targets | Window(s) | Result |",
            "|---|---:|---|---|",
        ]
    for entry in report.get("openWindows") or []:
        rows = entry.get("registrations") or []
        windows = sorted(
            {
                f"{r['expectedReleaseWindow']['start']}..{r['expectedReleaseWindow']['end']}"
                for r in rows
            }
        )
        verdict = entry.get("verdict") or {}
        result = (
            f"{verdict.get('code')}: {verdict.get('text')}"
            if verdict
            else f"would request `{entry.get('wouldRequest', '')}`"
        )
        if verdict.get("link"):
            result += f" ([capture]({verdict['link']}))"
        out.append(
            f"| {entry['sourceUrl']} | {len(rows)} | {', '.join(windows)} | "
            f"{result.replace('|', '/')} |"
        )
    closed = report.get("closedWindows") or []
    if closed:
        out += [
            "",
            "### Windows already closed (index read only)",
            "",
            "| Target | Window | HTTP 200 captures inside |",
            "|---|---|---:|",
        ]
    for entry in closed:
        index = entry.get("index")
        for row in entry.get("registrations") or []:
            window = row["expectedReleaseWindow"]
            count = (
                "index unread"
                if index is not None and not index.get("ok")
                else row.get("http200CapturesInWindow", "not read (dry run)")
            )
            span = f"{window['start']}..{window['end']}"
            out.append(f"| {row['dataPointId']} | {span} | {count} |")
    limits = sorted(
        {n for e in report.get("openWindows") or [] for n in e.get("knownLimits") or []}
    )
    if limits:
        out += ["", "### Known limits that apply today", ""] + [
            f"- {n}" for n in limits
        ]
    return "\n".join(out) + "\n"


def _refuse_records_path(path: pathlib.Path | None, repo_root: pathlib.Path) -> None:
    if path is None:
        return
    resolved = path.resolve()
    records = (repo_root / "records").resolve()
    if resolved == records or records in resolved.parents:
        raise SystemExit(
            f"refusing to write {path}: this witness writes nothing under records/"
        )


def load_pending(
    log_dir: pathlib.Path | None,
    loader: Callable[[], Mapping[str, Any]] | None = None,
) -> tuple[set[str] | None, str | None]:
    """(pending refs, failure). Failure means the pending state is unknown."""

    try:
        if loader is not None:
            log = loader()
        else:
            import thesis_log_client  # noqa: PLC0415

            log = (
                thesis_log_client.load_thesis_log_from_directory(log_dir)
                if log_dir
                else thesis_log_client.load_thesis_log()
            )
        if not isinstance(log.get("resolutionLinks"), list):
            return None, "the Thesis log has no resolutionLinks list"
        return pending_refs(log), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:200]}"


def _utc_time(value: str) -> dt.time:
    try:
        return dt.datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an HH:MM UTC time: {value!r}") from exc


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Fetcher | None = None,
    sleep: Callable[[float], None] | None = None,
    log_loader: Callable[[], Mapping[str, Any]] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be captured today; send nothing to the Archive",
    )
    mode.add_argument(
        "--audit",
        action="store_true",
        help="read the index for every started window; request no capture",
    )
    parser.add_argument(
        "--date",
        type=dt.date.fromisoformat,
        help="plan as of this UTC date (dry run only)",
    )
    parser.add_argument(
        "--targets-dir", type=pathlib.Path, default=ROOT / "records" / "targets"
    )
    parser.add_argument(
        "--log-dir",
        type=pathlib.Path,
        help="a downloaded Thesis log (thesis_log_client.py --output-dir) "
        "instead of the live one",
    )
    parser.add_argument(
        "--report", type=pathlib.Path, help="write the JSON report here"
    )
    parser.add_argument(
        "--summary",
        type=pathlib.Path,
        default=pathlib.Path(os.environ["GITHUB_STEP_SUMMARY"])
        if os.environ.get("GITHUB_STEP_SUMMARY")
        else None,
        help="append the Markdown summary here (default: $GITHUB_STEP_SUMMARY)",
    )
    parser.add_argument(
        "--skip-captured-since",
        type=_utc_time,
        metavar="HH:MM",
        help="second pass: leave alone a URL the index shows captured today "
        "at or after this UTC time",
    )
    parser.add_argument("--max-urls", type=int, default=DEFAULT_MAX_URLS)
    parser.add_argument(
        "--max-closed-reads", type=int, default=DEFAULT_MAX_CLOSED_READS
    )
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--save-timeout", type=float, default=DEFAULT_SAVE_TIMEOUT)
    parser.add_argument("--save-pause", type=float, default=DEFAULT_SAVE_PAUSE)
    parser.add_argument("--index-pause", type=float, default=DEFAULT_INDEX_PAUSE)
    parser.add_argument(
        "--deadline-minutes", type=float, default=DEFAULT_DEADLINE_MINUTES
    )
    args = parser.parse_args(argv)

    if args.date and not args.dry_run:
        parser.error("--date plans another day; it is only valid with --dry-run")
    if args.skip_captured_since and (args.dry_run or args.audit):
        parser.error("--skip-captured-since only applies to a capture run")
    _refuse_records_path(args.report, ROOT)
    _refuse_records_path(args.summary, ROOT)

    today = args.date or dt.datetime.now(dt.timezone.utc).date()
    notes: list[str] = []
    resolver, resolver_failure = _load_resolver()
    if resolver_failure:
        notes.append(
            f"resolve_pending did not import ({resolver_failure}); using the "
            "adapter-name rule"
        )
    no_plan, rule = plan_predicate(resolver)
    content_hash, hash_failure = _load_content_hash()
    if hash_failure:
        notes.append(
            f"register_targets did not import ({hash_failure}); registration "
            "content hashes were NOT checked this run"
        )
    targets, problems = scan_registrations(args.targets_dir, no_plan, content_hash)
    pending, pending_failure = load_pending(args.log_dir, log_loader)
    if pending_failure:
        notes.append(
            f"the Thesis log could not be read ({pending_failure}); pending "
            "state unknown, so every no-plan target in an open window is kept"
        )
    options = Options(
        mode="dry-run" if args.dry_run else "audit" if args.audit else "capture",
        max_urls=args.max_urls,
        max_closed_reads=args.max_closed_reads,
        lookback_days=args.lookback_days,
        save_timeout=args.save_timeout,
        save_pause=args.save_pause,
        index_pause=args.index_pause,
        skip_since=args.skip_captured_since,
    )
    transport = Transport(
        fetch=fetch or http_fetch,
        sleep=sleep or time.sleep,
        attempts=args.attempts,
        deadline_seconds=args.deadline_minutes * 60,
    )
    report = run(
        targets=targets,
        pending=pending,
        today=today,
        transport=transport,
        options=options,
        save_template=save_url_template(resolver),
        preamble={
            "noPlanRule": rule,
            "userAgent": WITNESS_USER_AGENT,
            "notes": notes,
            "registrationProblems": [
                p.text
                for p in problems
                if p.matters(pending, today, None if args.audit else args.lookback_days)
            ],
        },
    )
    sys.stdout.write(render_text(report))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.summary:
        with args.summary.open("a") as handle:
            handle.write(render_markdown(report))
    # Exit 0 whatever the per-URL outcomes: they are findings, and the
    # workflow's gap step decides what deserves an alert. Exit 1 only when
    # the run could not look at all.
    if not targets and any(p.data_point_id is None for p in problems):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
