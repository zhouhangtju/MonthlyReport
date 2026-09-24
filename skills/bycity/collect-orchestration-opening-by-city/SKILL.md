---
name: collect-orchestration-opening-by-city
description: 为地市及区县级专线开通指标准备编排“专线开通情况”原始数据并写入 MySQL。用户提到按杭州等地市生成区县开通量、地市版业务发展情况、区县产品分布，或运行 bycity 专线开通指标前的数据准备时使用；不在取数阶段计算或过滤区县指标。
---

# 编排专线开通地市版数据准备

复用项目现有 `collector/orchestration/fetch_opening.py` 获取数据。编排接口按订单结束时间导出全量工单，没有稳定的地市过滤参数；不要另写接口或重复维护一套入库程序。地市和区县筛选由 `metrics/opening/bycity/dedicated_line_metrics_by_city.py` 完成。

## 数据口径

- 数据集及 MySQL 原始表：`orch_opening`
- 主键：`订单号`
- 时间口径：`订单结束时间`
- 地市字段：`地市`
- 区县字段：`区县名称`
- 取数入口：`collector/orchestration/fetch_opening.py`
- 原始文件目录：`data/raw/orchestration/orch_opening/`

`A端专线接入区县` 是业务接入端属性，不作为默认行政区县口径。只有用户明确指定按 A 端归属统计时，才调整计算脚本口径。

## 执行

按指标所需完整月份取数。同比至少需要目标月、上月和去年同月；12 个月趋势需要目标月向前连续 11 个月。默认使用 `both`，同时保留 Excel 并幂等写入 MySQL。

```bash
python3 collector/orchestration/fetch_opening.py \
  --start-date 2025-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

默认沿用 `--chunk-days 3 --interval 2 --timeout 180`。认证使用命令行参数或环境变量 `GDDL_ZYTOKEN`、`GDDL_COOKIE`，不得把凭据写入技能、代码、Git 或日志。除非用户明确要求强制重取，否则不加 `--refresh`。

## 验证

1. 命令退出成功，所有日期分段均有成功结果或明确的 `database_already_covered`。
2. `etl_run` 中 `dataset_code='orch_opening'` 的目标周期状态为 `success`，`rows_failed=0`。
3. `orch_opening` 中目标地市存在数据，且 `区县名称` 的非空率足以支持区县统计：

```sql
SELECT
  `地市`,
  COUNT(*) AS total_rows,
  SUM(CASE WHEN NULLIF(TRIM(`区县名称`), '') IS NULL THEN 1 ELSE 0 END) AS missing_county
FROM `orch_opening`
WHERE `地市` IN ('杭州', '杭州市')
GROUP BY `地市`;
```

4. 取数完成后调用地市版计算脚本；本技能本身不计算指标：

```bash
python3 metrics/opening/bycity/dedicated_line_metrics_by_city.py \
  --city 杭州 \
  --start-month 2025-09 \
  --end-month 2026-08 \
  --mode both
```

缺少区县的有效订单由计算脚本归入“未归属区县”，不能静默丢弃，也不能改用市场网格或 A 端区县猜测归属。
