"""从数据库计算一体化平台专线开通撤退单率。"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from storage.metric_results import insert_results
from storage.database import connect, initialize
from storage.raw_tables import read_records
from config.report_periods import integration_opening_period


DATASET_CODE = "integration_opening"
METRIC_CODE = "dedicated_line_opening_withdrawal_rate"
METRIC_VERSION = "1.3.0-provisional"
COMPLETION_METRICS = {
    "total": "dedicated_line_opening_completed_count",
    "current": "dedicated_line_opening_completed_current_accepted_count",
    "previous": "dedicated_line_opening_completed_previous_accepted_count",
    "unknown": "dedicated_line_opening_completed_unknown_accepted_count",
}
DEFAULT_BUSINESS_TYPES: list[str] = []
EXCLUDED_BUSINESS_TYPES = {"行业视频行业版平台基础", "行业视频-行业版", "5G双域专网"}
EXCLUDED_BUSINESS_TYPE_KEYWORDS = ["跨省", "跨国"]
EXCLUDED_PACKAGE_KEYWORDS = ["跨省"]
DEFAULT_WITHDRAWAL_STATUSES = ["已撤单", "已驳回"]
DEFAULT_TEST_KEYWORDS = ["测试", "test"]


def text(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_time(value: object) -> datetime | None:
    raw = text(value)
    if not raw:
        return None
    normalized = raw.replace("/", "-").replace("T", " ")
    for length, pattern in [(19, "%Y-%m-%d %H:%M:%S"), (16, "%Y-%m-%d %H:%M"), (10, "%Y-%m-%d")]:
        try:
            return datetime.strptime(normalized[:length], pattern)
        except ValueError:
            continue
    return None


def load_rows(database: Path) -> tuple[list[dict[str, object]], list[str]]:
    initialize(database)
    with connect(database) as connection:
        records = read_records(connection, DATASET_CODE)
        source_runs = connection.execute(
            """SELECT run_id FROM etl_run WHERE dataset_code=? AND status='success'
               ORDER BY started_at""",
            (DATASET_CODE,),
        ).fetchall()
    return records, [item["run_id"] for item in source_runs]


def is_test_order(row: dict[str, object], keywords: list[str]) -> bool:
    title = text(row.get("工单主题")).lower()
    return any(keyword.lower() in title for keyword in keywords if keyword)


def business_exclusion_reason(row: dict[str, object]) -> str | None:
    business_type = text(row.get("业务类型"))
    package_type = text(row.get("业务套餐类型"))
    if business_type in EXCLUDED_BUSINESS_TYPES:
        return f"业务类型精确排除:{business_type}"
    keyword = next((item for item in EXCLUDED_BUSINESS_TYPE_KEYWORDS if item in business_type), None)
    if keyword:
        return f"业务类型包含:{keyword}"
    keyword = next((item for item in EXCLUDED_PACKAGE_KEYWORDS if item in package_type), None)
    if keyword:
        return f"业务套餐类型包含:{keyword}"
    return None


def rate_row(dimension_type: str, dimension: dict[str, str], rows: list[dict[str, object]], statuses: list[str]) -> dict[str, object]:
    numerator = sum(text(row.get("工单状态")) in statuses for row in rows)
    denominator = len(rows)
    return {
        "metric_code": METRIC_CODE,
        "dimension_type": dimension_type,
        "dimension": dimension,
        "numerator": numerator,
        "denominator": denominator,
        "metric_value": numerator / denominator if denominator else None,
    }


def calculate(
    rows: list[dict[str, object]],
    start_date: str,
    end_date: str,
    *,
    business_types: list[str] | None = None,
    all_business_types: bool = False,
    withdrawal_statuses: list[str] | None = None,
    test_keywords: list[str] | None = None,
) -> dict[str, object]:
    start = parse_time(start_date)
    end = parse_time(end_date)
    if start is None or end is None:
        raise ValueError("日期格式应为 YYYY-MM-DD")
    end = end.replace(hour=23, minute=59, second=59)
    if start > end:
        raise ValueError("start_date 不能晚于 end_date")
    business_types = list(dict.fromkeys(business_types or DEFAULT_BUSINESS_TYPES))
    statuses = list(dict.fromkeys(withdrawal_statuses or DEFAULT_WITHDRAWAL_STATUSES))
    keywords = list(dict.fromkeys(test_keywords or DEFAULT_TEST_KEYWORDS))

    in_period = []
    missing_end_time = 0
    for row in rows:
        end_time = parse_time(row.get("工单结束时间"))
        if end_time is None:
            missing_end_time += 1
            continue
        if start <= end_time <= end:
            in_period.append(row)
    source_base = [
        row for row in in_period
        if text(row.get("工单数据来源")) == "二编"
        and text(row.get("工单类型")) == "开通"
    ]
    excluded_business: list[tuple[dict[str, object], str]] = []
    business_base = []
    for row in source_base:
        reason = business_exclusion_reason(row)
        if reason is None:
            business_base.append(row)
        else:
            excluded_business.append((row, reason))
    base = [row for row in business_base
            if all_business_types or not business_types or text(row.get("业务类型")) in business_types]
    excluded_test = [row for row in base if is_test_order(row, keywords)]
    formal = [row for row in base if not is_test_order(row, keywords)]
    numerator_rows = [row for row in formal if text(row.get("工单状态")) in statuses]

    # The report month is the month containing period_end. Completion uses the same
    # 26th-to-25th period as the withdrawal denominator; acceptance groups use the
    # report month's natural boundaries.
    month_start = end.replace(day=1, hour=0, minute=0, second=0)
    month_end = (month_start.replace(year=month_start.year + 1, month=1)
                 if month_start.month == 12 else month_start.replace(month=month_start.month + 1))
    completed = [row for row in formal if text(row.get("工单状态")) == "已完成"]
    completion_groups = {"total": completed, "current": [], "previous": [], "unknown": []}
    for row in completed:
        dispatched = parse_time(row.get("派单时间"))
        finished = parse_time(row.get("工单结束时间"))
        if dispatched is None or dispatched > finished:
            completion_groups["unknown"].append(row)
        elif dispatched < month_start:
            completion_groups["previous"].append(row)
        elif dispatched < month_end:
            completion_groups["current"].append(row)
        else:
            completion_groups["unknown"].append(row)

    results = [rate_row("province", {"scope": "全省"}, formal, statuses)]
    cities = sorted({text(row.get("地市")) for row in formal if text(row.get("地市"))})
    for city in cities:
        results.append(rate_row("city", {"city": city}, [row for row in formal if text(row.get("地市")) == city], statuses))
    types = sorted({text(row.get("业务类型")) for row in formal if text(row.get("业务类型"))})
    for business_type in types:
        results.append(rate_row("business_type", {"business_type": business_type}, [row for row in formal if text(row.get("业务类型")) == business_type], statuses))

    for group, code in COMPLETION_METRICS.items():
        amount = len(completion_groups[group])
        results.append({"metric_code": code, "dimension_type": "province",
                        "dimension": {"scope": "全省"}, "numerator": amount,
                        "denominator": None, "metric_value": amount})

    return {
        "metric_code": METRIC_CODE,
        "metric_version": METRIC_VERSION,
        "period_start": start_date,
        "period_end": end_date,
        "rules": {
            "business_types": "排除固定范围后的全部" if all_business_types or not business_types else business_types,
            "excluded_business_types": sorted(EXCLUDED_BUSINESS_TYPES),
            "excluded_business_type_keywords": EXCLUDED_BUSINESS_TYPE_KEYWORDS,
            "excluded_package_keywords": EXCLUDED_PACKAGE_KEYWORDS,
            "withdrawal_statuses": statuses,
            "test_title_keywords": keywords,
            "failed_status_in_numerator": "失败" in statuses,
            "report_month": month_start.strftime("%Y-%m"),
            "completion_period": {"start": start_date, "end": end_date},
            "completion_time_field": "工单结束时间",
            "completion_status": "已完成",
            "completion_acceptance_field": "派单时间",
            "completion_current_accepted": "派单时间在月报自然月内且不晚于工单结束时间",
            "completion_previous_accepted": "派单时间早于竣工统计当月1日",
        },
        "quality": {
            "database_rows": len(rows),
            "rows_missing_end_time": missing_end_time,
            "rows_in_period": len(in_period),
            "rows_before_business_exclusion": len(source_base),
            "excluded_business_rows": len(excluded_business),
            "business_exclusion_reasons": dict(Counter(reason for _, reason in excluded_business)),
            "rows_before_test_exclusion": len(base),
            "excluded_test_orders": len(excluded_test),
            "denominator_orders": len(formal),
            "numerator_orders": len(numerator_rows),
            "status_distribution": dict(Counter(text(row.get("工单状态")) for row in formal)),
            "completed_orders": len(completed),
            "completed_current_accepted": len(completion_groups["current"]),
            "completed_previous_accepted": len(completion_groups["previous"]),
            "completed_unknown_accepted": len(completion_groups["unknown"]),
        },
        "results": results,
        "details": {
            "denominator": formal,
            "numerator": numerator_rows,
            "excluded": excluded_test,
            "excluded_business": [dict(row, _business_exclusion_reason=reason)
                                  for row, reason in excluded_business],
            "completed_current": completion_groups["current"],
            "completed_previous": completion_groups["previous"],
            "completed_unknown": completion_groups["unknown"],
        },
    }


def audit_payload(row: dict[str, object]) -> dict[str, object]:
    fields = ["工单号", "工单主题", "地市", "区县", "业务类型", "业务套餐类型", "工单状态", "工单结束时间", "派单时间", "是否撤单重录", "计费号/产品实例编号", "_business_exclusion_reason"]
    return {field: row.get(field) for field in fields}


def save_results(database: Path, report: dict[str, object], source_runs: list[str]) -> str:
    initialize(database)
    run_id = f"metric_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(database) as connection:
        connection.execute(
            """INSERT INTO metric_run (metric_run_id, metric_code, metric_version,
               period_start, period_end, started_at, status, source_runs)
               VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
            (run_id, METRIC_CODE, METRIC_VERSION, report["period_start"], report["period_end"], now, json.dumps(source_runs)),
        )
    try:
        with connect(database) as connection:
            insert_results(connection, report["metric_code"], run_id, report["results"])
            dimension = json.dumps({"period_start": report["period_start"], "period_end": report["period_end"]}, ensure_ascii=False, sort_keys=True)
            for role, rows in report["details"].items():
                for row in rows:
                    source_id = text(row.get("_source_record_id")) or text(row.get("工单号"))
                    if not source_id:
                        continue
                    connection.execute(
                        """INSERT INTO ads_metric_detail (metric_run_id, metric_code,
                           detail_role, source_dataset_code, source_record_id,
                           dimension_value, detail_data) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (run_id, METRIC_CODE, role, DATASET_CODE, source_id, dimension, json.dumps(audit_payload(row), ensure_ascii=False, sort_keys=True)),
                    )
            connection.execute("UPDATE metric_run SET finished_at=?, status='success' WHERE metric_run_id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), run_id))
    except Exception as exc:
        with connect(database) as connection:
            connection.execute("UPDATE metric_run SET finished_at=?, status='failed', error_message=? WHERE metric_run_id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(exc), run_id))
        raise
    return run_id


def public_report(report: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in report.items() if key != "details"}


def run(
    database: Path,
    start_date: str,
    end_date: str,
    *,
    mode: str = "both",
    output: Path | None = None,
    business_types: list[str] | None = None,
    all_business_types: bool = False,
    withdrawal_statuses: list[str] | None = None,
    test_keywords: list[str] | None = None,
) -> dict[str, object]:
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    database = database.expanduser().resolve() if database is not None else None
    rows, source_runs = load_rows(database)
    if not source_runs:
        raise RuntimeError("数据库中没有一体化售中开通工单的成功取数批次")
    report = calculate(rows, start_date, end_date, business_types=business_types, all_business_types=all_business_types, withdrawal_statuses=withdrawal_statuses, test_keywords=test_keywords)
    report["source_runs"] = source_runs
    report["metric_run_id"] = save_results(database, report, source_runs) if mode in {"database", "both"} else None
    if mode in {"file", "both"}:
        output = (output or Path(f"outputs/专线开通撤退单率_{start_date}_{end_date}.json")).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(public_report(report), ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_file"] = str(output)
    else:
        report["output_file"] = None
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="从数据库计算一体化专线开通撤退单率")
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
    parser.add_argument("--month", help="月报月份 YYYY-MM；自动使用上月26日至本月25日")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--business-type", action="append", dest="business_types", help="可重复指定，在固定排除规则之后进一步限定业务类型")
    parser.add_argument("--all-business-types", action="store_true", help="兼容参数：不额外限定业务类型，固定排除规则仍然生效")
    parser.add_argument("--withdrawal-status", action="append", dest="withdrawal_statuses", help="可重复指定，默认已撤单、已驳回")
    parser.add_argument("--test-keyword", action="append", dest="test_keywords", help="工单主题测试关键词，可重复指定")
    args = parser.parse_args()
    if args.month:
        if args.start_date or args.end_date:
            parser.error("--month 不能与 --start-date/--end-date 同时使用")
        try:
            start_date, end_date = integration_opening_period(args.month)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        if not args.start_date or not args.end_date:
            parser.error("请指定 --month，或同时指定 --start-date 和 --end-date")
        start_date, end_date = args.start_date, args.end_date
    report = run(args.database, start_date, end_date, mode=args.mode, output=args.output, business_types=args.business_types, all_business_types=args.all_business_types, withdrawal_statuses=args.withdrawal_statuses, test_keywords=args.test_keywords)
    print(json.dumps({"metric_run_id": report["metric_run_id"], "quality": report["quality"], "results": report["results"], "output_file": report["output_file"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
