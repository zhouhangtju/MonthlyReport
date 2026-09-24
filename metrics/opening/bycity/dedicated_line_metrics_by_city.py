#!/usr/bin/env python3
"""按指定地市计算编排专线开通量、趋势及区县产品分布。"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from storage.database import connect, initialize
from storage.metric_results import insert_results


DATASET_CODE = "orch_opening"
METRIC_CODE = "orchestration_opening_metrics_by_city"
RESULT_OWNER = "orchestration_opening_metrics"
METRIC_VERSION = "1.0.0"
STATUS = "已完成"

BUSINESS_GROUPS = [
    (
        "互联网专线",
        "internet_opening_orders",
        [
            "悦享专线动态IP版",
            "互联网专线套餐",
            "商务专线套餐（2020版）",
            "直播专线",
            "网吧专线套餐（2019版）",
            "高品质互联网专线",
        ],
    ),
    (
        "MPLS-VPN专线",
        "mpls_opening_orders",
        ["地区内MPLSVPN套餐", "省内MPLSVPN套餐"],
    ),
    (
        "传输专线",
        "transmission_opening_orders",
        [
            "地区间精品电路",
            "地区间数字电路出租套餐",
            "地区内SPN电路出租",
            "地区内精品电路",
            "地区内数字电路出租套餐",
            "光纤出租套餐",
        ],
    ),
]
INTERNET_PRODUCTS = BUSINESS_GROUPS[0][2]
OTHER_INTERNET_PRODUCTS = INTERNET_PRODUCTS[2:]
KEY_PRODUCTS = INTERNET_PRODUCTS[:3]
UNASSIGNED_COUNTY = "未归属区县"


def log(message: str) -> None:
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] {message}", flush=True)


def text(value: object) -> str:
    return "" if value is None else str(value).strip()


def normalize_city(value: str) -> str:
    value = text(value)
    return value[:-1] if value.endswith("市") else value


def display_city(value: str) -> str:
    value = normalize_city(value)
    return f"{value}市"


def county_name(value: object) -> str:
    return text(value) or UNASSIGNED_COUNTY


def shift_month(month: str, offset: int) -> str:
    value = datetime.strptime(month, "%Y-%m")
    index = value.year * 12 + value.month - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_range(start: str, end: str) -> list[str]:
    start = shift_month(start, 0)
    end = shift_month(end, 0)
    if start > end:
        raise ValueError("start-month 不能晚于 end-month")
    output = []
    while start <= end:
        output.append(start)
        start = shift_month(start, 1)
    return output


def month_dates(month: str) -> tuple[str, str]:
    value = datetime.strptime(month, "%Y-%m")
    return f"{month}-01", f"{month}-{calendar.monthrange(value.year, value.month)[1]:02d}"


def result(code: str, dimension_type: str, dimension: dict[str, str], numerator: float | int,
           denominator: float | int | None = None) -> dict[str, object]:
    return {
        "metric_code": code,
        "dimension_type": dimension_type,
        "dimension": dimension,
        "numerator": numerator,
        "denominator": denominator,
        "metric_value": numerator if denominator is None else (numerator / denominator if denominator else None),
    }


def summarize_month(connection, month: str, city: str, batch_size: int, temp_dir: Path | None,
                    include_counties: bool) -> tuple[list[dict[str, object]], dict[str, object]]:
    """流式读取一个月，并用临时 SQLite 按订单号执行最后记录优先去重。"""
    from pymysql.cursors import SSDictCursor

    raw_rows = missing_county = 0
    normalized_city = normalize_city(city)
    city_values = [normalized_city, display_city(normalized_city)]
    with tempfile.TemporaryDirectory(prefix="opening_bycity_", dir=temp_dir) as directory:
        import sqlite3

        cache = sqlite3.connect(str(Path(directory) / "dedup.sqlite"))
        try:
            cache.execute("PRAGMA temp_store=FILE")
            cache.execute(
                """CREATE TABLE records (
                    order_no TEXT PRIMARY KEY,
                    business_type TEXT,
                    product TEXT,
                    county TEXT
                ) WITHOUT ROWID"""
            )
            sql = (
                "SELECT `订单号`,`业务类型`,`产品名称`,`区县名称` FROM orch_opening "
                "WHERE NULLIF(TRIM(`订单结束时间`), '') >= %s "
                "AND NULLIF(TRIM(`订单结束时间`), '') < %s "
                "AND `订单状态`=%s AND `订单类型`=%s AND `地市` IN (%s,%s)"
            )
            with connection._connection.cursor(SSDictCursor) as cursor:
                cursor.execute(sql, (f"{month}-01", f"{shift_month(month, 1)}-01", STATUS, "开通", *city_values))
                while True:
                    batch = cursor.fetchmany(batch_size)
                    if not batch:
                        break
                    pending = []
                    for row in batch:
                        raw_rows += 1
                        county = county_name(row.get("区县名称"))
                        if county == UNASSIGNED_COUNTY:
                            missing_county += 1
                        pending.append((text(row.get("订单号")), text(row.get("业务类型")),
                                        text(row.get("产品名称")), county))
                    cache.executemany("INSERT OR REPLACE INTO records VALUES (?,?,?,?)", pending)
                    cache.commit()

            totals: Counter = Counter()
            products: Counter = Counter()
            counties: Counter = Counter()
            county_products: Counter = Counter()
            allowed = {business: set(product_names) for business, _code, product_names in BUSINESS_GROUPS}
            for business, product, county in cache.execute("SELECT business_type,product,county FROM records"):
                if business not in allowed:
                    continue
                if business != "互联网专线" and product not in allowed[business]:
                    continue
                totals[business] += 1
                if product in allowed[business]:
                    products[business, product] += 1
                if include_counties:
                    counties[business, county] += 1
                    if product in allowed[business]:
                        county_products[business, county, product] += 1

            city_label = display_city(city)
            output: list[dict[str, object]] = []
            for business, code, product_names in BUSINESS_GROUPS:
                output.append(result(code, "month_city", {"month": month, "city": city_label}, totals[business]))
                for product in product_names:
                    output.append(result(
                        code,
                        "month_city_product",
                        {"month": month, "city": city_label, "product": product},
                        products[business, product],
                    ))
                if include_counties:
                    county_labels = sorted({key[1] for key in counties if key[0] == business})
                    for county in county_labels:
                        output.append(result(
                            code,
                            "month_city_county",
                            {"month": month, "city": city_label, "county": county},
                            counties[business, county],
                        ))
                        for product in product_names:
                            output.append(result(
                                code,
                                "month_city_county_product",
                                {"month": month, "city": city_label, "county": county, "product": product},
                                county_products[business, county, product],
                            ))
            return output, {
                "database_rows": raw_rows,
                "missing_county_rows": missing_county,
                "county_values": sorted({key[1] for key in counties}),
            }
        finally:
            cache.close()


def find(results: list[dict[str, object]], code: str, dimension_type: str, **dims: str) -> dict[str, object] | None:
    return next((item for item in results
                 if item["metric_code"] == code and item["dimension_type"] == dimension_type
                 and all(item["dimension"].get(key) == value for key, value in dims.items())), None)


def number(item: dict[str, object] | None) -> int:
    return int(item["numerator"]) if item else 0


def add_comparisons(results: list[dict[str, object]], city: str, end_month: str) -> None:
    previous = shift_month(end_month, -1)
    last_year = shift_month(end_month, -12)
    product_yoy_codes = {
        "internet_opening_orders": "internet_product_opening_yoy",
        "mpls_opening_orders": "mpls_product_opening_yoy",
        "transmission_opening_orders": "transmission_product_opening_yoy",
    }
    for _business, code, products in BUSINESS_GROUPS:
        current = number(find(results, code, "month_city", month=end_month, city=city))
        for comparison, suffix in ((previous, "mom"), (last_year, "yoy")):
            baseline = number(find(results, code, "month_city", month=comparison, city=city))
            results.append(result(
                f"{code}_{suffix}",
                "month_city_comparison",
                {"month": end_month, "comparison_month": comparison, "city": city},
                current - baseline,
                baseline,
            ))
        for product in products:
            current_product = number(find(results, code, "month_city_product", month=end_month,
                                          city=city, product=product))
            baseline_product = number(find(results, code, "month_city_product", month=last_year,
                                           city=city, product=product))
            results.append(result(
                product_yoy_codes[code],
                "month_city_product_comparison",
                {"month": end_month, "comparison_month": last_year, "city": city, "product": product},
                current_product - baseline_product,
                baseline_product,
            ))


def add_rolling_results(results: list[dict[str, object]], city: str, end_month: str) -> None:
    months = {shift_month(end_month, offset) for offset in range(-11, 1)}
    for product in INTERNET_PRODUCTS[:2]:
        total = sum(number(item) for item in results
                    if item["metric_code"] == "internet_opening_orders"
                    and item["dimension_type"] == "month_city_product"
                    and item["dimension"].get("city") == city
                    and item["dimension"].get("product") == product
                    and item["dimension"].get("month") in months)
        results.append(result(
            "internet_product_average_monthly_orders",
            "rolling_12_months_city_product",
            {"end_month": end_month, "city": city, "product": product},
            total,
            12,
        ))
    other_total = sum(
        number(item) for item in results
        if item["metric_code"] == "internet_opening_orders"
        and item["dimension_type"] == "month_city_product"
        and item["dimension"].get("city") == city
        and item["dimension"].get("product") in OTHER_INTERNET_PRODUCTS
        and item["dimension"].get("month") in months
    )
    results.append(result(
        "other_internet_average_monthly_orders",
        "rolling_12_months_city",
        {"end_month": end_month, "city": city},
        other_total,
        12,
    ))


def calculate(database: Path | None, city: str, start_month: str, end_month: str,
              batch_size: int = 5000, temp_dir: Path | None = None) -> tuple[dict[str, object], list[str]]:
    if batch_size < 1:
        raise ValueError("batch-size 必须大于 0")
    city_label = display_city(city)
    trend_months = month_range(start_month, end_month)
    required = sorted(set(trend_months + [shift_month(end_month, -1), shift_month(end_month, -12)]
                          + [shift_month(end_month, offset) for offset in range(-11, 1)]))
    initialize(database)
    results: list[dict[str, object]] = []
    quality = {"database_rows": 0, "missing_county_rows": 0, "months_with_rows": [], "counties": []}
    with connect(database) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        connection.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        source_runs = [row["run_id"] for row in connection.execute(
            "SELECT run_id FROM etl_run WHERE dataset_code=? AND status='success' ORDER BY started_at",
            (DATASET_CODE,),
        ).fetchall()]
        if not source_runs:
            raise RuntimeError("数据库中没有 orch_opening 的成功取数批次")
        for month in required:
            log(f"开始计算 {city_label} {month} 指标")
            monthly, stats = summarize_month(connection, month, city, batch_size, temp_dir,
                                             include_counties=month == end_month)
            results.extend(monthly)
            quality["database_rows"] += stats["database_rows"]
            quality["missing_county_rows"] += stats["missing_county_rows"]
            if stats["database_rows"]:
                quality["months_with_rows"].append(month)
            if month == end_month:
                quality["counties"] = stats["county_values"]
    missing_months = [month for month in required if month not in quality["months_with_rows"]]
    if missing_months:
        raise RuntimeError(
            f"{city_label} 缺少必要月份的 orch_opening 明细：{', '.join(missing_months)}；"
            "请先补取或从归档恢复，不能将缺失月份按0计算"
        )
    add_comparisons(results, city_label, end_month)
    add_rolling_results(results, city_label, end_month)
    report = {
        "metric_code": METRIC_CODE,
        "metric_version": METRIC_VERSION,
        "city": city_label,
        "start_month": start_month,
        "end_month": end_month,
        "quality": quality,
        "results": results,
    }
    return report, source_runs


def save_results(database: Path | None, report: dict[str, object], source_runs: list[str]) -> str:
    run_id = f"metric_city_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    period_start, _ = month_dates(str(report["start_month"]))
    _, period_end = month_dates(str(report["end_month"]))
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(database) as connection:
        connection.execute(
            """INSERT INTO metric_run (
                metric_run_id, metric_code, metric_version, period_start, period_end,
                started_at, status, source_runs
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
            (run_id, METRIC_CODE, METRIC_VERSION, period_start, period_end, now,
             json.dumps(source_runs, ensure_ascii=False)),
        )
        connection.commit()
    try:
        with connect(database) as connection:
            insert_results(connection, RESULT_OWNER, run_id, report["results"])
            connection.execute(
                "UPDATE metric_run SET finished_at=?, status='success' WHERE metric_run_id=?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), run_id),
            )
    except Exception as exc:
        with connect(database) as connection:
            connection.execute(
                "UPDATE metric_run SET finished_at=?, status='failed', error_message=? WHERE metric_run_id=?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), str(exc), run_id),
            )
        raise
    return run_id


