#!/usr/bin/env python3
import argparse
import csv
import json
from datetime import datetime
from collections import defaultdict
from pathlib import Path


AUTOMATIC_HANDLER_RULE = "处理人包含‘自动’或等于‘系统管理员’"
METRICS = (
    ("互联网专线-开通-组网方案自动率", "开通", "组网方案"),
    ("互联网专线-移机-组网方案自动率", "变更", "组网方案"),
    ("互联网专线-移机-资源反馈自动率", "变更", "资源反馈"),
    ("互联网专线-拆机-组织资源释放自动率", "拆除", "组织资源释放"),
)
ORDER_ID_FIELD = "二级编排工单号"
REQUIRED_FIELDS = {
    ORDER_ID_FIELD, "环节名称", "地市", "业务类型", "工单类型", "处理人", "处理意见"
}


def is_automatic_handler(handler):
    value = (handler or "").strip()
    return "自动" in value or value == "系统管理员"


def read_rows(path):
    raw = Path(path).read_bytes()
    last_error = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            reader = csv.DictReader(raw.decode(encoding).splitlines())
            missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
            if missing:
                raise ValueError("CSV 缺少字段: " + "、".join(sorted(missing)))
            return [
                {key: (value or "").strip() for key, value in row.items()}
                for row in reader
            ]
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError("CSV 编码无法识别，应为 UTF-8 或 GB18030") from last_error


def make_summary(numbers):
    denominator = numbers["denominator"]
    return {
        "自动工单数": numbers["automatic"],
        "目标环节工单数": denominator,
        "自动率": numbers["automatic"] / denominator if denominator else None,
        "缺失目标环节工单数": numbers["missing"],
    }


def calculate_metrics(input_path):
    rows = [row for row in read_rows(input_path) if row["业务类型"] == "互联网专线"]
    result = {
        "口径": {
            "维度": ORDER_ID_FIELD,
            "自动处理人规则": AUTOMATIC_HANDLER_RULE,
            "自动判定": "同一工单目标环节的全部记录均由自动处理人处理",
            "分母": "出现目标环节的去重工单数",
            "缺失环节": "单列，不计入分母",
            "移机映射": "源数据工单类型=变更",
        },
        "metrics": {},
        "audit": {
            "mixed_processing_orders": [],
            "missing_target_stage_orders": [],
            "city_conflict_orders": [],
        },
    }

    for label, order_type, target_stage in METRICS:
        orders = defaultdict(list)
        for row in rows:
            if row["工单类型"] == order_type:
                orders[row[ORDER_ID_FIELD]].append(row)

        provincial = {"automatic": 0, "denominator": 0, "missing": 0}
        cities = defaultdict(lambda: {"automatic": 0, "denominator": 0, "missing": 0})

        for order_id, order_rows in orders.items():
            city_values = sorted({row["地市"] for row in order_rows if row["地市"]})
            if len(city_values) != 1:
                result["audit"]["city_conflict_orders"].append(
                    {"指标": label, ORDER_ID_FIELD: order_id, "地市值": city_values}
                )
                continue

            city = city_values[0]
            target_rows = [row for row in order_rows if row["环节名称"] == target_stage]
            if not target_rows:
                cities[city]["missing"] += 1
                provincial["missing"] += 1
                result["audit"]["missing_target_stage_orders"].append(
                    {"指标": label, "地市": city, ORDER_ID_FIELD: order_id}
                )
                continue

            handlers = [row["处理人"] for row in target_rows]
            automatic = all(is_automatic_handler(handler) for handler in handlers)
            cities[city]["denominator"] += 1
            provincial["denominator"] += 1
            if automatic:
                cities[city]["automatic"] += 1
                provincial["automatic"] += 1
            elif any(is_automatic_handler(handler) for handler in handlers):
                result["audit"]["mixed_processing_orders"].append(
                    {"指标": label, "地市": city, ORDER_ID_FIELD: order_id}
                )

        result["metrics"][label] = {
            "全省": make_summary(provincial),
            "地市": {city: make_summary(cities[city]) for city in sorted(cities)},
        }

    result["opening_network_nonautomatic_reasons"] = calculate_opening_network_reasons(rows)

    return result


