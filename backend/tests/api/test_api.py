"""API contract tests over a fixture database (FastAPI TestClient; no network)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from manakmarg.api import deps
from manakmarg.api.app import create_app
from manakmarg.core.config import Settings
from tests.fixture_db import build_fixture_db


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    engine = build_fixture_db(root / "api.sqlite3")
    settings = Settings(db_path=root / "api.sqlite3", anthropic_api_key=None, llm_model=None, groq_api_key=None)
    app = create_app(settings, state=deps.AppState(settings, engine=engine, index_dir=root / "indexes"), frontend_dir=root / "no-frontend")
    app.dependency_overrides[deps.get_today] = lambda: date(2026, 9, 13)
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def _evidence_ids(body):
    return {item["id"] for item in body["evidence"]}


def test_health_and_meta(client):
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["counts"]["faqs"] == 69
    assert meta["counts"]["ahcs"] == 31
    assert meta["counts"]["hallmarking_districts"] == 393
    assert meta["counts"]["manuals_parsed"] == 1
    assert meta["llm_enabled"] is False
    assert {item["key"] for item in meta["limitations"]} >= {"jewellers_captcha", "snapshots"}


def test_journey_endpoint_returns_steps_with_resolvable_evidence(client):
    response = client.post("/api/journey", json={"std_key": "IS 14756", "city": "Delhi"})
    assert response.status_code == 200
    body = response.json()
    assert [step["key"] for step in body["steps"]][:3] == ["product", "standards", "compulsory_status"]
    ids = _evidence_ids(body)
    assert all(evidence_id in ids for step in body["steps"] for evidence_id in step["evidence_ids"])
    assert body["sources"] and body["assessment"]["compulsory"] == "COMPULSORY"
    assert client.post("/api/journey", json={}).status_code == 422


def test_assess_endpoint(client):
    body = client.post("/api/assess", json={"text": "packaged drinking water"}).json()
    assert (body["label"], body["compulsory"]) == ("NEEDS_VERIFICATION", "DENOTIFIED")


def test_labs_and_hallmarking_endpoints(client):
    labs = client.get("/api/labs/for-standard", params={"ref": "IS 2062"}).json()
    assert len(labs["matches"]) == 6
    assert set(labs["matches"][0]["evidence_ids"]) <= _evidence_ids(labs)
    district = client.get("/api/hallmarking/district-check", params={"district": "Gurugram"}).json()
    assert district["status"] == "COVERED" and district["matches"][0]["district"] == "Gurgaon"
    ahcs = client.get("/api/hallmarking/ahc", params={"state": "Delhi"}).json()
    assert ahcs["operative"] and ahcs["total_operative"] == len(ahcs["operative"])
    assert all(item["effective_status"] == "OPERATIVE" for item in ahcs["operative"])
    assert client.get("/api/hallmarking/jewellers").json()["access_status"] == "captcha_blocked"


def test_listing_endpoints(client):
    listings = client.get("/api/coverage", params={"scheme_id": "SCHEME_I", "limit": 5}).json()
    assert listings["total"] > 5 and len(listings["items"]) == 5
    detail = client.get(f"/api/coverage/{listings['items'][0]['coverage_id']}").json()
    assert detail["listing"]["evidence_id"] in _evidence_ids(detail)
    upcoming = client.get("/api/qco/upcoming").json()
    assert upcoming["items"] and upcoming["items"][0]["effect"] in ("UPCOMING", "ENFORCEMENT_DATE_REACHED", "NEEDS_VERIFICATION")
    assert client.get("/api/coverage/999999").status_code == 404


def test_standards_faq_sources_and_search(client):
    found = client.get("/api/standards", params={"q": "IS 14756"}).json()
    assert {"IS 14756 (Part 1):2025", "IS 14756 (Part 2):2025"} <= {item["std_key"] for item in found["items"]}
    detail = client.get("/api/standards/detail", params={"key": "IS 269:2015"}).json()
    assert detail["compulsory"] == "COMPULSORY"
    assert "Ordinary Portland Cement" in {listing["product_name"] for listing in detail["listings"]}
    assert client.get("/api/standards/detail", params={"key": "IS 99999"}).status_code == 404
    assert client.get("/api/faq", params={"q": "HUID"}).json()["items"]
    sources = client.get("/api/sources").json()["items"]
    assert any(item["source_id"] == "manak_ahc_list" and item["latest_run"]["status"] == "success" for item in sources)
    search = client.get("/api/search", params={"q": "labs for IS 2062 in Kolkata"}).json()
    assert search["understanding"]["intent"] == "lab_search"


def test_input_validation(client):
    assert client.get("/api/search").status_code == 422
    assert client.get("/api/search", params={"q": "x" * 301}).status_code == 422
    assert client.get("/api/hallmarking/ahc", params={"metal": "platinum"}).status_code == 422
    assert client.get("/api/does-not-exist").status_code == 404
