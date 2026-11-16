"""终端利旧页面仅读取已计算入库结果，不读取原始或人工文件。"""
import json
from storage.database import connect


def read_terminal_reuse(month):
    with connect() as c:
        exists = c.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='terminal_reuse_result_audit'").fetchone()
        if not exists:
            return None
        row = c.execute('''SELECT a.result_json FROM terminal_reuse_result_audit a
            JOIN metric_run m ON m.metric_run_id COLLATE utf8mb4_unicode_ci=a.metric_run_id COLLATE utf8mb4_unicode_ci
            WHERE a.report_month=? AND m.status='success' AND m.metric_code='terminal_reuse'
            ORDER BY m.started_at DESC,m.metric_run_id DESC LIMIT 1''', (month,)).fetchone()
    if row is None:
        return None
    value=row['result_json']
    return json.loads(value) if isinstance(value,str) else value


def read_terminal_reuse_cumulative(month):
    with connect() as c:
        if not c.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='terminal_reuse_cumulative_audit'").fetchone():
            return None
        row=c.execute("SELECT a.result_json FROM terminal_reuse_cumulative_audit a JOIN metric_run m ON m.metric_run_id COLLATE utf8mb4_unicode_ci=a.metric_run_id COLLATE utf8mb4_unicode_ci WHERE a.report_month=? AND m.status='success' AND m.metric_code='terminal_reuse_cumulative' ORDER BY m.started_at DESC,m.metric_run_id DESC LIMIT 1",(month,)).fetchone()
    if row is None:return None
    return json.loads(row['result_json']) if isinstance(row['result_json'],str) else row['result_json']
