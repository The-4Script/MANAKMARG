"""Private, expiring storage for uploaded documents (spec §11, §14).

* A session is an unguessable random id; files live only under ``<root>/<session_id>/``.
* Uploads are validated by extension, magic bytes and size before they are written.
* Sessions expire after the configured TTL and are deleted by ``purge_expired`` or on request.
* File contents are never logged; only ids, roles, sizes and hashes are recorded in the session manifest.
"""

import hashlib
import json
import re
import secrets
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from manakmarg.core import clock

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
ROLES = ("requirement", "datasheet", "test_report")
_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


class UploadRejected(ValueError):
    """The file failed validation (type, content or size)."""


class SessionNotFound(LookupError):
    """Unknown, deleted or expired session."""


@dataclass(frozen=True)
class StoredFile:
    file_id: str
    filename: str
    role: str
    extension: str
    bytes: int
    sha256: str
    uploaded_at: str
    demo: bool = False


def _looks_valid(extension: str, data: bytes) -> bool:
    if extension == ".pdf":
        return data.startswith(b"%PDF")
    if extension == ".docx":
        return data.startswith(b"PK\x03\x04")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return b"\x00" not in data


class SessionStore:
    def __init__(self, root: Path, *, ttl_minutes: int, max_bytes: int):
        self.root = Path(root)
        self.ttl = timedelta(minutes=ttl_minutes)
        self.max_bytes = max_bytes

    # ------------------------------------------------------------------ sessions

    def _dir(self, session_id: str) -> Path:
        if not _SESSION_ID.match(session_id or ""):
            raise SessionNotFound(session_id)
        return self.root / session_id

    def _manifest(self, session_id: str) -> dict:
        path = self._dir(session_id) / "session.json"
        if not path.exists():
            raise SessionNotFound(session_id)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if datetime.fromisoformat(manifest["expires_at"]) <= clock.now_utc():
            self.delete(session_id)
            raise SessionNotFound(session_id)
        return manifest

    def _write_manifest(self, session_id: str, manifest: dict) -> None:
        (self._dir(session_id) / "session.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def create(self) -> dict:
        self.purge_expired()
        session_id = secrets.token_urlsafe(24)
        now = clock.now_utc()
        self._dir(session_id).mkdir(parents=True)
        manifest = {"session_id": session_id, "created_at": now.isoformat(), "expires_at": (now + self.ttl).isoformat(), "files": []}
        self._write_manifest(session_id, manifest)
        return {key: manifest[key] for key in ("session_id", "created_at", "expires_at")}

    def info(self, session_id: str) -> dict:
        manifest = self._manifest(session_id)
        return {**{key: manifest[key] for key in ("session_id", "created_at", "expires_at")}, "files": manifest["files"]}

    def delete(self, session_id: str) -> bool:
        directory = self._dir(session_id)
        if not directory.exists():
            return False
        shutil.rmtree(directory, ignore_errors=True)
        return True

    def purge_expired(self) -> int:
        if not self.root.exists():
            return 0
        removed = 0
        now = clock.now_utc()
        for manifest_path in self.root.glob("*/session.json"):
            try:
                expires = datetime.fromisoformat(json.loads(manifest_path.read_text(encoding="utf-8"))["expires_at"])
            except (ValueError, KeyError, json.JSONDecodeError):
                expires = now
            if expires <= now:
                shutil.rmtree(manifest_path.parent, ignore_errors=True)
                removed += 1
        return removed

    # ------------------------------------------------------------------ files

    def add_file(self, session_id: str, filename: str, data: bytes, role: str, *, demo: bool = False) -> StoredFile:
        manifest = self._manifest(session_id)
        if role not in ROLES:
            raise UploadRejected(f"role must be one of {', '.join(ROLES)}")
        extension = Path(filename or "").suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise UploadRejected("only PDF, DOCX and TXT files are accepted")
        if not data:
            raise UploadRejected("the file is empty")
        if len(data) > self.max_bytes:
            raise UploadRejected(f"the file is larger than {self.max_bytes // (1024 * 1024)} MB")
        if not _looks_valid(extension, data):
            raise UploadRejected("the file content does not match its extension")
        file_id = secrets.token_hex(8)
        safe_name = _UNSAFE_NAME.sub("_", Path(filename).name)[:120] or f"upload{extension}"
        (self._dir(session_id) / f"{file_id}{extension}").write_bytes(data)
        stored = StoredFile(
            file_id=file_id,
            filename=safe_name,
            role=role,
            extension=extension,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            uploaded_at=clock.now_utc().isoformat(),
            demo=demo,
        )
        manifest["files"].append(asdict(stored))
        self._write_manifest(session_id, manifest)
        return stored

    def remove_file(self, session_id: str, file_id: str) -> bool:
        manifest = self._manifest(session_id)
        remaining = [item for item in manifest["files"] if item["file_id"] != file_id]
        if len(remaining) == len(manifest["files"]):
            return False
        for item in manifest["files"]:
            if item["file_id"] == file_id:
                (self._dir(session_id) / f"{file_id}{item['extension']}").unlink(missing_ok=True)
        manifest["files"] = remaining
        self._write_manifest(session_id, manifest)
        return True

    def files(self, session_id: str) -> list[tuple[StoredFile, Path]]:
        manifest = self._manifest(session_id)
        return [
            (StoredFile(**item), self._dir(session_id) / f"{item['file_id']}{item['extension']}")
            for item in manifest["files"]
        ]
