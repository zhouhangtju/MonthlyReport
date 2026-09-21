"""Combine dedicated-line, enterprise-broadband and Qianliyan result JSON files."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


CITIES = ["杭州", "嘉兴", "宁波", "温州", "金华", "绍兴", "湖州", "台州", "衢州", "丽水", "舟山"]
LINE_CODE = "dedicated_line_repeat_complaint_rate"
QIANLIYAN_CODE = "qianliyan_repeat_complaint_rate"
QIKUAN_CODE = "qikuan_repeat_complaint_rate"
COMBINED_CODE = "combined_repeat_complaint_rate"
WEIGHTS = {"line": 0.4, "qikuan": 0.4, "qianliyan": 0.2}


def read_json(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError(f"无法读取结果JSON：{path}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"结果JSON顶层必须为对象：{path}")
    return document


def rate(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}缺少有效重复投诉率")
    if not 0 <= value <= 1:
        raise ValueError(f"{label}重复投诉率必须在0到1之间")
    return float(value)


def normalize_city(value: object) -> str:
    return str(value or "").strip().removesuffix("市")


def stored_rates(document: dict[str, object], metric_code: str, label: str) -> tuple[float, dict[str, float]]:
    if document.get("metric_code") not in (None, metric_code):
        raise ValueError(f"{label}结果指标不匹配：{document.get('metric_code')}")
    results = document.get("results")
    if not isinstance(results, list):
        raise ValueError(f"{label}结果缺少results数组")
    province = None
    cities: dict[str, float] = {}
    for row in results:
        if not isinstance(row, dict) or row.get("metric_code") != metric_code:
            continue
        dimension = row.get("dimension")
        if not isinstance(dimension, dict):
            continue
        if row.get("dimension_type") == "province" and dimension.get("scope") == "全省":
            province = rate(row.get("metric_value"), f"{label}全省")
        elif row.get("dimension_type") == "city":
            city = normalize_city(dimension.get("city"))
            if city in CITIES:
                if city in cities:
                    raise ValueError(f"{label}存在重复地市：{city}")
                cities[city] = rate(row.get("metric_value"), f"{label}{city}")
    if province is None:
        raise ValueError(f"{label}缺少全省结果")
    missing = set(CITIES) - set(cities)
    if missing:
        raise ValueError(f"{label}缺少地市结果：{'、'.join(sorted(missing))}")
    return province, cities


def qikuan_rates(document: dict[str, object], month: str) -> tuple[float, dict[str, float]]:
    if document.get("metric_set") != QIKUAN_CODE:
        raise ValueError("企宽结果metric_set不匹配")
    if document.get("report_month") != month:
        raise ValueError(f"企宽结果月份不是{month}")
    province_row = document.get("province")
    rows = document.get("cities")
    if not isinstance(province_row, dict) or not isinstance(rows, dict):
        raise ValueError("企宽结果缺少province或cities")
    province = rate(province_row.get("rate"), "企宽全省")
    cities = {normalize_city(city): rate(row.get("rate"), f"企宽{city}")
              for city, row in rows.items() if normalize_city(city) in CITIES and isinstance(row, dict)}
    missing = set(CITIES) - set(cities)
    if missing:
        raise ValueError(f"企宽结果缺少地市：{'、'.join(sorted(missing))}")
    return province, cities


def weighted(line: float, qikuan: float, qianliyan: float) -> float:
    return line * WEIGHTS["line"] + qikuan * WEIGHTS["qikuan"] + qianliyan * WEIGHTS["qianliyan"]


def calculate(line_document: dict[str, object], qianliyan_document: dict[str, object],
              qikuan_document: dict[str, object], month: str) -> dict[str, object]:
    line_province, line_cities = stored_rates(line_document, LINE_CODE, "专线")
    qianliyan_province, qianliyan_cities = stored_rates(qianliyan_document, QIANLIYAN_CODE, "千里眼")
    qikuan_province, qikuan_cities = qikuan_rates(qikuan_document, month)
    city_results = {
        city: {
            "line_rate": line_cities[city],
            "qikuan_rate": qikuan_cities[city],
            "qianliyan_rate": qianliyan_cities[city],
            "rate": weighted(line_cities[city], qikuan_cities[city], qianliyan_cities[city]),
        }
        for city in CITIES
    }
    province = {
        "line_rate": line_province,
        "qikuan_rate": qikuan_province,
        "qianliyan_rate": qianliyan_province,
        "rate": weighted(line_province, qikuan_province, qianliyan_province),
    }
    ranking = sorted(CITIES, key=lambda city: (-city_results[city]["rate"], CITIES.index(city)))
    return {
        "schema_version": "1.0",
        "metric_set": COMBINED_CODE,
        "metric": "合计重复投诉率",
        "report_month": month,
        "formula": "专线重复投诉率*0.4+企宽重复投诉率*0.4+千里眼重复投诉率*0.2",
        "weights": WEIGHTS,
        "province": province,
        "cities": city_results,
        "top_cities": ranking[:3],
    }


def source_info(path: Path) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    return {"path": str(resolved), "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description="从三类重复投诉率结果JSON计算加权合计重复投诉率")
    parser.add_argument("--line-result", required=True, type=Path, help="专线重复投诉率结果JSON")
    parser.add_argument("--qianliyan-result", required=True, type=Path, help="千里眼重复投诉率结果JSON")
    parser.add_argument("--qikuan-result", required=True, type=Path, help="企宽重复投诉率结果JSON")
    parser.add_argument("--month", required=True, help="月报月份，格式YYYY-MM")
    parser.add_argument("--output", type=Path,
                        help="合计重复投诉率结果JSON；不传时使用相对路径 outputs/manual_metrics/合计重复投诉率_月份.json")
    args = parser.parse_args()
    output = args.output or Path("outputs") / "manual_metrics" / f"合计重复投诉率_{args.month}.json"
    result = calculate(read_json(args.line_result), read_json(args.qianliyan_result),
                       read_json(args.qikuan_result), args.month)
    result["sources"] = {
        "line": source_info(args.line_result),
        "qianliyan": source_info(args.qianliyan_result),
        "qikuan": source_info(args.qikuan_result),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output_file": str(output.resolve()), "province": result["province"],
                      "top_cities": result["top_cities"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
