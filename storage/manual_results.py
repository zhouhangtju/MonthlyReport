"""按指标与报告月份保存手工统计结果。"""
import json
import re


def save_manual_result(result):
    from storage.database import connect

    month = result.get("report_month")
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month or ""):
        raise ValueError("入库需要有效的 --month YYYY-MM")
    counties = result.get("counties")
    if counties is not None:
        keys = [(row["city"], row["county"]) for row in counties]
        if len(keys) != len(set(keys)):
            raise ValueError("区县结果包含重复的地市、区县组合")
        if result["metric_set"] == "dedicated_line_withdrawal_reasons_by_city":
            if sum(row["sample_count"] for row in counties) != result["summary"]["reason_total_count"]:
                raise ValueError("区县原因样本合计与全省不一致")
        elif result["metric_set"] == "qikuan_withdrawal_rate_by_city":
            summary = result["ppt_overlay"]["qikuanWithdrawal"]
            if sum(row["accepted_count"] for row in counties) != summary["acceptedTotal"]:
                raise ValueError("区县受理数量与全省不一致")
            if sum(row["return_count"] for row in counties) != summary["withdrawalTotal"]:
                raise ValueError("区县退单数量与全省不一致")
        elif result["metric_set"] == "qikuan_withdrawal_summary":
            summary = result["ppt_overlay"]["qikuanWithdrawal"]
            for field, total in [("accepted_count", "acceptedTotal"), ("return_count", "returnTotal"),
                                 ("cancellation_count", "cancellationTotal"), ("withdrawal_count", "withdrawalTotal")]:
                if sum(row[field] for row in counties) != summary[total]:
                    raise ValueError(f"区县 {field} 合计与全省不一致")
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
    with connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS manual_metric_result (
                metric_set VARCHAR(128) NOT NULL,
                report_month CHAR(7) NOT NULL,
                result_json JSON NOT NULL,
                PRIMARY KEY (metric_set, report_month)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        connection.execute("""
            INSERT INTO manual_metric_result (metric_set, report_month, result_json)
            VALUES (?, ?, ?) ON DUPLICATE KEY UPDATE result_json = ?
        """, (result["metric_set"], month, payload, payload))
