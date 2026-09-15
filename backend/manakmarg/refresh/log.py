"""Refresh log (``data/refresh/refresh_log.jsonl``, one JSON object per refresh) and the active-dataset pointer
(``data/refresh/ACTIVE.json``)."""

import json
import os
from datetime import datetime
from pathlib import Path

LOG_NAME = "refresh_log.jsonl"
ACTIVE_NAME = "ACTIVE.json"


def append(refresh_dir: Path, entry: dict) -> None:
    refresh_dir = Path(refresh_dir)
    refresh_dir.mkdir(parents=True, exist_ok=True)
    with open(refresh_dir / LOG_NAME, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_entries(refresh_dir: Path, limit: int | None = None) -> list[dict]:
    path = Path(refresh_dir) / LOG_NAME
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a line torn by a crash is ignored; the next refresh appends a complete one
    return entries[-limit:] if limit else entries


def write_active(refresh_dir: Path, data: dict) -> None:
    path = Path(refresh_dir) / ACTIVE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(temporary, path)


def read_active(refresh_dir: Path) -> dict | None:
    path = Path(refresh_dir) / ACTIVE_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def last_successful(refresh_dir: Path) -> dict | None:
    return next((entry for entry in reversed(read_entries(refresh_dir)) if entry.get("status") == "success"), None)


def last_attempt_at(refresh_dir: Path) -> datetime | None:
    """Start time of the latest refresh that actually ran (runs skipped because one was already running are ignored)."""
    for entry in reversed(read_entries(refresh_dir)):
        if entry.get("status") != "skipped" and entry.get("started_at"):
            try:
                return datetime.fromisoformat(entry["started_at"])
            except ValueError:
                return None
    return None


def read_status(refresh_dir: Path, next_run_at: datetime | None = None) -> dict:
    entries = read_entries(refresh_dir)
    last = entries[-1] if entries else None
    active = read_active(refresh_dir) or {}
    success = last_successful(refresh_dir)
    return {
        "state": "never_run" if last is None else last.get("status"),
        "active_version": active.get("version"),
        "activated_at": active.get("activated_at"),
        "last_success_at": success.get("completed_at") if success else None,
        "last_refresh": None
        if last is None
        else {
            **{key: last.get(key) for key in ("refresh_id", "trigger", "status", "started_at", "completed_at", "error")},
            "activation": (last.get("activation") or {}).get("status"),
        },
        "next_scheduled_at": next_run_at.isoformat() if next_run_at else None,
    }
