from __future__ import annotations

import unittest
from datetime import timezone
from pathlib import Path

from psrdex.discovery import FileFingerprint
from psrdex.extractor import build_observation, compute_tbin, get_datetime_utc, infer_band, mjd_to_utc

UTC = timezone.utc


class ExtractorTests(unittest.TestCase):
    def test_infer_band_combined_and_single_subbands(self) -> None:
        self.assertEqual(infer_band(150, 72), "0b")
        self.assertEqual(infer_band(60, 36), "0c")
        self.assertEqual(infer_band(120, 24), "1b")
        self.assertEqual(infer_band(150, 24), "2b")
        self.assertEqual(infer_band(170, 24), "3b")
        self.assertEqual(infer_band(48, 12), "1c")
        self.assertEqual(infer_band(62, 12), "2c")
        self.assertEqual(infer_band(72, 12), "3c")
        self.assertEqual(infer_band(None, 12), "unknown")

    def test_datetime_prefers_filename(self) -> None:
        path = Path("/tmp/J1234+5678_2025-01-02_03:04:05_test.nop")
        self.assertEqual(
            get_datetime_utc(path, {"stt_date": "2024-01-01", "stt_time": "00:00:00"}),
            "2025-01-02T03:04:05Z",
        )

    def test_mjd_to_utc_epoch(self) -> None:
        dt = mjd_to_utc(0)
        self.assertIsNotNone(dt)
        assert dt is not None
        self.assertEqual(dt.year, 1858)
        self.assertEqual(dt.month, 11)
        self.assertEqual(dt.day, 17)
        self.assertEqual(dt.tzinfo, UTC)

    def test_compute_tbin_falls_back_to_period_over_bins(self) -> None:
        self.assertEqual(
            compute_tbin({"tbin": "UNDEF", "period": "1.0", "nbin": "1024"}),
            1.0 / 1024,
        )

    def test_build_observation_uses_filename_pulsar_fallback(self) -> None:
        fp = FileFingerprint(Path("/tmp/J1234+5678_2025-01-02_03:04:05_test.nop"), 12, 34)
        row = build_observation(
            fp,
            {
                "name": "UNDEF",
                "ra": "12:34:00",
                "dec": "+56:00:00",
                "mjd": "60000",
                "freq": "150",
                "bw": "72",
                "nsub": "10",
                "tsub": "5",
                "dmc": "1",
            },
            processed_at_utc="2026-01-01T00:00:00Z",
        )
        self.assertEqual(row["pulsar"], "J1234+5678")
        self.assertEqual(row["band"], "0b")
        self.assertEqual(row["duration_sec"], 50)
        self.assertIs(row["dmc"], True)


if __name__ == "__main__":
    unittest.main()