def print_report(report: dict[str, object]) -> None:
    city = str(report["city"])
    month = str(report["end_month"])
    rows = list(report["results"])
    total = number(find(rows, "internet_opening_orders", "month_city", month=month, city=city))
    yoy = find(rows, "internet_opening_orders_yoy", "month_city_comparison", month=month, city=city)
    mom = find(rows, "internet_opening_orders_mom", "month_city_comparison", month=month, city=city)
    log(f"{city} {month} 互联网专线开通量：{total} 单")
    log(f"同比：{yoy['metric_value'] if yoy else None}；环比：{mom['metric_value'] if mom else None}")
    for county in report["quality"]["counties"]:
        county_total = number(find(rows, "internet_opening_orders", "month_city_county",
                                   month=month, city=city, county=county))
        log(f"  {county}：{county_total} 单")


def run(database: Path | None, city: str, start_month: str, end_month: str, *, mode: str = "both",
        output: Path | None = None, batch_size: int = 5000, temp_dir: Path | None = None) -> dict[str, object]:
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    report, source_runs = calculate(database, city, start_month, end_month, batch_size, temp_dir)
    report["source_runs"] = source_runs
    print_report(report)
    if mode in {"database", "both"}:
        report["metric_run_id"] = save_results(database, report, source_runs)
    else:
        report["metric_run_id"] = None
    if mode in {"file", "both"}:
        output = output or Path(f"outputs/编排专线地市指标_{normalize_city(city)}_{end_month}.json")
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_file"] = str(output)
    else:
        report["output_file"] = None
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="计算指定地市及区县级编排专线开通指标")
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
    parser.add_argument("--city", required=True, help="地市名称，例如杭州或杭州市")
    parser.add_argument("--start-month", required=True, help="趋势起始月份，YYYY-MM")
    parser.add_argument("--end-month", required=True, help="最新统计月份，YYYY-MM")
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--temp-dir", type=Path)
    args = parser.parse_args()
    report = run(args.database, args.city, args.start_month, args.end_month, mode=args.mode,
                 output=args.output, batch_size=args.batch_size, temp_dir=args.temp_dir)
    print(json.dumps({
        "metric_run_id": report["metric_run_id"],
        "city": report["city"],
        "result_count": len(report["results"]),
        "quality": report["quality"],
        "output_file": report["output_file"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
