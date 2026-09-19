"""The built frontend is served for app routes with 200 and for unknown paths with a real 404; the API is untouched."""

import pytest
from fastapi.testclient import TestClient

from manakmarg.api import deps
from manakmarg.api.app import create_app, is_client_route
from manakmarg.core.config import Settings
from manakmarg.db.engine import get_engine, init_db


@pytest.fixture
def client(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=\"root\"></div>", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    engine = get_engine(tmp_path / "db.sqlite3")
    init_db(engine)
    settings = Settings(db_path=tmp_path / "db.sqlite3")
    app = create_app(settings, state=deps.AppState(settings, engine=engine, index_dir=tmp_path / "indexes"), frontend_dir=dist)
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


@pytest.mark.parametrize("path", ["/", "/assistant", "/journey?text=steel", "/gap-analysis?demo=1", "/standards/IS%202062", "/sources"])
def test_app_routes_are_served(client, path):
    response = client.get(path)
    assert response.status_code == 200 and "root" in response.text


@pytest.mark.parametrize("path", ["/no-such-page", "/assistant/extra/deep", "/labsx"])
def test_unknown_paths_get_the_app_with_a_404_status(client, path):
    response = client.get(path)
    assert response.status_code == 404 and "root" in response.text


def test_static_files_and_api_404(client):
    assert client.get("/favicon.svg").status_code == 200
    assert client.get("/api/nope").status_code == 404


def test_client_route_list():
    assert is_client_route("journey") and is_client_route("standards/IS 2062") and not is_client_route("standards/a/b")
