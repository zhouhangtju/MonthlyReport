"""装机出库利旧中间表：开通清单、物料明细、匹配明细和地区汇总。"""
import argparse
import calendar
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import uuid

# 使用标准 XML 后端，兼容本地 Anaconda 的 lxml 环境。
os.environ.setdefault('OPENPYXL_LXML', 'False')
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from storage.database import connect

NAMES = ['开通清单', '物料确认退库明细', '匹配', 'sheet5']
QUANTITIES = ['新物资数量有SN', '返修物资数量有SN', '回收物资数量有SN']
API_QUANTITIES = ['newSnNum', 'repairSnNum', 'recoverySnNum']
EXCLUDED = {'行业视频行业版平台基础', '行业视频-小微版'}
SERVICES = {'安全终端部署服务', 'E企组网'}
ZERO_MATERIALS = {'共用设备拆回标签', '在网业务标签', '无设备标签'}
CATEGORIES = {
    '互联网专线': '互联网专线', '行业视频-行业版': '视频监控',
    '行业视频MV专线': '视频监控', '视频监控': '视频监控',
    'MPLS VPN专线': 'MPLS VPN专线', '固话': '固话', '电路出租': '电路出租',
    '安全终端部署服务': '服务类', 'E企组网': '服务类',
}


def dump(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def period(month):
    dt = datetime.strptime(month, '%Y-%m')
    if dt.strftime('%Y-%m') != month:
        raise ValueError('月份格式必须为 YYYY-MM')
    return month + '-01', f'{month}-{calendar.monthrange(dt.year, dt.month)[1]:02d}'


def number(value):
    if value is None or text(value) == '':
        return Decimal(0)
    if isinstance(value, bool):
        raise ValueError('数量不能为布尔值')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'非法数量：{value!r}') from exc
    if not result.is_finite():
        raise ValueError(f'非法数量：{value!r}')
    return result


def read_table(content):
    if content.startswith(b'\xd0\xcf\x11\xe0'):
        import xlrd
        wb = xlrd.open_workbook(file_contents=content)
        try:
            ws = wb.sheet_by_index(0)
            rows = []
            for i in range(ws.nrows):
                rows.append([
                    xlrd.xldate.xldate_as_datetime(c.value, wb.datemode)
                    if c.ctype == xlrd.XL_CELL_DATE else c.value
                    for c in ws.row(i)
                ])
        finally:
            wb.release_resources()
    else:
        wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
        try:
            rows = list(wb.active.values)
        finally:
            wb.close()
    if not rows:
        raise ValueError('输入工作表为空')
    headers = [text(h) for h in rows[0]]
    if not all(headers) or len(set(headers)) != len(headers):
        raise ValueError('输入存在空白或重复表头')
    return headers, [list(r) for r in rows[1:] if any(text(v) for v in r)]


def require(table, columns, label):
    missing = set(columns) - set(table[0])
    if missing:
        raise ValueError(f'{label}缺列：{sorted(missing)}')


def load_source(path, codes, month):
    if path:
        content = path.read_bytes()
        source = {'path': str(path.resolve()), 'sha256': hashlib.sha256(content).hexdigest()}
    else:
        start, end = period(month)
        placeholders = ','.join('?' for _ in codes)
        with connect() as c:
            source = c.execute(f'''SELECT snapshot_id,dataset_code,etl_run_id,filename,
                sha256,workbook,created_at FROM tr_source_snapshot
                WHERE dataset_code IN ({placeholders}) AND period_start=? AND period_end=?
                ORDER BY created_at DESC,snapshot_id DESC LIMIT 1''', (*codes, start, end)).fetchone()
        if not source:
            raise ValueError(f'{month} 缺少 {codes} 快照，请先采集或指定对应文件参数')
        content = bytes(source.pop('workbook'))
        if hashlib.sha256(content).hexdigest() != source['sha256']:
            raise ValueError(f'源快照校验失败：{source["snapshot_id"]}')
    return read_table(content), source


