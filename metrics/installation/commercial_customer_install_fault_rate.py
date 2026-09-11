"""汇总企宽与专线分子分母，计算商客新装报障率。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from metrics.installation.common import result_row, save_metric, write_report
from storage.database import connect, initialize


METRIC_CODE = "commercial_customer_install_fault_rate"
METRIC_VERSION = "1.0.0"
COMPONENT_CODES = ["qikuan_install_fault_rate", "dedicated_line_install_fault_rate"]


def latest_component(database: Path, metric_code: str, start: str, end: str) -> tuple[str, list[dict[str, object]]]:
    with connect(database) as connection:
        run = connection.execute(
            """SELECT metric_run_id FROM metric_run WHERE metric_code=?
               AND period_start=? AND period_end=? AND status='success'
               ORDER BY finished_at DESC, started_at DESC LIMIT 1""",
            (metric_code, start, end),
        ).fetchone()
        if run is None:
            raise RuntimeError(f"缺少同周期已成功计算的上游指标：{metric_code}")
        rows = connection.execute(
            """SELECT dimension_type, dimension_value, numerator, denominator
               FROM ads_metric_result WHERE metric_run_id=? AND metric_code=?""",
            (run["metric_run_id"], metric_code),
        ).fetchall()
    return run["metric_run_id"], [dict(row) for row in rows]


def calculate(components: dict[str, list[dict[str, object]]], start: str, end: str) -> dict[str, object]:
    indexed: dict[str, dict[tuple[str, str], dict[str, object]]] = {}
    for code, rows in components.items():
        indexed[code] = {(row["dimension_type"], row["dimension_value"]): row for row in rows}
    keys = set().union(*(set(values) for values in indexed.values()))
    results = []
    for dimension_type, dimension_value in sorted(keys):
        numerator = sum(int((indexed[code].get((dimension_type, dimension_value)) or {"numerator": 0})["numerator"] or 0) for code in COMPONENT_CODES)
        denominator = sum(int((indexed[code].get((dimension_type, dimension_value)) or {"denominator": 0})["denominator"] or 0) for code in COMPONENT_CODES)
        results.append(result_row(METRIC_CODE, dimension_type, json.loads(dimension_value), numerator, denominator))
    if not any(item["dimension_type"] == "province" for item in results):
        raise RuntimeError("两个上游指标都缺少全省结果")
    return {
        "metric_code": METRIC_CODE, "metric_version": METRIC_VERSION,
        "period_start": start, "period_end": end,
        "formula": "(专线分子 + 企宽分子) / (专线分母 + 企宽分母)",
        "results": results,
    }


def run(database: Path, start: str, end: str, *, mode: str = "both", output: Path | None = None) -> dict[str, object]:
    if mode not in {"file", "database", "both"}: raise ValueError("mode 必须是 file、database 或 both")
    database = database.expanduser().resolve(); initialize(database)
    components, source_runs = {}, []
    for code in COMPONENT_CODES:
        run_id, rows = latest_component(database, code, start, end); source_runs.append(run_id); components[code] = rows
    report = calculate(components, start, end); report["source_metric_runs"] = source_runs
    report["metric_run_id"] = save_metric(database, report, source_runs) if mode in {"database", "both"} else None
    report["output_file"] = write_report(report, output or Path(f"outputs/商客新装报障率_{start}_{end}.json")) if mode in {"file", "both"} else None
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总企宽和专线计算商客新装报障率")
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db")); parser.add_argument("--start-date", required=True); parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both"); parser.add_argument("--output", type=Path); args = parser.parse_args()
    report = run(args.database, args.start_date, args.end_date, mode=args.mode, output=args.output)
    print(json.dumps({"metric_run_id": report["metric_run_id"], "formula": report["formula"], "results": report["results"], "output_file": report["output_file"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
