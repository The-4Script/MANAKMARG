"""BIS Standards portal downloader: the only module that knows how standards.bis.gov.in serves its Excel exports.

Everything below was read from the portal's own public JavaScript (``main.8c9b31dc7b0425e8.js`` and the lazy chunk
``361.1c21d6f291db9ea7.js``, September 2026). No endpoint is guessed:

* **Published Standards List page, "Export" button** (``PublishedStandardsListComponent.downloadExcel``): POST
  ``review-service/downloadPublishedStandardsListExcel`` with the page's filters; the JSON reply carries ``filePath``
  (or ``msg`` when no file was produced). A relative ``filePath`` is served from the portal's object storage
  (``downloadExcelFileFromUrl``). The overall list is that page opened with ``selectedType=7&totalRow=1``, whose
  heading is "Total".
* **Ministry-wise page**: ministries come from ``project-service/getWebsiteMinistries`` and their counts from
  ``review-service/getWebsiteMinistriesWisePSCount``; ministries with no standards are hidden. Each ministry's count
  links to the list page with ``selectedType=3`` and the ministry's encrypted id; that page's Export sends
  ``ministryIds=[id]``, ``encDepartmentId=<encrypted id>`` and the ministry name as the heading.
* The Group-wise and Ministry-wise pages' own aggregate "Download" buttons are shown only to signed-in users whose
  role the server approves (``checkDownloadPermission`` → ``verifyExcelDownloadPermission``). **They are not used.**

Access rules: anonymous requests only, carrying exactly what the page sends for a visitor who is not signed in (its
HTTP interceptor adds empty session fields); a clear User-Agent; robots.txt honoured; at least ``min_delay_s`` between
requests to a host; retries only for transient failures. HTTP 401/403, robots disallows and CAPTCHA pages raise
``AccessBlocked`` and are never retried or worked around. A reply in any other shape raises ``PortalChanged`` so the
refresh stops safely instead of loading data it does not understand. When the portal changes, only this module needs
updating.
"""

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from manakmarg.core import clock
from manakmarg.ingest.fetch import TRANSIENT_STATUSES, AccessBlocked, FetchError, looks_like_captcha_gate

PORTAL = "https://standards.bis.gov.in"
REVIEW_SERVICE = "https://standardsadmin.bis.gov.in/review-service"
PROJECT_SERVICE = "https://standardsadmin.bis.gov.in/project-service"
OBJECT_STORAGE = "https://bmqsdqljvwgm.compat.objectstorage.ap-mumbai-1.oraclecloud.com"

LIST_PAGE = f"{PORTAL}/website/published-standards/published-standards-list"
OVERALL_LIST_PAGE = f"{LIST_PAGE}?selectedType=7&committeeEncId=&totalRow=1"
MINISTRY_PAGE = f"{PORTAL}/website/published-standards/published-standard-ministrywise?activeTab=ministry"
GROUP_PAGE = f"{PORTAL}/website/published-standards/published-standard-groupwise?activeTab=group"

LIST_EXPORT_URL = f"{REVIEW_SERVICE}/downloadPublishedStandardsListExcel"
MINISTRIES_URL = f"{PROJECT_SERVICE}/getWebsiteMinistries"
MINISTRY_COUNTS_URL = f"{REVIEW_SERVICE}/getWebsiteMinistriesWisePSCount"

TYPE_TOTAL = 7
TYPE_MINISTRY = 3
# The portal's HTTP interceptor adds these fields to every request body; they are empty for a visitor who has not
# signed in, which is the only way this client calls the portal.
ANONYMOUS_SESSION_FIELDS = {"token": None, "refreshToken": None, "clientId": None, "clientSecret": None, "sub": None}
TRUSTED_FILE_HOSTS = (urlsplit(OBJECT_STORAGE).hostname, "bis.gov.in")
XLSX_SIGNATURE = b"PK\x03\x04"
MAX_ATTEMPTS = 3


class PortalChanged(Exception):
    """The portal answered in a shape this client does not recognise: its pages or requests have changed."""


@dataclass(frozen=True)
class Ministry:
    ministry_id: int | str
    name: str
    encrypted_id: str
    published_count: int | None = None

    @property
    def page_url(self) -> str:
        """This ministry's Published Standards List page, exactly as the Ministry-wise page links to it."""
        query = urlencode({"encryptedDepartmentId": self.encrypted_id, "committeeEncId": "", "selectedType": TYPE_MINISTRY})
        return f"{LIST_PAGE}?{query}"


