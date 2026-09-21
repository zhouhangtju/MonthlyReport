"""Parity, real unbuffered reads and bounded-memory simulation."""
import contextlib
import io
import random
import unittest
from unittest.mock import patch

from metrics.opening import dedicated_line_metrics as m
import test_split_raw_tables_integration as fixed


def batches(rows, size):
    for offset in range(0, len(rows), size):
        yield rows[offset:offset + size]


class StreamingParityTest(unittest.TestCase):
    def test_all_dimensions_and_cross_batch_dedup(self):
        rng = random.Random(17)
        rows = []
        months = m.month_range('2025-08', '2026-08')
        for n in range(2500):
            month = rng.choice(months)
            row = {'订单号': str(n % 47), '订单结束时间': f' {month}-15 12:00:00 ',
                   '订单状态': rng.choice(['已完成', '处理中']),
                   '业务类型': rng.choice([m.BUSINESS_TYPE, m.MPLS_BUSINESS_TYPE, m.TRANSMISSION_BUSINESS_TYPE, '其他']),
                   '订单类型': rng.choice(['开通', '变更', '拆除', '其他']),
                   '产品名称': rng.choice(m.ALL_PRODUCTS + m.MPLS_PRODUCTS + m.TRANSMISSION_PRODUCTS + ['未知']),
                   '地市': rng.choice(m.CITY_ORDER + ['未知'])}
            for _, field, automatic in m.OPENING_STAGES + m.REMOVAL_STAGES:
                row[field] = rng.choice([automatic, '人工', None])
            if n % 113 == 0:
                row['订单号'] = ''
            rows.append(row)
        rows += [dict(rows[0], 产品名称='互联网专线套餐')]
        expected = m.calculate(rows, '2025-09', '2026-08')
        for size in [1, 37, 5000]:
            month_batches = ((month, batches([r for r in rows if m.row_month(r) == month], size)) for month in months)
            with patch.object(m, 'log'):
                actual = m.calculate_month_batches(month_batches, '2025-09', '2026-08')
            self.assertEqual(actual, expected)

    def test_history_fallback_empty_months_and_zero_denominators(self):
        row = {'订单号': 'old', '订单结束时间': '2025-08-01', '订单状态': '已完成',
               '业务类型': m.BUSINESS_TYPE, '订单类型': '开通', '产品名称': m.ALL_PRODUCTS[0]}
        old = m.calculate([row], '2025-08', '2025-08')
        summaries = [r for r in old['results'] if r['dimension'].get('month') == '2025-08'
                     and not r['metric_code'].endswith(('_mom', '_yoy'))]
        for rows in [[], [dict(row, 订单结束时间='2025-08-01', 订单状态='处理中')]]:
            with patch.object(m, 'log'):
                actual = m.calculate_month_batches(((month, batches([r for r in rows if m.row_month(r) == month], 2))
                    for month in m.month_range('2025-08', '2026-08')), '2025-09', '2026-08', summaries)
            self.assertEqual(actual, m.calculate(rows, '2025-09', '2026-08', summaries))


class StreamingDatabaseTest(unittest.TestCase):
    setUp = fixed.FixedRawTablesTest.setUp
    drop_database = fixed.FixedRawTablesTest.drop_database
    write = fixed.FixedRawTablesTest.write
    put = fixed.FixedRawTablesTest.put

    def test_stream_matches_legacy_reader_and_saves_results(self):
        rows = [{'订单号': str(i), '订单结束时间': f'2026-0{7+i%2}-15 10:00:00',
                 '订单状态': '已完成', '业务类型': m.BUSINESS_TYPE,
                 '订单类型': '开通', '产品名称': m.ALL_PRODUCTS[i%2], '地市': '杭州市'} for i in range(17)]
        rows += [{'订单号': 'outside', '订单结束时间': '2026-09-01'},
                 {'订单号': 'missing', '订单结束时间': None}]
        self.put('orch_opening', rows)
        with patch.object(m, 'log'):
            legacy, sources = m.load_rows(None, '2025-08', '2026-08')
            report, actual_sources = m.load_and_calculate(None, '2025-09', '2026-08', 3, self.root)
        self.assertEqual(report, m.calculate(legacy, '2025-09', '2026-08'))
        self.assertEqual(actual_sources, sources)
        with patch.object(m, 'log'), patch.object(m, 'print_report'):
            final = m.run(None, '2025-09', '2026-08', mode='both', output=self.root/'report.json', batch_size=2, temp_dir=self.root)
        self.assertTrue((self.root/'report.json').is_file())
        self.assertTrue(final['metric_run_id'])
        self.assertEqual(list(self.root.glob('opening_month_*')), [])


if __name__ == '__main__':
    unittest.main()
