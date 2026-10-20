import unittest
from pathlib import Path
from unittest.mock import patch

from calculate import CITIES, VALUE, calculate, growth, periods, read_snapshot

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


if __name__ == "__main__":
    unittest.main()
