# 一体化专线开通撤退单率

## 1. 指标用途

本模块从 SQLite 的 `integration_opening`数据集计算专线开通撤退单率，不读取原始Excel或 `export`目录。

计算脚本：`metrics/opening/withdrawal.py`

## 2. 运行

```bash
python3 metrics/opening/withdrawal.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

默认输出：`outputs/专线开通撤退单率_开始日期_结束日期.json`。

## 3. 默认暂行口径

- 时间字段：`工单结束时间`，包含结束日期全天；
- 基础条件：`工单数据来源=二编`、`工单类型=开通`；
- 业务范围：默认仅 `互联网专线`；
- 测试单：工单主题包含“测试”或 `test`时剔除；
- 去重：同一工单号保留工单结束时间最晚的一条；
- 分母：筛选、剔除和去重后的正式开通工单数；
- 分子：状态为“已撤单”或“已驳回”的唯一工单数；
- “失败”默认不计入分子；
- 口径版本：`1.0.0-provisional`。

公式：

```text
专线开通撤退单率 =（已撤单工单数 + 已驳回工单数）÷ 正式开通工单数
```

`provisional`表示专线范围、测试单识别和“已驳回”等同退单仍需业务确认。

## 4. 可调参数

统计多个专线类型时重复传入 `--business-type`：

```bash
python3 metrics/opening/withdrawal.py \
  --start-date 2026-08-01 --end-date 2026-08-31 \
  --business-type 互联网专线 \
  --business-type "MPLS VPN专线"
```

- `--all-business-types`：计算全部业务类型；
- `--withdrawal-status`：可重复指定，替换默认分子状态；
- `--test-keyword`：可重复指定工单主题测试关键词。

## 5. 结果存储与明细

- `metric_run`：统计周期、口径版本、状态及源ETL批次；
- `ads_metric_result`：全省、地市和业务类型的分子、分母及撤退单率；
- `ads_metric_detail`：全省分母、分子及测试单剔除明细，可追溯到工单号；
- JSON文件：汇总与质量检查，不包含完整工单明细。

## 6. 已验证样例

原一体化样例共40,055张工单。在全部业务类型、不剔除测试关键词的口径下：

```text
已撤单：288
已驳回：198
分子：486
分母：40,055
撤退单率：1.2133%
```

数据库计算结果与原README一致。
