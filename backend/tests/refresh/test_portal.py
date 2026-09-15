"""BIS portal client: the exact requests the portal's own pages make, and safe failure on anything unexpected."""

import json

import pytest

from manakmarg.ingest.fetch import AccessBlocked, FetchError
from manakmarg.refresh import portal
from manakmarg.refresh.portal import BisPortalClient, Ministry, PortalChanged, resolve_file_url
from tests.refresh.exports import rows_for, write_export

SESSION_FIELDS = {"token": None, "refreshToken": None, "clientId": None, "clientSecret": None, "sub": None}


class FakeResponse:
    def __init__(self, status=200, body=b"", content_type="application/json"):
        self.status_code = status
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {"content-type": content_type}

    def json(self):
        return json.loads(self.content.decode("utf-8"))


class FakeSession:
    def __init__(self, posts=None, gets=None):
        self.post_routes = posts or {}
        self.get_routes = gets or {}
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        route = self.post_routes[url]
        return route.pop(0) if isinstance(route, list) else route

    def get(self, url, headers=None, timeout=None):
        self.gets.append({"url": url, "headers": headers})
        if url.endswith("/robots.txt"):
            return self.get_routes.get(url, FakeResponse(404, b"", "text/plain"))
        return self.get_routes[url]


@pytest.fixture
def workbook_bytes(tmp_path):
    return write_export(tmp_path / "export.xlsx", "Total", rows_for(["IS 269:2015"])).read_bytes()


def client(session):
    return BisPortalClient(user_agent="manakmarg-test", min_delay_s=0, session=session, sleep=lambda _seconds: None)


