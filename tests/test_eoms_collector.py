from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collector.eoms.client import CRAWL_SCRIPT, LOGIN_SCRIPT, collect
from collector.eoms.transform import fill_missing_account_with_phone
from storage.database import connect, initialize


class EomsCollectorTest(unittest.TestCase):
    def test_phone_only_fills_missing_billing_account(self):
        rows = [
            {"accountCode": "e55123", "jtPhone": "13800000001"},
            {"accountCode": "", "jtPhone": "13800000002"},
            {"accountCode": None, "jtPhone": "13800000003"},
            {"accountCode": "无", "jtPhone": "13800000004"},
            {"accountCode": "", "jtPhone": ""},
        ]
        result = fill_missing_account_with_phone(rows)
        self.assertEqual(result[0]["accountCode"], "e55123")
        self.assertNotIn("accountCodeFillSource", result[0])
        self.assertEqual(result[1]["accountCode"], "13800000002")
        self.assertEqual(result[2]["accountCode"], "13800000003")
        self.assertEqual(result[3]["accountCode"], "13800000004")
        self.assertEqual(result[1]["accountCodeFillSource"], "手机号码补位")
        self.assertEqual(result[4]["accountCode"], "")

    def test_runtime_scripts_are_local(self):
        self.assertTrue(LOGIN_SCRIPT.is_file())
        self.assertTrue(CRAWL_SCRIPT.is_file())
        self.assertIn("collector/eoms", LOGIN_SCRIPT.as_posix())
        self.assertNotIn("/export/", LOGIN_SCRIPT.as_posix())

    def test_complete_database_period_skips_login_and_crawl(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"
            initialize(database)
            with connect(database) as connection:
                connection.execute(
                    """INSERT INTO etl_run (
                        run_id, dataset_code, source_system, source_file, file_sha256,
                        period_start, period_end, started_at, finished_at, status, rows_failed
                    ) VALUES ('e1', 'eoms_complaint', 'EOMS', 'sample.xlsx', 'hash',
                              '2026-08-01', '2026-08-31', '2026-09-01', '2026-09-01',
                              'success', 0)"""
                )
            with patch("collector.eoms.client.refresh_login") as login, patch(
                "collector.eoms.client.run_crawl"
            ) as crawl:
                result = collect(
                    "2026-08-01", "2026-08-31", mode="database", database=database
                )
            login.assert_not_called()
            crawl.assert_not_called()
            self.assertTrue(result["skipped"])

    def test_database_mode_uses_temporary_file_and_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"

            def fake_crawl(start, end, output, **kwargs):
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"PK\x03\x04sample")
                return output

            with patch("collector.eoms.client.run_crawl", side_effect=fake_crawl), patch(
                "collector.eoms.client.import_file", return_value={"run_id": "etl1"}
            ) as importer:
                result = collect(
                    "2026-08-01", "2026-08-31", mode="database", database=database
                )
            importer.assert_called_once()
            self.assertIsNone(result["file"])
            self.assertEqual(result["etl"]["run_id"], "etl1")


if __name__ == "__main__":
    unittest.main()
