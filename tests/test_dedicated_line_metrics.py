from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from metrics.opening.dedicated_line_metrics import (
    calculate,
    load_monthly_summaries,
    save_results,
)
from storage.database import connect


def opening(order: str, month: str, *, product: str = "互联网专线套餐", city: str = "杭州市", automatic: bool = False) -> dict[str, object]:
    row = {
        "订单号": order,
        "订单创建时间": f"{month}-15 10:00:00",
        "结束时间": f"{month}-20 10:00:00",
        "订单状态": "已完成",
        "业务类型": "互联网专线",
        "产品名称": product,
        "订单类型": "开通",
        "地市": city,
        "受理人": "人工",
        "方案设计处理人": "人工",
        "资源分配受理人": "人工",
        "配置激活处理人": "人工",
        "开通结果审核处理人": "人工",
        "报结人": "人工",
    }
    if automatic:
        row.update({
            "受理人": "系统自动",
            "方案设计处理人": "系统自动",
            "资源分配受理人": "自动处理",
            "配置激活处理人": "系统自动",
            "开通结果审核处理人": "系统自动",
            "报结人": "自动处理",
        })
    return row


class DedicatedLineMetricsTest(unittest.TestCase):
    def test_counts_deduplicate_orders_and_calculates_comparisons(self):
        rows = [
            opening("A", "2026-08", automatic=True),
            opening("A", "2026-08", automatic=True),
            opening("B", "2026-08"),
            opening("C", "2026-07"),
            opening("D", "2025-08"),
        ]
        report = calculate(rows, "2026-07", "2026-08")
        results = report["results"]
        current = next(item for item in results if item["metric_code"] == "internet_opening_orders" and item["dimension"] == {"month": "2026-08"})
        mom = next(item for item in results if item["metric_code"] == "internet_opening_orders_mom")
        yoy = next(item for item in results if item["metric_code"] == "internet_opening_orders_yoy")
        stage = next(item for item in results if item["metric_code"] == "internet_opening_automation_rate" and item["dimension"].get("stage") == "受理")
        self.assertEqual(current["metric_value"], 2)
        self.assertEqual(mom["metric_value"], 1.0)
        self.assertEqual(yoy["metric_value"], 1.0)
        self.assertEqual(stage["numerator"], 1)
        self.assertEqual(stage["denominator"], 2)
        self.assertEqual(stage["metric_value"], 0.5)
        package_summary = next(
            item for item in results
            if item["metric_code"] == "internet_product_average_monthly_orders"
            and item["dimension"].get("product") == "互联网专线套餐"
        )
        self.assertEqual(package_summary["numerator"], 3)
        self.assertEqual(package_summary["denominator"], 12)
        self.assertAlmostEqual(package_summary["metric_value"], 3 / 12)

    def test_product_yoy_and_city_totals_match_workbook_dimensions(self):
        current_mpls = opening("M1", "2026-08", product="地区内MPLSVPN套餐", city="宁波市")
        current_mpls["业务类型"] = "MPLS-VPN专线"
        previous_mpls = opening("M0", "2025-08", product="地区内MPLSVPN套餐", city="宁波市")
        previous_mpls["业务类型"] = "MPLS-VPN专线"
        report = calculate([current_mpls, previous_mpls], "2025-08", "2026-08")
        product_yoy = next(
            item for item in report["results"]
            if item["metric_code"] == "mpls_product_opening_yoy"
            and item["dimension"]["product"] == "地区内MPLSVPN套餐"
        )
        city_total = next(
            item for item in report["results"]
            if item["metric_code"] == "mpls_opening_orders"
            and item["dimension_type"] == "month_city"
            and item["dimension"]["city"] == "宁波市"
        )
        self.assertEqual(product_yoy["numerator"], 0)
        self.assertEqual(product_yoy["metric_value"], 0)
        self.assertEqual(city_total["metric_value"], 1)

    def test_results_are_written_to_metric_tables(self):
        report = calculate([opening("A", "2026-08")], "2026-08", "2026-08")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"
            run_id = save_results(database, report, ["etl_source"])
            with connect(database) as connection:
                run = connection.execute("SELECT * FROM metric_run WHERE metric_run_id=?", (run_id,)).fetchone()
                count = connection.execute("SELECT COUNT(*) AS value FROM ads_metric_result WHERE metric_run_id=?", (run_id,)).fetchone()["value"]
            self.assertEqual(run["status"], "success")
            self.assertEqual(count, len(report["results"]))

    def test_monthly_summary_replaces_deleted_historical_detail(self):
        historical = calculate([opening("OLD", "2025-08")], "2025-08", "2025-08")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"
            save_results(database, historical, ["etl_old"])
            summaries = load_monthly_summaries(database, "2025-08", "2025-08")
            report = calculate(
                [opening("NOW", "2026-08")],
                "2026-08",
                "2026-08",
                summaries,
            )
            yoy = next(
                item for item in report["results"]
                if item["metric_code"] == "internet_opening_orders_yoy"
            )
            self.assertEqual(yoy["denominator"], 1)
            self.assertEqual(yoy["metric_value"], 0)


if __name__ == "__main__":
    unittest.main()
