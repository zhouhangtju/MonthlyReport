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
# 月度汇总与明细保留

每次以数据库模式成功计算时，程序会把 `end-month` 的基础指标写入
`orch_opening_monthly_summary`，并把数据质量写入
`orch_opening_monthly_quality`。历史订单明细删除后，趋势、同比、环比和
12 个月均值会自动用这些月度汇总补齐；存在明细的月份始终以明细重算为准。

建议逐月取数并逐月执行指标计算。确认需要保留的月份均已生成汇总后，可先预览：

```bash
python3 storage/prune_orchestration_opening.py \
  --database data/quality_assessment.db \
  --before-month 2026-07
```

确认预览中的 `missing_summary_months` 为空后，再实际归档清理：

```bash
python3 storage/prune_orchestration_opening.py \
  --database data/quality_assessment.db \
  --before-month 2026-07 \
  --apply
```

清理程序先将订单当前值和历史版本写入 `data/archive/orch_opening/*.jsonl.gz`，
然后删除对应的 ODS、raw 和版本明细，记录清理周期并执行 `VACUUM`。它不会删除
原始 Excel。`before-month` 为保留边界，例如 `2026-07` 表示删除 2026 年 7 月前
的数据库明细。
