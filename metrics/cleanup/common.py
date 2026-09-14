"""Conservative platform cleanup: explicit preview, verified archives, atomic delete."""

import argparse
import base64
import gzip
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from storage.raw_archive import digest_file, platform_for

DEPENDENCIES = {
    "eoms_complaint": ["dedicated_line_repeat_complaint_rate", "qianliyan_repeat_complaint_rate", "dedicated_line_install_fault_rate", "commercial_customer_install_fault_rate"],
    "eoms_service_removal_order": ["terminal_recovery"],
    "integration_opening": ["dedicated_line_opening_withdrawal_rate"],
    "integration_removal_order": ["terminal_recovery"],
    "integration_terminal_inbound": ["terminal_recovery"],
    "integration_terminal_outbound": ["terminal_recovery"],
    "integration_material_baseline": ["terminal_recovery"],
    "terminal_material_names": ["terminal_recovery"],
    "orch_opening": ["orchestration_opening_metrics"],
    "orch_install": ["dedicated_line_install_fault_rate", "commercial_customer_install_fault_rate"],
    "youshu_install": ["qikuan_install_fault_rate", "commercial_customer_install_fault_rate"],
    "youshu_complaint": ["qikuan_install_fault_rate", "commercial_customer_install_fault_rate"],
}


def lineage(conn, run_id, seen=None):
    seen = set() if seen is None else seen
    if run_id in seen:
        raise ValueError("Cyclic metric lineage")
    row = conn.execute("SELECT source_runs FROM metric_run WHERE metric_run_id=? AND status='success'", (run_id,)).fetchone()
    if row is None:
        return {run_id}
    result = set()
    for parent in json.loads(row[0]):
        result.update(lineage(conn, parent, seen | {run_id}))
    return result


