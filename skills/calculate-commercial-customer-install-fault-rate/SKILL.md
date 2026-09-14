---
name: calculate-commercial-customer-install-fault-rate
description: 汇总同周期企宽和专线新装报障率的分子分母，计算商客新装报障率。用户提到商客新装保障率、商客新装报障率或合并企宽与专线指标时使用。
---

# 商客新装报障率

调用 `metrics/installation/commercial_customer_install_fault_rate.py`。本指标不读业务明细，而是读取同周期最新成功的企宽和专线指标结果。

## 前置条件与公式

必须先以完全相同的起止日期、同一个数据库运行并入库：

1. `qikuan_install_fault_rate`
2. `dedicated_line_install_fault_rate`

商客分子等于两类分子之和，商客分母等于两类分母之和；结果不是两个百分比的算术平均。

## 执行

```bash
python3 metrics/installation/commercial_customer_install_fault_rate.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

## 验证

- 缺少任一同周期上游成功批次时，先运行对应上游 Skill，不伪造0值。
- 全省和各地市均核对“分子相加、分母相加”；某地市仅有一类业务时另一类按0计数。
- `metric_run` 和 `ads_metric_result` 应记录成功结果及两个上游批次ID。
- 默认文件为 `outputs/商客新装报障率_起始日期_结束日期.json`。

详细口径见 `metrics/installation/commercial_customer_install_fault_rate.README.md`。

## 默认收尾：清理源数据

完成上述验证且本次结果成功入库后，默认调用 `skills/cleanup-source-data/SKILL.md`，传递本次数据库绝对路径、实际周期、成功指标批次及源批次，并合并当前任务待清理范围。候选数据集：`youshu_install`、`youshu_complaint`、`orch_install`、`eoms_complaint`（沿两项前置指标追溯源批次）。

按清理 Skill 执行预览及通过后的 `--apply`，无需再次询问是否清理。共享源数据仍有未完成的依赖或当前任务计划中的后续消费者时，登记待清理并继续算数，在相关算数结束后再评估；不能为了清理额外扩大算数任务。用户要求保留明细、仅预览，或本次为 `file` 模式、算数失败/未入库时，不执行删除。验证明细必须在清理之前完成。
