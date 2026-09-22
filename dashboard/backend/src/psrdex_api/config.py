from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApiSettings:
    output_dir: Path
    data_dir: Path
    glob_pattern: str
    psrism_bin: str
    cors_origins: tuple[str, ...]

    @property
    def db_path(self) -> Path:
        return self.output_dir / "psrdex.sqlite"

    @property
    def psrism_runs_dir(self) -> Path:
        return self.output_dir / "psrism_runs"


def _origins() -> tuple[str, ...]:
    raw = os.getenv("PSRDEX_API_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())


def load_api_settings() -> ApiSettings:
    return ApiSettings(
        output_dir=Path(os.getenv("PSRDEX_OUTPUT_DIR", "/home/pmarmat/psrdex_catalog"))
        .expanduser()
        .resolve(),
        data_dir=Path(os.getenv("PSRDEX_DATA_DIR", "/QNAP/LOFAR/PL611")).expanduser(),
        glob_pattern=os.getenv("PSRDEX_GLOB", "*.nop"),
        psrism_bin=os.getenv("PSRDEX_PSRISM_BIN", "psrism"),
        cors_origins=_origins(),
    )
