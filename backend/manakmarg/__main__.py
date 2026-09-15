"""MANAK MARG command line: ``python -m manakmarg <command>`` (also installed as the ``manakmarg`` script)."""

import argparse
import json
import logging
import sys

from manakmarg.core import paths
from manakmarg.core.config import get_settings

STEP_NAMES = ("standards", "hsn", "schemes", "pages", "psg", "documents", "labs", "lab_scope", "hallmarking", "index", "quality")


def _fetcher(settings, *, offline: bool):
    from manakmarg.ingest.fetch import Fetcher

    return Fetcher(
        paths.RAW_WEB_DIR,
        min_delay_s=settings.fetch_min_delay_s,
        user_agent=settings.user_agent,
        offline=offline or settings.offline,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manakmarg", description="MANAK MARG — BIS standards and compliance assistant (SIH 2026 prototype)."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="Create the database schema and sync the source registry.")
    ingest = commands.add_parser("ingest", help="Fetch, parse and load official sources.")
    ingest.add_argument("--steps", nargs="+", choices=STEP_NAMES, help="Run only these steps (default: all).")
    ingest.add_argument("--offline", action="store_true", help="Replay cached snapshots only; never use the network.")
    build_index = commands.add_parser("build-index", help="Rebuild the full-text and vector indexes.")
    build_index.add_argument("--runtime-only", action="store_true", help="Build only what the API needs (FTS + listing vectors).")
    commands.add_parser("validate", help="Run data-quality checks and write the report.")
    commands.add_parser("inventory", help="Profile the supplied Excel workbooks.")
    export = commands.add_parser("export-data", help="Write the runtime data bundle (database, runtime index, manifests).")
    export.add_argument("--output", help="Bundle path (default: deploy/data/manakmarg-data.tar.gz).")
    load = commands.add_parser("import-data", help="Restore the runtime data bundle from a path or URL.")
    load.add_argument("source", nargs="?", help="Bundle path or http(s) URL (default: MANAKMARG_DATA_URL or deploy/data bundle).")
    load.add_argument("--force", action="store_true", help="Replace an existing database.")
    for name, text in (("serve", "Run the API and the built frontend."), ("start", "Deployment entry point: restore data if needed, then serve.")):
        command = commands.add_parser(name, help=text)
        command.add_argument("--host", default=None, help="Bind address (default: HOST or 127.0.0.1).")
        command.add_argument("--port", type=int, default=None, help="Port (default: PORT or 8000).")
    return parser


def _serve(settings, host: str | None, port: int | None) -> int:
    from manakmarg.core.data_bundle import data_status

    status = data_status(settings.db_path)
    if not status["ready"]:
        print(
            f"No processed data ({status['reason']}) at {status['db_path']}.\n"
            "Restore it with `python -m manakmarg import-data <bundle path or URL>` "
            "or rebuild it with `python -m manakmarg ingest`.",
            file=sys.stderr,
        )
        return 2
    import uvicorn

    uvicorn.run("manakmarg.api.app:create_app", factory=True, host=host or settings.host, port=port or settings.port)
    return 0


def _import(settings, source: str | None, force: bool) -> dict:
    from manakmarg.core.data_bundle import import_bundle

    chosen = source or settings.data_url or str(settings.data_bundle)
    return import_bundle(chosen, db_path=settings.db_path, index_dir=paths.INDEX_DIR, manifest_dir=paths.MANIFEST_DIR, force=force)


def _build_runtime_index(settings) -> dict:
    from manakmarg.db import fts
    from manakmarg.db.engine import get_engine
    from manakmarg.search.vectors import RUNTIME_CORPORA, build_vector_indexes

    engine = get_engine(settings.db_path)
    with engine.begin() as conn:
        fts.create_fts(conn)
        fts.rebuild_fts(conn)
    with engine.connect() as conn:
        counts = build_vector_indexes(conn, paths.INDEX_DIR, corpora=RUNTIME_CORPORA)
    engine.dispose()
    return {"vectors": counts}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    paths.ensure_dirs()

    if args.command == "serve":
        return _serve(settings, args.host, args.port)

    if args.command == "start":
        from manakmarg.core.data_bundle import BundleError, data_status

        if not data_status(settings.db_path)["ready"]:
            try:
                print(json.dumps(_import(settings, None, force=False), default=str))
            except BundleError as exc:
                print(f"Data bundle could not be restored: {exc}", file=sys.stderr)
                return 2
        if not (paths.INDEX_DIR / "coverage.joblib").exists():
            print(json.dumps(_build_runtime_index(settings)))
        return _serve(settings, args.host, args.port)

    if args.command == "inventory":
        from manakmarg.ingest.inventory import build_inventory, write_inventory

        write_inventory(
            build_inventory(paths.DATA_DIR), paths.MANIFEST_DIR / "data_inventory.json", paths.DOCS_DIR / "DATA_INVENTORY.md"
        )
        print("Inventory written to data/manifests/data_inventory.json and docs/DATA_INVENTORY.md")
        return 0

    if args.command == "export-data":
        from manakmarg.core.data_bundle import export_bundle

        output = args.output or str(settings.data_bundle)
        print(json.dumps(export_bundle(settings.db_path, paths.INDEX_DIR, paths.MANIFEST_DIR, output), indent=2, default=str))
        return 0

    if args.command == "import-data":
        from manakmarg.core.data_bundle import BundleError

        try:
            print(json.dumps(_import(settings, args.source, args.force), indent=2, default=str))
        except BundleError as exc:
            print(f"Data bundle could not be restored: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "build-index" and args.runtime_only:
        print(json.dumps(_build_runtime_index(settings), indent=2))
        return 0

    from manakmarg.db.engine import get_engine, init_db
    from manakmarg.ingest import pipeline, sources

    engine = get_engine(settings.db_path)
    if args.command == "init-db":
        init_db(engine)
        with engine.begin() as conn:
            sources.sync_registry(conn)
        print(f"Database ready: {settings.db_path}")
        return 0

    steps = {"ingest": args.steps if args.command == "ingest" else None, "build-index": ["index"], "validate": ["quality"]}
    offline = args.offline if args.command == "ingest" else True
    report = pipeline.run_pipeline(engine, _fetcher(settings, offline=offline), steps=steps[args.command])
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
