---
name: calculate-opening-withdrawal-rate
description: 从一体化售中开通工单计算专线开通撤退单率。用户提到一体化撤退单率、专线开通撤单率、已撤单或已驳回占比时使用。
---

# 一体化专线开通撤退单率

调用 `metrics/opening/withdrawal.py`，数据源为数据库 `integration_opening`，按 `工单结束时间` 统计。

用于月报时传入`--month YYYY-MM`，默认周期为上月26日至本月25日。例如2026年8月月报统计`2026-07-26`至`2026-08-25`。

## 算数前固定筛选

- 先限定数据来源为二编、工单类型为开通和目标统计周期。
- 从基础数据中强制剔除业务类型精确等于`行业视频行业版平台基础`、`行业视频-行业版`、`5G双域专网`的记录。
- 强制剔除业务类型包含`跨省`或`跨国`关键字的记录。
- 强制剔除业务套餐类型包含`跨省`关键字的记录。
- 上述固定排除必须先于总数、竣工量、撤退单数量和撤退率计算；`--all-business-types`也不能绕过这些排除。
- 未传`--business-type`时，使用固定排除后的全部业务类型；传入时在固定排除后进一步按精确值限定。
- 剔除主题包含“测试”或 `test` 的工单。
- 原始表以工单号为主键，指标阶段不二次去重。
- 分母：周期内筛选并剔除测试单后的正式开通工单数。
- 分子：状态为已撤单或已驳回的工单数。
- 同时统计当月已完成竣工量，并按派单时间拆分为当月受理和当月之前受理；派单时间缺失或晚于结束时间的记录单独审计。

## 执行

```bash
python3 metrics/opening/withdrawal.py \
  --month 2026-08 \
  --mode both
```

未经用户明确要求，不修改`--business-type`、`--withdrawal-status`或`--test-keyword`。文件默认写入`outputs/专线开通撤退单率_开始日期_结束日期.json`。

## 验证

- `metric_run` 成功，`result_opening_withdrawal` 包含全省、地市和业务类型结果。
- `ads_metric_detail` 能追溯分母、分子及测试单剔除明细。
- 核对`excluded_business`明细和`business_exclusion_reasons`计数，确认固定排除记录未进入分母、竣工量或撤退单数量。
- 核对公式为 `(已撤单+已驳回)/正式开通工单数`。
- 核对竣工总量等于当月受理、当月之前受理和异常派单时间三组之和。
- 口径版本含 `provisional`，报告结果时说明业务范围和状态口径仍属暂行。

详细口径见 `metrics/opening/withdrawal.README.md`。
