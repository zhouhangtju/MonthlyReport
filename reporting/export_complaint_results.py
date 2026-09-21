"""Export the stored support results selected by the PPT reader."""

import argparse
import json
from pathlib import Path

from database_results import Results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True)
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--metric", choices=["qianliyan_repeat_complaint_rate", "dedicated_line_repeat_complaint_rate", "commercial_customer_install_fault_rate"])
    args = parser.parse_args()
    selected = Results(args.database, args.month)
    names = {
        "qianliyan_repeat_complaint_rate": "千里眼重复投诉率",
        "dedicated_line_repeat_complaint_rate": "专网重复投诉率",
        "commercial_customer_install_fault_rate": "商客新装报障率",
    }
    if args.metric:
        names = {args.metric: names[args.metric]}
    else:
        names.pop("commercial_customer_install_fault_rate")
    for code in names:
        if code not in selected.runs:
            raise RuntimeError(f"No selected successful batch: {code}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for code, name in names.items():
        run = selected.runs[code]
        rows = [dict(row) for row in selected.rows[code] if row["metric_code"] == code]
        for row in rows:
            value = row.get("metric_value")
            row["display_percent"] = None if value is None else f"{value:.2%}"
        report = {
            "name": name,
            "database": str(selected.database),
            "requested_month": args.month,
            "period_start": run["period_start"],
            "period_end": run["period_end"],
            "metric_run": run,
            "results": rows,
            "note": "Database stored result export; not a reconstruction of the original calculation JSON or raw details.",
        }
        output = args.output_dir / f"{name}.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(f"Exported {code}: {len(rows)} results")


if __name__ == "__main__":
    main()
