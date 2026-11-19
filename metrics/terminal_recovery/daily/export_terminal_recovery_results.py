import json
from openpyxl import Workbook, load_workbook
from metrics.terminal_recovery import terminal_recovery_export_online as calc


def export_results(path, output, batch, start, end, district_rows):
    wb = load_workbook(path, read_only=True)
    try:
        rows = iter(wb[calc.CITY_SUMMARY_SHEET].values)
        header = next(rows)
        counts = {}
        for values in rows:
            row = dict(zip(header, values))
            city = row["地市"]
            if city in calc.CITIES:
                if city in counts:
                    raise ValueError(f"重复地市 {city}")
                counts[city] = (row["应拆回设备数"], row["已拆回设备数量"])
    finally:
        wb.close()
    if set(counts) != set(calc.CITIES):
        raise ValueError("地市汇总不完整")
    counts["浙江省"] = tuple(map(sum, zip(*counts.values())))
    for city, (expected, recovered) in counts.items():
        folder = output / ("省级" if city == "浙江省" else "地市")
        folder.mkdir(parents=True, exist_ok=True)
        result = dict(批次编号=batch, 开始日期=start, 截止日期=end, 区域=city,
                      应拆回设备数=expected, 已拆回设备数=recovered,
                      终端回收率=recovered / expected if expected else None)
        county_results = [
            dict(批次编号=batch, 开始日期=start, 截止日期=end, 区域=row["区县"],
                 应拆回设备数=row["应拆回设备数"], 已拆回设备数=row["已拆回设备数量"],
                 终端回收率=row["终端回收率"])
            for row in district_rows if row["地市"] == city
        ]
        write_result(folder, city, result, county_results)
    for row in district_rows:
        city, county = row["地市"], row["区县"]
        result = dict(批次编号=batch, 开始日期=start, 截止日期=end, 地市=city, 区县=county,
                      应拆回设备数=row["应拆回设备数"], 已拆回设备数=row["已拆回设备数量"],
                      终端回收率=row["终端回收率"])
        folder = output / "区县" / city
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{county}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "区县").mkdir(exist_ok=True)


def write_result(folder, name, result, county_results):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    book = Workbook()
    book.active.append(list(result))
    book.active.append(list(result.values()))
    for county in county_results:
        book.active.append(list(county.values()))
    for row in book.active.iter_rows(min_row=2, min_col=len(result), max_col=len(result)):
        row[0].number_format = "0.00%"
    book.active.freeze_panes = "A2"
    book.save(folder / f"{name}.xlsx")
