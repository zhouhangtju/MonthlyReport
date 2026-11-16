"""Build all city report indicators alongside the provincial calculation."""
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import json
import uuid

from metrics.opening import automation_intermediate as auto
from metrics.opening.bycity import dedicated_line_metrics_by_city as citydev
from storage.database import connect

OWNER = "orchestration_city_metrics"
TABLE = "result_orchestration_city"


class CityVolumes:
    def __init__(self, month, cities):
        self.month = month
        self.cities = cities
        path = citydev.DEFAULT_COUNTY_MAP
        if not path.exists():
            path = Path(auto.__file__).resolve().parents[1] / "terminal_recovery/区县信息汇总.xlsx"
        self.mapping = citydev.load_county_mapping(path)
        self.counties = Counter()
        self.by_city = defaultdict(list)
        self.months = set()

    def county(self, city, row):
        return citydev.standardize_county(
            row.get("区县名称"), row.get("主题"), self.mapping["aliases"][city.removesuffix("市")]
        )

    def observe(self, city, business, product, row):
        self.counties[city, self.county(city, row), business, product] += 1

    def monthly(self, month, products):
        self.months.add(month)
        for city in self.cities:
            for business, code, names in citydev.BUSINESS_GROUPS:
                dims = dict(city=city, month=month)
                counts = [products[business, city, name] for name in names]
                items = self.by_city[city]
                items.append(citydev.result(code, "month_city", dims, sum(counts)))
                for name, n in zip(names, counts):
                    items.append(citydev.result(code, "month_city_product", dict(dims, product=name), n))
                if month != self.month:
                    continue
                for county in self.labels(city):
                    dims2 = dict(dims, county=county)
                    counts = [self.counties[city, county, business, name] for name in names]
                    items.append(citydev.result(code, "month_city_county", dims2, sum(counts)))
                    for name, n in zip(names, counts):
                        items.append(
                            citydev.result(code, "month_city_county_product", dict(dims2, product=name), n)
                        )

    def labels(self, city):
        labels = self.mapping["standards"][city.removesuffix("市")]
        return [*labels, citydev.UNASSIGNED_COUNTY]

    def complete(self, summaries, required):
        if self.month not in self.months:
            raise ValueError(f"{self.month} 缺少生成区县分布所需的编排工单明细")
        codes = {code for _, code, _ in citydev.BUSINESS_GROUPS}
        for item in summaries:
            dim = item["dimension"]
            if (
                item["metric_code"] in codes
                and dim.get("month") in required - self.months
                and dim.get("city") in self.cities
                and item["dimension_type"] in {"month_city", "month_city_product"}
            ):
                self.by_city[dim["city"]].append(item)
        missing = {}
        for city, items in self.by_city.items():
            keys = {
                (
                    v["metric_code"],
                    v["dimension_type"],
                    v["dimension"].get("month"),
                    v["dimension"].get("product"),
                )
                for v in items
            }
            citydev.add_comparisons(items, city, self.month)
            citydev.add_rolling_results(items, city, self.month)
            missing[city] = sorted(
                m for m in required if ("internet_opening_orders", "month_city", m, None) not in keys
            )
            for item in items:
                dim = item["dimension"]
                if "comparison_month" in dim:
                    code = item["metric_code"].split("_")[0] + "_opening_orders"
                    kind = "month_city_product" if "product" in dim else "month_city"
                    bases = [
                        (code, kind, m, dim.get("product")) for m in (self.month, dim["comparison_month"])
                    ]
                elif item["dimension_type"].startswith("rolling_"):
                    names = [dim["product"]] if "product" in dim else citydev.OTHER_INTERNET_PRODUCTS
                    bases = [
                        (
                            "internet_opening_orders",
                            "month_city_product",
                            citydev.shift_month(self.month, -i),
                            p,
                        )
                        for i in range(12)
                        for p in names
                    ]
                else:
                    continue
                if any(key not in keys for key in bases):
                    for field in ("numerator", "denominator", "metric_value"):
                        item[field] = None
        return missing


