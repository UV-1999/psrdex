from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .catalog import CatalogRepository
from .config import load_api_settings
from .jobs import (
    PsrismRequest,
    build_psrism_command,
    launch_psrism,
    list_runs,
    run_detail,
    safe_run_file,
)

settings = load_api_settings()
app = FastAPI(title="PSRDEX API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def repo() -> CatalogRepository:
    return CatalogRepository(settings.output_dir)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "output_dir": str(settings.output_dir)}


@app.get("/api/catalog/overview")
def catalog_overview() -> dict[str, object]:
    return repo().overview()


@app.get("/api/catalog/pulsars")
def catalog_pulsars() -> list[dict[str, object]]:
    return repo().pulsars()


@app.get("/api/catalog/pulsars/{pulsar}/observations")
def pulsar_observations(
    pulsar: str,
    bands: list[str] | None = Query(default=None),
) -> dict[str, object]:
    observations = repo().observations_for_pulsar(pulsar)
    if bands:
        selected = set(bands)
        observations = [row for row in observations if str(row.get("band")) in selected]
    return {
        "pulsar": pulsar,
        "observations": observations,
        "band_summary": repo().band_summary(pulsar, bands),
    }


@app.post("/api/catalog/update")
def update_catalog(background_tasks: BackgroundTasks, force: bool = False) -> dict[str, str]:
    cmd = [
        "psrdex-update",
        "--data-dir",
        str(settings.data_dir),
        "--output-dir",
        str(settings.output_dir),
        "--glob",
        settings.glob_pattern,
        "update",
    ]
    if force:
        cmd.append("--force")
    log_path = settings.output_dir / "react_background_update.log"
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    background_tasks.add_task(_run_update, cmd, log_path)
    return {"status": "started", "log": str(log_path)}


@app.get("/api/psrism/runs")
def psrism_runs() -> list[dict[str, object]]:
    return list_runs(settings)


@app.get("/api/psrism/runs/{run_id}")
def psrism_run(run_id: str) -> dict[str, object]:
    try:
        return run_detail(settings, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="PSRISM run not found") from exc


@app.get("/api/psrism/runs/{run_id}/files/{relative_path:path}")
def psrism_run_file(run_id: str, relative_path: str) -> FileResponse:
    try:
        return FileResponse(safe_run_file(settings, run_id, relative_path))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="PSRISM file not found") from exc


@app.post("/api/psrism/runs")
def create_psrism_run(request: PsrismRequest) -> dict[str, str]:
    try:
        build_psrism_command(settings.psrism_bin, Path("."), request)
        return launch_psrism(settings, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _run_update(cmd: list[str], log_path: Path) -> None:
    with log_path.open("a") as log:
        subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=False)
