---
name: calculate-opening-withdrawal-metrics-by-city
description: 从数据库一体化开通工单及人工专线撤退原因、企宽明细计算指定地市和标准区县的集团撤退单指标，并保存数据库结果批次与JSON。用户要求计算地市业务支撑情况中的集团撤退单、区县撤退率或为地市月报第15页准备数据时使用。
---

# 计算地市及区县集团撤退单指标

调用 `metrics/opening/bycity/withdrawal_metrics_by_city.py`。与其他地市计算技能一致，算数逻辑放在 `metrics/`，默认使用 `--mode both` 保存数据库结果和 JSON；PPT 生成阶段只读取成功的地市结果批次。

## 数据准备

地市和月报月份取自用户请求，月份格式为 `YYYY-MM`，不能使用系统日期或文件名猜测。地市支持“杭州”及“杭州市”等写法。

| 输入 | 读取方式与用途 |
| --- | --- |
| MySQL `integration_opening` 数据集 | 复用 `metrics/opening/withdrawal.py` 的数据库读取、清洗和统计口径，计算专线撤退率及竣工量 |
| 专线撤退原因 Excel | `--line-reasons` 指定；读取“撤退单清单”的“地市、区县、工单主题、大类”，统计区县撤退原因 |
| 企宽 Excel | `--broadband` 指定；读取 `Sheet1` 的 `CELL`、`OP_REMARK`、`FIRST_LEVEL_PROBLEM`，计算企宽撤退、退单及原因 |
| 区县映射 Excel | `--county-map` 指定，默认 `data/区县信息汇总.xlsx`，提供地市、区县别名和标准区县 |

脚本内两份业务文件的默认路径为 `data/offline_data/7.26-8.25撤退单原因需反馈.xlsx` 和 `data/offline_data/企宽.xlsx`。运行时使用本次请求对应的实际文件路径；更换月份时不能直接沿用旧月文件。人工 Excel 按提供的明细范围计算，`--month` 不会自动将它们按日期过滤为当月数据。

专线数据库统计周期采用上月26日至本月25日，由 `config/report_periods.py` 统一确定。例如2026年8月为2026-07-26至2026-08-25。原始工单从数据库读取，两份人工 Excel 在计算层读取，不在绘图层补算。

## 区县与指标口径

- 专线工单按目标地市筛选，将“区县”映射为标准区县；无法映射时从“工单主题”匹配，仍无法识别则保留为“未归属区县”。专线原因表使用相同的区县清洗方式。
- 企宽直接对 `CELL` 在全部地市区县映射中做关键字匹配，唯一匹配后确定地市和标准区县，再提取目标地市。不得使用源表 `CITY` 预筛或回填；空值、未匹配及多归属冲突计入 `quality.cell_match`，不强行归属目标地市。
- 专线撤退率复用省级 `withdrawal.calculate` 的分子分母，原因表只用于原因数量和占比；原因样本总量不要求等于数据库撤退单总量。
- 企宽撤退率为“退单完成＋撤单完成”条数除以目标地市匹配到的全部受理明细；企宽退单率仅将“退单完成”计入分子。原因按各自分子范围内的 `FIRST_LEVEL_PROBLEM` 统计。
- 结果包含地市合计和区县指标。地市率使用地市分子除以地市分母，不平均区县百分比；零分母保留无数据含义。

## 执行

在项目根目录执行，先按本次请求设置月份、地市和两份文件路径：

```bash
python3 metrics/opening/bycity/withdrawal_metrics_by_city.py \
  --month "$REPORT_MONTH" \
  --city "$CITY" \
  --line-reasons "$LINE_REASONS_FILE" \
  --broadband "$BROADBAND_FILE" \
  --mode both
```

可用 `--county-map` 指定映射表、`--output` 指定结果 JSON。`--database` 仅兼容旧命令，实际连接配置由 `storage/database.py` 决定。用户要求全部11地市时，对同一月份和同一组源文件依次计算11个地市。

## 结果与交接

- 任务编码为 `business_support_withdrawal_by_city`，批次记录写入 `metric_run`，结果复用 `result_opening_withdrawal`，不新建地市结果表。
- `dimension_type='city'` 表示地市合计，`city_county` 表示区县；维度包含 `month`、`city`，区县结果另含 `county`。
- 默认 JSON 为 `outputs/集团撤退单地市指标_{地市简称}_{月份}.json`，包含结果、源文件路径及哈希、数据库来源批次和匹配质量信息。
- 计算完成后确认 `metric_run_id` 对应任务状态为 `success`，地市、月份和26日至25日周期正确；核对 `quality.line_unassigned`、`quality.cell_match` 与冲突样本，报告不能归属的情况，不能将缺失源文件解释为业务量为0。

需要生成月报时，交接给 [generate-monthly-report-ppt-by-city](../generate-monthly-report-ppt-by-city/SKILL.md)。该技能读取目标地市成功批次，绘制第15页的专线、企宽撤退和企宽退单概述、区县对比及排名。本技能只计算指标，不生成 PPT。

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。
