"""从数据库计算互联网专线新装报障率。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from metrics.installation.common import city, identifier, load_dataset, parse_time, period_bounds, result_row, save_metric, text, write_report


METRIC_CODE = "dedicated_line_install_fault_rate"
METRIC_VERSION = "1.0.0"


def calculate(installs: list[dict[str, object]], complaints: list[dict[str, object]], start: str, end: str) -> dict[str, object]:
    start_time, end_time = period_bounds(start, end)
    valid_installs, invalid_installs = [], []
    for row in installs:
        row["_dataset_code"] = "orch_install"
        account = identifier(row.get("产品实例编号"))
        created = parse_time(row.get("派单时间"))
        valid_scope = text(row.get("订单状态")) == "已完成" and text(row.get("订单类型")) == "开通" and text(row.get("业务类型")) == "互联网专线"
        if not account or created is None or not start_time <= created <= end_time or not valid_scope:
            invalid_installs.append(row); continue
        row["_account"] = account; row["_install_time"] = created; row["_city"] = city(row.get("地市"))
        valid_installs.append(row)

    earliest: dict[tuple[str, str], object] = {}
    for row in valid_installs:
        key = (row["_account"], row["_city"])
        if key not in earliest or row["_install_time"] < earliest[key]: earliest[key] = row["_install_time"]
    complaint_rows, matched_keys = [], set()
    for row in complaints:
        account = identifier(row.get("计费号码")); assigned = parse_time(row.get("派单时间")); complaint_city = city(row.get("所属地市"))
        if not account or assigned is None or not start_time <= assigned <= end_time: continue
        complaint_rows.append(row)
        key = (account, complaint_city)
        install_time = earliest.get(key)
        if install_time is not None and assigned >= install_time: matched_keys.add(key)

    denominator_accounts = {row["_account"] for row in valid_installs}
    numerator_accounts = denominator_accounts & {account for account, _ in matched_keys}
    results = [result_row(METRIC_CODE, "province", {"scope": "全省"}, len(numerator_accounts), len(denominator_accounts))]
    by_city: dict[str, set[str]] = defaultdict(set)
    for row in valid_installs: by_city[row["_city"] or "（空）"].add(row["_account"])
    for city_name in sorted(by_city):
        accounts = by_city[city_name]
        matched_city_accounts = {account for account, matched_city in matched_keys if matched_city == city_name}
        results.append(result_row(METRIC_CODE, "city", {"city": city_name}, len(accounts & matched_city_accounts), len(accounts)))
    numerator_rows = [row for row in valid_installs if (row["_account"], row["_city"]) in matched_keys]
    return {
        "metric_code": METRIC_CODE, "metric_version": METRIC_VERSION,
        "period_start": start, "period_end": end,
        "rules": {"join_key": "产品实例编号=计费号码", "time": "投诉派单时间不早于新装派单时间", "city": "新装地市与投诉所属地市一致", "count_unit": "唯一计费号码"},
        "quality": {"raw_install_rows": len(installs), "raw_complaint_rows": len(complaints), "valid_install_rows": len(valid_installs), "complaint_rows_in_period": len(complaint_rows), "denominator_accounts": len(denominator_accounts), "numerator_accounts": len(numerator_accounts), "excluded_install_rows": len(invalid_installs)},
        "results": results,
        "details": {"denominator": valid_installs, "numerator": numerator_rows, "excluded": invalid_installs},
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
