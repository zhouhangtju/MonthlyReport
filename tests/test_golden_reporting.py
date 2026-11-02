import unittest
from unittest.mock import patch
from reporting.golden_metrics import number, province, build_golden
class GoldenReportingTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(number('0.2417(14分30秒)'),.2417)
        self.assertEqual(number('100%'),100)
        self.assertIsNone(number(''))
        with self.assertRaises(ValueError): number('未知')
    def test_province(self):
        self.assertEqual(province([{'地市':'全省','有无资源开通场景':'不区分','接入方式':'不区分','x':1},{'地市':'杭州'}],'transport')['x'],1)
        with self.assertRaises(ValueError): province([{'地市':'全省'}]*2,'cloud')
    def test_missing_and_cross_year(self):
        class Cursor:
            def fetchone(self): return None
        class Connection:
            def __init__(self): self.calls=[]
            def execute(self,sql,args): self.calls.append(args); return Cursor()
        c=Connection();result=build_golden('2026-01',c)
        self.assertEqual(c.calls[0],('orch_golden_cloud','2025-12-26','2026-01-25'))
        self.assertEqual(result['groups'][0]['metrics'][0]['values'],[None])
    def test_thresholds(self):
        class Cursor:
            def fetchone(self): return {'run_id':'r'}
        class Connection:
            def execute(self,*args): return Cursor()
        row={'地市':'全省','业务开通前端退单率':'6%','线上配置环节平均时长':'4(4时)','资源分配成功率':'90%','装机一次上门率':'94%'}
        with patch('reporting.golden_metrics.read_records',return_value=[row]):
            result=build_golden('2026-01',Connection())
        self.assertEqual([m['failed'][0] for m in result['groups'][0]['metrics']],[True,False,False,True])
