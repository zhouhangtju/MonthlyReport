"""SQLite 数据库连接与初始化。"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS etl_run (
    run_id TEXT PRIMARY KEY,
    dataset_code TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_file TEXT NOT NULL,
    archived_file TEXT,
    file_sha256 TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    rows_read INTEGER NOT NULL DEFAULT 0,
    rows_inserted INTEGER NOT NULL DEFAULT 0,
    rows_updated INTEGER NOT NULL DEFAULT 0,
    rows_unchanged INTEGER NOT NULL DEFAULT 0,
    rows_failed INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_etl_run_dataset_started
ON etl_run(dataset_code, started_at);

CREATE TABLE IF NOT EXISTS raw_source_record (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_code TEXT NOT NULL,
    source_system TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_data TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    first_run_id TEXT NOT NULL REFERENCES etl_run(run_id),
    last_run_id TEXT NOT NULL REFERENCES etl_run(run_id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(dataset_code, source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_source_record_dataset
ON raw_source_record(dataset_code);

CREATE TABLE IF NOT EXISTS raw_source_record_version (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER NOT NULL REFERENCES raw_source_record(record_id),
    run_id TEXT NOT NULL REFERENCES etl_run(run_id),
    row_hash TEXT NOT NULL,
    source_data TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    UNIQUE(record_id, row_hash)
);

CREATE TABLE IF NOT EXISTS metric_run (
    metric_run_id TEXT PRIMARY KEY,
    metric_code TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    source_runs TEXT NOT NULL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS ads_metric_result (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_run_id TEXT NOT NULL REFERENCES metric_run(metric_run_id),
    metric_code TEXT NOT NULL,
    dimension_type TEXT NOT NULL,
    dimension_value TEXT NOT NULL,
    numerator REAL,
    denominator REAL,
    metric_value REAL,
    UNIQUE(metric_run_id, metric_code, dimension_type, dimension_value)
);

CREATE TABLE IF NOT EXISTS ads_metric_detail (
    detail_id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_run_id TEXT NOT NULL REFERENCES metric_run(metric_run_id),
    metric_code TEXT NOT NULL,
    detail_role TEXT NOT NULL CHECK (detail_role IN ('denominator', 'numerator', 'excluded')),
    source_dataset_code TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    dimension_value TEXT NOT NULL DEFAULT '{}',
    detail_data TEXT NOT NULL,
    UNIQUE(metric_run_id, metric_code, detail_role, source_dataset_code, source_record_id, dimension_value)
);

CREATE INDEX IF NOT EXISTS idx_ads_metric_detail_run_role
ON ads_metric_detail(metric_run_id, metric_code, detail_role);

CREATE TABLE IF NOT EXISTS orch_opening_monthly_summary (
    month TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    metric_code TEXT NOT NULL,
    dimension_type TEXT NOT NULL,
    dimension_value TEXT NOT NULL,
    numerator REAL,
    denominator REAL,
    metric_value REAL,
    source_metric_run_id TEXT NOT NULL REFERENCES metric_run(metric_run_id),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (month, metric_version, metric_code, dimension_type, dimension_value)
);

CREATE TABLE IF NOT EXISTS orch_opening_monthly_quality (
    month TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    database_rows INTEGER NOT NULL,
    rows_missing_order_month INTEGER NOT NULL,
    source_metric_run_id TEXT NOT NULL REFERENCES metric_run(metric_run_id),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (month, metric_version)
);

CREATE TABLE IF NOT EXISTS data_retention_purge (
    purge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_code TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    purged_at TEXT NOT NULL,
    archive_file TEXT NOT NULL,
    rows_purged INTEGER NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(path: Path) -> None:
    schema_path = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    with connect(path) as connection:
        connection.executescript(schema)
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ads_metric_result'"
        ).fetchone()["sql"]
        compact_sql = "".join(str(table_sql).split()).lower()
        old_unique = "unique(metric_run_id,dimension_type,dimension_value)"
        if old_unique in compact_sql:
            connection.executescript(
                """
                ALTER TABLE ads_metric_result RENAME TO ads_metric_result_legacy;
                CREATE TABLE ads_metric_result (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_run_id TEXT NOT NULL REFERENCES metric_run(metric_run_id),
                    metric_code TEXT NOT NULL,
                    dimension_type TEXT NOT NULL,
                    dimension_value TEXT NOT NULL,
                    numerator REAL,
                    denominator REAL,
                    metric_value REAL,
                    UNIQUE(metric_run_id, metric_code, dimension_type, dimension_value)
                );
                INSERT INTO ads_metric_result (
                    result_id, metric_run_id, metric_code, dimension_type,
                    dimension_value, numerator, denominator, metric_value
                )
                SELECT result_id, metric_run_id, metric_code, dimension_type,
                       dimension_value, numerator, denominator, metric_value
                FROM ads_metric_result_legacy;
                DROP TABLE ads_metric_result_legacy;
                """
            )
        from storage.orchestration_tables import backfill_missing
        backfill_missing(connection)


def has_successful_coverage(
    path: Path,
    dataset_code: str,
    period_start: str,
    period_end: str,
) -> bool:
    """Return whether successful, error-free ETL runs cover every requested day."""
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return False
    try:
        with connect(resolved) as connection:
            rows = connection.execute(
                """SELECT period_start, period_end
                   FROM etl_run
                   WHERE dataset_code = ?
                     AND status = 'success'
                     AND rows_failed = 0
                     AND period_start IS NOT NULL
                     AND period_end IS NOT NULL
                     AND period_end >= ?
                     AND period_start <= ?
                     AND NOT EXISTS (
                         SELECT 1 FROM data_retention_purge p
                         WHERE p.dataset_code = etl_run.dataset_code
                           AND etl_run.started_at <= p.purged_at
                           AND etl_run.period_end >= p.period_start
                           AND etl_run.period_start <= p.period_end
                     )""",
                (dataset_code, period_start, period_end),
            ).fetchall()
    except sqlite3.OperationalError:
        return False

    requested_start = date.fromisoformat(period_start)
    requested_end = date.fromisoformat(period_end)
    intervals = sorted(
        (
            max(requested_start, date.fromisoformat(row["period_start"])),
            min(requested_end, date.fromisoformat(row["period_end"])),
        )
        for row in rows
    )
    cursor = requested_start
    for start, end in intervals:
        if end < cursor:
            continue
        if start > cursor:
            return False
        cursor = max(cursor, end + timedelta(days=1))
        if cursor > requested_end:
            return True
    return cursor > requested_end


def has_collection_coverage(
    path: Path,
    dataset_code: str,
    period_start: str,
    period_end: str,
) -> bool:
    """Check complete collection markers, used by multi-file source exports."""
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return False
    try:
        with connect(resolved) as connection:
            rows = connection.execute(
                """SELECT period_start, period_end FROM collection_run
                   WHERE dataset_code = ? AND status = 'success'
                     AND imported_files = produced_files
                     AND produced_files > 0
                     AND period_end >= ? AND period_start <= ?
                     AND NOT EXISTS (
                         SELECT 1 FROM data_retention_purge p
                         WHERE p.dataset_code=collection_run.dataset_code
                           AND collection_run.started_at <= p.purged_at
                           AND collection_run.period_end >= p.period_start
                           AND collection_run.period_start <= p.period_end
                     )""",
                (dataset_code, period_start, period_end),
            ).fetchall()
    except sqlite3.OperationalError:
        return False
    requested_start = date.fromisoformat(period_start)
    requested_end = date.fromisoformat(period_end)
    intervals = sorted(
        (
            max(requested_start, date.fromisoformat(row["period_start"])),
            min(requested_end, date.fromisoformat(row["period_end"])),
        )
        for row in rows
    )
    cursor = requested_start
    for start, end in intervals:
        if end < cursor:
            continue
        if start > cursor:
            return False
        cursor = max(cursor, end + timedelta(days=1))
        if cursor > requested_end:
            return True
    return cursor > requested_end
