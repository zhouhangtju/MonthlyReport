from collections import Counter
from pathlib import Path

from openpyxl import Workbook, load_workbook
from metrics.terminal_recovery import terminal_recovery_export_online as calc


def distribute(sheet, targets, summary=False):
    sheet.reset_dimensions()
    rows = iter(sheet.values)
    header = next(rows)
    names = [str(v).strip() for v in header]
    keys = [names.index(k) for k in ("安装地市", "地市", "所属地市") if k in names]
    if not keys:
        raise ValueError(f"{sheet.title}缺少地市列")
    for target in targets.values():
        target.append(header)
    counts = Counter()
    for row in rows:
        if not any(v is not None for v in row):
            continue
        labels = {str(v).strip() for v in row if v is not None and str(v).strip()}
        if labels and labels <= {"有SN", "无SN"}:
            for target in targets.values():
                target.append(row)
            continue
        city = calc.normalize_city(next((row[i] for i in keys if i < len(row) and str(row[i] or "").strip()), ""))
        if city not in targets:
            counts["未归属"] += 1
            continue
        if summary:
            row = list(row)
            row[7] = row[6] / row[5] if row[5] else None
        targets[city].append(row)
        counts[city] += 1
    return counts


def split_raw(raw, paths):
    for path in paths:
        wb = load_workbook(path, read_only=True)
        try:
            books = {city: Workbook(write_only=True) for city in calc.CITIES}
            targets = {city: book.create_sheet(wb.active.title) for city, book in books.items()}
            counts = distribute(wb.active, targets)
            for city, book in books.items():
                dest = raw / "地市" / city / path.relative_to(raw)
                dest.parent.mkdir(parents=True, exist_ok=True)
                book.save(dest)
            print(path.name, dict(counts), flush=True)
        finally:
            wb.close()


def split_intermediate(path):
    dest = path.parent / "地市"
    dest.mkdir()
    books = {city: Workbook() for city in calc.CITIES}
    for book in books.values():
        book.remove(book.active)
    wb = load_workbook(path, read_only=True)
    try:
        for sheet in wb:
            if sheet.title in ("物料名称表", "全省物资基准库", calc.DETAIL_SUMMARY_SHEET):
                continue
            targets = {city: book.create_sheet(sheet.title) for city, book in books.items()}
            distribute(sheet, targets, sheet.title == calc.CITY_SUMMARY_SHEET)
        for city, book in books.items():
            calc.build_detail_summary_sheet(book)
            book.save(dest / f"{city}_终端回收率中间结果.xlsx")
    finally:
        wb.close()



def annotate(sheet, mapping, kind, orders=None):
    from metrics.terminal_recovery import districts
    headers = [districts.text(c.value) for c in sheet[1]]
    column = len(headers) + 1
    sheet.cell(1, column, "标准区县")
    sheet.cell(1, column + 1, "区县处理依据")
    for cells in sheet.iter_rows(min_row=2, max_col=len(headers)):
        row = dict(zip(headers, (cell.value for cell in cells)))
        values = {districts.text(v) for v in row.values()} - {""}
        if not values or values <= {"有SN", "无SN"}:
            continue
        if kind in ("line", "service"):
            city, county, reason, _ = districts.clean_row(row, mapping, kind == "service")
            if orders is not None:
                key = (calc.normalize_city(city), districts.text(row.get("工单号")))
                orders.setdefault(key, set()).add(county)
        elif kind == "orders":
            candidates = orders.get((calc.normalize_city(row.get("地市")), districts.text(row.get("工单号"))), set())
            county = next(iter(candidates)) if len(candidates) == 1 else ""
            reason = "拆机清单匹配" if county else "未匹配或歧义"
        else:
            original = districts.text(row.get("区县"))
            county = mapping.match("开发区" if original == "南城区" else original, row.get("地市"))
            reason = "区县映射" if county else "未匹配或歧义"
        sheet.cell(cells[0].row, column, county)
        sheet.cell(cells[0].row, column + 1, reason)


def clean_sources(paths, mapping):
    for path, kind in zip(paths, ("line", "service", "inbound")):
        wb = load_workbook(path)
        annotate(wb.active, mapping, kind)
        wb.save(path)
        wb.close()


def clean_intermediate(path, mapping, audit_path):
    wb = load_workbook(path)
    orders = {}
    for name, kind in ((calc.LINE_SHEET_NAME, "line"), (calc.SERVICE_SHEET_NAME, "service"),
                       (calc.REMOVAL_SUMMARY_SHEET_NAME, "orders")):
        annotate(wb[name], mapping, kind, orders)
    for name in (calc.RETURN_DEVICE_SHEET_NAME, calc.MATCHED_RETURN_SHEET, "sheet2", "sheet3"):
        annotate(wb[name], mapping, "inbound")
    audit = load_workbook(audit_path, read_only=True)
    try:
        for name in ("拆机区县清洗明细", "回收区县明细", "区县汇总"):
            target = wb.create_sheet(name)
            for row in audit[name].values:
                target.append(row)
    finally:
        audit.close()
    wb.save(path)
    wb.close()
