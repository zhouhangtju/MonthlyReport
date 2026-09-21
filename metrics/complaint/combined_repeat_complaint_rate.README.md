# 合计重复投诉率

本指标只合并已经完成算数的结果 JSON，不读取原始投诉数据。

## 输入

- 专线重复投诉率结果 JSON：由 `dedicated_line_repeat_complaint_rate.py --mode file|both` 生成。
- 千里眼重复投诉率结果 JSON：由 `qianliyan_repeat_complaint_rate.py --mode file|both` 生成。
- 企宽重复投诉率结果 JSON：由 `calculate-manual-qikuan-repeat-complaint-rate` 的计算脚本生成。

三份输入必须包含有效的全省结果和11个地市结果。任一组成率缺失、不是有限数值或超出0到1时，脚本停止并报错，不使用0补齐。

## 公式

```text
合计重复投诉率 = 专线重复投诉率*0.4
               + 企宽重复投诉率*0.4
               + 千里眼重复投诉率*0.2
```

全省合计使用三类全省重复投诉率计算。地市合计逐地市使用相同公式计算，再按合计重复投诉率降序选取前三名。

## 运行

```bash
python3 metrics/complaint/combined_repeat_complaint_rate.py \
  --line-result outputs/manual_metrics/专线重复投诉率_2026-06-01_2026-08-31.json \
  --qianliyan-result outputs/manual_metrics/千里眼重复投诉率_2026-06-01_2026-08-31.json \
  --qikuan-result outputs/manual_metrics/企宽重复投诉率_2026-08.json \
  --month 2026-08
```

不传 `--output` 时，结果默认保存到相对路径 `outputs/manual_metrics/合计重复投诉率_月份.json`，例如 `outputs/manual_metrics/合计重复投诉率_2026-08.json`；也可以显式传入其他输出路径。输出 JSON 的 `metric_set` 为 `combined_repeat_complaint_rate`。文件包含公式、权重、三类组成率、全省合计、11地市合计、前三地市和三份输入文件的 SHA-256。生成完整月报或“业务支撑情况”章节时，该结果文件是必需输入。
