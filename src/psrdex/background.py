from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from psrdex.config import Settings

UTC = timezone.utc


def enabled(value: str | None, *, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(lock_path: Path) -> int | None:
    if not lock_path.exists():
        return None
    try:
        text = lock_path.read_text().strip()
        return int(text.splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None


def maybe_start_background_update(
    settings: Settings,
    output_dir: Path,
    *,
    pythonpath_prefix: Path | None = None,
    cwd: Path | None = None,
) -> str:
    if not enabled(os.getenv("PSRDEX_APP_BACKGROUND_UPDATE"), default=True):
        return "disabled"

    output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir / ".psrdex-update.pid"
    log_path = output_dir / "background_update.log"
    cooldown_sec = int(os.getenv("PSRDEX_APP_UPDATE_COOLDOWN_SEC", "3600"))

    pid = read_lock(lock_path)
    if pid is not None and pid_is_running(pid):
        return f"running:{pid}"
    if lock_path.exists() and cooldown_sec > 0:
        age_sec = time.time() - lock_path.stat().st_mtime
        if age_sec < cooldown_sec:
            return f"recent:{int(cooldown_sec - age_sec)}s"

    env = os.environ.copy()
    if pythonpath_prefix is not None:
        env["PYTHONPATH"] = (
            str(pythonpath_prefix)
            if not env.get("PYTHONPATH")
            else f"{pythonpath_prefix}{os.pathsep}{env['PYTHONPATH']}"
        )

    cmd = [
        sys.executable,
        "-m",
        "psrdex.cli",
        "--data-dir",
        str(settings.data_dir),
        "--output-dir",
        str(output_dir),
        "--glob",
        settings.glob_pattern,
        "--workers",
        str(settings.max_workers),
        "--vap-bin",
        settings.vap_bin,
        "--pdv-bin",
        settings.pdv_bin,
        "update",
    ]

    try:
        with log_path.open("a") as log_handle:
            log_handle.write(f"\n[{datetime.now(UTC).isoformat()}] starting {' '.join(cmd)}\n")
            log_handle.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd) if cwd is not None else None,
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        lock_path.write_text(f"{proc.pid}\n")
        return f"started:{proc.pid}"
    except OSError as exc:
        return f"failed:{exc}"
