"""Document gap-analysis sessions: private uploads with TTL, labelled demo files, analysis, deletion."""

from functools import lru_cache

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from manakmarg.core import paths
from manakmarg.documents.gap import add_demo_files, analyze_session
from manakmarg.documents.store import SessionNotFound, SessionStore, UploadRejected

from ..deps import get_state
from ..serialize import plain

router = APIRouter(prefix="/documents", tags=["documents"])


@lru_cache(maxsize=1)
def _store() -> SessionStore:
    settings = get_state().settings
    return SessionStore(paths.UPLOAD_DIR, ttl_minutes=settings.upload_ttl_minutes, max_bytes=settings.upload_max_mb * 1024 * 1024)


def store() -> SessionStore:
    return _store()


def _not_found(exc: SessionNotFound) -> HTTPException:
    return HTTPException(404, "Session not found or expired.")


@router.post("/sessions")
def create_session() -> dict:
    created = store().create()
    return {**created, "max_mb": get_state().settings.upload_max_mb, "ttl_minutes": get_state().settings.upload_ttl_minutes}


@router.get("/sessions/{session_id}")
def session_info(session_id: str) -> dict:
    try:
        return store().info(session_id)
    except SessionNotFound as exc:
        raise _not_found(exc) from None


@router.post("/sessions/{session_id}/files")
async def upload(session_id: str, role: str = Form(...), file: UploadFile = File(...)) -> dict:
    limit = store().max_bytes
    data = await file.read(limit + 1)
    try:
        stored = store().add_file(session_id, file.filename or "upload", data, role)
    except SessionNotFound as exc:
        raise _not_found(exc) from None
    except UploadRejected as exc:
        raise HTTPException(422, str(exc)) from None
    return plain(stored)


@router.post("/sessions/{session_id}/demo")
def demo_files(session_id: str) -> dict:
    try:
        return {"files": add_demo_files(store(), session_id)}
    except SessionNotFound as exc:
        raise _not_found(exc) from None


@router.delete("/sessions/{session_id}/files/{file_id}")
def remove_file(session_id: str, file_id: str) -> dict:
    try:
        return {"removed": store().remove_file(session_id, file_id)}
    except SessionNotFound as exc:
        raise _not_found(exc) from None


@router.post("/sessions/{session_id}/analyze")
def analyze(session_id: str) -> dict:
    try:
        return plain(analyze_session(store(), session_id))
    except SessionNotFound as exc:
        raise _not_found(exc) from None


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    try:
        return {"deleted": store().delete(session_id)}
    except SessionNotFound as exc:
        raise _not_found(exc) from None
