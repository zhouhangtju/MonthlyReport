"""Read the successful stored activation-silence run for the report slide."""

from __future__ import annotations

from collections import Counter
import json

OWNER = "qikuan_activation_silence"
CODE = "qikuan_activation_silence_rate"
CITIES = ["杭州", "嘉兴", "宁波", "温州", "金华", "绍兴", "湖州", "台州", "衢州", "丽水", "舟山"]


def build_silence(db, month: str) -> dict:
    if OWNER not in db.runs:
        return {"month": month, "available": False, "source": None}
    rows = [row for row in db.rows[OWNER] if row["metric_code"] == CODE
            and row["dimension"].get("month") == month]
    def records(kind):
        return [dict(row["dimension"], numerator=int(row["numerator"]),
                     denominator=int(row["denominator"]), rate=row["metric_value"])
                for row in rows if row["dimension_type"] == kind]
    province = records("province")
    if len(province) != 1:
        raise ValueError("企宽激活即沉默全省结果缺失或重复")
    cities = records("city")
    districts = records("district")
    grids = [row for row in records("grid") if row["denominator"] >= 5]
    def ranked(data):
        return sorted(data, key=lambda row: (-row["rate"], -row["numerator"],
                    -row["denominator"], row.get("city", ""), row.get("district", ""),
                    row.get("grid", "")))
    def display(data, field):
        names = Counter(row[field] for row in data)
        for row in data:
            row["label"] = row[field] if names[row[field]] == 1 else (
                f"{row['city']}·{row[field]}")
        return data
    city_by_name = {row["city"]: row for row in cities}
    if any(city not in city_by_name for city in CITIES):
        raise ValueError("企宽激活即沉默地市结果未覆盖全部11地市")
    city_chart = sorted((city_by_name[city] for city in CITIES),
                        key=lambda row: (row["rate"], CITIES.index(row["city"])))
    district_top = display(ranked(districts)[:10], "district")
    grid_top = display(ranked(grids)[:10], "grid")
    source_runs = db.runs[OWNER].get("source_runs") or "{}"
    audit = json.loads(source_runs) if isinstance(source_runs, str) else source_runs
    return {"month": month, "available": True, "province": province[0], "cities": city_chart,
            "denominatorMonth": audit.get("denominator_month"),
            "districtTop": district_top, "gridTop": grid_top,
            "cityTopNames": [row["city"] for row in ranked(cities)[:3]],
            "districtTopNames": [row["label"] for row in district_top[:3]],
            "gridTopNames": [row["label"] for row in grid_top[:3]],
            "source": db.runs[OWNER]["metric_run_id"]}
