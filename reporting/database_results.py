"""Map stored metric results to the existing presentation JSON contract."""

import calendar
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage.metric_results import read_results, TABLES
from storage.database import _database_name, connect
from reporting.manual_results import load_results, apply_results, METRIC_SETS
from config.report_periods import integration_opening_period

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


def terminal_district_chart_rows(rows):
    """Select the lowest ten districts and order the chart high-to-low."""
    selected = sorted(rows, key=lambda r: (r["metric_value"], r["dimension"]["label"]))[:10]
    bottom_names = [r["dimension"]["label"].partition("·")[2] or r["dimension"]["label"]
                    for r in selected[:3]]
    return list(reversed(selected)), bottom_names


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
        self.withdrawal_start, self.withdrawal_end = integration_opening_period(month)
        self.support_start = f"{shifted(month, -2)}-01"
        self.database = _database_name()
        self.used = {}
        self.missing = {}
        self.rows = {}
        self.runs = {}
        with connect(database) as conn:
            runs = conn.execute(
                "SELECT * FROM metric_run WHERE status='success' AND period_end IN (?, ?) "
                "ORDER BY started_at DESC, metric_run_id DESC", (self.end, self.withdrawal_end)
            ).fetchall()
            for run in runs:
                owner = run["metric_code"]
                if owner not in TABLES:
                    continue
                is_trend = owner == "orchestration_opening_metrics"
                if owner in self.runs:
                    continue
                if owner == "dedicated_line_opening_withdrawal_rate":
                    if (run["period_start"], run["period_end"]) != (self.withdrawal_start, self.withdrawal_end):
                        continue
                elif owner in SUPPORT_METRICS:
                    if run["period_start"] != self.support_start:
                        continue
                elif not is_trend and run["period_start"] != self.start:
                    continue
                if run["period_start"] > self.start:
                    continue
                self.runs[owner] = dict(run)
                rows = read_results(conn, owner, run["metric_run_id"])
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


def build_data(database, month, manual_metrics_dir=None, required_manual=METRIC_SETS):
    manual, manual_audit = load_results(manual_metrics_dir, month, required_manual) if manual_metrics_dir is not None else ({}, [])
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
        enhanced = any(r['dimension'].get('automatic_value') == '包含自动' for r in rows)
        if enhanced:
            from metrics.opening.automation_intermediate import OPENING, REMOVAL
            stages = [s for s, _ in (REMOVAL if action == 'removal' else OPENING)]
        result = {"automaticCount": get(code, "month_all_stages", "numerator", month=month),
                  "totalCount": get(code, "month_all_stages", "denominator", month=month),
                  "overallRate": count(code, "month_all_stages"), "labels": stages,
                  "rates": [count(code, "month_stage", stage=s) for s in stages]}
        if action != "opening":
            result.update(cities=CITIES, activationRates=[count(f"internet_{action}_activation_rate", "month_city", city=c) for c in CITIES])
        if enhanced:
            result['automationSource'] = 'intermediate_orchestration_orders'
            if not result['totalCount']:
                result['overallRate'] = None
                result['rates'] = [None for _ in stages]
                if action != 'opening':
                    result['activationRates'] = [None for _ in CITIES]
            mapping = {'opening': [('network', '组网方案')],
                       'move': [('network', '组网方案'), ('resource', '资源反馈')],
                       'removal': [('release', '组织资源释放')]}[action]
            for name, stage in mapping:
                result[name] = {'cities': CITIES,
                    'rates': [count(code, 'month_city_stage', city=c, stage=stage) for c in CITIES],
                    'numerators': [get(code, 'month_city_stage', 'numerator', month=month, city=c, stage=stage) for c in CITIES],
                    'denominators': [get(code, 'month_city_stage', 'denominator', month=month, city=c, stage=stage) for c in CITIES]}
                result[name]['rates'] = [r if d else None for r, d in zip(result[name]['rates'], result[name]['denominators'])]
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
    district_rates = [r for r in db.rows.get(owner, [])
                      if r["dimension_type"] == "district_summary"
                      and r["dimension"]["column"] == "终端回收率" and r["denominator"] > 0]
    district_rates, bottom_rank_names = terminal_district_chart_rows(district_rates)
    district_labels = [r["dimension"]["label"].partition("·")[2] or r["dimension"]["label"]
                       for r in district_rates]
    if not district_rates:
        db.unavailable("terminalRecovery.topInstaller/installerDevices")
    def district_value(row, column):
        return db.value(owner, "terminal_recovery_rate" if column == "终端回收率" else "terminal_recovery_count",
                        "district_summary", label=row["dimension"]["label"], column=column)
    top_devices = sorted([{"name": d, "value": int(terminal("总计", d, "business"))} for d in DEVICES], key=lambda r: r['value'], reverse=True)[:3]
    terminal_data = {"city": city, "topInstaller": {"labels": district_labels,
                     "expected": [district_value(r, "应拆回设备数") for r in district_rates],
                     "completed": [district_value(r, "已拆回设备数量") for r in district_rates],
                     "rates": [district_value(r, "终端回收率") for r in district_rates],
                     "bottomRankNames": bottom_rank_names},
                     "deviceTypes": DEVICES, "topDevices": top_devices, "business": cross_table("business", BUSINESSES),
                     "cityDevices": cross_table("city", CITIES), "installerDevices": {"labels": district_labels, "series": [{"name": d, "values": [district_value(r, d) for r in district_rates]} for d in DEVICES]}}

    withdrawal_code = "dedicated_line_opening_withdrawal_rate"
    def withdrawal_value(kind, field="metric_value", **dimension):
        return db.value(withdrawal_code, withdrawal_code, kind, field, **dimension)
    withdrawal = {"cities": CITIES, "rates": [withdrawal_value("city", city=c) for c in CITIES],
                  "withdrawalCount": withdrawal_value("province", "numerator", scope="全省"),
                  "withdrawalRate": withdrawal_value("province", scope="全省")}
    for name in ("networkReasons", "customerReasons", "frontDeskReasons", "otherReasons"):
        db.unavailable("withdrawal." + name)
        withdrawal[name] = [0] * len(CITIES)
    for name in ("networkCount", "customerCount", "frontDeskCount", "otherCount", "networkShare", "customerShare", "frontDeskShare", "otherShare"):
        withdrawal[name] = db.unavailable("withdrawal." + name)

    for name, code in {
        "completionCount": "dedicated_line_opening_completed_count",
        "currentAcceptedCompletion": "dedicated_line_opening_completed_current_accepted_count",
        "previousAcceptedCompletion": "dedicated_line_opening_completed_previous_accepted_count",
        "unknownAcceptedCompletion": "dedicated_line_opening_completed_unknown_accepted_count",
    }.items():
        row = db.find(withdrawal_code, code, "province", scope="全省")
        withdrawal[name] = (db.value(withdrawal_code, code, "province", scope="全省")
                            if row is not None else None)

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
        "sourceFileName": db.database, "currentMonth": month, "displayMonth": f"{month_number}月", "displayMonthFull": f"{year}年{month_number}月",
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
                         "policy": "Opening withdrawal uses the previous-month 26th through current-month 25th; other monthly results use their configured natural or support periods. Orchestration history uses explicit month dimensions. Missing/null results are zero; no raw-data calculations."}
    data['dataAudit']['selected_manual_inputs'] = manual_audit
    apply_results(data, manual, data['dataAudit'], db)
    return data
