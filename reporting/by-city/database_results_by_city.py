"""将地市及区县级编排指标映射为业务发展和专线自动情况PPT数据模型。"""

from __future__ import annotations

import calendar
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from storage.database import _database_name, connect
from reporting.database_results import CITIES, DEVICES, BUSINESSES
from config.report_periods import integration_opening_period


OWNER = "orchestration_opening_metrics_by_city"
AUTOMATION_OWNER = "orchestration_automation_metrics_by_city"
SUPPORT_OWNER = "business_support_withdrawal_by_city"
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
    def __init__(self, database: Path | None, month: str, city: str, owner: str = OWNER):
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
                (owner, self.end),
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


class TerminalResults:
    def __init__(self, database: Path | None, month: str, city: str):
        self.start, self.end = month_bounds(month)
        self.city = normalize_city(city)
        self.database = _database_name()
        self.missing: dict[str, dict] = {}
        self.used: dict[str, dict] = {}
        with connect(database) as connection:
            runs = connection.execute(
                """SELECT * FROM metric_run WHERE metric_code='terminal_recovery_metrics_by_city'
                   AND status='success' AND period_start=? AND period_end=?
                   ORDER BY started_at DESC, metric_run_id DESC""",
                (self.start, self.end),
            ).fetchall()
            selected = None
            selected_rows = []
            city_short = self.city.removesuffix("市")
            for run in runs:
                rows = connection.execute(
                    """SELECT result_id,metric_run_id,metric_code,dimension_type,
                              dimension_value,numerator,denominator,metric_value
                       FROM result_terminal_recovery WHERE metric_run_id=? ORDER BY result_id""",
                    (run["metric_run_id"],),
                ).fetchall()
                parsed = [dict(row, dimension=json.loads(row["dimension_value"])) for row in rows]
                if any(row["dimension_type"] in {"district_summary", "city_business"}
                       and str(row["dimension"].get("label") or "").startswith(city_short + "·")
                       for row in parsed):
                    selected, selected_rows = dict(run), parsed
                    break
            if selected is None:
                raise RuntimeError(f"没有找到 {self.city} {month} 的成功地市终端回收指标批次")
            self.run = selected
            self.rows = selected_rows

    def value(self, kind: str, label: str, column: str):
        def same(actual, expected):
            return actual == expected or (isinstance(actual, str) and isinstance(expected, str)
                                          and actual.removesuffix("市") == expected.removesuffix("市"))
        matches = [row for row in self.rows if row["dimension_type"] == kind
                   and same(row["dimension"].get("label"), label)
                   and same(row["dimension"].get("column"), column)]
        spec = {"dimension_type": kind, "label": label, "column": column}
        key = json.dumps(spec, ensure_ascii=False, sort_keys=True)
        if len(matches) > 1:
            raise ValueError(f"终端回收指标维度不唯一：{spec}")
        if not matches:
            self.missing[key] = dict(spec, reason="missing_result")
            return 0
        value = matches[0]["metric_value"]
        self.used[key] = dict(spec, metric_run_id=matches[0]["metric_run_id"],
                              result_id=matches[0]["result_id"], value=value)
        return value or 0


