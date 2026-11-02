-- One-time migration for databases created with the former generic names.
-- Run this instead of the create script when the old tables contain data.
-- MySQL RENAME TABLE preserves rows, indexes and foreign keys.

RENAME TABLE
    youshu_install_completed_city TO youshu_qikuan_install_completed_city,
    youshu_install_completed_county TO youshu_qikuan_install_completed_county;

UPDATE collection_run
SET dataset_code = CASE dataset_code
    WHEN 'youshu_install_completed' THEN 'youshu_qikuan_install_completed'
    WHEN 'youshu_install_completed_history_city' THEN 'youshu_qikuan_install_completed_history_city'
    ELSE dataset_code
END
WHERE dataset_code IN (
    'youshu_install_completed',
    'youshu_install_completed_history_city'
);

UPDATE etl_run
SET dataset_code = CASE dataset_code
    WHEN 'youshu_install_completed_city' THEN 'youshu_qikuan_install_completed_city'
    WHEN 'youshu_install_completed_county' THEN 'youshu_qikuan_install_completed_county'
    ELSE dataset_code
END
WHERE dataset_code IN (
    'youshu_install_completed_city',
    'youshu_install_completed_county'
);
