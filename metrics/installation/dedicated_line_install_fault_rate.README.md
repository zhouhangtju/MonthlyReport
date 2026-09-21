# 专线新装报障率

## 数据来源

- 分母及新装时间：数据库 `orch_install` 数据集（编排互联网专线新装单）；
- 投诉匹配：数据库 `eoms_complaint` 数据集（EOMS政企投诉工单）。

## 计算口径

口径与 `export/有数平台/calculate_internet_line_install_fault_rate.py` 一致。新装数据使用 `订单创建时间`限定统计期，以编排的 `产品实例编号`关联 EOMS 的 `计费号码`，并要求新装与投诉地市一致。不额外根据订单状态、订单类型或业务类型过滤。

- 分母：符合条件的新装记录数，不按产品实例编号去重；
- 分子：存在同计费号码、同地市的投诉，且投诉派单时间不早于该条新装订单创建时间的新装记录数；
- 专线新装报障率 = 分子 / 分母。

不对产品实例编号去重。同一产品实例编号有多张新装单时，每张新装单都独立计入分母，并根据自己的订单创建时间判断是否计入分子。计费号仅去除首尾空格和 Excel 数字后缀 `.0`，不改变大小写。

## 运行

```bash
python3 metrics/installation/dedicated_line_install_fault_rate.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

`--mode`可选 `file`、`database`或 `both`。文件默认写入 `outputs/专线新装报障率_起始日期_结束日期.json`；数据库结果写入 `metric_run`、`result_dedicated_line_install_fault`和 `ads_metric_detail`。