class SupportResults:
    def __init__(self, database: Path | None, month: str, city: str):
        self.city = normalize_city(city)
        self.month = month
        self.used: list[dict] = []
        start, end = integration_opening_period(month)
        with connect(database) as connection:
            runs = connection.execute(
                """SELECT * FROM metric_run WHERE metric_code=? AND status='success'
                   AND period_start=? AND period_end=?
                   ORDER BY started_at DESC, metric_run_id DESC""",
                (SUPPORT_OWNER, start, end),
            ).fetchall()
            for run in runs:
                stored = connection.execute(
                    """SELECT result_id,metric_run_id,metric_code,dimension_type,
                              dimension_value,numerator,denominator,metric_value
                       FROM result_opening_withdrawal WHERE metric_run_id=?""",
                    (run["metric_run_id"],),
                ).fetchall()
                rows = [dict(row, dimension=json.loads(row["dimension_value"])) for row in stored]
                if any(row["dimension_type"] == "city" and
                       normalize_city(row["dimension"].get("city", "")) == self.city for row in rows):
                    self.run = dict(run)
                    self.rows = rows
                    break
            else:
                raise RuntimeError(f"没有找到 {self.city} {month} 的集团撤退单地市指标批次")

    def value(self, code: str, county: str | None = None, field: str = "metric_value"):
        kind = "city_county" if county is not None else "city"
        matches = [row for row in self.rows if row["metric_code"] == code
                   and row["dimension_type"] == kind
                   and normalize_city(row["dimension"].get("city", "")) == self.city
                   and (county is None or row["dimension"].get("county") == county)]
        if len(matches) != 1:
            raise ValueError(f"集团撤退单结果缺失或重复：{code}/{self.city}/{county}")
        row = matches[0]
        self.used.append({"result_id": row["result_id"], "metric_run_id": row["metric_run_id"]})
        return row[field] if row[field] is not None else 0

