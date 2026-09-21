from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from qikuan_common import CATEGORY_FIELDS, CITIES, iter_records, normalize_city, normalize_text, reason_summary, top_three, validate_month

INCLUDED_REMARKS = {"退单完成", "撤单完成"}


def calculate(records, source: str, sheet: str, month: str | None = None) -> dict:
    validate_month(month)
    counts, category_totals, included_by_remark = Counter(), Counter(), Counter()
    accepted, returned, cancelled = Counter(), Counter(), Counter()
    unknown_cities, unknown_categories, blank_rows = set(), set(), []
    source_rows = included_rows = 0
    for row_number, record in records:
        source_rows += 1
        if record["CITY"] is None or record["OP_REMARK"] is None: blank_rows.append(row_number); continue
        city = normalize_city(record["CITY"])
        if city not in CITIES: unknown_cities.add(city); continue
        accepted[city] += 1; remark = normalize_text(record["OP_REMARK"])
        if remark not in INCLUDED_REMARKS: continue
        included_rows += 1
        if record["FIRST_LEVEL_PROBLEM"] is None: blank_rows.append(row_number); continue
        category = normalize_text(record["FIRST_LEVEL_PROBLEM"])
        if category not in CATEGORY_FIELDS: unknown_categories.add(category); continue
        counts[(city, category)] += 1; category_totals[category] += 1; included_by_remark[remark] += 1
        (returned if remark == "退单完成" else cancelled)[city] += 1
    if blank_rows: raise ValueError(f"已纳入的记录中 CITY 或 FIRST_LEVEL_PROBLEM 为空，Excel 行：{blank_rows[:20]}")
    if unknown_cities: raise ValueError(f"存在未知地市：{sorted(unknown_cities)}")
    if unknown_categories: raise ValueError(f"存在未知一级原因：{sorted(unknown_categories)}")
    combined = Counter({city: returned[city] + cancelled[city] for city in CITIES}); accepted_total = sum(accepted.values())
    data = {"cities": CITIES, "acceptedCounts": [accepted[c] for c in CITIES], "returnCounts": [returned[c] for c in CITIES], "cancellationCounts": [cancelled[c] for c in CITIES], "withdrawalCounts": [combined[c] for c in CITIES], "rates": [combined[c] / accepted[c] if accepted[c] else 0 for c in CITIES], "acceptedTotal": accepted_total, "returnTotal": sum(returned.values()), "cancellationTotal": sum(cancelled.values()), "withdrawalTotal": included_rows, "overallRate": included_rows / accepted_total if accepted_total else 0, "topThreeRateCities": top_three(combined, accepted), "reasons": reason_summary(category_totals, included_rows), "reasonCountsByCity": {field: [counts[(city, category)] for city in CITIES] for category, field in CATEGORY_FIELDS.items()}}
    return {"schema_version": "1.0", "metric_set": "qikuan_withdrawal_summary", "report_month": month, "dimensions": {"cities": CITIES, "categories": list(CATEGORY_FIELDS)}, "ppt_overlay": {"qikuanWithdrawal": data}, "summary": {"source_row_count": source_rows, "included_row_count": included_rows, "included_by_op_remark": dict(included_by_remark), "category_totals": {c: category_totals[c] for c in CATEGORY_FIELDS}}, "audit": {"source_file": str(Path(source).resolve()), "source_sheet": sheet, "filter": "OP_REMARK in ('退单完成', '撤单完成')", "reason_column": "FIRST_LEVEL_PROBLEM", "generated_at": datetime.now(timezone.utc).isoformat(), "zero_filled_combinations": [{"city": city, "category": category} for city in CITIES for category in CATEGORY_FIELDS if counts[(city, category)] == 0]}}


def main() -> None:
    parser = argparse.ArgumentParser(description="按地市和一级原因统计企宽撤退单")
    parser.add_argument("--input", required=True, type=Path); parser.add_argument("--sheet", default="Sheet1"); parser.add_argument("--month"); parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(); result = calculate(iter_records(args.input, args.sheet, ["CITY", "OP_REMARK", "FIRST_LEVEL_PROBLEM"]), str(args.input), args.sheet, args.month)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    values = result["ppt_overlay"]["qikuanWithdrawal"]; print(f"完成：{args.output.resolve()} (撤退 {values['withdrawalTotal']} / 受理 {values['acceptedTotal']} = {values['overallRate']:.2%})")


if __name__ == "__main__": main()
