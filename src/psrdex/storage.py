from __future__ import annotations

import csv
import re
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from psrdex.config import Settings
from psrdex.discovery import FileFingerprint
from psrdex.extractor import OBSERVATION_COLUMNS, ExtractionResult

UTC = timezone.utc


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.+-]+", "_", value.strip())
    return safe or "unknown"


class CatalogStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "CatalogStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS processed_files (
                path TEXT PRIMARY KEY,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                status TEXT NOT NULL,
                pulsar TEXT,
                processed_at_utc TEXT NOT NULL,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS observations (
                path TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                file_size_bytes INTEGER NOT NULL,
                file_mtime_ns INTEGER NOT NULL,
                pulsar TEXT NOT NULL,
                datetime_utc TEXT,
                mjd REAL,
                ra TEXT,
                dec TEXT,
                band TEXT,
                freq_mhz REAL,
                bandwidth_mhz REAL,
                nsub INTEGER,
                nchan INTEGER,
                nbin INTEGER,
                npol INTEGER,
                tbin_sec REAL,
                tsub_sec REAL,
                duration_sec REAL,
                period_sec REAL,
                dm REAL,
                dmc INTEGER,
                snr REAL,
                processed_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS failures (
                path TEXT PRIMARY KEY,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                error TEXT NOT NULL,
                failed_at_utc TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_observations_pulsar ON observations (pulsar);
            CREATE INDEX IF NOT EXISTS idx_observations_mjd ON observations (mjd);
            CREATE INDEX IF NOT EXISTS idx_processed_status ON processed_files (status);
            """
        )
        self.conn.commit()

    def pending_files(
        self,
        fingerprints: Iterable[FileFingerprint],
        *,
        retry_failures: bool = False,
    ) -> list[FileFingerprint]:
        pending: list[FileFingerprint] = []
        for fp in fingerprints:
            row = self.conn.execute(
                """
                SELECT size_bytes, mtime_ns, status
                FROM processed_files
                WHERE path = ?
                """,
                (fp.path_str,),
            ).fetchone()
            if row is None:
                pending.append(fp)
                continue
            unchanged = row["size_bytes"] == fp.size_bytes and row["mtime_ns"] == fp.mtime_ns
            if not unchanged:
                pending.append(fp)
                continue
            if row["status"] == "ok":
                continue
            if retry_failures:
                pending.append(fp)
        return pending

    def record_result(self, result: ExtractionResult) -> None:
        if result.ok and result.observation is not None:
            self._record_success(result)
        else:
            self._record_failure(result)
        self.conn.commit()

    def _record_success(self, result: ExtractionResult) -> None:
        observation = dict(result.observation or {})
        observation["dmc"] = int(bool(observation.get("dmc")))
        values = [observation.get(column) for column in OBSERVATION_COLUMNS]
        placeholders = ", ".join("?" for _ in OBSERVATION_COLUMNS)
        updates = ", ".join(f"{column}=excluded.{column}" for column in OBSERVATION_COLUMNS[1:])

        self.conn.execute(
            f"""
            INSERT INTO observations ({", ".join(OBSERVATION_COLUMNS)})
            VALUES ({placeholders})
            ON CONFLICT(path) DO UPDATE SET {updates}
            """,
            values,
        )
        self.conn.execute(
            """
            INSERT INTO processed_files
                (path, size_bytes, mtime_ns, status, pulsar, processed_at_utc, error)
            VALUES (?, ?, ?, 'ok', ?, ?, NULL)
            ON CONFLICT(path) DO UPDATE SET
                size_bytes = excluded.size_bytes,
                mtime_ns = excluded.mtime_ns,
                status = excluded.status,
                pulsar = excluded.pulsar,
                processed_at_utc = excluded.processed_at_utc,
                error = NULL
            """,
            (
                result.fingerprint.path_str,
                result.fingerprint.size_bytes,
                result.fingerprint.mtime_ns,
                observation.get("pulsar"),
                observation.get("processed_at_utc") or utc_now(),
            ),
        )
        self.conn.execute("DELETE FROM failures WHERE path = ?", (result.fingerprint.path_str,))

    def _record_failure(self, result: ExtractionResult) -> None:
        now = utc_now()
        error = result.error or "unknown extraction error"
        self.conn.execute("DELETE FROM observations WHERE path = ?", (result.fingerprint.path_str,))
        self.conn.execute(
            """
            INSERT INTO processed_files
                (path, size_bytes, mtime_ns, status, pulsar, processed_at_utc, error)
            VALUES (?, ?, ?, 'failed', NULL, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                size_bytes = excluded.size_bytes,
                mtime_ns = excluded.mtime_ns,
                status = excluded.status,
                pulsar = NULL,
                processed_at_utc = excluded.processed_at_utc,
                error = excluded.error
            """,
            (
                result.fingerprint.path_str,
                result.fingerprint.size_bytes,
                result.fingerprint.mtime_ns,
                now,
                error,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO failures (path, size_bytes, mtime_ns, error, failed_at_utc)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                size_bytes = excluded.size_bytes,
                mtime_ns = excluded.mtime_ns,
                error = excluded.error,
                failed_at_utc = excluded.failed_at_utc
            """,
            (
                result.fingerprint.path_str,
                result.fingerprint.size_bytes,
                result.fingerprint.mtime_ns,
                error,
                now,
            ),
        )

    def status_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM processed_files GROUP BY status"
        ).fetchall()
        return {row["status"]: int(row["n"]) for row in rows}

    def observation_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM observations").fetchone()
        return int(row["n"]) if row else 0

    def export_csvs(self, settings: Settings) -> dict[str, Any]:
        settings.ensure_output_dirs()
        observations = self._fetch_dicts(
            "SELECT * FROM observations ORDER BY pulsar, mjd, band, path"
        )
        failures = self._fetch_dicts("SELECT * FROM failures ORDER BY failed_at_utc DESC, path")

        write_csv(settings.observations_csv, observations, OBSERVATION_COLUMNS)
        write_csv(settings.failures_csv, failures, FAILURE_COLUMNS)

        summary = build_summary(observations)
        write_csv(settings.summary_csv, summary, SUMMARY_COLUMNS)

        written_pulsars = set()
        by_pulsar: dict[str, list[dict[str, Any]]] = {}
        for observation in observations:
            pulsar_name = str(observation.get("pulsar") or "unknown")
            by_pulsar.setdefault(pulsar_name, []).append(observation)

        for pulsar_name, rows in by_pulsar.items():
            file_stem = safe_filename(pulsar_name)
            written_pulsars.add(file_stem)
            write_csv(settings.pulsar_dir / f"{file_stem}.csv", rows, OBSERVATION_COLUMNS)

        for old_csv in settings.pulsar_dir.glob("*.csv"):
            if old_csv.stem not in written_pulsars:
                old_csv.unlink()

        return {
            "observations": len(observations),
            "pulsars": len({row.get("pulsar") for row in observations if row.get("pulsar")}),
            "failures": len(failures),
            "observations_csv": str(settings.observations_csv),
            "summary_csv": str(settings.summary_csv),
            "pulsar_dir": str(settings.pulsar_dir),
        }

    def _fetch_dicts(self, query: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(query).fetchall()
        return [dict(row) for row in rows]


FAILURE_COLUMNS = ["path", "size_bytes", "mtime_ns", "error", "failed_at_utc"]

SUMMARY_COLUMNS = [
    "pulsar",
    "n_files",
    "total_duration_hours",
    "first_mjd",
    "last_mjd",
    "first_observation_utc",
    "last_observation_utc",
    "bands",
    "ra",
    "dec",
]


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_summary(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        pulsar = str(observation.get("pulsar") or "unknown")
        grouped.setdefault(pulsar, []).append(observation)

    rows = []
    for pulsar, group in sorted(grouped.items()):
        mjds = [float(row["mjd"]) for row in group if row.get("mjd") is not None]
        durations = [
            float(row["duration_sec"]) for row in group if row.get("duration_sec") is not None
        ]
        datetimes = [str(row["datetime_utc"]) for row in group if row.get("datetime_utc")]
        bands = sorted({str(row["band"]) for row in group if row.get("band")})
        ra = next((row.get("ra") for row in group if row.get("ra")), None)
        dec = next((row.get("dec") for row in group if row.get("dec")), None)
        rows.append(
            {
                "pulsar": pulsar,
                "n_files": len(group),
                "total_duration_hours": sum(durations) / 3600,
                "first_mjd": min(mjds) if mjds else None,
                "last_mjd": max(mjds) if mjds else None,
                "first_observation_utc": min(datetimes) if datetimes else None,
                "last_observation_utc": max(datetimes) if datetimes else None,
                "bands": ",".join(bands),
                "ra": ra,
                "dec": dec,
            }
        )
    return rows
