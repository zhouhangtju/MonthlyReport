CREATE TABLE IF NOT EXISTS `raw_qikuan_activation_silence_batch` (
    batch_id VARCHAR(80) PRIMARY KEY,
    report_month CHAR(7) NOT NULL,
    source_file VARCHAR(512) NOT NULL,
    file_sha256 CHAR(64) NOT NULL,
    imported_at VARCHAR(40) NOT NULL,
    row_count INT NOT NULL,
    duplicate_count INT NOT NULL,
    UNIQUE KEY uk_month_file (report_month, file_sha256),
    KEY idx_month (report_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `raw_qikuan_activation_silence` (
    batch_id VARCHAR(80) NOT NULL,
    order_id VARCHAR(255) COLLATE utf8mb4_bin NOT NULL,
    source_row INT NOT NULL,
    manual_city VARCHAR(100),
    manual_district VARCHAR(100),
    completion_time VARCHAR(40),
    source_data LONGTEXT NOT NULL,
    PRIMARY KEY (batch_id, order_id),
    FOREIGN KEY (batch_id) REFERENCES raw_qikuan_activation_silence_batch(batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `result_qikuan_activation_silence` (
    result_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    metric_run_id VARCHAR(80) NOT NULL,
    metric_code VARCHAR(120) NOT NULL,
    dimension_type VARCHAR(120) NOT NULL,
    dimension_value LONGTEXT NOT NULL,
    dimension_value_hash CHAR(64) GENERATED ALWAYS AS (SHA2(dimension_value, 256)) STORED,
    `month` VARCHAR(255) GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(dimension_value, '$.month'))) STORED,
    `city` VARCHAR(255) GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(dimension_value, '$.city'))) STORED,
    `district` VARCHAR(255) GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(dimension_value, '$.district'))) STORED,
    `grid` VARCHAR(255) GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(dimension_value, '$.grid'))) STORED,
    numerator DOUBLE,
    denominator DOUBLE,
    metric_value DOUBLE,
    UNIQUE KEY uk_result_dimension (metric_run_id, metric_code, dimension_type, dimension_value_hash),
    KEY idx_month_city (month, city),
    FOREIGN KEY (metric_run_id) REFERENCES metric_run(metric_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
