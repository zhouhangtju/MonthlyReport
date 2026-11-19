from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from storage.manual_results import save_manual_result
from storage.manual_evidence import archive, source_hash, DEFAULT_ARCHIVE

from qikuan_common import CATEGORY_FIELDS, CITIES, iter_records, normalize_city, normalize_text, reason_summary, top_three, validate_month

from metrics.opening.bycity.dedicated_line_metrics_by_city import DEFAULT_COUNTY_MAP, load_county_mapping
from metrics.opening.bycity.withdrawal_metrics_by_city import locate_cell

NUMERATOR_REMARK = "退单完成"


def calculate(records, source: str, sheet: str, month: str | None = None, *, county_map: Path = DEFAULT_COUNTY_MAP, include_county: bool = True) -> dict:
    validate_month(month)
    mapping = load_county_mapping(county_map) if include_county else None
    county_accepted, county_returned, county_reasons = Counter(), Counter(), Counter()
    cell_quality = Counter()
    cell_issues = []
    accepted, returned, reasons = Counter(), Counter(), Counter()
    blank_rows, unknown_cities, unknown_categories = [], set(), set()
    row_count = 0
    for row_number, record in records:
        row_count += 1
        if record["CITY"] is None or record["OP_REMARK"] is None:
            blank_rows.append(row_number); continue
        city = normalize_city(record["CITY"])
        if city not in CITIES:
            unknown_cities.add(city); continue
        county = "未归属区县"
        if include_county:
            if "CELL" not in record:
                raise ValueError("区县统计需要 CELL 字段")
            mapped_city, mapped_county, state = locate_cell(record["CELL"], mapping["aliases"])
            if state == "matched" and mapped_city != city:
                state = "city_mismatch"
            if state == "matched":
                county = mapped_county
            else:
                cell_issues.append({"row": row_number, "city": city, "state": state})
            cell_quality[state] += 1
            county_accepted[city, county] += 1
        accepted[city] += 1
        if normalize_text(record["OP_REMARK"]) == NUMERATOR_REMARK:
            returned[city] += 1
            if record["FIRST_LEVEL_PROBLEM"] is None:
                blank_rows.append(row_number); continue
            category = normalize_text(record["FIRST_LEVEL_PROBLEM"])
            if category not in CATEGORY_FIELDS:
                unknown_categories.add(category); continue
            reasons[category] += 1
            if include_county:
                county_returned[city, county] += 1
                county_reasons[city, county, category] += 1
    if blank_rows: raise ValueError(f"CITY、OP_REMARK 或已纳入退单的 FIRST_LEVEL_PROBLEM 为空，Excel 行：{blank_rows[:20]}")
    if unknown_cities: raise ValueError(f"存在未知地市：{sorted(unknown_cities)}")
    if unknown_categories: raise ValueError(f"存在未知一级原因：{sorted(unknown_categories)}")
    accepted_values = [accepted[city] for city in CITIES]
    returned_values = [returned[city] for city in CITIES]
    accepted_total, returned_total = sum(accepted_values), sum(returned_values)
    result = {"schema_version": "1.0", "metric_set": "qikuan_withdrawal_rate_by_city", "report_month": month, "dimensions": {"cities": CITIES}, "ppt_overlay": {"qikuanWithdrawal": {"cities": CITIES, "acceptedCounts": accepted_values, "withdrawalCounts": returned_values, "rates": [returned[city] / accepted[city] if accepted[city] else 0 for city in CITIES], "acceptedTotal": accepted_total, "withdrawalTotal": returned_total, "overallRate": returned_total / accepted_total if accepted_total else 0, "topThreeRateCities": top_three(returned, accepted), "reasons": reason_summary(reasons, returned_total)}}, "audit": {"source_file": str(Path(source).resolve()), "source_sheet": sheet, "source_row_count": row_count, "formula": "count(OP_REMARK == '退单完成') / count(all nonblank detail rows), grouped by CITY", "reason_filter": "OP_REMARK == '退单完成'; group FIRST_LEVEL_PROBLEM", "excluded_from_numerator": ["撤单完成"], "generated_at": datetime.now(timezone.utc).isoformat()}}

    if include_county:
        counties = []
        for city in CITIES:
            names = list(mapping["standards"].get(city, []))
            names.extend(c for c in dict.fromkeys(k[1] for k in county_accepted if k[0] == city) if c not in names)
            for county in names:
                denominator = county_accepted[city, county]
                numerator = county_returned[city, county]
                counties.append({"city": city, "county": county,
                    "accepted_count": denominator, "return_count": numerator,
                    "return_rate": numerator / denominator if denominator else None,
                    "reasons": {c: {"count": county_reasons[city, county, c],
                                   "share": county_reasons[city, county, c] / numerator if numerator else None}
                                for c in CATEGORY_FIELDS}})
        if sum(row["accepted_count"] for row in counties) != accepted_total:
            raise ValueError("区县受理数量与全省不一致")
        if sum(row["return_count"] for row in counties) != returned_total:
            raise ValueError("区县退单数量与全省不一致")
        result["counties"] = counties
        result["audit"].update(county_map=str(county_map.resolve()),
                               cell_quality=dict(cell_quality), cell_issues=cell_issues)
    result["audit"]["include_county"] = include_county
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="按地市计算企宽退单率")
    parser.add_argument("--input", required=True, type=Path); parser.add_argument("--sheet", default="Sheet1"); parser.add_argument("--month"); parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mysql", action="store_true", help="同时保存到 MySQL（需要 --month）")
    parser.add_argument("--county-map", type=Path, default=DEFAULT_COUNTY_MAP)
    parser.add_argument("--no-county", action="store_true", help="关闭默认开启的区县统计")
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE, help="省市原始清单归档根目录")
    args = parser.parse_args()
    if not args.month:
        parser.error("计算归档需要 --month YYYY-MM")
    print("正在读取原始清单并计算…", flush=True)
    fingerprint = source_hash(args.input)
    columns = ["CITY", "OP_REMARK", "FIRST_LEVEL_PROBLEM"]
    if not args.no_county:
        columns.append("CELL")
    result = calculate(iter_records(args.input, args.sheet, columns), str(args.input),
                       args.sheet, args.month, county_map=args.county_map,
                       include_county=not args.no_county)
    print("指标计算完成，准备归档…", flush=True)
    archive(result, args.input, args.sheet, args.archive_root, args.county_map,
            not args.no_county, fingerprint)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if args.mysql:
        print("归档完成，正在写入 MySQL…", flush=True)
        save_manual_result(result)
    values = result["ppt_overlay"]["qikuanWithdrawal"]
    print(f"完成：{args.output.resolve()} (退单 {values['withdrawalTotal']} / 受理 {values['acceptedTotal']} = {values['overallRate']:.2%})")


if __name__ == "__main__": main()
