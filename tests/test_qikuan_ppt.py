import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from reporting.qikuan_business import build_qikuan, CITIES, OPENING_KEYS, read_document
from reporting.build_internet_line_ppt import SECTION_SLIDE_MAP


class QikuanPptTest(unittest.TestCase):
    def test_actual_stock_and_unavailable_opening(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "outputs/manual_metrics/企宽存量_2026-09.json"
        if not source.exists():
            self.skipTest("Local September source result not installed")
        result = build_qikuan("2026-09", None, stock_path=source)
        self.assertEqual(result["stock"]["province"]["current"], 2871396)
        self.assertIsNone(result["stock"]["province"]["yoy"])
        self.assertIsNone(result["opening"]["province"]["current_month"])
        self.assertEqual([r["city"] for r in result["stock"]["cities"]], CITIES)
        self.assertTrue(all(r["filled_value"] is None for r in result["missing"]))

    def test_stored_database_values_are_mapped_without_zero_filling(self):
        db = Mock()
        db.runs = {"qikuan_opening_metrics": {"metric_run_id": "test"}}
        def find(owner, code, kind, **dims):
            key = code.removeprefix("qikuan_opening_")
            value = {"current_month": 9, "previous_month": 10, "current_ytd": 90,
                     "previous_ytd": 100, "yoy": -.1, "ytd_yoy": -.1}[key]
            if kind == "province" and key not in ("yoy", "ytd_yoy"):
                value *= 11
            return {"metric_value": value}
        db.find.side_effect = find
        result = build_qikuan("2026-09", None, db)
        self.assertEqual(result["opening"]["province"]["current_month"], 99)
        self.assertEqual(result["opening"]["province"]["yoy"], -.1)
        self.assertIsNone(result["stock"]["province"]["current"])
        self.assertEqual(db.find.call_count, 72)

    def test_json_rejects_wrong_month_and_bad_totals(self):
        rows = [{"city": c, **dict.fromkeys(OPENING_KEYS, None)} for c in CITIES]
        for row in rows:
            row["current_month"] = 1
        document = {"metric_code": "qikuan_opening_metrics", "month": "2026-09",
                    "cities": rows, "province": {"city": "全省", **dict.fromkeys(OPENING_KEYS, None)}}
        document["province"]["current_month"] = 11
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "opening.json"
            path.write_text(json.dumps(document))
            self.assertEqual(read_document(path, "2026-09", True)["province"]["current_month"], 11)
            with self.assertRaises(ValueError):
                read_document(path, "2026-08", True)
            bad = copy.deepcopy(document)
            bad["province"]["current_month"] = 12
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                read_document(path, "2026-09", True)

    def test_section_pages_shift_after_insert(self):
        self.assertEqual(SECTION_SLIDE_MAP["业务发展情况"], list(range(1, 8)))
        self.assertEqual(SECTION_SLIDE_MAP["企宽业务"], [7])
        self.assertEqual(SECTION_SLIDE_MAP["终端回收情况"], [1, 2, 13, 14])
        self.assertEqual(SECTION_SLIDE_MAP["业务支撑情况"], [1, 2, 16, 17])


if __name__ == "__main__":
    unittest.main()
