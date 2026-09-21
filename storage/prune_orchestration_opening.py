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
            """SELECT COUNT(*) AS value FROM orch_opening
               WHERE NULLIF(TRIM(`订单结束时间`), '') < ?""",
            (cutoff,),
        ).fetchone()["value"]
        months = [
            row["month"] for row in connection.execute(
                """SELECT DISTINCT substr(NULLIF(TRIM(`订单结束时间`), ''), 1, 7) AS month
                   FROM orch_opening WHERE NULLIF(TRIM(`订单结束时间`), '') < ?
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
    query = """SELECT o.*, a.source_record_id,
                      a.row_hash AS raw_row_hash, a.first_run_id AS raw_first_run_id,
                      a.last_run_id AS raw_last_run_id, a.first_seen_at AS raw_first_seen_at,
                      a.last_seen_at AS raw_last_seen_at
               FROM orch_opening o
               LEFT JOIN raw_record_audit a ON a.dataset_code='orch_opening' AND a.source_record_id=o.`订单号`
               WHERE NULLIF(TRIM(o.`订单结束时间`), '') < ? ORDER BY NULLIF(TRIM(o.`订单结束时间`), ''), o.`订单号`"""
    partial = archive.with_suffix(archive.suffix + ".part")
    partial.unlink(missing_ok=True)
    count = 0
    try:
        with connect(database) as connection, gzip.open(partial, "wt", encoding="utf-8") as target:
            target.write(json.dumps({"type": "manifest", "dataset_code": DATASET_CODE,
                                     "before_month": before_month}, ensure_ascii=False) + "\n")
            cursor = connection.execute(query, (cutoff,))
            while batch := cursor.fetchmany(ARCHIVE_BATCH_SIZE):
                source_record_ids = [row["source_record_id"] for row in batch if row["source_record_id"] is not None]
                versions: dict[str, list[dict[str, object]]] = {source_record_id: [] for source_record_id in source_record_ids}
                if source_record_ids:
                    placeholders = ",".join("?" for _ in source_record_ids)
                    version_rows = connection.execute(
                        f"""SELECT * FROM orch_opening_version
                            WHERE source_record_id IN ({placeholders})
                            ORDER BY source_record_id, observed_at, version_id""",
                        source_record_ids,
                    )
                    for version in version_rows:
                        versions[version["source_record_id"]].append(dict(version))
                for row in batch:
                    item = dict(row)
                    item["raw_data"] = connection.execute(
                        "SELECT * FROM orch_opening WHERE `订单号`=?", (row["订单号"],)
                    ).fetchone()
                    item["versions"] = versions.get(row["source_record_id"], [])
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

    database = database.expanduser().resolve() if database is not None else None
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
            "SELECT MIN(substr(NULLIF(TRIM(`订单结束时间`), ''), 1, 10)) AS value FROM orch_opening WHERE NULLIF(TRIM(`订单结束时间`), '') < ?",
            (cutoff,),
        ).fetchone()["value"]
        connection.execute(
            """DELETE FROM orch_opening_version WHERE source_record_id IN (
                   SELECT o.`订单号` FROM orch_opening o
                   WHERE NULLIF(TRIM(o.`订单结束时间`), '') < ?
               )""",
            (cutoff,),
        )
        connection.execute(
            """DELETE a FROM raw_record_audit a JOIN orch_opening o
               ON a.source_record_id=o.`订单号` WHERE a.dataset_code='orch_opening'
               AND NULLIF(TRIM(o.`订单结束时间`), '') < ?""", (cutoff,),
        )
        connection.execute("DELETE FROM orch_opening WHERE NULLIF(TRIM(`订单结束时间`), '') < ?", (cutoff,))
        connection.execute(
            """INSERT INTO data_retention_purge (
                   dataset_code, period_start, period_end, purged_at, archive_file, rows_purged
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (DATASET_CODE, period_start, period_end, purged_at, str(archive), archived_rows),
        )
    return {**plan, "archive_file": str(archive), "vacuumed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="归档并清理编排开通历史明细")
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
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
