import hashlib

import pytest
import requests

from manakmarg.ingest.fetch import AccessBlocked, FetchError, Fetcher, OfflineCacheMiss

UA = "ManakMarg-SIH2026-Prototype/0.1 (test)"


class FakeResponse:
    def __init__(self, url, status=200, content=b"", content_type="text/html; charset=utf-8"):
        self.url = url
        self.status_code = status
        self.content = content
        self.headers = {"content-type": content_type}


class FakeSession:
    """Serves canned responses per URL; the last response for a URL repeats."""

    def __init__(self, routes):
        self.routes = {url: list(responses) for url, responses in routes.items()}
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=True):
        self.calls.append({"url": url, "params": params, "headers": headers})
        responses = self.routes.get(url)
        if not responses:
            return FakeResponse(url, 404, b"not found")
        status, content = responses.pop(0) if len(responses) > 1 else responses[0]
        return FakeResponse(url, status, content)


class RaisingSession(FakeSession):
    """Raises the queued exceptions on the first calls, then serves routes."""

    def __init__(self, routes, failures):
        super().__init__(routes)
        self.failures = list(failures)

    def get(self, url, params=None, headers=None, timeout=None, allow_redirects=True):
        if self.failures:
            self.calls.append({"url": url, "params": params, "headers": headers})
            raise self.failures.pop(0)
        return super().get(url, params=params, headers=headers, timeout=timeout, allow_redirects=allow_redirects)


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_fetcher(tmp_path, session, *, offline=False, respect_robots=False, min_delay_s=2.5, fake_time=None):
    fake_time = fake_time or FakeTime()
    return Fetcher(
        tmp_path / "cache",
        min_delay_s=min_delay_s,
        user_agent=UA,
        offline=offline,
        session=session,
        respect_robots=respect_robots,
        sleep=fake_time.sleep,
        monotonic=fake_time.monotonic,
    )


def test_fetch_downloads_then_serves_from_cache(tmp_path):
    url = "https://www.bis.gov.in/page/"
    session = FakeSession({url: [(200, b"<html>ok</html>")]})
    fetcher = make_fetcher(tmp_path, session)

    first = fetcher.get(url, source_id="bis_test")
    second = fetcher.get(url, source_id="bis_test")

    assert first.status == 200
    assert first.from_cache is False
    assert first.sha256 == hashlib.sha256(b"<html>ok</html>").hexdigest()
    assert first.local_path.read_bytes() == b"<html>ok</html>"
    assert second.from_cache is True
    assert second.content == first.content
    assert len(session.calls) == 1


def test_refresh_bypasses_cache(tmp_path):
    url = "https://www.bis.gov.in/page/"
    fetcher = make_fetcher(tmp_path, FakeSession({url: [(200, b"v1"), (200, b"v2")]}))
    fetcher.get(url, source_id="s")
    assert fetcher.get(url, source_id="s", refresh=True).content == b"v2"


def test_query_parameters_are_part_of_cache_identity(tmp_path):
    url = "https://lims.bis.gov.in/home/search_is_number/"
    session = FakeSession({url: [(200, b"a"), (200, b"b")]})
    fetcher = make_fetcher(tmp_path, session)
    a = fetcher.get(url, source_id="lims", params={"is_number__doc_no": "2062"})
    b = fetcher.get(url, source_id="lims", params={"is_number__doc_no": "269"})
    assert a.local_path != b.local_path
    assert len(session.calls) == 2


def test_offline_mode_never_touches_network(tmp_path):
    url = "https://www.bis.gov.in/page/"
    make_fetcher(tmp_path, FakeSession({url: [(200, b"cached")]})).get(url, source_id="s")

    session = FakeSession({})
    offline = make_fetcher(tmp_path, session, offline=True)
    assert offline.get(url, source_id="s").content == b"cached"
    with pytest.raises(OfflineCacheMiss):
        offline.get("https://www.bis.gov.in/other/", source_id="s")
    assert session.calls == []


