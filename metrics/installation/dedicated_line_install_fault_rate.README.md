# 专线新装报障率

## 数据来源

- 分母及新装时间：数据库 `orch_install` 数据集（编排互联网专线新装单）；
- 投诉匹配：数据库 `eoms_complaint` 数据集（EOMS政企投诉工单）。

## 计算口径

新装数据按照接口取数口径使用 `派单时间`限定统计期，并要求 `订单状态=已完成`、`订单类型=开通`、`业务类型=互联网专线`。以编排的 `产品实例编号`关联EOMS的 `计费号码`，并要求新装与投诉地市一致。

- 分母：符合条件的唯一产品实例编号数；
- 分子：统计期内存在同计费号码、同地市的投诉，且投诉派单时间不早于首次新装时间的唯一产品实例编号数；
- 专线新装报障率 = 分子 / 分母。

同一产品实例编号有多张新装单时，取最早派单时间作为新装时间，并按一个客户账号计数。账号和地市在匹配前会做格式标准化。

## 运行

```bash
python3 metrics/installation/dedicated_line_install_fault_rate.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

`--mode`可选 `file`、`database`或 `both`。文件默认写入 `outputs/专线新装报障率_起始日期_结束日期.json`；数据库结果写入 `metric_run`、`ads_metric_result`和 `ads_metric_detail`。
