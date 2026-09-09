from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from collector.integration.client import collect, download_one, request_body
from storage.database import connect, initialize


class FakeResponse:
    status_code = 200
    content = b"PK\x03\x04integration-workbook"
    headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


class IntegrationCollectorTest(unittest.TestCase):
    def add_successful_run(self, database: Path, start: str, end: str) -> None:
        with connect(database) as connection:
            connection.execute(
                """INSERT INTO etl_run (
                    run_id, dataset_code, source_system, source_file, file_sha256,
                    period_start, period_end, started_at, finished_at, status,
                    rows_read, rows_failed
                ) VALUES ('integration_run', 'integration_opening', '一体化',
                          'fixture.xlsx', 'hash', ?, ?,
                          '2026-09-01T00:00:00+00:00',
                          '2026-09-01T00:01:00+00:00', 'success', 10, 0)""",
                (start, end),
            )

    def test_request_body_preserves_confirmed_filters(self):
        body = request_body("2026-08-01", "2026-08-31")
        self.assertEqual(body["endTimeStart"], "2026-08-01 00:00:00")
        self.assertEqual(body["endTimeEnd"], "2026-08-31 23:59:59")
        self.assertEqual(body["ordertypeList"], ["开通"])
        self.assertEqual(body["dataSources"], "二编")
        self.assertEqual(body["statusList"], [])
        self.assertEqual(body["serviceType"], [])
        self.assertEqual(len(body["headers"]), 29)
        self.assertEqual(len(body["headerEns"]), 29)

    def test_download_writes_excel_and_sends_token_headers_via_session(self):
        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession()
            path, downloaded = download_one(
                "2026-08-01",
                "2026-08-31",
                Path(directory),
                "token",
                session=session,
            )
            self.assertTrue(downloaded)
            self.assertTrue(path.exists())
            self.assertEqual(len(session.calls), 1)
            _, request = session.calls[0]
            self.assertEqual(request["json"]["dataSources"], "二编")

    def test_database_coverage_skips_login_and_network(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"
            initialize(database)
            self.add_successful_run(database, "2026-08-01", "2026-08-31")
            session = FakeSession()
            result = collect(
                "2026-08-01",
                "2026-08-31",
                mode="database",
                database=database,
                session=session,
            )
            self.assertTrue(result["skipped"])
            self.assertEqual(result["skip_reason"], "database_already_covered")
            self.assertEqual(len(session.calls), 0)

    def test_file_mode_uses_explicit_token_without_login(self):
        with tempfile.TemporaryDirectory() as directory:
            session = FakeSession()
            result = collect(
                "2026-08-01",
                "2026-08-31",
                mode="file",
                output_dir=Path(directory),
                token="token",
                session=session,
            )
            self.assertFalse(result["skipped"])
            self.assertTrue(Path(result["file"]).exists())


if __name__ == "__main__":
    unittest.main()
