-- Independent city/county snapshots. Requires existing collection_run and etl_run.

CREATE TABLE IF NOT EXISTS youshu_install_completed_city (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    collection_run_id VARCHAR(80) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    city VARCHAR(64) NOT NULL,
    completed_order_count BIGINT UNSIGNED NOT NULL,
    source_file VARCHAR(512) NOT NULL,
    collected_at VARCHAR(40) NOT NULL,
    UNIQUE KEY uk_completed_city (collection_run_id,period_start,period_end,city),
    KEY idx_completed_city_period (period_start,period_end),
    FOREIGN KEY (collection_run_id) REFERENCES collection_run(collection_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS youshu_install_completed_county (
    id BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    collection_run_id VARCHAR(80) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    city VARCHAR(64) NOT NULL,
    county VARCHAR(64) NOT NULL,
    completed_order_count BIGINT UNSIGNED NOT NULL,
    source_file VARCHAR(512) NOT NULL,
    collected_at VARCHAR(40) NOT NULL,
    UNIQUE KEY uk_completed_county (collection_run_id,period_start,period_end,city,county),
    KEY idx_completed_county_period (period_start,period_end),
    FOREIGN KEY (collection_run_id) REFERENCES collection_run(collection_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
