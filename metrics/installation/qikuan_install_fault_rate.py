"""从数据库计算企宽新装报障率。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from metrics.installation.common import city, identifier, load_dataset, parse_time, period_bounds, result_row, save_metric, text, write_report


METRIC_CODE = "qikuan_install_fault_rate"
METRIC_VERSION = "1.0.0"


def calculate(installs: list[dict[str, object]], complaints: list[dict[str, object]], start: str, end: str) -> dict[str, object]:
    start_time, end_time = period_bounds(start, end)
    valid_installs, invalid_installs = [], []
    for row in installs:
        row["_dataset_code"] = "youshu_install"
        account, order_id, assigned = identifier(row.get("宽带账号")), identifier(row.get("工单id")), parse_time(row.get("派单时间"))
        if not account or not order_id or assigned is None or not start_time <= assigned <= end_time:
            invalid_installs.append(row)
            continue
        row["_account"] = account
        row["_install_time"] = assigned
        valid_installs.append(row)

    complaint_last: dict[str, object] = {}
    valid_complaints = 0
    for row in complaints:
        account, assigned = identifier(row.get("宽带账号")), parse_time(row.get("派单时间"))
        if not account or assigned is None or not start_time <= assigned <= end_time:
            continue
        valid_complaints += 1
        if account not in complaint_last or assigned > complaint_last[account]:
            complaint_last[account] = assigned

    matched = [row for row in valid_installs if row["_account"] in complaint_last and complaint_last[row["_account"]] > row["_install_time"]]
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in valid_installs:
        grouped[city(row.get("地市")) or "（空）"].append(row)
    results = [result_row(METRIC_CODE, "province", {"scope": "全省"}, len(matched), len(valid_installs))]
    matched_ids = {id(row) for row in matched}
    for city_name in sorted(grouped):
        group = grouped[city_name]
        results.append(result_row(METRIC_CODE, "city", {"city": city_name}, sum(id(row) in matched_ids for row in group), len(group)))
    return {
        "metric_code": METRIC_CODE,
        "metric_version": METRIC_VERSION,
        "period_start": start,
        "period_end": end,
        "rules": {"join_key": "宽带账号", "match": "统计期内存在派单时间晚于新装派单时间的投诉"},
        "quality": {"raw_install_rows": len(installs), "raw_complaint_rows": len(complaints), "denominator_install_orders": len(valid_installs), "complaint_rows_in_period": valid_complaints, "numerator_install_orders": len(matched), "excluded_install_rows": len(invalid_installs)},
        "results": results,
        "details": {"denominator": valid_installs, "numerator": matched, "excluded": invalid_installs},
    }


def run(database: Path, start: str, end: str, *, mode: str = "both", output: Path | None = None) -> dict[str, object]:
    if mode not in {"file", "database", "both"}: raise ValueError("mode 必须是 file、database 或 both")
    database = database.expanduser().resolve()
    installs, install_runs = load_dataset(database, "youshu_install")
    complaints, complaint_runs = load_dataset(database, "youshu_complaint")
    if not install_runs or not complaint_runs:
        raise RuntimeError("数据库必须同时包含有数企宽新装单和企宽投诉单的成功取数批次")
    report = calculate(installs, complaints, start, end)
    report["source_runs"] = install_runs + complaint_runs
    report["metric_run_id"] = save_metric(database, report, report["source_runs"], details=report["details"]) if mode in {"database", "both"} else None
    report["output_file"] = write_report(report, output or Path(f"outputs/企宽新装报障率_{start}_{end}.json")) if mode in {"file", "both"} else None
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="从数据库计算企宽新装报障率")
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    parser.add_argument("--start-date", required=True); parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both"); parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.database, args.start_date, args.end_date, mode=args.mode, output=args.output)
    print(json.dumps({"metric_run_id": report["metric_run_id"], "quality": report["quality"], "results": report["results"], "output_file": report["output_file"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
