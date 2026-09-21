---
name: calculate-qianliyan-repeat-complaint-rate
description: 从 EOMS 政企投诉工单计算千里眼重复投诉率，输出全省和地市结果及审计明细。用户提到千里眼重复投诉率、视频监控重复投诉或24小时重复派单规则时使用。
---

# 千里眼重复投诉率

调用 `metrics/complaint/qianliyan_repeat_complaint_rate.py`，读取数据库 `eoms_complaint`，按 `派单时间` 截取周期。

默认统计周期：用于月报 PPT 时，若用户只给出月报月份而未显式指定起止日期，本指标按月报月及前两个月的三个自然月计算。也就是 `end-date` 取月报月最后一天，`start-date` 取月报月往前数第 2 个月的第一天。例如绘制 2026 年 8 月汇报 PPT 时，默认使用 `2026-06-01` 至 `2026-08-31`，不是 8 月单月。

## 核心口径

- 业务类别为千里眼，或视频监控但不含专线专网。
- 客服流水号非空且 `工单状态=正常结束`，剔除重置鉴权码主题。
- 客户标识优先计费号码，为空用手机号码；Key 为 `客户标识|一级业务类别`。
- 分母为唯一客户标识数。
- 指定班组/结单人的工单只从分子候选剔除，不影响分母。
- 同一Key相邻派单间隔不超过24小时的后一单从分子候选剔除；剩余至少2次才是重复Key。
- 分子为命中重复Key的唯一客户标识数。

## 执行

```bash
python3 metrics/complaint/qianliyan_repeat_complaint_rate.py \
  --start-date 2026-06-01 \
  --end-date 2026-08-31 \
  --mode both
```

## 验证

- `metric_run` 成功，`result_qianliyan_repeat_complaint` 有全省与地市结果。
- `ads_metric_detail` 区分分母、分子和剔除记录。
- 不用“最后处理人”替代“结单人”，不把24小时规则作用到分母。
- 默认文件为 `outputs/千里眼重复投诉率_起始日期_结束日期.json`。

详细口径见 `metrics/complaint/qianliyan_repeat_complaint_rate.README.md`。
