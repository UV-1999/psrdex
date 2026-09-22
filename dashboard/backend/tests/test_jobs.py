from __future__ import annotations

from pathlib import Path

from psrdex_api.config import ApiSettings
from psrdex_api.jobs import PsrismRequest, build_psrism_command, discover_run_files, safe_run_file


def test_build_psrism_command_whitelists_products():
    request = PsrismRequest(
        archive_paths=[Path("/data/a.nop")],
        products=["dspec", "fit_tau"],
        nchan=64,
        tau_subbands=4,
    )

    assert build_psrism_command("psrism", Path("/data/a.nop"), request) == [
        "psrism",
        "/data/a.nop",
        "--dspec",
        "--fit-tau",
        "--nchan",
        "64",
        "--tau-subbands",
        "4",
    ]


def test_discover_run_files_recurses_into_psrism_output_dirs(tmp_path):
    output_dir = tmp_path / "catalog"
    run_dir = output_dir / "psrism_runs" / "run-1"
    nested = run_dir / "J0000+0000"
    nested.mkdir(parents=True)
    (nested / "plot.png").write_bytes(b"png")
    (nested / "table.csv").write_text("x,y\n1,2\n")
    (run_dir / "pid").write_text("123")

    files = discover_run_files(run_dir)

    assert [file["path"] for file in files] == [
        "J0000+0000/plot.png",
        "J0000+0000/table.csv",
    ]


def test_safe_run_file_blocks_path_escape(tmp_path):
    output_dir = tmp_path / "catalog"
    run_dir = output_dir / "psrism_runs" / "run-1"
    run_dir.mkdir(parents=True)
    settings = ApiSettings(
        output_dir=output_dir,
        data_dir=tmp_path,
        glob_pattern="*.nop",
        psrism_bin="psrism",
        cors_origins=(),
    )

    try:
        safe_run_file(settings, "run-1", "../secret.txt")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("path escape should not be allowed")
