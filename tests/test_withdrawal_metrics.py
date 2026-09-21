from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from metrics.opening.withdrawal import calculate, save_results
from storage.database import connect


def order(order_id: str, status: str, *, end_time: str = "2026-08-15 10:00:00", dispatch_time: str | None = "2026-08-01 09:00:00", business_type: str = "互联网专线", package_type: str = "省内标准套餐", title: str = "正式客户开通单", city: str = "杭州市") -> dict[str, object]:
    return {
        "_source_record_id": order_id,
        "工单号": order_id,
        "工单主题": title,
        "工单数据来源": "二编",
        "工单类型": "开通",
        "业务类型": business_type,
        "业务套餐类型": package_type,
        "工单状态": status,
        "工单结束时间": end_time,
        "派单时间": dispatch_time,
        "地市": city,
    }


class WithdrawalMetricsTest(unittest.TestCase):
    def test_filters_custom_period_scope_and_tests_without_secondary_deduplication(self):
        rows = [
            order("A", "已完成", end_time="2026-08-10 10:00:00"),
            order("A", "已撤单", end_time="2026-08-11 10:00:00"),
            order("B", "已驳回"),
            order("C", "失败"),
            order("T", "已撤单", title="测试客户开通单"),
            order("V", "已撤单", business_type="行业视频行业版平台基础"),
            order("OLD", "已撤单", end_time="2026-07-25 23:59:59"),
        ]
        report = calculate(rows, "2026-07-26", "2026-08-25")
        province = report["results"][0]
        self.assertEqual(province["numerator"], 2)
        self.assertEqual(province["denominator"], 4)
        self.assertAlmostEqual(province["metric_value"], 1 / 2)
        self.assertEqual(report["quality"]["excluded_test_orders"], 1)
        self.assertNotIn("失败", report["rules"]["withdrawal_statuses"])

    def test_counts_current_month_completions_and_splits_by_dispatch_month(self):
        rows = [
            order("CURRENT", "已完成", dispatch_time="2026-08-03 09:00:00"),
            order("PREVIOUS", "已完成", dispatch_time="2026-07-31 23:59:59"),
            order("MISSING", "已完成", dispatch_time=None),
            order("INVALID", "已完成", end_time="2026-08-10 10:00:00", dispatch_time="2026-08-11 09:00:00"),
            order("PERIOD_START", "已完成", end_time="2026-07-26 00:00:00", dispatch_time="2026-07-01 09:00:00"),
            order("BEFORE_PERIOD", "已完成", end_time="2026-07-25 23:59:59", dispatch_time="2026-07-01 09:00:00"),
            order("PERIOD_END", "已完成", end_time="2026-08-25 23:59:59", dispatch_time="2026-08-25 09:00:00"),
            order("AFTER_PERIOD", "已完成", end_time="2026-08-26 00:00:00", dispatch_time="2026-08-25 09:00:00"),
            order("WITHDRAWN", "已撤单", dispatch_time="2026-08-02 09:00:00"),
        ]
        report = calculate(rows, "2026-07-26", "2026-08-25")
        values = {item["metric_code"]: item["metric_value"] for item in report["results"]
                  if item["dimension_type"] == "province"}

        self.assertEqual(values["dedicated_line_opening_completed_count"], 6)
        self.assertEqual(values["dedicated_line_opening_completed_current_accepted_count"], 2)
        self.assertEqual(values["dedicated_line_opening_completed_previous_accepted_count"], 2)
        self.assertEqual(values["dedicated_line_opening_completed_unknown_accepted_count"], 2)
        self.assertEqual(report["quality"]["completed_orders"], 6)
        self.assertEqual(
            report["quality"]["completed_current_accepted"]
            + report["quality"]["completed_previous_accepted"]
            + report["quality"]["completed_unknown_accepted"],
            report["quality"]["completed_orders"],
        )

    def test_withdrawal_rate_keeps_all_filtered_unique_orders_in_denominator(self):
        rows = [order("DONE", "已完成"), order("CANCELLED", "已撤单"), order("FAILED", "失败")]
        province = calculate(rows, "2026-07-26", "2026-08-25")["results"][0]
        self.assertEqual(province["numerator"], 1)
        self.assertEqual(province["denominator"], 3)
        self.assertAlmostEqual(province["metric_value"], 1 / 3)

    def test_fixed_business_exclusions_apply_before_calculation(self):
        rows = [
            order("INTERNET", "已完成"),
            order("OTHER", "已撤单", business_type="普通专线业务"),
            order("VIDEO1", "已撤单", business_type="行业视频行业版平台基础"),
            order("VIDEO2", "已撤单", business_type="行业视频-行业版"),
            order("5G", "已撤单", business_type="5G双域专网"),
            order("PROVINCE", "已撤单", business_type="跨省互联网专线"),
            order("COUNTRY", "已撤单", business_type="国际跨国专线"),
            order("PACKAGE", "已撤单", business_type="普通专线业务", package_type="跨省精品套餐"),
        ]
        report = calculate(rows, "2026-07-26", "2026-08-25", all_business_types=True)
        self.assertEqual(report["results"][0]["numerator"], 1)
        self.assertEqual(report["results"][0]["denominator"], 2)
        self.assertEqual(report["quality"]["excluded_business_rows"], 6)
        self.assertEqual(len(report["details"]["excluded_business"]), 6)
        self.assertTrue(all(row["_business_exclusion_reason"] for row in report["details"]["excluded_business"]))

    def test_saves_results_and_audit_details(self):
        report = calculate([order("A", "已完成"), order("B", "已撤单")], "2026-07-26", "2026-08-25")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "quality.db"
            run_id = save_results(database, report, ["etl1"])
            with connect(database) as connection:
                run = connection.execute("SELECT status FROM metric_run WHERE metric_run_id=?", (run_id,)).fetchone()
                roles = dict(connection.execute("SELECT detail_role, COUNT(*) AS value FROM ads_metric_detail WHERE metric_run_id=? GROUP BY detail_role", (run_id,)).fetchall())
            self.assertEqual(run["status"], "success")
            self.assertEqual(roles["denominator"], 2)
            self.assertEqual(roles["numerator"], 1)


if __name__ == "__main__":
    unittest.main()
