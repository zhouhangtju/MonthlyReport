import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.daily_installation import cleanup_current_runs
from storage.metric_results import table_for


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE metric_run (metric_run_id TEXT PRIMARY KEY, metric_code TEXT, period_start TEXT, period_end TEXT, status TEXT)')
        self.db.execute('CREATE TABLE ads_metric_detail (metric_run_id TEXT)')
        self.runs = []
        self.tables = ['metric_run', 'ads_metric_detail']
        for metric in ('qikuan', 'dedicated_line', 'commercial_customer'):
            code = metric + '_install_fault_rate'
            table = table_for(code)
            self.tables.append(table)
            self.db.execute(f'CREATE TABLE {table} (metric_run_id TEXT)')
            for index in range(2):
                run = dict(metric_run_id=f'{metric}{index}', metric_code=code, period_start='2026-08-01', period_end='2026-10-29')
                self.runs.append(run)
                self.db.execute('INSERT INTO metric_run VALUES (?,?,?,?,?)', (*run.values(), 'success'))
                self.db.execute('INSERT INTO ads_metric_detail VALUES (?)', (run['metric_run_id'],))
                self.db.execute(f'INSERT INTO {table} VALUES (?)', (run['metric_run_id'],))
        self.db.execute("INSERT INTO metric_run VALUES ('old','old','old','old','success')")
        self.db.execute("INSERT INTO ads_metric_detail VALUES ('old')")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def connection(self, fail=False):
        db = self.db
        class Adapter:
            def __enter__(self): return self
            def __exit__(self, kind, *_):
                db.rollback() if kind else db.commit()
            def execute(self, sql, args):
                if fail and sql.startswith('DELETE FROM metric_run'):
                    raise RuntimeError('injected delete failure')
                return db.execute(sql.replace(' FOR UPDATE', ''), args)
        return Adapter()

    def counts(self):
        return [self.db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in self.tables]

    def test_only_current_runs_removed(self):
        with patch('storage.database.connect', return_value=self.connection()):
            cleanup_current_runs(self.runs)
        self.assertEqual(self.counts(), [1, 1, 0, 0, 0])
        self.assertEqual(self.db.execute('SELECT metric_run_id FROM metric_run').fetchone()[0], 'old')

    def test_delete_failure_rolls_back_all_tables(self):
        before = self.counts()
        with patch('storage.database.connect', return_value=self.connection(fail=True)):
            with self.assertRaises(RuntimeError): cleanup_current_runs(self.runs)
        self.assertEqual(self.counts(), before)

    def test_mismatched_identity_preserves_all_rows(self):
        before = self.counts()
        self.runs[-1]['period_start'] = 'wrong'
        with patch('storage.database.connect', return_value=self.connection()):
            with self.assertRaises(ValueError): cleanup_current_runs(self.runs)
        self.assertEqual(self.counts(), before)