def city_automation(connection, volume, build_id, provincial):
    from pymysql.cursors import SSDictCursor

    month = volume.month
    results = []
    for city in volume.cities:
        buckets = defaultdict(list)
        reasons = Counter()
        with connection._connection.cursor(SSDictCursor) as cursor:
            cursor.execute(
                f"SELECT * FROM {auto.TABLE} WHERE report_month=%s AND build_id=%s AND 地市=%s",
                (month, build_id, city),
            )
            for row in cursor:
                source = json.loads(row.pop("source_payload"))
                county = volume.county(city, source)
                matches = row.pop("asset_matches")
                buckets[row["业务类型"], county].append(row)
                if (
                    row["业务类型"] == "互联网专线"
                    and row["订单状态"] == "已完成"
                    and row["订单类型"] == "开通"
                    and auto.stage_participates(row["组网方案"])
                    and not auto.automatic(row["组网方案"])
                ):
                    opinion = json.loads(matches).get("组网方案", {}).get("处理意见", "")
                    reasons[county, "count"] += 1
                    reasons[
                        county,
                        "engineering_count"
                        if "工程施工" in opinion
                        else "other_count"
                        if opinion
                        else "blank_count",
                    ] += 1
        stages = defaultdict(lambda: [0, 0])
        for county in volume.labels(city):
            dims = dict(city=city, county=county, month=month)
            for reason in ("count", "engineering_count", "other_count", "blank_count"):
                code = "internet_opening_network_nonautomatic_" + reason
                results.append(citydev.result(code, "month_city_county", dims, reasons[county, reason]))
            for prefix, (business,) in auto.BUSINESS_GROUPS.items():
                rows = buckets[business, county]
                indicators = auto.aggregate(rows, month, prefix)
                if prefix != "video":
                    indicators.extend(auto.aggregate_stop_resume(rows, month, prefix))
                    for action, suffix in (("停机", "stop"), ("复机", "resume")):
                        action_rows = [row for row in rows if auto.clean(row.get("调整类型")) == action]
                        for item in auto.aggregate_stop_resume(action_rows, month, prefix):
                            item["metric_code"] = item["metric_code"].replace("_stop_resume_", f"_{suffix}_")
                            indicators.append(item)
                for item in indicators:
                    kind = item["dimension_type"]
                    dim = item["dimension"]
                    if kind == "month_city" and dim["city"] == "全省合计":
                        kind = "month"
                    elif kind not in ("month_stage", "month_all_stages"):
                        continue
                    code = item["metric_code"]
                    n, d = item["numerator"], item["denominator"]
                    region = dict(dims)
                    if "stage" in dim:
                        region["stage"] = dim["stage"]
                    results.append(
                        citydev.result(code, kind.replace("month", "month_city_county", 1), region, n, d)
                    )
                    pair = stages[code, kind, dim.get("stage")]
                    pair[0] += n
                    pair[1] += d
        for reason in ("count", "engineering_count", "other_count", "blank_count"):
            results.append(
                citydev.result(
                    "internet_opening_network_nonautomatic_" + reason,
                    "month_city",
                    dict(month=month, city=city),
                    sum(n for (county, k), n in reasons.items() if k == reason),
                )
            )
        shared = {
            (r["metric_code"], r["dimension_type"], r["dimension"].get("stage")): r
            for r in provincial
            if r["dimension"].get("city") == city
        }
        for (code, kind, stage), (n, d) in stages.items():
            kind = kind.replace("month", "month_city", 1)
            existing = shared.get((code, kind, stage))
            if existing:
                if (n, d) != (existing["numerator"], existing["denominator"]):
                    raise ValueError(f"区县合计与省级结果不一致：{city}/{code}/{stage}")
                results.append(existing)
            else:
                dims = dict(city=city, month=month)
                if stage:
                    dims["stage"] = stage
                results.append(citydev.result(code, kind, dims, n, d))
    return results


def publish(database, volumes, audit, province_run, provincial, start, missing):
    month = volumes.month
    build_id = audit["build_id"]
    with connect(database) as c:
        c.execute(
            f"""CREATE TABLE IF NOT EXISTS {TABLE} (
          result_id BIGINT PRIMARY KEY AUTO_INCREMENT, metric_run_id VARCHAR(80) NOT NULL,
          report_month CHAR(7) NOT NULL, indicator_month CHAR(7) NOT NULL, city VARCHAR(64) NOT NULL,
          county VARCHAR(64), metric_code VARCHAR(128) NOT NULL, dimension_type VARCHAR(80) NOT NULL,
          dimension_value JSON NOT NULL, numerator DOUBLE, denominator DOUBLE, metric_value DOUBLE,
          INDEX city_report(metric_run_id,city,report_month)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
        )
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        c.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        builds = c.execute(
            f"SELECT DISTINCT build_id FROM {auto.TABLE} WHERE report_month=?", (month,)
        ).fetchall()
        if [r["build_id"] for r in builds] != [build_id]:
            raise ValueError("中间结果批次已变化，请重新运行")
        rows = city_automation(c, volumes, build_id, provincial)
        rows.extend(r for group in volumes.by_city.values() for r in group)
        run = "city_" + uuid.uuid4().hex
        sql = f"""INSERT INTO {TABLE} (metric_run_id, report_month,indicator_month,city,county,metric_code,
             dimension_type,dimension_value,numerator,denominator,metric_value) VALUES (?,?,?,?,?,?,?,?,?,?,?)"""
        for first in range(0, len(rows), 1000):
            batch = []
            for r in rows[first : first + 1000]:
                dim = r["dimension"]
                batch.append(
                    (
                        run,
                        month,
                        dim.get("month", month),
                        dim["city"],
                        dim.get("county"),
                        r["metric_code"],
                        r["dimension_type"],
                        json.dumps(dim, ensure_ascii=False),
                        r["numerator"],
                        r["denominator"],
                        r["metric_value"],
                    )
                )
            c.executemany(sql, batch)
        now = datetime.now().isoformat()
        c.execute(
            """INSERT INTO metric_run(metric_run_id,metric_code,metric_version,period_start,period_end,
                     started_at,finished_at,status,source_runs) VALUES (?,?,?,?,?,?,?,'success',?)""",
            (
                run,
                OWNER,
                "1.0",
                start + "-01",
                citydev.month_dates(month)[1],
                now,
                now,
                json.dumps(
                    dict(
                        province_run=province_run,
                        build_id=build_id,
                        missing_history=missing,
                        county_map_sha256=volumes.mapping["sha256"],
                    ),
                    ensure_ascii=False,
                ),
            ),
        )
    return run
