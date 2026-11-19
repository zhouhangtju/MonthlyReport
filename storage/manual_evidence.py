"""Archive manual withdrawal source evidence by province and city."""
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

CITIES = ["杭州", "嘉兴", "宁波", "温州", "金华", "绍兴", "湖州", "台州", "衢州", "丽水", "舟山"]
DEFAULT_ARCHIVE = Path(r"D:\dev-projects\openclaw_data\outputs\withdrawal")


def source_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()



def export_results(result, directory):
    from openpyxl import Workbook
    directory.mkdir()
    line = result["metric_set"] == "dedicated_line_withdrawal_reasons_by_city"
    overlay = result["ppt_overlay"]
    for city in ["全省", *CITIES]:
        summary = []
        if line:
            data = overlay["withdrawal"]
            cities = result["dimensions"]["cities"]
            for category, prefix in [("网络建设原因","network"),("用户原因","customer"),
                                     ("前台原因","frontDesk"),("其他原因","other")]:
                amount = data[prefix + "Count"] if city == "全省" else data[prefix + "Reasons"][cities.index(city)]
                summary.append([city, category + "数量", amount])
        else:
            data = overlay["qikuanWithdrawal"]
            index = data["cities"].index(city) if city != "全省" else None
            fields = [("受理量","acceptedTotal","acceptedCounts"),
                      ("撤退或退单量","withdrawalTotal","withdrawalCounts"),
                      ("撤退或退单率","overallRate","rates")]
            if "returnTotal" in data:
                fields += [("退单量","returnTotal","returnCounts"),
                           ("撤单量","cancellationTotal","cancellationCounts")]
            for label, total, counts in fields:
                summary.append([city, label, data[total] if city == "全省" else data[counts][index]])
        book = Workbook()
        ws = book.active
        ws.title = "指标汇总"
        ws.append(["地区","指标","结果"])
        for row in summary:
            ws.append(row)
            if row[1].endswith("率"):
                ws.cell(ws.max_row,3).number_format = "0.00%"
        counties = [r for r in result.get("counties",[]) if city == "全省" or r["city"] == city]
        details = book.create_sheet("区县明细")
        columns = list(dict.fromkeys(k for row in counties for k in row))
        details.append(columns or ["暂无区县结果"])
        for row in counties:
            details.append([json.dumps(row.get(k),ensure_ascii=False) if isinstance(row.get(k),(dict,list)) else row.get(k) for k in columns])
        for sheet in book:
            sheet.freeze_panes = "A2"
            for column in sheet.columns:
                sheet.column_dimensions[column[0].column_letter].width = 24
        book.save(directory / (city + ".xlsx"))


def archive(result, source, sheet, root, county_map, include_county, expected_hash):
    import pandas as pd
    from openpyxl import Workbook
    from metrics.opening.bycity.dedicated_line_metrics_by_city import load_county_mapping, standardize_county
    from metrics.opening.bycity.withdrawal_metrics_by_city import locate_cell
    month = result.get("report_month")
    if not month:
        raise ValueError("归档需要 --month YYYY-MM")
    print("开始归档原始文件及省市清单…", flush=True)
    source = source.resolve()
    root = root.expanduser().resolve() / month
    root.mkdir(parents=True, exist_ok=True)
    name = result["metric_set"]
    token = uuid.uuid4().hex
    staging, final = root / ("." + name + ".tmp_" + token), root / name
    backup = root / ("." + name + ".backup_" + token)
    staging.mkdir()
    try:
        (staging / "source").mkdir()
        snapshot = staging / "source" / source.name
        shutil.copy2(source, snapshot)
        if source_hash(snapshot) != expected_hash:
            raise ValueError("计算期间源文件发生变化，请重新计算")
        if snapshot.suffix.lower() in {".xlsx", ".xlsm"}:
            from openpyxl import load_workbook
            book = load_workbook(snapshot, read_only=True, data_only=True)
            try:
                source_rows = list(book[sheet].iter_rows(values_only=True))
                frame = pd.DataFrame(source_rows[1:], columns=source_rows[0])
            finally:
                book.close()
        else:
            frame = pd.read_excel(snapshot, sheet_name=sheet, dtype=object)
        added = ["归档_源行号", "归档_标准地市", "归档_标准区县", "归档_匹配状态"]
        if set(added) & set(frame.columns):
            raise ValueError("源文件包含归档专用字段")
        mapping = load_county_mapping(county_map) if include_county else None
        line = result["metric_set"] == "dedicated_line_withdrawal_reasons_by_city"
        print(f"原始文件读取完成：{len(frame)} 行，正在匹配地区…", flush=True)
        rows, grouped = [], {city: [] for city in CITIES}
        for index, row in frame.iterrows():
            values = [None if pd.isna(v) else v for v in row.tolist()]
            record = dict(zip(frame.columns, values))
            city = str(record.get("地市" if line else "CITY") or "").strip().removesuffix("市")
            if city not in grouped:
                city = "未归属地市"
                grouped.setdefault(city, [])
            county, state = None, "未计算区县"
            if mapping:
                if line:
                    county = standardize_county(record.get("区县"), record.get("工单主题"), mapping["aliases"].get(city, {}))
                    state = "未匹配" if county == "未归属区县" else "matched"
                else:
                    mapped_city, matched_county, state = locate_cell(record.get("CELL"), mapping["aliases"])
                    if state == "matched" and mapped_city != city:
                        state = "city_mismatch"
                    county = matched_county if state == "matched" else "未归属区县"
            item = values + [int(index) + 2, city, county, state]
            rows.append(item)
            grouped[city].append(item)
        headers = list(frame.columns) + added
        def write(path, records):
            path.parent.mkdir(parents=True, exist_ok=True)
            from openpyxl.cell import WriteOnlyCell
            from openpyxl.utils import get_column_letter
            print(f"正在归档：{path.parent.name}，{len(records)} 行", flush=True)
            book = Workbook(write_only=True)
            ws = book.create_sheet("原始清单")
            ws.freeze_panes = "A2"
            ws.append(headers)
            for record in records:
                cells = []
                for value in record:
                    cell = WriteOnlyCell(ws, value=value)
                    if isinstance(value, str):
                        cell.data_type = "s"
                    cells.append(cell)
                ws.append(cells)
            ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(records) + 1}"
            book.save(path)
        write(staging / "province" / "原始清单.xlsx", rows)
        for city, records in grouped.items():
            write(staging / "cities" / city / "原始清单.xlsx", records)
        export_results(result, staging / "results")
        manifest = dict(metric_set=result["metric_set"], report_month=month,
                        created_at=datetime.now(timezone.utc).isoformat(), source_file=source.name,
                        source_sha256=expected_hash, source_sheet=sheet, province_rows=len(rows),
                        city_rows={city: len(records) for city, records in grouped.items()},
                        include_county=include_county)
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        from tools.daily_installation import task_lock
        with task_lock(root / ("." + name + ".lock")):
            if final.exists():
                final.replace(backup)
            try:
                staging.replace(final)
            except Exception:
                if backup.exists():
                    backup.replace(final)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        result["evidence"] = dict(relative_path=str(final.relative_to(root.parent)),
                                  archive_root=str(root.parent), source_sha256=expected_hash)
        return final
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
