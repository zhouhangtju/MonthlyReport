---
name: calculate-orchestration-opening-metrics
description: 从 SQLite 的编排专线开通数据计算《专线产品情况》前18个子 Sheet 对应的开通量、趋势、产品分布和自动率。用户提到编排专线开通指标、专线产品情况、开通量、同比环比或开通自动率时使用。
---

# 编排专线开通指标集

调用 `metrics/opening/dedicated_line_metrics.py`，只从数据库 `orch_opening` 数据集读取，不直接读取 Excel 或 `export`。

## 执行

统计月份按订单结束时间归属。将用户周期转换成 `YYYY-MM`；`start-month` 是趋势起点，`end-month` 是最新统计月。未指定模式时用 `both`，未指定库时用 `data/quality_assessment.db`。

```bash
python3 metrics/opening/dedicated_line_metrics.py \
  --database data/quality_assessment.db \
  --start-month 2025-09 \
  --end-month 2026-08 \
  --mode both
```

脚本一次读取明细并一次遍历计算完整指标集，不要为18个子 Sheet 重复运行。基础口径是 `订单状态=已完成`；数量按 `订单号` 去重，空订单号按行计数。默认 JSON 为 `outputs/编排专线指标_YYYY-MM.json`。

## 验证

- 运行日志应从 `[Sheet 1/18]` 到 `[Sheet 18/18]`，并打印各项摘要。
- 数据库模式应产生成功的 `metric_run`，结果写入 `ads_metric_result`。
- 核对 `quality.rows_missing_order_month`；缺失业务月份的记录不会进入结果。
- 分母为0的自动率应为 `null`，不能解释成0%。
- 前几个月为0时先检查数据库是否有对应结束月份的 `orch_opening` 数据。

不要改变结束时间口径、订单号去重和产品分类。详细口径见 `metrics/opening/dedicated_line_metrics.README.md`。
