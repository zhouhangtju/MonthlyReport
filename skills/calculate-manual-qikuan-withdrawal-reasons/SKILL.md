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

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。

### MySQL 入库

需要同时入库时，在计算命令中传入 `--mysql --month YYYY-MM`。结果写入 `manual_metric_result`，同指标同月份再次运行会更新该月结果。


## 区县维度与入库

区县统计默认开启，--no-county 可关闭；Python 调用传 include_county=False。映射表默认 data/区县信息汇总.xlsx，必须包含“地市、区县、标准区县”，可用 --county-map 指定其他路径。映射缺失时明确报错。

区县统计要求输入包含 CELL。保留原 CITY 地市口径，通过 CELL 在全部地市区县别名中唯一匹配。CELL 为空、未匹配、多归属或匹配地市与 CITY 不一致时归入 CITY 的“未归属区县”，并记录 audit.cell_quality 和 audit.cell_issues。区县输出受理量、退单量、撤单量、撤退量、撤退率、退单率和原因数量占比。分母为全部受理明细，原因占比分母为区县撤退总量。不会根据 --month 自动过滤 Excel 日期。

保留原全省、地市及 ppt_overlay 字段，新增顶层 counties 列表。无工单的标准区县数量为零，比率为 null。--mysql 将完整 JSON（含 counties）保存到 manual_metric_result.result_json，按 metric_set、report_month 更新同月结果。关闭区县后再次入库会以本次无区县结果替换同月 JSON。

在项目根目录运行：

```bash
python3 skills/calculate-manual-qikuan-withdrawal-reasons/scripts/calculate.py --input "/实际路径/明细.xlsx" --month 2026-10 --output "outputs/calculate-manual-qikuan-withdrawal-reasons_2026-10.json" --county-map "/实际路径/区县信息汇总.xlsx" --mysql
python3 skills/calculate-manual-qikuan-withdrawal-reasons/scripts/calculate.py --input "/实际路径/明细.xlsx" --month 2026-10 --output "outputs/calculate-manual-qikuan-withdrawal-reasons_2026-10.json" --no-county --mysql
```


## 计算后原始清单归档

CLI要求--month。计算成功后自动归档，默认D:\dev-projects\openclaw_data\outputs\withdrawal，可用--archive-root修改。
按报告月份/指标集/source、province、cities/11地市固定目录保存。source备份原始Excel，province及各地市输出原始清单.xlsx，保留全部原始列并增加归档_源行号、归档_标准地市、归档_标准区县、归档_匹配状态。
区县仅作为列，无区县目录；--no-county时不匹配区县。无法确定地市的原始行归入未归属地市。
全省和地市清单包含全部原始记录，未按分子筛选，企宽包含完整受理记录。每个技能使用独立固定目录，空地市也生成表头文件。
manifest记录原始文件哈希、行数与生成时间；计算期间源文件变更时归档失败。成功归档后才输出结果JSON并执行--mysql入库，结果的evidence保存归档根及相对路径。同月重跑覆盖该指标集的固定目录，先写临时目录，完成后替换；不会保留同月旧清单。
