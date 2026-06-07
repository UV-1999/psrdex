from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

try:
    from streamlit_app import re_split_angle
except ModuleNotFoundError as exc:  # pragma: no cover - allows lean pipeline-only envs.
    re_split_angle = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class StreamlitAppTests(unittest.TestCase):
    def test_re_split_angle_validates_without_display_expression(self) -> None:
        if re_split_angle is None:
            self.skipTest(f"streamlit app dependencies unavailable: {IMPORT_ERROR}")

        self.assertEqual(re_split_angle("06:08:46.136"), ["06", "08", "46.136"])
        self.assertEqual(re_split_angle("not-an-angle"), [])


if __name__ == "__main__":
    unittest.main()
