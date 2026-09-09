"""编排两个数据集的独立业务表投影。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


TABLES = {
    "orch_opening": "ods_orch_opening",
    "orch_install": "ods_orch_install",
}


def _value(row: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _projection(dataset_code: str, row: dict[str, Any]) -> tuple[Any, ...]:
    common = (
        _value(row, "订单号"),
        _value(row, "订单创建时间", "创建时间", "订单受理时间"),
        _value(row, "地市", "所属地市"),
        _value(row, "订单状态", "状态"),
        _value(row, "业务类型"),
        _value(row, "产品名称"),
        _value(row, "订单类型"),
    )
    if dataset_code == "orch_opening":
        business_time = _value(row, "订单结束时间", "结束时间", "完成时间", "订单完成时间", "报结时间")
    else:
        business_time = _value(row, "派单时间", "订单派单时间")
    return common + (business_time,)


def upsert(
    connection: sqlite3.Connection,
    dataset_code: str,
    row: dict[str, Any],
    payload: str,
    row_hash: str,
    first_run_id: str,
    last_run_id: str,
    first_seen_at: str,
    last_seen_at: str,
) -> None:
    table = TABLES.get(dataset_code)
    if not table:
        return
    order_no, created, city, status, business_type, product, order_type, business_time = _projection(dataset_code, row)
    time_column = "order_finished_at" if dataset_code == "orch_opening" else "dispatched_at"
    connection.execute(
        f"""INSERT INTO {table} (
            order_no, order_created_at, {time_column}, city, order_status,
            business_type, product_name, order_type, source_data, row_hash,
            first_run_id, last_run_id, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(order_no) DO UPDATE SET
            order_created_at=excluded.order_created_at,
            {time_column}=excluded.{time_column},
            city=excluded.city,
            order_status=excluded.order_status,
            business_type=excluded.business_type,
            product_name=excluded.product_name,
            order_type=excluded.order_type,
            source_data=excluded.source_data,
            row_hash=excluded.row_hash,
            last_run_id=excluded.last_run_id,
            last_seen_at=excluded.last_seen_at""",
        (
            order_no, created, business_time, city, status, business_type, product,
            order_type, payload, row_hash, first_run_id, last_run_id,
            first_seen_at, last_seen_at,
        ),
    )


def backfill_missing(connection: sqlite3.Connection) -> None:
    """为升级前已入库的编排记录补建独立业务表。"""
    for dataset_code, table in TABLES.items():
        records = connection.execute(
            f"""SELECT r.source_record_id, r.source_data, r.row_hash,
                       r.first_run_id, r.last_run_id, r.first_seen_at, r.last_seen_at
                FROM raw_source_record r
                LEFT JOIN {table} o ON o.order_no = r.source_record_id
                WHERE r.dataset_code=? AND o.order_no IS NULL""",
            (dataset_code,),
        ).fetchall()
        for record in records:
            upsert(
                connection, dataset_code, json.loads(record["source_data"]),
                record["source_data"], record["row_hash"], record["first_run_id"],
                record["last_run_id"], record["first_seen_at"], record["last_seen_at"],
            )
