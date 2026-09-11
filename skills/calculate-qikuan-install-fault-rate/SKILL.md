---
name: calculate-qikuan-install-fault-rate
description: 从有数企宽新装清单和企宽投诉清单计算企宽新装报障率。用户提到企宽新装保障率、企宽新装报障率、企宽新装后的投诉匹配时使用。
---

# 企宽新装报障率

调用 `metrics/installation/qikuan_install_fault_rate.py`，读取数据库 `youshu_install` 与 `youshu_complaint`。

## 口径

- 有效新装必须有 `工单id`、`宽带账号`、`派单时间`。
- 新装清单不按命令周期再次过滤，只剔除所有业务字段完全相同的重复行；同一工单ID其他字段不同则保留。
- 投诉按统计期过滤，同一账号多条投诉取最晚投诉派单时间。
- 分母为有效新装工单数；分子为投诉派单时间严格晚于新装派单时间的新装工单数。

## 执行

```bash
python3 metrics/installation/qikuan_install_fault_rate.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

结果写入 `metric_run`、`ads_metric_result`、`ads_metric_detail`，文件默认写入 `outputs/企宽新装报障率_起始日期_结束日期.json`。

## 验证

- 先确认两个源数据集均已入库。
- 检查全省及地市分子、分母；一个账号多张新装单应按工单分别计数。
- 不把“严格晚于”改成“大于等于”，不按工单ID额外去重。

详细口径见 `metrics/installation/qikuan_install_fault_rate.README.md`。
