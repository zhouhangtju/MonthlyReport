"""Module-specific result storage and the stable reporting read contract."""
import json

TABLES = {
    'terminal_recovery': 'result_terminal_recovery',
    'dedicated_line_opening_withdrawal_rate': 'result_opening_withdrawal',
    'dedicated_line_install_fault_rate': 'result_dedicated_line_install_fault',
    'qikuan_install_fault_rate': 'result_qikuan_install_fault',
    'commercial_customer_install_fault_rate': 'result_commercial_install_fault',
    'dedicated_line_repeat_complaint_rate': 'result_dedicated_line_repeat_complaint',
    'qianliyan_repeat_complaint_rate': 'result_qianliyan_repeat_complaint',
    'orchestration_opening_metrics': 'result_orchestration_opening',
}

# All original dimensions remain in the canonical JSON for exact, lossless reads.
# Explicit columns expose the same dimensions for direct SQL inspection.
RATE_FIELDS = {'scope': 'scope', 'city': 'city', 'business_type': 'business_type'}
FIELDS = {owner: dict(RATE_FIELDS) for owner in TABLES}
FIELDS['orchestration_opening_metrics'] = {
    'month': 'month', 'comparison_month': 'comparison_month', 'end_month': 'end_month',
    'city': 'city', 'county': 'county', 'product': 'product', 'stage': 'stage', 'field': 'source_field',
    'automatic_value': 'automatic_value',
}
FIELDS['terminal_recovery'] = {
    'sheet': 'sheet_name', 'table': 'summary_type', 'row_index': 'row_index',
    'column_index': 'column_index', 'label_column': 'label_column',
    'label': 'row_label', 'column': 'column_label',
}


def table_for(owner):
    if owner not in TABLES:
        raise ValueError(f'未配置的指标模块：{owner}')
    return TABLES[owner]


def insert_results(connection, owner, run_id, results):
    table = table_for(owner)
    fields = FIELDS[owner]
    values = []
    for item in results:
        dimension = item['dimension']
        unknown = set(dimension) - set(fields)
        if unknown:
            raise ValueError(f'{owner}: 未映射的结果维度 {sorted(unknown)}')
        payload = json.dumps(dimension, ensure_ascii=False, sort_keys=True, allow_nan=False)
        values.append((run_id, item['metric_code'], item['dimension_type'], payload,
                       item['numerator'], item['denominator'], item['metric_value']))
    if values:
        connection.executemany(
            f'INSERT INTO `{table}` (metric_run_id, metric_code, dimension_type, dimension_value, '
            'numerator, denominator, metric_value) VALUES (?, ?, ?, ?, ?, ?, ?)', values)


def read_results(connection, owner, run_id):
    rows = connection.execute(
        f'SELECT result_id, metric_run_id, metric_code, dimension_type, dimension_value, '
        f'numerator, denominator, metric_value FROM `{table_for(owner)}` '
        'WHERE metric_run_id=? ORDER BY result_id', (run_id,)).fetchall()
    if not rows:
        legacy = connection.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() "
            "AND table_name='ads_metric_result'").fetchone()
        if legacy and connection.execute(
            'SELECT 1 FROM ads_metric_result WHERE metric_run_id=? LIMIT 1', (run_id,)).fetchone():
            raise RuntimeError('该任务仍在旧结果表中，请先运行 storage/migrate_metric_results.py --apply')
    return [dict(row) for row in rows]


def schema_statements():
    statements = []
    for owner, table in TABLES.items():
        columns = []
        for key, column in FIELDS[owner].items():
            kind = 'INT' if key in {'row_index', 'column_index'} else 'VARCHAR(255)'
            columns.append(f"`{column}` {kind} GENERATED ALWAYS AS "
                           f"(JSON_UNQUOTE(JSON_EXTRACT(dimension_value, '$.{key}'))) STORED")
        statements.append(f'''CREATE TABLE IF NOT EXISTS `{table}` (
    result_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    metric_run_id VARCHAR(80) NOT NULL,
    metric_code VARCHAR(120) NOT NULL,
    dimension_type VARCHAR(120) NOT NULL,
    dimension_value LONGTEXT NOT NULL,
    dimension_value_hash CHAR(64) GENERATED ALWAYS AS (SHA2(dimension_value, 256)) STORED,
    {', '.join(columns)},
    numerator DOUBLE,
    denominator DOUBLE,
    metric_value DOUBLE,
    UNIQUE KEY uk_result_dimension (metric_run_id, metric_code, dimension_type, dimension_value_hash),
    FOREIGN KEY (metric_run_id) REFERENCES metric_run(metric_run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;''')
    return statements
