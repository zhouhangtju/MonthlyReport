from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

CITIES = ["杭州", "嘉兴", "宁波", "温州", "金华", "绍兴", "湖州", "台州", "衢州", "丽水", "舟山"]
CATEGORY_FIELDS = {"网络建设原因": "networkReasons", "用户原因": "customerReasons", "前台原因": "frontDeskReasons", "其他原因": "otherReasons"}


def normalize_city(value: object) -> str:
    city = str(value).strip()
    return city[:-1] if city.endswith("市") else city


def normalize_category(value: object) -> str:
    return re.sub(r"\s+", "", str(value))


def summarize_frame(frame: pd.DataFrame, source: str, sheet: str, month: str | None = None) -> dict:
    missing = sorted({"地市", "大类"} - set(frame.columns))
    if missing: raise ValueError(f"工作表 {sheet!r} 缺少必需列：{missing}")
    working = frame.loc[:, ["地市", "大类"]].copy()
    blank = working["地市"].isna() | working["大类"].isna()
    if blank.any(): raise ValueError(f"地市或大类为空，Excel 行：{[int(i) + 2 for i in working.index[blank].tolist()][:20]}")
    working["地市"] = working["地市"].map(normalize_city); working["大类"] = working["大类"].map(normalize_category)
    unknown_cities = sorted(set(working["地市"]) - set(CITIES)); unknown_categories = sorted(set(working["大类"]) - set(CATEGORY_FIELDS))
    if unknown_cities: raise ValueError(f"存在未知地市：{unknown_cities}")
    if unknown_categories: raise ValueError(f"存在未知大类：{unknown_categories}")
    counts = Counter(zip(working["地市"], working["大类"])); totals = {category: int((working["大类"] == category).sum()) for category in CATEGORY_FIELDS}; total = len(working)
    withdrawal = {field: [counts[(city, category)] for city in CITIES] for category, field in CATEGORY_FIELDS.items()}
    for category, field in CATEGORY_FIELDS.items():
        prefix = field.removesuffix("Reasons"); count = totals[category]; withdrawal[f"{prefix}Count"] = count; withdrawal[f"{prefix}Share"] = count / total if total else 0
    return {"schema_version": "1.0", "metric_set": "dedicated_line_withdrawal_reasons_by_city", "report_month": month, "dimensions": {"cities": CITIES, "categories": list(CATEGORY_FIELDS)}, "ppt_overlay": {"withdrawal": withdrawal}, "summary": {"source_row_count": total, "reason_total_count": total, "category_totals": totals}, "audit": {"source_file": str(Path(source).resolve()), "source_sheet": sheet, "source_columns": ["地市", "大类"], "generated_at": datetime.now(timezone.utc).isoformat(), "normalization": ["地市去除首尾空白及末尾的‘市’", "大类去除所有空白字符"], "zero_filled_combinations": [{"city": city, "category": category} for city in CITIES for category in CATEGORY_FIELDS if counts[(city, category)] == 0]}}


def summarize_file(input_path: Path, sheet: str, month: str | None = None) -> dict:
    if not input_path.is_file(): raise FileNotFoundError(f"找不到输入文件：{input_path}")
    if input_path.suffix.lower() not in {".xlsx", ".xls"}: raise ValueError("当前只支持 .xlsx 和 .xls 文件")
    if month is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month): raise ValueError("月份格式应为 YYYY-MM")
    return summarize_frame(pd.read_excel(input_path, sheet_name=sheet), str(input_path), sheet, month)


def main() -> None:
    parser = argparse.ArgumentParser(description="按地市和原因大类统计专线撤退单")
    parser.add_argument("--input", required=True, type=Path); parser.add_argument("--sheet", default="撤退单清单"); parser.add_argument("--month"); parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(); result = summarize_file(args.input.resolve(), args.sheet, args.month)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"完成：{args.output.resolve()} (明细 {result['summary']['source_row_count']} 条，大类 {len(result['dimensions']['categories'])} 个，地市 {len(result['dimensions']['cities'])} 个)")


if __name__ == "__main__": main()
