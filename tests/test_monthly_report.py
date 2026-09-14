import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from reporting.database_results import build_data, month_bounds
from storage.database import initialize


class MonthlyReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / 'test.db'
        initialize(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def seed(self, owner, start, end, code, kind, dimension, value, run='one', stamp='2026-09-01'):
        with sqlite3.connect(self.database) as conn:
            conn.execute("INSERT OR IGNORE INTO metric_run VALUES (?,?, 'test',?,?,?,?,'success','[]',NULL)", (run, owner, start, end, stamp, stamp))
            conn.execute("INSERT INTO ads_metric_result(metric_run_id,metric_code,dimension_type,dimension_value,numerator,denominator,metric_value) VALUES(?,?,?,?,?,?,?)", (run, code, kind, json.dumps(dimension), 8, 10, value))

    def test_support_prefers_monthly_then_ending_quarter_but_not_other_month(self):
        code = 'qianliyan_repeat_complaint_rate'
        self.seed(code, '2026-06-01', '2026-08-31', code, 'province', {'scope': '全省'}, .5)
        self.seed(code, '2026-09-01', '2026-09-30', code, 'province', {'scope': '全省'}, .9, run='future')
        data = build_data(self.database, '2026-08')
        self.assertEqual(data['complaintFault']['repeat']['broadbandAverage'], .5)
        self.assertEqual(data['complaintFault']['repeatPeriod'], '2026-06-01至2026-08-31')
        self.seed(code, '2026-08-01', '2026-08-31', code, 'province', {'scope': '全省'}, .12, run='monthly')
        data = build_data(self.database, '2026-08')
        self.assertEqual(data['complaintFault']['repeat']['broadbandAverage'], .12)

    def test_latest_terminal_batch_and_stored_rate(self):
        dims = {'label': '杭州市', 'column': '终端回收率'}
        self.seed('terminal_recovery', '2026-08-01', '2026-08-31', 'terminal_recovery_rate', 'city_summary', dims, .37)
        self.seed('terminal_recovery', '2026-08-01', '2026-08-31', 'terminal_recovery_rate', 'city_summary', dims, .42, run='new', stamp='2026-09-02')
        data = build_data(self.database, '2026-08')
        self.assertEqual(data['terminalRecovery']['city']['rates'][0], .42)
        self.assertEqual(data['terminalRecovery']['city']['rate'], 0)

    def test_opening_history_uses_month_dimension(self):
        self.seed('orchestration_opening_metrics', '2025-08-01', '2026-08-31', 'internet_opening_orders', 'month', {'month': '2026-08'}, 123)
        self.seed('orchestration_opening_metrics', '2025-08-01', '2026-08-31', 'internet_opening_orders', 'month', {'month': '2026-07'}, 456)
        self.seed('orchestration_opening_metrics', '2025-08-01', '2026-08-31', 'internet_product_average_monthly_orders', 'rolling_12_months', {'end_month': '2026-08', 'product': '悦享专线动态IP版'}, 100, run='one')
        with sqlite3.connect(self.database) as conn:
            conn.execute(
                """UPDATE ads_metric_result SET numerator=1200, denominator=12
                   WHERE metric_code='internet_product_average_monthly_orders'"""
            )
        data = build_data(self.database, '2026-08')
        self.assertEqual(data['currentTotal'], 123)
        self.assertEqual(len(data['months']), 12)
        self.assertEqual(data['months'][-1], '26.08')
        self.assertEqual(data['trendSummary']['悦享专线动态IP版']['sum'], 1200)
        self.assertEqual(data['trendSummary']['悦享专线动态IP版']['average'], 100)

    def test_missing_results_are_zero_and_database_is_read_only(self):
        before = self.database.read_bytes()
        data = build_data(self.database, '2026-08')
        self.assertEqual(data['currentTotal'], 0)
        self.assertEqual(data['withdrawal']['networkCount'], 0)
        self.assertEqual(data['terminalRecovery']['city']['completed'], [0]*11)
        json.dumps(data, allow_nan=False)
        self.assertTrue(data['dataAudit']['missing'])
        self.assertEqual(before, self.database.read_bytes())

    def test_missing_database_is_not_created(self):
        missing = Path(self.temp.name) / 'missing.db'
        with self.assertRaises(sqlite3.OperationalError):
            build_data(missing, '2026-08')
        self.assertFalse(missing.exists())

    def test_dates_are_calendar_months(self):
        self.assertEqual(month_bounds('2028-02'), ('2028-02-01', '2028-02-29'))
        for value in ('2026-8', '2026-13', '2026-08-01'):
            with self.assertRaises(ValueError):
                month_bounds(value)


if __name__ == '__main__':
    unittest.main()
