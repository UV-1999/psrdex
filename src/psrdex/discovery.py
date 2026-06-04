from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileFingerprint:
    path: Path
    size_bytes: int
    mtime_ns: int

    @property
    def path_str(self) -> str:
        return str(self.path)


def fingerprint(path: Path) -> FileFingerprint:
    stat = path.stat()
    return FileFingerprint(
        path=path.resolve(),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def discover_files(data_dir: Path, glob_pattern: str) -> list[FileFingerprint]:
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory does not exist: {data_dir}")
    if not data_dir.is_dir():
        raise NotADirectoryError(f"Data path is not a directory: {data_dir}")

    files = (path for path in data_dir.rglob(glob_pattern) if path.is_file())
    return sorted((fingerprint(path) for path in files), key=lambda item: item.path_str)
