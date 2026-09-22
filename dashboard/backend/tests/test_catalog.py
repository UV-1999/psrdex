from __future__ import annotations

import csv

from psrdex_api.catalog import CatalogRepository


def test_catalog_reads_csv_when_sqlite_is_absent(tmp_path):
    path = tmp_path / "observations.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["path", "file_name", "pulsar", "mjd", "band", "duration_sec", "snr"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "path": "/data/J0000+0000_2024-01-01_00:00:00.nop",
                "file_name": "J0000+0000_2024-01-01_00:00:00.nop",
                "pulsar": "J0000+0000",
                "mjd": "60310",
                "band": "1b",
                "duration_sec": "120",
                "snr": "42.5",
            }
        )

    repo = CatalogRepository(tmp_path)

    assert repo.overview()["files"] == 1
    assert repo.pulsars()[0]["pulsar"] == "J0000+0000"
    assert repo.band_summary("J0000+0000")[0]["receiver"] == "HBA"
