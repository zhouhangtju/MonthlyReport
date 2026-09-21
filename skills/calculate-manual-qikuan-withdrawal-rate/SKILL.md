---
name: calculate-manual-qikuan-withdrawal-rate
description: 从用户在对话中上传或指定的企宽 Excel 明细中，以全部明细为分母、仅以 OP_REMARK=退单完成为分子，计算企宽退单总量、退单率、前三退单率地市、退单原因及占比和各地市退单率。用户提到手工计算企宽退单指标时使用；不用于企宽撤退合并口径或 PPT 生成。
---

# 计算企宽退单率

调用技能包内的 `scripts/calculate.py` 读取 Excel，不修改源文件，不手工计数。

## 输入与口径

- 优先使用对话中唯一的企宽 `.xlsx` 或 `.xlsm` 附件；有多个候选文件且无法唯一确定时询问用户。
- 默认工作表为 `Sheet1`，必需字段为 `CITY`、`OP_REMARK` 和 `FIRST_LEVEL_PROBLEM`。
- 每一个非空明细行计为 1 张当月受理工单，默认不去重。
- 退单数只计 `OP_REMARK` 等于“退单完成”的记录；“撤单完成”不进入分子。
- 退单率 = 退单完成数 / 受理工单总数，分地市和全省分别使用各自的分子、分母计算。
- 前三地市按地市退单率从高到低排序。
- 退单原因只统计“退单完成”记录的 `FIRST_LEVEL_PROBLEM`，各原因占比分母为退单总量。保留用户、前台、建设、其他和网络五类，以保证合计闭合。
- `CITY` 必须属于浙江 11 地市；空值或未知地市直接报错。
- 用于月报时显式传入 `--month YYYY-MM`；不得从文件名猜测月份。

## 运行

```bash
python3 scripts/calculate.py \
  --input "/absolute/path/to/企宽.xlsx" \
  --month 2026-08 \
  --output outputs/manual_metrics/企宽退单率_2026-08.json
```

使用已安装 `openpyxl` 的项目 Python 3.10+ 环境。命令成功后核对全省分子等于 11 地市分子之和，分母也必须相等，原因数之和等于退单总量。报告退单总量、退单率、前三地市、原因及占比、各地市退单率和输出路径。
