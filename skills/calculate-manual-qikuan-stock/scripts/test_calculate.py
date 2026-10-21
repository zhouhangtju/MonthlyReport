import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from calculate import (CITIES, VALUE, calculate, growth, periods, read_snapshot,
                       read_history_workbook, load_history, history_snapshot)
from calculate import update_history

HEADERS = ["日期", "地市", "县市", "产品带宽", "产品带宽", "接入技术", "产品分类", "校园属性", VALUE]


class Sheet:
    def __init__(self, rows):
        self.rows = rows

    def iter_rows(self, **kwargs):
        return iter([HEADERS, *self.rows])


class Book:
    sheetnames = ["202609"]

    def __init__(self, rows):
        self.rows = rows

    def __getitem__(self, key):
        return Sheet(self.rows)

    def close(self):
        pass


class CalculationTests(unittest.TestCase):
    def rows(self):
        return [["20260930", city, "县", "100", "100M", "FTTH", "小微宽带", "非校园", i]
                for i, city in enumerate(CITIES)]

    def read(self, rows):
        with patch("calculate.load_workbook", return_value=Book(rows)), patch.object(Path, "read_bytes", return_value=b"test"):
            return read_snapshot(Path("test.xlsx"), "2026-09")

    def test_filter_and_month_end(self):
        rows = self.rows()
        rows += [["20260929", "杭州", "县", "100", "100M", "FTTH", "小微宽带", "非校园", 999]]
        rows += [["20260930", "杭州", "县", "100", "100M", "FTTH", "家庭宽带", "非校园", 999]]
        snapshot = self.read(rows)
        self.assertEqual(sum(snapshot["counts"].values()), 55)
        self.assertEqual(snapshot["audit"]["selected_rows"], 11)

    def test_invalid_inputs(self):
        for value in (None, -1, 1.5, True, "=SUM(A1:A2)"):
            rows = self.rows()
            rows[0][-1] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.read(rows)
        with self.assertRaises(ValueError):
            self.read(self.rows()[:-1])
        with self.assertRaises(ValueError):
            self.read(self.rows() + [self.rows()[0]])
        rows = self.rows()
        rows[0][1] = "未知"
        with self.assertRaises(ValueError):
            self.read(rows)

    def test_periods_and_rates(self):
        self.assertEqual(periods("2026-01")["previous"], "2025-12")
        self.assertEqual(periods("2026-09")["year_ago"], "2025-09")
        self.assertEqual(growth(90, 100), (-0.1, None))
        self.assertEqual(growth(100, 100), (0, None))
        self.assertIsNone(growth(100, 0)[0])
        self.assertIsNone(growth(100, None)[0])
        current = {"counts": dict.fromkeys(CITIES, 100), "audit": {}}
        previous = {"counts": dict.fromkeys(CITIES, 50), "audit": {}}
        previous["counts"]["杭州"] = 100
        result = calculate("2026-09", {"current": current, "previous": previous, "year_ago": None})
        self.assertAlmostEqual(result["province"]["mom"], (1100 - 600) / 600)
        self.assertEqual(result["missing_periods"], ["2025-09"])
        self.assertIsNone(result["province"]["yoy"])

    def test_saved_history_supplies_yoy_and_mom(self):
        path = Path(__file__).resolve().parents[1] / "assets/qikuan_stock_history.json"
        history = load_history(path)
        self.assertEqual(history["audit"]["first_month"], "2022-01")
        self.assertEqual(history["audit"]["last_month"], "2026-09")
        self.assertEqual(history["audit"]["month_count"], 57)
        self.assertEqual(history_snapshot(history, "2026-08")["counts"]["杭州"], 469872)
        self.assertEqual(history_snapshot(history, "2025-09")["counts"]["杭州"], 424937)

    def test_history_sheet_blocks_are_validated(self):
        source = Path("/Users/hzhou/Desktop/企宽装机投诉存量.xlsx")
        if not source.exists():
            self.skipTest("历史台账样本不存在")
        history = read_history_workbook(source)
        self.assertEqual(history["months"]["2026-09"]["province"], 2871396)
        self.assertEqual(history["months"]["2025-09"]["province"], 2657715)
        self.assertEqual(history["months"]["2026-08"]["province"], 2853960)

    def test_calculated_month_updates_history(self):
        counts = {city: index + 1 for index, city in enumerate(CITIES)}
        snapshot = {"counts": counts, "audit": {"source_file": "/tmp/month.xlsx",
                    "sha256": "abc", "sheet": "202610", "snapshot_date": "20261031",
                    "selected_rows": 11}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            history = {"months": {}, "audit": None}
            self.assertEqual(update_history(path, history, "2026-10", snapshot), "新增记录")
            saved = json.loads(path.read_text())
            self.assertEqual(saved["months"]["2026-10"]["province"], sum(counts.values()))
            self.assertEqual(saved["month_sources"]["2026-10"]["sheet"], "202610")
            loaded = load_history(path)
            self.assertEqual(loaded["months"]["2026-10"]["counts"], counts)
            self.assertEqual(update_history(path, loaded, "2026-10", snapshot), "确认无变化")


if __name__ == "__main__":
    unittest.main()
