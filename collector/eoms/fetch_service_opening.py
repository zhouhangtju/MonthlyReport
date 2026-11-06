"""EOMS服务类已完成开通工单；与终端回收拆除数据独立。"""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from collector.eoms import eoms_export_qiwan_auto_login as shared

CODE='eoms_service_opening_order'
OUTPUT_DIR=Path(__file__).resolve().parents[2]/'data/raw/eoms'/CODE

def collect(start_date,end_date,*,mode='both',database=None,output_dir=OUTPUT_DIR,reuse_existing=False,refresh=False):
    month=shared.validate_dates(start_date,end_date)
    if mode not in {'file','database','both'}:raise ValueError('Unsupported mode')
    filename=f'服务类产品支撑开通工单_{month}.xlsx'
    cached=shared.covered_result({CODE:Path(output_dir)/filename},start_date,end_date,mode,database,refresh,reuse_existing)
    if cached is not None:return cached
    with shared.download_directory(mode,output_dir,reuse_existing) as target:
        path=target/filename
        if not reuse_existing:
            exported=Path(shared.export_qiwan(start_date+' 00:00:00',end_date+' 23:59:59',service_type='全量',output_dir=str(target),operate_type='开通'))
            exported.replace(path)
        return shared.finish_exports({CODE:path},start_date,end_date,mode,database)

def main():
    parser=shared.parser('EOMS服务类开通工单取数和入库')
    parser.set_defaults(output_dir=OUTPUT_DIR)
    print(json.dumps(collect(**vars(parser.parse_args())),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
