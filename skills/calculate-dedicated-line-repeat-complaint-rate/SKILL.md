---
name: calculate-dedicated-line-repeat-complaint-rate
description: 从 EOMS 政企投诉工单计算专线或专网重复投诉率，输出全省和地市结果及审计明细。用户提到专线重复投诉率、专网重复投诉率或1小时重复派单规则时使用。
---

# 专线/专网重复投诉率

调用 `metrics/complaint/dedicated_line_repeat_complaint_rate.py`，读取数据库 `eoms_complaint`，按 `派单时间` 截取周期。

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
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

## 验证

- `metric_run` 成功，`ads_metric_result` 有全省和地市结果。
- `ads_metric_detail` 可区分分母、分子及剔除原因。
- 不要求客服流水号非空，不把1小时规则作用到分母。
- 默认文件为 `outputs/专线专网重复投诉率_起始日期_结束日期.json`。

详细口径见 `metrics/complaint/dedicated_line_repeat_complaint_rate.README.md`。

## 默认收尾：清理源数据

完成上述验证且本次结果成功入库后，默认调用 `skills/cleanup-source-data/SKILL.md`，传递本次数据库绝对路径、实际周期、成功指标批次及源批次，并合并当前任务待清理范围。候选数据集：`eoms_complaint`。

按清理 Skill 执行预览及通过后的 `--apply`，无需再次询问是否清理。共享源数据仍有未完成的依赖或当前任务计划中的后续消费者时，登记待清理并继续算数，在相关算数结束后再评估；不能为了清理额外扩大算数任务。用户要求保留明细、仅预览，或本次为 `file` 模式、算数失败/未入库时，不执行删除。验证明细必须在清理之前完成。
