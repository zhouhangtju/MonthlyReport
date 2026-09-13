"""归档并清理已经生成月度汇总的编排开通明细。"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.database import connect, initialize


DATASET_CODE = "orch_opening"
METRIC_VERSION = "1.0.0"


def preview(database: Path, before_month: str) -> dict[str, object]:
    cutoff = datetime.strptime(before_month, "%Y-%m").strftime("%Y-%m-01")
    initialize(database)
    with connect(database) as connection:
        rows = connection.execute(
            """SELECT order_no, order_finished_at FROM ods_orch_opening
               WHERE order_finished_at < ? ORDER BY order_finished_at""",
            (cutoff,),
        ).fetchall()
        months = sorted({str(row["order_finished_at"])[:7] for row in rows})
        summarized = {
            row["month"] for row in connection.execute(
                """SELECT month FROM orch_opening_monthly_quality
                   WHERE metric_version=? AND month < ?""",
                (METRIC_VERSION, before_month),
            ).fetchall()
        }
    missing = [month for month in months if month not in summarized]
    return {
        "cutoff": cutoff,
        "rows": len(rows),
        "months": months,
        "missing_summary_months": missing,
    }


def prune(database: Path, before_month: str, archive_dir: Path) -> dict[str, object]:
    plan = preview(database, before_month)
    if plan["missing_summary_months"]:
        missing = ", ".join(plan["missing_summary_months"])
        raise RuntimeError(f"以下月份尚无月度汇总，拒绝清理：{missing}")
    if not plan["rows"]:
        return {**plan, "archive_file": None, "vacuumed": False}

    database = database.expanduser().resolve()
    archive_dir = archive_dir.expanduser().resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = archive_dir / f"orch_opening_before_{before_month}_{stamp}.jsonl.gz"
    cutoff = str(plan["cutoff"])

    with connect(database) as connection:
        records = connection.execute(
            """SELECT o.*, r.record_id, r.source_system, r.source_record_id,
                      r.source_data AS raw_source_data, r.row_hash AS raw_row_hash,
                      r.first_run_id AS raw_first_run_id, r.last_run_id AS raw_last_run_id,
                      r.first_seen_at AS raw_first_seen_at, r.last_seen_at AS raw_last_seen_at
               FROM ods_orch_opening o
               LEFT JOIN raw_source_record r
                 ON r.dataset_code=? AND r.source_record_id=o.order_no
               WHERE o.order_finished_at < ? ORDER BY o.order_finished_at""",
            (DATASET_CODE, cutoff),
        ).fetchall()
        record_ids = [row["record_id"] for row in records if row["record_id"] is not None]
        versions: dict[int, list[dict[str, object]]] = {}
        for record_id in record_ids:
            versions[record_id] = [
                dict(row) for row in connection.execute(
                    "SELECT * FROM raw_source_record_version WHERE record_id=? ORDER BY observed_at",
                    (record_id,),
                ).fetchall()
            ]

    # 先完成可恢复归档，再开启删除事务。
    with gzip.open(archive, "wt", encoding="utf-8") as target:
        target.write(json.dumps({"type": "manifest", "dataset_code": DATASET_CODE,
                                 "before_month": before_month, "rows": len(records)}, ensure_ascii=False) + "\n")
        for row in records:
            item = dict(row)
            item["versions"] = versions.get(row["record_id"], [])
            target.write(json.dumps({"type": "record", "data": item}, ensure_ascii=False) + "\n")

    purged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    period_start = min(str(row["order_finished_at"])[:10] for row in records)
    period_end = (datetime.strptime(cutoff, "%Y-%m-%d") - timedelta(days=1)).date().isoformat()
    with connect(database) as connection:
        if record_ids:
            placeholders = ",".join("?" for _ in record_ids)
            connection.execute(
                f"DELETE FROM raw_source_record_version WHERE record_id IN ({placeholders})",
                record_ids,
            )
            connection.execute(
                f"DELETE FROM raw_source_record WHERE record_id IN ({placeholders})",
                record_ids,
            )
        connection.execute("DELETE FROM ods_orch_opening WHERE order_finished_at < ?", (cutoff,))
        connection.execute(
            """INSERT INTO data_retention_purge (
                   dataset_code, period_start, period_end, purged_at, archive_file, rows_purged
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (DATASET_CODE, period_start, period_end, purged_at, str(archive), len(records)),
        )
    with connect(database) as connection:
        connection.execute("VACUUM")
    return {**plan, "archive_file": str(archive), "vacuumed": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="归档并清理编排开通历史明细")
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    parser.add_argument("--before-month", required=True, help="清理此月份之前的明细，YYYY-MM")
    parser.add_argument("--archive-dir", type=Path, default=Path("data/archive/orch_opening"))
    parser.add_argument("--apply", action="store_true", help="实际执行；省略时只输出预览")
    args = parser.parse_args()
    result = (
        prune(args.database, args.before_month, args.archive_dir)
        if args.apply else preview(args.database, args.before_month)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