def calculate_opening_network_reasons(rows):
    orders = defaultdict(list)
    for row in rows:
        if row["工单类型"] == "开通" and row["环节名称"] == "组网方案":
            orders[row[ORDER_ID_FIELD]].append(row)

    province = {"nonautomatic": 0, "engineering": 0, "blank": 0}
    cities = defaultdict(lambda: {"nonautomatic": 0, "engineering": 0, "blank": 0})
    engineering_orders = []
    blank_orders = []
    city_conflict_orders = []

    for order_id, target_rows in orders.items():
        city_values = sorted({row["地市"] for row in target_rows if row["地市"]})
        if len(city_values) != 1:
            city_conflict_orders.append({ORDER_ID_FIELD: order_id, "地市值": city_values})
            continue
        if all(is_automatic_handler(row["处理人"]) for row in target_rows):
            continue

        city = city_values[0]
        manual_rows = [row for row in target_rows if not is_automatic_handler(row["处理人"])]
        opinions = [row["处理意见"] for row in manual_rows]
        has_engineering = any("工程施工" in opinion for opinion in opinions)
        has_blank = any(not opinion for opinion in opinions)

        province["nonautomatic"] += 1
        cities[city]["nonautomatic"] += 1
        if has_engineering:
            province["engineering"] += 1
            cities[city]["engineering"] += 1
            engineering_orders.append({"地市": city, ORDER_ID_FIELD: order_id})
        if has_blank:
            province["blank"] += 1
            cities[city]["blank"] += 1
            blank_orders.append({"地市": city, ORDER_ID_FIELD: order_id})

    def reason_summary(values):
        denominator = values["nonautomatic"]
        return {
            "非自动工单数": denominator,
            "工程施工工单数": values["engineering"],
            "工程施工占比": values["engineering"] / denominator if denominator else None,
            "空原因工单数": values["blank"],
            "空原因占比": values["blank"] / denominator if denominator else None,
        }

    city_results = {city: reason_summary(cities[city]) for city in sorted(cities)}
    top_three = sorted(
        (
            {"地市": city, **values}
            for city, values in city_results.items()
        ),
        key=lambda item: (-item["工程施工工单数"], item["地市"]),
    )[:3]
    return {
        "口径": {
            "范围": "业务类型=互联网专线、工单类型=开通、环节名称=组网方案",
            "非自动": "目标环节至少一条记录的处理人不满足自动处理人规则",
            "工程施工": "非自动处理记录的处理意见至少一条包含‘工程施工’",
            "空原因": "非自动处理记录的处理意见至少一条为空",
            "去重字段": ORDER_ID_FIELD,
        },
        "全省": reason_summary(province),
        "地市": city_results,
        "工程施工前三地市": top_three,
        "audit": {
            "工程施工工单": engineering_orders,
            "空原因工单": blank_orders,
            "地市冲突工单": city_conflict_orders,
        },
    }


def write_summary_csv(result, path):
    fields = [
        "指标", "范围", "自动工单数", "目标环节工单数", "自动率", "缺失目标环节工单数",
        "非自动工单数", "工程施工工单数", "工程施工占比", "空原因工单数", "空原因占比",
    ]
    with Path(path).open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for label, metric in result["metrics"].items():
            scopes = [("全省", metric["全省"])] + list(metric["地市"].items())
            for scope, values in scopes:
                rate = values["自动率"]
                writer.writerow({
                    "指标": label,
                    "范围": scope,
                    "自动工单数": values["自动工单数"],
                    "目标环节工单数": values["目标环节工单数"],
                    "自动率": "" if rate is None else "{:.2%}".format(rate),
                    "缺失目标环节工单数": values["缺失目标环节工单数"],
                })
        reasons = result["opening_network_nonautomatic_reasons"]
        scopes = [("全省", reasons["全省"])] + list(reasons["地市"].items())
        for scope, values in scopes:
            writer.writerow({
                "指标": "互联网专线-开通-组网方案非自动原因",
                "范围": scope,
                "非自动工单数": values["非自动工单数"],
                "工程施工工单数": values["工程施工工单数"],
                "工程施工占比": "" if values["工程施工占比"] is None else "{:.2%}".format(values["工程施工占比"]),
                "空原因工单数": values["空原因工单数"],
                "空原因占比": "" if values["空原因占比"] is None else "{:.2%}".format(values["空原因占比"]),
            })


def main():
    parser = argparse.ArgumentParser(description="按工单维度计算互联网专线各地市环节自动率")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--csv-output", type=Path)
    parser.add_argument('--month', required=True, help='月报归属月份 YYYY-MM，源文件必须是该期完结工单全集')
    args = parser.parse_args()

    result = calculate_metrics(args.input)
    if datetime.strptime(args.month, '%Y-%m').strftime('%Y-%m') != args.month:
        raise ValueError('月份格式必须为 YYYY-MM')
    result.update(schema_version='1.0', metric_set='internet_line_manual_automation', report_month=args.month,
                  sources=[{'path': str(args.input.resolve()), 'period_basis': '源文件指定完结工单周期，不按环节时间再次截断'}])
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.csv_output:
        args.csv_output.parent.mkdir(parents=True, exist_ok=True)
        write_summary_csv(result, args.csv_output)


if __name__ == "__main__":
    main()
