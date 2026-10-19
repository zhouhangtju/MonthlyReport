---
name: calculate-orchestration-opening-metrics-by-city
description: 从 MySQL 的编排专线开通数据计算指定地市及区县的开通量、趋势和产品分布。用户提到杭州等地市的区县级专线指标、地市版业务发展情况或运行 bycity 指标脚本时使用；默认复用已有 orch_opening 数据，仅在目标周期尚未取数时补取原始数据。
---

# 计算地市及区县级编排专线开通指标

调用 `metrics/opening/bycity/dedicated_line_metrics_by_city.py`，从 MySQL `orch_opening` 读取已入库的编排专线明细，按目标地市及标准区县计算指标。原始数据与省级计算共用同一张表，不维护单独的地市采集脚本或地市原始表。区县先使用 `data/区县信息汇总.xlsx` 中当前地市的“区县→标准区县”映射清洗；无法映射时再从 `主题` 按区县别名或标准区县关键字回填。

## 数据准备判断

月份必须从用户请求或当前月报任务中取得，不能把示例月份当成固定值。计算只读取 MySQL `orch_opening`，不从本地原始文件补数；数据库缺少的月份按0计算，并在结果的 `quality.missing_months_filled_zero` 中记录。同比需要目标月的去年同月，环比需要目标月的上月，滚动12个月使用目标月及向前连续11个月。

可先按目标地市检查月份覆盖情况：

```sql
SELECT
  DATE_FORMAT(`订单结束时间`, '%Y-%m') AS month,
  COUNT(*) AS row_count
FROM `orch_opening`
WHERE `地市` IN (%(city_short)s, %(city_full)s)
  AND `订单结束时间` >= %(required_start_date)s
  AND `订单结束时间` < %(required_end_exclusive)s
GROUP BY DATE_FORMAT(`订单结束时间`, '%Y-%m')
ORDER BY month;
```

本技能不读取 `data` 目录中的业务原始文件，也不自动补取或补导缺失月份。`data/区县信息汇总.xlsx` 仅用于区县名称标准化，不提供业务指标数据。

## 计算

将用户请求的地市和统计周期转换为脚本参数。`--start-month` 是输出趋势起点，`--end-month` 是本次月报的目标月份；脚本会自动补入同比、环比和滚动趋势所需的依赖月份。以下变量必须按本次请求赋值：

```bash
python3 metrics/opening/bycity/dedicated_line_metrics_by_city.py \
  --city "$CITY" \
  --start-month "$START_MONTH" \
  --end-month "$END_MONTH" \
  --mode both
```

例如用户要生成2026年8月月报时，`END_MONTH` 才取 `2026-08`；生成其他月份时应使用对应月份。生成月报前6页的12个月趋势时，`START_MONTH` 取 `END_MONTH` 向前11个月；其他任务则按用户要求的趋势区间确定，不能固定为某个月。

地市名称会统一为带“市”的形式。无法通过原始 `区县名称` 或 `主题` 识别的记录归入“未归属区县”用于审计；PPT横轴严格使用映射表中的标准区县清单。`A端专线接入区县` 是业务接入端属性，只有用户明确指定该口径时才使用。

## 验证

- 命令退出成功；数据库缺月时按0处理，并在 `quality.missing_months_filled_zero` 中如实记录。
- 数据库模式产生成功的 `metric_run`，且 `metric_code='orchestration_opening_metrics_by_city'`。
- 结果写入 `result_orchestration_opening`，维度包含目标 `city`；区县分布包含 `county`。
- 目标月各区县合计应与同口径地市总量一致，“未归属区县”不得静默丢弃。
- JSON 审计文件中的地市、周期、产品分类和缺失月份符合本次请求。

完成计算后，可调用 `generate-monthly-report-ppt-by-city` 生成月报前6页业务发展情况。

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。
