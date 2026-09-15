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

from storage.database import connect, initialize


DATASET_CODE = "integration_opening"
METRIC_CODE = "dedicated_line_opening_withdrawal_rate"
METRIC_VERSION = "1.0.0-provisional"
DEFAULT_BUSINESS_TYPES = ["互联网专线"]
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
        records = connection.execute(
            """SELECT source_record_id, source_data FROM raw_source_record
               WHERE dataset_code=?""",
            (DATASET_CODE,),
        ).fetchall()
        source_runs = connection.execute(
            """SELECT run_id FROM etl_run WHERE dataset_code=? AND status='success'
               ORDER BY started_at""",
            (DATASET_CODE,),
        ).fetchall()
    rows = []
    for record in records:
        row = json.loads(record["source_data"])
        row["_source_record_id"] = record["source_record_id"]
        rows.append(row)
    return rows, [item["run_id"] for item in source_runs]


def is_test_order(row: dict[str, object], keywords: list[str]) -> bool:
    title = text(row.get("工单主题")).lower()
    return any(keyword.lower() in title for keyword in keywords if keyword)


def deduplicate_latest(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
    latest: dict[str, tuple[datetime, int, dict[str, object]]] = {}
    missing = 0
    for index, row in enumerate(rows):
        order_id = text(row.get("工单号"))
        if not order_id:
            missing += 1
            continue
        end_time = parse_time(row.get("工单结束时间")) or datetime.min
        current = latest.get(order_id)
        if current is None or (end_time, index) > (current[0], current[1]):
            latest[order_id] = (end_time, index, row)
    return [item[2] for item in latest.values()], missing


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
    base = [
        row for row in in_period
        if text(row.get("工单数据来源")) == "二编"
        and text(row.get("工单类型")) == "开通"
        and (all_business_types or text(row.get("业务类型")) in business_types)
    ]
    excluded_test = [row for row in base if is_test_order(row, keywords)]
    formal = [row for row in base if not is_test_order(row, keywords)]
    deduplicated, missing_order_id = deduplicate_latest(formal)
    numerator_rows = [row for row in deduplicated if text(row.get("工单状态")) in statuses]

    results = [rate_row("province", {"scope": "全省"}, deduplicated, statuses)]
    cities = sorted({text(row.get("地市")) for row in deduplicated if text(row.get("地市"))})
    for city in cities:
        results.append(rate_row("city", {"city": city}, [row for row in deduplicated if text(row.get("地市")) == city], statuses))
    types = sorted({text(row.get("业务类型")) for row in deduplicated if text(row.get("业务类型"))})
    for business_type in types:
        results.append(rate_row("business_type", {"business_type": business_type}, [row for row in deduplicated if text(row.get("业务类型")) == business_type], statuses))

    return {
        "metric_code": METRIC_CODE,
        "metric_version": METRIC_VERSION,
        "period_start": start_date,
        "period_end": end_date,
        "rules": {
            "business_types": "全部" if all_business_types else business_types,
            "withdrawal_statuses": statuses,
            "test_title_keywords": keywords,
            "failed_status_in_numerator": "失败" in statuses,
        },
        "quality": {
            "database_rows": len(rows),
            "rows_missing_end_time": missing_end_time,
            "rows_in_period": len(in_period),
            "rows_before_test_exclusion": len(base),
            "excluded_test_orders": len(excluded_test),
            "rows_missing_order_id": missing_order_id,
            "denominator_orders": len(deduplicated),
            "numerator_orders": len(numerator_rows),
            "status_distribution": dict(Counter(text(row.get("工单状态")) for row in deduplicated)),
        },
        "results": results,
        "details": {
            "denominator": deduplicated,
            "numerator": numerator_rows,
            "excluded": excluded_test,
        },
    }


def audit_payload(row: dict[str, object]) -> dict[str, object]:
    fields = ["工单号", "工单主题", "地市", "区县", "业务类型", "工单状态", "工单结束时间", "是否撤单重录", "计费号/产品实例编号"]
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
            for item in report["results"]:
                connection.execute(
                    """INSERT INTO ads_metric_result (metric_run_id, metric_code,
                       dimension_type, dimension_value, numerator, denominator, metric_value)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, item["metric_code"], item["dimension_type"], json.dumps(item["dimension"], ensure_ascii=False, sort_keys=True), item["numerator"], item["denominator"], item["metric_value"]),
                )
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
    database = database.expanduser().resolve()
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
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--business-type", action="append", dest="business_types", help="可重复指定，默认仅互联网专线")
    parser.add_argument("--all-business-types", action="store_true", help="不筛选业务类型，用于复现README全量样例")
    parser.add_argument("--withdrawal-status", action="append", dest="withdrawal_statuses", help="可重复指定，默认已撤单、已驳回")
    parser.add_argument("--test-keyword", action="append", dest="test_keywords", help="工单主题测试关键词，可重复指定")
    args = parser.parse_args()
    report = run(args.database, args.start_date, args.end_date, mode=args.mode, output=args.output, business_types=args.business_types, all_business_types=args.all_business_types, withdrawal_statuses=args.withdrawal_statuses, test_keywords=args.test_keywords)
    print(json.dumps({"metric_run_id": report["metric_run_id"], "quality": report["quality"], "results": report["results"], "output_file": report["output_file"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
