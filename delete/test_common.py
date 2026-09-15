"""Tests use disposable SQLite fixtures only."""

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from .common import DEPENDENCIES, GROUPS, execute


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "test.db"
        self.source = self.root / "source.csv"
        self.source.write_text("id\n1\n", encoding="utf-8")
        with sqlite3.connect(self.db) as conn:
            conn.executescript((Path(__file__).resolve().parents[1] / "sql/schema.sql").read_text(encoding="utf-8"))
            conn.execute("""INSERT INTO etl_run
                (run_id,dataset_code,source_system,source_file,file_sha256,period_start,period_end,
                started_at,finished_at,status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                ("r", "integration_opening", "integration", str(self.source),
                 hashlib.sha256(self.source.read_bytes()).hexdigest(), "2026-08-01", "2026-08-31",
                 "2026-09-01", "2026-09-02", "success"))
            conn.execute("""INSERT INTO raw_source_record VALUES
                (1,'integration_opening','integration','1','{}','hash','r','r','2026-09-01','2026-09-01')""")
            conn.execute("INSERT INTO raw_source_record_version VALUES (1,1,'r','hash','{}','2026-09-01')")
            conn.execute("""INSERT INTO metric_run VALUES
                ('m','dedicated_line_opening_withdrawal_rate','1','2026-08-01','2026-08-31',
                 '2026-09-03','2026-09-04','success',?,NULL)""", (json.dumps(["r"]),))
            conn.execute("INSERT INTO ads_metric_result VALUES (1,'m','metric','province','{}',1,1,1)")
            conn.execute("""INSERT INTO ads_metric_detail VALUES
                (1,'m','metric','numerator','integration_opening','1','{}','{}')""")

    def run_delete(self, **kwargs):
        return execute(self.db, "integration_opening", "2026-08-01", "2026-08-31", **kwargs)

    def count(self, table):
        with sqlite3.connect(self.db) as conn:
            return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_preview_and_apply(self):
        before = self.db.read_bytes()
        self.assertFalse(self.run_delete()["blockers"])
        self.assertEqual(before, self.db.read_bytes())
        result = self.run_delete(apply=True)
        self.assertTrue(result["applied"])
        for table in ("raw_source_record", "raw_source_record_version", "ads_metric_detail"):
            self.assertEqual(self.count(table), 0)
        for table in ("etl_run", "metric_run", "ads_metric_result", "data_retention_purge"):
            self.assertEqual(self.count(table), 1)
        self.assertTrue(self.source.exists())
        self.assertFalse(result["backup_created"])
        self.assertFalse(self.run_delete(apply=True)["applied"])

    def test_missing_source_blocks(self):
        self.source.unlink()
        self.assertTrue(self.run_delete(apply=True)["blockers"])
        self.assertEqual(self.count("raw_source_record"), 1)

    def test_missing_result_blocks(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("DELETE FROM ads_metric_result")
        self.assertTrue(self.run_delete(apply=True)["blockers"])

    def test_bad_selection_blocks(self):
        self.assertTrue(self.run_delete(run_ids=["unknown"])["blockers"])
        result = execute(self.db, "integration_opening", "2026-08-02", "2026-08-31", apply=True)
        self.assertTrue(result["blockers"])

    def test_rollback(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("""CREATE TRIGGER reject_delete BEFORE DELETE ON raw_source_record
                BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.run_delete(apply=True)
        self.assertEqual(self.count("raw_source_record_version"), 1)
        self.assertEqual(self.count("ads_metric_detail"), 1)
        self.assertEqual(self.count("data_retention_purge"), 0)

    def test_running_and_bad_hash_block(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE metric_run SET status='running'")
        self.assertTrue(self.run_delete(apply=True)["blockers"])
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE metric_run SET status='success'")
        self.source.write_text("changed", encoding="utf-8")
        self.assertTrue(self.run_delete(apply=True)["blockers"])

    def test_shared_record_blocks(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute("""INSERT INTO etl_run SELECT 'older', dataset_code,source_system,
                source_file,archived_file,file_sha256,period_start,period_end,started_at,
                finished_at,status,rows_read,rows_inserted,rows_updated,rows_unchanged,
                rows_failed,error_message FROM etl_run WHERE run_id='r'""")
            conn.execute("UPDATE raw_source_record SET first_run_id='older'")
        self.assertTrue(self.run_delete(run_ids=["r"], apply=True)["blockers"])
        self.assertEqual(self.count("raw_source_record"), 1)

    def test_missing_database_not_created(self):
        missing = self.root / "missing.db"
        with self.assertRaises(sqlite3.OperationalError):
            execute(missing, "integration_opening", "2026-08-01", "2026-08-31")
        self.assertFalse(missing.exists())

    def test_all_eight_groups_preserve_results_and_old_opening(self):
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""
                DELETE FROM ads_metric_detail; DELETE FROM ads_metric_result;
                DELETE FROM metric_run; DELETE FROM raw_source_record_version;
                DELETE FROM raw_source_record; DELETE FROM etl_run;
                CREATE TABLE tr_source_snapshot (snapshot_id TEXT PRIMARY KEY,
                    dataset_code TEXT, etl_run_id TEXT, workbook BLOB);
                CREATE TABLE tr_source_row (snapshot_id TEXT REFERENCES tr_source_snapshot,
                    row_number INTEGER, cells_json TEXT);
            """)
            codes = [code for group in GROUPS.values() for code in group] + ["orch_opening"]
            for i, code in enumerate(codes, 1):
                conn.execute("""INSERT INTO etl_run
                    (run_id,dataset_code,source_system,source_file,file_sha256,period_start,
                    period_end,started_at,finished_at,status) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (code, code, "test", str(self.source), hashlib.sha256(self.source.read_bytes()).hexdigest(),
                     "2026-08-01", "2026-08-31", "2026-09-01", "2026-09-02", "success"))
                conn.execute("INSERT INTO raw_source_record VALUES (?,?,?,'1','{}','h',?,?,?,?)",
                             (i, code, "test", code, code, "2026-09-01", "2026-09-02"))
                conn.execute("INSERT INTO raw_source_record_version VALUES (?,?,?,'h','{}','2026-09-02')",
                             (i, i, code))
                if code.startswith("orch_"):
                    conn.execute(f"""INSERT INTO ods_{code}
                        (order_no,source_data,row_hash,first_run_id,last_run_id,first_seen_at,last_seen_at)
                        VALUES ('1','{{}}','h',?,?,'2026-09-01','2026-09-02')""", (code, code))
                else:
                    conn.execute("INSERT INTO tr_source_snapshot VALUES (?,?,?,?)", (code, code, code, b"test"))
                    conn.execute("INSERT INTO tr_source_row VALUES (?,1,'[]')", (code,))
            metrics = {m for deps in DEPENDENCIES.values() for m in deps} | {"terminal_recovery"}
            for metric in metrics:
                conn.execute("""INSERT INTO metric_run VALUES
                    (?,?,'1','2026-08-01','2026-08-31','2026-09-03','2026-09-04','success',?,NULL)""",
                    (metric, metric, json.dumps(codes)))
                conn.execute("""INSERT INTO ads_metric_result
                    (metric_run_id,metric_code,dimension_type,dimension_value,metric_value)
                    VALUES (?,?,'province','{}',42)""", (metric, metric))
            before_results = conn.execute("SELECT * FROM ads_metric_result ORDER BY result_id").fetchall()
        self.assertEqual(len(GROUPS), 8)
        for group in GROUPS:
            with self.subTest(group=group):
                result = execute(self.db, group, "2026-08-01", "2026-08-31", apply=True)
                self.assertEqual(result["blockers"], [])
                self.assertTrue(result["applied"])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conn.execute("SELECT * FROM ads_metric_result ORDER BY result_id").fetchall(), before_results)
            self.assertEqual(conn.execute("SELECT dataset_code FROM raw_source_record").fetchall(), [("orch_opening",)])
        self.assertEqual(self.count("ods_orch_opening"), 1)
        self.assertEqual(self.count("ods_orch_install"), 0)
        self.assertEqual(self.count("tr_source_snapshot"), 0)
        self.assertEqual(self.count("tr_source_row"), 0)


if __name__ == "__main__":
    unittest.main()
