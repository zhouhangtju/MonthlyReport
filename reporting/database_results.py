"""Map stored metric results to the existing presentation JSON contract."""

import calendar
import json
import math
import re
import sqlite3
from pathlib import Path

PRODUCTS = ["悦享专线动态IP版", "互联网专线套餐", "商务专线套餐（2020版）", "直播专线", "网吧专线套餐（2019版）", "高品质互联网专线"]
PRODUCT_LABELS = ["悦享专线\n动态IP版", "互联网\n专线套餐", "商务专线套餐\n（2020版）", "直播专线", "网吧专线套餐\n（2019版）", "高品质\n互联网专线"]
CITIES = ["杭州", "嘉兴", "宁波", "温州", "金华", "绍兴", "湖州", "台州", "衢州", "丽水", "舟山"]
DEVICES = ["ONU", "FTTO", "摄像头", "WIFI路由器", "专线卫士"]
BUSINESSES = ["互联网专线", "互联网专线（小微版）", "E企组网", "安全终端部署服务", "其他专线", "视频监控"]
STAGES = ["受理", "方案设计", "资源分配", "配置激活", "开通结果审核", "报结"]
SUPPORT_METRICS = {
    "dedicated_line_repeat_complaint_rate", "qianliyan_repeat_complaint_rate",
    "dedicated_line_install_fault_rate", "qikuan_install_fault_rate",
    "commercial_customer_install_fault_rate",
}


def month_bounds(month):
    if not re.fullmatch(r"\d{4}-\d{2}", str(month)):
        raise ValueError("月份格式应为 YYYY-MM")
    year, number = map(int, month.split("-"))
    last = calendar.monthrange(year, number)[1]
    return f"{month}-01", f"{month}-{last:02d}"


def shifted(month, offset):
    year, number = map(int, month.split("-"))
    year, number = divmod(year * 12 + number - 1 + offset, 12)
    return f"{year:04d}-{number + 1:02d}"


def short_month(month):
    return month[2:].replace("-", ".")


class Results:
    def __init__(self, database, month):
        self.month = month
        self.start, self.end = month_bounds(month)
        self.database = Path(database).resolve()
        self.used = {}
        self.missing = {}
        self.rows = {}
        self.runs = {}
        # A read-only connection prevents report generation from changing source data.
        with sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            runs = conn.execute(
                "SELECT * FROM metric_run WHERE status='success' AND period_end=? "
                "ORDER BY (period_start=?) DESC, started_at DESC, rowid DESC", (self.end, self.start)
            ).fetchall()
            for run in runs:
                owner = run["metric_code"]
                is_trend = owner == "orchestration_opening_metrics"
                if owner in self.runs or (run["period_start"] != self.start and not is_trend and owner not in SUPPORT_METRICS):
                    continue
                if run["period_start"] > self.start:
                    continue
                self.runs[owner] = dict(run)
                rows = conn.execute("SELECT * FROM ads_metric_result WHERE metric_run_id=? ORDER BY result_id", (run["metric_run_id"],)).fetchall()
                self.rows[owner] = [dict(row, dimension=json.loads(row["dimension_value"])) for row in rows]

    def find(self, owner, code, kind, **dimension):
        matches = []
        for row in self.rows.get(owner, []):
            if row["metric_code"] != code or row["dimension_type"] != kind:
                continue
            def equal(key, value):
                actual = row["dimension"].get(key)
                if key in {"city", "label"} and isinstance(actual, str) and isinstance(value, str):
                    return actual.removesuffix("市") == value.removesuffix("市")
                return actual == value
            if all(equal(k, v) for k, v in dimension.items()):
                matches.append(row)
        if len(matches) > 1:
            raise ValueError(f"指标维度不唯一：{owner}/{code}/{kind}/{dimension}")
        return matches[0] if matches else None

    def value(self, owner, code, kind, field="metric_value", **dimension):
        row = self.find(owner, code, kind, **dimension)
        spec = {"owner": owner, "metric_code": code, "dimension_type": kind, "dimension": dimension, "field": field}
        key = json.dumps(spec, ensure_ascii=False, sort_keys=True)
        value = row[field] if row else None
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            self.missing[key] = dict(spec, reason="missing_result" if row is None else "null_or_nonfinite_value", filled_value=0)
            return 0
        self.used[key] = dict(spec, metric_run_id=row["metric_run_id"], result_id=row["result_id"], value=value)
        return value

    def unavailable(self, name):
        self.missing[name] = {"ppt_field": name, "reason": "no_corresponding_stored_result", "filled_value": 0}
        return 0


