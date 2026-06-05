from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _get_optional_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    output_dir: Path
    glob_pattern: str = "*.nop"
    max_workers: int = 8
    vap_bin: str = "vap"
    pdv_bin: str = "pdv"
    vap_timeout_sec: int = 120
    extract_snr: bool = True
    telescope_lat_deg: float | None = None
    telescope_lon_deg: float | None = None
    telescope_height_m: float | None = None

    @property
    def db_path(self) -> Path:
        return self.output_dir / "psrdex.sqlite"

    @property
    def pulsar_dir(self) -> Path:
        return self.output_dir / "pulsars"

    @property
    def observations_csv(self) -> Path:
        return self.output_dir / "observations.csv"

    @property
    def summary_csv(self) -> Path:
        return self.output_dir / "pulsar_summary.csv"

    @property
    def failures_csv(self) -> Path:
        return self.output_dir / "failures.csv"

    def ensure_output_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pulsar_dir.mkdir(parents=True, exist_ok=True)

    def with_overrides(
        self,
        *,
        data_dir: Path | None = None,
        output_dir: Path | None = None,
        glob_pattern: str | None = None,
        max_workers: int | None = None,
        vap_bin: str | None = None,
        pdv_bin: str | None = None,
    ) -> "Settings":
        return replace(
            self,
            data_dir=data_dir or self.data_dir,
            output_dir=output_dir or self.output_dir,
            glob_pattern=glob_pattern or self.glob_pattern,
            max_workers=max_workers or self.max_workers,
            vap_bin=vap_bin or self.vap_bin,
            pdv_bin=pdv_bin or self.pdv_bin,
        )


def load_settings() -> Settings:
    workers_default = min(8, os.cpu_count() or 1)
    return Settings(
        data_dir=Path(os.getenv("PSRDEX_DATA_DIR", "/QNAP/LOFAR/PL611")).expanduser(),
        output_dir=Path(
            os.getenv("PSRDEX_OUTPUT_DIR", "/home/pmarmat/psrdex_catalog")
        ).expanduser().resolve(),
        glob_pattern=os.getenv("PSRDEX_GLOB", "*.nop"),
        max_workers=_get_int("PSRDEX_MAX_WORKERS", workers_default),
        vap_bin=os.getenv("PSRDEX_VAP_BIN", "vap"),
        pdv_bin=os.getenv("PSRDEX_PDV_BIN", "pdv"),
        vap_timeout_sec=_get_int("PSRDEX_VAP_TIMEOUT_SEC", 120),
        extract_snr=_get_bool("PSRDEX_EXTRACT_SNR", True),
        telescope_lat_deg=_get_optional_float("PSRDEX_TELESCOPE_LAT_DEG"),
        telescope_lon_deg=_get_optional_float("PSRDEX_TELESCOPE_LON_DEG"),
        telescope_height_m=_get_optional_float("PSRDEX_TELESCOPE_HEIGHT_M"),
    )
