CREATE TABLE IF NOT EXISTS result_terminal_reuse (
    result_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    metric_run_id VARCHAR(80) NOT NULL,
    metric_code VARCHAR(120) NOT NULL,
    dimension_type VARCHAR(120) NOT NULL,
    dimension_value LONGTEXT NOT NULL,
    numerator DOUBLE,
    denominator DOUBLE,
    metric_value DOUBLE,
    INDEX idx_reuse_run(metric_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS terminal_reuse_result_audit (
    metric_run_id VARCHAR(80) PRIMARY KEY,
    report_month CHAR(7) NOT NULL,
    result_json JSON NOT NULL,
    INDEX idx_reuse_month(report_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
