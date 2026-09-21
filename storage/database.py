"""MySQL database connection and initialization.

The public functions keep their path argument for compatibility. MySQL
connection settings are defined in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3306
DEFAULT_DATABASE = "quality_assessment"
DEFAULT_USER = "root"
DEFAULT_PASSWORD = "123456"
DEFAULT_CHARSET = "utf8mb4"


def _load_pymysql():
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as exc:
        raise RuntimeError("缺少 pymysql，请先执行 python -m pip install -r requirements.txt") from exc
    return pymysql, DictCursor


def _config(include_database: bool = True) -> dict[str, Any]:
    config: dict[str, Any] = {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "user": DEFAULT_USER,
        "password": DEFAULT_PASSWORD,
        "charset": DEFAULT_CHARSET,
        "autocommit": False,
    }

    if include_database:
        config["database"] = DEFAULT_DATABASE

    return config


def _database_name() -> str:
    return DEFAULT_DATABASE


def _translate_placeholders(sql: str) -> str:
    """Translate sqlite-style ``?`` placeholders to DB-API ``%s`` placeholders."""
    return sql.replace("?", "%s")


def _split_sql_script(script: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    index = 0
    while index < len(script):
        char = script[index]
        next_char = script[index + 1] if index + 1 < len(script) else ""
        if not in_single and not in_double and char == "-" and next_char == "-":
            end = script.find("\n", index)
            if end == -1:
                break
            index = end + 1
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        if char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        index += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


class MySQLCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor

    @property
    def lastrowid(self) -> int:
        return self._cursor.lastrowid

    def execute(self, sql: str, params: Iterable[Any] | None = None):
        self._cursor.execute(_translate_placeholders(sql), params)
        return self

    def executemany(self, sql: str, params: Iterable[Iterable[Any]]):
        self._cursor.executemany(_translate_placeholders(sql), params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size: int | None = None):
        return self._cursor.fetchmany(size)

    def __iter__(self):
        return iter(self._cursor)

    def close(self) -> None:
        self._cursor.close()


@dataclass
class MySQLConnection:
    _connection: Any

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> MySQLCursor:
        cursor = MySQLCursor(self._connection.cursor())
        return cursor.execute(sql, params)

    def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> MySQLCursor:
        cursor = MySQLCursor(self._connection.cursor())
        return cursor.executemany(sql, params)

    def executescript(self, script: str) -> None:
        for statement in _split_sql_script(script):
            self.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MySQLConnection":
        return self

    def __exit__(self, exc_type, _exc, _tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()


def _connect_raw(*, include_database: bool = True):
    pymysql, DictCursor = _load_pymysql()
    return pymysql.connect(cursorclass=DictCursor, **_config(include_database=include_database))


def connect(path: Path | None = None) -> MySQLConnection:
    del path
    return MySQLConnection(_connect_raw(include_database=True))


def initialize(path: Path | None = None) -> None:
    del path
    pymysql, _DictCursor = _load_pymysql()
    database_name = _database_name()
    with MySQLConnection(_connect_raw(include_database=False)) as connection:
        safe_name = re.sub(r"[^0-9A-Za-z_$]", "", database_name)
        if safe_name != database_name or not safe_name:
            raise ValueError(f"MySQL 数据库名不安全：{database_name!r}")
        connection.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
            f"DEFAULT CHARACTER SET {DEFAULT_CHARSET} COLLATE utf8mb4_unicode_ci"
        )
    schema_path = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")
    with connect(None) as connection:
        from storage.raw_tables import check_existing_layouts

        check_existing_layouts(connection)
        try:
            connection.executescript(schema)
            # A deduplicated inventory row can belong to several periods.
            indexes = connection.execute("SHOW INDEX FROM raw_period_row").fetchall()
            if any(row['Key_name'] == 'uk_raw_period_row_id' for row in indexes):
                connection.execute(
                    "ALTER TABLE raw_period_row DROP INDEX uk_raw_period_row_id, "
                    "ADD INDEX idx_raw_period_row_id (dataset_code, row_id), "
                    "ADD UNIQUE INDEX uk_raw_period_row_once "
                    "(dataset_code, period_start, period_end, row_id)"
                )
        except pymysql.err.OperationalError as exc:
            raise RuntimeError(f"MySQL 初始化失败：{exc}") from exc
        # Initialization only manages schema; calculations read raw tables directly.


def _covered_by_intervals(
    rows: list[dict[str, Any]],
    period_start: str,
    period_end: str,
) -> bool:
    requested_start = date.fromisoformat(period_start)
    requested_end = date.fromisoformat(period_end)
    intervals = sorted(
        (
            max(requested_start, date.fromisoformat(row["period_start"])),
            min(requested_end, date.fromisoformat(row["period_end"])),
        )
        for row in rows
    )
    cursor = requested_start
    for start, end in intervals:
        if end < cursor:
            continue
        if start > cursor:
            return False
        cursor = max(cursor, end + timedelta(days=1))
        if cursor > requested_end:
            return True
    return cursor > requested_end


def has_successful_coverage(
    path: Path,
    dataset_code: str,
    period_start: str,
    period_end: str,
) -> bool:
    del path
    try:
        initialize(None)
        with connect(None) as connection:
            rows = connection.execute(
                """SELECT period_start, period_end
                   FROM etl_run
                   WHERE dataset_code = ?
                     AND status = 'success'
                     AND rows_failed = 0
                     AND period_start IS NOT NULL
                     AND period_end IS NOT NULL
                     AND period_end >= ?
                     AND period_start <= ?
                     AND NOT EXISTS (
                         SELECT 1 FROM data_retention_purge p
                         WHERE p.dataset_code=etl_run.dataset_code
                           AND p.purged_at >= etl_run.started_at
                           AND p.period_end >= etl_run.period_start
                           AND p.period_start <= etl_run.period_end
                     )""",
                (dataset_code, period_start, period_end),
            ).fetchall()
    except Exception:
        return False
    return _covered_by_intervals(rows, period_start, period_end)


def has_collection_coverage(
    path: Path,
    dataset_code: str,
    period_start: str,
    period_end: str,
) -> bool:
    del path
    try:
        initialize(None)
        with connect(None) as connection:
            rows = connection.execute(
                """SELECT period_start, period_end FROM collection_run
                   WHERE dataset_code = ? AND status = 'success'
                     AND imported_files = produced_files
                     AND produced_files > 0
                     AND period_end >= ? AND period_start <= ?
                     AND NOT EXISTS (
                         SELECT 1 FROM data_retention_purge p
                         WHERE p.dataset_code=collection_run.dataset_code
                           AND p.purged_at >= collection_run.started_at
                           AND p.period_end >= collection_run.period_start
                           AND p.period_start <= collection_run.period_end
                     )""",
                (dataset_code, period_start, period_end),
            ).fetchall()
    except Exception:
        return False
    return _covered_by_intervals(rows, period_start, period_end)
