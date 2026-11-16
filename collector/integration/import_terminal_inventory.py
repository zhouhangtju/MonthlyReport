"""Import an offline stock workbook and its original snapshot; no network login."""
import argparse
import calendar
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def collect(month, source):
    from openpyxl import load_workbook
    from config.datasets import get_dataset
    from storage.importer import import_file
    from storage.terminal_recovery import save_source

    period = datetime.strptime(month, '%Y-%m')
    if period.strftime('%Y-%m') != month:
        raise ValueError('月份必须为 YYYY-MM')
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        rows = workbook.active.iter_rows(values_only=True)
        headers = next(rows, ())
        required = {'物料名称', '型号', '地市', '返修物资-正常SN', '回收物资-正常SN'}
        missing = required - set(headers)
        if missing:
            raise ValueError('库存表缺列：' + str(sorted(missing)))
        if any(not isinstance(h, str) or not h.strip() for h in headers):
            raise ValueError('库存表存在空表头')
        if len(set(h.strip().casefold() for h in headers)) != len(headers):
            raise ValueError('库存表存在重复表头')
        if {'物料分类', '不可利旧设备型号', '可利旧数量'} & set(headers):
            raise ValueError('请上传未加工的原始库存表')
        count = sum(1 for row in rows if any(v not in (None, '') for v in row))
        if not count:
            raise ValueError('库存表没有数据')
    finally:
        workbook.close()
    start = month + '-01'
    end = f'{month}-{calendar.monthrange(period.year, period.month)[1]:02d}'
    # Preserve the supplied business columns; the shared importer handles schema extension.
    etl = import_file(None, get_dataset('integration_terminal_inventory'), source,
                      period_start=start, period_end=end)
    if etl['failed']:
        raise RuntimeError(f"库存导入有 {etl['failed']} 行失败，未保存完整采集快照；请检查ETL审计")
    snapshots = {}
    for code in ('integration_terminal_inventory', 'integration_terminal_inventory_export'):
        snapshots[code] = save_source(None, code, source, start, end, etl['run_id'])
    return {'collection_method': 'offline_workbook_simulation', 'month': month,
            'source': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'record_count': count, 'etl': etl, 'snapshots': snapshots}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month', required=True, help='模拟数据归属月份 YYYY-MM')
    parser.add_argument('--input', type=Path, default=ROOT / 'data/offline_data/库存统计表(在库)-1793867132253.xlsx')
    args = parser.parse_args()
    print(json.dumps(collect(args.month, args.input), ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
