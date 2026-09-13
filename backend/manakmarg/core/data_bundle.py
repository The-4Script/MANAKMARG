"""Runtime data bundle: the processed database, the runtime vector index and the manifests in one archive.

Deployments start from this bundle instead of re-running the ~25-minute online ingestion. ``export_bundle`` writes
it from a working installation; ``import_bundle`` restores it from a local path or an HTTP(S) URL, refusing unsafe
archive members and verifying checksums.
"""

import hashlib
import io
import json
import shutil
import sqlite3
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from manakmarg import __version__
from manakmarg.core import clock
from manakmarg.search.vectors import RUNTIME_CORPORA

BUNDLE_FORMAT = 1
_ALLOWED_PREFIXES = ("processed/", "indexes/", "manifests/")


class BundleError(RuntimeError):
    """The bundle is missing, unreadable, unsafe or does not match its checksums."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def data_status(db_path: Path) -> dict:
    """Whether the database file exists and holds processed listings (read-only check)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return {"ready": False, "reason": "database_missing", "db_path": str(db_path)}
    try:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            listings = conn.execute("SELECT count(*) FROM scheme_coverage").fetchone()[0]
            standards = conn.execute("SELECT count(*) FROM standard").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"ready": False, "reason": f"database_unreadable: {exc}", "db_path": str(db_path)}
    ready = listings > 0 and standards > 0
    return {"ready": ready, "reason": None if ready else "database_empty", "db_path": str(db_path), "listings": listings, "standards": standards}


def export_bundle(db_path: Path, index_dir: Path, manifest_dir: Path, output: Path) -> dict:
    db_path, index_dir, manifest_dir, output = Path(db_path), Path(index_dir), Path(manifest_dir), Path(output)
    status = data_status(db_path)
    if not status["ready"]:
        raise BundleError(f"cannot export: {status['reason']} ({db_path})")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    members = [(db_path, "processed/manakmarg.sqlite3")]
    members += [(index_dir / f"{name}.joblib", f"indexes/{name}.joblib") for name in RUNTIME_CORPORA if (index_dir / f"{name}.joblib").exists()]
    members += [(path, f"manifests/{path.name}") for path in sorted(manifest_dir.glob("*.json"))]
    info = {
        "format": BUNDLE_FORMAT,
        "created_at": clock.now_utc().isoformat(),
        "code_version": __version__,
        "listings": status["listings"],
        "standards": status["standards"],
        "files": {arcname: _sha256(path) for path, arcname in members},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz", compresslevel=9) as tar:
        for path, arcname in members:
            tar.add(path, arcname=arcname)
        payload = json.dumps(info, indent=2).encode("utf-8")
        header = tarfile.TarInfo("BUNDLE.json")
        header.size = len(payload)
        tar.addfile(header, io.BytesIO(payload))
    return {**info, "output": str(output), "bytes": output.stat().st_size}


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": f"manakmarg-deploy/{__version__}"})
    with urllib.request.urlopen(request, timeout=300) as response, open(target, "wb") as handle:
        shutil.copyfileobj(response, handle)


def import_bundle(source: str | Path, *, db_path: Path, index_dir: Path, manifest_dir: Path, force: bool = False) -> dict:
    """Restore a bundle. Skips when a ready database already exists unless ``force`` is set."""
    db_path, index_dir, manifest_dir = Path(db_path), Path(index_dir), Path(manifest_dir)
    if not force and data_status(db_path)["ready"]:
        return {"imported": False, "reason": "database_already_present", "db_path": str(db_path)}
    with tempfile.TemporaryDirectory() as workdir:
        workdir = Path(workdir)
        archive = workdir / "bundle.tar.gz"
        text = str(source)
        if text.startswith(("http://", "https://")):
            _download(text, archive)
        elif Path(text).exists():
            archive = Path(text)
        else:
            raise BundleError(f"bundle not found: {text}")
        extracted = workdir / "extracted"
        try:
            with tarfile.open(archive, "r:gz") as tar:
                members = tar.getmembers()
                for member in members:
                    name = member.name
                    if not member.isfile() or name.startswith(("/", "\\")) or ".." in Path(name).parts or not (name == "BUNDLE.json" or name.startswith(_ALLOWED_PREFIXES)):
                        raise BundleError(f"unsafe or unexpected member in bundle: {name}")
                tar.extractall(extracted, members=members, filter="data")
        except (tarfile.TarError, OSError) as exc:
            raise BundleError(f"cannot read bundle: {exc}") from exc
        info_path = extracted / "BUNDLE.json"
        if not info_path.exists():
            raise BundleError("bundle has no BUNDLE.json")
        info = json.loads(info_path.read_text(encoding="utf-8"))
        for arcname, expected in info.get("files", {}).items():
            path = extracted / arcname
            if not path.exists() or _sha256(path) != expected:
                raise BundleError(f"checksum mismatch or missing file: {arcname}")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)
        shutil.copyfile(extracted / "processed" / "manakmarg.sqlite3", db_path)
        index_dir.mkdir(parents=True, exist_ok=True)
        for path in (extracted / "indexes").glob("*.joblib"):
            shutil.copyfile(path, index_dir / path.name)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        for path in (extracted / "manifests").glob("*.json"):
            shutil.copyfile(path, manifest_dir / path.name)
    return {"imported": True, "db_path": str(db_path), **{key: info.get(key) for key in ("created_at", "code_version", "listings", "standards")}}