def plan(conn, platform, datasets, start, end):
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("Invalid date range")
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "data_retention_purge" not in present:
        raise ValueError("Database schema must be initialized by the normal pipeline first")
    errors, batches, metric_ids, files = [], [], set(), []
    if conn.execute("SELECT 1 FROM etl_run WHERE status='running' LIMIT 1").fetchone() or conn.execute("SELECT 1 FROM metric_run WHERE status='running' LIMIT 1").fetchone():
        errors.append("Active ETL/metric batch exists; stop writers before cleanup")
    for code in datasets:
        if code not in DEPENDENCIES or platform_for(code) != platform:
            raise ValueError(f"Dataset does not belong to platform: {code}")
        rows = list(conn.execute("SELECT * FROM etl_run WHERE dataset_code=? AND period_start<=? AND period_end>=? ORDER BY started_at,run_id", (code, end, start)))
        if not rows:
            errors.append(f"{code}: no source batches; explicitly select only datasets to clean")
            continue
        for row in rows:
            if row["period_start"] < start or row["period_end"] > end:
                errors.append(f"{code}: batch crosses cleanup boundary: {row['run_id']}")
            if row["status"] != "success" or row["rows_failed"]:
                errors.append(f"{code}: failed/incomplete source batch: {row['run_id']}")
            original = next((Path(p).resolve() for p in (row["archived_file"], row["source_file"]) if p and Path(p).is_file() and digest_file(p) == row["file_sha256"]), None)
            if original is None:
                errors.append(f"{code}: matching import file missing for {row['run_id']}")
            else:
                files.append({"etl_run_id": row["run_id"], "path": str(original), "sha256": row["file_sha256"]})
        batches.extend(dict(r) for r in rows)
        for owner in DEPENDENCIES[code]:
            metric = conn.execute("SELECT * FROM metric_run WHERE metric_code=? AND period_start=? AND period_end=? AND status='success' ORDER BY started_at DESC,rowid DESC LIMIT 1", (owner, start, end)).fetchone()
            if metric is None:
                errors.append(f"{owner}: missing successful exact-period calculation")
                continue
            metric_ids.add(metric["metric_run_id"])
            if not conn.execute("SELECT 1 FROM ads_metric_result WHERE metric_run_id=? LIMIT 1", (metric["metric_run_id"],)).fetchone():
                errors.append(f"{owner}: no stored results")
            if code != "integration_terminal_outbound":
                required = {rows[-1]["run_id"]} if owner == "terminal_recovery" else {r["run_id"] for r in rows}
                if not required.issubset(lineage(conn, metric["metric_run_id"])):
                    errors.append(f"{owner}: source provenance does not cover selected batches")
            latest_end = max(r["finished_at"] or r["started_at"] for r in rows)
            if datetime.fromisoformat(metric["started_at"]).timestamp() < datetime.fromisoformat(latest_end).timestamp():
                errors.append(f"{owner}: calculation predates source completion")
        if code == "orch_opening":
            months = set()
            for row in rows:
                month = date.fromisoformat(row["period_start"]).replace(day=1)
                last_month = date.fromisoformat(row["period_end"]).replace(day=1)
                # Cross-month batches are allowed; retain summaries for every covered month.
                while month <= last_month:
                    months.add(month.strftime("%Y-%m"))
                    month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
            for month in months:
                if not conn.execute("SELECT 1 FROM orch_opening_monthly_quality q JOIN metric_run m ON q.source_metric_run_id=m.metric_run_id WHERE q.month=? AND q.rows_missing_order_month=0 AND m.status='success' AND EXISTS (SELECT 1 FROM orch_opening_monthly_summary s WHERE s.month=q.month AND s.metric_version=q.metric_version AND s.source_metric_run_id=q.source_metric_run_id)", (month,)).fetchone():
                    errors.append(f"orch_opening: monthly summary not ready: {month}")
    conn.execute("CREATE TEMP TABLE cleanup_etl (id TEXT PRIMARY KEY)")
    conn.executemany("INSERT OR IGNORE INTO cleanup_etl VALUES (?)", ((r["run_id"],) for r in batches))
    conn.execute("CREATE TEMP TABLE cleanup_metric (id TEXT PRIMARY KEY)")
    # Only remove this platform's audit rows; shared consumers keep other sources.
    for owner in {o for d in datasets for o in DEPENDENCIES[d]}:
        conn.execute("INSERT OR IGNORE INTO cleanup_metric SELECT metric_run_id FROM metric_run WHERE metric_code=? AND period_start=? AND period_end=? AND status='success'", (owner, start, end))
    conn.execute("CREATE TEMP TABLE cleanup_dataset (code TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO cleanup_dataset VALUES (?)", ((d,) for d in datasets))
    predicates = {
        "raw_source_record": "last_run_id IN (SELECT id FROM cleanup_etl)",
        "raw_source_record_version": "record_id IN (SELECT record_id FROM raw_source_record WHERE last_run_id IN (SELECT id FROM cleanup_etl))",
        "ods_orch_opening": "last_run_id IN (SELECT id FROM cleanup_etl)",
        "ods_orch_install": "last_run_id IN (SELECT id FROM cleanup_etl)",
        "tr_source_snapshot": "etl_run_id IN (SELECT id FROM cleanup_etl)",
        "tr_source_row": "snapshot_id IN (SELECT snapshot_id FROM tr_source_snapshot WHERE etl_run_id IN (SELECT id FROM cleanup_etl))",
        "ads_metric_detail": "metric_run_id IN (SELECT id FROM cleanup_metric) AND source_dataset_code IN (SELECT code FROM cleanup_dataset)",
    }
    predicates = {t: p for t, p in predicates.items() if t in present}
    counts = {t: conn.execute(f'SELECT count(*) FROM "{t}" WHERE {p}').fetchone()[0] for t, p in predicates.items()}
    per_dataset = {d: conn.execute("SELECT count(*) FROM raw_source_record WHERE dataset_code=? AND last_run_id IN (SELECT id FROM cleanup_etl)", (d,)).fetchone()[0] for d in datasets}
    return {"platform": platform, "datasets": datasets, "start": start, "end": end,
            "source_batches": batches, "metric_batches": sorted(metric_ids), "original_files": files,
            "counts": counts, "raw_counts": per_dataset, "blockers": sorted(set(errors))}, predicates


def encode(value):
    return {"base64": base64.b64encode(value).decode("ascii")} if isinstance(value, bytes) else value