def build_data(database: Path | None, month: str, city: str) -> dict:
    db = CityResults(database, month, city)
    auto = CityResults(database, month, city, AUTOMATION_OWNER)
    terminal = TerminalResults(database, month, city)
    support = SupportResults(database, month, city)
    city = db.city
    months = [shifted(month, offset) for offset in range(-11, 1)]
    year, month_number = map(int, month.split("-"))

    def count(code: str, kind: str, **dims):
        return db.value(code, kind, "metric_value", **dims)

    def numerator(code: str, kind: str, **dims):
        return db.value(code, kind, "numerator", **dims)

    def auto_value(code: str, kind: str, field: str = "metric_value", **dims):
        return auto.value(code, kind, field, **dims)

    def county_names(code: str) -> list[str]:
        names: list[str] = []
        for row in db.rows:
            county = row["dimension"].get("county")
            if (
                row["metric_code"] == code
                and row["dimension_type"] == "month_city_county"
                and row["dimension"].get("month") == month
                and normalize_city(row["dimension"].get("city", "")) == city
                and county not in {None, "未归属区县"}
                and county not in names
            ):
                names.append(county)
        return names

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

    def automation_group(prefix: str, stages: list[str]) -> dict:
        code = f"internet_{prefix}_automation_rate"
        overall_stage = f"{len(stages)}环节整体"
        return {
            "overall": auto_value(code, "month_city_all_stages", month=month, city=city,
                                  stage=overall_stage),
            "automaticCount": auto_value(code, "month_city_all_stages", "numerator",
                                         month=month, city=city, stage=overall_stage),
            "totalCount": auto_value(code, "month_city_all_stages", "denominator",
                                     month=month, city=city, stage=overall_stage),
            "stages": [{"name": stage, "value": auto_value(code, "month_city_stage",
                       month=month, city=city, stage=stage)} for stage in stages],
            "counties": internet_counties,
            "countyOverall": [auto_value(code, "month_city_county_all_stages", month=month,
                              city=city, county=county, stage=overall_stage) for county in internet_counties],
            "countyStageSeries": [{"name": stage, "values": [
                auto_value(code, "month_city_county_stage", month=month, city=city,
                           county=county, stage=stage) for county in internet_counties
            ]} for stage in stages],
        }
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
        "internetAuto": automation_group("opening", ["受理", "方案设计", "组网方案", "资源分配",
                                                     "资源反馈", "配置激活", "开通结果审核", "归档审核", "报结"]),
        "internetMoveAuto": automation_group("move", ["受理", "方案设计", "组网方案", "资源分配",
                                                         "资源反馈", "配置激活", "开通结果审核", "归档审核", "报结"]),
        "internetRemovalAuto": automation_group("removal", ["受理", "资源查询", "配置激活",
                                                               "开通结果审核", "组织资源释放", "报结"]),
    }
    data["internetAuto"]["engineeringCounts"] = [
        auto_value("internet_opening_network_nonautomatic_engineering_count", "month_city_county",
                   month=month, city=city, county=county) for county in internet_counties
    ]
    nonautomatic_count = auto_value("internet_opening_network_nonautomatic_count", "month_city",
                                    month=month, city=city)
    engineering_count = auto_value("internet_opening_network_nonautomatic_engineering_count", "month_city",
                                   month=month, city=city)
    blank_count = auto_value("internet_opening_network_nonautomatic_blank_count", "month_city",
                             month=month, city=city)
    data["internetAuto"]["manualReasons"] = {
        "nonautomaticCount": nonautomatic_count,
        "engineeringCount": engineering_count,
        "blankCount": blank_count,
        "engineeringShare": engineering_count / nonautomatic_count if nonautomatic_count else None,
        "blankShare": blank_count / nonautomatic_count if nonautomatic_count else None,
        "allEngineeringCounties": [county for index, county in enumerate(internet_counties)
                                    if auto_value("internet_opening_network_nonautomatic_count",
                                                  "month_city_county", month=month, city=city,
                                                  county=county) > 0
                                    and data["internetAuto"]["engineeringCounts"][index]
                                    == auto_value("internet_opening_network_nonautomatic_count",
                                                  "month_city_county", month=month, city=city,
                                                  county=county)],
    }

    city_short = city.removesuffix("市")
    terminal_city = {
        "labels": CITIES,
        "expected": [terminal.value("city_summary", name, "应拆回设备数") for name in CITIES],
        "completed": [terminal.value("city_summary", name, "已拆回设备数量") for name in CITIES],
        "rates": [terminal.value("city_summary", name, "终端回收率") for name in CITIES],
    }
    terminal_city["expectedTotal"] = int(sum(terminal_city["expected"]))
    terminal_city["completedTotal"] = int(sum(terminal_city["completed"]))
    terminal_city["rate"] = (terminal_city["completedTotal"] / terminal_city["expectedTotal"]
                             if terminal_city["expectedTotal"] else 0)
    ranked_cities = sorted(zip(CITIES, terminal_city["rates"]), key=lambda item: (item[1], CITIES.index(item[0])))
    terminal_city["bottomRankNames"] = [name for name, _rate in ranked_cities[:3]]

    district_rate_rows = [row for row in terminal.rows
                          if row["dimension_type"] == "district_summary"
                          and row["dimension"].get("column") == "终端回收率"
                          and row["dimension"].get("label", "").startswith(city_short + "·")
                          and (row["denominator"] or 0) > 0]
    selected_low = sorted(district_rate_rows,
                          key=lambda row: (row["metric_value"], row["dimension"]["label"]))[:10]
    bottom_names = [row["dimension"]["label"].partition("·")[2] for row in selected_low[:3]]
    district_rate_rows = list(reversed(selected_low))
    district_labels_full = [row["dimension"]["label"] for row in district_rate_rows]
    district_labels = [label.partition("·")[2] for label in district_labels_full]

    business_labels = []
    for row in sorted((row for row in terminal.rows if row["dimension_type"] == "city_business"),
                      key=lambda row: row["dimension"].get("column_index", 0)):
        label = row["dimension"].get("column")
        if label and label not in business_labels:
            business_labels.append(label)
    business_series = []
    for device in DEVICES:
        business_series.append({"name": device, "values": [
            terminal.value("city_business", f"{city_short}·{device}", business_type)
            for business_type in business_labels
        ]})
    target_device_totals = [{"name": item["name"], "value": int(sum(item["values"]))}
                            for item in business_series]
    top_devices = sorted(target_device_totals, key=lambda item: item["value"], reverse=True)[:3]

    data["terminalRecovery"] = {
        "targetCity": city,
        "targetCityRate": terminal.value("city_summary", city_short, "终端回收率"),
        "targetCityCompletedTotal": terminal.value("city_summary", city_short, "已拆回设备数量"),
        "city": terminal_city,
        "topInstaller": {
            "labels": district_labels,
            "expected": [terminal.value("district_summary", label, "应拆回设备数") for label in district_labels_full],
            "completed": [terminal.value("district_summary", label, "已拆回设备数量") for label in district_labels_full],
            "rates": [terminal.value("district_summary", label, "终端回收率") for label in district_labels_full],
            "bottomRankNames": bottom_names,
        },
        "deviceTypes": DEVICES,
        "topDevices": top_devices,
        "business": {"labels": business_labels, "series": business_series},
        "cityDevices": {"labels": CITIES, "series": [
            {"name": device, "values": [terminal.value("city", device, name) for name in CITIES]}
            for device in DEVICES
        ]},
        "installerDevices": {"labels": district_labels, "series": [
            {"name": device, "values": [terminal.value("district_summary", label, device)
                                         for label in district_labels_full]}
            for device in DEVICES
        ]},
    }
    support_counties = []
    for row in support.rows:
        county = row["dimension"].get("county")
        if row["dimension_type"] == "city_county" and county not in {None, "未归属区县"} \
                and county not in support_counties:
            support_counties.append(county)
    line_rate = "dedicated_line_opening_withdrawal_rate"
    qikuan_rate = "qikuan_withdrawal_rate"
    qikuan_return_rate = "qikuan_return_rate"
    def support_series(code):
        return [support.value(code, county) for county in support_counties]
    def support_reasons(prefix, names):
        return {name: support.value(f"{prefix}_{name}") for name in names}
    def top_rate_names(code):
        pairs = [(county, support.value(code, county)) for county in support_counties
                 if support.value(code, county, "denominator") > 0]
        return [county for county, _ in sorted(pairs, key=lambda pair: (-pair[1], pair[0]))[:3]]
    line_reason_names = ["network", "customer", "frontDesk", "other"]
    qikuan_reason_names = ["customer", "frontDesk", "construction", "other", "network"]
    data["withdrawal"] = {
        "city": city, "counties": support_counties,
        "line": {
            "completed": support.value("dedicated_line_opening_completed_count"),
            "current": support.value("dedicated_line_opening_completed_current_accepted_count"),
            "previous": support.value("dedicated_line_opening_completed_previous_accepted_count"),
            "unknown": support.value("dedicated_line_opening_completed_unknown_accepted_count"),
            "count": support.value(line_rate, field="numerator"),
            "rate": support.value(line_rate), "rates": support_series(line_rate),
            "reasons": support_reasons("line_withdrawal_reason", line_reason_names),
            "reasonSeries": {name: support_series(f"line_withdrawal_reason_{name}")
                             for name in line_reason_names},
        },
        "qikuan": {
            "accepted": support.value(qikuan_rate, field="denominator"),
            "count": support.value(qikuan_rate, field="numerator"),
            "rate": support.value(qikuan_rate), "rates": support_series(qikuan_rate),
            "returned": support.value("qikuan_return_count"),
            "cancelled": support.value("qikuan_cancellation_count"),
            "returnRate": support.value(qikuan_return_rate),
            "returnRates": support_series(qikuan_return_rate),
            "returnSeries": support_series("qikuan_return_count"),
            "cancellationSeries": support_series("qikuan_cancellation_count"),
            "reasons": support_reasons("qikuan_withdrawal_reason", qikuan_reason_names),
            "returnReasons": support_reasons("qikuan_return_reason", qikuan_reason_names),
            "topRateCounties": top_rate_names(qikuan_rate),
            "topReturnCounties": top_rate_names(qikuan_return_rate),
        },
    }
    data["dataAudit"] = {
        "database": db.database,
        "period_start": db.run["period_start"],
        "period_end": db.run["period_end"],
        "city": city,
        "selected_batch": db.run,
        "selected_automation_batch": auto.run,
        "selected_terminal_batch": terminal.run,
        "selected_support_batch": support.run,
        "used_results": list(db.used.values()) + list(auto.used.values()) + list(terminal.used.values()) + support.used,
        "missing": list(db.missing.values()) + list(auto.missing.values()) + list(terminal.missing.values()),
        "null_values": list(db.nulls.values()) + list(auto.nulls.values()),
        "policy": "只读取成功的地市指标批次；区县使用区县名称；缺失指标不在绘图层重算。",
    }
    return data
