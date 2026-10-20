import sqlite3
import calendar
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from storage import import_youshu_completed_history as h
from tests.test_youshu_install_completed import Connection


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.db'
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE collection_run(collection_run_id TEXT PRIMARY KEY,dataset_code TEXT,
              period_start TEXT,period_end TEXT,started_at TEXT,finished_at TEXT,status TEXT,expected_files INTEGER,
              produced_files INTEGER,imported_files INTEGER,source_files TEXT,etl_run_ids TEXT);
              CREATE TABLE etl_run(run_id TEXT,dataset_code TEXT,source_system TEXT,source_file TEXT,file_sha256 TEXT,
              period_start TEXT,period_end TEXT,started_at TEXT,finished_at TEXT,status TEXT,rows_read INTEGER,rows_inserted INTEGER);
              CREATE TABLE youshu_install_completed_city(collection_run_id TEXT,period_start TEXT,period_end TEXT,
              city TEXT,completed_order_count INTEGER,source_file TEXT,collected_at TEXT);''')
        patcher=patch.object(h,'connect',side_effect=lambda:Connection(self.path))
        patcher.start();self.addCleanup(patcher.stop)
        self.data={'path':'history.xlsx','sheet':'Sheet1','sha256':'a'*64,
                   'months':{('2025-01-01','2025-01-31'):{c:{'value':10,'cell':f'C{i+3}'} for i,c in enumerate(sorted(h.CITIES))}}}

    def test_dry_run_then_idempotent_insert(self):
        self.assertFalse(h.import_history(self.data)['applied'])
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM collection_run').fetchone()[0],0)
        self.assertEqual(h.import_history(self.data,True)['inserted_rows'],11)
        self.assertEqual(h.import_history(self.data,True)['inserted_rows'],0)

    def test_conflict_prevents_all_writes(self):
        h.import_history(self.data,True)
        rows=self.data['months'][('2025-01-01','2025-01-31')]
        self.data['months'][('2025-02-01','2025-02-28')]=rows
        rows['杭州']['value']=20
        with self.assertRaisesRegex(ValueError,'不一致'):h.import_history(self.data,True)
        with sqlite3.connect(self.path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM collection_run').fetchone()[0],1)

    def test_failure_rolls_back_audit_and_rows(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER reject_row BEFORE INSERT ON youshu_install_completed_city BEGIN SELECT RAISE(ABORT,'forced'); END")
        with self.assertRaises(sqlite3.IntegrityError):h.import_history(self.data,True)
        with sqlite3.connect(self.path) as db:
            for table in ('collection_run','etl_run','youshu_install_completed_city'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0],0)

    def test_overwrite_keeps_history_and_repeat_is_skipped(self):
        old=h.import_history(self.data,True)['plan'][0]['collection_run_id']
        self.data['months'][('2025-01-01','2025-01-31')]['杭州']['value']=20
        preview=h.import_history(self.data,overwrite=True)
        self.assertEqual(preview['plan'][0]['action'],'overwrite')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT status FROM collection_run').fetchone()[0],'success')
        self.assertEqual(h.import_history(self.data,True,True)['inserted_rows'],11)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT status FROM collection_run WHERE collection_run_id=?',(old,)).fetchone()[0],'superseded')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM youshu_install_completed_city').fetchone()[0],22)
            self.assertEqual(db.execute("SELECT completed_order_count FROM youshu_install_completed_city d JOIN collection_run c ON c.collection_run_id=d.collection_run_id WHERE c.status='success' AND city='杭州'").fetchone()[0],20)
        self.assertEqual(h.import_history(self.data,True,True)['inserted_rows'],0)
        # Reimporting a previously used file must create a fresh batch rather than collide with its old ID.
        self.data['months'][('2025-01-01','2025-01-31')]['杭州']['value']=10
        self.assertEqual(h.import_history(self.data,True,True)['inserted_rows'],11)

    def test_failed_overwrite_restores_original_active_batch(self):
        h.import_history(self.data,True)
        self.data['months'][('2025-01-01','2025-01-31')]['杭州']['value']=20
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER reject_row BEFORE INSERT ON youshu_install_completed_city BEGIN SELECT RAISE(ABORT,'forced'); END")
        with self.assertRaises(sqlite3.IntegrityError):h.import_history(self.data,True,True)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT status FROM collection_run').fetchone()[0],'success')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM youshu_install_completed_city').fetchone()[0],11)

    def test_history_import_to_monthly_sum_calculation(self):
        from metrics.qikuan_opening import qikuan_opening_metrics as m
        self.data['months']={}
        for year in (2025,2026):
            for month in range(1,10):
                bounds=(f'{year}-{month:02}-01',f'{year}-{month:02}-{calendar.monthrange(year,month)[1]:02}')
                self.data['months'][bounds]={c:{'value':10 if year==2025 else 20,'cell':'C3'} for c in h.CITIES}
        h.import_history(self.data,True)
        with patch.object(m.source,'connect',side_effect=lambda:Connection(self.path)):
            report=m.calculate('2026-09',m.load_sources('2026-09','monthly_sum'))
            self.assertEqual(report['province']['current_month'],220)
            self.assertEqual(report['province']['current_ytd'],1980)
            self.assertEqual(report['province']['previous_ytd'],990)
            self.assertEqual(report['province']['ytd_yoy'],1)
            self.assertEqual(len(report['sources']['current_ytd']['source_batches']),9)
            with sqlite3.connect(self.path) as db:
                db.execute("UPDATE collection_run SET status='superseded' WHERE period_start='2025-03-01'")
            with self.assertRaises(m.MissingPeriods) as error:m.load_sources('2026-09','monthly_sum')
            self.assertEqual(error.exception.missing,[('2025-03-01','2025-03-31')])


if __name__=='__main__':unittest.main()
