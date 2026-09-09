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

CREATE TABLE IF NOT EXISTS collection_run (
    collection_run_id TEXT PRIMARY KEY,
    dataset_code TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    expected_files INTEGER,
    produced_files INTEGER NOT NULL DEFAULT 0,
    imported_files INTEGER NOT NULL DEFAULT 0,
    source_files TEXT NOT NULL DEFAULT '[]',
    etl_run_ids TEXT NOT NULL DEFAULT '[]',
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_collection_run_dataset_period
ON collection_run(dataset_code, period_start, period_end, status);

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

-- 编排专线开通情况：接口周期按结束时间筛选。
CREATE TABLE IF NOT EXISTS ods_orch_opening (
    order_no TEXT PRIMARY KEY,
    order_created_at TEXT,
    order_finished_at TEXT,
    city TEXT,
    order_status TEXT,
    business_type TEXT,
    product_name TEXT,
    order_type TEXT,
    source_data TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    first_run_id TEXT NOT NULL REFERENCES etl_run(run_id),
    last_run_id TEXT NOT NULL REFERENCES etl_run(run_id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ods_orch_opening_finished
ON ods_orch_opening(order_finished_at);

-- 编排互联网专线新装单：接口周期按派单时间筛选。
CREATE TABLE IF NOT EXISTS ods_orch_install (
    order_no TEXT PRIMARY KEY,
    order_created_at TEXT,
    dispatched_at TEXT,
    city TEXT,
    order_status TEXT,
    business_type TEXT,
    product_name TEXT,
    order_type TEXT,
    source_data TEXT NOT NULL,
    row_hash TEXT NOT NULL,
    first_run_id TEXT NOT NULL REFERENCES etl_run(run_id),
    last_run_id TEXT NOT NULL REFERENCES etl_run(run_id),
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ods_orch_install_dispatched
ON ods_orch_install(dispatched_at);

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
