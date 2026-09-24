# 地市及区县级编排专线开通指标

## 用途

`dedicated_line_metrics_by_city.py` 从 MySQL `orch_opening` 原始表计算指定地市的业务发展指标，为地市版月报第一章提供数据。省级脚本 `metrics/opening/dedicated_line_metrics.py` 保持不变。

地市参数接受“杭州”和“杭州市”两种写法，结果统一保存为“杭州市”。默认区县字段为 `区县名称`；空值统一归入“未归属区县”。脚本不会使用 `A端专线接入区县`、市场网格或地址字段推断区县。

## 统计口径

- 数据源：MySQL `orch_opening`
- 业务时间：`订单结束时间`
- 基础过滤：`订单状态=已完成`、`订单类型=开通`
- 地市过滤：`地市` 同时兼容“杭州”和“杭州市”
- 数量口径：按 `订单号` 去重
- 区县口径：`区县名称`
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

现有省级 `orch_opening_monthly_summary` 没有区县维度，不能反推出历史区县数据。历史 `orch_opening` 明细如果已经清理，必须从保留的原始 Excel 或 gzip 归档重新导入后再计算；不得把缺失月份解释为真实的零。

## 验证

1. `quality.months_with_rows` 应覆盖需要的趋势月份、上月和去年同月。
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
