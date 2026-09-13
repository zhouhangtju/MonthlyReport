from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from metrics.opening.dedicated_line_metrics import calculate, save_results
from storage.database import connect, has_successful_coverage, initialize
from storage.prune_orchestration_opening import preview, prune


class OrchestrationRetentionTest(unittest.TestCase):
    def test_prune_requires_summary_then_archives_and_invalidates_coverage(self):
        row = {
            "订单号": "OLD-1",
            "结束时间": "2025-08-20 10:00:00",
            "订单状态": "已完成",
            "业务类型": "互联网专线",
            "产品名称": "互联网专线套餐",
            "订单类型": "开通",
            "地市": "杭州市",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "quality.db"
            initialize(database)
            with connect(database) as connection:
                connection.execute(
                    """INSERT INTO etl_run (
                           run_id, dataset_code, source_system, source_file, file_sha256,
                           period_start, period_end, started_at, finished_at, status,
                           rows_read, rows_inserted, rows_failed
                       ) VALUES ('etl_old', 'orch_opening', '编排', 'old.xlsx', 'hash',
                           '2025-08-01', '2025-08-31', '2025-09-01T00:00:00+00:00',
                           '2025-09-01T00:01:00+00:00', 'success', 1, 1, 0)"""
                )
                payload = json.dumps(row, ensure_ascii=False)
                connection.execute(
                    """INSERT INTO raw_source_record (
                           dataset_code, source_system, source_record_id, source_data,
                           row_hash, first_run_id, last_run_id, first_seen_at, last_seen_at
                       ) VALUES ('orch_opening', '编排', 'OLD-1', ?, 'hash',
                           'etl_old', 'etl_old', '2025-09-01', '2025-09-01')""",
                    (payload,),
                )
            # initialize() 在指标保存时会将 raw 记录投影到 ods_orch_opening。
            report = calculate([row], "2025-08", "2025-08")
            save_results(database, report, ["etl_old"])
            self.assertEqual(preview(database, "2025-09")["rows"], 1)
            result = prune(database, "2025-09", root / "archive")
            self.assertTrue(Path(result["archive_file"]).is_file())
            with connect(database) as connection:
                remaining = connection.execute(
                    "SELECT COUNT(*) AS n FROM ods_orch_opening"
                ).fetchone()["n"]
            self.assertEqual(remaining, 0)
            self.assertFalse(
                has_successful_coverage(database, "orch_opening", "2025-08-01", "2025-08-31")
            )


if __name__ == "__main__":
    unittest.main()
