# 商客新装报障率

## 数据来源

本指标不重新读取业务明细，而是读取同一统计周期内以下两个指标的最新成功数据库结果：

- 企宽新装报障率 `qikuan_install_fault_rate`；
- 专线新装报障率 `dedicated_line_install_fault_rate`。

因此，执行商客指标前必须先以完全相同的起止日期计算并入库企宽和专线指标。

## 计算口径

- 商客分子 = 企宽分子 + 专线分子；
- 商客分母 = 企宽分母 + 专线分母；
- 商客新装报障率 = 商客分子 / 商客分母。

计算的是汇总分子除以汇总分母，不是企宽报障率与专线报障率的算术平均。全省和各地市均按相同方式合并；某地市只有一类业务数据时，另一类按0计数。合并结果会记录两个上游指标批次ID，便于追溯。

## 运行

```bash
python3 metrics/installation/commercial_customer_install_fault_rate.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

`--mode`可选 `file`、`database`或 `both`。文件默认写入 `outputs/商客新装报障率_起始日期_结束日期.json`；数据库结果写入 `metric_run`和 `result_commercial_install_fault`。

