"""Normalize dispatch export fields and retain the first appointment column."""

from collections import Counter


FIELD_ALIASES = {"订单ID": "工单id", "用户账号": "宽带账号"}
DUPLICATE_FIELD = "最后预约时间"


def map_headers(headers: list[str]) -> list[str]:
    mapped = [FIELD_ALIASES.get(header, header) for header in headers]
    counts = Counter(header.casefold() for header in mapped)
    if not mapped or not all(mapped):
        raise ValueError("文件表头为空，或包含空列名")
    for name, count in counts.items():
        if count > 1 and not (name == DUPLICATE_FIELD and count == 2):
            raise ValueError(f"企宽新装表头重复或映射冲突：{name}")
    return mapped


def merge_cells(columns: list[str], values: list[object]) -> dict[str, object]:
    row: dict[str, object] = {}
    for index, column in enumerate(columns):
        value = values[index] if index < len(values) else None
        if column not in row:
            row[column] = value
    return row