def cleanup(database, platform, datasets, start, end, apply=False):
    database = Path(database).resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    with closing(sqlite3.connect(database.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True, timeout=60)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        try:
            report, predicates = plan(conn, platform, datasets, start, end)
            if not apply:
                return report
            if report["blockers"]:
                raise ValueError("Cleanup refused: " + "; ".join(report["blockers"]))
            if not any(report["counts"].values()):
                return {**report, "applied": False}
            folder = database.parent / "cleanup_logs" / platform / uuid.uuid4().hex
            folder.mkdir(parents=True, exist_ok=False)
            archive = folder / "details.jsonl.gz"
            with gzip.open(archive, "wt", encoding="utf-8") as stream:
                # Preserve metadata needed to interpret historical details and IDs.
                for table in ("etl_run", "metric_run"):
                    for row in conn.execute(f'SELECT * FROM "{table}"'):
                        stream.write(json.dumps({"table": table, "row": dict(row)}, ensure_ascii=False) + "\n")
                for table, predicate in predicates.items():
                    for row in conn.execute(f'SELECT * FROM "{table}" WHERE {predicate}'):
                        stream.write(json.dumps({"table": table, "row": {k: encode(v) for k, v in dict(row).items()}}, ensure_ascii=False) + "\n")
            verified = dict.fromkeys(predicates, 0)
            with gzip.open(archive, "rt", encoding="utf-8") as stream:
                for line in stream:
                    item = json.loads(line)
                    if item["table"] in verified:
                        verified[item["table"]] += 1
            if verified != report["counts"]:
                raise ValueError("Archive record counts do not match")
            # Include unchanged, lossless source workbook files for terminal recovery.
            from storage.raw_archive import archive_source
            if "tr_source_snapshot" in predicates:
                for row in conn.execute("SELECT * FROM tr_source_snapshot WHERE " + predicates["tr_source_snapshot"]):
                    import hashlib
                    if hashlib.sha256(row["workbook"]).hexdigest() != row["sha256"]:
                        raise ValueError("Invalid terminal workbook snapshot")
                    original = folder / (row["snapshot_id"] + "_" + Path(row["filename"]).name)
                    original.write_bytes(row["workbook"])
                    report["original_files"].append({"path": str(original), "sha256": row["sha256"], "etl_run_id": row["etl_run_id"]})
            # Move references to durable copies, even for legacy ETLs without archives.
            for item in report["original_files"]:
                source = Path(item["path"])
                run = next(r for r in report["source_batches"] if r["run_id"] == item["etl_run_id"])
                saved = archive_source(source, database, run["dataset_code"], run["period_start"], run["period_end"], run["run_id"], role="cleanup_" + uuid.uuid4().hex[:8])
                if digest_file(saved) != item["sha256"]:
                    raise ValueError("Source archive checksum mismatch")
                item["path"] = str(saved)
            report.update(archive=str(archive), archive_sha256=digest_file(archive))
            manifest = folder / "manifest.json"
            manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            for table in ("ads_metric_detail", "tr_source_row", "tr_source_snapshot", "raw_source_record_version", "ods_orch_opening", "ods_orch_install", "raw_source_record"):
                if table in predicates:
                    conn.execute(f'DELETE FROM "{table}" WHERE {predicates[table]}')
            stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            for code in datasets:
                conn.execute("INSERT INTO data_retention_purge (dataset_code,period_start,period_end,purged_at,archive_file,rows_purged) VALUES (?,?,?,?,?,?)", (code, start, end, stamp, str(manifest), report["raw_counts"][code]))
            conn.commit()
            return {**report, "applied": True, "manifest": str(manifest)}
        finally:
            conn.rollback()


def main(platform):
    parser = argparse.ArgumentParser(description=f"Preview/archive/delete {platform} source data after calculation")
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--dataset", action="append", choices=[d for d in DEPENDENCIES if platform_for(d) == platform])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    datasets = sorted(set(args.dataset or [d for d in DEPENDENCIES if platform_for(d) == platform]))
    print(json.dumps(cleanup(args.database, platform, datasets, args.start_date, args.end_date, args.apply), ensure_ascii=False, indent=2))
