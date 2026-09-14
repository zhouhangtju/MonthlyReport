"""Lossless terminal recovery source snapshots and collection coverage."""

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook


SOURCE_FILES = {
    "integration_removal_order": "一体化专线拆机清单_{month}.xlsx",
    "eoms_service_removal_order": "服务类产品支撑工单_{month}.xlsx",
    "integration_terminal_inbound": "终端入库_{month}.xlsx",
    "integration_material_baseline": "全省物资基准库.xlsx",
    "terminal_material_names": "物料名称表.xlsx",
}

REPORT_SHEETS = (
    "物料名称表", "全省物资基准库", "一体化专线拆机清单（不含小微版）",
    "EOMS服务类拆机清单", "一体化拆回设备清单", "拆除清单汇总",
    "按地市回收率汇总", "匹配后拆回设备清单（三类标签已去重）",
    "sheet2", "sheet3", "sheet1",
)


def connection(database):
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database, timeout=60)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tr_source_snapshot (
            snapshot_id TEXT PRIMARY KEY, dataset_code TEXT NOT NULL,
            period_start TEXT NOT NULL, period_end TEXT NOT NULL,
            etl_run_id TEXT NOT NULL, created_at TEXT NOT NULL,
            filename TEXT NOT NULL, sha256 TEXT NOT NULL,
            row_count INTEGER NOT NULL, workbook BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tr_source_row (
            snapshot_id TEXT NOT NULL REFERENCES tr_source_snapshot(snapshot_id),
            row_number INTEGER NOT NULL, cells_json TEXT NOT NULL,
            PRIMARY KEY(snapshot_id, row_number)
        );
    """)


def encode_cell(value):
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    return value


def decode_cell(value):
    if isinstance(value, dict):
        if "datetime" in value:
            return datetime.fromisoformat(value["datetime"])
        if "date" in value:
            return date.fromisoformat(value["date"])
    return value


def save_source(database, code, source, start, end, etl_run_id):
    """Store full ordered cell data plus the original workbook for formatting."""
    source = Path(source)
    content = source.read_bytes()
    snapshot_id = uuid.uuid4().hex
    from storage.raw_archive import archive_source
    archive_source(source, database, code, start, end, etl_run_id, role="original")
    wb = load_workbook(BytesIO(content), read_only=True, data_only=False)
    try:
        ws = wb.active
        with closing(connection(database)) as conn:
            initialize(conn)
            with conn:
                conn.execute("INSERT INTO tr_source_snapshot VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (snapshot_id, code, start, end, etl_run_id,
                              datetime.now().isoformat(), source.name,
                              hashlib.sha256(content).hexdigest(), ws.max_row, content))
                conn.executemany("INSERT INTO tr_source_row VALUES (?,?,?)", (
                    (snapshot_id, number, json.dumps([encode_cell(v) for v in row], ensure_ascii=False))
                    for number, row in enumerate(ws.iter_rows(values_only=True), 1)
                ))
    finally:
        wb.close()
    return snapshot_id


def restore_sources(database, start, end, output_dir):
    """Select exact-period snapshots, never fall back to raw latest-state records."""
    if not Path(database).is_file():
        raise FileNotFoundError(database)
    output_dir = Path(output_dir)
    snapshots = {}
    with closing(connection(database)) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='tr_source_snapshot'").fetchone():
            raise ValueError("No terminal source snapshots; import sources first")
        for code in SOURCE_FILES:
            row = conn.execute("""SELECT * FROM tr_source_snapshot
                WHERE dataset_code=? AND period_start=? AND period_end=?
                ORDER BY created_at DESC, rowid DESC LIMIT 1""", (code, start, end)).fetchone()
            if row is None:
                raise ValueError(f"Missing source snapshot: {code} ({start}..{end})")
            snapshots[code] = row
        output_dir.mkdir(parents=True, exist_ok=True)
        for code, snapshot in snapshots.items():
            if hashlib.sha256(snapshot["workbook"]).hexdigest() != snapshot["sha256"]:
                raise ValueError(f"Corrupted source snapshot: {code}")
            wb = load_workbook(BytesIO(snapshot["workbook"]), data_only=False)
            try:
                ws = wb.active
                count = 0
                for number, cells_json in conn.execute(
                    "SELECT row_number,cells_json FROM tr_source_row WHERE snapshot_id=? ORDER BY row_number",
                    (snapshot["snapshot_id"],),
                ):
                    count += 1
                    if number != count:
                        raise ValueError(f"Non-contiguous source rows: {code}")
                    for column, value in enumerate(json.loads(cells_json), 1):
                        cell = ws.cell(number, column)
                        # Merged-cell placeholders have no writable value.
                        if cell.__class__.__name__ != "MergedCell":
                            cell.value = decode_cell(value)
                if count != snapshot["row_count"]:
                    raise ValueError(f"Incomplete source snapshot: {code}")
                wb.save(output_dir / SOURCE_FILES[code].format(month=start[:7]))
            finally:
                wb.close()
    return {code: row["snapshot_id"] for code, row in snapshots.items()}


def source_run_ids(database, snapshots):
    with closing(connection(database)) as conn:
        return list(dict.fromkeys(
            conn.execute("SELECT etl_run_id FROM tr_source_snapshot WHERE snapshot_id=?", (snapshot,)).fetchone()[0]
            for snapshot in snapshots.values()
        ))


def has_source_coverage(database, codes, start, end):
    if not Path(database).is_file():
        return False
    with closing(connection(database)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='tr_source_snapshot'").fetchone():
            return False
        return all(conn.execute(
            "SELECT 1 FROM tr_source_snapshot WHERE dataset_code=? AND period_start=? AND period_end=? LIMIT 1",
            (code, start, end),
        ).fetchone() for code in codes)
