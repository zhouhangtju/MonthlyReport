from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from collector.orchestration.client import EXPORTS, collect, date_ranges, download_one
from storage.database import connect, has_successful_coverage, initialize


class FakeResponse:
    headers = {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        del chunk_size
        yield b"PK\x03\x04test-workbook"


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


class OrchestrationCollectorTest(unittest.TestCase):
    def add_successful_run(self, database, run_id, start, end):
        with connect(database) as connection:
            connection.execute(
                """INSERT INTO etl_run (
                    run_id, dataset_code, source_system, source_file, file_sha256,
                    period_start, period_end, started_at, finished_at, status,
                    rows_read, rows_failed
                ) VALUES (?, 'orch_opening', '编排', 'fixture.xlsx', 'hash',
                          ?, ?, '2026-09-01T00:00:00+00:00',
                          '2026-09-01T00:01:00+00:00', 'success', 10, 0)""",
                (run_id, start, end),
            )

    def test_date_ranges_are_contiguous_and_inclusive(self):
        self.assertEqual(
            date_ranges("2026-08-01", "2026-08-08", 3),
            [
                ("2026-08-01", "2026-08-03"),
                ("2026-08-04", "2026-08-06"),
                ("2026-08-07", "2026-08-08"),
            ],
        )

    def test_opening_and_install_use_their_original_parameters(self):
        opening = EXPORTS["opening"].params("2026-08-01", "2026-08-03")
        install = EXPORTS["install"].params("2026-08-01", "2026-08-03")
        self.assertEqual(opening["finish_start_time"], "2026-08-01")
        self.assertEqual(opening["finish_end_time"], "2026-08-03")
        self.assertNotIn("service_type", opening)
        self.assertEqual(install["start_time"], "2026-08-01")
        self.assertEqual(install["end_time"], "2026-08-03")
        self.assertEqual(install["service_type"], "ProvInternetLine")
        self.assertEqual(install["order_type"], 2)

    def test_download_validates_and_saves_excel_response(self):
        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession()
            path, downloaded = download_one(
                EXPORTS["opening"],
                "2026-08-01",
                "2026-08-03",
                Path(directory),
                session=session,
            )
            self.assertTrue(downloaded)
            self.assertTrue(path.exists())
            self.assertTrue(path.read_bytes().startswith(b"PK\x03\x04"))
            _, request = session.calls[0]
            self.assertEqual(request["params"]["finish_start_time"], "2026-08-01")

    def test_file_mode_keeps_each_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession()
            result = collect(
                "install",
                "2026-08-01",
                "2026-08-04",
                mode="file",
                output_dir=Path(directory),
                chunk_days=3,
                interval=0,
                session=session,
            )
            self.assertEqual(len(result), 2)
            self.assertEqual(len(session.calls), 2)
            self.assertTrue(all(Path(item["file"]).exists() for item in result))
            self.assertTrue(all(item["etl"] is None for item in result))

    def test_database_coverage_can_be_combined_from_multiple_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"
            initialize(database)
            self.add_successful_run(database, "run1", "2026-08-01", "2026-08-15")
            self.add_successful_run(database, "run2", "2026-08-16", "2026-08-31")
            self.assertTrue(
                has_successful_coverage(database, "orch_opening", "2026-08-01", "2026-08-31")
            )
            self.assertFalse(
                has_successful_coverage(database, "orch_opening", "2026-07-31", "2026-08-31")
            )

    def test_database_mode_skips_an_already_covered_period(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"
            initialize(database)
            self.add_successful_run(database, "run1", "2026-08-01", "2026-08-31")
            session = FakeSession()
            result = collect(
                "opening",
                "2026-08-01",
                "2026-08-31",
                mode="database",
                database=database,
                chunk_days=3,
                interval=0,
                session=session,
            )
            self.assertEqual(len(session.calls), 0)
            self.assertTrue(all(item["skipped"] for item in result))
            self.assertTrue(
                all(item["skip_reason"] == "database_already_covered" for item in result)
            )


if __name__ == "__main__":
    unittest.main()
