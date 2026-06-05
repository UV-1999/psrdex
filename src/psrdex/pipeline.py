from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

from psrdex.config import Settings
from psrdex.discovery import FileFingerprint, discover_files
from psrdex.extractor import ExtractionResult, process_file
from psrdex.storage import CatalogStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateReport:
    discovered: int
    pending: int
    processed_ok: int
    failed: int
    exported: dict[str, object]


def _process_worker(args: tuple[FileFingerprint, str, str, int, bool]) -> ExtractionResult:
    fingerprint, vap_bin, pdv_bin, timeout_sec, extract_snr = args
    return process_file(
        fingerprint,
        vap_bin=vap_bin,
        pdv_bin=pdv_bin,
        timeout_sec=timeout_sec,
        extract_snr=extract_snr,
    )


def run_update(
    settings: Settings,
    *,
    retry_failures: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> UpdateReport:
    settings.ensure_output_dirs()
    LOGGER.info("Scanning %s for %s", settings.data_dir, settings.glob_pattern)
    discovered = discover_files(settings.data_dir, settings.glob_pattern)

    with CatalogStore(settings.db_path) as store:
        pending = store.pending_files(discovered, retry_failures=retry_failures, force=force)
        LOGGER.info("Discovered %d files; %d need processing", len(discovered), len(pending))

        if dry_run:
            return UpdateReport(
                discovered=len(discovered),
                pending=len(pending),
                processed_ok=0,
                failed=0,
                exported={},
            )

        ok = 0
        failed = 0
        if pending:
            worker_args = [
                (
                    fp,
                    settings.vap_bin,
                    settings.pdv_bin,
                    settings.vap_timeout_sec,
                    settings.extract_snr,
                )
                for fp in pending
            ]
            max_workers = max(1, settings.max_workers)
            if max_workers == 1:
                results = (_process_worker(args) for args in worker_args)
                for result in results:
                    store.record_result(result)
                    ok += int(result.ok)
                    failed += int(not result.ok)
            else:
                with ProcessPoolExecutor(max_workers=max_workers) as executor:
                    futures = [executor.submit(_process_worker, args) for args in worker_args]
                    for future in as_completed(futures):
                        result = future.result()
                        store.record_result(result)
                        ok += int(result.ok)
                        failed += int(not result.ok)
                        if (ok + failed) % 100 == 0:
                            LOGGER.info("Processed %d/%d pending files", ok + failed, len(pending))

        exported = store.export_csvs(settings)

    return UpdateReport(
        discovered=len(discovered),
        pending=len(pending),
        processed_ok=ok,
        failed=failed,
        exported=exported,
    )


def export_catalogs(settings: Settings) -> dict[str, object]:
    settings.ensure_output_dirs()
    with CatalogStore(settings.db_path) as store:
        return store.export_csvs(settings)
