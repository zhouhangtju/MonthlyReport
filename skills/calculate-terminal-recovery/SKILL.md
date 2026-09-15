---
name: calculate-terminal-recovery
description: 从 SQLite 源快照计算线上口径的终端回收率，生成完整 Excel、两张汇总 sheet 的 JSON 及数据库指标。用户提到终端回收率汇总、终端回收算数或完整终端回收流程时使用。
---

# 终端回收率：线上算数

唯一正式入口为 `metrics/terminal_recovery/terminal_recovery_export_online.py`。不要调用或重建已删除的复现版，不用人工指定单据保留规则。

## 前置条件与完整流程

定位包含 `pyproject.toml` 的项目根目录，在该目录运行已安装依赖的 Python 3.10+。将用户月份转换为含年份的月初和月末；所有步骤用同一周期、同一数据库绝对路径。

用户只要求算数时，先检查已有源快照，不擅自联网重取。用户要求完整取数算数时依次执行：

1. `collect-integration-terminal-removal`：专线拆机工单。
2. `collect-eoms-terminal-removal`：服务类拆机工单。
3. `collect-integration-terminal-materials`：出入库、物资基准库和物料映射。
4. 本 Skill：从数据库算数。任何取数步骤失败都停止下游。

三个 collector 须使用 `database` 或 `both`，或将用户确认周期的本地文件以 `--reuse-existing` 入库。仅有 `D:\edge_download` 文件不等于数据库具备源数据。

算数必需五类同周期源快照：`integration_removal_order`、`eoms_service_removal_order`、`integration_terminal_inbound`、`integration_material_baseline`、`terminal_material_names`。缺失即停止，不改用其他月份，不用零值伪造源数据。出库数据当前不参与算数。

## 执行

Windows 项目根目录示例，替换实际月份和部署路径：

```powershell
py -3.11 metrics/terminal_recovery/terminal_recovery_export_online.py --start-date 2026-08-01 --end-date 2026-08-31 --mode both --database D:/MonthlyReport/data/quality_assessment.db --output-dir D:/MonthlyReport/outputs/terminal_recovery_online
```

其他平台先确认 Python 与路径，不能直接照搬 Windows 示例。

## 口径与模式

- 三种模式全部从 SQLite 读取各类最新、日期完全匹配的源快照，恢复临时 Excel 后调用既有算法；不直接从下载目录算数。
- 关联单据号在筛选后的候选记录内按源表顺序去重，保留首次出现的记录；不是先对全部源数据去重，不排序后再取第一条。
- `file`：完整 Excel 和 JSON，不写结果数据库。
- `database`：仅写两个目标 sheet 对应的结构化指标，不保留本地结果。
- `both`：Excel、JSON、SQLite 都输出，默认模式。
- 本地名称为 `终端回收率汇总表_YYYY-MM.xlsx` 和 `.json`；Excel 保留完整 11 个 sheet，JSON 仅含 `按地市回收率汇总`、`sheet1`。
- 数据库使用 `metric_run`、`ads_metric_result`，模块 `terminal_recovery`；不将整份结果 Excel 作为 BLOB 保存，不按每个 sheet 新建结果表。

## 验证与交付

等待进程结束。记录统计周期、源批次、计算批次、输出位置、退出状态；按 mode 检查应有结果。文件模式核对两个目标 sheet 名称；数据库模式核对成功批次及指标行数，不能把历史批次当作本次成功。用临时测试库运行测试，不清空业务数据库。

同月重复算数会生成新结果批次，不删除旧记录。由复现版切到线上版时必须真正执行本入口才能产生新结果，仅删除旧脚本或重新生成 PPT 不会改变历史结果。

本 Skill 不自动生成 PPT；用户另行要求时再执行 reporting 流程。PPT 默认从已存储结果中选批次，不检查是哪个脚本生成，核对其选择的批次 ID。详细规则见 `metrics/terminal_recovery/README.md`。
