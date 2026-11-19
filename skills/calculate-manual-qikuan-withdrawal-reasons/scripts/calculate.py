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

INCLUDED_REMARKS = {"退单完成", "撤单完成"}


def calculate(records, source: str, sheet: str, month: str | None = None, *, county_map: Path = DEFAULT_COUNTY_MAP, include_county: bool = True) -> dict:
    validate_month(month)
    mapping = load_county_mapping(county_map) if include_county else None
    county_accepted, county_returned, county_cancelled, county_reasons = (Counter() for _ in range(4))
    cell_quality = Counter()
    cell_issues = []
    counts, category_totals, included_by_remark = Counter(), Counter(), Counter()
    accepted, returned, cancelled = Counter(), Counter(), Counter()
    unknown_cities, unknown_categories, blank_rows = set(), set(), []
    source_rows = included_rows = 0
    for row_number, record in records:
        source_rows += 1
        if record["CITY"] is None or record["OP_REMARK"] is None: blank_rows.append(row_number); continue
        city = normalize_city(record["CITY"])
        if city not in CITIES: unknown_cities.add(city); continue
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
        accepted[city] += 1; remark = normalize_text(record["OP_REMARK"])
        if remark not in INCLUDED_REMARKS: continue
        included_rows += 1
        if record["FIRST_LEVEL_PROBLEM"] is None: blank_rows.append(row_number); continue
        category = normalize_text(record["FIRST_LEVEL_PROBLEM"])
        if category not in CATEGORY_FIELDS: unknown_categories.add(category); continue
        counts[(city, category)] += 1; category_totals[category] += 1; included_by_remark[remark] += 1
        if include_county:
            county_reasons[city, county, category] += 1
            (county_returned if remark == "退单完成" else county_cancelled)[city, county] += 1
        (returned if remark == "退单完成" else cancelled)[city] += 1
    if blank_rows: raise ValueError(f"已纳入的记录中 CITY 或 FIRST_LEVEL_PROBLEM 为空，Excel 行：{blank_rows[:20]}")
    if unknown_cities: raise ValueError(f"存在未知地市：{sorted(unknown_cities)}")
    if unknown_categories: raise ValueError(f"存在未知一级原因：{sorted(unknown_categories)}")
    combined = Counter({city: returned[city] + cancelled[city] for city in CITIES}); accepted_total = sum(accepted.values())
    data = {"cities": CITIES, "acceptedCounts": [accepted[c] for c in CITIES], "returnCounts": [returned[c] for c in CITIES], "cancellationCounts": [cancelled[c] for c in CITIES], "withdrawalCounts": [combined[c] for c in CITIES], "rates": [combined[c] / accepted[c] if accepted[c] else 0 for c in CITIES], "acceptedTotal": accepted_total, "returnTotal": sum(returned.values()), "cancellationTotal": sum(cancelled.values()), "withdrawalTotal": included_rows, "overallRate": included_rows / accepted_total if accepted_total else 0, "topThreeRateCities": top_three(combined, accepted), "reasons": reason_summary(category_totals, included_rows), "reasonCountsByCity": {field: [counts[(city, category)] for city in CITIES] for category, field in CATEGORY_FIELDS.items()}}
    result = {"schema_version": "1.0", "metric_set": "qikuan_withdrawal_summary", "report_month": month, "dimensions": {"cities": CITIES, "categories": list(CATEGORY_FIELDS)}, "ppt_overlay": {"qikuanWithdrawal": data}, "summary": {"source_row_count": source_rows, "included_row_count": included_rows, "included_by_op_remark": dict(included_by_remark), "category_totals": {c: category_totals[c] for c in CATEGORY_FIELDS}}, "audit": {"source_file": str(Path(source).resolve()), "source_sheet": sheet, "filter": "OP_REMARK in ('退单完成', '撤单完成')", "reason_column": "FIRST_LEVEL_PROBLEM", "generated_at": datetime.now(timezone.utc).isoformat(), "zero_filled_combinations": [{"city": city, "category": category} for city in CITIES for category in CATEGORY_FIELDS if counts[(city, category)] == 0]}}

    if include_county:
        counties = []
        for city in CITIES:
            names = list(mapping["standards"].get(city, []))
            names.extend(c for c in dict.fromkeys(k[1] for k in county_accepted if k[0] == city) if c not in names)
            for county in names:
                accepted_count = county_accepted[city, county]
                returned_count = county_returned[city, county]
                cancelled_count = county_cancelled[city, county]
                total = returned_count + cancelled_count
                counties.append({"city": city, "county": county, "accepted_count": accepted_count,
                    "return_count": returned_count, "cancellation_count": cancelled_count,
                    "withdrawal_count": total, "withdrawal_rate": total / accepted_count if accepted_count else None,
                    "return_rate": returned_count / accepted_count if accepted_count else None,
                    "reasons": {c: {"count": county_reasons[city, county, c],
                                   "share": county_reasons[city, county, c] / total if total else None}
                                for c in CATEGORY_FIELDS}})
        if sum(r["accepted_count"] for r in counties) != accepted_total:
            raise ValueError("区县受理数量与全省不一致")
        if sum(r["withdrawal_count"] for r in counties) != included_rows:
            raise ValueError("区县撤退数量与全省不一致")
        result["counties"] = counties
        result["audit"].update(county_map=str(county_map.resolve()), cell_quality=dict(cell_quality), cell_issues=cell_issues)
    result["audit"]["include_county"] = include_county
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="按地市和一级原因统计企宽撤退单")
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
    result = calculate(iter_records(args.input, args.sheet, columns), str(args.input), args.sheet,
                       args.month, county_map=args.county_map, include_county=not args.no_county)
    print("指标计算完成，准备归档…", flush=True)
    archive(result, args.input, args.sheet, args.archive_root, args.county_map,
            not args.no_county, fingerprint)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    if args.mysql:
        print("归档完成，正在写入 MySQL…", flush=True)
        save_manual_result(result)
    values = result["ppt_overlay"]["qikuanWithdrawal"]; print(f"完成：{args.output.resolve()} (撤退 {values['withdrawalTotal']} / 受理 {values['acceptedTotal']} = {values['overallRate']:.2%})")


if __name__ == "__main__": main()
