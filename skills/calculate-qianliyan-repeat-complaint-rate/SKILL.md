---
name: calculate-qianliyan-repeat-complaint-rate
description: 从 EOMS 政企投诉工单计算千里眼重复投诉率，输出全省和地市结果及审计明细。用户提到千里眼重复投诉率、视频监控重复投诉或24小时重复派单规则时使用。
---

# 千里眼重复投诉率

调用 `metrics/complaint/qianliyan_repeat_complaint_rate.py`，读取数据库 `eoms_complaint`，按 `派单时间` 截取周期。

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
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

## 验证

- `metric_run` 成功，`ads_metric_result` 有全省与地市结果。
- `ads_metric_detail` 区分分母、分子和剔除记录。
- 不用“最后处理人”替代“结单人”，不把24小时规则作用到分母。
- 默认文件为 `outputs/千里眼重复投诉率_起始日期_结束日期.json`。

详细口径见 `metrics/complaint/qianliyan_repeat_complaint_rate.README.md`。

## 默认收尾：清理源数据

完成上述验证且本次结果成功入库后，默认调用 `skills/cleanup-source-data/SKILL.md`，传递本次数据库绝对路径、实际周期、成功指标批次及源批次，并合并当前任务待清理范围。候选数据集：`eoms_complaint`。

按清理 Skill 执行预览及通过后的 `--apply`，无需再次询问是否清理。共享源数据仍有未完成的依赖或当前任务计划中的后续消费者时，登记待清理并继续算数，在相关算数结束后再评估；不能为了清理额外扩大算数任务。用户要求保留明细、仅预览，或本次为 `file` 模式、算数失败/未入库时，不执行删除。验证明细必须在清理之前完成。