def calculate(opening, eoms, outbound, materials, baseline):
    require(opening, ['工单号', '业务类型'], '开通清单')
    require(eoms, ['工单号', '服务类别'], 'EMOS开通清单')
    require(outbound, ['关联单据号', '物料名称', '地市', '区县'], '出库明细')
    require(materials, ['物料名称', '划分类型'], '物料名称表')
    require(baseline, ['物料名称', '分类'], '全省物资基准库')
    audit = {'opening_input': len(opening[1]), 'eoms_input': len(eoms[1]),
             'outbound_input': len(outbound[1]), 'opening_excluded': 0,
             'eoms_excluded': 0, 'duplicate_order_rows': 0,
             'blank_order_rows': 0, 'unmatched_material_rows': 0,
             'unmatched_order_rows': 0, 'unmatched_category_rows': 0}
    orders, lookup = [], {}
    for table, column, is_service in [(opening, '业务类型', False), (eoms, '服务类别', True)]:
        for values in table[1]:
            row = dict(zip(table[0], values))
            business = text(row[column])
            if (is_service and business not in SERVICES) or (not is_service and business in EXCLUDED):
                audit['eoms_excluded' if is_service else 'opening_excluded'] += 1
                continue
            key = text(row['工单号'])
            category = CATEGORIES.get(business, '其他专线')
            orders.append([key or None, business or None, category])
            if not key:
                audit['blank_order_rows'] += 1
                continue
            if key in lookup:
                if lookup[key] != category:
                    raise ValueError(f'工单号业务类别冲突：{key}，{lookup[key]} / {category}')
                audit['duplicate_order_rows'] += 1
            lookup[key] = category

    # 与终端回收一致：按去空格后的物料名称匹配，重复键取首条。
    material_lookup, category_lookup = {}, {}
    for values in materials[1]:
        row = dict(zip(materials[0], values)); key = text(row['物料名称'])
        if key and key not in material_lookup:
            material_lookup[key] = (row['物料名称'], 0 if key in ZERO_MATERIALS else row['划分类型'])
    for values in baseline[1]:
        row = dict(zip(baseline[0], values)); key = text(row['物料名称'])
        if key and key not in category_lookup:
            category_lookup[key] = row['分类']

    headers = list(outbound[0])
    added = ['物料名称匹配', '型号匹配', '分类', '关联单据号匹配', '业务类别']
    if set(added) & set(headers):
        raise ValueError('请使用尚未加工的出库明细')
    aliases = []
    for target, api in zip(QUANTITIES, API_QUANTITIES):
        if target not in headers:
            if api not in headers:
                raise ValueError(f'出库明细缺少 {target}/{api}；不能使用旧版简写数量字段替代')
            headers.append(target); aliases.append((target, api))
    details, matched = [], []
    city, county = defaultdict(lambda: [Decimal(0)] * 3), defaultdict(lambda: [Decimal(0)] * 3)
    total = [Decimal(0)] * 3
    for index, values in enumerate(outbound[1], 2):
        row = dict(zip(outbound[0], values))
        for target, api in aliases:
            row[target] = row[api]
        try:
            quantities = [number(row[q]) for q in QUANTITIES]
        except ValueError as exc:
            raise ValueError(f'出库明细第 {index} 行：{exc}') from exc
        key = text(row['物料名称'])
        material = material_lookup.get(key, (None, None))
        detail = [row.get(h) for h in headers] + [*material, category_lookup.get(key)]
        details.append(detail)
        if key not in category_lookup:
            audit['unmatched_category_rows'] += 1
        if text(material[0]) in ('', '#N/A'):
            audit['unmatched_material_rows'] += 1
            continue
        order = text(row['关联单据号'])
        business = lookup.get(order)
        if business is None:
            audit['unmatched_order_rows'] += 1
        matched.append(detail + [order if business is not None else None, business])
        city_key = text(row['地市']) or None
        county_key = (city_key, text(row['区县']) or None)
        for i, quantity in enumerate(quantities):
            city[city_key][i] += quantity
            county[county_key][i] += quantity
            total[i] += quantity
    summary = []
    for key in sorted(city, key=lambda k: k or ''):
        summary.append(['地市', key, None, *city[key]])
    for key in sorted(county, key=lambda k: (k[0] or '', k[1] or '')):
        summary.append(['区县', *key, *county[key]])
    city_total = [sum((v[i] for v in city.values()), Decimal(0)) for i in range(3)]
    county_total = [sum((v[i] for v in county.values()), Decimal(0)) for i in range(3)]
    if total != city_total or total != county_total:
        raise ValueError('地区汇总与匹配明细数量不一致')
    detail_headers = headers + added[:3]
    sheets = [(['工单号', '业务类别1', '业务类别2'], orders),
              (detail_headers, details), (detail_headers + added[3:], matched),
              (['统计层级', '地市', '区县'] + QUANTITIES, summary)]
    audit.update(sheet_rows={n: len(t[1]) for n, t in zip(NAMES, sheets)},
                 matched_totals=dict(zip(QUANTITIES, total)),
                 city_totals=dict(zip(QUANTITIES, city_total)),
                 county_totals=dict(zip(QUANTITIES, county_total)))
    return sheets, audit


