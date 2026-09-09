"""EOMS 取数后的轻量字段补全规则。"""

from __future__ import annotations

import logging


def fill_missing_account_with_phone(
    rows: list,
    *,
    logger: logging.Logger | None = None,
) -> list:
    """计费号码仍为空时使用手机号码补位，不覆盖已有计费号码。"""
    empty_values = {"", "nan", "none", "null", "无"}
    filled = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        account = str(row.get("accountCode") or "").strip()
        phone = str(row.get("jtPhone") or "").strip()
        if account.lower() in empty_values and phone.lower() not in empty_values:
            row["accountCode"] = phone
            row["accountCodeFillSource"] = "手机号码补位"
            filled += 1
    if logger is not None:
        logger.info("计费号码仍为空时使用手机号码补位: %s 条", filled)
    return rows
