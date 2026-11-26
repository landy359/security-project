import json
from pathlib import Path
import sys
import tempfile
import unittest

from monitor.catalog import catalog
from monitor.target import ManagedProcess


class CatalogTests(unittest.TestCase):
    def test_registered_argv_runs_without_modification_and_profiles_versioned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            record = {
                "id": "sleeper",
                "label": "Worker",
                "startup_seconds": 0,
                "argv": [sys.executable, "-c", "import time; time.sleep(10)"],
            }
            path.write_text(json.dumps([record]))
            first = catalog(path)["sleeper"]
            proc = ManagedProcess(first)
            try:
                self.assertTrue(proc.alive())
                self.assertTrue(proc.initialized())
                self.assertIsNone(proc.ready_fd)
            finally:
                proc.close()
            self.assertFalse(proc.alive())
            record["label"] = "Renamed"
            path.write_text(json.dumps([record]))
            self.assertEqual(catalog(path)["sleeper"].namespace, first.namespace)
            record["argv"][-1] = "import time; time.sleep(5)"
            path.write_text(json.dumps([record]))
            self.assertNotEqual(catalog(path)["sleeper"].namespace, first.namespace)

    def test_invalid_catalog_is_rejected_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "targets.json"
            valid = {"id": "worker", "label": "Worker", "argv": [sys.executable]}
            for records in (
                [valid, valid],
                [{**valid, "id": "viewer"}],
                [{**valid, "argv": ["relative"]}],
                [{**valid, "startup_seconds": -1}],
            ):
                with self.subTest(records=records):
                    path.write_text(json.dumps(records))
                    with self.assertRaises(ValueError):
                        catalog(path)
