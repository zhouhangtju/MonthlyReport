import copy
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reporting import manual_results as m
from reporting.database_results import Results, build_data


class ManualResultsTest(unittest.TestCase):
    def test_ppt_selects_shifted_opening_withdrawal_period(self):
        owner = 'dedicated_line_opening_withdrawal_rate'
        runs = [
            {'metric_run_id': 'natural', 'metric_code': owner, 'period_start': '2026-08-01',
             'period_end': '2026-08-31', 'started_at': '2026-09-02', 'status': 'success'},
            {'metric_run_id': 'shifted', 'metric_code': owner, 'period_start': '2026-07-26',
             'period_end': '2026-08-25', 'started_at': '2026-09-01', 'status': 'success'},
        ]

        class Cursor:
            def fetchall(self):
                return runs

        class Connection:
            def execute(self, _sql, _params):
                return Cursor()

        @contextlib.contextmanager
        def fake_connect(_database):
            yield Connection()

        with patch('reporting.database_results.connect', fake_connect), \
             patch('reporting.database_results._database_name', return_value='simulation'), \
             patch('reporting.database_results.read_results', return_value=[]):
            selected = Results(None, '2026-08')

        self.assertEqual(selected.runs[owner]['metric_run_id'], 'shifted')

    def test_selection_strict_month_duplicates_corrupt_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'input.json'
            d = dict(schema_version='1.0', metric_set=m.REPEAT, report_month='2026-08')
            p.write_text(json.dumps(d), encoding='utf-8')
            self.assertEqual(set(m.load_results(directory, '2026-08', {m.REPEAT})[0]), {m.REPEAT})
            with self.assertRaises(ValueError):
                m.load_results(directory, '2026-07', {m.REPEAT})
            p.with_name('duplicate.json').write_text(json.dumps(d), encoding='utf-8')
            with self.assertRaises(ValueError):
                m.load_results(directory, '2026-08', {m.REPEAT})
            p.write_text('{bad', encoding='utf-8')
            with self.assertRaises(ValueError):
                m.load_results(directory, '2026-08', {m.REPEAT})

    def test_city_reorder_and_invalid_numbers(self):
        self.assertEqual(m.city_array(list(range(11)), list(reversed(m.CITIES)), 'city'), list(reversed(range(11))))
        for value in [True, -1, float('nan'), float('inf'), '1']:
            with self.assertRaises(ValueError):
                m.number(value, 'field')
        with self.assertRaises(ValueError):
            m.city_array([0]*11, ['杭州']*11, 'city')
        self.assertIsNone(m.ratio(0, 0))

    def test_qikuan_withdrawal_and_return_do_not_overwrite(self):
        def doc(n, combined=False):
            raw = dict(cities=m.CITIES, acceptedCounts=[10]*11, withdrawalCounts=[n]*11,
                       rates=[n/10]*11, acceptedTotal=110, withdrawalTotal=n*11,
                       overallRate=n/10, reasons={'customer': dict(count=n*11, share=1)})
            if combined:
                raw.update(returnCounts=[1]*11, cancellationCounts=[2]*11)
            return {'ppt_overlay': {'qikuanWithdrawal': raw}}
        data = {}
        audit = dict(missing=[], derived_results={})
        docs = {m.QIKUAN: doc(3, True), m.RETURN: doc(1)}
        m.apply_results(data, docs, audit, None)
        self.assertEqual(data['qikuanWithdrawal']['withdrawalTotal'], 33)
        self.assertEqual(data['qikuanReturn']['withdrawalTotal'], 11)
        docs[m.RETURN]['ppt_overlay']['qikuanWithdrawal']['acceptedCounts'][0] = 9
        with self.assertRaises(ValueError):
            m.apply_results({}, docs, audit, None)

    def test_combined_ratio_includes_only_line_and_qikuan_and_preserves_other_city(self):
        db = Results.__new__(Results)
        code = 'dedicated_line_repeat_complaint_rate'
        def row(kind, dim, n, d):
            return dict(metric_code=code, dimension_type=kind, dimension=dim, numerator=n,
                        denominator=d, metric_run_id='line-run')
        db.rows = {code: [row('city', {'city': c}, 2, 10) for c in m.CITIES] + [row('province', {'scope': '全省'}, 22, 110)]}
        manual = dict(report_month='2026-08', cities={c:dict(numerator=1, denominator=20, rate=.05) for c in m.CITIES},
                      province=dict(numerator=11, denominator=221, rate=11/221))
        manual['cities']['其他'] = dict(numerator=0, denominator=1, rate=0)
        data = {'complaintFault': {'repeat': {'broadbandRates': [.8]*11, 'broadbandAverage': .8}}}
        audit = dict(missing=[], derived_results={})
        m.apply_results(data, {m.REPEAT:manual}, audit, db)
        repeat = data['complaintFault']['repeat']
        self.assertEqual(repeat['totalRates'], [.1]*11)
        self.assertAlmostEqual(repeat['totalAverage'], 33/331)
        self.assertEqual(repeat['broadbandRates'], [.8]*11)
        self.assertEqual(repeat['qikuanRates'], [.05]*11)
        db.rows[code] = []
        m.apply_results(data, {m.REPEAT:manual}, audit, db)
        self.assertIsNone(repeat['totalAverage'])
        self.assertEqual(repeat['totalRates'], [None]*11)

    def test_real_skill_outputs_with_mock_database(self):
        # Integration smoke using local calculated fixtures when available; no database writes.
        if not m.DEFAULT_DIRECTORY.exists():
            self.skipTest('No local manual result fixtures')
        try:
            docs, selected = m.load_results(m.DEFAULT_DIRECTORY, '2026-08')
        except ValueError:
            self.skipTest('Local 2026-08 fixtures incomplete')
        def init(db, database, month):
            db.database='simulation'; db.month=month; db.start='2026-08-01'; db.end='2026-08-31'
            db.rows={}; db.runs={}; db.used={}; db.missing={}
        with patch.object(Results, '__init__', init):
            data=build_data(None,'2026-08',m.DEFAULT_DIRECTORY)
        self.assertEqual(data['withdrawal']['reasonTotal'],294)
        self.assertEqual(data['qikuanWithdrawal']['withdrawalTotal'],10506)
        self.assertEqual(data['qikuanReturn']['withdrawalTotal'],2961)
        self.assertAlmostEqual(data['complaintFault']['repeat']['qikuanAverage'],497/13476)
        self.assertEqual(len(data['dataAudit']['selected_manual_inputs']),5)
        self.assertNotIn('withdrawal.customerCount', [x.get('ppt_field') for x in data['dataAudit']['missing']])
        json.dumps(data, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
