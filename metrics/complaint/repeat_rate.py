"""EOMS 专线/专网和千里眼重复投诉率公共计算逻辑。"""

from __future__ import annotations

import re
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


LINE = Profile("dedicated_line_repeat_complaint_rate", "1.6.0", "专线/专网重复投诉率", 1, "重复投诉Key")
QLY = Profile("qianliyan_repeat_complaint_rate", "1.0.0", "千里眼重复投诉率", 24, "唯一客户标识")


AREA_NORMALIZE = {
    "金东": "金东区", "婺城": "婺城区", "义乌": "义乌市", "东阳": "东阳市", "永康": "永康市",
    "兰溪": "兰溪市", "浦江": "浦江县", "武义": "武义县", "磐安": "磐安县",
}
CITY_AREAS = {
    "杭州": ["上城区", "拱墅区", "西湖区", "滨江区", "萧山区", "余杭区", "临平区", "钱塘区", "富阳区", "临安区", "桐庐县", "淳安县", "建德市"],
    "宁波": ["海曙区", "江北区", "北仑区", "镇海区", "鄞州区", "奉化区", "余姚市", "慈溪市", "象山县", "宁海县"],
    "温州": ["鹿城区", "龙湾区", "瓯海区", "洞头区", "瑞安市", "乐清市"],
    "嘉兴": ["南湖区", "秀洲区", "嘉善县", "海盐县", "海宁市", "平湖市", "桐乡市"],
    "湖州": ["吴兴区", "南浔区", "德清县", "长兴县", "安吉县"],
    "绍兴": ["越城区", "柯桥区", "上虞区", "新昌县", "诸暨市", "嵊州市"],
    "金华": ["婺城区", "金东区", "义乌市", "东阳市", "永康市", "兰溪市", "浦江县", "武义县", "磐安县"],
    "衢州": ["柯城区", "衢江区", "江山市", "常山县", "开化县", "龙游县"],
    "舟山": ["定海区", "普陀区", "岱山县", "嵊泗县"],
    "台州": ["椒江区", "黄岩区", "路桥区", "临海市", "温岭市", "玉环市", "天台县", "仙居县", "三门县"],
    "丽水": ["莲都区", "龙泉市", "青田县", "缙云县", "遂昌县", "松阳县", "云和县", "庆元县", "景宁畲族自治县", "景宁县"],
}
AREA_TO_CITY = {area: city_name for city_name, areas in CITY_AREAS.items() for area in areas}
AREA_TO_CITY.update({short: AREA_TO_CITY[full] for short, full in {"金东": "金东区", "婺城": "婺城区"}.items()})
AREA_PATTERNS = sorted(AREA_TO_CITY, key=len, reverse=True)


def _extract_area(value: object) -> str:
    raw = text(value)
    if not raw or raw.lower() == "nan":
        return ""
    for expression in (r"【摄像头所属区县】[：:]*\s*([^\n【]+)", r"【摄像头所属地市】[：:]*\s*([^\n【]+)", r"地址[：:]\s*(.*?)(?:[,，;；\n]|$)"):
        match = re.search(expression, raw)
        if match:
            segment = match.group(1).strip()
            for area in AREA_PATTERNS:
                if area in segment:
                    return area
            normalized = AREA_NORMALIZE.get(segment, segment)
            for area in AREA_PATTERNS:
                if area == normalized or normalized in area or area.rstrip("区市县") in normalized:
                    return area
    return ""


def enrich_location(row: dict[str, object]) -> tuple[str, str, bool]:
    """复制 export 千里眼脚本的区县提取和地市反推口径。"""
    original_city = city(row.get("所属地市"))
    area = AREA_NORMALIZE.get(text(row.get("所属区县")), text(row.get("所属区县")))

    # export 会让投诉内容中识别到的摄像头区县覆盖原区县。
    content_area = _extract_area(row.get("投诉内容"))
    if content_area:
        area = content_area
    if not area:
        area = _extract_area(row.get("退单附加说明"))
    if not area:
        topic = text(row.get("工单主题"))
        for candidate in AREA_PATTERNS:
            if candidate in topic:
                area = candidate
                break
        if not area:
            for short, full in AREA_NORMALIZE.items():
                if len(short) >= 2 and short in topic:
                    area = full
                    break
    if not area:
        area = text(row.get("下一环节区县"))
    if not area:
        note = text(row.get("附加说明"))
        for candidate in AREA_PATTERNS:
            if candidate in note:
                area = candidate
                break
    area = AREA_NORMALIZE.get(area, area)

    resolved_city = original_city
    if not resolved_city and area in AREA_TO_CITY:
        resolved_city = AREA_TO_CITY[area]
    if not resolved_city:
        match = re.search(r"【摄像头所属地市】[：:]*\s*([^\n【]+)", text(row.get("投诉内容")))
        if match:
            segment = match.group(1).strip().rstrip("省")
            for city_name in CITY_AREAS:
                if city_name in segment or f"{city_name}市" in segment:
                    resolved_city = city_name
                    break
    return resolved_city, area, bool(not original_city and resolved_city)


