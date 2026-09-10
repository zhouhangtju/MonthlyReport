from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from metrics.opening.withdrawal import calculate, save_results
from storage.database import connect


def order(order_id: str, status: str, *, end_time: str = "2026-08-15 10:00:00", business_type: str = "互联网专线", title: str = "正式客户开通单", city: str = "杭州市") -> dict[str, object]:
    return {
        "_source_record_id": order_id,
        "工单号": order_id,
        "工单主题": title,
        "工单数据来源": "二编",
        "工单类型": "开通",
        "业务类型": business_type,
        "工单状态": status,
        "工单结束时间": end_time,
        "地市": city,
    }


class WithdrawalMetricsTest(unittest.TestCase):
    def test_filters_scope_tests_and_keeps_latest_order_state(self):
        rows = [
            order("A", "已完成", end_time="2026-08-10 10:00:00"),
            order("A", "已撤单", end_time="2026-08-11 10:00:00"),
            order("B", "已驳回"),
            order("C", "失败"),
            order("T", "已撤单", title="测试客户开通单"),
            order("V", "已撤单", business_type="行业视频行业版平台基础"),
            order("OLD", "已撤单", end_time="2026-07-31 23:59:59"),
        ]
        report = calculate(rows, "2026-08-01", "2026-08-31")
        province = report["results"][0]
        self.assertEqual(province["numerator"], 2)
        self.assertEqual(province["denominator"], 3)
        self.assertAlmostEqual(province["metric_value"], 2 / 3)
        self.assertEqual(report["quality"]["excluded_test_orders"], 1)
        self.assertNotIn("失败", report["rules"]["withdrawal_statuses"])

    def test_all_business_types_reproduces_unfiltered_scope(self):
        rows = [order("A", "已完成"), order("V", "已撤单", business_type="行业视频行业版平台基础")]
        report = calculate(rows, "2026-08-01", "2026-08-31", all_business_types=True)
        self.assertEqual(report["results"][0]["numerator"], 1)
        self.assertEqual(report["results"][0]["denominator"], 2)

    def test_saves_results_and_audit_details(self):
        report = calculate([order("A", "已完成"), order("B", "已撤单")], "2026-08-01", "2026-08-31")
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
