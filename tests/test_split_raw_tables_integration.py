"""Isolated MySQL regression tests for fixed XLSX columns."""
from __future__ import annotations
import csv
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from config.datasets import DATASETS
from storage.database import _connect_raw, connect, initialize
from storage.importer import import_file
from storage.raw_tables import source_columns, read_records, table_statements
from metrics.opening.withdrawal import load_rows, calculate, save_results

class FixedRawTablesTest(unittest.TestCase):
    def setUp(self):
        self.name = 'qa_fixed_test_' + uuid.uuid4().hex[:12]
        self.config = patch('storage.database.DEFAULT_DATABASE', self.name)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.addCleanup(self.drop_database)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        initialize(None)

    def drop_database(self):
        assert self.name.startswith('qa_fixed_test_')
        conn = _connect_raw(include_database=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(f'DROP DATABASE IF EXISTS `{self.name}`')
            conn.commit()
        finally:
            conn.close()

    def write(self, code, rows):
        path = self.root / (code + '.csv')
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=source_columns(code))
            writer.writeheader()
            writer.writerows(rows)
        return path

    def put(self, code, rows, start='2026-08-01', end='2026-08-31'):
        return import_file(None, DATASETS[code], self.write(code,rows),period_start=start,period_end=end)

    def test_all_tables_keys_and_repeat_import(self):
        for code, dataset in DATASETS.items():
            with self.subTest(code=code):
                row = {'物料名称':'ONU'} if dataset.auto_increment else {dataset.key_column:'000123'}
                first=self.put(code,[row]); second=self.put(code,[row])
                self.assertEqual(first['inserted'],1)
                self.assertEqual(second['unchanged'],1)
                with connect(None) as conn:
                    columns=conn.execute(f'SHOW COLUMNS FROM `{code}`').fetchall()
                    self.assertEqual([c['Field'] for c in columns],(['id'] if dataset.auto_increment else [])+source_columns(code))
                    self.assertEqual([c['Field'] for c in columns if c['Key']=='PRI'],[dataset.key_column])
                    records=read_records(conn,code,'2026-08-01','2026-08-31')
                    self.assertEqual(len(records),1)
                    self.assertEqual(conn.execute(f'SELECT COUNT(*) AS n FROM `{code}_version`').fetchone()['n'],1)

    def test_period_replacement_deduplicates_and_preserves_other_months(self):
        code='integration_terminal_inbound'
        self.put(code,[{'物料名称':'ONU'},{'物料名称':'ONU'}])
        self.put(code,[{'物料名称':'SEP'}],'2026-09-01','2026-09-30')
        result=self.put(code,[{'物料名称':'NEW'}])
        self.assertEqual(result['replaced'],1)
        with connect(None) as conn:
            self.assertEqual([r['物料名称'] for r in read_records(conn,code,'2026-08-01','2026-08-31')],['NEW'])
            self.assertEqual([r['物料名称'] for r in read_records(conn,code,'2026-09-01','2026-09-30')],['SEP'])
            self.assertEqual(conn.execute(f'SELECT COUNT(*) AS n FROM `{code}_version`').fetchone()['n'],3)
            with self.assertRaises(ValueError): read_records(conn,code)
        self.put(code,[])
        with connect(None) as conn:
            self.assertEqual(read_records(conn,code,'2026-08-01','2026-08-31'),[])

    def test_inventory_dedup_is_global_and_compares_every_column(self):
        for code in ('integration_terminal_inbound', 'integration_terminal_outbound'):
            first=self.put(code,[{'物料名称':'ONU','总数量':'1'}]*2)
            self.assertEqual((first['inserted'],first['duplicates']),(1,1))
            second=self.put(code,[{'物料名称':'ONU','总数量':'1'}],'2026-09-01','2026-09-30')
            self.assertEqual((second['inserted'],second['unchanged']),(0,1))
            third=self.put(code,[{'物料名称':'ONU','总数量':'1'},
                                 {'物料名称':'ONU','总数量':'2'},
                                 {'物料名称':'onu','总数量':'1'},
                                 {'物料名称':'ONU ','总数量':'1'}])
            self.assertEqual((third['inserted'],third['unchanged']),(3,1))
            with connect(None) as conn:
                self.assertEqual(conn.execute(f'SELECT COUNT(*) AS n FROM `{code}`').fetchone()['n'],4)
                august=read_records(conn,code,'2026-08-01','2026-08-31')
                september=read_records(conn,code,'2026-09-01','2026-09-30')
                self.assertEqual(august[0]['id'],september[0]['id'])
            self.put(code,[])
            repeat=self.put(code,[{'物料名称':'ONU','总数量':'1'}])
            self.assertEqual((repeat['inserted'],repeat['unchanged']),(0,1))

    def test_conflict_rolls_back_and_logs_errors(self):
        code='terminal_material_names'
        self.put(code,[{'物料名称':'ONU','划分类型':'old'}])
        with self.assertRaises(ValueError):
            self.put(code,[{'物料名称':'ONU','划分类型':'a'},{'物料名称':'ONU','划分类型':'b'}])
        with connect(None) as conn:
            self.assertEqual(read_records(conn,code)[0]['划分类型'],'old')
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM raw_import_error').fetchone()['n'],1)
        result=self.put(code,[{'物料名称':'ONU','划分类型':'new'}]*2)
        self.assertEqual((result['updated'],result['duplicates']),(1,1))

    def test_calculation_reads_fixed_columns_and_saves(self):
        code='integration_opening'
        self.put(code,[{'工单号':'000123','工单数据来源':'二编','工单类型':'开通',
                       '业务类型':'互联网专线','工单状态':'已撤单','工单结束时间':'2026-08-15 10:00:00','地市':'杭州'}])
        rows,runs=load_rows(None)
        report=calculate(rows,'2026-08-01','2026-08-31')
        self.assertEqual((report['results'][0]['numerator'],report['results'][0]['denominator']),(1,1))
        save_results(None,report,runs)
        self.assertEqual(rows[0]['_source_record_id'],'000123')

    def test_header_mismatch_is_not_silently_imported(self):
        path=self.root/'wrong.csv'; path.write_text('unknown\nvalue\n',encoding='utf-8-sig')
        with self.assertRaisesRegex(ValueError,'表头'):
            import_file(None,DATASETS['integration_opening'],path)

    def partial(self, code, headers, rows):
        path = self.root / 'partial.csv'
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerows(rows)
        return import_file(None, DATASETS[code], path,
                           period_start='2026-08-01', period_end='2026-08-31')

    def test_partial_headers_merge_and_expand(self):
        code = 'eoms_complaint'
        self.partial(code, ['工单号', 'isSelfbuild'], [['A', 'keep']])
        self.partial(code, ['新增字段', '工单号'], [['new', 'A'], ['other', 'B']])
        initialize(None)
        repeat = self.partial(code, ['工单号'], [['A']])
        self.assertEqual(repeat['unchanged'], 1)
        with connect(None) as conn:
            rows = {r['工单号']: r for r in read_records(conn, code)}
            self.assertEqual(rows['A']['isSelfbuild'], 'keep')
            self.assertEqual(rows['A']['新增字段'], 'new')
            self.assertIsNone(rows['B']['isSelfbuild'])
            import json
            versions = conn.execute('SELECT source_data FROM eoms_complaint_version WHERE source_record_id=?', ('A',)).fetchall()
            self.assertTrue(any(json.loads(r['source_data']).get('新增字段') == 'new' and
                                json.loads(r['source_data'])['isSelfbuild'] == 'keep' for r in versions))
        self.partial(code, ['工单号', 'isSelfbuild'], [['A', '']])
        with connect(None) as conn:
            self.assertNotEqual(conn.execute('SELECT isSelfbuild FROM eoms_complaint WHERE `工单号`=?', ('A',)).fetchone()['isSelfbuild'], 'keep')

    def test_partial_inventory_compares_missing_as_null(self):
        code = 'integration_terminal_inbound'
        self.partial(code, ['物料名称', '扩展列'], [['ONU', 'x']])
        self.assertEqual(self.partial(code, ['物料名称'], [['ONU']])['inserted'], 1)
        self.assertEqual(self.partial(code, ['物料名称'], [['ONU']])['unchanged'], 1)

    def test_duplicate_headers_and_invalid_keys_fail_before_expansion(self):
        with self.assertRaises(ValueError):
            self.partial('eoms_complaint', ['工单号', '工单号'], [['A', 'B']])
        with self.assertRaises(ValueError):
            self.partial('eoms_complaint', ['工单号', '不应创建'], [['', 'x']])
        with connect(None) as conn:
            self.assertNotIn('不应创建', [r['Field'] for r in conn.execute('SHOW COLUMNS FROM eoms_complaint').fetchall()])

    def test_youshu_both_without_ods(self):
        from collector.youshu.client import collect
        path = self.write('youshu_complaint', [{'工单号': 'C-1'}])
        with patch('collector.youshu.client.run_fetch', return_value=[path]):
            result = collect('complaint', '2026-08-01', '2026-08-31',
                             mode='both', output_dir=self.root)
        self.assertEqual(result['etl_runs'][0]['inserted'], 1)
        with connect(None) as conn:
            row = conn.execute('SELECT * FROM collection_run').fetchone()
            self.assertEqual(row['status'], 'success')
            self.assertEqual(row['imported_files'], 1)
            self.assertNotEqual(row['source_files'], '[]')
            self.assertNotEqual(row['etl_run_ids'], '[]')
        with patch('collector.youshu.client.run_fetch') as fetch:
            self.assertTrue(collect('complaint', '2026-08-01', '2026-08-31',
                                    mode='both', output_dir=self.root)['skipped'])
            fetch.assert_not_called()

    def test_install_calculation_without_ods(self):
        from metrics.installation.common import load_dataset, save_metric
        from metrics.installation.dedicated_line_install_fault_rate import calculate
        self.put('orch_install', [{'订单号': 'I-1', '产品实例编号': '001',
                                  '订单创建时间': '2026-08-01 10:00:00', '地市': '杭州市'}])
        self.put('eoms_complaint', [{'工单号': 'C-1', '计费号码': '001',
                                   '派单时间': '2026-08-02 10:00:00', '所属地市': '杭州市'}])
        installs, runs = load_dataset(None, 'orch_install')
        complaints, other = load_dataset(None, 'eoms_complaint')
        report = calculate(installs, complaints, '2026-08-01', '2026-08-31')
        self.assertEqual((report['results'][0]['numerator'], report['results'][0]['denominator']), (1, 1))
        save_metric(None, report, runs + other, details=report['details'])

    def test_raw_calculation_and_retention_use_business_key(self):
        from metrics.opening.dedicated_line_metrics import calculate as opening_calculate, save_results as opening_save
        from storage.prune_orchestration_opening import prune
        row={'订单号':'ORDER-1','订单结束时间':'2025-08-20 10:00:00','订单状态':'已完成',
             '业务类型':'互联网专线','产品名称':'互联网专线套餐','订单类型':'开通','地市':'杭州市'}
        run=self.put('orch_opening',[row],'2025-08-01','2025-08-31')
        self.put('orch_opening', [{'订单号': 'KEEP', '订单结束时间': '2025-09-01 00:00:00'},
                                 {'订单号': 'EMPTY', '订单结束时间': '  '}])
        from metrics.opening.dedicated_line_metrics import load_rows as opening_load
        initialize(None)
        with connect(None) as conn:
            tables = conn.execute("SHOW TABLES").fetchall()
            self.assertFalse(any('ods_orch_' in str(t) for t in tables))
        rows, runs = opening_load(None, '2025-08', '2025-08')
        self.assertEqual([r['_source_record_id'] for r in rows], ['ORDER-1'])
        actual = opening_calculate(rows, '2025-08', '2025-08')
        expected = opening_calculate([row], '2025-08', '2025-08')
        self.assertEqual(actual['results'], expected['results'])
        opening_save(None, actual, runs)
        result=prune(None,'2025-09',self.root/'archive')
        self.assertTrue(Path(result['archive_file']).is_file())
        with connect(None) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM orch_opening').fetchone()['n'],2)
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM raw_record_audit').fetchone()['n'],2)
        import gzip, json
        with gzip.open(result['archive_file'], 'rt', encoding='utf-8') as stream:
            archived = [json.loads(line) for line in stream]
        self.assertEqual(archived[1]['data']['raw_data']['订单号'], 'ORDER-1')
        self.assertEqual(len(archived[1]['data']['versions']), 1)

if __name__=='__main__': unittest.main()
