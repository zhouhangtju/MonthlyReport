"""Map already calculated qikuan results to the presentation; no raw-data calculation."""
import hashlib
import json
import math
from pathlib import Path

CITIES = "杭州 湖州 嘉兴 金华 丽水 宁波 衢州 绍兴 台州 温州 舟山".split()
OPENING_KEYS = ("current_month", "previous_month", "current_ytd", "previous_ytd", "yoy", "ytd_yoy")
STOCK_KEYS = ("current", "previous", "year_ago", "yoy", "mom")


def shifted_month(month, offset):
    year, number = map(int, month.split("-"))
    absolute = year * 12 + number - 1 + offset
    year, zero_based = divmod(absolute, 12)
    return f"{year:04d}-{zero_based + 1:02d}"


def trend_months(month):
    return [shifted_month(month, offset) for offset in range(-11, 1)]


def validate_trend(trend, month):
    expected = trend_months(month)
    months = trend.get("months", [])
    values = trend.get("values", [])
    if months != expected or len(values) != 12:
        raise ValueError("企宽开通量近12个月趋势必须连续且截至报告月")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or int(value) != value:
            raise ValueError("企宽开通量趋势必须为12个非负整数")
    total = sum(values)
    average = total / 12
    if trend.get("total") is not None and trend["total"] != total:
        raise ValueError("企宽开通量趋势合计与月度值不一致")
    if trend.get("average") is not None and not math.isclose(trend["average"], average, rel_tol=1e-9):
        raise ValueError("企宽开通量趋势月均与月度值不一致")
    return {"months": months, "values": values, "total": total, "average": average}


def validate_rows(document, keys):
    rows = document["cities"]
    names = [r["city"] for r in rows]
    if len(names) != 11 or set(names) != set(CITIES):
        raise ValueError("企宽结果必须包含且仅包含浙江11地市")
    province = document["province"]
    for row in [province, *rows]:
        for key in keys:
            value = row[key]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError(f"企宽结果 {row['city']}/{key} 不是有效数值")
            if key not in ("yoy", "mom", "ytd_yoy") and value is not None and (value < 0 or int(value) != value):
                raise ValueError(f"企宽结果 {row['city']}/{key} 不是非负整数")
        pairs = (("yoy", "current", "year_ago"), ("mom", "current", "previous")) if keys == STOCK_KEYS else (
            ("yoy", "current_month", "previous_month"), ("ytd_yoy", "current_ytd", "previous_ytd"))
        for rate_key, current_key, base_key in pairs:
            current, base, value = row[current_key], row[base_key], row[rate_key]
            if current is None or base in (None, 0):
                if value is not None:
                    raise ValueError(f"{row['city']}/{rate_key} 基数不可用时应为空")
            elif value is not None and not math.isclose(value, (current - base) / base, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError(f"{row['city']}/{rate_key} 与已存数量不一致")
    for key in keys:
        if key in ("yoy", "mom", "ytd_yoy"):
            continue
        values = [r[key] for r in rows]
        if all(v is not None for v in values):
            if province[key] != sum(values):
                raise ValueError(f"企宽结果 {key} 全省与地市合计不一致")
        elif province[key] is not None or any(v is not None for v in values):
            raise ValueError(f"企宽结果 {key} 地市数据不完整")
    return {"province": province, "cities": sorted(rows, key=lambda r: CITIES.index(r["city"]))}


def read_document(path, month, opening=False):
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8-sig"))
    if opening:
        if document.get("metric_code") != "qikuan_opening_metrics" or document.get("month") != month:
            raise ValueError(f"企宽开通量结果指标或月份不符：{path}")
        keys = OPENING_KEYS
    else:
        if document.get("metric_set") != "qikuan_stock" or document.get("report_month") != month:
            raise ValueError(f"企宽存量结果指标或月份不符：{path}")
        keys = STOCK_KEYS
    result = validate_rows(document, keys)
    if opening:
        result["trend"] = validate_trend(document["trend"], month) if document.get("trend") else {
            "months": trend_months(month), "values": [None] * 12, "total": None, "average": None}
    result["source"] = {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                        "metric_run_id": document.get("metric_run_id"),
                        "sources": document.get("sources", document.get("audit"))}
    return result


def build_qikuan(month, directory, db=None, stock_path=None, opening_path=None):
    """Missing results remain null, including unavailable historical comparisons."""
    missing = []
    def empty(keys):
        return {"province": {"city": "全省", **dict.fromkeys(keys)},
                "cities": [{"city": city, **dict.fromkeys(keys)} for city in CITIES], "source": None}
    if stock_path is None and directory is not None:
        candidates = []
        for path in sorted(Path(directory).glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            if document.get("metric_set") == "qikuan_stock" and document.get("report_month") == month:
                candidates.append(path)
        if len(candidates) > 1:
            raise ValueError("企宽存量有多份结果，请用 --qikuan-stock-json 指定")
        stock_path = candidates[0] if candidates else None
    stock = read_document(Path(stock_path), month) if stock_path else empty(STOCK_KEYS)
    opening = empty(OPENING_KEYS)
    opening["trend"] = {"months": trend_months(month), "values": [None] * 12,
                        "total": None, "average": None}
    if opening_path:
        opening = read_document(Path(opening_path), month, opening=True)
    elif db is not None:
        owner = "qikuan_opening_metrics"
        for record in [opening["province"], *opening["cities"]]:
            city = record["city"]
            kind = "province" if city == "全省" else "city"
            dims = {"month": month, **({"scope": "全省"} if city == "全省" else {"city": city})}
            for key in OPENING_KEYS:
                row = db.find(owner, f"qikuan_opening_{key}", kind, **dims)
                if row:
                    record[key] = row["metric_value"]
        validate_rows(opening, OPENING_KEYS)
        values = []
        for trend_month in opening["trend"]["months"]:
            row = db.find(owner, "qikuan_opening_monthly_trend", "trend_month", month=trend_month)
            values.append(row["metric_value"] if row else None)
        opening["trend"]["values"] = values
        if all(value is not None for value in values):
            opening["trend"]["total"] = sum(values)
            opening["trend"]["average"] = sum(values) / 12
        opening["source"] = db.runs.get(owner)
    for name, data, keys in (("stock", stock, STOCK_KEYS), ("opening", opening, OPENING_KEYS)):
        for row in [data["province"], *data["cities"]]:
            for key in keys:
                if row[key] is None:
                    missing.append({"ppt_field": f"qikuanBusiness.{name}.{row['city']}.{key}",
                                    "reason": "unavailable_stored_result", "filled_value": None})
    for trend_month, value in zip(opening["trend"]["months"], opening["trend"]["values"]):
        if value is None:
            missing.append({"ppt_field": f"qikuanBusiness.opening.trend.{trend_month}",
                            "reason": "unavailable_stored_result", "filled_value": None})
    return {"month": month, "stock": stock, "opening": opening, "missing": missing}
