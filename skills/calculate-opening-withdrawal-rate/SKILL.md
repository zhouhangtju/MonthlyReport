---
name: calculate-opening-withdrawal-rate
description: 从一体化售中开通工单计算专线开通撤退单率。用户提到一体化撤退单率、专线开通撤单率、已撤单或已驳回占比时使用。
---

# 一体化专线开通撤退单率

调用 `metrics/opening/withdrawal.py`，数据源为数据库 `integration_opening`，按 `工单结束时间` 统计。

## 默认口径

- 条件：数据来源为二编、工单类型为开通，默认业务范围仅互联网专线。
- 剔除主题包含“测试”或 `test` 的工单。
- 同一工单号保留结束时间最晚的一条。
- 分母：筛选、剔除和去重后的正式开通工单数。
- 分子：状态为已撤单或已驳回的唯一工单数。

## 执行

```bash
python3 metrics/opening/withdrawal.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

未经用户明确要求，不使用 `--all-business-types`，也不修改 `--business-type`、`--withdrawal-status` 或 `--test-keyword`。文件默认写入 `outputs/专线开通撤退单率_开始日期_结束日期.json`。

## 验证

- `metric_run` 成功，`ads_metric_result` 包含全省、地市和业务类型结果。
- `ads_metric_detail` 能追溯分母、分子及测试单剔除明细。
- 核对公式为 `(已撤单+已驳回)/正式开通工单数`。
- 口径版本含 `provisional`，报告结果时说明业务范围和状态口径仍属暂行。

详细口径见 `metrics/opening/withdrawal.README.md`。

## 默认收尾：清理源数据

完成上述验证且本次结果成功入库后，默认调用 `skills/cleanup-source-data/SKILL.md`，传递本次数据库绝对路径、实际周期、成功指标批次及源批次，并合并当前任务待清理范围。候选数据集：`integration_opening`。

按清理 Skill 执行预览及通过后的 `--apply`，无需再次询问是否清理。共享源数据仍有未完成的依赖或当前任务计划中的后续消费者时，登记待清理并继续算数，在相关算数结束后再评估；不能为了清理额外扩大算数任务。用户要求保留明细、仅预览，或本次为 `file` 模式、算数失败/未入库时，不执行删除。验证明细必须在清理之前完成。
