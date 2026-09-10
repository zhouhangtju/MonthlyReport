# 新装报障类指标

本目录的计算脚本只读取数据库，不依赖 `export` 目录或取数生成的 Excel 文件。项目统一使用“新装报障率”这一名称。

## 指标与执行顺序

1. `qikuan_install_fault_rate.py`：计算企宽新装报障率；
2. `dedicated_line_install_fault_rate.py`：计算专线新装报障率；
3. `commercial_customer_install_fault_rate.py`：读取前两项同周期的最新成功结果，计算商客新装报障率。

商客指标必须在企宽和专线指标之后执行，且三个脚本的起止日期必须一致。

```bash
python3 metrics/installation/qikuan_install_fault_rate.py \
  --start-date 2026-08-01 --end-date 2026-08-31 --mode both

python3 metrics/installation/dedicated_line_install_fault_rate.py \
  --start-date 2026-08-01 --end-date 2026-08-31 --mode both

python3 metrics/installation/commercial_customer_install_fault_rate.py \
  --start-date 2026-08-01 --end-date 2026-08-31 --mode both
```

各项详细口径分别见：

- `qikuan_install_fault_rate.README.md`
- `dedicated_line_install_fault_rate.README.md`
- `commercial_customer_install_fault_rate.README.md`

