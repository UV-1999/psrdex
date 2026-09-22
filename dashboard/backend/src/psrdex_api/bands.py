from __future__ import annotations

from typing import Any

BAND_INFO: dict[str, dict[str, Any]] = {
    "1b": {"label": "lane1b", "receiver": "HBA", "center_mhz": 129, "range_mhz": "117-141"},
    "2b": {"label": "lane2b", "receiver": "HBA", "center_mhz": 153, "range_mhz": "141-165"},
    "3b": {"label": "lane3b", "receiver": "HBA", "center_mhz": 177, "range_mhz": "165-189"},
    "0b": {"label": "lane0b", "receiver": "HBA", "center_mhz": None, "range_mhz": "117-189"},
    "1c": {"label": "lane1c", "receiver": "LBA", "center_mhz": 50, "range_mhz": "44-56"},
    "2c": {"label": "lane2c", "receiver": "LBA", "center_mhz": 62, "range_mhz": "56-68"},
    "3c": {"label": "lane3c", "receiver": "LBA", "center_mhz": 74, "range_mhz": "68-80"},
    "0c": {"label": "lane0c", "receiver": "LBA", "center_mhz": None, "range_mhz": "44-80"},
}

_BAND_ORDER = {"0b": 0, "1b": 1, "2b": 2, "3b": 3, "0c": 4, "1c": 5, "2c": 6, "3c": 7}


def band_sort_key(band: str) -> tuple[int, str]:
    return (_BAND_ORDER.get(str(band), 99), str(band))


def band_label(band: str | None) -> str:
    if band is None:
        return ""
    info = BAND_INFO.get(str(band))
    if info is None:
        return str(band)
    center = "combined" if info["center_mhz"] is None else f"{info['center_mhz']} MHz"
    return f"{info['label']} {info['receiver']} {center} ({info['range_mhz']} MHz)"
