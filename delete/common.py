"""Independent, fail-closed deletion; no backup, migration or collector hooks."""

import argparse
import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

GROUPS = {
    "eoms_complaints": ("eoms_complaint",),
    "eoms_terminal_removal": ("eoms_service_removal_order",),
    "integration_opening": ("integration_opening",),
    "integration_terminal_materials": (
        "integration_terminal_inbound", "integration_terminal_outbound",
        "integration_material_baseline", "terminal_material_names"),
    "integration_terminal_removal": ("integration_removal_order",),
    "orchestration_install": ("orch_install",),
    "youshu_complaints": ("youshu_complaint",),
    "youshu_install": ("youshu_install",),
}
DEPENDENCIES = {
    "eoms_complaint": ("dedicated_line_repeat_complaint_rate",
                       "qianliyan_repeat_complaint_rate", "dedicated_line_install_fault_rate",
                       "commercial_customer_install_fault_rate"),
    "integration_opening": ("dedicated_line_opening_withdrawal_rate",),
    "orch_install": ("dedicated_line_install_fault_rate", "commercial_customer_install_fault_rate"),
    "youshu_complaint": ("qikuan_install_fault_rate", "commercial_customer_install_fault_rate"),
    "youshu_install": ("qikuan_install_fault_rate", "commercial_customer_install_fault_rate"),
}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def lineage(conn, run_id, seen=None):
    seen = set() if seen is None else seen
    if run_id in seen:
        raise ValueError("Cyclic metric lineage")
    if conn.execute("SELECT 1 FROM etl_run WHERE run_id=?", (run_id,)).fetchone():
        return {run_id}
    row = conn.execute("SELECT source_runs, status FROM metric_run WHERE metric_run_id=?", (run_id,)).fetchone()
    if not row or row["status"] != "success":
        raise ValueError("Missing or unsuccessful source metric: " + run_id)
    sources = json.loads(row["source_runs"])
    if not isinstance(sources, list):
        raise ValueError("Invalid metric lineage")
    result = set()
    for source in sources:
        result.update(lineage(conn, source, seen | {run_id}))
    return result


