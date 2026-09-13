"""Filesystem layout. Raw supplied workbooks stay directly in data/ and are never modified.

All paths are relative to the repository root, which is found from this file's location. Set ``MANAKMARG_HOME`` to
point at another root (for example when the package is installed outside the repository).
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ["MANAKMARG_HOME"]).resolve() if os.environ.get("MANAKMARG_HOME") else Path(__file__).resolve().parents[3]

DATA_DIR = PROJECT_ROOT / "data"
RAW_WEB_DIR = DATA_DIR / "raw" / "web"
RAW_DOCS_DIR = DATA_DIR / "raw" / "documents"
STAGING_DIR = DATA_DIR / "staging"
PROCESSED_DIR = DATA_DIR / "processed"
INDEX_DIR = DATA_DIR / "indexes"
MANIFEST_DIR = DATA_DIR / "manifests"
UPLOAD_DIR = DATA_DIR / "uploads"

DOCS_DIR = PROJECT_ROOT / "docs"
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"

_WORKING_DIRS = (
    RAW_WEB_DIR,
    RAW_DOCS_DIR,
    STAGING_DIR,
    PROCESSED_DIR,
    INDEX_DIR,
    MANIFEST_DIR,
    UPLOAD_DIR,
)


def ensure_dirs() -> None:
    for directory in _WORKING_DIRS:
        directory.mkdir(parents=True, exist_ok=True)
