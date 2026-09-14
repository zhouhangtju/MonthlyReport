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
ARCHIVE_BATCH_SIZE = 500


def preview(database: Path, before_month: str) -> dict[str, object]:
    cutoff = datetime.strptime(before_month, "%Y-%m").strftime("%Y-%m-01")
    initialize(database)
    with connect(database) as connection:
        row_count = connection.execute(
            """SELECT COUNT(*) AS value FROM ods_orch_opening
               WHERE order_finished_at < ?""",
            (cutoff,),
        ).fetchone()["value"]
        months = [
            row["month"] for row in connection.execute(
                """SELECT DISTINCT substr(order_finished_at, 1, 7) AS month
                   FROM ods_orch_opening WHERE order_finished_at < ?
                   ORDER BY month""",
                (cutoff,),
            ).fetchall()
        ]
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
        "rows": row_count,
        "months": months,
        "missing_summary_months": missing,
    }


def archive_records(database: Path, cutoff: str, archive: Path, before_month: str) -> int:
    """分批读取订单和版本，避免全量 fetchall 与逐订单查询。"""
    query = """SELECT o.*, r.record_id, r.source_system, r.source_record_id,
                      r.source_data AS raw_source_data, r.row_hash AS raw_row_hash,
                      r.first_run_id AS raw_first_run_id, r.last_run_id AS raw_last_run_id,
                      r.first_seen_at AS raw_first_seen_at, r.last_seen_at AS raw_last_seen_at
               FROM ods_orch_opening o
               LEFT JOIN raw_source_record r
                 ON r.dataset_code=? AND r.source_record_id=o.order_no
               WHERE o.order_finished_at < ?
               ORDER BY o.order_finished_at, o.order_no"""
    partial = archive.with_suffix(archive.suffix + ".part")
    partial.unlink(missing_ok=True)
    count = 0
    try:
        with connect(database) as connection, gzip.open(partial, "wt", encoding="utf-8") as target:
            target.write(json.dumps({"type": "manifest", "dataset_code": DATASET_CODE,
                                     "before_month": before_month}, ensure_ascii=False) + "\n")
            cursor = connection.execute(query, (DATASET_CODE, cutoff))
            while batch := cursor.fetchmany(ARCHIVE_BATCH_SIZE):
                record_ids = [row["record_id"] for row in batch if row["record_id"] is not None]
                versions: dict[int, list[dict[str, object]]] = {record_id: [] for record_id in record_ids}
                if record_ids:
                    placeholders = ",".join("?" for _ in record_ids)
                    version_rows = connection.execute(
                        f"""SELECT * FROM raw_source_record_version
                            WHERE record_id IN ({placeholders})
                            ORDER BY record_id, observed_at, version_id""",
                        record_ids,
                    )
                    for version in version_rows:
                        versions[version["record_id"]].append(dict(version))
                for row in batch:
                    item = dict(row)
                    item["versions"] = versions.get(row["record_id"], [])
                    target.write(json.dumps({"type": "record", "data": item}, ensure_ascii=False) + "\n")
                    count += 1
        partial.replace(archive)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return count


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

    # 先完成可恢复归档，再开启删除事务。
    archived_rows = archive_records(database, cutoff, archive, before_month)
    if archived_rows != plan["rows"]:
        archive.unlink(missing_ok=True)
        raise RuntimeError(f"归档行数不一致：预期 {plan['rows']}，实际 {archived_rows}")

    purged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    period_end = (datetime.strptime(cutoff, "%Y-%m-%d") - timedelta(days=1)).date().isoformat()
    with connect(database) as connection:
        period_start = connection.execute(
            "SELECT MIN(substr(order_finished_at, 1, 10)) AS value FROM ods_orch_opening WHERE order_finished_at < ?",
            (cutoff,),
        ).fetchone()["value"]
        connection.execute(
            """DELETE FROM raw_source_record_version WHERE record_id IN (
                   SELECT r.record_id FROM raw_source_record r
                   JOIN ods_orch_opening o ON o.order_no=r.source_record_id
                   WHERE r.dataset_code=? AND o.order_finished_at < ?
               )""",
            (DATASET_CODE, cutoff),
        )
        connection.execute(
            """DELETE FROM raw_source_record
               WHERE dataset_code=? AND EXISTS (
                   SELECT 1 FROM ods_orch_opening o
                   WHERE o.order_no=raw_source_record.source_record_id
                     AND o.order_finished_at < ?
               )""",
            (DATASET_CODE, cutoff),
        )
        connection.execute("DELETE FROM ods_orch_opening WHERE order_finished_at < ?", (cutoff,))
        connection.execute(
            """INSERT INTO data_retention_purge (
                   dataset_code, period_start, period_end, purged_at, archive_file, rows_purged
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (DATASET_CODE, period_start, period_end, purged_at, str(archive), archived_rows),
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