def test_forbidden_is_access_blocked_and_not_retried(tmp_path):
    url = "https://www.bis.gov.in/PDF/cart/PM_IS_2062.pdf"
    session = FakeSession({url: [(403, b"Forbidden")]})
    fetcher = make_fetcher(tmp_path, session)
    with pytest.raises(AccessBlocked) as info:
        fetcher.get(url, source_id="s")
    assert info.value.status == 403
    assert info.value.reason == "http_403"
    assert len(session.calls) == 1


def test_captcha_page_is_access_blocked(tmp_path):
    url = "https://huid.manakonline.in/MANAK/ApplicationHMLicenceRelatedrpt1?isno=1417"
    page = b'<form><input type="text" name="captcha" id="captcha0071"></form>'
    fetcher = make_fetcher(tmp_path, FakeSession({url: [(200, page)]}))
    with pytest.raises(AccessBlocked) as info:
        fetcher.get(url, source_id="s")
    assert info.value.reason == "captcha"


def test_server_errors_are_retried_with_backoff(tmp_path):
    url = "https://www.bis.gov.in/page/"
    session = FakeSession({url: [(503, b"busy"), (200, b"ok")]})
    fake_time = FakeTime()
    fetcher = make_fetcher(tmp_path, session, fake_time=fake_time)
    assert fetcher.get(url, source_id="s").content == b"ok"
    assert len(session.calls) == 2
    assert max(fake_time.sleeps) >= 2.5


def test_broken_transfers_are_retried(tmp_path):
    url = "https://www.bis.gov.in/scheme-i/"
    session = RaisingSession(
        {url: [(200, b"complete")]},
        [requests.exceptions.ChunkedEncodingError("Connection broken: IncompleteRead(243689 bytes read)")],
    )
    assert make_fetcher(tmp_path, session).get(url, source_id="s").content == b"complete"
    assert len(session.calls) == 2


def test_repeated_network_failures_raise_fetch_error(tmp_path):
    url = "https://www.bis.gov.in/scheme-i/"
    session = RaisingSession({url: [(200, b"never")]}, [requests.exceptions.ChunkedEncodingError("broken")] * 5)
    with pytest.raises(FetchError):
        make_fetcher(tmp_path, session).get(url, source_id="s")
    assert len(session.calls) == 3


def test_requests_to_the_same_host_are_spaced(tmp_path):
    session = FakeSession(
        {
            "https://www.bis.gov.in/a/": [(200, b"a")],
            "https://www.bis.gov.in/b/": [(200, b"b")],
        }
    )
    fake_time = FakeTime()
    fetcher = make_fetcher(tmp_path, session, fake_time=fake_time, min_delay_s=2.5)
    fetcher.get("https://www.bis.gov.in/a/", source_id="s")
    fetcher.get("https://www.bis.gov.in/b/", source_id="s")
    assert fake_time.sleeps == [pytest.approx(2.5)]


def test_user_agent_header_is_sent(tmp_path):
    url = "https://www.bis.gov.in/page/"
    session = FakeSession({url: [(200, b"ok")]})
    make_fetcher(tmp_path, session).get(url, source_id="s")
    assert session.calls[0]["headers"]["User-Agent"] == UA


def test_robots_disallow_blocks_fetch(tmp_path):
    session = FakeSession(
        {
            "https://example.gov.in/robots.txt": [(200, b"User-agent: *\nDisallow: /private/\n")],
            "https://example.gov.in/private/x": [(200, b"secret")],
        }
    )
    fetcher = make_fetcher(tmp_path, session, respect_robots=True)
    with pytest.raises(AccessBlocked) as info:
        fetcher.get("https://example.gov.in/private/x", source_id="s")
    assert info.value.reason == "robots"
    assert all(call["url"] != "https://example.gov.in/private/x" for call in session.calls)
