"""源数据集定义及已确认的业务主键。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dataset:
    code: str
    name: str
    source_system: str
    key_column: str


DATASETS: dict[str, Dataset] = {
    "orch_opening": Dataset("orch_opening", "编排专线开通情况", "编排", "订单号"),
    "orch_install": Dataset("orch_install", "编排互联网专线新装单", "编排", "订单号"),
    "integration_opening": Dataset(
        "integration_opening", "一体化售中开通工单", "一体化", "工单号"
    ),
    "eoms_complaint": Dataset("eoms_complaint", "EOMS政企投诉工单", "EOMS", "id"),
    "youshu_install": Dataset("youshu_install", "有数企宽新装清单", "有数", "工单id"),
    "youshu_complaint": Dataset(
        "youshu_complaint", "有数企宽投诉清单", "有数", "工单号"
    ),
}


def get_dataset(code: str) -> Dataset:
    try:
        return DATASETS[code]
    except KeyError as exc:
        choices = ", ".join(DATASETS)
        raise ValueError(f"未知数据集 {code!r}，可选值：{choices}") from exc
