from __future__ import annotations

import csv
import math
import re
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bands import BAND_INFO, band_label, band_sort_key


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return [{key: _coerce(value) for key, value in row.items()} for row in csv.DictReader(handle)]


def _coerce(value: str | None) -> Any:
    if value in (None, ""):
        return None
    text = str(value)
    for caster in (int, float):
        try:
            return caster(text)
        except ValueError:
            pass
    return text


class CatalogRepository:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.db_path = output_dir / "psrdex.sqlite"

    def observations(self) -> list[dict[str, Any]]:
        if self.db_path.exists():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM observations ORDER BY pulsar, mjd, band, path").fetchall()
            return [self._shape_observation(dict(row), index) for index, row in enumerate(rows)]
        return [self._shape_observation(row, index) for index, row in enumerate(_read_csv(self.output_dir / "observations.csv"))]

    def failures(self) -> list[dict[str, Any]]:
        if self.db_path.exists():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM failures ORDER BY failed_at_utc DESC, path").fetchall()
            return [dict(row) for row in rows]
        return _read_csv(self.output_dir / "failures.csv")

    def overview(self) -> dict[str, Any]:
        observations = self.observations()
        pulsars = sorted({row["pulsar"] for row in observations if row.get("pulsar")})
        duration = sum(float(row.get("duration_sec") or 0) for row in observations)
        bands = sorted({str(row["band"]) for row in observations if row.get("band")}, key=band_sort_key)
        processed = [row.get("processed_at_utc") for row in observations if row.get("processed_at_utc")]
        csv_path = self.output_dir / "observations.csv"
        last_updated = max(processed) if processed else None
        if last_updated is None and csv_path.exists():
            last_updated = datetime.fromtimestamp(csv_path.stat().st_mtime, timezone.utc).isoformat()
        return {
            "pulsars": len(pulsars),
            "files": len(observations),
            "total_duration_hours": duration / 3600,
            "bands": [{"id": band, **BAND_INFO.get(band, {}), "display": band_label(band)} for band in bands],
            "last_updated": last_updated,
            "failures": len(self.failures()),
        }

    def pulsars(self) -> list[dict[str, Any]]:
        rows = self.observations()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get("pulsar") or "unknown"), []).append(row)
        result = []
        for pulsar, group in sorted(grouped.items()):
            mjds = [float(row["mjd"]) for row in group if row.get("mjd") is not None]
            duration = sum(float(row.get("duration_sec") or 0) for row in group)
            snrs = [float(row["snr"]) for row in group if row.get("snr") is not None]
            bands = sorted({str(row["band"]) for row in group if row.get("band")}, key=band_sort_key)
            result.append(
                {
                    "pulsar": pulsar,
                    "n_files": len(group),
                    "total_duration_hours": duration / 3600,
                    "first_mjd": min(mjds) if mjds else None,
                    "last_mjd": max(mjds) if mjds else None,
                    "max_snr": max(snrs) if snrs else None,
                    "bands": bands,
                    "ra": next((row.get("ra") for row in group if row.get("ra")), None),
                    "dec": next((row.get("dec") for row in group if row.get("dec")), None),
                }
            )
        return result

    def observations_for_pulsar(self, pulsar: str) -> list[dict[str, Any]]:
        return [row for row in self.observations() if str(row.get("pulsar")) == pulsar]

    def band_summary(self, pulsar: str, bands: Iterable[str] | None = None) -> list[dict[str, Any]]:
        selected = set(bands or [])
        rows = self.observations_for_pulsar(pulsar)
        if selected:
            rows = [row for row in rows if str(row.get("band")) in selected]
        summary = []
        for band in sorted({str(row.get("band")) for row in rows if row.get("band")}, key=band_sort_key):
            group = [row for row in rows if str(row.get("band")) == band]
            snrs = [float(row["snr"]) for row in group if row.get("snr") is not None]
            duration = sum(float(row.get("duration_sec") or 0) for row in group)
            times = [row["observation_time"] for row in group if row.get("observation_time")]
            summary.append(
                {
                    "band": band,
                    "lane": band_label(band),
                    "receiver": BAND_INFO.get(band, {}).get("receiver", ""),
                    "files": len(group),
                    "hours": duration / 3600,
                    "max_snr": max(snrs) if snrs else None,
                    "latest": max(times) if times else None,
                }
            )
        return summary

    def _shape_observation(self, row: dict[str, Any], index: int) -> dict[str, Any]:
        clean = {key: _clean_value(value) for key, value in row.items()}
        clean["row_id"] = str(index)
        clean["band_display"] = band_label(clean.get("band"))
        clean["observation_time"] = observation_time(clean)
        return clean


def observation_time(row: dict[str, Any]) -> str | None:
    raw = row.get("datetime_utc")
    if raw:
        return str(raw)
    if row.get("mjd") is not None:
        try:
            mjd_epoch = datetime(1858, 11, 17, tzinfo=timezone.utc)
            seconds = float(row["mjd"]) * 86400
            return datetime.fromtimestamp(mjd_epoch.timestamp() + seconds, timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            pass
    file_name = str(row.get("file_name") or "")
    match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2}:\d{2}:\d{2})", file_name)
    if match:
        return f"{match.group(1)}T{match.group(2)}Z"
    return None
