import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from metrics.opening.automation_intermediate import (
    COLUMNS, OPENING, REMOVAL, aggregate, automatic, excluded_fields, load_assets, timestamp,
)


class AutomationIntermediateTests(unittest.TestCase):
    def test_latest_time_not_csv_order_and_tie_last_row(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'asset.csv'
            with path.open('w', encoding='utf-8-sig', newline='') as target:
                writer = csv.writer(target)
                writer.writerow(['二级编排工单号', '环节名称', '结束时间', '处理人', '处理意见'])
                writer.writerows([
                    ['A', '资源反馈', '2026/8/6 10:09:08', '人工', ''],
                    ['A', '资源反馈', '2026/8/3 13:02:00', '自动处理1', ''],
                    ['A', '组网方案', '2026/8/6 10:09:08', '人工', ''],
                    ['A', '组网方案', '2026/8/6 10:09:09', '系统自动', ''],
                    ['A', '归档审核', '2026/8/6 10:09:08', '系统自动', ''],
                    ['A', '归档审核', '2026/8/6 10:09:08', '最终人工', ''],
                ])
            with sqlite3.connect(':memory:') as cache:
                cache.execute('CREATE TABLE assets(order_no TEXT,stage TEXT,ended TEXT,payload TEXT,PRIMARY KEY(order_no,stage))')
                load_assets(cache, path)
                selected = {s: json.loads(p)['处理人'] for s, p in cache.execute('SELECT stage,payload FROM assets')}
                self.assertEqual(selected, {'资源反馈': '人工', '组网方案': '系统自动', '归档审核': '最终人工'})

    def test_nine_nine_six_denominators_and_missing_stages(self):
        rows = []
        for kind in ['开通', '变更', '拆除']:
            row = dict.fromkeys(COLUMNS, '')
            row.update(订单状态='已完成', 业务类型='互联网专线', 订单类型=kind, 地市='杭州市')
            for _, field in REMOVAL if kind == '拆除' else OPENING:
                row[field] = '账号自动处理1'
            rows.append(row)
        rows[0]['资源反馈'] = ''
        results = aggregate(rows, '2026-08')
        overall = {r['metric_code']: (r['numerator'], r['denominator']) for r in results if r['dimension_type'] == 'month_all_stages'}
        self.assertEqual(overall['internet_opening_automation_rate'], (8, 9))
        self.assertEqual(overall['internet_move_automation_rate'], (9, 9))
        self.assertEqual(overall['internet_removal_automation_rate'], (6, 6))
        self.assertFalse(automatic('系统管理员'))
        self.assertTrue(automatic(' 系统自动 '))

    def test_invalid_time_rejected(self):
        with self.assertRaises(ValueError):
            timestamp('')

    def test_slash_cleaning_depends_on_order_type(self):
        opening = {'订单类型': '开通', '报结人': ' / ', '资源查询受理人': '/'}
        move = {'订单类型': '变更', '资源分配受理人': '/', '资源查询受理人': '/'}
        removal = {'订单类型': '拆除', '方案设计处理人': '/', '资源分配受理人': '/',
                   '资源查询受理人': ' / ', '报结人': '自动/处理'}
        self.assertEqual(excluded_fields(opening), ['报结人'])
        self.assertEqual(excluded_fields(move), ['资源分配受理人'])
        self.assertEqual(excluded_fields(removal), ['资源查询受理人'])
        self.assertEqual(excluded_fields({'订单类型': '开通', '受理人': None,
                                          '方案设计处理人': '', '报结人': '自动/处理'}), [])
        self.assertEqual(excluded_fields({'订单类型': '激活', '受理人': '/'}), [])

    def test_legacy_manual_json_cannot_override_database_automation(self):
        from reporting.manual_results import apply_results, AUTOMATION
        data = {key: {'automationSource': 'intermediate_orchestration_orders', 'network': {'rates': [0.5]}}
                for key in ('internetAuto', 'internetMoveAuto', 'internetRemovalAuto')}
        # No legacy automation metrics: only the retained reasons are needed.
        document = {'opening_network_nonautomatic_reasons': {
            '地市': {}, '全省': {'工程施工工单数': 0}}}
        apply_results(data, {AUTOMATION: document}, {'missing': []}, None)
        self.assertEqual(data['internetAuto']['network']['rates'], [0.5])
        self.assertIn('manualReasons', data['internetAuto'])


if __name__ == '__main__':
    unittest.main()