def plan(conn, group, start, end, run_ids=()):
    date.fromisoformat(start)
    date.fromisoformat(end)
    if start > end:
        raise ValueError("start-date must not exceed end-date")
    blockers, files, batches = [], [], []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("etl_run", "metric_run", "collection_run"):
        if table in tables and conn.execute(f"SELECT 1 FROM {table} WHERE status='running' LIMIT 1").fetchone():
            blockers.append("Running task in " + table)
    codes = GROUPS[group]
    for code in codes:
        candidates = conn.execute(
            "SELECT * FROM etl_run WHERE dataset_code=? AND period_start<=? AND period_end>=?",
            (code, end, start)).fetchall()
        batches.extend(r for r in candidates if not run_ids or r["run_id"] in run_ids)
    selected = {r["run_id"] for r in batches}
    if run_ids and selected != set(run_ids):
        blockers.append("Some run IDs are missing or outside the requested datasets/period")
    if not batches:
        blockers.append("No matching ETL batches")
    for row in batches:
        if row["period_start"] < start or row["period_end"] > end:
            blockers.append("Batch crosses requested bounds: " + row["run_id"])
        if row["status"] != "success" or row["rows_failed"] or not row["finished_at"]:
            blockers.append("Incomplete ETL batch: " + row["run_id"])
        valid = None
        for value in (row["archived_file"], row["source_file"]):
            if value and Path(value).is_file() and digest(Path(value)) == row["file_sha256"]:
                valid = str(Path(value).resolve())
                break
        if not valid:
            blockers.append("No checksum-matching local source: " + row["run_id"])
        files.append({"run_id": row["run_id"], "path": valid, "sha256": row["file_sha256"]})

    for name, column in (("selected_runs", "id TEXT PRIMARY KEY"),
                         ("selected_records", "id INTEGER PRIMARY KEY"),
                         ("selected_metrics", "id TEXT PRIMARY KEY")):
        conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS {name} ({column})")
        conn.execute(f"DELETE FROM {name}")
    conn.executemany("INSERT INTO selected_runs VALUES (?)", [(r,) for r in selected])
    conn.execute("""INSERT INTO selected_records SELECT record_id FROM raw_source_record
                    WHERE last_run_id IN (SELECT id FROM selected_runs)""")
    # A latest-state row can also belong to an earlier batch. Never silently erase it.
    shared = conn.execute("""SELECT 1 FROM raw_source_record r WHERE record_id IN
        (SELECT id FROM selected_records) AND (first_run_id NOT IN (SELECT id FROM selected_runs)
        OR EXISTS (SELECT 1 FROM raw_source_record_version v WHERE v.record_id=r.record_id
                   AND v.run_id NOT IN (SELECT id FROM selected_runs))) LIMIT 1""").fetchone()
    if shared:
        blockers.append("Shared records have history outside the selection; explicitly include those batches")

    for row in batches:
        code = row["dataset_code"]
        for metric in DEPENDENCIES.get(code, ("terminal_recovery",)):
            # Outbound is not consumed by the current terminal calculation.
            needed = code != "integration_terminal_outbound"
            candidates = conn.execute("""SELECT * FROM metric_run m WHERE metric_code=?
                AND status='success' AND period_start<=? AND period_end>=?
                AND EXISTS (SELECT 1 FROM ads_metric_result a WHERE a.metric_run_id=m.metric_run_id)
                ORDER BY started_at DESC""", (metric, row["period_start"], row["period_end"])).fetchall()
            match = next((m for m in candidates if m["started_at"] >= (row["finished_at"] or "~")
                          and (not needed or row["run_id"] in lineage(conn, m["metric_run_id"]))), None)
            if not match:
                blockers.append(f"No covering, current result: {metric} / {row['run_id']}")
            else:
                conn.execute("INSERT OR IGNORE INTO selected_metrics VALUES (?)", (match["metric_run_id"],))

    conditions = {
        "ads_metric_detail": "metric_run_id IN (SELECT id FROM selected_metrics) AND EXISTS "
            "(SELECT 1 FROM raw_source_record r WHERE r.record_id IN (SELECT id FROM selected_records) "
            "AND r.dataset_code=ads_metric_detail.source_dataset_code "
            "AND r.source_record_id=ads_metric_detail.source_record_id)",
        "tr_source_row": "snapshot_id IN (SELECT snapshot_id FROM tr_source_snapshot WHERE etl_run_id IN (SELECT id FROM selected_runs))",
        "tr_source_snapshot": "etl_run_id IN (SELECT id FROM selected_runs)",
        "raw_source_record_version": "record_id IN (SELECT id FROM selected_records) OR run_id IN (SELECT id FROM selected_runs)",
        "ods_orch_install": "last_run_id IN (SELECT id FROM selected_runs)",
        "raw_source_record": "record_id IN (SELECT id FROM selected_records)",
    }
    conditions = {t: c for t, c in conditions.items() if t in tables}
    counts = {t: conn.execute(f"SELECT count(*) FROM {t} WHERE {c}").fetchone()[0]
              for t, c in conditions.items()}
    return {"group": group, "period_start": start, "period_end": end,
            "run_ids": sorted(selected), "files": files, "counts": counts,
            "batch_raw_counts": {r: conn.execute(
                "SELECT count(*) FROM raw_source_record WHERE last_run_id=?", (r,)).fetchone()[0]
                for r in selected},
            "blockers": sorted(set(blockers)), "backup_created": False}, conditions, batches


def execute(database, group, start, end, run_ids=(), apply=False, log_dir=None):
    database = Path(database).resolve()
    # mode=rw must not silently create an empty database on a typo.
    uri = database.as_uri() + ("?mode=rw" if apply else "?mode=ro")
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        try:
            report, conditions, batches = plan(conn, group, start, end, run_ids)
            report.update(database=str(database), applied=False)
            if not apply or report["blockers"] or not any(report["counts"].values()):
                conn.rollback()
                return report
            folder = Path(log_dir) if log_dir else database.parent / "cleanup_logs"
            folder.mkdir(parents=True, exist_ok=True)
            log = folder / (group + "_" + uuid.uuid4().hex + ".json")
            report.update(log_file=str(log.resolve()), state="prepared")
            log.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            for table, condition in conditions.items():
                conn.execute(f"DELETE FROM {table} WHERE {condition}")
            stamp = datetime.now().isoformat()
            for row, source in zip(batches, report["files"]):
                conn.execute("""INSERT INTO data_retention_purge
                    (dataset_code,period_start,period_end,purged_at,archive_file,rows_purged)
                    VALUES (?,?,?,?,?,?)""", (row["dataset_code"], row["period_start"], row["period_end"],
                    stamp, source["path"], report["batch_raw_counts"][row["run_id"]]))
            conn.commit()
            report.update(applied=True, state="committed")
            try:
                log.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as exc:
                report["log_warning"] = "Deletion committed but final log update failed: " + str(exc)
            return report
        except Exception:
            conn.rollback()
            raise


def main(group):
    parser = argparse.ArgumentParser(description="Test-only deletion. No backup is created.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--log-dir", type=Path)
    args = parser.parse_args()
    try:
        report = execute(args.database, group, args.start_date, args.end_date,
                         args.run_id, args.apply, args.log_dir)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["blockers"] else 0
