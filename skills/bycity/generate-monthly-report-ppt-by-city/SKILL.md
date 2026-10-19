---
name: generate-monthly-report-ppt-by-city
description: 从 MySQL 已落库的地市及区县级指标生成15页地市月报PPTX，包含业务发展情况、专线自动情况、终端回收情况和集团撤退单。用户要求生成杭州等地市版月报或展示区县指标时使用；不在绘图阶段重新计算指标。
---

# 生成地市月报 PPT

只调用 `reporting/by-city/build_internet_line_ppt_by_city.py`，从成功的 `orchestration_opening_metrics_by_city`、`orchestration_automation_metrics_by_city`、`terminal_recovery_metrics_by_city` 和 `business_support_withdrawal_by_city` 指标批次生成15页 PPT。地市指标批次必须与目标月份和目标地市一致。

## 页面结构

1. 集客综调月报封面，标明地市和月份。
2. 目录页，突出“业务发展情况”。
3. 互联网专线：地市产品总览、各区县分产品开通量、近12个月悦享专线趋势。
4. 互联网专线套餐和其他互联网产品近12个月趋势。
5. MPLS-VPN：地市产品总览、各区县分产品开通量、近12个月趋势。
6. 传输专线：地市产品总览、各区县分产品开通量、近12个月趋势。
7. 目录页，突出“专线自动情况”。
8. 互联网专线开通自动率：地市各环节、各区县环节和整体自动率。
9. 互联网专线移机自动率：地市各环节、各区县环节和整体自动率。
10. 互联网专线拆机自动率：地市各环节、各区县环节和整体自动率。
11. 目录页，突出“终端回收情况”。
12. 全省11地市回收率对比，以及目标地市回收率最低的10个标准区县。
13. 目标地市按业务类型的设备回收量、全省按地市设备回收量、目标地市后10区县设备回收量。
14. 目录页，突出“业务情况”。
15. 集团撤退单：目标地市专线、企宽撤退和企宽退单的概述、区县对比与区县排名。

视觉、字号、配色、母版和图表布局继承现有省级业务发展页面。省级页面中的“全省”替换为目标地市，“各地市”替换为目标地市各区县。不得用0掩盖缺失指标。

## 数据准备

四部分统一采用“独立计算技能 → metrics 脚本 → 数据库成功结果批次 → 本技能绘制 PPT”的流程。地市和月份必须来自本次请求；已有同周期、同地市且源数据未变化的成功结果时可以复用，缺少或需要更新时调用对应计算技能：

| 章节 | 计算技能 | 结果任务编码 | 结果表 |
| --- | --- | --- | --- |
| 业务发展情况 | [calculate-orchestration-opening-metrics-by-city](../calculate-orchestration-opening-metrics-by-city/SKILL.md) | `orchestration_opening_metrics_by_city` | `result_orchestration_opening` |
| 专线自动情况 | [calculate-orchestration-automation-metrics-by-city](../calculate-orchestration-automation-metrics-by-city/SKILL.md) | `orchestration_automation_metrics_by_city` | `result_orchestration_opening` |
| 终端回收情况 | [calculate-terminal-recovery-by-city](../calculate-terminal-recovery-by-city/SKILL.md) | `terminal_recovery_metrics_by_city` | `result_terminal_recovery` |
| 业务情况—集团撤退单 | [calculate-opening-withdrawal-metrics-by-city](../calculate-opening-withdrawal-metrics-by-city/SKILL.md) | `business_support_withdrawal_by_city` | `result_opening_withdrawal` |

计算步骤、原始数据和人工文件参数以对应计算技能为准。本技能只读数据库结果，不在绘图阶段读取人工 Excel 或重新计算业务指标。集团撤退单的专线原因和企宽明细必须在计算阶段选用本次周期的文件。

生成前确认四类批次均为 `status='success'`，结果中的月份和 `city` 与请求一致。业务发展、自动率和终端回收的批次结束日期为月报月末；集团撤退单采用上月26日至本月25日，不能按月末筛选它的批次。

业务发展页展示连续12个月趋势，计算起点取月报月向前11个月，并按对应技能处理同比、环比基期；数据库缺月补0的情况应保留审计记录。目标月应有 `month_city_county_product` 区县分布。

## 生成

```bash
python3 reporting/by-city/build_internet_line_ppt_by_city.py \
  --month "$REPORT_MONTH" \
  --city "$CITY"
```

默认输出：

```text
outputs/city_monthly_report/{YYYY-MM}/{地市简称}/{地市}业务发展情况_{年份}年{月份}月.pptx
outputs/city_monthly_report/{YYYY-MM}/{地市简称}/{地市}业务发展情况_{年份}年{月份}月.audit.json
```

例如2026年8月仅代表一次具体运行；生成其他月份时，指标批次、`--month`、输出文件名和页面文字必须同步使用实际月报月份。

可通过 `--output` 指定输出，通过 `--template` 指定 PPT 模板；`--keep-json` 保留绘图中间数据。`--database` 仅兼容旧命令，实际 MySQL 连接配置仍由 `storage/database.py` 决定。

## 验证

1. 构建命令退出为0，PPTX和审计JSON存在。
2. 审计中的 `missing` 必须为空，选中的指标批次、月份和地市正确。
3. PPTX可解压，页面数必须为15。
4. 使用 PowerPoint 兼容的本地渲染导出PDF，再逐页检查：母版、微软雅黑、标题、数据标签、区县横轴、图例、页码和口径说明均正确。
5. 第3、5、6页区县合计应与对应地市总量一致；“未归属区县”存在时必须保留显示并在交付说明中披露。

找不到成功指标批次或审计出现缺失时，按对应计算技能准备数据并补算，不得在 reporting 层直接查询原始订单临时计算。

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。
