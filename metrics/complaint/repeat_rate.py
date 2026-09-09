"""EOMS 专线/专网和千里眼重复投诉率公共计算逻辑。"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from metrics.installation.common import city, identifier, load_dataset, parse_time, period_bounds, result_row, save_metric, text, write_report


@dataclass(frozen=True)
class Profile:
    metric_code: str
    metric_version: str
    name: str
    dispatch_window_hours: int
    numerator_unit: str


LINE = Profile("dedicated_line_repeat_complaint_rate", "1.0.0", "专线/专网重复投诉率", 1, "重复投诉Key")
QLY = Profile("qianliyan_repeat_complaint_rate", "1.0.0", "千里眼重复投诉率", 24, "唯一客户标识")


def category_after_enterprise_market(value: object) -> str:
    parts = [part.strip() for part in text(value).split("->") if part.strip()]
    if "政企市场" in parts:
        parts = parts[parts.index("政企市场") + 1 :]
    return "->".join(parts)


def first_category(value: object) -> str:
    return text(value).split("->", 1)[0].strip()


def customer_id(row: dict[str, object]) -> str:
    return identifier(row.get("计费号码")) or identifier(row.get("手机号码"))


def is_business_row(row: dict[str, object], profile: Profile) -> bool:
    category = text(row.get("业务类别"))
    if profile == LINE:
        return "专线" in category or "专网" in category
    return "千里眼" in category or ("视频监控" in category and "专线专网" not in category)


def numerator_excluded(row: dict[str, object], profile: Profile) -> bool:
    team = text(row.get("最后处理班组"))
    if profile == LINE:
        reason = text(row.get("退单原因"))
        return bool(reason) and "政企头部客户重保组" in team and "售中催单" not in reason
    closer = text(row.get("结单人"))
    return "政企头部客户重保组" in team or "创新院" in team or closer in {"周楷函", "张艺飞"}


def _exclude(row: dict[str, object], reason: str, target: list[dict[str, object]]) -> None:
    row["剔除原因"] = reason
    target.append(row)


def calculate(rows: list[dict[str, object]], start: str, end: str, profile: Profile) -> dict[str, object]:
    start_time, end_time = period_bounds(start, end)
    denominator_rows: list[dict[str, object]] = []
    numerator_candidates: list[dict[str, object]] = []
    excluded_rows: list[dict[str, object]] = []
    numerator_only_excluded: list[dict[str, object]] = []

    for source in rows:
        row = dict(source)
        row["_dataset_code"] = "eoms_complaint"
        assigned = parse_time(row.get("派单时间"))
        if assigned is None or not start_time <= assigned <= end_time:
            _exclude(row, "不在统计周期或派单时间无效", excluded_rows)
            continue
        if not is_business_row(row, profile):
            _exclude(row, "不属于指标业务范围", excluded_rows)
            continue
        if not text(row.get("客服流水号")) or text(row.get("工单状态")) != "正常结束":
            _exclude(row, "非自建口径不满足：客服流水号为空或工单状态非正常结束", excluded_rows)
            continue
        if "重置鉴权码" in text(row.get("工单主题")):
            _exclude(row, "工单主题包含重置鉴权码", excluded_rows)
            continue
        customer = customer_id(row)
        category = category_after_enterprise_market(row.get("业务类别")) if profile == LINE else first_category(row.get("业务类别"))
        if not customer or not category:
            _exclude(row, "客户标识或业务类别为空", excluded_rows)
            continue
        row["_customer"] = customer
        row["_category"] = category
        row["_repeat_key"] = f"{customer}|{category}"
        row["_assigned_time"] = assigned
        row["_city"] = city(row.get("所属地市")) or "（空）"
        denominator_rows.append(row)
        if numerator_excluded(row, profile):
            excluded_copy = dict(row)
            excluded_copy["剔除原因"] = "仅从分子候选剔除"
            numerator_only_excluded.append(excluded_copy)
        else:
            numerator_candidates.append(row)

    removed_dispatch: list[dict[str, object]] = []
    after_dispatch: list[dict[str, object]] = []
    by_key: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in numerator_candidates:
        by_key[row["_repeat_key"]].append(row)
    window = timedelta(hours=profile.dispatch_window_hours)
    for key_rows in by_key.values():
        ordered = sorted(key_rows, key=lambda item: item["_assigned_time"])
        previous_time = None
        for row in ordered:
            if previous_time is not None and row["_assigned_time"] - previous_time <= window:
                removed = dict(row)
                removed["剔除原因"] = f"同一Key相邻派单间隔不超过{profile.dispatch_window_hours}小时"
                removed_dispatch.append(removed)
            else:
                after_dispatch.append(row)
            previous_time = row["_assigned_time"]

    repeat_counts = Counter(row["_repeat_key"] for row in after_dispatch)
    repeat_keys = {key for key, count in repeat_counts.items() if count >= 2}
    numerator_rows = [row for row in after_dispatch if row["_repeat_key"] in repeat_keys]
    denominator_customers = {row["_customer"] for row in denominator_rows}
    numerator = len(repeat_keys) if profile == LINE else len({row["_customer"] for row in numerator_rows})

    results = [result_row(profile.metric_code, "province", {"scope": "全省"}, numerator, len(denominator_customers))]
    cities = sorted({row["_city"] for row in denominator_rows})
    for city_name in cities:
        city_denominator = {row["_customer"] for row in denominator_rows if row["_city"] == city_name}
        city_repeat_rows = [row for row in numerator_rows if row["_city"] == city_name]
        # 专线正式源脚本的全省总计按重复Key计数，产品工作簿的地市行按重复客户去重。
        city_numerator = len({row["_customer"] for row in city_repeat_rows})
        results.append(result_row(profile.metric_code, "city", {"city": city_name}, city_numerator, len(city_denominator)))

    return {
        "metric_code": profile.metric_code,
        "metric_version": profile.metric_version,
        "period_start": start,
        "period_end": end,
        "rules": {
            "name": profile.name,
            "dispatch_window_hours": profile.dispatch_window_hours,
            "numerator_unit": profile.numerator_unit,
            "denominator_unit": "唯一客户标识",
            "customer_id": "计费号码优先，空时使用手机号码",
        },
        "quality": {
            "raw_rows": len(rows),
            "denominator_rows": len(denominator_rows),
            "denominator_customers": len(denominator_customers),
            "numerator_only_excluded_rows": len(numerator_only_excluded),
            "duplicate_dispatch_removed_rows": len(removed_dispatch),
            "repeat_keys": len(repeat_keys),
            "numerator": numerator,
            "excluded_rows": len(excluded_rows),
        },
        "results": results,
        "details": {
            "denominator": denominator_rows,
            "numerator": numerator_rows,
            "excluded": excluded_rows + numerator_only_excluded + removed_dispatch,
        },
    }


def run_metric(profile: Profile, database: Path, start: str, end: str, mode: str, output: Path | None) -> dict[str, object]:
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    database = database.expanduser().resolve()
    rows, source_runs = load_dataset(database, "eoms_complaint")
    if not source_runs:
        raise RuntimeError("数据库中没有EOMS政企投诉工单的成功取数批次")
    report = calculate(rows, start, end, profile)
    report["source_runs"] = source_runs
    report["metric_run_id"] = save_metric(database, report, source_runs, details=report["details"]) if mode in {"database", "both"} else None
    default_output = Path(f"outputs/{profile.name}_{start}_{end}.json")
    report["output_file"] = write_report(report, output or default_output) if mode in {"file", "both"} else None
    return report
