---
name: calculate-manual-qikuan-withdrawal-reasons
description: 从用户在对话中上传或指定的企宽 Excel 明细中，以 OP_REMARK 为退单完成或撤单完成为撤退口径，计算企宽撤退总量、撤退率、前三撤退率地市、原因及占比，以及各地市撤单量和退单量。用户提到手工计算企宽撤退单指标时使用；不用于仅看退单完成的企宽退单指标或 PPT 生成。
---

# 统计企宽撤退原因

调用技能包内的 `scripts/calculate.py` 读取 Excel，不修改源文件，不手工计数。

## 输入与口径

- 优先使用对话中唯一的企宽 `.xlsx` 或 `.xlsm` 附件；有多个候选文件且无法唯一确定时询问用户。
- 默认工作表为 `Sheet1`，必需字段为 `CITY`、`OP_REMARK` 和 `FIRST_LEVEL_PROBLEM`。
- 只纳入 `OP_REMARK` 等于“退单完成”或“撤单完成”的记录。
- 撤退率 = （退单完成数 + 撤单完成数）/ 全部受理明细数；全省和各地市分别使用各自分子、分母。
- 前三地市按地市撤退率从高到低排序。
- 按 `CITY × FIRST_LEVEL_PROBLEM` 计数，并计算各原因全省占比。占比分母为纳入的退单完成和撤单完成记录总数。
- 允许的一级原因为：用户原因、前台原因、建设原因、其他原因、网络原因。未知原因必须报错，不得自动并入其他原因。
- 被纳入记录的 `CITY` 或 `FIRST_LEVEL_PROBLEM` 为空时必须报错。
- 未出现的“地市 × 原因”组合补 0 并记入审计信息。
- 用于月报时显式传入 `--month YYYY-MM`；不得从文件名猜测月份。

## 运行

```bash
python3 scripts/calculate.py \
  --input "/absolute/path/to/企宽.xlsx" \
  --month 2026-08 \
  --output outputs/manual_metrics/企宽撤退原因_2026-08.json
```

使用已安装 `openpyxl` 的项目 Python 3.10+ 环境。命令成功后核对五个原因合计等于撤退总量，各地市撤单量与退单量之和等于撤退总量。报告撤退总量、撤退率、前三地市、原因及占比、各地市撤单量和退单量以及输出路径。
