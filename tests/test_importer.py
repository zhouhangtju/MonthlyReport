from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from config.datasets import get_dataset
from storage.database import connect
from storage.importer import import_file


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=["工单号", "工单状态", "地市"])
        writer.writeheader()
        writer.writerows(rows)


class ImporterTest(unittest.TestCase):
    def test_import_is_idempotent_and_keeps_changed_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "complaints.csv"
            database = root / "quality.db"
            dataset = get_dataset("youshu_complaint")
            rows = [
                {"工单号": "A1", "工单状态": "处理中", "地市": "杭州"},
                {"工单号": "A2", "工单状态": "已完成", "地市": "宁波"},
            ]
            write_csv(source, rows)

            first = import_file(database, dataset, source, archive_root=root / "raw")
            second = import_file(database, dataset, source, archive_root=root / "raw")
            self.assertEqual(first["inserted"], 2)
            self.assertEqual(second["unchanged"], 2)

            rows[0]["工单状态"] = "已完成"
            write_csv(source, rows)
            third = import_file(database, dataset, source, archive_root=root / "raw")
            self.assertEqual(third["updated"], 1)
            self.assertEqual(third["unchanged"], 1)

            with connect(database) as connection:
                records = connection.execute("SELECT * FROM raw_source_record").fetchall()
                versions = connection.execute("SELECT * FROM raw_source_record_version").fetchall()
                runs = connection.execute("SELECT * FROM etl_run").fetchall()
            self.assertEqual(len(records), 2)
            self.assertEqual(len(versions), 3)
            self.assertEqual(len(runs), 3)
            changed = next(row for row in records if row["source_record_id"] == "A1")
            self.assertEqual(json.loads(changed["source_data"])["工单状态"], "已完成")

    def test_missing_business_key_is_a_failed_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "complaints.csv"
            database = root / "quality.db"
            write_csv(source, [{"工单号": "", "工单状态": "已完成", "地市": "杭州"}])
            result = import_file(database, get_dataset("youshu_complaint"), source)
            self.assertEqual(result["read"], 1)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["inserted"], 0)


if __name__ == "__main__":
    unittest.main()
