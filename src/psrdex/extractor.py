from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psrdex.discovery import FileFingerprint

LOGGER = logging.getLogger(__name__)

VAP_FIELDS = [
    "name",
    "ra",
    "dec",
    "stt_date",
    "stt_time",
    "mjd",
    "freq",
    "bw",
    "nsub",
    "nchan",
    "nbin",
    "npol",
    "tbin",
    "tsub",
    "period",
    "dm",
    "dmc",
]

OBSERVATION_COLUMNS = [
    "path",
    "file_name",
    "file_size_bytes",
    "file_mtime_ns",
    "pulsar",
    "datetime_utc",
    "mjd",
    "ra",
    "dec",
    "band",
    "freq_mhz",
    "bandwidth_mhz",
    "nsub",
    "nchan",
    "nbin",
    "npol",
    "tbin_sec",
    "tsub_sec",
    "duration_sec",
    "period_sec",
    "dm",
    "dmc",
    "snr",
    "processed_at_utc",
]

FILENAME_REGEX = re.compile(
    r"(?P<pulsar>J\d+[+-]\d+)_"
    r"(?P<date>\d{4}-\d{2}-\d{2})_"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
)


@dataclass(frozen=True)
class ExtractionResult:
    fingerprint: FileFingerprint
    observation: dict[str, Any] | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.observation is not None and self.error is None


def normalize_empty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.upper() in {"UNDEF", "NAN", "NONE", "NULL"}:
        return None
    return text


def to_float(value: Any) -> float | None:
    value = normalize_empty(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    value = normalize_empty(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def mjd_to_utc(mjd: Any) -> datetime | None:
    mjd_value = to_float(mjd)
    if mjd_value is None:
        return None
    return datetime(1858, 11, 17, tzinfo=UTC) + timedelta(days=mjd_value)


def infer_band(freq_mhz: Any, bw_mhz: Any) -> str:
    freq = to_float(freq_mhz)
    bandwidth = to_float(bw_mhz)
    if freq is None or bandwidth is None:
        return "unknown"

    if 68 <= bandwidth <= 76 and 117 <= freq <= 189:
        return "0b"
    if 34 <= bandwidth <= 40 and 44 <= freq <= 80:
        return "0c"

    if 117 <= freq < 141:
        return "1b"
    if 141 <= freq < 165:
        return "2b"
    if 165 <= freq < 189:
        return "3b"

    if 44 <= freq < 56:
        return "1c"
    if 56 <= freq < 68:
        return "2c"
    if 68 <= freq < 80:
        return "3c"

    return "unknown"


def pulsar_from_filename(path: Path) -> str | None:
    match = FILENAME_REGEX.search(path.name)
    if not match:
        return None
    return match.group("pulsar")


def get_datetime_utc(path: Path, vap: dict[str, Any]) -> str | None:
    match = FILENAME_REGEX.search(path.name)
    if match:
        return f"{match.group('date')}T{match.group('time')}Z"

    date = normalize_empty(vap.get("stt_date"))
    time = normalize_empty(vap.get("stt_time"))
    if date and time:
        return f"{date}T{time}Z"

    mjd_dt = mjd_to_utc(vap.get("mjd"))
    if mjd_dt is not None:
        return mjd_dt.isoformat().replace("+00:00", "Z")

    return None


def compute_tbin(vap: dict[str, Any]) -> float | None:
    tbin = to_float(vap.get("tbin"))
    if tbin is not None:
        return tbin

    period = to_float(vap.get("period"))
    nbin = to_float(vap.get("nbin"))
    if period is not None and nbin is not None and period > 0 and nbin > 0:
        return period / nbin
    return None


def compute_duration_sec(vap: dict[str, Any]) -> float | None:
    nsub = to_float(vap.get("nsub"))
    tsub = to_float(vap.get("tsub"))
    if nsub is not None and tsub is not None and nsub > 0 and tsub > 0:
        return nsub * tsub
    return None


def parse_vap_output(stdout: str) -> dict[str, str] | None:
    for line in stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < len(VAP_FIELDS) + 1:
            continue
        values = parts[1 : len(VAP_FIELDS) + 1]
        return dict(zip(VAP_FIELDS, values, strict=True))
    return None


def run_vap(path: Path, vap_bin: str, timeout_sec: int) -> dict[str, str] | None:
    cmd = [
        vap_bin,
        "-n",
        "-c",
        ",".join(VAP_FIELDS),
        str(path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout_sec,
    )
    return parse_vap_output(result.stdout)


def build_observation(
    fingerprint: FileFingerprint,
    vap: dict[str, Any],
    *,
    processed_at_utc: str | None = None,
) -> dict[str, Any]:
    path = fingerprint.path
    pulsar = normalize_empty(vap.get("name")) or pulsar_from_filename(path) or "unknown"
    processed_at_utc = processed_at_utc or datetime.now(UTC).isoformat().replace("+00:00", "Z")

    return {
        "path": fingerprint.path_str,
        "file_name": path.name,
        "file_size_bytes": fingerprint.size_bytes,
        "file_mtime_ns": fingerprint.mtime_ns,
        "pulsar": pulsar,
        "datetime_utc": get_datetime_utc(path, vap),
        "mjd": to_float(vap.get("mjd")),
        "ra": normalize_empty(vap.get("ra")),
        "dec": normalize_empty(vap.get("dec")),
        "band": infer_band(vap.get("freq"), vap.get("bw")),
        "freq_mhz": to_float(vap.get("freq")),
        "bandwidth_mhz": to_float(vap.get("bw")),
        "nsub": to_int(vap.get("nsub")),
        "nchan": to_int(vap.get("nchan")),
        "nbin": to_int(vap.get("nbin")),
        "npol": to_int(vap.get("npol")),
        "tbin_sec": compute_tbin(vap),
        "tsub_sec": to_float(vap.get("tsub")),
        "duration_sec": compute_duration_sec(vap),
        "period_sec": to_float(vap.get("period")),
        "dm": to_float(vap.get("dm")),
        "dmc": str(normalize_empty(vap.get("dmc")) or "").lower() in {"1", "true", "t", "yes"},
        "snr": None,
        "processed_at_utc": processed_at_utc,
    }


def process_file(
    fingerprint: FileFingerprint,
    *,
    vap_bin: str = "vap",
    timeout_sec: int = 120,
) -> ExtractionResult:
    try:
        vap = run_vap(fingerprint.path, vap_bin=vap_bin, timeout_sec=timeout_sec)
        if vap is None:
            return ExtractionResult(fingerprint, None, "vap returned no parseable metadata")
        observation = build_observation(fingerprint, vap)
        return ExtractionResult(fingerprint, observation)
    except subprocess.TimeoutExpired:
        return ExtractionResult(fingerprint, None, f"vap timed out after {timeout_sec} seconds")
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        message = stderr or f"vap failed with exit code {exc.returncode}"
        LOGGER.debug("vap failed for %s: %s", fingerprint.path, message)
        return ExtractionResult(fingerprint, None, message)
    except Exception as exc:  # noqa: BLE001 - keep batch jobs alive across bad files.
        LOGGER.exception("Unexpected extraction error for %s", fingerprint.path)
        return ExtractionResult(fingerprint, None, str(exc))
