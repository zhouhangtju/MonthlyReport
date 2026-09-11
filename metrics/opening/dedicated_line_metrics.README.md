# 编排专线开通类指标

## 1. 指标用途

本模块从 SQLite 的 `orch_opening`数据集计算专线开通量、趋势、产品分布和自动率，不读取原始Excel或 `export`目录。

计算脚本：`metrics/opening/dedicated_line_metrics.py`

## 2. 运行

```bash
python3 metrics/opening/dedicated_line_metrics.py \
  --database data/quality_assessment.db \
  --start-month 2025-09 \
  --end-month 2026-08 \
  --mode both
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--database` | `data/quality_assessment.db` | SQLite数据库 |
| `--start-month` | 必填 | 趋势起始月份，`YYYY-MM` |
| `--end-month` | 必填 | 最新统计月份，`YYYY-MM` |
| `--mode` | `both` | `file`、`database`或`both` |
| `--output` | 自动生成 | 自定义JSON结果路径 |

默认输出：`outputs/编排专线指标_YYYY-MM.json`。

## 3. 月份与基础口径

- 月份取接口筛选口径对应的结束时间，兼容 `订单结束时间`、`结束时间`、`完成时间`、`订单完成时间`和 `报结时间`；
- 不使用ETL执行时间或文件入库时间归月；
- 基础筛选为 `订单状态=已完成`；
- 数量按 `订单号`去重，空订单号按行计数；
- 口径版本为 `1.0.0`。

`quality.rows_missing_order_month`记录无法取得业务月份的记录数，这些记录不会进入月度指标。

## 4. 已实现指标

- 互联网专线已完成开通订单量、环比和同比；
- 重点互联网产品同比；
- 互联网六类产品按月、地市和产品分布；
- MPLS-VPN指定产品开通量、同比、地市和产品分布；
- 传输专线指定六类产品开通量、同比、地市和产品分布；
- 其他互联网专线滚动12个月开通量及平均月开通量；
- 互联网专线开通六环节自动率及整体自动率；
- 移机六环节、拆机五环节自动率及整体自动率；
- 移机、拆机各地市配置激活自动率。

运行时会按《专线产品情况》前18个子 Sheet 的顺序打印读取进度和指标摘要。数据库明细只查询一次，每条 `source_data` 只解析一次，并在一次遍历中完成归月、基础筛选、订单号去重和分组。指标结果使用批量 SQL 写入。

自动率保存实际分子和分母。分母为0时 `metric_value`为 `null`，不会把无数据表示成0%。

## 5. 结果存储

- `metric_run`：统计周期、口径版本和源ETL批次；
- `ads_metric_result`：指标编码、月份、产品、地市、环节、分子、分母和指标值；
- JSON：文件模式下的审计结果。

历史口径来源为 `stat_internet_line_metrics.py`，运行时不引用该文件。
