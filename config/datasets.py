"""源数据集定义及已确认的业务主键。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dataset:
    code: str
    name: str
    source_system: str
    key_column: str

    @property
    def auto_increment(self) -> bool:
        return self.code in {"integration_terminal_outbound", "integration_terminal_inbound"}


DATASETS: dict[str, Dataset] = {
    "terminal_material_names": Dataset("terminal_material_names", "终端物料名称映射", "本地配置", "物料名称"),
    "integration_removal_order": Dataset("integration_removal_order", "一体化专线拆机清单", "一体化", "工单号"),
    "eoms_service_removal_order": Dataset("eoms_service_removal_order", "EOMS服务类拆机工单", "EOMS", "工单号"),
    "integration_terminal_outbound": Dataset("integration_terminal_outbound", "终端出库", "一体化", "id"),
    "integration_terminal_inbound": Dataset("integration_terminal_inbound", "终端入库", "一体化", "id"),
    "integration_material_baseline": Dataset("integration_material_baseline", "全省物资基准库", "一体化", "物料基准ID"),
    "orch_opening": Dataset("orch_opening", "编排专线开通情况", "编排", "订单号"),
    "orch_install": Dataset("orch_install", "编排互联网专线新装单", "编排", "订单号"),
    "integration_opening": Dataset(
        "integration_opening", "一体化售中开通工单", "一体化", "工单号"
    ),
    "eoms_complaint": Dataset("eoms_complaint", "EOMS政企投诉工单", "EOMS", "工单号"),
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
