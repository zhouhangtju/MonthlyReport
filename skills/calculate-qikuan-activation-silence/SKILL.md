---
name: calculate-qikuan-activation-silence
description: 将手工上传的企宽激活即沉默清单入库，与已入库的有数企宽装机清单按工单号匹配，计算全省、地市、区县、网格占比，供省级业务发展页使用。
---

# 企宽激活即沉默指标

先确认有数 `youshu_install_list` 对报告月 T-3 的完整自然月已有成功采集及入库批次。`--month` 指指标展示的报告月；手工表的文件名不决定统计月份，手工表“定单报结时间”应位于报告月 T-3。例如 2026-10 报告使用 2026-07 的企宽工单作为分母。

在项目根目录运行：

```powershell
python metrics/qikuan_activation_silence/qikuan_activation_silence_metrics.py --month 2026-10 --input "data/offline_data/宽带激活即沉默10月合表.xlsx"
```

如果系统仅提供 `python3`，可用它替换 `python`。同一手工文件和月份重复运行时复用原始数据批次，生成新的成功计算批次。不传 `--input` 时从数据库复用该月最近一次手工入库批次。

口径：有数企宽装机清单报结时间处于报告月 T-3 的所有工单 id 去重后作分母，不额外筛选动作类型；报告月手工清单的工单号与其匹配成功的工单作分子。全省、地市、区县分别汇总；网格按“地市＋市场网格”汇总，同一地市内跨区县的同名网格合并。网格为空的工单保留在全省、地市和区县统计中；PPT 网格排名仅展示分母至少 5 单的网格。

程序将原始手工行和来源文件哈希写入 `raw_qikuan_activation_silence*`，将分子、分母、比例写入 `result_qikuan_activation_silence`，并输出计算 JSON 及未匹配工单号清单。核对命令退出码、来源批次、匹配数、未匹配数后，再运行省级 PPT 生成入口。
