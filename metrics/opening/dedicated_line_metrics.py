"""从数据库计算编排专线开通量、产品分布及自动率指标。"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
import uuid
from collections import defaultdict
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


def log(message: str) -> None:
    print(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] {message}",
        flush=True,
    )


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


def load_rows(
    database: Path,
    first_month: str | None = None,
    last_month: str | None = None,
) -> tuple[list[dict[str, object]], list[str]]:
    log(f"正在初始化数据库：{database}")
    initialize(database)
    where = ""
    parameters: tuple[str, ...] = ()
    if first_month and last_month:
        where = " WHERE order_finished_at >= ? AND order_finished_at < ?"
        parameters = (f"{first_month}-01", f"{shift_month(last_month, 1)}-01")
    log(
        "正在读取 ods_orch_opening"
        + (f"（结束时间 {first_month} 至 {last_month}）" if where else "")
    )
    with connect(database) as connection:
        cursor = connection.execute(
            "SELECT order_no, source_data FROM ods_orch_opening" + where,
            parameters,
        )
        rows: list[dict[str, object]] = []
        while True:
            records = cursor.fetchmany(5000)
            if not records:
                break
            for record in records:
                row = json.loads(record["source_data"])
                row["_source_record_id"] = record["order_no"]
                rows.append(row)
            if len(rows) % 50000 == 0:
                log(f"已读取并解析 {len(rows)} 条…")
        runs = connection.execute(
            """SELECT run_id FROM etl_run
               WHERE dataset_code=? AND status='success' ORDER BY started_at""",
            (DATASET_CODE,),
        ).fetchall()
    log(f"数据读取完成，共 {len(rows)} 条")
    return rows, [row["run_id"] for row in runs]


def load_monthly_summaries(
    database: Path,
    first_month: str,
    last_month: str,
) -> list[dict[str, object]]:
    """读取可替代已清理订单明细的基础月度指标。"""
    initialize(database)
    with connect(database) as connection:
        records = connection.execute(
            """SELECT metric_code, dimension_type, dimension_value,
                      numerator, denominator, metric_value
               FROM orch_opening_monthly_summary
               WHERE metric_version=? AND month>=? AND month<=?""",
            (METRIC_VERSION, first_month, last_month),
        ).fetchall()
    return [
        {
            "metric_code": row["metric_code"],
            "dimension_type": row["dimension_type"],
            "dimension": json.loads(row["dimension_value"]),
            "numerator": row["numerator"],
            "denominator": row["denominator"],
            "metric_value": row["metric_value"],
        }
        for row in records
    ]


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


def build_index(
    rows: Iterable[dict[str, object]],
) -> tuple[dict[tuple[str, str, str], list[dict[str, object]]], int]:
    """一次遍历完成归月、筛选和订单号去重。"""
    grouped: dict[tuple[str, str, str], dict[str, dict[str, object]]] = defaultdict(dict)
    missing_month = 0
    empty_sequence = 0
    for row in rows:
        month = row_month(row)
        if month is None:
            missing_month += 1
            continue
        if text(row.get("订单状态")) != STATUS:
            continue
        order_no = text(row.get("订单号"))
        if not order_no:
            empty_sequence += 1
            order_no = f"__empty_order_{empty_sequence}"
        key = (
            month,
            text(row.get("业务类型")),
            text(row.get("订单类型")),
        )
        grouped[key][order_no] = row
    return {key: list(value.values()) for key, value in grouped.items()}, missing_month


def group_rows(
    index: dict[tuple[str, str, str], list[dict[str, object]]],
    month: str,
    business_type: str,
    order_type: str = "开通",
) -> list[dict[str, object]]:
    return index.get((month, business_type, order_type), [])


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


def volume_results(
    index: dict[tuple[str, str, str], list[dict[str, object]]],
    months: list[str],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for month in months:
        for business_type, products, code in [
            (BUSINESS_TYPE, None, "internet_opening_orders"),
            (MPLS_BUSINESS_TYPE, MPLS_PRODUCTS, "mpls_opening_orders"),
            (TRANSMISSION_BUSINESS_TYPE, TRANSMISSION_PRODUCTS, "transmission_opening_orders"),
        ]:
            source = group_rows(index, month, business_type)
            if products is not None:
                source = [row for row in source if text(row.get("产品名称")) in products]
            output.append(result(code, "month", {"month": month}, order_count(source)))
            for product in products or (ALL_PRODUCTS if business_type == BUSINESS_TYPE else []):
                count = order_count(row for row in source if text(row.get("产品名称")) == product)
                output.append(result(code, "month_product", {"month": month, "product": product}, count))
    return output


def current_distribution(
    index: dict[tuple[str, str, str], list[dict[str, object]]],
    month: str,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for business_type, products, code in [
        (BUSINESS_TYPE, ALL_PRODUCTS, "internet_opening_orders"),
        (MPLS_BUSINESS_TYPE, MPLS_PRODUCTS, "mpls_opening_orders"),
        (TRANSMISSION_BUSINESS_TYPE, TRANSMISSION_PRODUCTS, "transmission_opening_orders"),
    ]:
        source = group_rows(index, month, business_type)
        source = [row for row in source if text(row.get("产品名称")) in products]
        for city in CITY_ORDER:
            for product in products:
                count = sum(
                    1 for row in source
                    if text(row.get("地市")) == city
                    and text(row.get("产品名称")) == product
                )
                output.append(result(code, "month_city_product", {"month": month, "city": city, "product": product}, count))
            city_total = sum(1 for row in source if text(row.get("地市")) == city)
            output.append(result(code, "month_city", {"month": month, "city": city}, city_total))
    return output


def automation_results(
    index: dict[tuple[str, str, str], list[dict[str, object]]],
    month: str,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for order_type, stages, prefix in [
        ("开通", OPENING_STAGES, "internet_opening_automation_rate"),
        ("变更", OPENING_STAGES, "internet_move_automation_rate"),
        ("拆除", REMOVAL_STAGES, "internet_removal_automation_rate"),
    ]:
        source = group_rows(index, month, BUSINESS_TYPE, order_type)
        denominator = len(source)
        automatic_total = 0
        for stage, field, automatic_value in stages:
            numerator = sum(1 for row in source if text(row.get(field)) == automatic_value)
            automatic_total += numerator
            output.append(result(prefix, "month_stage", {"month": month, "stage": stage, "field": field, "automatic_value": automatic_value}, numerator, denominator))
        output.append(result(prefix, "month_all_stages", {"month": month, "stage": f"{len(stages)}环节整体"}, automatic_total, denominator * len(stages)))
        if order_type in {"变更", "拆除"}:
            city_code = "internet_move_activation_rate" if order_type == "变更" else "internet_removal_activation_rate"
            for city in CITY_ORDER:
                city_rows = [row for row in source if text(row.get("地市")) == city]
                city_total = len(city_rows)
                city_auto = sum(1 for row in city_rows if text(row.get("配置激活处理人")) == "系统自动")
                output.append(result(city_code, "month_city", {"month": month, "city": city}, city_auto, city_total))
            province_auto = sum(1 for row in source if text(row.get("配置激活处理人")) == "系统自动")
            output.append(result(city_code, "month_city", {"month": month, "city": "全省合计"}, province_auto, denominator))
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
    for source_code, result_code, products in [
        ("internet_opening_orders", "internet_product_opening_yoy", KEY_PRODUCTS),
        ("mpls_opening_orders", "mpls_product_opening_yoy", MPLS_PRODUCTS),
        ("transmission_opening_orders", "transmission_product_opening_yoy", TRANSMISSION_PRODUCTS),
    ]:
        for product in products:
            current_key = json.dumps({"month": current, "product": product}, ensure_ascii=False, sort_keys=True)
            last_key = json.dumps({"month": last_year, "product": product}, ensure_ascii=False, sort_keys=True)
            current_value = int((lookup.get((source_code, current_key)) or {"numerator": 0})["numerator"])
            last_value = int((lookup.get((source_code, last_key)) or {"numerator": 0})["numerator"])
            output.append(result(result_code, "month_product_comparison", {"month": current, "comparison_month": last_year, "product": product}, current_value - last_value, last_value))
    return output


def _result_key(item: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(item["metric_code"]),
        str(item["dimension_type"]),
        json.dumps(item["dimension"], ensure_ascii=False, sort_keys=True),
    )


def calculate(
    rows: list[dict[str, object]],
    start_month: str,
    end_month: str,
    monthly_summaries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    trend_months = month_range(start_month, end_month)
    required = sorted(set(trend_months + [shift_month(end_month, -1), shift_month(end_month, -12)] + [shift_month(end_month, offset) for offset in range(-11, 1)]))
    index, missing_month_rows = build_index(rows)
    volumes = volume_results(index, required)
    base_results = volumes + current_distribution(index, end_month) + automation_results(index, end_month)
    for month in [shift_month(end_month, offset) for offset in range(-11, 1)]:
        source = group_rows(index, month, BUSINESS_TYPE)
        count = len(source) - sum(1 for row in source if text(row.get("产品名称")) == "悦享专线动态IP版") - sum(1 for row in source if text(row.get("产品名称")) == "互联网专线套餐")
        base_results.append(result("other_internet_opening_orders", "month", {"month": month}, count))

    # 有订单明细的月份以明细重算为准；没有明细的月份由永久月度快照补齐。
    detail_months = {month for row in rows if (month := row_month(row)) is not None}
    merged = {_result_key(item): item for item in base_results}
    for item in monthly_summaries or []:
        month = item.get("dimension", {}).get("month")
        if month and month not in detail_months:
            merged[_result_key(item)] = item
    base_results = list(merged.values())

    merged_volumes = [
        item for item in base_results
        if item["metric_code"] in {
            "internet_opening_orders", "mpls_opening_orders", "transmission_opening_orders"
        }
        and item["dimension_type"] in {"month", "month_product"}
    ]
    results = base_results + comparison_results(merged_volumes, end_month)
    rolling_months = {shift_month(end_month, offset) for offset in range(-11, 1)}
    other_total = sum(
        int(item["numerator"])
        for item in base_results
        if item["metric_code"] == "other_internet_opening_orders"
        and item["dimension_type"] == "month"
        and item["dimension"].get("month") in rolling_months
    )
    results.append(result("other_internet_average_monthly_orders", "rolling_12_months", {"end_month": end_month}, other_total, 12))
    for product in KEY_PRODUCTS[:2]:
        product_total = sum(
            int(item["numerator"])
            for item in base_results
            if item["metric_code"] == "internet_opening_orders"
            and item["dimension_type"] == "month_product"
            and item["dimension"].get("month") in rolling_months
            and item["dimension"].get("product") == product
        )
        results.append(result(
            "internet_product_average_monthly_orders",
            "rolling_12_months",
            {"end_month": end_month, "product": product},
            product_total,
            12,
        ))

    return {
        "metric_code": METRIC_CODE,
        "metric_version": METRIC_VERSION,
        "start_month": start_month,
        "end_month": end_month,
        "quality": {
            "database_rows": len(rows),
            "snapshot_database_rows": sum(1 for row in rows if row_month(row) == end_month),
            "rows_missing_order_month": missing_month_rows,
            "detail_months": sorted(detail_months),
        },
        "results": results,
    }


def print_report(report: dict[str, object]) -> None:
    """按《专线产品情况》的子 Sheet 顺序打印指标日志。"""
    current = str(report["end_month"])
    previous = shift_month(current, -1)
    last_year = shift_month(current, -12)
    rows = list(report["results"])

    def matching(code: str, dimension_type: str | None = None) -> list[dict[str, object]]:
        return [
            item for item in rows
            if item["metric_code"] == code
            and (dimension_type is None or item["dimension_type"] == dimension_type)
        ]

    def find(
        code: str,
        dimension_type: str | None = None,
        **dimension: str,
    ) -> dict[str, object] | None:
        return next(
            (
                item for item in rows
                if item["metric_code"] == code
                and (dimension_type is None or item["dimension_type"] == dimension_type)
                and all(item["dimension"].get(key) == value for key, value in dimension.items())
            ),
            None,
        )

    def number(item: dict[str, object] | None) -> int:
        return int(item["numerator"]) if item else 0

    def rate(item: dict[str, object] | None) -> str:
        value = None if item is None else item["metric_value"]
        return "无法计算" if value is None else f"{float(value):.2%}"

    log("[Sheet 1/18] 互联网指标汇总")
    for month in (last_year, previous, current):
        log(f"  {month}：{number(find('internet_opening_orders', month=month))} 单")
    log(f"  同比：{rate(find('internet_opening_orders_yoy'))}；环比：{rate(find('internet_opening_orders_mom'))}")

    log("[Sheet 2/18] 互联网重点产品同比")
    for product in KEY_PRODUCTS:
        item = find("internet_product_opening_yoy", product=product)
        baseline = int(item["denominator"]) if item else 0
        delta = number(item)
        log(f"  {product}：{last_year} {baseline} 单，{current} {baseline + delta} 单，增减 {delta} 单，同比 {rate(item)}")

    log(f"[Sheet 3/18] 互联网全省{current}产品")
    province_product_total = 0
    for product in ALL_PRODUCTS:
        count = number(find("internet_opening_orders", month=current, product=product))
        province_product_total += count
        log(f"  {product}：{count} 单")
    log(f"  合计：{province_product_total} 单")

    log(f"[Sheet 4/18] 互联网11地市{current}产品")
    for city in CITY_ORDER:
        values = [
            f"{product}={number(find('internet_opening_orders', 'month_city_product', month=current, city=city, product=product))}"
            for product in ALL_PRODUCTS
        ]
        total = number(find("internet_opening_orders", "month_city", month=current, city=city))
        log(f"  {city}：{'，'.join(values)}，合计={total}")

    log("[Sheet 5/18] 互联网月度分布")
    for month in month_range(str(report["start_month"]), current):
        enjoy = number(find("internet_opening_orders", month=month, product="悦享专线动态IP版"))
        package = number(find("internet_opening_orders", month=month, product="互联网专线套餐"))
        log(f"  {month}：悦享 {enjoy} 单，互联网套餐 {package} 单")

    average = next(iter(matching("other_internet_average_monthly_orders")), None)
    log("[Sheet 6/18] 互联网其他专线12月汇总")
    if average:
        log(f"  累计 {int(average['numerator'])} 单，平均每月 {float(average['metric_value']):.2f} 单")
    log("[Sheet 7/18] 互联网其他专线12月明细")
    for item in matching("other_internet_opening_orders", "month"):
        month = item["dimension"]["month"]
        values = [
            f"{product}={number(find('internet_opening_orders', month=month, product=product))}"
            for product in OTHER_PRODUCTS
        ]
        log(f"  {month}：{'，'.join(values)}，其他互联网专线合计={int(item['numerator'])}")

    for sheet_no, label, code, products, comparison_code in [
        (8, "MPLS-VPN", "mpls_opening_orders", MPLS_PRODUCTS, "mpls_product_opening_yoy"),
        (11, "传输专线", "transmission_opening_orders", TRANSMISSION_PRODUCTS, "transmission_product_opening_yoy"),
    ]:
        log(f"[Sheet {sheet_no}/18] {label}指标汇总")
        total_yoy = find(f"{code}_yoy")
        total_baseline = int(total_yoy["denominator"]) if total_yoy else 0
        total_delta = number(total_yoy)
        log(f"  合计：{last_year} {total_baseline} 单，{current} {total_baseline + total_delta} 单，增减 {total_delta} 单，同比 {rate(total_yoy)}")
        for product in products:
            item = find(comparison_code, product=product)
            baseline = int(item["denominator"]) if item else 0
            delta = number(item)
            log(f"  {product}：{last_year} {baseline} 单，{current} {baseline + delta} 单，增减 {delta} 单，同比 {rate(item)}")
        log(f"[Sheet {sheet_no + 1}/18] {label}{current}地市")
        for city in CITY_ORDER:
            values = [
                f"{product}={number(find(code, 'month_city_product', month=current, city=city, product=product))}"
                for product in products
            ]
            total = number(find(code, "month_city", month=current, city=city))
            log(f"  {city}：{'，'.join(values)}，合计={total}")
        log(f"[Sheet {sheet_no + 2}/18] {label}月度分布")
        for month in month_range(str(report["start_month"]), current):
            values = [
                f"{product}={number(find(code, month=month, product=product))}"
                for product in products
            ]
            log(f"  {month}：{'，'.join(values)}，合计={number(find(code, month=month))}")

    def print_automation(sheet_no: int, label: str, code: str) -> None:
        log(f"[Sheet {sheet_no}/18] {label}_{current}")
        for item in matching(code):
            log(
                f"  {item['dimension']['stage']}：{int(item['numerator'])}/"
                f"{int(item['denominator'])}，{rate(item)}"
            )

    def print_city_automation(sheet_no: int, label: str, code: str) -> None:
        log(f"[Sheet {sheet_no}/18] {label}_{current}")
        for city in [*CITY_ORDER, "全省合计"]:
            item = find(code, city=city)
            log(f"  {city}：{number(item)}/{int(item['denominator']) if item else 0}，{rate(item)}")

    print_automation(14, "互联网专线开通自动率", "internet_opening_automation_rate")
    print_automation(15, "互联网专线移机自动率", "internet_move_automation_rate")
    print_city_automation(16, "互联网专线移机地市自动率", "internet_move_activation_rate")
    print_automation(17, "互联网专线拆机自动率", "internet_removal_automation_rate")
    print_city_automation(18, "互联网专线拆机地市自动率", "internet_removal_activation_rate")


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
            connection.executemany(
                """INSERT INTO ads_metric_result (
                   metric_run_id, metric_code, dimension_type, dimension_value,
                   numerator, denominator, metric_value
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        run_id, item["metric_code"], item["dimension_type"],
                        json.dumps(item["dimension"], ensure_ascii=False, sort_keys=True),
                        item["numerator"], item["denominator"], item["metric_value"],
                    )
                    for item in report["results"]
                ],
            )
            snapshot_month = str(report["end_month"])
            snapshot_rows = [
                item for item in report["results"]
                if item.get("dimension", {}).get("month") == snapshot_month
                and not str(item["metric_code"]).endswith(("_mom", "_yoy"))
                and item["dimension_type"] != "month_comparison"
            ]
            has_snapshot_detail = snapshot_month in report["quality"].get("detail_months", [])
            connection.executemany(
                """INSERT INTO orch_opening_monthly_summary (
                       month, metric_version, metric_code, dimension_type,
                       dimension_value, numerator, denominator, metric_value,
                       source_metric_run_id, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(month, metric_version, metric_code, dimension_type, dimension_value)
                   DO UPDATE SET numerator=excluded.numerator,
                       denominator=excluded.denominator, metric_value=excluded.metric_value,
                       source_metric_run_id=excluded.source_metric_run_id,
                       updated_at=excluded.updated_at""",
                [
                    (
                        snapshot_month, METRIC_VERSION, item["metric_code"],
                        item["dimension_type"],
                        json.dumps(item["dimension"], ensure_ascii=False, sort_keys=True),
                        item["numerator"], item["denominator"], item["metric_value"],
                        run_id, now,
                    )
                    for item in snapshot_rows if has_snapshot_detail
                ],
            )
            quality = report["quality"]
            if has_snapshot_detail:
                connection.execute(
                """INSERT INTO orch_opening_monthly_quality (
                       month, metric_version, database_rows, rows_missing_order_month,
                       source_metric_run_id, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(month, metric_version) DO UPDATE SET
                       database_rows=excluded.database_rows,
                       rows_missing_order_month=excluded.rows_missing_order_month,
                       source_metric_run_id=excluded.source_metric_run_id,
                       updated_at=excluded.updated_at""",
                    (
                        snapshot_month, METRIC_VERSION, quality["snapshot_database_rows"],
                        quality["rows_missing_order_month"], run_id, now,
                    ),
                )
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


