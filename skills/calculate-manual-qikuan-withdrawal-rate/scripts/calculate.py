from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from qikuan_common import CATEGORY_FIELDS, CITIES, iter_records, normalize_city, normalize_text, reason_summary, top_three, validate_month

NUMERATOR_REMARK = "退单完成"


def calculate(records, source: str, sheet: str, month: str | None = None) -> dict:
    validate_month(month)
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
        accepted[city] += 1
        if normalize_text(record["OP_REMARK"]) == NUMERATOR_REMARK:
            returned[city] += 1
            if record["FIRST_LEVEL_PROBLEM"] is None:
                blank_rows.append(row_number); continue
            category = normalize_text(record["FIRST_LEVEL_PROBLEM"])
            if category not in CATEGORY_FIELDS:
                unknown_categories.add(category); continue
            reasons[category] += 1
    if blank_rows: raise ValueError(f"CITY、OP_REMARK 或已纳入退单的 FIRST_LEVEL_PROBLEM 为空，Excel 行：{blank_rows[:20]}")
    if unknown_cities: raise ValueError(f"存在未知地市：{sorted(unknown_cities)}")
    if unknown_categories: raise ValueError(f"存在未知一级原因：{sorted(unknown_categories)}")
    accepted_values = [accepted[city] for city in CITIES]
    returned_values = [returned[city] for city in CITIES]
    accepted_total, returned_total = sum(accepted_values), sum(returned_values)
    return {"schema_version": "1.0", "metric_set": "qikuan_withdrawal_rate_by_city", "report_month": month, "dimensions": {"cities": CITIES}, "ppt_overlay": {"qikuanWithdrawal": {"cities": CITIES, "acceptedCounts": accepted_values, "withdrawalCounts": returned_values, "rates": [returned[city] / accepted[city] if accepted[city] else 0 for city in CITIES], "acceptedTotal": accepted_total, "withdrawalTotal": returned_total, "overallRate": returned_total / accepted_total if accepted_total else 0, "topThreeRateCities": top_three(returned, accepted), "reasons": reason_summary(reasons, returned_total)}}, "audit": {"source_file": str(Path(source).resolve()), "source_sheet": sheet, "source_row_count": row_count, "formula": "count(OP_REMARK == '退单完成') / count(all nonblank detail rows), grouped by CITY", "reason_filter": "OP_REMARK == '退单完成'; group FIRST_LEVEL_PROBLEM", "excluded_from_numerator": ["撤单完成"], "generated_at": datetime.now(timezone.utc).isoformat()}}


def main() -> None:
    parser = argparse.ArgumentParser(description="按地市计算企宽退单率")
    parser.add_argument("--input", required=True, type=Path); parser.add_argument("--sheet", default="Sheet1"); parser.add_argument("--month"); parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = calculate(iter_records(args.input, args.sheet, ["CITY", "OP_REMARK", "FIRST_LEVEL_PROBLEM"]), str(args.input), args.sheet, args.month)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    values = result["ppt_overlay"]["qikuanWithdrawal"]
    print(f"完成：{args.output.resolve()} (退单 {values['withdrawalTotal']} / 受理 {values['acceptedTotal']} = {values['overallRate']:.2%})")


if __name__ == "__main__": main()
