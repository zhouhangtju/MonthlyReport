import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from storage.importer import iter_rows, read_headers
ROOT = Path(__file__).resolve().parents[1]
class GoldenTest(unittest.TestCase):
    def test_samples(self):
        for kind,title,count,columns in [('transport','传输L4工单统计报表',10,26),('internet','互联网L4工单统计报表',12,25),('cloud','云网业务综合指标报表',7,24)]:
            code='orch_golden_'+kind
            path=ROOT/'payload'/f'【{title}】查询结果.xls'
            self.assertEqual(len(read_headers(path,code)),columns)
            rows=list(iter_rows(path,code))
            self.assertEqual(len(rows),count)
            self.assertEqual(rows[0]['地市'],'全省')
    def test_whole_period_file_mode(self):
        from collector.orchestration.golden_client import collect
        class Response:
            headers={}
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def raise_for_status(self): pass
            def iter_content(self,**kwargs): yield (ROOT/'payload/【云网业务综合指标报表】查询结果.xls').read_bytes()
        class Session:
            def __init__(self): self.calls=[]
            def post(self,url,**kwargs): self.calls.append(kwargs); return Response()
        session=Session()
        with tempfile.TemporaryDirectory() as d, patch('collector.orchestration.golden_client.initialize',side_effect=AssertionError('database used')):
            result=collect('cloud','2026-09-26','2026-10-25',mode='file',output_dir=Path(d),session=session)
            self.assertEqual(len(session.calls),1)
            self.assertTrue(Path(result[0]['file']).exists())

    def test_cloud_values_are_preserved(self):
        row=next(iter_rows(ROOT/'payload/【云网业务综合指标报表】查询结果.xls','orch_golden_cloud'))
        self.assertEqual(row['端到端业务开通平均时长'],'25.4382(1天1时26分17秒)')
        self.assertEqual(row['资源分配成功率'],'100%')
        self.assertEqual(row['资源分配成功率(5分钟维度)'],'')

    def test_database_exact_skip(self):
        from collector.orchestration.golden_client import collect
        with patch('collector.orchestration.golden_client.has_snapshot',return_value=True), patch('collector.orchestration.golden_client.download',side_effect=AssertionError('download')):
            result=collect('cloud','2026-09-26','2026-10-25',mode='database',session=object())
        self.assertTrue(result[0]['skipped'])

    def test_database_tempfile_cleanup_and_both_keeps_file(self):
        from collector.orchestration.golden_client import collect
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def raise_for_status(self): pass
            def iter_content(self,**kwargs): yield (ROOT/'payload/【云网业务综合指标报表】查询结果.xls').read_bytes()
        class Session:
            def post(self,*args,**kwargs): return Response()
        imported=[]
        def importer(db,dataset,path,**kwargs):
            self.assertTrue(path.exists()); imported.append(path)
            self.assertEqual(kwargs,{'period_start':'2026-09-26','period_end':'2026-10-25'})
            return {'read':7,'failed':0}
        with tempfile.TemporaryDirectory() as d, patch('collector.orchestration.golden_client.has_snapshot',return_value=False),patch('collector.orchestration.golden_client.import_file',side_effect=importer):
            result=collect('cloud','2026-09-26','2026-10-25',mode='database',session=Session())
            self.assertIsNone(result[0]['file']); self.assertFalse(imported[-1].exists())
            result=collect('cloud','2026-09-26','2026-10-25',mode='both',output_dir=Path(d),session=Session())
            self.assertTrue(Path(result[0]['file']).exists())

    def test_error_response_cleans_partial(self):
        from collector.orchestration.golden_client import collect
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def raise_for_status(self): pass
            def iter_content(self,**kwargs): yield b'{"error":"login"}'
        class Session:
            def post(self,*args,**kwargs): return Response()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                collect('cloud','2026-09-26','2026-10-25',mode='file',output_dir=Path(d),session=Session())
            self.assertEqual(list(Path(d).rglob('*.part')),[])
            self.assertEqual(list(Path(d).rglob('*.xls')),[])

    def test_samples_stage_for_period_import(self):
        from storage.importer import _stage
        from config.datasets import get_dataset
        for kind,title,count in [('transport','传输L4工单统计报表',10),('internet','互联网L4工单统计报表',12),('cloud','云网业务综合指标报表',7)]:
            counts={'read':0,'failed':0,'duplicates':0}
            with tempfile.TemporaryFile(mode='w+',encoding='utf-8') as staged:
                _stage(ROOT/'payload'/f'【{title}】查询结果.xls',get_dataset('orch_golden_'+kind),staged,counts,[])
                self.assertEqual(len(staged.readlines()),count)
            self.assertEqual(counts['failed'],0)

    def test_snapshot_lookup_uses_exact_bounds(self):
        from collector.orchestration.golden_client import has_snapshot
        from unittest.mock import MagicMock
        connection=MagicMock()
        connection.execute.return_value.fetchone.return_value={'run_id':'x'}
        context=MagicMock()
        context.__enter__.return_value=connection
        with patch('collector.orchestration.golden_client.initialize'),patch('collector.orchestration.golden_client.connect',return_value=context):
            self.assertTrue(has_snapshot('orch_golden_cloud','2026-09-26','2026-10-25'))
        sql,args=connection.execute.call_args.args
        self.assertIn('b.period_start=? AND b.period_end=?',sql)
        self.assertEqual(args,('orch_golden_cloud','2026-09-26','2026-10-25'))
