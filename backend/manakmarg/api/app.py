"""FastAPI application: JSON API under /api and, when built, the React SPA at /."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from manakmarg import __version__
from manakmarg.core import paths
from manakmarg.core.config import Settings, get_settings

from . import deps
from .routers import assistant, compliance, documents, hsn, labs_hallmarking, meta, voice


CLIENT_ROUTES = frozenset({"", "assistant", "journey", "standards", "certification", "labs", "hallmarking", "gap-analysis", "sources"})


def is_client_route(path: str) -> bool:
    """Paths the React router serves (kept in step with ``frontend/src/App.tsx``)."""
    parts = path.strip("/").split("/")
    return (len(parts) == 1 and parts[0] in CLIENT_ROUTES) or (len(parts) == 2 and parts[0] == "standards" and bool(parts[1]))


def create_app(settings: Settings | None = None, state: deps.AppState | None = None, frontend_dir: Path | None = None) -> FastAPI:
    settings = settings or get_settings()
    deps.configure(state or deps.AppState(settings))
    app = FastAPI(
        title="MANAK MARG API",
        version=__version__,
        description="Evidence-first navigator for Indian Standards and BIS compliance (independent SIH 2026 prototype).",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    for router in (meta.router, compliance.router, labs_hallmarking.router, assistant.router, documents.router, voice.router, hsn.router):
        app.include_router(router, prefix="/api")

    dist = frontend_dir or paths.FRONTEND_DIST_DIR
    if (dist / "index.html").exists():
        if (dist / "assets").exists():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Not found")
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            # Unknown paths still get the app (it shows a "page not found" view) but with a real 404 status.
            status = 200 if is_client_route(path) else 404
            return FileResponse(dist / "index.html", status_code=status)

    return app
