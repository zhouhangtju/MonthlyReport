"""Export persisted installation metrics and their exact source details to XLSX."""
import json
from pathlib import Path

CITIES = ['杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴', '金华', '衢州', '舟山', '台州', '丽水']
METRICS = [('dedicated_line', '专线'), ('qikuan', '企宽'), ('commercial_customer', '商客')]


def load_details(run_id):
    from storage.database import connect
    with connect(None) as connection:
        rows = connection.execute(
            "SELECT detail_role, source_dataset_code, source_record_id, detail_data FROM ads_metric_detail WHERE metric_run_id=? "
            "AND detail_role IN ('numerator', 'denominator') ORDER BY detail_id", (run_id,)).fetchall()
    result = {'numerator': [], 'denominator': []}
    for row in rows:
        result[row['detail_role']].append({
            **json.loads(row['detail_data']),
            '来源数据集': row['source_dataset_code'],
            '原始记录ID': str(row['source_record_id']),
        })
    return result


def export_excel(reports, output, label, detail_loader=load_details):
    # Runtime exporter uses the project's existing openpyxl dependency.
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.cell import WriteOnlyCell
    indexes = {}
    for key, _ in METRICS:
        indexes[key] = {('全省' if r['dimension_type'] == 'province' else r['dimension']['city']): r
                        for r in reports[key]['results']}
        if '全省' not in indexes[key]:
            raise ValueError(f'{key}: 缺少全省结果')
    period = {(r['period_start'], r['period_end']) for r in reports.values()}
    if len(period) != 1:
        raise ValueError('指标统计范围不一致')
    start, end = next(iter(period))
    wb = Workbook(write_only=True)
    def sheet(name, headers):
        ws = wb.create_sheet(name)
        ws.freeze_panes = 'B2'
        for i, _ in enumerate(headers, 1):
            from openpyxl.utils import get_column_letter
            ws.column_dimensions[get_column_letter(i)].width = 24
        cells = []
        for value in headers:
            cell = WriteOnlyCell(ws, value=value)
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='165D91')
            cell.alignment = Alignment(wrap_text=True)
            cells.append(cell)
        ws.append(cells)
        return ws
    def append(ws, values, rates=()):
        cells = []
        for i, value in enumerate(values):
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            cell = WriteOnlyCell(ws, value=value)
            if isinstance(value, str):
                cell.data_type = 's'  # Preserve identifiers and prevent source text becoming formulas.
            if i in rates:
                cell.number_format = '0.00%'
            cells.append(cell)
        ws.append(cells)
    ws = sheet('汇总', ['地市'] + [f'{label}{field}' for _, label in METRICS for field in ('分子', '分母', '报障率')])
    extra = sorted(set().union(*(set(v) for v in indexes.values())) - set(CITIES) - {'全省'})
    for city in ['全省', *CITIES, *extra]:
        values = [city]
        for key, _ in METRICS:
            row = indexes[key].get(city, {})
            n, d = row.get('numerator', 0), row.get('denominator', 0)
            values.extend([n, d, n / d if d else None])
        append(ws, values, (3, 6, 9))
    append(ws, [f'{label}：{start} 至 {end}（含首尾）；分母为0时报障率留空。'])
    append(ws, ['商客分子、分母分别为专线与企宽之和；明细见对应四张清单。'])
    append(ws, ['企宽沿用现有口径：新装派单时间不二次过滤；投诉时间限制在统计期内。'])
    for key, title in METRICS[:2]:
        details = detail_loader(reports[key]['metric_run_id'])
        for role, suffix in [('numerator', '分子'), ('denominator', '分母')]:
            rows = details[role]
            if len(rows) != indexes[key]['全省'][role]:
                raise ValueError(f'{title}{suffix}明细数量与指标不一致，停止导出')
            headers = list(dict.fromkeys(k for row in rows for k in row if not k.startswith('_'))) or ['无记录']
            if len(rows) > 1048575:
                raise ValueError(f'{title}{suffix}超过Excel单表行数限制')
            detail_sheet = sheet(title + suffix, headers)
            for row in rows:
                append(detail_sheet, [row.get(k) for k in headers])
            detail_sheet.auto_filter.ref = f'A1:{__import__("openpyxl").utils.get_column_letter(len(headers))}{len(rows)+1}'
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp.xlsx')
    wb.save(temporary)
    temporary.replace(output)
    return str(output)
