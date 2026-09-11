"""从数据库计算互联网专线新装报障率。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from metrics.installation.common import city, load_dataset, parse_time, period_bounds, result_row, save_metric, text, write_report


METRIC_CODE = "dedicated_line_install_fault_rate"
METRIC_VERSION = "1.0.0"
INVALID_IDS = {"", "/", "nan", "none", "null", "nat"}


def normalize_id(value: object) -> str:
    """与 export/calculate_internet_line_install_fault_rate.py 保持一致。"""
    value_text = text(value)
    value_text = re.sub(r"\.0$", "", value_text)
    return "" if value_text.lower() in INVALID_IDS else value_text


def calculate(installs: list[dict[str, object]], complaints: list[dict[str, object]], start: str, end: str) -> dict[str, object]:
    start_time, end_time = period_bounds(start, end)
    valid_installs, invalid_installs = [], []
    for row in installs:
        row["_dataset_code"] = "orch_install"
        account = normalize_id(row.get("产品实例编号"))
        created = parse_time(row.get("订单创建时间"))
        install_city = city(row.get("地市"))
        if not account or not install_city or created is None or not start_time <= created <= end_time:
            invalid_installs.append(row); continue
        row["_account"] = account; row["_install_time"] = created; row["_city"] = install_city
        valid_installs.append(row)

    complaint_rows = []
    complaints_by_account: dict[str, list[tuple[str, object]]] = defaultdict(list)
    for row in complaints:
        account = normalize_id(row.get("计费号码")); assigned = parse_time(row.get("派单时间")); complaint_city = city(row.get("所属地市"))
        if not account or assigned is None or not start_time <= assigned <= end_time: continue
        complaint_rows.append(row)
        complaints_by_account[account].append((complaint_city, assigned))

    # 不按产品实例编号去重：每条新装记录独立计入分母并判断分子。
    matched_rows = []
    for row in valid_installs:
        if any(
            complaint_city == row["_city"] and assigned >= row["_install_time"]
            for complaint_city, assigned in complaints_by_account.get(row["_account"], [])
        ):
            matched_rows.append(row)

    results = [result_row(METRIC_CODE, "province", {"scope": "全省"}, len(matched_rows), len(valid_installs))]
    by_city: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in valid_installs: by_city[row["_city"]].append(row)
    matched_source_ids = {id(row) for row in matched_rows}
    for city_name in sorted(by_city):
        city_rows = by_city[city_name]
        city_matched = sum(id(row) in matched_source_ids for row in city_rows)
        results.append(result_row(METRIC_CODE, "city", {"city": city_name}, city_matched, len(city_rows)))
    return {
        "metric_code": METRIC_CODE, "metric_version": METRIC_VERSION,
        "period_start": start, "period_end": end,
        "rules": {"join_key": "产品实例编号=计费号码", "install_time": "订单创建时间在统计期内", "time": "投诉派单时间不早于订单创建时间", "city": "新装地市与投诉所属地市一致", "deduplication": "不去重，每条有效新装记录独立计数", "count_unit": "新装记录"},
        "quality": {"raw_install_rows": len(installs), "raw_complaint_rows": len(complaints), "valid_install_rows": len(valid_installs), "complaint_rows_in_period": len(complaint_rows), "denominator_install_rows": len(valid_installs), "numerator_install_rows": len(matched_rows), "excluded_install_rows": len(invalid_installs)},
        "results": results,
        "details": {"denominator": valid_installs, "numerator": matched_rows, "excluded": invalid_installs},
    }


def run(database: Path, start: str, end: str, *, mode: str = "both", output: Path | None = None) -> dict[str, object]:
    if mode not in {"file", "database", "both"}: raise ValueError("mode 必须是 file、database 或 both")
    database = database.expanduser().resolve()
    installs, install_runs = load_dataset(database, "orch_install"); complaints, complaint_runs = load_dataset(database, "eoms_complaint")
    if not install_runs or not complaint_runs: raise RuntimeError("数据库必须同时包含编排互联网专线新装单和EOMS投诉工单的成功取数批次")
    report = calculate(installs, complaints, start, end); report["source_runs"] = install_runs + complaint_runs
    report["metric_run_id"] = save_metric(database, report, report["source_runs"], details=report["details"]) if mode in {"database", "both"} else None
    report["output_file"] = write_report(report, output or Path(f"outputs/专线新装报障率_{start}_{end}.json")) if mode in {"file", "both"} else None
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="从数据库计算互联网专线新装报障率")
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db")); parser.add_argument("--start-date", required=True); parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both"); parser.add_argument("--output", type=Path); args = parser.parse_args()
    report = run(args.database, args.start_date, args.end_date, mode=args.mode, output=args.output)
    print(json.dumps({"metric_run_id": report["metric_run_id"], "quality": report["quality"], "results": report["results"], "output_file": report["output_file"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
