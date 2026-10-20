CREATE TABLE IF NOT EXISTS `result_qikuan_opening` (
    result_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    metric_run_id VARCHAR(80) NOT NULL,
    metric_code VARCHAR(120) NOT NULL,
    dimension_type VARCHAR(120) NOT NULL,
    dimension_value LONGTEXT NOT NULL,
    dimension_value_hash CHAR(64) GENERATED ALWAYS AS (SHA2(dimension_value, 256)) STORED,
    `month` VARCHAR(255) GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(dimension_value, '$.month'))) STORED, `scope` VARCHAR(255) GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(dimension_value, '$.scope'))) STORED, `city` VARCHAR(255) GENERATED ALWAYS AS (JSON_UNQUOTE(JSON_EXTRACT(dimension_value, '$.city'))) STORED,
    numerator DOUBLE,
    denominator DOUBLE,
    metric_value DOUBLE,
    UNIQUE KEY uk_result_dimension (metric_run_id, metric_code, dimension_type, dimension_value_hash),
    FOREIGN KEY (metric_run_id) REFERENCES metric_run(metric_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
