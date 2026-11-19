"""File helpers and city/county evidence; original columns are preserved."""
import json
from pathlib import Path
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from storage.importer import iter_rows, read_headers, file_sha256
from metrics.opening import dedicated_line_metrics as dev
from metrics.opening.bycity import dedicated_line_metrics_by_city as citydev


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def workbook(path, rows, headers=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = iter(rows)
    first = next(rows, None)
    headers = list(headers or (first or {}).keys())
    wb = Workbook(write_only=True)
    ws = wb.create_sheet('数据')
    ws.freeze_panes = 'A2'
    ws.append(headers)
    def append(row):
        cells = []
        for h in headers:
            value = row.get(h)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            if isinstance(value, str) and len(value) > 32767:
                raise ValueError(f'Excel单元格超过32767字符：{h}，请检查源数据')
            cell = WriteOnlyCell(ws, value=value)
            if isinstance(value, str):
                cell.data_type = 's'  # imported text must never become an Excel formula
            cells.append(cell)
        ws.append(cells)
    if first is not None:
        append(first)
    for row in rows:
        append(row)
    wb.save(path)


def annotate(row, mapping):
    row = dict(row)
    city = citydev.display_city(row.get('地市', ''))
    row['标准地市'] = city if city in dev.CITY_ORDER else '未归属地市'
    aliases = mapping['aliases'].get(city.removesuffix('市'), {})
    raw = row.get('区县名称')
    county = citydev.standardize_county(raw, row.get('主题'), aliases)
    direct = citydev.standardize_county(raw, '', aliases)
    row['标准区县'] = county
    row['区县清洗依据'] = ('未匹配' if county == citydev.UNASSIGNED_COUNTY else
                         '原区县映射' if direct != citydev.UNASSIGNED_COUNTY else '主题匹配')
    return row


def read_sources(paths, month, mapping, automation=False):
    required = set(dev.READ_COLUMNS)
    if automation:
        required.add('调整类型')
    for path in sorted(map(Path, paths)):
        missing = required - set(read_headers(path, 'orch_opening'))
        if missing:
            raise ValueError(f'{path.name} 缺少字段：{sorted(missing)}')
        for number, row in enumerate(iter_rows(path, 'orch_opening'), 2):
            if dev.row_month(row) != month:
                raise ValueError(f'{path.name} 第{number}行结束时间不属于{month}')
            row = annotate(row, mapping)
            row['来源文件'] = path.name
            row['来源行号'] = number
            yield row


def split_workbooks(directory, rows, name):
    """One province workbook and one per city, including explicit unassigned rows."""
    directory = Path(directory)
    headers = list(dict.fromkeys(k for r in rows for k in r))
    workbook(directory / f'全省_{name}.xlsx', rows, headers)
    for city in [*dev.CITY_ORDER, '未归属地市']:
        selected = [r for r in rows if r.get('标准地市', r.get('地市')) == city]
        if city == '未归属地市' and not selected:
            continue
        workbook(directory / '地市' / city / f'{name}.xlsx', selected, headers)


def batches(rows, size=5000):
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def hashes(directory):
    return {str(p.relative_to(directory)): file_sha256(p)
            for p in Path(directory).rglob('*') if p.is_file() and p.name != 'manifest.json'}
