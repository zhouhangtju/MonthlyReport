---
name: calculate-combined-repeat-complaint-rate
description: 在专线、企宽和千里眼重复投诉率结果都已生成后，计算月报使用的加权合计重复投诉率。只合并结果 JSON，不读取投诉原始表，也不计算商客业务整体重复投诉率。
---

# 计算合计重复投诉率

在项目根目录运行 `metrics/complaint/combined_repeat_complaint_rate.py`。先确认三份输入 JSON 对应同一月报月份，均有有效的全省和浙江 11 地市结果。缺少组成率或数值无效时停止，不以 0 代替。

公式：`专线重复投诉率 × 0.4 + 企宽重复投诉率 × 0.4 + 千里眼重复投诉率 × 0.2`。全省用三项全省率计算；各地市分别计算并按合计率排序。它不是“商客业务整体重复投诉率”。

例如生成 2026 年 8 月结果（输入路径应按实际文件位置调整）：

```bash
python3 metrics/complaint/combined_repeat_complaint_rate.py \
  --line-result "outputs/专线/专网重复投诉率_2026-06-01_2026-08-31.json" \
  --qianliyan-result "outputs/千里眼重复投诉率_2026-06-01_2026-08-31.json" \
  --qikuan-result "outputs/manual_metrics/企宽重复投诉率2026-08-01_2026-08-31.json" \
  --month 2026-08
```

若 `python3` 不可用，可改用 `python`；先确认它是 Python 3.10 及以上且已安装项目依赖。默认输出为 `outputs/manual_metrics/合计重复投诉率_YYYY-MM.json`，也可用 `--output` 指定路径。

运行后核对全省和 11 地市合计率、前三地市、公式和权重，以及 `sources` 中三份输入文件的 SHA-256。生成 PPT 时同一月份、同一 `metric_set` 的结果 JSON 在 `outputs/manual_metrics` 中只能保留一份。详细口径见 `metrics/complaint/combined_repeat_complaint_rate.README.md`。
