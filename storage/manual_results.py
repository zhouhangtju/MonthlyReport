"""按指标与报告月份保存手工统计结果。"""
import json
import re


def save_manual_result(result):
    from storage.database import connect

    month = result.get("report_month")
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month or ""):
        raise ValueError("入库需要有效的 --month YYYY-MM")
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