def test_overall_export_sends_the_list_page_request_and_downloads_the_file(tmp_path, workbook_bytes):
    file_url = f"{portal.OBJECT_STORAGE}/exports/published-standards.xlsx"
    session = FakeSession(
        posts={portal.LIST_EXPORT_URL: FakeResponse(body={"filePath": "exports/published-standards.xlsx"})},
        gets={file_url: FakeResponse(body=workbook_bytes, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    export = client(session).download_total(tmp_path / "downloads")

    request = session.posts[0]
    assert request["json"] == {
        "typeSelected": 7,
        "ministryIds": [],
        "sdgIds": [],
        "allDepartments": True,
        "totalRow": 1,
        "techCommitteeId": 0,
        "exportByFilters": True,
        "selectedHeadingName": "Total",
        "selectedCommitteeName": "",
        **SESSION_FIELDS,
    }
    assert request["headers"]["User-Agent"] == "manakmarg-test" and request["headers"]["Referer"] == portal.OVERALL_LIST_PAGE
    assert export.kind == "total" and export.file_url == file_url and export.path.read_bytes() == workbook_bytes
    assert export.bytes == len(workbook_bytes) and len(export.sha256) == 64


def test_ministries_come_with_their_counts_and_each_is_exported_from_its_own_list_page(tmp_path, workbook_bytes):
    ministries_reply = {"data": [{"ministryId": 11, "ministryName": " Ministry of  Coal ", "encryptedMinistryId": "enc11"}, {"ministryId": 12, "ministryName": "NITI Aayog", "encryptedMinistryId": "enc12"}]}
    counts_reply = {"data": [{"ministryId": 11, "publishedStandardCnt": "54"}]}
    file_url = "https://files.bis.gov.in/ministry-11.xlsx"
    session = FakeSession(
        posts={
            portal.MINISTRIES_URL: FakeResponse(body=ministries_reply),
            portal.MINISTRY_COUNTS_URL: FakeResponse(body=counts_reply),
            portal.LIST_EXPORT_URL: FakeResponse(body={"filePath": file_url}),
        },
        gets={file_url: FakeResponse(body=workbook_bytes)},
    )
    portal_client = client(session)
    ministries = portal_client.list_ministries()
    assert ministries == [Ministry(11, "Ministry of Coal", "enc11", 54), Ministry(12, "NITI Aayog", "enc12", 0)]
    assert session.posts[1]["json"] == {"ministryIds": [11, 12], **SESSION_FIELDS}

    export = portal_client.download_ministry(ministries[0], tmp_path)
    assert session.posts[2]["json"] == {
        "typeSelected": 3,
        "ministryIds": [11],
        "sdgIds": [],
        "encDepartmentId": "enc11",
        "techCommitteeId": 0,
        "exportByFilters": True,
        "selectedHeadingName": "Ministry of Coal",
        "selectedCommitteeName": "",
        **SESSION_FIELDS,
    }
    assert "encryptedDepartmentId=enc11" in export.page_url and "selectedType=3" in export.page_url
    assert export.ministry.name == "Ministry of Coal" and export.path.name == "ministry-11.xlsx"


def test_export_file_locations_are_restricted_to_the_portal():
    assert resolve_file_url("/a/b.xlsx") == f"{portal.OBJECT_STORAGE}/a/b.xlsx"
    assert resolve_file_url("https://standardsadmin.bis.gov.in/x.xlsx") == "https://standardsadmin.bis.gov.in/x.xlsx"
    for unsafe in ("https://evil.example.com/x.xlsx", "http://standards.bis.gov.in/x.xlsx", "https://notbis.gov.in.example.com/x.xlsx"):
        with pytest.raises(PortalChanged):
            resolve_file_url(unsafe)


def test_an_export_without_a_file_is_reported(tmp_path):
    refused = FakeSession(posts={portal.LIST_EXPORT_URL: FakeResponse(body={"msg": "Excel export failed. Please try again."})})
    with pytest.raises(FetchError, match="Excel export failed"):
        client(refused).download_total(tmp_path)
    changed = FakeSession(posts={portal.LIST_EXPORT_URL: FakeResponse(body={"status": "SUCCESS"})})
    with pytest.raises(PortalChanged, match="no filePath"):
        client(changed).download_total(tmp_path)


def test_access_refusals_are_never_retried_or_worked_around(tmp_path):
    forbidden = FakeSession(posts={portal.LIST_EXPORT_URL: FakeResponse(403, b"Forbidden", "text/html")})
    with pytest.raises(AccessBlocked):
        client(forbidden).download_total(tmp_path)
    assert len(forbidden.posts) == 1

    captcha = FakeSession(posts={portal.LIST_EXPORT_URL: FakeResponse(200, b"<form><div class='g-recaptcha'></div></form>", "text/html")})
    with pytest.raises(AccessBlocked) as blocked:
        client(captcha).download_total(tmp_path)
    assert blocked.value.reason == "captcha"

    robots = FakeSession(gets={"https://standardsadmin.bis.gov.in/robots.txt": FakeResponse(200, b"User-agent: *\nDisallow: /review-service/", "text/plain")})
    with pytest.raises(AccessBlocked) as disallowed:
        client(robots).download_total(tmp_path)
    assert disallowed.value.reason == "robots" and robots.posts == []


def test_transient_errors_are_retried(tmp_path, workbook_bytes):
    file_url = f"{portal.OBJECT_STORAGE}/x.xlsx"
    session = FakeSession(
        posts={portal.LIST_EXPORT_URL: [FakeResponse(503, b"busy", "text/plain"), FakeResponse(body={"filePath": "x.xlsx"})]},
        gets={file_url: FakeResponse(body=workbook_bytes)},
    )
    assert client(session).download_total(tmp_path).file_url == file_url
    assert len(session.posts) == 2


def test_unexpected_replies_mean_the_portal_changed(tmp_path):
    html_file = FakeSession(
        posts={portal.LIST_EXPORT_URL: FakeResponse(body={"filePath": "x.xlsx"})},
        gets={f"{portal.OBJECT_STORAGE}/x.xlsx": FakeResponse(200, b"<html>moved</html>", "text/html")},
    )
    with pytest.raises(PortalChanged, match="not an Excel workbook"):
        client(html_file).download_total(tmp_path)

    renamed = FakeSession(posts={portal.MINISTRIES_URL: FakeResponse(body={"data": [{"id": 1, "name": "Ministry of Coal"}]})})
    with pytest.raises(PortalChanged, match="ministryId"):
        client(renamed).list_ministries()

    empty = FakeSession(posts={portal.MINISTRIES_URL: FakeResponse(body={"data": []})})
    with pytest.raises(PortalChanged, match="no ministries"):
        client(empty).list_ministries()

    not_json = FakeSession(posts={portal.MINISTRIES_URL: FakeResponse(200, b"<html>maintenance</html>", "text/html")})
    with pytest.raises(PortalChanged, match="JSON"):
        client(not_json).list_ministries()
