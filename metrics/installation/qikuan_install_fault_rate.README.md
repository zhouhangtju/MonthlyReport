# 企宽新装报障率

## 数据来源

- 分母：数据库 `youshu_install` 数据集（有数企宽新装清单）；
- 投诉匹配：数据库 `youshu_complaint` 数据集（有数企宽投诉清单）。

## 计算口径

统计期内，有效新装工单必须同时具备 `工单id`、`宽带账号`和`派单时间`。投诉按标准化后的 `宽带账号`关联新装工单；同一账号有多条投诉时取最晚投诉派单时间。

- 分母：有效企宽新装工单数；
- 分子：存在统计期内投诉，且投诉派单时间严格晚于新装派单时间的新装工单数；
- 企宽新装报障率 = 分子 / 分母。

一个宽带账号存在多张新装工单时按工单分别计数。账号会去除首尾空格、转为大写并清理 Excel 数字尾缀 `.0`。除全省结果外，同时按新装清单的 `地市`输出地市结果。

## 运行

```bash
python3 metrics/installation/qikuan_install_fault_rate.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

`--mode`可选 `file`、`database`或 `both`。文件默认写入 `outputs/企宽新装报障率_起始日期_结束日期.json`；数据库结果写入 `metric_run`、`ads_metric_result`和 `ads_metric_detail`。

