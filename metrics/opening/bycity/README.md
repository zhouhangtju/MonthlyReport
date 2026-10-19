# 地市及区县级编排专线开通指标

## 用途

`dedicated_line_metrics_by_city.py` 从 MySQL `orch_opening` 原始表计算指定地市的业务发展指标，为地市版月报第一章提供数据。省级脚本 `metrics/opening/dedicated_line_metrics.py` 保持不变。

`automation_metrics_by_city.py` 从既有 `intermediate_orchestration_orders` 中间表计算地市及标准区县的开通、移机、拆机自动率。它复用省级自动率已完成的订单清洗和资管环节匹配，不重新读取资管 CSV，也不改写省级指标。

地市参数接受“杭州”和“杭州市”两种写法，结果统一保存为“杭州市”。区县使用 `data/区县信息汇总.xlsx` 按地市映射到“标准区县”；原始区县无法映射时，从 `主题` 按区县别名或标准区县关键字回填，仍无法匹配的记录归入“未归属区县”供审计。PPT横轴只使用映射表中的标准区县。脚本不会使用 `A端专线接入区县`、市场网格或地址字段推断区县。

## 统计口径

- 数据源：MySQL `orch_opening`
- 业务时间：`订单结束时间`
- 基础过滤：`订单状态=已完成`、`订单类型=开通`
- 地市过滤：`地市` 同时兼容“杭州”和“杭州市”
- 数量口径：按 `订单号` 去重
- 区县口径：`区县名称` 经 `data/区县信息汇总.xlsx` 标准化，必要时使用 `主题` 回填
- 产品分类：与省级 `dedicated_line_metrics.py` 一致
- 指标版本：`1.0.0`

## 结果范围

脚本生成以下结果：

| `dimension_type` | 含义 |
| --- | --- |
| `month_city` | 地市各月开通量 |
| `month_city_product` | 地市各月分产品开通量 |
| `month_city_county` | 目标月各区县开通量 |
| `month_city_county_product` | 目标月各区县分产品开通量 |
| `month_city_comparison` | 地市总量同比、环比 |
| `month_city_product_comparison` | 地市分产品同比 |
| `rolling_12_months_city_product` | 地市重点产品近12个月累计及月均 |
| `rolling_12_months_city` | 地市其他互联网产品近12个月累计及月均 |

互联网专线、MPLS-VPN专线和传输专线均输出地市趋势、产品分布和目标月区县分布。结果写入 `metric_run` 和 `result_orchestration_opening`，任务编码为 `orchestration_opening_metrics_by_city`，不会被现有省级 PPT 读取为省级批次。

## 运行

```bash
python3 metrics/opening/bycity/dedicated_line_metrics_by_city.py \
  --city 杭州 \
  --start-month 2025-09 \
  --end-month 2026-08 \
  --mode both
```

专线自动情况：

```bash
python3 metrics/opening/bycity/automation_metrics_by_city.py \
  --city 杭州 \
  --month 2026-08 \
  --mode both
```

自动率地市结果任务编码为 `orchestration_automation_metrics_by_city`，结果同样写入 `result_orchestration_opening`。区县严格使用 `data/区县信息汇总.xlsx` 的标准区县；无法归属的记录保留在审计结果中，不作为 PPT 横坐标。

默认 JSON 输出：

```text
outputs/编排专线地市指标_杭州_2026-08.json
```

参数说明：

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--city` | 是 | 无 | 地市名称，例如杭州或杭州市 |
| `--start-month` | 是 | 无 | 趋势起始月份，`YYYY-MM` |
| `--end-month` | 是 | 无 | 最新统计月份，`YYYY-MM` |
| `--mode` | 否 | `both` | `file`、`database` 或 `both` |
| `--output` | 否 | 自动命名 | 自定义 JSON 路径 |
| `--batch-size` | 否 | `5000` | MySQL 流式读取批大小 |
| `--temp-dir` | 否 | 系统临时目录 | 订单号去重临时文件目录 |
| `--database` | 否 | 无 | 兼容旧命令；MySQL 连接仍由 `storage/database.py` 决定 |

## 数据准备与历史限制

运行前使用 `skills/bycity/collect-orchestration-opening-by-city` 对应流程准备 `orch_opening` 数据。同比需要去年同月，环比需要上月，滚动12个月需要连续12个月原始明细。

现有省级 `orch_opening_monthly_summary` 没有区县维度，不能反推出历史区县数据。地市版只读取 MySQL `orch_opening`；数据库缺少的月份按0计算，并写入 `quality.missing_months_filled_zero` 供审计，不读取本地原始文件补数。

## 验证

1. 核查 `quality.months_with_rows` 和 `quality.missing_months_filled_zero`；数据库缺少的月份会按0展示。
2. `quality.counties` 应包含目标地市实际区县；`未归属区县` 出现时核查 `quality.missing_county_rows`。
3. 对每个业务类型，目标月所有区县合计应等于该地市总量。互联网六类产品合计与总量不一致时，说明存在未纳入既定产品分类的订单，应单独核查，不能把差额分摊到已有产品。
4. 同比、环比分母为0时 `metric_value` 为 `null`，不能解释为0%。
5. 数据库模式成功后，`metric_run.metric_code` 应为 `orchestration_opening_metrics_by_city`，对应结果位于 `result_orchestration_opening`。

核对杭州互联网专线区县结果示例：

```sql
SELECT
  county,
  product,
  numerator
FROM result_orchestration_opening
WHERE metric_run_id = '<本次metric_run_id>'
  AND dimension_type = 'month_city_county_product'
ORDER BY county, product;
```
