"""从数据库计算编排专线开通量、产品分布及自动率指标。"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from storage.database import connect, initialize


DATASET_CODE = "orch_opening"
METRIC_CODE = "orchestration_opening_metrics"
METRIC_VERSION = "1.0.0"
STATUS = "已完成"
BUSINESS_TYPE = "互联网专线"
MPLS_BUSINESS_TYPE = "MPLS-VPN专线"
TRANSMISSION_BUSINESS_TYPE = "传输专线"

KEY_PRODUCTS = ["悦享专线动态IP版", "互联网专线套餐", "商务专线套餐（2020版）"]
ALL_PRODUCTS = [
    "悦享专线动态IP版", "互联网专线套餐", "商务专线套餐（2020版）",
    "直播专线", "网吧专线套餐（2019版）", "高品质互联网专线",
]
OTHER_PRODUCTS = ["商务专线套餐（2020版）", "直播专线", "网吧专线套餐（2019版）", "高品质互联网专线"]
MPLS_PRODUCTS = ["地区内MPLSVPN套餐", "省内MPLSVPN套餐"]
TRANSMISSION_PRODUCTS = [
    "地区间精品电路", "地区间数字电路出租套餐", "地区内SPN电路出租",
    "地区内精品电路", "地区内数字电路出租套餐", "光纤出租套餐",
]
CITY_ORDER = ["杭州市", "嘉兴市", "宁波市", "温州市", "金华市", "绍兴市", "湖州市", "台州市", "衢州市", "丽水市", "舟山市"]
DATE_FIELDS = ["订单结束时间", "结束时间", "完成时间", "订单完成时间", "报结时间"]
OPENING_STAGES = [
    ("受理", "受理人", "系统自动"),
    ("方案设计", "方案设计处理人", "系统自动"),
    ("资源分配", "资源分配受理人", "自动处理"),
    ("配置激活", "配置激活处理人", "系统自动"),
    ("开通结果审核", "开通结果审核处理人", "系统自动"),
    ("报结", "报结人", "自动处理"),
]
REMOVAL_STAGES = [
    ("受理", "受理人", "系统自动"),
    ("资源查询", "资源查询受理人", "自动处理"),
    ("配置激活", "配置激活处理人", "系统自动"),
    ("开通结果审核", "开通结果审核处理人", "系统自动"),
    ("报结", "报结人", "自动处理"),
]


def text(value: object) -> str:
    return "" if value is None else str(value).strip()


def parse_month(value: object) -> str | None:
    raw = text(value)
    if len(raw) >= 7 and raw[4] in {"-", "/"}:
        candidate = raw[:7].replace("/", "-")
        try:
            datetime.strptime(candidate, "%Y-%m")
            return candidate
        except ValueError:
            return None
    if len(raw) >= 6 and raw[:6].isdigit():
        candidate = f"{raw[:4]}-{raw[4:6]}"
        try:
            datetime.strptime(candidate, "%Y-%m")
            return candidate
        except ValueError:
            return None
    return None


def row_month(row: dict[str, object]) -> str | None:
    for field in DATE_FIELDS:
        month = parse_month(row.get(field))
        if month:
            return month
    return None


def shift_month(month: str, offset: int) -> str:
    value = datetime.strptime(month, "%Y-%m")
    index = value.year * 12 + value.month - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_range(start: str, end: str) -> list[str]:
    if shift_month(start, 0) > shift_month(end, 0):
        raise ValueError("start_month 不能晚于 end_month")
    result, current = [], shift_month(start, 0)
    while current <= end:
        result.append(current)
        current = shift_month(current, 1)
    return result


def month_dates(month: str) -> tuple[str, str]:
    value = datetime.strptime(month, "%Y-%m")
    return f"{month}-01", f"{month}-{calendar.monthrange(value.year, value.month)[1]:02d}"


def load_rows(database: Path) -> tuple[list[dict[str, object]], list[str]]:
    initialize(database)
    with connect(database) as connection:
        records = connection.execute(
            "SELECT order_no, source_data FROM ods_orch_opening"
        ).fetchall()
        runs = connection.execute(
            """SELECT run_id FROM etl_run
               WHERE dataset_code=? AND status='success' ORDER BY started_at""",
            (DATASET_CODE,),
        ).fetchall()
    rows = []
    for record in records:
        row = json.loads(record["source_data"])
        row["_source_record_id"] = record["order_no"]
        rows.append(row)
    return rows, [row["run_id"] for row in runs]


def order_count(rows: Iterable[dict[str, object]]) -> int:
    keys, empty = set(), 0
    for row in rows:
        key = text(row.get("订单号"))
        if key:
            keys.add(key)
        else:
            empty += 1
    return len(keys) + empty


def select(
    rows: Iterable[dict[str, object]],
    *,
    month: str,
    business_type: str,
    order_type: str = "开通",
    product: str | None = None,
    city: str | None = None,
) -> list[dict[str, object]]:
    return [
        row for row in rows
        if row_month(row) == month
        and text(row.get("订单状态")) == STATUS
        and text(row.get("业务类型")) == business_type
        and text(row.get("订单类型")) == order_type
        and (product is None or text(row.get("产品名称")) == product)
        and (city is None or text(row.get("地市")) == city)
    ]


def result(
    code: str,
    dimension_type: str,
    dimension: dict[str, str],
    numerator: float | int,
    denominator: float | int | None = None,
) -> dict[str, object]:
    value = numerator if denominator is None else (numerator / denominator if denominator else None)
    return {
        "metric_code": code,
        "dimension_type": dimension_type,
        "dimension": dimension,
        "numerator": numerator,
        "denominator": denominator,
        "metric_value": value,
    }


def volume_results(rows: list[dict[str, object]], months: list[str]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for month in months:
        for business_type, products, code in [
            (BUSINESS_TYPE, None, "internet_opening_orders"),
            (MPLS_BUSINESS_TYPE, MPLS_PRODUCTS, "mpls_opening_orders"),
            (TRANSMISSION_BUSINESS_TYPE, TRANSMISSION_PRODUCTS, "transmission_opening_orders"),
        ]:
            source = select(rows, month=month, business_type=business_type)
            if products is not None:
                source = [row for row in source if text(row.get("产品名称")) in products]
            output.append(result(code, "month", {"month": month}, order_count(source)))
            for product in products or (ALL_PRODUCTS if business_type == BUSINESS_TYPE else []):
                count = order_count(row for row in source if text(row.get("产品名称")) == product)
                output.append(result(code, "month_product", {"month": month, "product": product}, count))
    return output


def current_distribution(rows: list[dict[str, object]], month: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for business_type, products, code in [
        (BUSINESS_TYPE, ALL_PRODUCTS, "internet_opening_orders"),
        (MPLS_BUSINESS_TYPE, MPLS_PRODUCTS, "mpls_opening_orders"),
        (TRANSMISSION_BUSINESS_TYPE, TRANSMISSION_PRODUCTS, "transmission_opening_orders"),
    ]:
        for city in CITY_ORDER:
            for product in products:
                count = order_count(select(rows, month=month, business_type=business_type, product=product, city=city))
                output.append(result(code, "month_city_product", {"month": month, "city": city, "product": product}, count))
    return output


def automation_results(rows: list[dict[str, object]], month: str) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for order_type, stages, prefix in [
        ("开通", OPENING_STAGES, "internet_opening_automation_rate"),
        ("变更", OPENING_STAGES, "internet_move_automation_rate"),
        ("拆除", REMOVAL_STAGES, "internet_removal_automation_rate"),
    ]:
        source = select(rows, month=month, business_type=BUSINESS_TYPE, order_type=order_type)
        denominator = order_count(source)
        automatic_total = 0
        for stage, field, automatic_value in stages:
            numerator = order_count(row for row in source if text(row.get(field)) == automatic_value)
            automatic_total += numerator
            output.append(result(prefix, "month_stage", {"month": month, "stage": stage, "field": field, "automatic_value": automatic_value}, numerator, denominator))
        output.append(result(prefix, "month_all_stages", {"month": month, "stage": f"{len(stages)}环节整体"}, automatic_total, denominator * len(stages)))
        if order_type in {"变更", "拆除"}:
            city_code = "internet_move_activation_rate" if order_type == "变更" else "internet_removal_activation_rate"
            for city in CITY_ORDER:
                city_rows = [row for row in source if text(row.get("地市")) == city]
                city_total = order_count(city_rows)
                city_auto = order_count(row for row in city_rows if text(row.get("配置激活处理人")) == "系统自动")
                output.append(result(city_code, "month_city", {"month": month, "city": city}, city_auto, city_total))
    return output


def comparison_results(results: list[dict[str, object]], current: str) -> list[dict[str, object]]:
    previous, last_year = shift_month(current, -1), shift_month(current, -12)
    lookup = {
        (item["metric_code"], json.dumps(item["dimension"], ensure_ascii=False, sort_keys=True)): item
        for item in results if item["dimension_type"] in {"month", "month_product"}
    }
    output: list[dict[str, object]] = []
    for code in ["internet_opening_orders", "mpls_opening_orders", "transmission_opening_orders"]:
        current_item = lookup.get((code, json.dumps({"month": current}, ensure_ascii=False, sort_keys=True)))
        if not current_item:
            continue
        current_value = int(current_item["numerator"])
        for comparison, label in [(previous, "mom"), (last_year, "yoy")]:
            other = lookup.get((code, json.dumps({"month": comparison}, ensure_ascii=False, sort_keys=True)))
            other_value = int(other["numerator"]) if other else 0
            output.append(result(f"{code}_{label}", "month_comparison", {"month": current, "comparison_month": comparison}, current_value - other_value, other_value))
    for product in KEY_PRODUCTS:
        current_key = json.dumps({"month": current, "product": product}, ensure_ascii=False, sort_keys=True)
        last_key = json.dumps({"month": last_year, "product": product}, ensure_ascii=False, sort_keys=True)
        current_value = int((lookup.get(("internet_opening_orders", current_key)) or {"numerator": 0})["numerator"])
        last_value = int((lookup.get(("internet_opening_orders", last_key)) or {"numerator": 0})["numerator"])
        output.append(result("internet_product_opening_yoy", "month_product_comparison", {"month": current, "comparison_month": last_year, "product": product}, current_value - last_value, last_value))
    return output


def calculate(rows: list[dict[str, object]], start_month: str, end_month: str) -> dict[str, object]:
    trend_months = month_range(start_month, end_month)
    required = sorted(set(trend_months + [shift_month(end_month, -1), shift_month(end_month, -12)] + [shift_month(end_month, offset) for offset in range(-11, 1)]))
    volumes = volume_results(rows, required)
    results = volumes + current_distribution(rows, end_month) + automation_results(rows, end_month)
    results += comparison_results(volumes, end_month)

    internet_month_counts = {
        item["dimension"]["month"]: int(item["numerator"])
        for item in volumes
        if item["metric_code"] == "internet_opening_orders" and item["dimension_type"] == "month"
    }
    other_total = 0
    for month in [shift_month(end_month, offset) for offset in range(-11, 1)]:
        source = select(rows, month=month, business_type=BUSINESS_TYPE)
        count = order_count(source) - order_count(row for row in source if text(row.get("产品名称")) == "悦享专线动态IP版") - order_count(row for row in source if text(row.get("产品名称")) == "互联网专线套餐")
        other_total += count
        results.append(result("other_internet_opening_orders", "month", {"month": month}, count))
    results.append(result("other_internet_average_monthly_orders", "rolling_12_months", {"end_month": end_month}, other_total, 12))

    missing_month_rows = sum(1 for row in rows if row_month(row) is None)
    return {
        "metric_code": METRIC_CODE,
        "metric_version": METRIC_VERSION,
        "start_month": start_month,
        "end_month": end_month,
        "quality": {"database_rows": len(rows), "rows_missing_order_month": missing_month_rows},
        "results": results,
    }


def save_results(database: Path, report: dict[str, object], source_runs: list[str]) -> str:
    initialize(database)
    run_id = f"metric_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    period_start, _ = month_dates(str(report["start_month"]))
    _, period_end = month_dates(str(report["end_month"]))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(database) as connection:
        connection.execute(
            """INSERT INTO metric_run (metric_run_id, metric_code, metric_version,
               period_start, period_end, started_at, status, source_runs)
               VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
            (run_id, METRIC_CODE, METRIC_VERSION, period_start, period_end, now, json.dumps(source_runs)),
        )
        connection.commit()
    try:
        with connect(database) as connection:
            for item in report["results"]:
                connection.execute(
                    """INSERT INTO ads_metric_result (
                       metric_run_id, metric_code, dimension_type, dimension_value,
                       numerator, denominator, metric_value
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, item["metric_code"], item["dimension_type"], json.dumps(item["dimension"], ensure_ascii=False, sort_keys=True), item["numerator"], item["denominator"], item["metric_value"]),
                )
            connection.execute("UPDATE metric_run SET finished_at=?, status='success' WHERE metric_run_id=?", (now, run_id))
    except Exception as exc:
        with connect(database) as connection:
            connection.execute(
                "UPDATE metric_run SET finished_at=?, status='failed', error_message=? WHERE metric_run_id=?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(exc), run_id),
            )
        raise
    return run_id


def run(database: Path, start_month: str, end_month: str, *, mode: str = "both", output: Path | None = None) -> dict[str, object]:
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    database = database.expanduser().resolve()
    rows, source_runs = load_rows(database)
    if not source_runs:
        raise RuntimeError("数据库中没有编排专线开通情况的成功取数批次")
    report = calculate(rows, start_month, end_month)
    report["source_runs"] = source_runs
    report["metric_run_id"] = save_results(database, report, source_runs) if mode in {"database", "both"} else None
    if mode in {"file", "both"}:
        output = (output or Path(f"outputs/编排专线指标_{end_month}.json")).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_file"] = str(output)
    else:
        report["output_file"] = None
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="从数据库计算编排专线开通类指标")
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    parser.add_argument("--start-month", required=True, help="趋势起始月份，YYYY-MM")
    parser.add_argument("--end-month", required=True, help="最新统计月份，YYYY-MM")
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.database, args.start_month, args.end_month, mode=args.mode, output=args.output)
    print(json.dumps({
        "metric_run_id": report["metric_run_id"],
        "result_count": len(report["results"]),
        "quality": report["quality"],
        "output_file": report["output_file"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
