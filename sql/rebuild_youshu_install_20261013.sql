-- Run once after backup_youshu_install_20261013.sql, with collection/import jobs stopped.
-- Both old backup tables must exist and both original table names must be absent.
-- Do not use mysql --force: stop on any error. Do not rerun after importing new data.
-- Shared history is copied before invalidation. Old ETL rows remain for FK references.

USE quality_assessment;

-- These statements fail before any new table is created if the old backups are absent.
SELECT COUNT(*) AS old_install_rows FROM youshu_install_backup_20261013;
SELECT COUNT(*) AS old_version_rows FROM youshu_install_version_backup_20261013;

CREATE TABLE `youshu_install` (
    `地市` LONGTEXT,
    `工单id` VARCHAR(255) COLLATE utf8mb4_bin NOT NULL,
    `装维人员名称` LONGTEXT,
    `装维电话` LONGTEXT,
    `动作类型` LONGTEXT,
    `宽带账号` LONGTEXT,
    `用户电话` LONGTEXT,
    `覆盖场景` LONGTEXT,
    `工单类型` LONGTEXT,
    `是否合装` LONGTEXT,
    `是否酒店类业务` LONGTEXT,
    `开通时长` LONGTEXT,
    `工单状态` LONGTEXT,
    `报结是否及时` LONGTEXT,
    `是否暂未超时` LONGTEXT,
    `派单时间` LONGTEXT,
    `首次派单时间` LONGTEXT,
    `首次进入已配置派发时间` LONGTEXT,
    `打卡时间` LONGTEXT,
    `最后预约时间` LONGTEXT,
    `最后预约上门开始时间` LONGTEXT,
    `最后预约上门结束时间` LONGTEXT,
    `是否当天回单` LONGTEXT,
    `需归档时间` LONGTEXT,
    `状态更新时间` LONGTEXT,
    `当前取数时间` LONGTEXT,
    `开通时长-派单时间` LONGTEXT,
    PRIMARY KEY (`工单id`)
) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `youshu_install_version` (
    version_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_record_id VARCHAR(255) COLLATE utf8mb4_bin NOT NULL,
    run_id VARCHAR(80) NOT NULL,
    row_hash CHAR(64) NOT NULL,
    source_data LONGTEXT NOT NULL,
    observed_at VARCHAR(40) NOT NULL,
    UNIQUE KEY uk_version_record_hash (source_record_id, row_hash),
    KEY idx_version_run (run_id),
    FOREIGN KEY (run_id) REFERENCES etl_run(run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Preserve the old installation-specific shared records.
CREATE TABLE youshu_install_etl_backup_20261013 LIKE etl_run;
INSERT INTO youshu_install_etl_backup_20261013
SELECT * FROM etl_run WHERE dataset_code = 'youshu_install';

CREATE TABLE youshu_install_collection_backup_20261013 LIKE collection_run;
INSERT INTO youshu_install_collection_backup_20261013
SELECT * FROM collection_run WHERE dataset_code = 'youshu_install';

CREATE TABLE youshu_install_audit_backup_20261013 LIKE raw_record_audit;
INSERT INTO youshu_install_audit_backup_20261013
SELECT * FROM raw_record_audit WHERE dataset_code = 'youshu_install';

-- Invalidate only the saved old records so the same period can be collected again.
START TRANSACTION;
UPDATE etl_run e
JOIN youshu_install_etl_backup_20261013 b ON b.run_id = e.run_id
SET e.status = 'superseded'
WHERE e.dataset_code = 'youshu_install' AND e.status = 'success';

UPDATE collection_run c
JOIN youshu_install_collection_backup_20261013 b
  ON b.collection_run_id = c.collection_run_id
SET c.status = 'superseded'
WHERE c.dataset_code = 'youshu_install' AND c.status = 'success';

DELETE a FROM raw_record_audit a
JOIN youshu_install_audit_backup_20261013 b
  ON b.dataset_code = a.dataset_code AND b.source_record_id = a.source_record_id
WHERE a.dataset_code = 'youshu_install';
COMMIT;

-- Expect 27 business columns and zero rows in both new tables.
SHOW COLUMNS FROM youshu_install;
SELECT COUNT(*) AS new_install_rows FROM youshu_install;
SELECT COUNT(*) AS new_version_rows FROM youshu_install_version;
