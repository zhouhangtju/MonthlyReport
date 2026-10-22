import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from metrics.qikuan_opening import qikuan_opening_metrics as m
from storage.metric_results import schema_statements


def snapshots(month='2026-07', amounts=(85139,75103,538968,461737)):
    result = {}
    for (role,(start,end)), amount in zip(m.periods(month).items(), amounts):
        result[role] = {'collection_run_id': role, 'city': [
            {'city': city, 'completed_order_count': amount if i == 0 else 0,
             'period_start': start, 'period_end': end, 'collection_run_id': role}
            for i,city in enumerate(m.CITY_ORDER)]}
    return result


class MetricsTest(unittest.TestCase):
    def test_ppt_example(self):
        result = m.calculate('2026-07',snapshots())
        self.assertEqual(f"{result['province']['yoy']:.2%}", '13.36%')
        self.assertEqual(f"{result['province']['ytd_yoy']:.2%}", '16.73%')
        self.assertEqual(result['charts']['province']['values'],[75103,85139,461737,538968])
        self.assertEqual(len(result['results']),72)
        self.assertEqual(result['cities'][1]['yoy_status'],'zero_base')
        json.dumps(result,allow_nan=False)

    def test_negative_zero_and_zero_base(self):
        self.assertEqual(m.growth(0,100),-1)
        self.assertEqual(m.growth(100,100),0)
        self.assertIsNone(m.growth(5,0))
        self.assertIsNone(m.growth(0,0))
        self.assertEqual(m.rate_text(0),'持平')

    def test_weighted_province(self):
        data=snapshots(amounts=(200,100,300,200))
        data['current_month']['city'][1]['completed_order_count']=900
        data['previous_month']['city'][1]['completed_order_count']=900
        r=m.calculate('2026-07',data)
        self.assertAlmostEqual(r['province']['yoy'],.1)

    def test_periods_leap_year_and_invalid(self):
        p=m.periods('2024-02')
        self.assertEqual(p['current_month'],('2024-02-01','2024-02-29'))
        self.assertEqual(p['previous_month'],('2023-02-01','2023-02-28'))
        for bad in ('2026-7','2026-13','2026-00','2026','0001-01'):
            with self.assertRaises(ValueError):m.periods(bad)

    def test_january_reads_two_periods_only(self):
        with patch.object(m.source,'load_latest_city',return_value={}) as load:
            m.load_sources('2026-01')
        self.assertEqual(load.call_count,13)

    def test_twelve_month_trend_is_stored(self):
        data = snapshots()
        data['monthly_trend'] = {}
        for index, month in enumerate(m.rolling_months('2026-07'), 1):
            start, end = m.monthly_bounds(month)
            data['monthly_trend'][month] = {'collection_run_id': month, 'city': [
                {'city': city, 'completed_order_count': index if i == 0 else 0,
                 'period_start': start, 'period_end': end, 'collection_run_id': month}
                for i, city in enumerate(m.CITY_ORDER)]}
        result = m.calculate('2026-07', data)
        self.assertEqual(result['trend']['months'], m.rolling_months('2026-07'))
        self.assertEqual(result['trend']['values'], list(range(1, 13)))
        self.assertEqual(result['trend']['total'], 78)
        self.assertEqual(len(result['results']), 84)

    def test_all_missing_periods_collected(self):
        with patch.object(m.source,'load_latest_city',side_effect=ValueError('该统计周期没有完整成功的报结量数据')):
            with self.assertRaises(m.MissingPeriods) as error:m.load_sources('2026-07')
        self.assertEqual(len(error.exception.missing),15)

    def test_connection_error_not_reported_as_missing(self):
        with patch.object(m.source,'load_latest_city',side_effect=RuntimeError('database offline')):
            with self.assertRaisesRegex(RuntimeError,'offline'):m.load_sources('2026-07')

    def test_corrupt_source_rejected(self):
        for field,value in [('city','未知'),('completed_order_count',-1),('period_start','2025-07-01'),('collection_run_id','other')]:
            data=snapshots()
            data['current_month']['city'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):m.calculate('2026-07',data)
        data=snapshots();data['current_month']['city'].pop()
        with self.assertRaisesRegex(ValueError,'11'):m.calculate('2026-07',data)

    def test_file_mode_reads_db_but_does_not_save(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(m,'load_sources',return_value=snapshots()),patch.object(m,'save') as save:
            path=Path(directory)/'result.json'
            result=m.run('2026-07','file',path)
            self.assertEqual(json.loads(path.read_text())['province']['current_month'],85139)
            self.assertIsNone(result['metric_run_id'])
            save.assert_not_called()

    def test_schema_consistency(self):
        sql=(m.ROOT/'sql/create_result_qikuan_opening.sql').read_text().strip()
        self.assertIn(sql,schema_statements())
        self.assertIn(sql,(m.ROOT/'sql/schema.sql').read_text())

    def test_transaction_failure_and_provenance(self):
        # Isolated SQL transaction substitute; no production DB connection.
        class Connection:
            def __init__(self,path):self.db=sqlite3.connect(path)
            def __enter__(self):return self
            def __exit__(self,typ,*args):
                self.db.rollback() if typ else self.db.commit()
                self.db.close()
            def executescript(self,sql):pass # MySQL DDL is checked separately.
            def execute(self,*args):return self.db.execute(*args)
            def executemany(self,*args):return self.db.executemany(*args)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.db'
            with sqlite3.connect(path) as db:
                db.executescript('''CREATE TABLE metric_run(metric_run_id TEXT,metric_code TEXT,
                  metric_version TEXT,period_start TEXT,period_end TEXT,started_at TEXT,
                  status TEXT,source_runs TEXT,finished_at TEXT,error_message TEXT);
                  CREATE TABLE result_qikuan_opening(metric_run_id TEXT,metric_code TEXT,
                  dimension_type TEXT,dimension_value TEXT,numerator REAL,denominator REAL,metric_value REAL);''')
            with patch.object(m,'connect',side_effect=lambda:Connection(path)):
                report=m.calculate('2026-07',snapshots())
                run=m.save(report)
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM result_qikuan_opening').fetchone()[0],72)
                    provenance=json.loads(db.execute('SELECT source_runs FROM metric_run').fetchone()[0])
                    self.assertEqual(provenance,report['sources'])
                    db.execute("CREATE TRIGGER reject_row BEFORE INSERT ON result_qikuan_opening BEGIN SELECT RAISE(ABORT,'forced'); END")
                with self.assertRaises(sqlite3.IntegrityError):m.save(report)
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM result_qikuan_opening').fetchone()[0],72)
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM metric_run WHERE status='failed'").fetchone()[0],1)


if __name__=='__main__':unittest.main()
