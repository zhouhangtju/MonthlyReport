# EOMS重复投诉类指标

本目录从数据库 `eoms_complaint` 数据集计算重复投诉率，不在运行时引用 `export` 目录。正式口径迁移自原工具包文件名带“客服流水号口径”的脚本。

```bash
python3 metrics/complaint/dedicated_line_repeat_complaint_rate.py \
  --start-date 2026-08-01 --end-date 2026-08-31 --mode both

python3 metrics/complaint/qianliyan_repeat_complaint_rate.py \
  --start-date 2026-08-01 --end-date 2026-08-31 --mode both
```

两个指标相互独立，没有执行顺序要求。详细口径分别见：

- `dedicated_line_repeat_complaint_rate.README.md`
- `qianliyan_repeat_complaint_rate.README.md`

