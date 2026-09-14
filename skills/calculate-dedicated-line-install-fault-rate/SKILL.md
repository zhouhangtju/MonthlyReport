---
name: calculate-dedicated-line-install-fault-rate
description: 从编排互联网专线新装单和 EOMS 投诉工单计算专线新装报障率。用户提到互联网专线新装保障率、专线新装报障率或计费号匹配投诉时使用。
---

# 专线新装报障率

调用 `metrics/installation/dedicated_line_install_fault_rate.py`，读取 `orch_install` 和 `eoms_complaint`。

## 口径

- 新装记录按 `订单创建时间` 限定统计期。
- 以 `产品实例编号` 匹配 EOMS `计费号码`，并要求地市一致。
- 不额外按订单状态、订单类型或业务类型筛选。
- 分母为符合条件的新装记录数，明确不按产品实例编号去重。
- 分子为存在同计费号、同地市投诉，且投诉派单时间不早于该条订单创建时间的新装记录数。

## 执行

```bash
python3 metrics/installation/dedicated_line_install_fault_rate.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

结果写入三张指标表，文件默认写入 `outputs/专线新装报障率_起始日期_结束日期.json`。

## 验证

- 先确认 `orch_install` 和 `eoms_complaint` 已覆盖周期。
- 同一产品实例编号的多张新装单必须分别进入分母并独立判断分子。
- 核对全省及地市结果，不得增加产品实例编号去重。

详细口径见 `metrics/installation/dedicated_line_install_fault_rate.README.md`。

## 默认收尾：清理源数据

完成上述验证且本次结果成功入库后，默认调用 `skills/cleanup-source-data/SKILL.md`，传递本次数据库绝对路径、实际周期、成功指标批次及源批次，并合并当前任务待清理范围。候选数据集：`orch_install`、`eoms_complaint`。

按清理 Skill 执行预览及通过后的 `--apply`，无需再次询问是否清理。共享源数据仍有未完成的依赖或当前任务计划中的后续消费者时，登记待清理并继续算数，在相关算数结束后再评估；不能为了清理额外扩大算数任务。用户要求保留明细、仅预览，或本次为 `file` 模式、算数失败/未入库时，不执行删除。验证明细必须在清理之前完成。
