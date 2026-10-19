---
name: calculate-orchestration-opening-metrics
description: 一次完成编排专线正式指标与资管 CSV 辅助分析，分别输出数据库指标、JSON 和非自动原因结果。只有用户明确要求其中一项时才单独运行。
---

# 编排专线开通指标与资管环节分析

默认使用同一份当月完结工单资管 CSV，顺序运行本技能的 `scripts/calculate_manual_csv.py` 和 `metrics/opening/dedicated_line_metrics.py`，两步都成功才报告技能完成。前者产出各环节辅助自动率和开通组网非自动原因 JSON/CSV；后者从 MySQL `orch_opening` 读取工单，结合资管 CSV 生成正式开通指标并入库。只有用户明确要求单独分析 CSV 或单独重算正式指标时，才仅运行对应步骤。

PPT 的主要自动率取正式中间表结果；辅助 JSON 中的组网方案非自动原因也会由 `reporting/manual_results.py` 载入 PPT，其他辅助环节率仅在正式中间表结果不可用时作为补充。因此两份结果都要输出，并核对月报月份一致，但不要求两种不同口径的自动率数值相同。

## 完整执行：先生成辅助结果

```bash
python3 skills/calculate-orchestration-opening-metrics/scripts/calculate_manual_csv.py \
  --input "/absolute/path/to/资管专线.csv" \
  --month 2026-08 \
  --json-output "outputs/manual_metrics/互联网专线自动率_2026-08.json" \
  --csv-output "outputs/manual_metrics/互联网专线自动率_2026-08.csv"
```

同一月份在 `outputs/manual_metrics` 中只保留一份 `internet_line_manual_automation` JSON，避免 PPT 读取时报重复。

## 再计算正式指标

统计月份按订单结束时间归属。将用户周期转换成 `YYYY-MM`；`start-month` 是趋势起点，`end-month` 是最新统计月。未指定模式时用 `both`。`--database` 仅兼容旧命令；MySQL 连接信息写在 `storage/database.py`。

```bash
python3 metrics/opening/dedicated_line_metrics.py \
  --start-month 2025-09 \
  --end-month 2026-08 \
  --asset-csv "/absolute/path/to/资管专线.csv" \
  --mode both
```

脚本一次读取明细并一次遍历计算完整指标集，不要为18个子 Sheet 重复运行。基础口径是 `订单状态=已完成`；数量按 `订单号` 去重，空订单号按行计数。默认 JSON 为 `outputs/编排专线指标_YYYY-MM.json`。

## 验证

- 运行日志应从 `[Sheet 1/18]` 到 `[Sheet 18/18]`，并打印各项摘要。
- 数据库模式应产生成功的 `metric_run`，结果写入 `result_orchestration_opening`。
- 核对 `quality.rows_missing_order_month`；缺失业务月份的记录不会进入结果。
- 分母为0的自动率应为 `null`，不能解释成0%。
- 核对 `internet_product_average_monthly_orders`：悦享专线动态 IP 版和互联网专线套餐都应保存滚动12个月累计量（`numerator`）及月均量（`metric_value`）；有趋势数据时不得缺失或显示为0。
- 前几个月为0时先检查数据库是否有对应结束月份的 `orch_opening` 数据。
- 数据库模式成功后，确认 `orch_opening_monthly_summary` 和
  `orch_opening_monthly_quality` 已保存 `end-month` 快照。历史明细已按保留期清理时，程序会自动使用这些快照补齐趋势和同比，不应要求重新拉取全部历史明细。

不要改变结束时间口径、订单号去重和产品分类。详细口径见 `metrics/opening/dedicated_line_metrics.README.md`。

## 资管 CSV 辅助分析口径

源 CSV 至少包含 `二级编排工单号`、`环节名称`、`地市`、`业务类型`、`工单类型`、`处理人`、`处理意见`。筛选 `业务类型=互联网专线`，以 `二级编排工单号` 唯一标识工单，分别分析开通的组网方案、变更的组网方案和资源反馈、拆除的组织资源释放。资管源数据用“变更”表示移机，未能关联确认纯移机时须标注“变更暂按移机统计”。

辅助脚本的自动条件为处理人包含“自动”或等于“系统管理员”，先去除首尾空格；不能凭处理意见中的“自动”判断。同一工单目标环节的全部记录都自动才算自动，任一人工、空值或未知账号均判为非自动。分母是含目标环节的去重工单数；缺少目标环节和工单跨地市冲突须单独审计。分母为零时自动率为 `null`，全省率用全省分子除以全省分母。源文件已是指定完结周期工单全集时，不再按单条环节结束时间筛选。

对开通组网非自动原因，只检查非自动处理记录的 `处理意见`：包含“工程施工”及空意见分别按工单去重计数；同一工单可以同时进入两类，各类别最多计一次。两类占比均以非自动工单数为分母，工程施工前三地市按工单数降序、并列按地市名排序。

运行后核对 JSON `audit` 中缺失目标环节、混合处理和地市冲突，报告各指标的分子、分母，以及开通组网非自动原因的数量、占比和前三地市。脚本支持 UTF-8、UTF-8 BOM 和 GB18030 CSV。

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。
