from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import ApiSettings

UTC = timezone.utc

PSRISM_FLAGS = {
    "inspect": "--inspect",
    "dspec": "--dspec",
    "acspec": "--acspec",
    "zoom_acf": "--zoom-acf",
    "sspec": "--sspec",
    "fit_arc": "--fit-arc",
    "intpf": "--intpf",
    "fit_tau": "--fit-tau",
    "fit_alpha": "--fit-alpha",
    "fit_anisotropy": "--fit-anisotropy",
    "estimate_refractive": "--estimate-refractive",
}


class PsrismRequest(BaseModel):
    archive_paths: list[Path] = Field(min_length=1)
    products: list[str] = Field(default_factory=list)
    nsub: int | None = Field(default=None, ge=1)
    nchan: int | None = Field(default=None, ge=1)
    nbin: int | None = Field(default=None, ge=1)
    tau_subbands: int | None = Field(default=None, ge=1)
    distance_kpc: float | None = Field(default=None, gt=0)
    velocity_kms: float | None = Field(default=None, gt=0)
    time_params: str | None = None


def launch_psrism(settings: ApiSettings, request: PsrismRequest) -> dict[str, str]:
    settings.psrism_runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = settings.psrism_runs_dir / run_id
    run_dir.mkdir()

    target = _prepare_target(run_dir, request.archive_paths)
    cmd = build_psrism_command(settings.psrism_bin, target, request)
    metadata = {
        "run_id": run_id,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "archive_paths": [str(path) for path in request.archive_paths],
        "command": cmd,
        "options": request.model_dump(mode="json"),
    }
    (run_dir / "run.json").write_text(json.dumps(metadata, indent=2))
    log = (run_dir / "terminal_output.log").open("w")
    proc = subprocess.Popen(
        cmd,
        cwd=run_dir,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log.close()
    (run_dir / "pid").write_text(str(proc.pid))
    return {"run_id": run_id, "status": "running", "run_dir": str(run_dir)}


def build_psrism_command(psrism_bin: str, target: Path, request: PsrismRequest) -> list[str]:
    cmd = [psrism_bin, str(target)]
    for product in request.products:
        if product not in PSRISM_FLAGS:
            raise ValueError(f"Unsupported PSRISM product: {product}")
        cmd.append(PSRISM_FLAGS[product])
    for option, value in [
        ("--nsub", request.nsub),
        ("--nchan", request.nchan),
        ("--nbin", request.nbin),
        ("--tau-subbands", request.tau_subbands),
        ("--distance-kpc", request.distance_kpc),
        ("--velocity-kms", request.velocity_kms),
    ]:
        if value is not None:
            cmd.extend([option, str(value)])
    if request.time_params:
        allowed = {"dm", "tau", "alpha", "dnu_d", "dt_d", "t_r", "all"}
        if request.time_params not in allowed:
            raise ValueError(f"Unsupported time parameter: {request.time_params}")
        cmd.extend(["--time-params", request.time_params])
    return cmd


def list_runs(settings: ApiSettings) -> list[dict[str, Any]]:
    if not settings.psrism_runs_dir.exists():
        return []
    runs = []
    for run_dir in sorted(settings.psrism_runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        runs.append(run_detail(settings, run_dir.name, include_log=False))
    return runs


def run_detail(settings: ApiSettings, run_id: str, *, include_log: bool = True) -> dict[str, Any]:
    run_dir = safe_run_dir(settings, run_id)
    metadata_path = run_dir / "run.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    status = _status_from_pid(run_dir)
    files = discover_run_files(run_dir)
    detail: dict[str, Any] = {
        **metadata,
        "run_id": run_dir.name,
        "status": status,
        "files": files,
        "products": [file["path"] for file in files],
    }
    if include_log:
        detail["log_tail"] = read_log_tail(run_dir / "terminal_output.log")
    return detail


def discover_run_files(run_dir: Path) -> list[dict[str, Any]]:
    result = []
    allowed_suffixes = {".png", ".jpg", ".jpeg", ".csv", ".txt", ".log", ".json"}
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == "pid" or path.suffix.lower() not in allowed_suffixes:
            continue
        relative = path.relative_to(run_dir).as_posix()
        result.append(
            {
                "path": relative,
                "name": path.name,
                "kind": file_kind(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return result


def file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg"}:
        return "image"
    if suffix == ".csv":
        return "table"
    if suffix in {".log", ".txt"}:
        return "text"
    return "metadata"


def safe_run_dir(settings: ApiSettings, run_id: str) -> Path:
    base = settings.psrism_runs_dir.resolve()
    run_dir = (base / run_id).resolve()
    if base not in run_dir.parents or not run_dir.is_dir():
        raise FileNotFoundError(run_id)
    return run_dir


def safe_run_file(settings: ApiSettings, run_id: str, relative_path: str) -> Path:
    run_dir = safe_run_dir(settings, run_id)
    path = (run_dir / relative_path).resolve()
    if run_dir not in path.parents or not path.is_file():
        raise FileNotFoundError(relative_path)
    return path


def read_log_tail(path: Path, *, limit: int = 12000) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    return data[-limit:].decode(errors="replace")


def _prepare_target(run_dir: Path, archive_paths: list[Path]) -> Path:
    if len(archive_paths) == 1:
        return archive_paths[0]
    selected_dir = run_dir / "selected_archives"
    selected_dir.mkdir()
    for archive in archive_paths:
        link = selected_dir / archive.name
        try:
            link.symlink_to(archive)
        except OSError:
            shutil.copy2(archive, link)
    return selected_dir


def _status_from_pid(run_dir: Path) -> str:
    pid_path = run_dir / "pid"
    if not pid_path.exists():
        return "unknown"
    try:
        pid = int(pid_path.read_text().strip())
        subprocess.run(["kill", "-0", str(pid)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "running"
    except (ValueError, subprocess.CalledProcessError):
        return "finished"
