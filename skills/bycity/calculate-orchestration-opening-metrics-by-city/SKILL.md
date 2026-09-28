---
name: calculate-orchestration-opening-metrics-by-city
description: 从 MySQL 的编排专线开通数据计算指定地市及区县的开通量、趋势和产品分布。用户提到杭州等地市的区县级专线指标、地市版业务发展情况或运行 bycity 指标脚本时使用；默认复用已有 orch_opening 数据，仅在目标周期尚未取数时补取原始数据。
---

# 计算地市及区县级编排专线开通指标

调用 `metrics/opening/bycity/dedicated_line_metrics_by_city.py`，从 MySQL `orch_opening` 读取已入库的编排专线明细，按目标地市及 `区县名称` 计算指标。原始数据与省级计算共用同一张表，不维护单独的地市采集脚本或地市原始表。

## 数据准备判断

默认不重复取数。月份必须从用户请求或当前月报任务中取得，不能把示例月份当成固定值。计算前先确认 `orch_opening` 已覆盖计算所需月份：同比需要目标月的去年同月，环比需要目标月的上月，滚动12个月需要目标月及向前连续11个月。若用户要求的趋势起始月更早，还要覆盖从该月到目标月的全部月份。

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

满足以下任一情况时才补取数据：

- `orch_opening` 从未完成过相应周期的入库；
- 目标地市缺少计算依赖月份；
- `etl_run` 显示对应周期采集失败或数据不完整。

补取时复用现有 `collector/orchestration/fetch_opening.py`。接口按时间范围导出全量工单，不能只拉某个地市；默认使用 `both`，同时保留 Excel 并幂等写入 MySQL：

其中 `required_start_date` 取“趋势起始月”和“目标月向前12个月”两者中更早月份的月初，`required_end_exclusive` 取目标月下一月月初。

补取命令中的日期也必须根据本次任务计算，不能照抄示例月份：

```bash
python3 collector/orchestration/fetch_opening.py \
  --start-date "$REQUIRED_START_DATE" \
  --end-date "$REPORT_MONTH_END_DATE" \
  --mode both
```

认证使用命令行参数或环境变量 `GDDL_ZYTOKEN`、`GDDL_COOKIE`，不得写入技能、代码、Git 或日志。除非用户明确要求强制重取，否则不加 `--refresh`。

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

地市名称会统一为带“市”的形式。区县默认使用 `区县名称`；空值归入“未归属区县”。`A端专线接入区县` 是业务接入端属性，只有用户明确指定该口径时才使用。

## 验证

- 命令退出成功，所需月份均完成计算；缺月时不得按0处理。
- 数据库模式产生成功的 `metric_run`，且 `metric_code='orchestration_opening_metrics_by_city'`。
- 结果写入 `result_orchestration_opening`，维度包含目标 `city`；区县分布包含 `county`。
- 目标月各区县合计应与同口径地市总量一致，“未归属区县”不得静默丢弃。
- JSON 审计文件中的地市、周期、产品分类和缺失月份符合本次请求。

完成计算后，可调用 `generate-monthly-report-ppt-by-city` 生成月报前6页业务发展情况。
