---
name: calculate-dedicated-line-repeat-complaint-rate
description: 从 EOMS 政企投诉工单计算专线或专网重复投诉率，输出全省和地市结果及审计明细。用户提到专线重复投诉率、专网重复投诉率或1小时重复派单规则时使用。
---

# 专线/专网重复投诉率

调用 `metrics/complaint/dedicated_line_repeat_complaint_rate.py`，读取数据库 `eoms_complaint`，按 `派单时间` 截取周期。

默认统计周期：用于月报 PPT 时，若用户只给出月报月份而未显式指定起止日期，本指标按月报月及前两个月的三个自然月计算。也就是 `end-date` 取月报月最后一天，`start-date` 取月报月往前数第 2 个月的第一天。例如绘制 2026 年 8 月汇报 PPT 时，默认使用 `2026-06-01` 至 `2026-08-31`，不是 8 月单月。

## 核心口径

- 业务类别包含专线或专网，剔除 `isSelfbuild=1`。
- 只保留状态为正常结束、已完成或完成的工单，剔除重置鉴权码主题。
- 客户标识优先计费号码，并沿用附加报结信息和多文本字段提取 e55 的逻辑；仍为空用手机号。
- Key 为 `客户标识|一级业务类别`，分母为全部唯一Key数。
- 满足退单原因非空、重保班组且退单原因不含售中催单的记录整体剔除，同时影响分子和分母。
- 同一Key相邻派单间隔不超过1小时的后一单仅从分子候选剔除。
- 分子为处理后仍至少出现2次的重复Key数。

## 执行

```bash
python3 metrics/complaint/dedicated_line_repeat_complaint_rate.py \
  --start-date 2026-06-01 \
  --end-date 2026-08-31 \
  --mode both
```

## 验证

- `metric_run` 成功，`result_dedicated_line_repeat_complaint` 有全省和地市结果。
- `ads_metric_detail` 可区分分母、分子及剔除原因。
- 不要求客服流水号非空，不把1小时规则作用到分母。
- 默认文件为 `outputs/专线专网重复投诉率_起始日期_结束日期.json`。

详细口径见 `metrics/complaint/dedicated_line_repeat_complaint_rate.README.md`。