def category_after_enterprise_market(value: object) -> str:
    parts = [part.strip() for part in text(value).split("->") if part.strip()]
    if "政企市场" in parts:
        parts = parts[parts.index("政企市场") + 1 :]
    return "->".join(parts)


def first_category(value: object) -> str:
    return text(value).split("->", 1)[0].strip()


def customer_id(row: dict[str, object]) -> str:
    return identifier(row.get("计费号码")) or identifier(row.get("手机号码"))


def extract_e55(value: object) -> str:
    match = re.search(r"e55\d+", text(value), re.IGNORECASE)
    return match.group(0).lower() if match else ""


def line_customer_id(row: dict[str, object]) -> str:
    """与 calc_zhuanxian_repeat_rate.py 一致的专线客户标识补全。"""
    account = text(row.get("计费号码"))
    append_account = extract_e55(row.get("附加报结信息"))
    if append_account:
        account = append_account
    if account in {"", "nan", "None"}:
        for field in ("投诉内容", "jtCalle", "附加说明", "退单附加说明", "附加报结信息", "结单意见", "完成建议", "处理备注", "专线编号"):
            account = extract_e55(row.get(field))
            if account:
                break
    if account in {"", "nan", "None"}:
        account = text(row.get("手机号码"))
    return "" if account in {"", "nan", "None"} else account


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
    location_filled_rows = 0

    for source in rows:
        row = dict(source)
        row["_dataset_code"] = "eoms_complaint"
        resolved_city, resolved_area, city_was_filled = enrich_location(row)
        row["_resolved_city"] = resolved_city
        row["_resolved_area"] = resolved_area
        location_filled_rows += int(city_was_filled)
        assigned = parse_time(row.get("派单时间"))
        if assigned is None or not start_time <= assigned <= end_time:
            _exclude(row, "不在统计周期或派单时间无效", excluded_rows)
            continue
        if not is_business_row(row, profile):
            _exclude(row, "不属于指标业务范围", excluded_rows)
            continue
        if profile == LINE:
            if not text(row.get("客服流水号")) or text(row.get("工单状态")) != "正常结束":
                _exclude(row, "非自建口径不满足：客服流水号为空或工单状态非正常结束", excluded_rows)
                continue
        elif not text(row.get("客服流水号")) or text(row.get("工单状态")) != "正常结束":
            _exclude(row, "非自建口径不满足：客服流水号为空或工单状态非正常结束", excluded_rows)
            continue
        if "重置鉴权码" in text(row.get("工单主题")):
            _exclude(row, "工单主题包含重置鉴权码", excluded_rows)
            continue
        customer = line_customer_id(row) if profile == LINE else customer_id(row)
        category = category_after_enterprise_market(row.get("业务类别")) if profile == LINE else first_category(row.get("业务类别"))
        if not customer or not category:
            _exclude(row, "客户标识或业务类别为空", excluded_rows)
            continue
        row["_customer"] = customer.lower() if profile == LINE else customer
        row["_category"] = category
        row["_repeat_key"] = f"{row['_customer']}|{category}"
        row["_assigned_time"] = assigned
        row["_city"] = resolved_city or "（空）"
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
    denominator_keys = {row["_repeat_key"] for row in denominator_rows}
    numerator = len(repeat_keys) if profile == LINE else len({row["_customer"] for row in numerator_rows})
    denominator = len(denominator_customers)

    results = [result_row(profile.metric_code, "province", {"scope": "全省"}, numerator, denominator)]
    cities = sorted({row["_city"] for row in denominator_rows})
    for city_name in cities:
        city_denominator = {row["_customer"] for row in denominator_rows if row["_city"] == city_name}
        city_repeat_rows = [row for row in numerator_rows if row["_city"] == city_name]
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
            "denominator_keys": len(denominator_keys),
            "numerator_only_excluded_rows": len(numerator_only_excluded),
            "duplicate_dispatch_removed_rows": len(removed_dispatch),
            "repeat_keys": len(repeat_keys),
            "numerator": numerator,
            "excluded_rows": len(excluded_rows),
            "location_filled_rows": location_filled_rows,
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
    database = database.expanduser().resolve() if database is not None else None
    rows, source_runs = load_dataset(database, "eoms_complaint")
    if not source_runs:
        raise RuntimeError("数据库中没有EOMS政企投诉工单的成功取数批次")
    report = calculate(rows, start, end, profile)
    report["source_runs"] = source_runs
    report["metric_run_id"] = save_metric(database, report, source_runs, details=report["details"]) if mode in {"database", "both"} else None
    default_output = Path(f"outputs/{profile.name}_{start}_{end}.json")
    report["output_file"] = write_report(report, output or default_output) if mode in {"file", "both"} else None
    return report
