"""互联网专线新装报障率 V2：筛选专线/专网投诉，并在匹配前剔除退单。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from metrics.installation.common import (
    city, load_dataset, parse_time, period_bounds, result_row,
    save_metric, text, write_report,
)

METRIC_CODE = "dedicated_line_install_fault_rate"
METRIC_VERSION = "2.0.0"
RETURNED_FLAGS = {"1", "1.0", "是"}
INVALID_IDS = {"", "/", "nan", "none", "null", "nat"}


def normalize_id(value: object) -> str:
    value_text = re.sub(r"\.0$", "", text(value))
    return "" if value_text.lower() in INVALID_IDS else value_text


def calculate(
    installs: list[dict[str, object]],
    complaints: list[dict[str, object]],
    start: str,
    end: str,
) -> dict[str, object]:
    """直接完成投诉筛选、新装关联及全省、地市统计，不依赖其他指标入口。"""
    start_time, end_time = period_bounds(start, end)
    selected, excluded = [], []
    business_rows = returned_rows = 0
    for source in complaints:
        reason = ""
        category = text(source.get("业务类别"))
        if "专线" not in category and "专网" not in category:
            reason = "业务类别不包含专线或专网"
        else:
            business_rows += 1
            if text(source.get("是否退单")) in RETURNED_FLAGS:
                returned_rows += 1
                reason = "投诉退单"
        if reason:
            excluded.append({
                **source,
                "_dataset_code": "eoms_complaint",
                "剔除原因": reason,
            })
        else:
            selected.append(source)

    valid_installs, invalid_installs = [], []
    for source in installs:
        row = {**source, "_dataset_code": "orch_install"}
        account = normalize_id(row.get("产品实例编号"))
        created = parse_time(row.get("订单创建时间"))
        install_city = city(row.get("地市"))
        if not account or not install_city or created is None or not start_time <= created <= end_time:
            invalid_installs.append(row)
            continue
        row.update({"_account": account, "_install_time": created, "_city": install_city})
        valid_installs.append(row)

    complaints_by_account = defaultdict(list)
    complaint_rows_in_period = 0
    for row in selected:
        account = normalize_id(row.get("计费号码"))
        assigned = parse_time(row.get("派单时间"))
        if not account or assigned is None or not start_time <= assigned <= end_time:
            continue
        complaint_rows_in_period += 1
        complaints_by_account[account].append((city(row.get("所属地市")), assigned))

    matched_rows = []
    by_city = defaultdict(lambda: [0, 0])
    for row in valid_installs:
        matched = any(
            complaint_city == row["_city"] and assigned >= row["_install_time"]
            for complaint_city, assigned in complaints_by_account.get(row["_account"], [])
        )
        if matched:
            matched_rows.append(row)
        by_city[row["_city"]][0] += int(matched)
        by_city[row["_city"]][1] += 1

    results = [result_row(METRIC_CODE, "province", {"scope": "全省"}, len(matched_rows), len(valid_installs))]
    for city_name, (numerator, denominator) in sorted(by_city.items()):
        results.append(result_row(METRIC_CODE, "city", {"city": city_name}, numerator, denominator))

    rules = {
        "join_key": "产品实例编号=计费号码",
        "install_time": "订单创建时间在统计期内",
        "time": "投诉派单时间不早于订单创建时间",
        "city": "新装地市与投诉所属地市一致",
        "deduplication": "不去重，每条有效新装记录独立计数",
        "count_unit": "新装记录",
        "complaint_business_scope": "业务类别包含专线或专网",
        "returned_complaints": "匹配前剔除是否退单为1、1.0或是的投诉；空值保留",
        "complaint_time": "投诉派单时间在统计期内",
    }
    quality = {
        "raw_install_rows": len(installs),
        "raw_complaint_rows": len(complaints),
        "business_complaint_rows": business_rows,
        "excluded_non_business_complaint_rows": len(complaints) - business_rows,
        "excluded_returned_complaint_rows": returned_rows,
        "filtered_complaint_rows": len(selected),
        "valid_install_rows": len(valid_installs),
        "complaint_rows_in_period": complaint_rows_in_period,
        "denominator_install_rows": len(valid_installs),
        "numerator_install_rows": len(matched_rows),
        "excluded_install_rows": len(invalid_installs),
    }
    return {
        "metric_code": METRIC_CODE, "metric_version": METRIC_VERSION,
        "period_start": start, "period_end": end,
        "rules": rules, "quality": quality, "results": results,
        "details": {
            "denominator": valid_installs, "numerator": matched_rows,
            "excluded": invalid_installs, "excluded_complaints": excluded,
        },
    }


def run(
    database: Path | None,
    start: str,
    end: str,
    *,
    mode: str = "both",
    output: Path | None = None,
) -> dict[str, object]:
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    database = database.expanduser().resolve() if database is not None else None
    installs, install_runs = load_dataset(database, "orch_install")
    complaints, complaint_runs = load_dataset(database, "eoms_complaint")
    if not install_runs or not complaint_runs:
        raise RuntimeError("数据库必须同时包含编排互联网专线新装单和EOMS投诉工单的成功取数批次")
    report = calculate(installs, complaints, start, end)
    report["source_runs"] = install_runs + complaint_runs
    report["metric_run_id"] = (
        save_metric(database, report, report["source_runs"], details=report["details"])
        if mode in {"database", "both"} else None
    )
    report["output_file"] = (
        write_report(report, output or Path(f"outputs/专线新装报障率_v2_{start}_{end}.json"))
        if mode in {"file", "both"} else None
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.database, args.start_date, args.end_date, mode=args.mode, output=args.output)
    print(json.dumps({key: report[key] for key in (
        "metric_code", "metric_version", "metric_run_id", "quality", "results", "output_file",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
