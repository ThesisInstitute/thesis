"""Content-addressed HTTP cache.

Every response the comparison uses is stored under ``raw/<sha256>`` with its
URL, status and fetch time in ``index.jsonl``. A rerun with ``offline=True``
reads only the store, so results reproduce byte for byte.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

# bls.gov refuses non-browser clients (HTTP 403); the resolver and witness jobs
# use the same honest "compatible" form that names who is fetching.
BROWSER_COMPATIBLE_UA = (
    "Mozilla/5.0 (compatible; thesis-paper-comparison/0.1; "
    "+https://app.thesisinstitute.org)"
)
API_UA = "thesis-paper-comparison/0.1 (+https://github.com/ThesisInstitute/thesis)"

RETRY_STATUSES = {429, 500, 502, 503, 504}


class OfflineMissError(RuntimeError):
    """An offline run asked for a URL the store does not hold."""


class FetchError(RuntimeError):
    pass


def build_url(base: str, path: str, params: dict | None = None) -> str:
    if not params:
        return base + path
    query = urllib.parse.urlencode(sorted((k, v) for k, v in params.items()))
    return f"{base}{path}?{query}"


class FetchCache:
    def __init__(
        self,
        root: pathlib.Path | str,
        *,
        offline: bool = False,
        min_interval: float = 0.08,
        max_attempts: int = 6,
    ) -> None:
        self.root = pathlib.Path(root)
        self.raw = self.root / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.jsonl"
        self.offline = offline
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self._last_request = 0.0
        self.index: dict[str, dict] = {}
        if self.index_path.exists():
            for line in self.index_path.read_text().splitlines():
                if line.strip():
                    record = json.loads(line)
                    self.index[record["url"]] = record

    def _record(self, record: dict) -> None:
        self.index[record["url"]] = record
        with self.index_path.open("a") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def get(
        self,
        url: str,
        *,
        user_agent: str = API_UA,
        accept: str = "application/json",
        allow_404: bool = False,
    ) -> bytes | None:
        """Return the body for ``url`` (None for a recorded 404)."""
        record = self.index.get(url)
        if record is not None:
            if record["status"] == 404:
                if allow_404:
                    return None
                raise FetchError(f"recorded 404 for {url}")
            body = (self.raw / record["sha256"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != record["sha256"]:
                raise FetchError(f"stored body for {url} fails its hash")
            return body
        if self.offline:
            raise OfflineMissError(url)
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            self._throttle()
            request = urllib.request.Request(
                url, headers={"User-Agent": user_agent, "Accept": accept}
            )
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    body = response.read()
                    status = response.status
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    self._record(_record_for(url, 404, None))
                    if allow_404:
                        return None
                    raise FetchError(f"404 for {url}") from error
                if error.code in RETRY_STATUSES:
                    last_error = error
                    time.sleep(min(30, 1.5 * 2**attempt))
                    continue
                raise FetchError(f"HTTP {error.code} for {url}") from error
            except (urllib.error.URLError, TimeoutError) as error:
                last_error = error
                time.sleep(min(30, 1.5 * 2**attempt))
                continue
            digest = hashlib.sha256(body).hexdigest()
            path = self.raw / digest
            if not path.exists():
                path.write_bytes(body)
            self._record(_record_for(url, status, body, digest))
            return body
        raise FetchError(f"gave up on {url}: {last_error}")

    def get_json(self, url: str, **kwargs) -> dict | None:
        body = self.get(url, **kwargs)
        return None if body is None else json.loads(body)

    def sha256_of(self, url: str) -> str | None:
        record = self.index.get(url)
        return None if record is None else record.get("sha256")


def _record_for(
    url: str, status: int, body: bytes | None, digest: str | None = None
) -> dict:
    return {
        "url": url,
        "status": status,
        "sha256": digest,
        "bytes": None if body is None else len(body),
        "fetchedAt": (
            dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
    }
