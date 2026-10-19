#!/usr/bin/env python3
"""从专线自动率中间表计算指定地市及标准区县的自动率指标。"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from metrics.opening.automation_intermediate import OPENING, REMOVAL, automatic
from metrics.opening.bycity.dedicated_line_metrics_by_city import (
    DEFAULT_COUNTY_MAP, display_city, load_county_mapping, month_dates,
    normalize_city, result, standardize_county, text,
)
from storage.database import connect, initialize
from storage.metric_results import insert_results


METRIC_CODE = "orchestration_automation_metrics_by_city"
RESULT_OWNER = "orchestration_opening_metrics"
METRIC_VERSION = "1.0.0"
TABLE = "intermediate_orchestration_orders"
KINDS = {
    "开通": ("opening", OPENING),
    "变更": ("move", OPENING),
    "拆除": ("removal", REMOVAL),
}


def log(message: str) -> None:
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] {message}", flush=True)


def calculate(database: Path | None, month: str, city: str,
              county_map: Path = DEFAULT_COUNTY_MAP, batch_size: int = 5000):
    from pymysql.cursors import SSDictCursor

    city_label = display_city(city)
    city_short = normalize_city(city)
    mapping = load_county_mapping(county_map)
    aliases = mapping["aliases"].get(city_short)
    standards = mapping["standards"].get(city_short)
    if not aliases or not standards:
        raise ValueError(f"区县映射表中没有找到地市：{city_short}")

    totals, stages, county_totals, county_stages, network_reasons = (Counter() for _ in range(5))
    stats = Counter()
    build_ids: set[str] = set()
    with connect(database) as connection:
        with connection._connection.cursor(SSDictCursor) as cursor:
            cursor.execute(
                f"SELECT * FROM `{TABLE}` WHERE report_month=%s AND `地市` IN (%s,%s)",
                (month, city_short, city_label),
            )
            while True:
                batch = cursor.fetchmany(batch_size)
                if not batch:
                    break
                for row in batch:
                    stats["intermediate_rows"] += 1
                    build_ids.add(text(row.get("build_id")))
                    kind = text(row.get("订单类型"))
                    if text(row.get("订单状态")) != "已完成" or text(row.get("业务类型")) != "互联网专线" or kind not in KINDS:
                        stats["ignored_rows"] += 1
                        continue
                    try:
                        source = json.loads(row.get("source_payload") or "{}")
                    except json.JSONDecodeError:
                        source = {}
                    county = standardize_county(source.get("区县名称"), source.get("主题"), aliases)
                    if county == "未归属区县":
                        stats["unassigned_county_rows"] += 1
                    totals[kind] += 1
                    county_totals[kind, county] += 1
                    _prefix, stage_defs = KINDS[kind]
                    for stage, field in stage_defs:
                        if automatic(row.get(field)):
                            stages[kind, stage] += 1
                            county_stages[kind, county, stage] += 1
                    if kind == "开通" and not automatic(row.get("组网方案")):
                        try:
                            matches = json.loads(row.get("asset_matches") or "{}")
                        except json.JSONDecodeError:
                            matches = {}
                        opinion = text(matches.get("组网方案", {}).get("处理意见"))
                        reason = "工程施工" if "工程施工" in opinion else ("空" if not opinion else "其他")
                        network_reasons[county, "非自动"] += 1
                        network_reasons[county, reason] += 1

    build_ids.discard("")
    if not stats["intermediate_rows"]:
        raise RuntimeError(f"中间表中没有 {city_label} {month} 的记录，请先生成省级专线自动率中间表")
    if len(build_ids) != 1:
        raise RuntimeError(f"{city_label} {month} 对应的中间表 build_id 不唯一：{sorted(build_ids)}")

    results = []
    county_labels = list(standards)
    if stats["unassigned_county_rows"]:
        county_labels.append("未归属区县")
    for kind, (prefix, stage_defs) in KINDS.items():
        code = f"internet_{prefix}_automation_rate"
        for stage, field in stage_defs:
            results.append(result(code, "month_city_stage",
                                  {"month": month, "city": city_label, "stage": stage, "field": field,
                                   "automatic_value": "包含自动"},
                                  stages[kind, stage], totals[kind]))
            for county in county_labels:
                results.append(result(code, "month_city_county_stage",
                                      {"month": month, "city": city_label, "county": county, "stage": stage},
                                      county_stages[kind, county, stage], county_totals[kind, county]))
        results.append(result(code, "month_city_all_stages",
                              {"month": month, "city": city_label, "stage": f"{len(stage_defs)}环节整体"},
                              sum(stages[kind, stage] for stage, _ in stage_defs),
                              totals[kind] * len(stage_defs)))
        for county in county_labels:
            results.append(result(code, "month_city_county_all_stages",
                                  {"month": month, "city": city_label, "county": county,
                                   "stage": f"{len(stage_defs)}环节整体"},
                                  sum(county_stages[kind, county, stage] for stage, _ in stage_defs),
                                  county_totals[kind, county] * len(stage_defs)))
    reason_codes = {
        "非自动": "internet_opening_network_nonautomatic_count",
        "工程施工": "internet_opening_network_nonautomatic_engineering_count",
        "空": "internet_opening_network_nonautomatic_blank_count",
        "其他": "internet_opening_network_nonautomatic_other_count",
    }
    for reason, code in reason_codes.items():
        city_count = sum(network_reasons[county, reason] for county in county_labels)
        results.append(result(code, "month_city", {"month": month, "city": city_label}, city_count))
        for county in county_labels:
            results.append(result(code, "month_city_county",
                                  {"month": month, "city": city_label, "county": county},
                                  network_reasons[county, reason]))

    return {
        "metric_code": METRIC_CODE,
        "metric_version": METRIC_VERSION,
        "month": month,
        "city": city_label,
        "build_id": next(iter(build_ids)),
        "quality": dict(stats),
        "county_mapping": {"file": mapping["path"], "sha256": mapping["sha256"],
                           "standard_counties": standards},
        "results": results,
    }


def save_results(database: Path | None, report: dict) -> str:
    run_id = f"metric_city_auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    period_start, period_end = month_dates(report["month"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source_runs = [f"intermediate:{report['month']}:{report['build_id']}"]
    with connect(database) as connection:
        connection.execute(
            """INSERT INTO metric_run(metric_run_id,metric_code,metric_version,period_start,period_end,
               started_at,status,source_runs) VALUES(?,?,?,?,?,?,'running',?)""",
            (run_id, METRIC_CODE, METRIC_VERSION, period_start, period_end, now,
             json.dumps(source_runs, ensure_ascii=False)),
        )
    try:
        with connect(database) as connection:
            insert_results(connection, RESULT_OWNER, run_id, report["results"])
            connection.execute("UPDATE metric_run SET finished_at=?,status='success' WHERE metric_run_id=?",
                               (datetime.now(timezone.utc).isoformat(timespec="seconds"), run_id))
    except Exception as exc:
        with connect(database) as connection:
            connection.execute("UPDATE metric_run SET finished_at=?,status='failed',error_message=? WHERE metric_run_id=?",
                               (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(exc), run_id))
        raise
    return run_id


def run(database: Path | None, month: str, city: str, mode="both", output: Path | None = None,
        county_map: Path = DEFAULT_COUNTY_MAP, batch_size=5000):
    initialize(database)
    report = calculate(database, month, city, county_map, batch_size)
    report["metric_run_id"] = save_results(database, report) if mode in {"database", "both"} else None
    if mode in {"file", "both"}:
        target = (output or Path(f"outputs/编排专线自动率地市指标_{normalize_city(city)}_{month}.json")).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_file"] = str(target)
    log(f"完成 {display_city(city)} {month} 专线自动率：{report['metric_run_id'] or '仅文件'}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="计算指定地市及标准区县的专线自动率")
    parser.add_argument("--month", required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--county-map", type=Path, default=DEFAULT_COUNTY_MAP)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    run(args.database, args.month, args.city, args.mode, args.output, args.county_map, args.batch_size)


if __name__ == "__main__":
    main()
