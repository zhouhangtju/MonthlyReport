"""验证每日任务结果：先执行每日任务，再运行本文件。"""
import json
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


class DailyInstallationTaskTest(unittest.TestCase):
    def test_today_run_succeeded(self):
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        path = Path(r'C:\.openclaw\outputs') / 'installation_fault_rate' / today / f'{today}.json'
        self.assertTrue(path.exists(), f'今天没有任务结果：{path}')
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report['run_date'], today)
        self.assertEqual(report['status'], 'success', report)
        self.assertEqual(set(report['windows']), {'rolling_three_months', 'calendar_three_months'})
        for result in report['windows'].values():
            self.assertTrue(Path(result['excel_path']).is_file())
            from openpyxl import load_workbook
            workbook = load_workbook(result['excel_path'], read_only=True)
            try:
                self.assertEqual(workbook.sheetnames, ['汇总', '专线分子', '专线分母', '企宽分子', '企宽分母'])
            finally:
                workbook.close()
            self.assertEqual(set(result['metrics']), {'qikuan', 'dedicated_line', 'commercial_customer'})
            for metric in result['metrics'].values():
                self.assertEqual(metric['status'], 'success')
                self.assertTrue(Path(metric['evidence_path']).is_file())
        self.assertTrue(report['collection_complete'])
        self.assertEqual(report['cleanup']['status'], 'success')


if __name__ == '__main__':
    unittest.main()
