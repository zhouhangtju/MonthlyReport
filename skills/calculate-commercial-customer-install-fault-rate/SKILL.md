---
name: calculate-commercial-customer-install-fault-rate
description: 汇总同周期企宽和专线新装报障率的分子分母，计算商客新装报障率。用户提到商客新装保障率、商客新装报障率或合并企宽与专线指标时使用。
---

# 商客新装报障率

调用 `metrics/installation/commercial_customer_install_fault_rate.py`。本指标不读业务明细，而是读取同周期最新成功的企宽和专线指标结果。

默认统计周期：用于月报 PPT 时，若用户只给出月报月份而未显式指定起止日期，本指标按月报月及前两个月的三个自然月计算。也就是 `end-date` 取月报月最后一天，`start-date` 取月报月往前数第 2 个月的第一天。例如绘制 2026 年 8 月汇报 PPT 时，默认使用 `2026-06-01` 至 `2026-08-31`，并且两个上游指标也必须使用完全相同的起止日期。

## 前置条件与公式

必须先以完全相同的起止日期、同一个数据库运行并入库：

1. `qikuan_install_fault_rate`
2. `dedicated_line_install_fault_rate`

商客分子等于两类分子之和，商客分母等于两类分母之和；结果不是两个百分比的算术平均。

## 执行

```bash
python3 metrics/installation/commercial_customer_install_fault_rate.py \
  --start-date 2026-06-01 \
  --end-date 2026-08-31 \
  --mode both
```

## 验证

- 缺少任一同周期上游成功批次时，先运行对应上游 Skill，不伪造0值。
- 全省和各地市均核对“分子相加、分母相加”；某地市仅有一类业务时另一类按0计数。
- `metric_run` 和 `result_commercial_install_fault` 应记录成功结果及两个上游批次ID。
- 默认文件为 `outputs/商客新装报障率_起始日期_结束日期.json`。

详细口径见 `metrics/installation/commercial_customer_install_fault_rate.README.md`。
