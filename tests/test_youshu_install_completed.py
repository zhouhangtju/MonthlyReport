import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, Mock

from openpyxl import Workbook

from collector.youshu import fetch_install_completed as collector
from storage import youshu_install_completed as storage


class Connection:
    """SQLite transaction harness; production always uses MySQL."""
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql, args=()):
        return self.conn.execute(sql.replace(" FOR UPDATE", ""), args)

    def executemany(self, sql, args):
        return self.conn.executemany(sql, args)

    def __enter__(self):
        return self

    def __exit__(self, typ, exc, tb):
        self.conn.rollback() if typ else self.conn.commit()
        self.conn.close()


class CompletedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.city = self.root / "city.xlsx"
        self.county = self.root / "county.xlsx"
        self.city_rows = [[c, i] for i, c in enumerate(sorted(storage.CITIES), 1)]
        self.county_rows = [[c, "测试区", n] for c, n in self.city_rows]
        self.write_sources()

    def write(self, path, headers, rows):
        wb = Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)
        wb.save(path)
        wb.close()

    def write_sources(self):
        self.write(self.city, ["地市", "装机报结工单量"], self.city_rows + [["总计", 66]])
        self.write(self.county, ["地市", "区县", "装机报结工单量"], self.county_rows + [["总计", None, 66]])

    def db(self):
        path = self.root / "test.sqlite"
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE collection_run (collection_run_id TEXT PRIMARY KEY,
                  dataset_code TEXT,period_start TEXT,period_end TEXT,started_at TEXT,
                  finished_at TEXT,status TEXT,expected_files INTEGER,produced_files INTEGER DEFAULT 0,
                  imported_files INTEGER DEFAULT 0,source_files TEXT,etl_run_ids TEXT,error_message TEXT);
                CREATE TABLE etl_run (run_id TEXT PRIMARY KEY,dataset_code TEXT,source_system TEXT,
                  source_file TEXT,file_sha256 TEXT,period_start TEXT,period_end TEXT,
                  started_at TEXT,finished_at TEXT,status TEXT,rows_read INTEGER,rows_inserted INTEGER);
            """)
            for level in storage.TABLES:
                county = ",county TEXT" if level == "county" else ""
                conn.execute(f"""CREATE TABLE {storage.TABLES[level]} (
                    collection_run_id TEXT,period_start TEXT,period_end TEXT,city TEXT,
                    completed_order_count INTEGER,source_file TEXT,collected_at TEXT{county})""")
        p = patch.object(storage, "connect", side_effect=lambda: Connection(path))
        p.start()
        self.addCleanup(p.stop)
        return path

    def test_parse_and_totals(self):
        parsed = storage.validate_pair(self.city, self.county)
        self.assertEqual(parsed["city"]["total"], 66)
        self.assertEqual(len(parsed["city"]["rows"]), 11)
        self.assertEqual(len(parsed["county"]["rows"]), 11)

    def test_invalid_counts(self):
        for value in (None, True, -1, 1.5, "NaN", "Infinity", "=SUM(A1:A2)", "abc", 2**64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                storage.count_value(value)
        self.assertEqual(storage.count_value(0.0), 0)

    def test_missing_city_rejected(self):
        self.city_rows.pop()
        self.write_sources()
        with self.assertRaisesRegex(ValueError, "11"):
            storage.parse_file(self.city, "city")

    def test_duplicate_rejected(self):
        self.county_rows.append(self.county_rows[0])
        self.write_sources()
        with self.assertRaisesRegex(ValueError, "重复"):
            storage.parse_file(self.county, "county")

    def test_wrong_headers_rejected(self):
        with self.assertRaisesRegex(ValueError, "表头"):
            storage.parse_file(self.city, "county")

    def test_cross_check_rejected(self):
        self.county_rows[0][-1] += 1
        self.county_rows[1][-1] -= 1
        self.write_sources()
        with self.assertRaisesRegex(ValueError, "交叉"):
            storage.validate_pair(self.city, self.county)

    def test_missing_total_rejected(self):
        self.write(self.city, ["地市", "装机报结工单量"], self.city_rows)
        with self.assertRaisesRegex(ValueError, "总计"):
            storage.parse_file(self.city, "city")

    def test_task_filters(self):
        for level, component in collector.COMPONENTS.items():
            task = collector.build_task(level, "http://example.test", "2025-01-01", "2025-07-31")
            self.assertEqual(task["body"]["componentId"], component)
            state = task["setCacheBody"]["data"]["state"]
            date = next(c for c in state["components"] if c["id"] == collector.DATE_COMPONENT)
            self.assertEqual(date["setting"]["data"]["date"]["period"],
                {"minBound": "2025-01-01 00:00:00", "maxBound": "2025-07-31 24:00:00"})
            filters = state["dashboard"]["setting"]["data"]["filter"]["146664"]
            self.assertEqual(filters[0]["filter"]["match"]["isJust"], "1")
            self.assertEqual(filters[1]["filter"]["match"]["leaf"][1]["value"], "企业宽带")

    def test_bad_period(self):
        for start, end in [("2026-02-30", "2026-03-01"), ("2026-09-01", "2026-08-31")]:
            with self.assertRaises(ValueError):
                storage.validate_period(start, end)

    def test_file_only_no_database_and_manifest(self):
        with patch.object(collector, "initialize", side_effect=AssertionError("DB called")):
            result = collector.collect("2026-08-01", "2026-08-31", mode="file",
                city_file=self.city, county_file=self.county, output_dir=self.root / "out")
        manifest = json.loads(Path(result["manifest"]).read_text())
        self.assertEqual(manifest["status"], "success")
        self.assertEqual(manifest["files"]["city"]["platform_total"], 66)
        self.assertEqual(manifest["period_source"], "caller_supplied")

    def test_atomic_insert_idempotency_exact_coverage(self):
        self.db()
        data = storage.validate_pair(self.city, self.county)
        storage.start_run("test", "2026-08-01", "2026-08-31")
        first = storage.import_pair("test", "2026-08-01", "2026-08-31", data)
        self.assertEqual(first, storage.import_pair("test", "2026-08-01", "2026-08-31", data))
        self.assertEqual(storage.latest_success("2026-08-01", "2026-08-31"), "test")
        self.assertIsNone(storage.latest_success("2026-08-01", "2026-08-15"))
        with storage.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM youshu_install_completed_city").fetchone()[0], 11)

    def test_second_table_failure_rolls_back(self):
        path = self.db()
        with sqlite3.connect(path) as conn:
            conn.execute("""CREATE TRIGGER reject_county BEFORE INSERT ON youshu_install_completed_county
                         BEGIN SELECT RAISE(ABORT, 'forced failure'); END""")
        storage.start_run("test", "2026-08-01", "2026-08-31")
        with self.assertRaises(sqlite3.IntegrityError):
            storage.import_pair("test", "2026-08-01", "2026-08-31", storage.validate_pair(self.city, self.county))
        with storage.connect() as conn:
            for table in [*storage.TABLES.values(), "etl_run"]:
                self.assertEqual(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT status FROM collection_run").fetchone()[0], "running")

    def test_failed_validation_audited(self):
        self.db()
        self.county_rows[0][-1] = -1
        self.write_sources()
        with patch.object(collector, "initialize"), self.assertRaises(ValueError):
            collector.collect("2026-08-01", "2026-08-31", mode="both",
                city_file=self.city, county_file=self.county, output_dir=self.root / "out")
        with storage.connect() as conn:
            row = conn.execute("SELECT * FROM collection_run").fetchone()
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["produced_files"], 2)
            self.assertEqual(row["imported_files"], 0)

    def test_refresh_creates_snapshot_skip_avoids_download(self):
        self.db()
        kwargs = dict(city_file=self.city, county_file=self.county, output_dir=self.root / "out")
        with patch.object(collector, "initialize"):
            a = collector.collect("2026-08-01", "2026-08-31", **kwargs)
            b = collector.collect("2026-08-01", "2026-08-31", **kwargs)
            c = collector.collect("2026-08-01", "2026-08-31", refresh=True, **kwargs)
        self.assertTrue(b["skipped"])
        self.assertEqual(b["collection_run_id"], a["collection_run_id"])
        self.assertNotEqual(a["collection_run_id"], c["collection_run_id"])
        self.assertEqual(storage.latest_success("2026-08-01", "2026-08-31"), c["collection_run_id"])
        latest = storage.load_latest("2026-08-01", "2026-08-31")
        self.assertEqual(len(latest["city"]), 11)
        self.assertEqual(latest["collection_run_id"], c["collection_run_id"])

    def test_download_two_components_without_date_splitting(self):
        (self.root / "task_install_completed_38598.json").write_bytes(
            (collector.MODULE / "task_install_completed_38598.json").read_bytes())
        (self.root / "有数配置.json").write_text(json.dumps({"base": "http://example.test", "headers": {}}))
        exporter = Mock()
        exporter.run_export.side_effect = [(str(self.city), "xlsx"), (str(self.county), "xlsx")]
        exporter.is_valid_xlsx.return_value = True
        with patch.object(collector, "MODULE", self.root):
            files = dict(collector.download_pair(self.root, "2026-01-01", "2026-08-31", 120, 600, exporter=exporter))
        self.assertEqual(set(files), {"city", "county"})
        self.assertEqual(exporter.run_export.call_count, 2)
        for call in exporter.run_export.call_args_list:
            self.assertEqual(call.args[4:6], ("2026-01-01", "2026-08-31"))
            self.assertIn(call.args[0]["body"]["componentId"], collector.COMPONENTS.values())

    def test_database_only_cleans_successful_temporary_files(self):
        self.db()
        with patch.object(collector, "initialize"):
            result = collector.collect("2026-08-01", "2026-08-31", mode="database",
                city_file=self.city, county_file=self.county)
        self.assertEqual(result["files"], {})
        with storage.connect() as conn:
            source = conn.execute("SELECT source_file FROM etl_run LIMIT 1").fetchone()[0]
        self.assertFalse(Path(source).exists())

    def test_second_download_failure_not_covered(self):
        self.db()
        def failing_download(*args):
            yield "city", self.city
            raise RuntimeError("county export failed")
        with patch.object(collector, "initialize"), patch.object(collector, "download_pair", failing_download):
            with self.assertRaisesRegex(RuntimeError, "county"):
                collector.collect("2026-08-01", "2026-08-31", output_dir=self.root / "out")
        self.assertIsNone(storage.latest_success("2026-08-01", "2026-08-31"))
        with storage.connect() as conn:
            row = conn.execute("SELECT * FROM collection_run").fetchone()
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["produced_files"], 1)

    def test_success_batch_cannot_change_source(self):
        self.db()
        data = storage.validate_pair(self.city, self.county)
        storage.start_run("test", "2026-08-01", "2026-08-31")
        storage.import_pair("test", "2026-08-01", "2026-08-31", data)
        data["city"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "不可替换"):
            storage.import_pair("test", "2026-08-01", "2026-08-31", data)


if __name__ == "__main__":
    unittest.main()
