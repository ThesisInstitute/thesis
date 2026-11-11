#!/usr/bin/env python3
"""Fetch one official page through a real browser engine (headless Chromium).

Some official publishers sit behind Akamai Bot Manager, which refuses every
non-browser TLS client — curl, urllib, and the Wayback Machine's Save Page
Now fetcher — with HTTP 403 while serving browsers normally. ssa.gov is the
motivating case (verified 2026-08-23: urllib 403 on every statcomps/appeals
URL from both a laptop and a GitHub Actions runner; headless Chromium 200 on
the same URLs from the same runner; robots.txt disallows none of the paths).

This module gives ``scripts/resolve_pending.py`` a declared, auditable
browser transport instead of a TLS-impersonating client:

* one navigation per call, in a fresh browser context;
* no redirects accepted — the final URL must equal the requested URL;
* the raw response body and response headers are returned as served;
* the engine, Playwright version, and User-Agent are recorded so every
  capture envelope names the transport that produced its bytes.

Playwright is an optional runtime dependency (``pip install playwright``
plus ``python -m playwright install --with-deps chromium``). A missing
engine raises :class:`BrowserFetchUnavailableError`, which the resolver treats as
a fatal environment failure — never as a silent deferral.

CLI (used by the resolver workflow's smoke step and for fixture capture)::

    python3 scripts/official_browser_fetch.py URL --out body.html
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from dataclasses import dataclass
from urllib.parse import urlparse

USER_AGENT_SUFFIX = "thesis-resolver/1.0 (+https://app.thesisinstitute.org)"
DEFAULT_TIMEOUT_SECONDS = 90.0
MAX_BODY_BYTES = 25_000_000


class BrowserFetchUnavailableError(RuntimeError):
    """The browser engine is not installed in this environment."""


class BrowserFetchError(RuntimeError):
    """The navigation did not yield one clean 200 response for the exact URL."""


@dataclass(frozen=True)
class BrowserCapture:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    retrieved_at: str
    user_agent: str
    engine: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def transport_record(self) -> dict[str, object]:
        """The transport block every capture envelope embeds."""
        return {
            "kind": "headless-browser",
            "engine": self.engine,
            "userAgent": self.user_agent,
            "redirectsAccepted": False,
        }

    def response_record(self) -> dict[str, object]:
        return {
            "url": self.url,
            "finalUrl": self.final_url,
            "status": self.status,
            "headers": dict(sorted(self.headers.items())),
            "retrievedAt": self.retrieved_at,
            "bytes": len(self.body),
            "sha256": self.sha256,
        }


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_https(url: str, allowed_hosts: tuple[str, ...] | None) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise BrowserFetchError(f"only https URLs are fetched: {url!r}")
    if allowed_hosts is not None and parsed.hostname not in allowed_hosts:
        raise BrowserFetchError(
            f"host {parsed.hostname!r} is not in the allowed set "
            f"{sorted(allowed_hosts)!r}"
        )


def browser_fetch(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    allowed_hosts: tuple[str, ...] | None = None,
) -> BrowserCapture:
    """Navigate headless Chromium to ``url`` and return the raw main response."""

    _require_https(url, allowed_hosts)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised in CI runtime only
        raise BrowserFetchUnavailableError(
            "playwright is unavailable; install it with `pip install playwright` "
            "and `python -m playwright install --with-deps chromium`"
        ) from exc

    try:
        import importlib.metadata as metadata

        playwright_version = metadata.version("playwright")
    except Exception:  # noqa: BLE001 - version is informational only
        playwright_version = "unknown"

    retrieved_at = _utc_now()
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except PlaywrightError as exc:
                raise BrowserFetchUnavailableError(
                    f"chromium could not launch; run `python -m playwright install "
                    f"--with-deps chromium`: {exc}"
                ) from exc
            try:
                probe_context = browser.new_context()
                default_user_agent = probe_context.new_page().evaluate(
                    "() => navigator.userAgent"
                )
                probe_context.close()
                user_agent = f"{default_user_agent} {USER_AGENT_SUFFIX}"
                context = browser.new_context(
                    user_agent=user_agent,
                    locale="en-US",
                    accept_downloads=False,
                )
                page = context.new_page()
                page.set_default_timeout(timeout_seconds * 1000)
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_seconds * 1000,
                )
                if response is None:
                    raise BrowserFetchError(f"navigation produced no response: {url}")
                if response.request.redirected_from is not None:
                    raise BrowserFetchError(
                        f"redirect refused: {url} -> {response.url}"
                    )
                if response.url != url:
                    raise BrowserFetchError(
                        f"final URL {response.url!r} differs from requested {url!r}"
                    )
                body = response.body()
                if len(body) > MAX_BODY_BYTES:
                    raise BrowserFetchError(
                        f"response exceeds {MAX_BODY_BYTES} bytes: {url}"
                    )
                headers = {
                    str(name).lower(): str(value)
                    for name, value in response.headers.items()
                }
                engine = f"chromium {browser.version} (playwright {playwright_version})"
                status = response.status
                context.close()
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise BrowserFetchError(f"browser navigation failed for {url}: {exc}") from exc

    if status != 200:
        raise BrowserFetchError(f"HTTP {status} for {url}")
    return BrowserCapture(
        url=url,
        final_url=url,
        status=status,
        headers=headers,
        body=body,
        retrieved_at=retrieved_at,
        user_agent=user_agent,
        engine=engine,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--out", help="write the raw response body to this path")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="seconds"
    )
    args = parser.parse_args(argv)
    try:
        capture = browser_fetch(args.url, timeout_seconds=args.timeout)
    except (BrowserFetchUnavailableError, BrowserFetchError) as exc:
        print(json.dumps({"url": args.url, "error": str(exc)}))
        return 1
    if args.out:
        with open(args.out, "wb") as stream:
            stream.write(capture.body)
    summary = {
        **capture.response_record(),
        "transport": capture.transport_record(),
        "out": args.out,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
