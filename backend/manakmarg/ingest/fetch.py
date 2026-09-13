"""Polite, cache-first HTTP fetcher for official sources.

Rules (spec §7):
* identify with a clear User-Agent and honour robots.txt;
* space requests to the same host by at least ``min_delay_s``;
* retry only transient failures (connection errors, transfers broken mid-body, 429, 5xx) with backoff;
* never retry or work around HTTP 401/403 or CAPTCHA-gated pages — raise ``AccessBlocked``;
* cache every successful response by URL + query parameters so ingestion can be replayed offline.
"""

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from manakmarg.core import clock

TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3

_CAPTCHA_MARKERS = (
    re.compile(rb"""name=["']?captcha""", re.IGNORECASE),
    re.compile(rb"g-recaptcha", re.IGNORECASE),
    re.compile(rb"h-captcha", re.IGNORECASE),
    re.compile(rb"CheckForTheCaptcha", re.IGNORECASE),
)

_EXTENSIONS = (
    ("pdf", ".pdf"),
    ("html", ".html"),
    ("json", ".json"),
    ("xml", ".xml"),
    ("spreadsheetml", ".xlsx"),
    ("text/plain", ".txt"),
)


class AccessBlocked(Exception):
    """The source refused access (HTTP 401/403, robots.txt or a CAPTCHA gate). Do not work around it."""

    def __init__(self, url: str, reason: str, status: int | None = None):
        super().__init__(f"access blocked ({reason}): {url}")
        self.url = url
        self.reason = reason
        self.status = status


class OfflineCacheMiss(Exception):
    """Offline mode was requested but the URL has no cached snapshot."""


class FetchError(Exception):
    """The request failed for a reason other than an access block."""

    def __init__(self, url: str, message: str, status: int | None = None):
        super().__init__(f"{message}: {url}")
        self.url = url
        self.status = status


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    content: bytes
    content_type: str
    sha256: str
    local_path: Path
    retrieved_at: datetime
    from_cache: bool


@dataclass(frozen=True)
class _CacheEntry:
    directory: Path
    key: str

    @property
    def meta_path(self) -> Path:
        return self.directory / f"{self.key}.json"


def request_url(url: str, params: dict | None) -> str:
    """The URL including sorted query parameters — the cache identity of a request."""
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(sorted(params.items()))}"


def looks_like_captcha_gate(content: bytes) -> bool:
    return any(marker.search(content) for marker in _CAPTCHA_MARKERS)


def _extension(content_type: str, url: str) -> str:
    lowered = content_type.lower()
    for needle, extension in _EXTENSIONS:
        if needle in lowered:
            return extension
    suffix = Path(urlsplit(url).path).suffix.lower()
    return suffix if suffix in {".pdf", ".html", ".htm", ".xlsx", ".json", ".txt"} else ".bin"


class Fetcher:
    def __init__(
        self,
        cache_root: Path,
        *,
        min_delay_s: float,
        user_agent: str,
        offline: bool = False,
        session=None,
        respect_robots: bool = True,
        timeout_s: float = 90.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.cache_root = Path(cache_root)
        self.min_delay_s = min_delay_s
        self.user_agent = user_agent
        self.offline = offline
        self.session = session if session is not None else requests.Session()
        self.respect_robots = respect_robots
        self.timeout_s = timeout_s
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    # ------------------------------------------------------------------ public API

    def get(
        self,
        url: str,
        *,
        source_id: str,
        params: dict | None = None,
        refresh: bool = False,
        detect_captcha: bool = True,
    ) -> FetchResult:
        identity = request_url(url, params)
        entry = self._cache_entry(source_id, identity)

        if not refresh and entry.meta_path.exists():
            return self._load_cached(entry)
        if self.offline:
            raise OfflineCacheMiss(identity)
        if self.respect_robots and not self._robots_allow(identity):
            raise AccessBlocked(identity, "robots")

        response = self._request_with_retries(url, params)
        status = response.status_code
        if status in (401, 403):
            raise AccessBlocked(identity, f"http_{status}", status)
        if status >= 400:
            raise FetchError(identity, f"HTTP {status}", status)
        if detect_captcha and looks_like_captcha_gate(response.content):
            raise AccessBlocked(identity, "captcha", status)
        return self._store(entry, identity, response)

    # ------------------------------------------------------------------ internals

    def _cache_entry(self, source_id: str, identity: str) -> _CacheEntry:
        key = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:20]
        return _CacheEntry(self.cache_root / source_id, key)

    def _load_cached(self, entry: _CacheEntry) -> FetchResult:
        meta = json.loads(entry.meta_path.read_text(encoding="utf-8"))
        body_path = entry.directory / meta["body"]
        return FetchResult(
            url=meta["url"],
            final_url=meta["final_url"],
            status=meta["status"],
            content=body_path.read_bytes(),
            content_type=meta["content_type"],
            sha256=meta["sha256"],
            local_path=body_path,
            retrieved_at=datetime.fromisoformat(meta["retrieved_at"]),
            from_cache=True,
        )

    def _store(self, entry: _CacheEntry, identity: str, response) -> FetchResult:
        content = response.content
        content_type = response.headers.get("content-type", "") or ""
        digest = hashlib.sha256(content).hexdigest()
        retrieved_at = clock.now_utc()

        entry.directory.mkdir(parents=True, exist_ok=True)
        body_path = entry.directory / f"{entry.key}{_extension(content_type, identity)}"
        body_path.write_bytes(content)
        meta = {
            "url": identity,
            "final_url": str(response.url),
            "status": response.status_code,
            "content_type": content_type,
            "sha256": digest,
            "bytes": len(content),
            "retrieved_at": retrieved_at.isoformat(),
            "body": body_path.name,
        }
        entry.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return FetchResult(
            url=identity,
            final_url=str(response.url),
            status=response.status_code,
            content=content,
            content_type=content_type,
            sha256=digest,
            local_path=body_path,
            retrieved_at=retrieved_at,
            from_cache=False,
        )

    def _wait_for_host(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = self._monotonic() - last
            if elapsed < self.min_delay_s:
                self._sleep(self.min_delay_s - elapsed)
        self._last_request_at[host] = self._monotonic()

    def _request_with_retries(self, url: str, params: dict | None):
        headers = {"User-Agent": self.user_agent}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._wait_for_host(url)
            try:
                response = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout_s, allow_redirects=True
                )
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as exc:
                if attempt == MAX_ATTEMPTS:
                    raise FetchError(request_url(url, params), f"network error: {exc}") from exc
                self._sleep(self.min_delay_s * 2 ** (attempt - 1))
                continue
            if response.status_code in TRANSIENT_STATUSES and attempt < MAX_ATTEMPTS:
                self._sleep(self.min_delay_s * 2 ** (attempt - 1))
                continue
            return response
        raise AssertionError("unreachable")

    def _robots_allow(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        parser = self._robots[origin]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    def _load_robots(self, origin: str) -> RobotFileParser | None:
        robots_url = f"{origin}/robots.txt"
        self._wait_for_host(robots_url)
        try:
            response = self.session.get(
                robots_url, headers={"User-Agent": self.user_agent}, timeout=self.timeout_s
            )
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        parser = RobotFileParser()
        parser.parse(response.content.decode("utf-8", errors="replace").splitlines())
        return parser
