from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from psrdex.config import Settings, load_settings
from psrdex.pipeline import export_catalogs, run_update
from psrdex.storage import CatalogStore


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="psrdex-update",
        description="Incrementally update pulsar archive metadata catalogs.",
    )
    parser.add_argument("--data-dir", type=Path, help="Archive directory to scan.")
    parser.add_argument("--output-dir", type=Path, help="Directory for SQLite and CSV outputs.")
    parser.add_argument("--glob", dest="glob_pattern", help="Archive glob pattern, e.g. '*.nop'.")
    parser.add_argument("--workers", type=int, help="Number of parallel vap workers.")
    parser.add_argument("--vap-bin", help="Path/name of the PSRCHIVE vap executable.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update", help="Scan for new/changed files and update catalogs.")
    update.add_argument("--retry-failures", action="store_true", help="Retry unchanged failed files.")
    update.add_argument("--dry-run", action="store_true", help="Report pending files without processing.")

    subparsers.add_parser("export", help="Re-export CSV catalogs from SQLite.")
    subparsers.add_parser("status", help="Print current manifest counts.")

    return parser


def apply_cli_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    return settings.with_overrides(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        glob_pattern=args.glob_pattern,
        max_workers=args.workers,
        vap_bin=args.vap_bin,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    settings = apply_cli_overrides(load_settings(), args)

    if args.command == "update":
        report = run_update(
            settings,
            retry_failures=args.retry_failures,
            dry_run=args.dry_run,
        )
        print(json.dumps(report.__dict__, indent=2, sort_keys=True))
        return 0

    if args.command == "export":
        print(json.dumps(export_catalogs(settings), indent=2, sort_keys=True))
        return 0

    if args.command == "status":
        with CatalogStore(settings.db_path) as store:
            status = {
                "db_path": str(settings.db_path),
                "observations": store.observation_count(),
                "processed_files": store.status_counts(),
            }
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
