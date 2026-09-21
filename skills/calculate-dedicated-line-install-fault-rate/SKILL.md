---
name: calculate-dedicated-line-install-fault-rate
description: 从编排互联网专线新装单和 EOMS 投诉工单计算专线新装报障率。用户提到互联网专线新装保障率、专线新装报障率或计费号匹配投诉时使用。
---

# 专线新装报障率

调用 `metrics/installation/dedicated_line_install_fault_rate.py`，读取 `orch_install` 和 `eoms_complaint`。

默认统计周期：用于月报 PPT 时，若用户只给出月报月份而未显式指定起止日期，本指标按月报月及前两个月的三个自然月计算。也就是 `end-date` 取月报月最后一天，`start-date` 取月报月往前数第 2 个月的第一天。例如绘制 2026 年 8 月汇报 PPT 时，默认使用 `2026-06-01` 至 `2026-08-31`，不是 8 月单月。

## 口径

- 新装记录按 `订单创建时间` 限定统计期。
- 以 `产品实例编号` 匹配 EOMS `计费号码`，并要求地市一致。
- 不额外按订单状态、订单类型或业务类型筛选。
- 分母为符合条件的新装记录数，明确不按产品实例编号去重。
- 分子为存在同计费号、同地市投诉，且投诉派单时间不早于该条订单创建时间的新装记录数。

## 执行

```bash
python3 metrics/installation/dedicated_line_install_fault_rate.py \
  --start-date 2026-06-01 \
  --end-date 2026-08-31 \
  --mode both
```

结果写入三张指标表，文件默认写入 `outputs/专线新装报障率_起始日期_结束日期.json`。

## 验证

- 先确认 `orch_install` 和 `eoms_complaint` 已覆盖周期。
- 同一产品实例编号的多张新装单必须分别进入分母并独立判断分子。
- 核对全省及地市结果，不得增加产品实例编号去重。

详细口径见 `metrics/installation/dedicated_line_install_fault_rate.README.md`。
