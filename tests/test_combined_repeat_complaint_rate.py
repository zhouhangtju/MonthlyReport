import unittest

from metrics.complaint import combined_repeat_complaint_rate as combined


def stored_document(code, province_rate, city_rates):
    results = [{
        'metric_code': code,
        'dimension_type': 'province',
        'dimension': {'scope': '全省'},
        'metric_value': province_rate,
    }]
    results.extend({
        'metric_code': code,
        'dimension_type': 'city',
        'dimension': {'city': city},
        'metric_value': city_rates[city],
    } for city in combined.CITIES)
    return {'metric_code': code, 'results': results}


class CombinedRepeatComplaintRateTest(unittest.TestCase):
    def test_calculates_province_cities_and_top_three(self):
        line_rates = {city: .01 + i / 1000 for i, city in enumerate(combined.CITIES)}
        qianliyan_rates = {city: .02 + i / 1000 for i, city in enumerate(combined.CITIES)}
        qikuan_rates = {city: .03 + i / 1000 for i, city in enumerate(combined.CITIES)}
        line = stored_document(combined.LINE_CODE, .01, line_rates)
        qianliyan = stored_document(combined.QIANLIYAN_CODE, .02, qianliyan_rates)
        qikuan = {
            'metric_set': combined.QIKUAN_CODE,
            'report_month': '2026-08',
            'province': {'rate': .03},
            'cities': {city: {'rate': value} for city, value in qikuan_rates.items()},
        }
        result = combined.calculate(line, qianliyan, qikuan, '2026-08')
        self.assertAlmostEqual(result['province']['rate'], .02)
        self.assertAlmostEqual(result['cities']['杭州']['rate'], .02)
        self.assertEqual(result['top_cities'], ['舟山', '丽水', '衢州'])
        self.assertEqual(result['metric_set'], combined.COMBINED_CODE)

    def test_rejects_missing_component_city(self):
        rates = {city: .01 for city in combined.CITIES}
        line = stored_document(combined.LINE_CODE, .01, rates)
        qianliyan = stored_document(combined.QIANLIYAN_CODE, .01, rates)
        qianliyan['results'] = [row for row in qianliyan['results']
                                if row.get('dimension', {}).get('city') != '舟山']
        qikuan = {
            'metric_set': combined.QIKUAN_CODE,
            'report_month': '2026-08',
            'province': {'rate': .01},
            'cities': {city: {'rate': .01} for city in combined.CITIES},
        }
        with self.assertRaises(ValueError):
            combined.calculate(line, qianliyan, qikuan, '2026-08')


if __name__ == '__main__':
    unittest.main()