def export(path, sheets):
    wb = Workbook(write_only=True)
    for name, (headers, rows) in zip(NAMES, sheets):
        ws = wb.create_sheet(name); ws.freeze_panes = 'A2'
        for i, header in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(i)].width = 24 if '数量' in header else 20
        cells = []
        for header in headers:
            cell = WriteOnlyCell(ws, value=header)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='176B87'); cells.append(cell)
        ws.append(cells)
        for row in rows:
            cells = []
            for value in row:
                cell = WriteOnlyCell(ws, value=float(value) if isinstance(value, Decimal) else value)
                if isinstance(value, str):
                    cell.data_type = 's'
                cells.append(cell)
            ws.append(cells)
        ws.auto_filter.ref = f'A1:{get_column_letter(len(headers))}{len(rows)+1}'
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path); wb.close()
    check = load_workbook(path, read_only=True, data_only=True)
    try:
        if check.sheetnames != NAMES:
            raise ValueError('输出工作表名称校验失败')
        for name, (headers, rows) in zip(NAMES, sheets):
            iterator = check[name].values
            if list(next(iterator)) != headers or sum(1 for _ in iterator) != len(rows):
                raise ValueError(f'输出工作表校验失败：{name}')
    finally:
        check.close()


def save(month, sheets, audit, sources):
    run_id = 'installation_reuse_' + uuid.uuid4().hex
    start, end = period(month)
    schema = (ROOT / 'sql/create_terminal_installation_reuse.sql').read_text(encoding='utf-8')
    with connect() as c:
        for statement in schema.split(';'):
            if statement.strip():
                c.execute(statement)
    now = datetime.now().isoformat()
    with connect() as c:
        c.execute('''INSERT INTO metric_run(metric_run_id,metric_code,metric_version,
            period_start,period_end,started_at,finished_at,status,source_runs)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (run_id, 'terminal_installation_reuse', '1.0', start, end, now, now, 'success', dump(sources)))
        c.execute('''INSERT INTO terminal_installation_reuse_audit
            (metric_run_id,report_month,sources,audit,sheet_headers) VALUES (?,?,?,?,?)''',
            (run_id, month, dump(sources), dump(audit), dump({n: t[0] for n, t in zip(NAMES, sheets)})))
        sql = '''INSERT INTO intermediate_terminal_installation_reuse
            (metric_run_id,sheet_name,source_row_number,city,county,business_category,
             material_category,statistic_level,new_sn_quantity,repair_sn_quantity,recovery_sn_quantity,row_data)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)'''
        for name, (headers, rows) in zip(NAMES, sheets):
            batch = []
            for index, values in enumerate(rows, 2):
                row = dict(zip(headers, values))
                quantities = [number(row[q]) if q in row else None for q in QUANTITIES]
                batch.append((run_id, name, index, row.get('地市'), row.get('区县'),
                              row.get('业务类别', row.get('业务类别2')), row.get('型号匹配'),
                              row.get('统计层级'), *quantities, dump(values)))
                if len(batch) == 500:
                    c.executemany(sql, batch); batch = []
            if batch:
                c.executemany(sql, batch)
    return run_id


def run(args):
    period(args.month)
    specs = [
        (args.opening, ['integration_opening']),
        (args.eoms, ['eoms_service_opening_order']),
        (args.outbound, ['integration_terminal_outbound_export', 'integration_terminal_outbound']),
        (args.material_names, ['terminal_material_names']),
        (args.material_baseline, ['integration_material_baseline']),
    ]
    tables, sources = [], []
    for path, codes in specs:
        table, source = load_source(path, codes, args.month)
        tables.append(table); sources.append(source)
    sheets, audit = calculate(*tables)
    result = {'month': args.month, 'audit': audit, 'sources': sources}
    if args.mode != 'database':
        path = args.output_dir / f'装机出库利旧中间结果_{args.month}.xlsx'
        export(path, sheets); result['file'] = str(path.resolve())
    if args.mode != 'file':
        result['metric_run_id'] = save(args.month, sheets, audit, sources)
    if args.mode != 'database':
        (args.output_dir / f'装机出库利旧审计_{args.month}.json').write_text(dump(result), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month', required=True)
    for option in ['opening', 'eoms', 'outbound', 'material-names', 'material-baseline']:
        parser.add_argument('--' + option, type=Path, help='可选Excel文件；默认读取该月数据库快照')
    parser.add_argument('--mode', choices=['file', 'database', 'both'], default='both')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/terminal_installation_reuse')
    print(dump(run(parser.parse_args())))


if __name__ == '__main__':
    main()
