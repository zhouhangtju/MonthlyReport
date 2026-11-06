CREATE TABLE IF NOT EXISTS intermediate_terminal_installation_reuse (
    metric_run_id VARCHAR(80) NOT NULL,
    sheet_name VARCHAR(100) NOT NULL,
    source_row_number INT NOT NULL,
    city VARCHAR(255),
    county VARCHAR(255),
    business_category VARCHAR(255),
    material_category VARCHAR(255),
    statistic_level VARCHAR(16),
    new_sn_quantity DECIMAL(24,6),
    repair_sn_quantity DECIMAL(24,6),
    recovery_sn_quantity DECIMAL(24,6),
    row_data LONGTEXT NOT NULL,
    PRIMARY KEY(metric_run_id,sheet_name,source_row_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS terminal_installation_reuse_audit (
    metric_run_id VARCHAR(80) PRIMARY KEY,
    report_month VARCHAR(7) NOT NULL,
    sources LONGTEXT NOT NULL,
    audit LONGTEXT NOT NULL,
    sheet_headers LONGTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