def run(database: Path, start_month: str, end_month: str, *, mode: str = "both", output: Path | None = None) -> dict[str, object]:
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    database = database.expanduser().resolve()
    trend_months = month_range(start_month, end_month)
    required_months = sorted(set(
        trend_months
        + [shift_month(end_month, -1), shift_month(end_month, -12)]
        + [shift_month(end_month, offset) for offset in range(-11, 1)]
    ))
    rows, source_runs = load_rows(database, required_months[0], required_months[-1])
    summaries = load_monthly_summaries(database, required_months[0], required_months[-1])
    if not source_runs and not summaries:
        raise RuntimeError("数据库中没有编排专线开通情况的成功取数批次或月度汇总")
    log("正在单次遍历建立指标分组并计算…")
    report = calculate(rows, start_month, end_month, summaries)
    log(f"指标计算完成，共 {len(report['results'])} 条结果")
    print_report(report)
    report["source_runs"] = source_runs
    if mode in {"database", "both"}:
        log("正在批量写入 metric_run 和 ads_metric_result…")
        report["metric_run_id"] = save_results(database, report, source_runs)
        log(f"指标入库完成：{report['metric_run_id']}")
    else:
        report["metric_run_id"] = None
    if mode in {"file", "both"}:
        output = (output or Path(f"outputs/编排专线指标_{end_month}.json")).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["output_file"] = str(output)
        log(f"JSON 输出完成：{output}")
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
