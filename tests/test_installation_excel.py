import sys
import tempfile
import unittest
from pathlib import Path
from openpyxl import load_workbook
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.installation_excel import export_excel
from tools.daily_installation import validate_excel


class ExcelTests(unittest.TestCase):
    def test_summary_and_details(self):
        reports = {}
        for key, n in [('qikuan', 1), ('dedicated_line', 1), ('commercial_customer', 2)]:
            reports[key] = dict(metric_run_id=key, period_start='2026-08-01', period_end='2026-10-29',
                results=[dict(dimension_type=kind, dimension=dim, numerator=n, denominator=2*n)
                         for kind, dim in [('province', {'scope': '全省'}), ('city', {'city': '杭州'})]])
        details = {'numerator': [{'账号': '=001', '地市': '杭州'}],
                   'denominator': [{'账号': '=001', '地市': '杭州'}, {'账号': '0002', '地市': '杭州'}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.xlsx'
            export_excel(reports, path, '测试', detail_loader=lambda _: details)
            validate_excel(path, reports)
            book = load_workbook(path)
            self.assertEqual(book.sheetnames, ['汇总', '专线分子', '专线分母', '企宽分子', '企宽分母'])
            self.assertEqual(book['汇总']['J2'].value, .5)
            self.assertEqual(book['汇总']['H2'].value, 2)
            self.assertEqual(book['汇总']['I2'].value, 4)
            self.assertIsNone(book['汇总']['D4'].value)
            self.assertEqual(book['汇总']['A13'].value, '丽水')
            self.assertEqual(book['企宽分子']['A2'].data_type, 's')
            self.assertEqual(book['企宽分母']['A3'].value, '0002')
            book.close()


if __name__ == '__main__':
    unittest.main()
