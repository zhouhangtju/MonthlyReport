"""Isolated MySQL checks for result routing, migration and PPT input parity."""
import json
import unittest
from unittest.mock import patch
import test_split_raw_tables_integration as fixed
from storage.database import connect
from storage.metric_results import TABLES, insert_results, read_results
from storage.migrate_metric_results import migrate
from metrics.installation.common import save_metric
from reporting.database_results import build_data


class ModuleResultsTest(unittest.TestCase):
    setUp = fixed.FixedRawTablesTest.setUp
    drop_database = fixed.FixedRawTablesTest.drop_database

    def report(self, owner, value=.5):
        item = dict(metric_code=owner, dimension_type='province', dimension={'scope': '全省'},
                    numerator=5, denominator=10, metric_value=value)
        if owner == 'orchestration_opening_metrics':
            item.update(metric_code='internet_opening_orders', dimension_type='month',
                        dimension={'month': '2026-08'}, numerator=5, denominator=None, metric_value=5)
        if owner == 'terminal_recovery':
            item.update(metric_code='terminal_recovery_rate', dimension_type='city_summary',
                        dimension={'sheet': '按地市回收率汇总', 'table': 'city_summary',
                                   'row_index': 1, 'column_index': 8, 'label_column': '地市',
                                   'label': '杭州市', 'column': '终端回收率'})
        start = '2026-08-01' if owner in {'terminal_recovery', 'orchestration_opening_metrics'} else '2026-06-01'
        end = '2026-08-31'
        if owner == 'dedicated_line_opening_withdrawal_rate':
            start, end = '2026-07-26', '2026-08-25'
        results = [item]
        if owner == 'terminal_recovery':
            for kind, column in [('business', '互联网专线'), ('city', '杭州市')]:
                results.append(dict(metric_code='terminal_recovery_count', dimension_type=kind,
                    dimension={'sheet': 'sheet1', 'table': kind, 'row_index': 1,
                               'column_index': 2, 'label_column': '型号匹配',
                               'label': 'ONU', 'column': column},
                    numerator=7, denominator=1, metric_value=7))
        return dict(metric_code=owner, metric_version='test', period_start=start,
                    period_end=end, results=results)

    def legacy_table(self):
        with connect(None) as conn:
            conn.execute('''CREATE TABLE ads_metric_result (
                result_id BIGINT AUTO_INCREMENT PRIMARY KEY, metric_run_id VARCHAR(80),
                metric_code VARCHAR(120), dimension_type VARCHAR(120), dimension_value LONGTEXT,
                numerator DOUBLE, denominator DOUBLE, metric_value DOUBLE)''')

    def test_routes_all_eight_modules_and_explicit_columns(self):
        for owner, table in TABLES.items():
            report = self.report(owner)
            run = save_metric(None, report, [])
            with connect(None) as conn:
                row = conn.execute(f'SELECT * FROM `{table}` WHERE metric_run_id=? ORDER BY result_id', (run,)).fetchone()
                self.assertEqual(json.loads(row['dimension_value']), report['results'][0]['dimension'])
                if owner == 'terminal_recovery':
                    self.assertEqual((row['row_label'], row['row_index']), ('杭州市', 1))
                elif owner == 'orchestration_opening_metrics':
                    self.assertEqual(row['month'], '2026-08')
                else:
                    self.assertEqual(row['scope'], '全省')
        with connect(None) as conn:
            self.assertFalse(conn.execute("SHOW TABLES LIKE 'ads_metric_result'").fetchall())

    def test_migration_restart_and_ppt_parity(self):
        self.legacy_table()
        for owner, table in TABLES.items():
            run = save_metric(None, self.report(owner), [])
            with connect(None) as conn:
                conn.execute(f'''INSERT INTO ads_metric_result
                    (metric_run_id,metric_code,dimension_type,dimension_value,numerator,denominator,metric_value)
                    SELECT metric_run_id,metric_code,dimension_type,dimension_value,numerator,denominator,metric_value
                    FROM `{table}` WHERE metric_run_id=?''', (run,))
                conn.execute(f'DELETE FROM `{table}` WHERE metric_run_id=?', (run,))
        def old_reader(conn, owner, run):
            return conn.execute('SELECT * FROM ads_metric_result WHERE metric_run_id=? ORDER BY result_id', (run,)).fetchall()
        with patch('reporting.database_results.read_results', side_effect=old_reader):
            before = build_data(None, '2026-08')
        with self.assertRaisesRegex(RuntimeError, '迁移|migrate'):
            build_data(None, '2026-08')
        self.assertEqual(migrate(False)['source_rows'], 10)
        self.assertEqual(migrate(True)['inserted'], 10)
        self.assertEqual(migrate(True)['inserted'], 0)
        after = build_data(None, '2026-08')
        # IDs are now table-local; every consumed value and dimension must remain equal.
        for data in (before, after):
            for row in data['dataAudit']['used_results']:
                row.pop('result_id')
        self.assertEqual(before, after)

    def test_migration_conflict_preserves_source_and_target(self):
        self.legacy_table()
        owner = 'qikuan_install_fault_rate'
        run = save_metric(None, self.report(owner), [])
        with connect(None) as conn:
            conn.execute('''INSERT INTO ads_metric_result
                (metric_run_id,metric_code,dimension_type,dimension_value,numerator,denominator,metric_value)
                SELECT metric_run_id,metric_code,dimension_type,dimension_value,999,denominator,metric_value
                FROM result_qikuan_install_fault WHERE metric_run_id=?''', (run,))
        with self.assertRaisesRegex(ValueError, '冲突'):
            migrate(True)
        with connect(None) as conn:
            self.assertEqual(read_results(conn, owner, run)[0]['numerator'], 5)
            self.assertEqual(conn.execute('SELECT numerator FROM ads_metric_result').fetchone()['numerator'], 999)

    def test_commercial_uses_split_upstreams(self):
        from metrics.installation.commercial_customer_install_fault_rate import run
        owners = ['qikuan_install_fault_rate', 'dedicated_line_install_fault_rate']
        sources = [save_metric(None, self.report(owner), []) for owner in owners]
        report = run(None, '2026-06-01', '2026-08-31', mode='database')
        self.assertEqual(report['source_metric_runs'], sources)
        self.assertEqual(report['results'][0]['numerator'], 10)
        self.assertEqual(report['results'][0]['denominator'], 20)

    def test_unknown_dimensions_fail_without_partial_results(self):
        report = self.report('qikuan_install_fault_rate')
        report['results'].append(dict(report['results'][0], dimension={'unmapped': 'x'}))
        with self.assertRaisesRegex(ValueError, '未映射'):
            save_metric(None, report, [])
        with connect(None) as conn:
            self.assertEqual(conn.execute('SELECT status FROM metric_run').fetchone()['status'], 'failed')
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM result_qikuan_install_fault').fetchone()['n'], 0)

    def test_ppt_selects_whole_latest_successful_batch(self):
        owner = 'terminal_recovery'
        old = save_metric(None, self.report(owner, .2), [])
        new = save_metric(None, self.report(owner, .4), [])
        with connect(None) as conn:
            conn.execute("UPDATE metric_run SET started_at='2026-09-01' WHERE metric_run_id=?", (old,))
            conn.execute("UPDATE metric_run SET started_at='2026-09-02' WHERE metric_run_id=?", (new,))
        self.assertEqual(build_data(None, '2026-08')['terminalRecovery']['city']['rates'][0], .4)
        with connect(None) as conn:
            conn.execute("UPDATE metric_run SET status='failed' WHERE metric_run_id=?", (new,))
        self.assertEqual(build_data(None, '2026-08')['terminalRecovery']['city']['rates'][0], .2)


if __name__ == '__main__':
    unittest.main()
