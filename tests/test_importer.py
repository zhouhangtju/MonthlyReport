"""Importer checks use isolated MySQL databases and complete source layouts."""
import unittest
import test_split_raw_tables_integration as fixed_tests
from storage.database import connect

class ImporterTest(unittest.TestCase):
    setUp = fixed_tests.FixedRawTablesTest.setUp
    drop_database = fixed_tests.FixedRawTablesTest.drop_database
    write = fixed_tests.FixedRawTablesTest.write
    put = fixed_tests.FixedRawTablesTest.put

    def test_import_is_idempotent_and_keeps_changed_versions(self):
        code = "youshu_complaint"
        rows = [{"工单号":"A1", "工单状态":"处理中"}, {"工单号":"A2", "工单状态":"已完成"}]
        self.assertEqual(self.put(code, rows)["inserted"], 2)
        self.assertEqual(self.put(code, rows)["unchanged"], 2)
        rows[0]["工单状态"] = "已完成"
        result = self.put(code, rows)
        self.assertEqual((result["updated"],result["unchanged"]),(1,1))
        with connect(None) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM youshu_complaint_version").fetchone()["n"],3)

    def test_missing_business_key_rejects_batch(self):
        with self.assertRaises(ValueError):
            self.put("youshu_complaint", [{"工单号":"", "工单状态":"已完成"}])
        with connect(None) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM youshu_complaint").fetchone()["n"],0)
            self.assertEqual(connection.execute("SELECT status FROM etl_run").fetchone()["status"],"failed")

    def test_orchestration_datasets_are_stored_without_ods(self):
        self.put("orch_opening", [{"订单号":"O1", "订单结束时间":"2026-08-02 10:00:00"}])
        self.put("orch_install", [{"订单号":"I1", "首次派单时间":"2026-08-01 09:00:00"}])
        with connect(None) as connection:
            self.assertEqual(connection.execute("SELECT `订单号` FROM orch_opening").fetchone()["订单号"],"O1")
            self.assertEqual(connection.execute("SELECT `订单号` FROM orch_install").fetchone()["订单号"],"I1")

if __name__ == "__main__": unittest.main()
