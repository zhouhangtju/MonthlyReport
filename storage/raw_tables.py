"""Fixed XLSX column layouts, safe identifiers and relational raw reads."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from config.datasets import DATASETS, get_dataset


def quote_identifier(name: str) -> str:
    if not name or len(name) > 64 or "\x00" in name or name.endswith(" "):
        raise ValueError(f"不支持的 MySQL 字段名: {name!r}")
    return "`" + name.replace("`", "``") + "`"


@lru_cache(maxsize=1)
def layouts() -> dict:
    return json.loads((Path(__file__).resolve().parents[1] / "config/raw_columns.json").read_text("utf-8"))


def raw_table(dataset_code: str) -> str:
    return get_dataset(dataset_code).code


def version_table(dataset_code: str) -> str:
    return raw_table(dataset_code) + "_version"


def source_columns(dataset_code: str) -> list[str]:
    columns = [str(value).strip() for value in layouts()[raw_table(dataset_code)]["headers"]]
    if len({name.casefold() for name in columns}) != len(columns):
        raise ValueError(f"{dataset_code}: 表头重复")
    for column in columns:
        quote_identifier(column)
    return columns


def validate_headers(dataset_code: str, headers: list[str]) -> None:
    dataset = get_dataset(dataset_code)
    if len(headers) != len(set(h.casefold() for h in headers)):
        raise ValueError("表头包含重复列名")
    for name in headers:
        quote_identifier(name)
    if dataset.auto_increment:
        if any(h.casefold() == 'id' for h in headers):
            raise ValueError('源文件 id 与自增主键冲突')
    elif dataset.key_column not in headers:
        raise ValueError(f'表头缺少主键列 {dataset.key_column}')


def database_columns(connection, dataset_code):
    dataset = get_dataset(dataset_code)
    return [r['Field'] for r in connection.execute(
        f'SHOW COLUMNS FROM {quote_identifier(dataset.code)}').fetchall()
        if not (dataset.auto_increment and r['Field'] == 'id')]


def ensure_columns(connection, dataset_code, headers):
    # Called under the dataset import lock, after staging and before data writes.
    columns = database_columns(connection, dataset_code)
    folded = {c.casefold(): c for c in columns}
    for name in headers:
        if name.casefold() in folded and folded[name.casefold()] != name:
            raise ValueError(f'字段名大小写冲突：{name}')
    extra = [h for h in headers if h not in columns]
    if extra:
        connection.execute(f'ALTER TABLE {quote_identifier(dataset_code)} ' +
                           ', '.join(f'ADD COLUMN {quote_identifier(h)} LONGTEXT NULL' for h in extra))
    return columns + extra


def table_statements() -> list[str]:
    statements = []
    for code, dataset in DATASETS.items():
        columns = source_columns(code)
        if dataset.auto_increment and any(c.casefold() == "id" for c in columns):
            raise ValueError(f"{code}: 源文件的 id 与自增主键冲突")
        if not dataset.auto_increment and dataset.key_column not in columns:
            raise ValueError(f"{code}: 缺少主键列 {dataset.key_column}")
        definitions = ["`id` BIGINT PRIMARY KEY AUTO_INCREMENT"] if dataset.auto_increment else []
        for column in columns:
            sql_type = "VARCHAR(255) COLLATE utf8mb4_bin NOT NULL" if column == dataset.key_column else "LONGTEXT"
            definitions.append(f"{quote_identifier(column)} {sql_type}")
        if not dataset.auto_increment:
            definitions.append(f"PRIMARY KEY ({quote_identifier(dataset.key_column)})")
        statements.append(f"CREATE TABLE IF NOT EXISTS `{code}` (\n    " + ",\n    ".join(definitions) +
                          "\n) ENGINE=InnoDB ROW_FORMAT=DYNAMIC DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;")
        # No FK to current rows: period replacement retains old row versions.
        statements.append(f"""CREATE TABLE IF NOT EXISTS `{code}_version` (
    version_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    source_record_id VARCHAR(255) COLLATE utf8mb4_bin NOT NULL,
    run_id VARCHAR(80) NOT NULL,
    row_hash CHAR(64) NOT NULL,
    source_data LONGTEXT NOT NULL,
    observed_at VARCHAR(40) NOT NULL,
    UNIQUE KEY uk_version_record_hash (source_record_id, row_hash),
    KEY idx_version_run (run_id),
    FOREIGN KEY (run_id) REFERENCES etl_run(run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;""")
    return statements


def check_existing_layouts(connection) -> None:
    rows = connection.execute(
        "SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name, COLUMN_KEY AS column_key "
        "FROM information_schema.columns WHERE table_schema=DATABASE() ORDER BY ORDINAL_POSITION"
    ).fetchall()
    actual = {}
    for row in rows:
        actual.setdefault(row["table_name"], []).append(row)
    for code, dataset in DATASETS.items():
        if code not in actual:
            continue
        expected = (["id"] if dataset.auto_increment else []) + source_columns(code)
        found = actual[code]
        if not set(expected).issubset({r["column_name"] for r in found}) or [r["column_name"] for r in found if r["column_key"] == "PRI"] != [dataset.key_column]:
            raise RuntimeError(f"{code} 是旧表或字段不匹配；请在新数据库初始化并重新导入本地文件，程序不会删除或覆盖旧表结构")


def read_records(connection, dataset_code: str, period_start: str | None = None,
                 period_end: str | None = None) -> list[dict]:
    dataset = get_dataset(dataset_code)
    table = quote_identifier(dataset.code)
    if dataset.auto_increment:
        if not period_start or not period_end:
            raise ValueError(f"{dataset_code}: 出入库读取必须指定完整周期")
        batch = connection.execute(
            "SELECT run_id FROM raw_period_batch WHERE dataset_code=? AND period_start=? AND period_end=?",
            (dataset_code, period_start, period_end),
        ).fetchone()
        if batch is None:
            raise ValueError(f"{dataset_code}: 指定周期尚未导入")
        records = connection.execute(
            f"SELECT r.* FROM {table} r JOIN raw_period_row p ON p.row_id=r.id "
            "WHERE p.dataset_code=? AND p.period_start=? AND p.period_end=? ORDER BY p.source_row_number",
            (dataset_code, period_start, period_end),
        ).fetchall()
    else:
        records = connection.execute(f"SELECT * FROM {table}").fetchall()
    return [{**row, "_source_record_id": str(row[dataset.key_column])} for row in records]
