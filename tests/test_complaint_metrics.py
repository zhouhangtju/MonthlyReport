from __future__ import annotations

import unittest

from metrics.complaint.repeat_rate import LINE, QLY, calculate


def row(order: str, customer: str, category: str, assigned: str, **extra):
    data = {
        "_source_record_id": order,
        "工单号": order,
        "计费号码": customer,
        "手机号码": "",
        "业务类别": category,
        "派单时间": assigned,
        "客服流水号": f"flow-{order}",
        "工单状态": "正常结束",
        "工单主题": "网络故障",
        "所属地市": "杭州市",
    }
    data.update(extra)
    return data


class ComplaintMetricsTest(unittest.TestCase):
    def test_line_uses_full_path_and_repeat_key_numerator(self):
        path_a = "政企市场->通信连接->专线专网->互联网专线->中断"
        path_b = "政企市场->通信连接->专线专网->互联网专线->丢包"
        rows = [
            row("1", "E551", path_a, "2026-08-01 08:00:00"),
            row("2", "e551", path_a, "2026-08-01 08:30:00"),  # 1小时内后单剔除
            row("3", "E551", path_a, "2026-08-02 08:00:00"),
            row("4", "E551", path_b, "2026-08-03 08:00:00"),
            row("5", "E551", path_b, "2026-08-04 08:00:00"),
        ]
        report = calculate(rows, "2026-08-01", "2026-08-31", LINE)
        province = report["results"][0]
        self.assertEqual((province["numerator"], province["denominator"]), (2, 1))
        self.assertEqual(report["quality"]["duplicate_dispatch_removed_rows"], 1)

    def test_line_specific_return_rule_only_excludes_numerator(self):
        category = "政企市场->通信连接->专线专网->互联网专线"
        rows = [
            row("1", "E551", category, "2026-08-01 08:00:00"),
            row("2", "E551", category, "2026-08-03 08:00:00", **{"退单原因": "客户原因", "最后处理班组": "政企头部客户重保组"}),
            row("3", "E552", category, "2026-08-01 08:00:00", **{"退单原因": "售中催单", "最后处理班组": "政企头部客户重保组"}),
            row("4", "E552", category, "2026-08-03 08:00:00"),
        ]
        report = calculate(rows, "2026-08-01", "2026-08-31", LINE)
        self.assertEqual((report["results"][0]["numerator"], report["results"][0]["denominator"]), (1, 2))
        self.assertEqual(report["quality"]["numerator_only_excluded_rows"], 1)

    def test_qianliyan_uses_phone_fallback_and_24_hour_rule(self):
        category = "政企市场->视频监控->千里眼"
        rows = [
            row("1", "", category, "2026-08-01 08:00:00", **{"手机号码": "13800000000"}),
            row("2", "", category, "2026-08-02 08:00:00", **{"手机号码": "13800000000"}),  # 正好24小时，剔除
            row("3", "", category, "2026-08-04 08:00:00", **{"手机号码": "13800000000"}),
            row("4", "E552", category, "2026-08-01 08:00:00", **{"最后处理班组": "创新院"}),
            row("5", "E552", category, "2026-08-04 08:00:00"),
        ]
        report = calculate(rows, "2026-08-01", "2026-08-31", QLY)
        self.assertEqual((report["results"][0]["numerator"], report["results"][0]["denominator"]), (1, 2))
        self.assertEqual(report["quality"]["duplicate_dispatch_removed_rows"], 1)
        self.assertEqual(report["quality"]["numerator_only_excluded_rows"], 1)

    def test_common_filters_require_flow_completed_and_exclude_auth_reset(self):
        category = "政企市场->视频监控->千里眼"
        rows = [
            row("1", "E551", category, "2026-08-01 08:00:00", **{"客服流水号": ""}),
            row("2", "E552", category, "2026-08-01 08:00:00", **{"工单状态": "处理中"}),
            row("3", "E553", category, "2026-08-01 08:00:00", **{"工单主题": "重置鉴权码"}),
        ]
        report = calculate(rows, "2026-08-01", "2026-08-31", QLY)
        self.assertEqual(report["results"][0]["denominator"], 0)
        self.assertEqual(report["quality"]["excluded_rows"], 3)


if __name__ == "__main__":
    unittest.main()

