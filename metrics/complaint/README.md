# EOMS重复投诉类指标

本目录从数据库 `eoms_complaint` 数据集计算重复投诉率，不在运行时引用 `export` 目录。正式口径迁移自原工具包文件名带“客服流水号口径”的脚本。

```bash
python3 metrics/complaint/dedicated_line_repeat_complaint_rate.py \
  --start-date 2026-08-01 --end-date 2026-08-31 --mode both

python3 metrics/complaint/qianliyan_repeat_complaint_rate.py \
  --start-date 2026-08-01 --end-date 2026-08-31 --mode both
```

两个基础指标相互独立，没有执行顺序要求。专线、千里眼和企宽三份结果都生成后，运行合计脚本：

```bash
python3 metrics/complaint/combined_repeat_complaint_rate.py \
  --line-result outputs/manual_metrics/专线重复投诉率_2026-06-01_2026-08-31.json \
  --qianliyan-result outputs/manual_metrics/千里眼重复投诉率_2026-06-01_2026-08-31.json \
  --qikuan-result outputs/manual_metrics/企宽重复投诉率_2026-08.json \
  --month 2026-08
```

不传 `--output` 时，结果默认保存到相对路径 `outputs/manual_metrics/合计重复投诉率_月份.json`。合计结果使用 `专线重复投诉率*0.4 + 企宽重复投诉率*0.4 + 千里眼重复投诉率*0.2`，输出全省、11地市及前三地市。PPT直接读取该结果文件，不在绘图阶段重新计算。

详细口径分别见：

- `dedicated_line_repeat_complaint_rate.README.md`
- `qianliyan_repeat_complaint_rate.README.md`
- `combined_repeat_complaint_rate.README.md`
