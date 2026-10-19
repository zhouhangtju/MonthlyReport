-- Back up the old installation tables before rebuilding their schema.
-- Stop collection/import jobs before running this script.
-- Run the preflight section first. If either backup name exists, STOP.
-- Do not use mysql --force: execution must stop on errors.
-- This script does not rebuild tables or clear audit/coverage records.

USE quality_assessment;

-- Preflight: both source tables must exist; both backup names must be absent.
SHOW TABLES LIKE 'youshu_install%';
SELECT COUNT(*) AS installation_rows_before FROM youshu_install;
SELECT COUNT(*) AS version_rows_before FROM youshu_install_version;

-- Rename both tables in one statement, preserving the old data and structure.
RENAME TABLE
  youshu_install TO youshu_install_backup_20261013,
  youshu_install_version TO youshu_install_version_backup_20261013;

-- Compare these counts with the preflight results.
SELECT COUNT(*) AS installation_rows_after FROM youshu_install_backup_20261013;
SELECT COUNT(*) AS version_rows_after FROM youshu_install_version_backup_20261013;

-- Leave collection/import jobs stopped until the new schema and code are ready.
