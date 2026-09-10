from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.delivery.automatic_dock_preferences import (  # noqa: E402
    AutomaticDockPreferenceStore,
)


class AutomaticDockPreferenceStoreTests(unittest.TestCase):
    def test_missing_defaults_off_and_boolean_round_trip_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AutomaticDockPreferenceStore(Path(directory).resolve())
            self.assertFalse(store.load())
            store.save(True)
            self.assertTrue(store.load())
            store.save(False)
            self.assertFalse(store.load())
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_invalid_value_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "automatic-dock.json").write_text(
                '{"schema_version":1,"enabled":"yes"}\n', encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                AutomaticDockPreferenceStore(root).load()


if __name__ == "__main__":
    unittest.main()
