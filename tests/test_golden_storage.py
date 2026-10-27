"""Run against a disposable MySQL database only."""
import unittest
from pathlib import Path
from config.datasets import get_dataset
from storage.importer import import_file
from storage.database import connect
from storage.raw_tables import read_records
import test_split_raw_tables_integration as fixed_tests

class GoldenStorageTest(unittest.TestCase):
    setUp=fixed_tests.FixedRawTablesTest.setUp
    drop_database=fixed_tests.FixedRawTablesTest.drop_database
    def test_sample_repeat_and_period_isolation(self):
        root=Path(__file__).resolve().parents[1]/'payload'
        for kind,title,count in [('transport','传输L4工单统计报表',10),('internet','互联网L4工单统计报表',12),('cloud','云网业务综合指标报表',7)]:
            code='orch_golden_'+kind
            path=root/f'【{title}】查询结果.xls'
            def put(start):
                return import_file(None,get_dataset(code),path,period_start=start,period_end='2026-10-25')
            self.assertEqual(put('2026-09-26')['inserted'],count)
            self.assertEqual(put('2026-09-26')['unchanged'],count)
            put('2026-09-25')
            with connect(None) as conn:
                self.assertEqual(len(read_records(conn,code,'2026-09-26','2026-10-25')),count)
                self.assertEqual(len(read_records(conn,code,'2026-09-25','2026-10-25')),count)
