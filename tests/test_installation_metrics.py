from __future__ import annotations

import json
import unittest

from metrics.installation.commercial_customer_install_fault_rate import calculate as calculate_commercial
from metrics.installation.dedicated_line_install_fault_rate import calculate as calculate_line
from metrics.installation.qikuan_install_fault_rate import calculate as calculate_qikuan


class InstallationMetricsTest(unittest.TestCase):
    def test_qikuan_counts_install_orders_with_later_complaint(self):
        installs = [
            {"_source_record_id": "i1", "工单id": "i1", "宽带账号": " A.0 ", "派单时间": "2026-08-01 10:00:00", "地市": "杭州市"},
            {"_source_record_id": "i2", "工单id": "i2", "宽带账号": "A", "派单时间": "2026-08-10 10:00:00", "地市": "杭州"},
            {"_source_record_id": "i3", "工单id": "i3", "宽带账号": "B", "派单时间": "2026-08-10 10:00:00", "地市": "宁波"},
        ]
        complaints = [{"宽带账号": "a", "派单时间": "2026-08-20 10:00:00"}]
        report = calculate_qikuan(installs, complaints, "2026-08-01", "2026-08-31")
        self.assertEqual(report["results"][0]["numerator"], 2)
        self.assertEqual(report["results"][0]["denominator"], 3)
        hangzhou = next(item for item in report["results"] if item["dimension"].get("city") == "杭州")
        self.assertEqual((hangzhou["numerator"], hangzhou["denominator"]), (2, 2))

    def test_line_uses_unique_account_time_and_matching_city(self):
        installs = [
            {"_source_record_id": "o1", "订单状态": "已完成", "订单类型": "开通", "业务类型": "互联网专线", "产品实例编号": "e551", "订单创建时间": "2026-08-01 10:00:00", "地市": "杭州市"},
            {"_source_record_id": "o2", "订单状态": "已完成", "订单类型": "开通", "业务类型": "互联网专线", "产品实例编号": "e551", "订单创建时间": "2026-08-02 10:00:00", "地市": "杭州市"},
            {"_source_record_id": "o3", "订单状态": "已完成", "订单类型": "开通", "业务类型": "互联网专线", "产品实例编号": "e552", "订单创建时间": "2026-08-02 10:00:00", "地市": "宁波市"},
            {"_source_record_id": "o4", "订单状态": "已完成", "订单类型": "开通", "业务类型": "互联网专线", "产品实例编号": "e551", "订单创建时间": "2026-08-02 10:00:00", "地市": "宁波市"},
        ]
        complaints = [
            {"计费号码": "E551", "派单时间": "2026-08-03 10:00:00", "所属地市": "杭州"},
            {"计费号码": "E552", "派单时间": "2026-08-03 10:00:00", "所属地市": "杭州"},
        ]
        report = calculate_line(installs, complaints, "2026-08-01", "2026-08-31")
        self.assertEqual(report["results"][0]["numerator"], 1)
        self.assertEqual(report["results"][0]["denominator"], 2)
        ningbo = next(item for item in report["results"] if item["dimension"].get("city") == "宁波")
        self.assertEqual((ningbo["numerator"], ningbo["denominator"]), (0, 2))

    def test_commercial_customer_sums_numerators_and_denominators(self):
        dimension = json.dumps({"scope": "全省"}, ensure_ascii=False, sort_keys=True)
        components = {
            "qikuan_install_fault_rate": [{"dimension_type": "province", "dimension_value": dimension, "numerator": 20, "denominator": 100}],
            "dedicated_line_install_fault_rate": [{"dimension_type": "province", "dimension_value": dimension, "numerator": 5, "denominator": 50}],
        }
        report = calculate_commercial(components, "2026-08-01", "2026-08-31")
        total = report["results"][0]
        self.assertEqual(total["numerator"], 25)
        self.assertEqual(total["denominator"], 150)
        self.assertAlmostEqual(total["metric_value"], 25 / 150)
        self.assertNotAlmostEqual(total["metric_value"], (0.2 + 0.1) / 2)


if __name__ == "__main__": unittest.main()
