"""新装报障类指标的数据库读取、标准化与结果持久化。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from storage.database import connect, initialize


EMPTY_IDENTIFIERS = {"", "/", "nan", "none", "null", "无"}


def text(value: object) -> str:
    return "" if value is None else str(value).strip()


def identifier(value: object) -> str:
    value = text(value).upper()
    if value.lower() in EMPTY_IDENTIFIERS:
        return ""
    return value[:-2] if value.endswith(".0") else value


def city(value: object) -> str:
    value = text(value)
    return value[:-1] if value.endswith("市") else value


def parse_time(value: object) -> datetime | None:
    raw = text(value).replace("/", "-").replace("T", " ")
    for length, pattern in [(26, "%Y-%m-%d %H:%M:%S.%f"), (19, "%Y-%m-%d %H:%M:%S"), (16, "%Y-%m-%d %H:%M"), (10, "%Y-%m-%d")]:
        try:
            return datetime.strptime(raw[:length], pattern)
        except ValueError:
            continue
    return None


def period_bounds(start: str, end: str) -> tuple[datetime, datetime]:
    start_time, end_time = parse_time(start), parse_time(end)
    if start_time is None or end_time is None:
        raise ValueError("日期格式应为 YYYY-MM-DD")
    end_time = end_time.replace(hour=23, minute=59, second=59, microsecond=999999)
    if start_time > end_time:
        raise ValueError("开始日期不能晚于结束日期")
    return start_time, end_time


def load_dataset(database: Path, dataset_code: str) -> tuple[list[dict[str, object]], list[str]]:
    initialize(database)
    with connect(database) as connection:
        records = connection.execute(
            "SELECT source_record_id, source_data FROM raw_source_record WHERE dataset_code=?",
            (dataset_code,),
        ).fetchall()
        runs = connection.execute(
            "SELECT run_id FROM etl_run WHERE dataset_code=? AND status='success' ORDER BY started_at",
            (dataset_code,),
        ).fetchall()
    rows = []
    for record in records:
        row = json.loads(record["source_data"])
        row["_source_record_id"] = record["source_record_id"]
        rows.append(row)
    return rows, [row["run_id"] for row in runs]


def result_row(metric_code: str, dimension_type: str, dimension: dict[str, str], numerator: int, denominator: int) -> dict[str, object]:
    return {
        "metric_code": metric_code,
        "dimension_type": dimension_type,
        "dimension": dimension,
        "numerator": numerator,
        "denominator": denominator,
        "metric_value": numerator / denominator if denominator else None,
    }


def save_metric(
    database: Path,
    report: dict[str, object],
    source_runs: list[str],
    *,
    details: dict[str, list[dict[str, object]]] | None = None,
) -> str:
    initialize(database)
    run_id = f"metric_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(database) as connection:
        connection.execute(
            """INSERT INTO metric_run (metric_run_id, metric_code, metric_version,
               period_start, period_end, started_at, status, source_runs)
               VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
            (run_id, report["metric_code"], report["metric_version"], report["period_start"], report["period_end"], now, json.dumps(source_runs)),
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
            scope = json.dumps({"period_start": report["period_start"], "period_end": report["period_end"]}, ensure_ascii=False, sort_keys=True)
            for role, records in (details or {}).items():
                for row in records:
                    source_id = text(row.get("_source_record_id"))
                    if not source_id:
                        continue
                    connection.execute(
                        """INSERT INTO ads_metric_detail (metric_run_id, metric_code,
                           detail_role, source_dataset_code, source_record_id,
                           dimension_value, detail_data) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (run_id, report["metric_code"], role, row["_dataset_code"], source_id, scope, json.dumps({k: v for k, v in row.items() if not k.startswith("_")}, ensure_ascii=False, sort_keys=True)),
                    )
            connection.execute("UPDATE metric_run SET finished_at=?, status='success' WHERE metric_run_id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), run_id))
    except Exception as exc:
        with connect(database) as connection:
            connection.execute("UPDATE metric_run SET finished_at=?, status='failed', error_message=? WHERE metric_run_id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(exc), run_id))
        raise
    return run_id


def write_report(report: dict[str, object], output: Path) -> str:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    public = {key: value for key, value in report.items() if key != "details"}
    output.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output)
