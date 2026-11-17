from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from storage.manual_results import save_manual_result

import pandas as pd
from metrics.opening.bycity.dedicated_line_metrics_by_city import (
    DEFAULT_COUNTY_MAP, load_county_mapping, standardize_county,
)

CITIES = ["杭州", "嘉兴", "宁波", "温州", "金华", "绍兴", "湖州", "台州", "衢州", "丽水", "舟山"]
CATEGORY_FIELDS = {"网络建设原因": "networkReasons", "用户原因": "customerReasons", "前台原因": "frontDeskReasons", "其他原因": "otherReasons"}


def normalize_city(value: object) -> str:
    city = str(value).strip()
    return city[:-1] if city.endswith("市") else city


def normalize_category(value: object) -> str:
    return re.sub(r"\s+", "", str(value))


def summarize_frame(frame: pd.DataFrame, source: str, sheet: str, month: str | None = None, *, county_map: Path = DEFAULT_COUNTY_MAP, include_county: bool = True) -> dict:
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
    result = {"schema_version": "1.0", "metric_set": "dedicated_line_withdrawal_reasons_by_city", "report_month": month, "dimensions": {"cities": CITIES, "categories": list(CATEGORY_FIELDS)}, "ppt_overlay": {"withdrawal": withdrawal}, "summary": {"source_row_count": total, "reason_total_count": total, "category_totals": totals}, "audit": {"source_file": str(Path(source).resolve()), "source_sheet": sheet, "source_columns": ["地市", "大类"], "generated_at": datetime.now(timezone.utc).isoformat(), "normalization": ["地市去除首尾空白及末尾的‘市’", "大类去除所有空白字符"], "zero_filled_combinations": [{"city": city, "category": category} for city in CITIES for category in CATEGORY_FIELDS if counts[(city, category)] == 0]}}


    if include_county:
        missing = {"区县", "工单主题"} - set(frame.columns)
        if missing:
            raise ValueError(f"区县统计缺少字段：{sorted(missing)}")
        mapping = load_county_mapping(county_map)
        county_counts = Counter()
        for position, (_, row) in enumerate(frame.iterrows()):
            city = working.iloc[position]["地市"]
            raw = "" if pd.isna(row["区县"]) else row["区县"]
            subject = "" if pd.isna(row["工单主题"]) else row["工单主题"]
            county = standardize_county(raw, subject, mapping["aliases"].get(city, {}))
            county_counts[city, county, working.iloc[position]["大类"]] += 1
        counties = []
        for city in CITIES:
            names = list(mapping["standards"].get(city, []))
            names.extend(c for c in dict.fromkeys(k[1] for k in county_counts if k[0] == city) if c not in names)
            for county in names:
                total = sum(county_counts[city, county, c] for c in CATEGORY_FIELDS)
                counties.append({"city": city, "county": county, "sample_count": total,
                    "reasons": {c: {"count": county_counts[city, county, c],
                                   "share": county_counts[city, county, c] / total if total else None}
                                for c in CATEGORY_FIELDS}})
        if sum(row["sample_count"] for row in counties) != len(working):
            raise ValueError("区县样本数量与全省不一致")
        result["counties"] = counties
        result["audit"]["county_map"] = str(county_map.resolve())
    result["audit"]["include_county"] = include_county
    return result


def summarize_file(input_path: Path, sheet: str, month: str | None = None, *, county_map: Path = DEFAULT_COUNTY_MAP, include_county: bool = True) -> dict:
    if not input_path.is_file(): raise FileNotFoundError(f"找不到输入文件：{input_path}")
    if input_path.suffix.lower() not in {".xlsx", ".xls"}: raise ValueError("当前只支持 .xlsx 和 .xls 文件")
    if month is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month): raise ValueError("月份格式应为 YYYY-MM")
    return summarize_frame(pd.read_excel(input_path, sheet_name=sheet), str(input_path), sheet, month, county_map=county_map, include_county=include_county)


def main() -> None:
    parser = argparse.ArgumentParser(description="按地市和原因大类统计专线撤退单")
    parser.add_argument("--input", required=True, type=Path); parser.add_argument("--sheet", default="撤退单清单"); parser.add_argument("--month"); parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mysql", action="store_true", help="同时保存到 MySQL（需要 --month）")
    parser.add_argument("--county-map", type=Path, default=DEFAULT_COUNTY_MAP)
    parser.add_argument("--no-county", action="store_true", help="关闭默认开启的区县统计")
    args = parser.parse_args()
    result = summarize_file(args.input.resolve(), args.sheet, args.month,
                            county_map=args.county_map, include_county=not args.no_county)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if args.mysql:
        save_manual_result(result)
    print(f"完成：{args.output.resolve()} (明细 {result['summary']['source_row_count']} 条，大类 {len(result['dimensions']['categories'])} 个，地市 {len(result['dimensions']['cities'])} 个)")


if __name__ == "__main__": main()