def build_data(database, month):
    db = Results(database, month)
    opening = "orchestration_opening_metrics"
    months = [shifted(month, n) for n in range(-11, 1)]
    year, month_number = map(int, month.split("-"))
    def get(code, kind, field="metric_value", **dims):
        return db.value(opening, code, kind, field, **dims)
    def count(code, kind, **dims):
        return get(code, kind, month=month, **dims)
    def rank(labels, values, ascending=False):
        return [label for label, value in sorted(zip(labels, values), key=lambda p: p[1], reverse=not ascending)[:3]] if any(values) else []

    def line_group(prefix, products):
        code = f"{prefix}_opening_orders"
        city_totals = [count(code, "month_city", city=city) for city in CITIES]
        cities = sorted(CITIES, key=lambda c: city_totals[CITIES.index(c)], reverse=True)
        return {
            "currentTotal": count(code, "month"), "totalYoy": count(code + "_yoy", "month_comparison"),
            "products": [{"name": product, "value": count(code, "month_product", product=product),
                          "yoy": count(f"{prefix}_product_opening_yoy", "month_product_comparison", product=product),
                          "increase": get(f"{prefix}_product_opening_yoy", "month_product_comparison", "numerator", month=month, product=product)} for product in products],
            "cities": cities,
            "citySeries": [{"name": p, "values": [count(code, "month_city_product", city=c, product=p) for c in cities]} for p in products],
            "months": [short_month(m) for m in months], "periodShort": f"{short_month(months[0])}–{short_month(month)}",
            "trend": [get(code, "month", month=m) for m in months],
        }

    def automation(action):
        code = f"internet_{action}_automation_rate"
        stages = [s for s in STAGES if not (action == "removal" and s == "方案设计")]
        rows = [r for r in db.rows.get(opening, []) if r['metric_code'] == code and r['dimension_type'] == 'month_stage' and r['dimension'].get('month') == month]
        if rows:
            stages = [r['dimension']['stage'] for r in rows]
        result = {"automaticCount": get(code, "month_all_stages", "numerator", month=month),
                  "totalCount": get(code, "month_all_stages", "denominator", month=month),
                  "overallRate": count(code, "month_all_stages"), "labels": stages,
                  "rates": [count(code, "month_stage", stage=s) for s in stages]}
        if action != "opening":
            result.update(cities=CITIES, activationRates=[count(f"internet_{action}_activation_rate", "month_city", city=c) for c in CITIES])
        return result

    product_trends = {
        product: [get("internet_opening_orders", "month_product", month=value, product=product) for value in months]
        for product in PRODUCTS[:2]
    }

    def product_trend_summary(product):
        stored = db.find(
            opening,
            "internet_product_average_monthly_orders",
            "rolling_12_months",
            end_month=month,
            product=product,
        )
        if stored is not None:
            return {
                "sum": get("internet_product_average_monthly_orders", "rolling_12_months", "numerator", end_month=month, product=product),
                "average": get("internet_product_average_monthly_orders", "rolling_12_months", end_month=month, product=product),
            }
        total = sum(product_trends[product])
        return {"sum": total, "average": total / 12}

    owner = "terminal_recovery"
    def terminal(column, label, table="city_summary"):
        code = "terminal_recovery_rate" if column == "终端回收率" else "terminal_recovery_count"
        return db.value(owner, code, table, label=label, column=column)
    city = {"labels": CITIES,
            "expected": [terminal("应拆回设备数", c) for c in CITIES],
            "completed": [terminal("已拆回设备数量", c) for c in CITIES],
            "rates": [terminal("终端回收率", c) for c in CITIES]}
    # The stored city summary has eleven cities but no province-total row.
    expected_total = int(sum(city["expected"]))
    completed_total = int(sum(city["completed"]))
    city.update(expectedTotal=expected_total, completedTotal=completed_total,
                rate=completed_total / expected_total if expected_total else 0,
                bottomRankNames=rank(CITIES, city["rates"], True))
    def cross_table(table, fallback):
        rows = [r for r in db.rows.get(owner, []) if r['dimension_type'] == table]
        columns = {r['dimension']['column_index']: r['dimension']['column'] for r in rows if r['dimension']['column'] != '总计'}
        labels = [columns[i] for i in sorted(columns)] or fallback
        return {"labels": labels, "series": [{"name": d, "values": [terminal(c, d, table) for c in labels]} for d in DEVICES]}
    district_labels = [f"区县{i}" for i in range(1, 11)]
    db.unavailable("terminalRecovery.topInstaller/installerDevices")
    top_devices = sorted([{"name": d, "value": int(terminal("总计", d, "business"))} for d in DEVICES], key=lambda r: r['value'], reverse=True)[:3]
    terminal_data = {"city": city, "topInstaller": {"labels": district_labels, "expected": [0]*10, "completed": [0]*10, "rates": [0]*10, "bottomRankNames": []},
                     "deviceTypes": DEVICES, "topDevices": top_devices, "business": cross_table("business", BUSINESSES),
                     "cityDevices": cross_table("city", CITIES), "installerDevices": {"labels": district_labels, "series": [{"name": d, "values": [0]*10} for d in DEVICES]}}

    withdrawal_code = "dedicated_line_opening_withdrawal_rate"
    def withdrawal_value(kind, field="metric_value", **dimension):
        return db.value(withdrawal_code, withdrawal_code, kind, field, **dimension)
    withdrawal = {"cities": CITIES, "rates": [withdrawal_value("city", city=c) for c in CITIES],
                  "withdrawalCount": withdrawal_value("province", "numerator", scope="全省"),
                  "withdrawalRate": withdrawal_value("province", scope="全省")}
    for name in ("networkReasons", "customerReasons", "frontDeskReasons", "otherReasons"):
        db.unavailable("withdrawal." + name)
        withdrawal[name] = [0] * len(CITIES)
    for name in ("completionCount", "currentAcceptedCompletion", "previousAcceptedCompletion", "networkCount", "customerCount", "frontDeskCount", "otherCount", "networkShare", "customerShare", "frontDeskShare", "otherShare"):
        withdrawal[name] = db.unavailable("withdrawal." + name)

    def rates(code):
        return [db.value(code, code, "city", city=c) for c in CITIES]
    def province_rate(code):
        return db.value(code, code, "province", scope="全省")
    def support_period(codes):
        periods = sorted({(db.runs[c]["period_start"], db.runs[c]["period_end"]) for c in codes if c in db.runs})
        return "、".join(f"{start}至{end}" for start, end in periods) or f"{year}年{month_number}月"
    repeat_line = rates("dedicated_line_repeat_complaint_rate")
    repeat_camera = rates("qianliyan_repeat_complaint_rate")
    fault_total = rates("commercial_customer_install_fault_rate")
    complaint = {"period": f"{year}年{month_number}月",
                 "repeatPeriod": support_period(["dedicated_line_repeat_complaint_rate", "qianliyan_repeat_complaint_rate"]),
                 "faultPeriod": support_period(["dedicated_line_install_fault_rate", "qikuan_install_fault_rate", "commercial_customer_install_fault_rate"]),
                 "repeat": {"cities": CITIES, "lineRates": repeat_line, "broadbandRates": repeat_camera,
                            "totalRates": [db.unavailable("complaintFault.repeat.totalRates")] * len(CITIES),
                            "lineAverage": province_rate("dedicated_line_repeat_complaint_rate"),
                            "broadbandAverage": province_rate("qianliyan_repeat_complaint_rate"),
                            "totalAverage": db.unavailable("complaintFault.repeat.totalAverage"),
                            "lineHighNames": rank(CITIES, repeat_line), "broadbandHighNames": rank(CITIES, repeat_camera)},
                 "fault": {"cities": CITIES, "lineRates": rates("dedicated_line_install_fault_rate"), "broadbandRates": rates("qikuan_install_fault_rate"),
                           "totalRates": fault_total, "lineAverage": province_rate("dedicated_line_install_fault_rate"),
                           "broadbandAverage": province_rate("qikuan_install_fault_rate"), "totalAverage": province_rate("commercial_customer_install_fault_rate"),
                           "highNames": rank(CITIES, fault_total)}}
    data = {
        "sourceFileName": db.database.name, "currentMonth": month, "displayMonth": f"{month_number}月", "displayMonthFull": f"{year}年{month_number}月",
        "currentTotal": count("internet_opening_orders", "month"), "yoy": count("internet_opening_orders_yoy", "month_comparison"), "mom": count("internet_opening_orders_mom", "month_comparison"),
        "keyProducts": {p: count("internet_opening_orders", "month_product", product=p) for p in PRODUCTS[:3]},
        "keyProductYoy": {p: count("internet_product_opening_yoy", "month_product_comparison", product=p) for p in PRODUCTS[:3]},
        "province": [{"name": p, "label": label, "value": count("internet_opening_orders", "month_product", product=p)} for p, label in zip(PRODUCTS, PRODUCT_LABELS)],
        "cities": CITIES, "citySeries": [{"name": label.replace('\n', ''), "values": [count("internet_opening_orders", "month_city_product", city=c, product=p) for c in CITIES]} for p, label in zip(PRODUCTS, PRODUCT_LABELS)],
        "months": [short_month(m) for m in months], "trendSeries": [{"name": p, "values": product_trends[p]} for p in PRODUCTS[:2]],
        "packageTrend": {"name": "互联网专线套餐", "values": [get("internet_opening_orders", "month_product", month=m, product=PRODUCTS[1]) for m in months]},
        "otherTrend": {"name": "互联网专线其他产品", "values": [get("other_internet_opening_orders", "month", month=m) for m in months]},
        "trendPeriodText": f"{months[0]}–{month}", "trendPeriodShort": f"{short_month(months[0])}–{short_month(month)}",
        "trendSummary": {p: product_trend_summary(p) for p in PRODUCTS[:2]},
        "otherTrendSummary": {"sum": get("other_internet_average_monthly_orders", "rolling_12_months", "numerator", end_month=month), "average": get("other_internet_average_monthly_orders", "rolling_12_months", end_month=month)},
        "mpls": line_group("mpls", ["地区内MPLSVPN套餐", "省内MPLSVPN套餐"]),
        "transmission": line_group("transmission", ["光纤出租套餐", "地区内数字电路出租套餐", "地区间精品电路", "地区内SPN电路出租", "地区间数字电路出租套餐", "地区内精品电路"]),
        "internetAuto": automation("opening"), "internetMoveAuto": automation("move"), "internetRemovalAuto": automation("removal"),
        "terminalRecovery": terminal_data, "withdrawal": withdrawal, "complaintFault": complaint,
    }
    data["dataAudit"] = {"database": str(db.database), "period_start": db.start, "period_end": db.end,
                         "selected_batches": list(db.runs.values()), "used_results": list(db.used.values()), "missing": list(db.missing.values()),
                         "derived_results": {"terminalRecovery.city.expectedTotal": "sum of the eleven stored city expected counts", "terminalRecovery.city.completedTotal": "sum of the eleven stored city completed counts", "terminalRecovery.city.rate": "completedTotal / expectedTotal; zero when denominator is zero", "trendSummary": "stored rolling-12-month metric when available; otherwise sum and average of the twelve stored month_product results from the selected orchestration run"},
                         "policy": "Monthly results; support metrics prefer the exact month, falling back to the latest successful period ending on that month, with actual periods displayed. Orchestration history uses explicit month dimensions. Missing/null results are zero; no raw-data calculations."}
    return data
