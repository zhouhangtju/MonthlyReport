"""将地市及区县级编排指标映射为6页业务发展PPT的数据模型。"""

from __future__ import annotations

import calendar
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from storage.database import _database_name, connect


OWNER = "orchestration_opening_metrics_by_city"
PRODUCTS = [
    "悦享专线动态IP版", "互联网专线套餐", "商务专线套餐（2020版）",
    "直播专线", "网吧专线套餐（2019版）", "高品质互联网专线",
]
PRODUCT_LABELS = [
    "悦享专线\n动态IP版", "互联网\n专线套餐", "商务专线套餐\n（2020版）",
    "直播专线", "网吧专线套餐\n（2019版）", "高品质\n互联网专线",
]
MPLS_PRODUCTS = ["地区内MPLSVPN套餐", "省内MPLSVPN套餐"]
TRANSMISSION_PRODUCTS = [
    "光纤出租套餐", "地区内数字电路出租套餐", "地区间精品电路",
    "地区内SPN电路出租", "地区间数字电路出租套餐", "地区内精品电路",
]


def month_bounds(month: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("月份格式应为 YYYY-MM")
    year, number = map(int, month.split("-"))
    return f"{month}-01", f"{month}-{calendar.monthrange(year, number)[1]:02d}"


def shifted(month: str, offset: int) -> str:
    year, number = map(int, month.split("-"))
    year, number = divmod(year * 12 + number - 1 + offset, 12)
    return f"{year:04d}-{number + 1:02d}"


def short_month(month: str) -> str:
    return month[2:].replace("-", ".")


def normalize_city(city: str) -> str:
    city = str(city).strip()
    return city if city.endswith("市") else f"{city}市"


class CityResults:
    def __init__(self, database: Path | None, month: str, city: str):
        self.month = month
        self.city = normalize_city(city)
        self.start, self.end = month_bounds(month)
        self.database = _database_name()
        self.missing: dict[str, dict] = {}
        self.nulls: dict[str, dict] = {}
        self.used: dict[str, dict] = {}
        with connect(database) as connection:
            runs = connection.execute(
                """SELECT * FROM metric_run
                   WHERE metric_code=? AND status='success' AND period_end=?
                   ORDER BY started_at DESC, metric_run_id DESC""",
                (OWNER, self.end),
            ).fetchall()
            selected = None
            selected_rows = []
            for run in runs:
                rows = connection.execute(
                    """SELECT result_id,metric_run_id,metric_code,dimension_type,
                              dimension_value,numerator,denominator,metric_value
                       FROM result_orchestration_opening
                       WHERE metric_run_id=? ORDER BY result_id""",
                    (run["metric_run_id"],),
                ).fetchall()
                parsed = [dict(row, dimension=json.loads(row["dimension_value"])) for row in rows]
                if any(normalize_city(row["dimension"].get("city", "")) == self.city for row in parsed):
                    selected, selected_rows = dict(run), parsed
                    break
            if selected is None:
                raise RuntimeError(f"没有找到 {self.city} {month} 的成功地市指标批次")
            self.run = selected
            self.rows = selected_rows

    def find(self, code: str, kind: str, **dimension: str):
        matches = []
        for row in self.rows:
            if row["metric_code"] != code or row["dimension_type"] != kind:
                continue
            actual_dimension = row["dimension"]
            if all(
                normalize_city(actual_dimension.get(key, "")) == normalize_city(value)
                if key == "city" else actual_dimension.get(key) == value
                for key, value in dimension.items()
            ):
                matches.append(row)
        if len(matches) > 1:
            raise ValueError(f"指标维度不唯一：{code}/{kind}/{dimension}")
        return matches[0] if matches else None

    def value(self, code: str, kind: str, field: str = "metric_value", **dimension: str):
        row = self.find(code, kind, **dimension)
        spec = {"metric_code": code, "dimension_type": kind, "dimension": dimension, "field": field}
        key = json.dumps(spec, ensure_ascii=False, sort_keys=True)
        value = row[field] if row else None
        if row is None:
            self.missing[key] = dict(spec, reason="missing_result")
            return 0
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            self.nulls[key] = dict(spec, reason="null_or_nonfinite_value", filled_value=0)
            return 0
        self.used[key] = dict(spec, metric_run_id=row["metric_run_id"], result_id=row["result_id"], value=value)
        return value


def build_data(database: Path | None, month: str, city: str) -> dict:
    db = CityResults(database, month, city)
    city = db.city
    months = [shifted(month, offset) for offset in range(-11, 1)]
    year, month_number = map(int, month.split("-"))

    def count(code: str, kind: str, **dims):
        return db.value(code, kind, "metric_value", **dims)

    def numerator(code: str, kind: str, **dims):
        return db.value(code, kind, "numerator", **dims)

    def county_names(code: str) -> list[str]:
        names = {
            row["dimension"].get("county") for row in db.rows
            if row["metric_code"] == code
            and row["dimension_type"] == "month_city_county"
            and row["dimension"].get("month") == month
            and normalize_city(row["dimension"].get("city", "")) == city
        }
        names.discard(None)
        return sorted(names, key=lambda name: (name == "未归属区县", name))

    def line_group(prefix: str, products: list[str]) -> dict:
        code = f"{prefix}_opening_orders"
        counties = county_names(code)
        return {
            "currentTotal": count(code, "month_city", month=month, city=city),
            "totalYoy": count(f"{code}_yoy", "month_city_comparison", month=month, city=city),
            "products": [
                {
                    "name": product,
                    "value": count(code, "month_city_product", month=month, city=city, product=product),
                    "yoy": count(f"{prefix}_product_opening_yoy", "month_city_product_comparison",
                                 month=month, city=city, product=product),
                    "increase": numerator(f"{prefix}_product_opening_yoy", "month_city_product_comparison",
                                          month=month, city=city, product=product),
                }
                for product in products
            ],
            "counties": counties,
            "countySeries": [
                {
                    "name": product,
                    "values": [count(code, "month_city_county_product", month=month, city=city,
                                     county=county, product=product) for county in counties],
                }
                for product in products
            ],
            "months": [short_month(value) for value in months],
            "periodShort": f"{short_month(months[0])}–{short_month(month)}",
            "trend": [count(code, "month_city", month=value, city=city) for value in months],
        }

    internet_counties = county_names("internet_opening_orders")
    product_trends = {
        product: [count("internet_opening_orders", "month_city_product", month=value,
                        city=city, product=product) for value in months]
        for product in PRODUCTS
    }
    other_trend = [sum(product_trends[p][index] for p in PRODUCTS[2:]) for index in range(12)]
    trend_summary = {
        product: {
            "sum": numerator("internet_product_average_monthly_orders", "rolling_12_months_city_product",
                             end_month=month, city=city, product=product),
            "average": count("internet_product_average_monthly_orders", "rolling_12_months_city_product",
                             end_month=month, city=city, product=product),
        }
        for product in PRODUCTS[:2]
    }
    other_summary = {
        "sum": numerator("other_internet_average_monthly_orders", "rolling_12_months_city",
                         end_month=month, city=city),
        "average": count("other_internet_average_monthly_orders", "rolling_12_months_city",
                         end_month=month, city=city),
    }
    data = {
        "sourceFileName": db.database,
        "city": city,
        "cityShort": city.removesuffix("市"),
        "currentMonth": month,
        "displayMonth": f"{month_number}月",
        "displayMonthFull": f"{year}年{month_number}月",
        "currentTotal": count("internet_opening_orders", "month_city", month=month, city=city),
        "yoy": count("internet_opening_orders_yoy", "month_city_comparison", month=month, city=city),
        "mom": count("internet_opening_orders_mom", "month_city_comparison", month=month, city=city),
        "keyProducts": {p: count("internet_opening_orders", "month_city_product", month=month,
                                 city=city, product=p) for p in PRODUCTS[:3]},
        "keyProductYoy": {p: count("internet_product_opening_yoy", "month_city_product_comparison",
                                   month=month, city=city, product=p) for p in PRODUCTS[:3]},
        "cityProducts": [
            {"name": p, "label": label,
             "value": count("internet_opening_orders", "month_city_product", month=month, city=city, product=p)}
            for p, label in zip(PRODUCTS, PRODUCT_LABELS)
        ],
        "counties": internet_counties,
        "countySeries": [
            {"name": label.replace("\n", ""),
             "values": [count("internet_opening_orders", "month_city_county_product", month=month,
                              city=city, county=county, product=p) for county in internet_counties]}
            for p, label in zip(PRODUCTS, PRODUCT_LABELS)
        ],
        "months": [short_month(value) for value in months],
        "trendPeriodText": f"{months[0]}–{month}",
        "trendPeriodShort": f"{short_month(months[0])}–{short_month(month)}",
        "trendSeries": [{"name": p, "values": product_trends[p]} for p in PRODUCTS[:2]],
        "packageTrend": {"name": PRODUCTS[1], "values": product_trends[PRODUCTS[1]]},
        "otherTrend": {"name": "互联网专线其他产品", "values": other_trend},
        "trendSummary": trend_summary,
        "otherTrendSummary": other_summary,
        "mpls": line_group("mpls", MPLS_PRODUCTS),
        "transmission": line_group("transmission", TRANSMISSION_PRODUCTS),
    }
    data["dataAudit"] = {
        "database": db.database,
        "period_start": db.run["period_start"],
        "period_end": db.run["period_end"],
        "city": city,
        "selected_batch": db.run,
        "used_results": list(db.used.values()),
        "missing": list(db.missing.values()),
        "null_values": list(db.nulls.values()),
        "policy": "只读取成功的地市指标批次；区县使用区县名称；缺失指标不在绘图层重算。",
    }
    return data