@dataclass(frozen=True)
class DownloadedExport:
    kind: str  # total | ministry
    path: Path
    page_url: str
    request_url: str
    file_url: str
    sha256: str
    bytes: int
    retrieved_at: str
    ministry: Ministry | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["path"] = str(self.path)
        return data


def resolve_file_url(file_path: str) -> str:
    """Where the list page downloads an export from: an absolute URL as given, otherwise the portal's object storage.

    Only HTTPS locations on the portal's own object storage or a bis.gov.in host are accepted."""
    text = file_path.strip()
    url = text if text.startswith(("http://", "https://")) else f"{OBJECT_STORAGE}/{text.lstrip('/')}"
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not any(host == trusted or host.endswith(f".{trusted}") for trusted in TRUSTED_FILE_HOSTS):
        raise PortalChanged(f"the export file is served from an unexpected location: {host or url!r}")
    return url


def _body(reply):
    return reply["body"] if isinstance(reply, dict) and isinstance(reply.get("body"), dict) else reply


def _data_rows(reply, url: str) -> list[dict]:
    body = _body(reply)
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise PortalChanged(f"{url} did not return a data list")
    return rows


def _count(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PortalChanged(f"published-standard count is not a number: {value!r}") from exc


def _slug(value) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-") or hashlib.sha1(str(value).encode()).hexdigest()[:10]


class BisPortalClient:
    def __init__(
        self,
        *,
        user_agent: str,
        min_delay_s: float = 2.5,
        timeout_s: float = 90.0,
        export_timeout_s: float = 900.0,
        session=None,
        respect_robots: bool = True,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.user_agent = user_agent
        self.min_delay_s = min_delay_s
        self.timeout_s = timeout_s
        self.export_timeout_s = export_timeout_s
        self.session = session if session is not None else requests.Session()
        self.respect_robots = respect_robots
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    # ------------------------------------------------------------------ public API

    def list_ministries(self) -> list[Ministry]:
        """Every ministry on the Ministry-wise page with its published-standard count."""
        ministries = []
        for row in _data_rows(self._post_json(MINISTRIES_URL, {}, referer=MINISTRY_PAGE), MINISTRIES_URL):
            ministry_id = row.get("ministryId")
            name = " ".join(str(row.get("ministryName") or "").split())
            encrypted = row.get("encryptedMinistryId") or row.get("ministryEncId")
            if ministry_id in (None, "") or not name or not encrypted:
                raise PortalChanged(f"ministry entry without ministryId, ministryName or encryptedMinistryId (fields: {', '.join(sorted(row))})")
            ministries.append(Ministry(ministry_id, name, str(encrypted)))
        if not ministries:
            raise PortalChanged("the Ministry-wise page lists no ministries")
        counts = {}
        reply = self._post_json(MINISTRY_COUNTS_URL, {"ministryIds": [ministry.ministry_id for ministry in ministries]}, referer=MINISTRY_PAGE)
        for row in _data_rows(reply, MINISTRY_COUNTS_URL):
            if "ministryId" not in row or "publishedStandardCnt" not in row:
                raise PortalChanged(f"ministry count entry without ministryId or publishedStandardCnt (fields: {', '.join(sorted(row))})")
            counts[str(row["ministryId"])] = _count(row["publishedStandardCnt"])
        return [replace(ministry, published_count=counts.get(str(ministry.ministry_id), 0)) for ministry in ministries]

    def download_total(self, directory: Path) -> DownloadedExport:
        """The overall Published Standards List (heading "Total"), as its Export button produces it."""
        payload = {
            "typeSelected": TYPE_TOTAL,
            "ministryIds": [],
            "sdgIds": [],
            "allDepartments": True,
            "totalRow": 1,
            "techCommitteeId": 0,
            "exportByFilters": True,
            "selectedHeadingName": "Total",
            "selectedCommitteeName": "",
        }
        return self._export(payload, page_url=OVERALL_LIST_PAGE, target=Path(directory) / "overall-total.xlsx", kind="total")

    def download_ministry(self, ministry: Ministry, directory: Path) -> DownloadedExport:
        """One ministry's Published Standards List, as the Export button on that ministry's page produces it."""
        payload = {
            "typeSelected": TYPE_MINISTRY,
            "ministryIds": [ministry.ministry_id],
            "sdgIds": [],
            "encDepartmentId": ministry.encrypted_id,
            "techCommitteeId": 0,
            "exportByFilters": True,
            "selectedHeadingName": ministry.name,
            "selectedCommitteeName": "",
        }
        target = Path(directory) / f"ministry-{_slug(ministry.ministry_id)}.xlsx"
        return self._export(payload, page_url=ministry.page_url, target=target, kind="ministry", ministry=ministry)

    # ------------------------------------------------------------------ internals

    def _export(self, payload: dict, *, page_url: str, target: Path, kind: str, ministry: Ministry | None = None) -> DownloadedExport:
        body = _body(self._post_json(LIST_EXPORT_URL, payload, referer=page_url, timeout=self.export_timeout_s))
        if not isinstance(body, dict):
            raise PortalChanged("the export reply is not a JSON object")
        file_path = body.get("filePath")
        if not file_path:
            message = body.get("msg") or body.get("message")
            if message:
                raise FetchError(LIST_EXPORT_URL, f"export not generated ({message})")
            raise PortalChanged("the export reply has no filePath")
        file_url = resolve_file_url(str(file_path))
        response = self._request("GET", file_url, referer=page_url, timeout=self.export_timeout_s)
        content = response.content
        if not content.startswith(XLSX_SIGNATURE):
            if looks_like_captcha_gate(content):
                raise AccessBlocked(file_url, "captcha", response.status_code)
            raise PortalChanged(f"the export file is not an Excel workbook ({response.headers.get('content-type') or 'unknown type'})")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return DownloadedExport(
            kind=kind,
            path=target,
            page_url=page_url,
            request_url=LIST_EXPORT_URL,
            file_url=file_url,
            sha256=hashlib.sha256(content).hexdigest(),
            bytes=len(content),
            retrieved_at=clock.now_utc().isoformat(timespec="seconds"),
            ministry=ministry,
        )

    def _post_json(self, url: str, payload: dict, *, referer: str, timeout: float | None = None):
        response = self._request("POST", url, referer=referer, json_body={**payload, **ANONYMOUS_SESSION_FIELDS}, timeout=timeout)
        try:
            return response.json()
        except ValueError as exc:
            if looks_like_captcha_gate(response.content):
                raise AccessBlocked(url, "captcha", response.status_code) from exc
            raise PortalChanged(f"{url} did not return JSON") from exc

    def _request(self, method: str, url: str, *, referer: str, json_body: dict | None = None, timeout: float | None = None):
        if self.respect_robots and not self._robots_allow(url):
            raise AccessBlocked(url, "robots")
        headers = {"User-Agent": self.user_agent, "Accept": "application/json, */*", "Referer": referer}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._wait_for_host(url)
            try:
                if method == "POST":
                    response = self.session.post(url, json=json_body, headers=headers, timeout=timeout or self.timeout_s)
                else:
                    response = self.session.get(url, headers=headers, timeout=timeout or self.timeout_s)
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as exc:
                if attempt == MAX_ATTEMPTS:
                    raise FetchError(url, f"network error: {exc}") from exc
                self._sleep(self.min_delay_s * 2 ** (attempt - 1))
                continue
            status = response.status_code
            if status in (401, 403):
                raise AccessBlocked(url, f"http_{status}", status)
            if status in TRANSIENT_STATUSES and attempt < MAX_ATTEMPTS:
                self._sleep(self.min_delay_s * 2 ** (attempt - 1))
                continue
            if status >= 400:
                raise FetchError(url, f"HTTP {status}", status)
            return response
        raise AssertionError("unreachable")

    def _wait_for_host(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = self._monotonic() - last
            if elapsed < self.min_delay_s:
                self._sleep(self.min_delay_s - elapsed)
        self._last_request_at[host] = self._monotonic()

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
            response = self.session.get(robots_url, headers={"User-Agent": self.user_agent}, timeout=self.timeout_s)
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        parser = RobotFileParser()
        parser.parse(response.content.decode("utf-8", errors="replace").splitlines())
        return parser
