"""Validate report 47422 exports before marking collection complete."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from storage.importer import iter_rows, read_headers, row_payload
from storage.raw_tables import source_columns


def default_period(today: date | None = None) -> tuple[str, str]:
    """Return the complete calendar month three months before Beijing today."""
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    month_index = today.year * 12 + today.month - 1 - 3
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return (f"{year:04d}-{month:02d}-01",
            f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}")


def validate_period(start: str, end: str) -> None:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("日期须为 YYYY-MM-DD") from exc
    if first.isoformat() != start or last.isoformat() != end or first > last:
        raise ValueError("日期范围无效，须为 YYYY-MM-DD 且开始日期不晚于结束日期")


def validate_exports(paths: list[Path]) -> dict[str, int]:
    expected = source_columns("youshu_install_list")
    seen: dict[str, str] = {}
    rows = duplicates = 0
    for path in paths:
        headers = read_headers(path, "youshu_install_list")
        if headers != expected:
            raise ValueError(f"{path.name}: 企宽装机清单应为指定的19列，实际表头与报表47422不一致")
        for number, row in enumerate(iter_rows(path, "youshu_install_list"), 2):
            rows += 1
            order_id = str(row.get("工单id") or "").strip()
            if not order_id:
                raise ValueError(f"{path.name} 第{number}行：工单id为空")
            nettype = str(row.get("宽带类型") or "").strip()
            if nettype not in {"1", "1.0"}:
                raise ValueError(f"{path.name} 第{number}行：宽带类型不是 nettype=1")
            if str(row.get("工单状态") or "").strip() != "已报结":
                raise ValueError(f"{path.name} 第{number}行：工单状态不是已报结")
            payload = {key: row.get(key) for key in expected}
            payload["工单id"] = order_id
            _source, digest = row_payload(payload)
            previous = seen.get(order_id)
            if previous is not None and previous != digest:
                raise ValueError(f"{path.name} 第{number}行：工单id {order_id} 在导出批次中内容冲突")
            if previous is not None:
                duplicates += 1
            else:
                seen[order_id] = digest
    return {"rows": rows, "unique_orders": len(seen), "duplicate_rows": duplicates}
