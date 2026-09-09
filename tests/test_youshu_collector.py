from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collector.youshu.client import (
    DATA_CONFIG,
    FETCH_SCRIPT,
    LOGIN_SCRIPT,
    collect,
    expected_file_count,
)
from storage.database import connect, initialize


class YoushuCollectorTest(unittest.TestCase):
    def test_required_runtime_files_exist(self):
        self.assertTrue(FETCH_SCRIPT.exists())
        self.assertTrue(LOGIN_SCRIPT.exists())
        self.assertTrue(DATA_CONFIG.exists())

    def test_expected_file_count_matches_export_shapes(self):
        self.assertEqual(expected_file_count("install", "2026-08-01", "2026-08-08", 3), 33)
        self.assertEqual(expected_file_count("complaint", "2026-08-01", "2026-08-08", 3), 3)

    def test_existing_complete_collection_skips_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"
            initialize(database)
            with connect(database) as connection:
                connection.execute(
                    """INSERT INTO collection_run (
                        collection_run_id, dataset_code, period_start, period_end,
                        started_at, finished_at, status, expected_files,
                        produced_files, imported_files
                    ) VALUES ('c1', 'youshu_install', '2026-08-01', '2026-08-31',
                              '2026-09-01', '2026-09-01', 'success', 121, 121, 121)"""
                )
            with patch("collector.youshu.client.run_fetch") as fetch:
                result = collect(
                    "install", "2026-08-01", "2026-08-31",
                    mode="database", database=database,
                )
            fetch.assert_not_called()
            self.assertTrue(result["skipped"])
            self.assertEqual(result["skip_reason"], "database_already_covered")

    def test_incomplete_file_set_marks_collection_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"
            output = Path(directory) / "raw"
            with patch(
                "collector.youshu.client.run_fetch",
                side_effect=RuntimeError("有数取数文件不完整"),
            ):
                with self.assertRaisesRegex(RuntimeError, "文件不完整"):
                    collect(
                        "complaint", "2026-08-01", "2026-08-03",
                        mode="both", database=database, output_dir=output,
                    )
            with connect(database) as connection:
                row = connection.execute("SELECT status FROM collection_run").fetchone()
            self.assertEqual(row["status"], "failed")


if __name__ == "__main__":
    unittest.main()
