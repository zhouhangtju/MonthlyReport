"""Import exported CSV/XLSX data with archiving, deduplication and audit logs."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from openpyxl import load_workbook

from config.datasets import Dataset
from storage.database import connect, initialize
from storage.orchestration_tables import upsert as upsert_orchestration


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_cell(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, str):
        return value.strip()
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def row_payload(row: dict[str, object]) -> tuple[str, str]:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def iter_csv(path: Path) -> Iterator[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            raise ValueError("CSV 缺少表头")
        for row in reader:
            yield {str(key).strip(): normalize_cell(value) for key, value in row.items()}


def iter_excel(path: Path) -> Iterator[dict[str, object]]:
    with path.open("rb") as probe:
        signature = probe.read(8)
    if signature.startswith(b"\xd0\xcf\x11\xe0"):
        yield from iter_legacy_xls(path)
        return
    # 使用文件对象可兼容扩展名为 .xls、实际内容为 XLSX 的平台导出文件。
    with path.open("rb") as source:
        workbook = load_workbook(source, read_only=True, data_only=True)
        try:
            sheet = workbook[workbook.sheetnames[0]]
            sheet.reset_dimensions()
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, None)
            if not header:
                raise ValueError("Excel 缺少表头")
            columns = [str(value).strip() if value is not None else "" for value in header]
            if not all(columns) or len(columns) != len(set(columns)):
                raise ValueError("Excel 表头包含空列名或重复列名")
            for values in rows:
                row = {
                    column: normalize_cell(values[index] if index < len(values) else None)
                    for index, column in enumerate(columns)
                }
                if any(value not in (None, "") for value in row.values()):
                    yield row
        finally:
            workbook.close()


def iter_legacy_xls(path: Path) -> Iterator[dict[str, object]]:
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError("读取传统 XLS 需要 xlrd，请安装 requirements.txt") from exc
    workbook = xlrd.open_workbook(path)
    sheet = workbook.sheet_by_index(0)
    if sheet.nrows == 0:
        raise ValueError("Excel 缺少表头")
    columns = [str(sheet.cell_value(0, index)).strip() for index in range(sheet.ncols)]
    if not all(columns) or len(columns) != len(set(columns)):
        raise ValueError("Excel 表头包含空列名或重复列名")
    for row_index in range(1, sheet.nrows):
        row: dict[str, object] = {}
        for column_index, column in enumerate(columns):
            cell = sheet.cell(row_index, column_index)
            value: object = cell.value
            if cell.ctype == xlrd.XL_CELL_DATE:
                value = xlrd.xldate_as_datetime(value, workbook.datemode)
            row[column] = normalize_cell(value)
        if any(value not in (None, "") for value in row.values()):
            yield row


def iter_rows(path: Path) -> Iterator[dict[str, object]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        yield from iter_excel(path)
    elif suffix in {".csv", ".tsv"}:
        if suffix == ".tsv":
            raise ValueError("TSV 暂未支持，请先转换为 CSV")
        yield from iter_csv(path)
    else:
        raise ValueError(f"不支持的文件格式：{suffix}")


def archive_file(path: Path, archive_root: Path, dataset: Dataset, digest: str) -> Path:
    day = datetime.now().strftime("%Y-%m-%d")
    target_dir = archive_root / dataset.code / day
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{digest[:12]}_{path.name}"
    if not target.exists():
        shutil.copy2(path, target)
    return target.resolve()


def import_file(
    database_path: Path,
    dataset: Dataset,
    source_path: Path,
    archive_root: Path | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    keep_local_source: bool = True,
) -> dict[str, object]:
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    initialize(database_path)
    digest = file_sha256(source_path)
    run_id = f"etl_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    from storage.raw_archive import archive_source
    archived = archive_source(source_path, database_path, dataset.code, period_start,
                              period_end, run_id, root=archive_root) if keep_local_source else None
    started_at = utc_now()
    counts = {"read": 0, "inserted": 0, "updated": 0, "unchanged": 0, "failed": 0}

    with connect(database_path) as connection:
        connection.execute(
            """INSERT INTO etl_run (
                run_id, dataset_code, source_system, source_file, archived_file,
                file_sha256, period_start, period_end, started_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')""",
            (
                run_id, dataset.code, dataset.source_system, str(source_path),
                str(archived) if archived else None, digest, period_start, period_end, started_at,
            ),
        )
        connection.commit()

        try:
            for row in iter_rows(source_path):
                counts["read"] += 1
                key = row.get(dataset.key_column)
                source_record_id = "" if key is None else str(key).strip()
                if not source_record_id:
                    counts["failed"] += 1
                    continue
                payload, row_hash = row_payload(row)
                existing = connection.execute(
                    """SELECT record_id, row_hash, first_run_id, first_seen_at
                       FROM raw_source_record
                       WHERE dataset_code = ? AND source_record_id = ?""",
                    (dataset.code, source_record_id),
                ).fetchone()
                observed_at = utc_now()
                if existing is None:
                    cursor = connection.execute(
                        """INSERT INTO raw_source_record (
                            dataset_code, source_system, source_record_id, source_data, row_hash,
                            first_run_id, last_run_id, first_seen_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            dataset.code, dataset.source_system, source_record_id, payload, row_hash,
                            run_id, run_id, observed_at, observed_at,
                        ),
                    )
                    record_id = cursor.lastrowid
                    counts["inserted"] += 1
                elif existing["row_hash"] == row_hash:
                    record_id = existing["record_id"]
                    connection.execute(
                        """UPDATE raw_source_record SET last_run_id = ?, last_seen_at = ?
                           WHERE record_id = ?""",
                        (run_id, observed_at, record_id),
                    )
                    counts["unchanged"] += 1
                else:
                    record_id = existing["record_id"]
                    connection.execute(
                        """UPDATE raw_source_record
                           SET source_data = ?, row_hash = ?, last_run_id = ?, last_seen_at = ?
                           WHERE record_id = ?""",
                        (payload, row_hash, run_id, observed_at, record_id),
                    )
                    counts["updated"] += 1
                connection.execute(
                    """INSERT OR IGNORE INTO raw_source_record_version
                       (record_id, run_id, row_hash, source_data, observed_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (record_id, run_id, row_hash, payload, observed_at),
                )
                upsert_orchestration(
                    connection, dataset.code, row, payload, row_hash,
                    run_id if existing is None else existing["first_run_id"],
                    run_id,
                    observed_at if existing is None else existing["first_seen_at"],
                    observed_at,
                )

            connection.execute(
                """UPDATE etl_run SET finished_at = ?, status = 'success', rows_read = ?,
                   rows_inserted = ?, rows_updated = ?, rows_unchanged = ?, rows_failed = ?
                   WHERE run_id = ?""",
                (
                    utc_now(), counts["read"], counts["inserted"], counts["updated"],
                    counts["unchanged"], counts["failed"], run_id,
                ),
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            connection.execute(
                """UPDATE etl_run SET finished_at = ?, status = 'failed', error_message = ?
                   WHERE run_id = ?""",
                (utc_now(), str(exc), run_id),
            )
            connection.commit()
            raise

    return {"run_id": run_id, "archived_file": str(archived) if archived else None, **counts}
