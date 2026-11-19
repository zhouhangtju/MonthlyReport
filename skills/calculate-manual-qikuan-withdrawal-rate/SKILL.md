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

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。

### MySQL 入库

需要同时入库时，在计算命令中传入 `--mysql --month YYYY-MM`。结果写入 `manual_metric_result`，同指标同月份再次运行会更新该月结果。


## 区县统计

默认开启区县统计，--no-county 可关闭，Python 调用传 include_county=False。
--county-map 指定包含“地市、区县、标准区县”三列的映射表，默认 data/区县信息汇总.xlsx。
开启时要求输入包含 CELL。保留原 CITY 地市口径，以 CELL 唯一匹配区县。
空值、未匹配、多归属及匹配地市与 CITY 冲突时归入该 CITY 的“未归属区县”，在 audit.cell_quality、audit.cell_issues 中记录。
区县输出 accepted_count、return_count、return_rate 和各原因 count、share。分子仅为退单完成，分母包含全部受理明细。零分母比率为 null。
原全省、地市及 ppt_overlay 结构保留，新增顶层 counties 列表。--mysql 将完整结果保存到 manual_metric_result.result_json，metric_set 仍为 qikuan_withdrawal_rate_by_city。关闭区县后同月再次入库会替换原 JSON。
月份不会自动过滤 Excel 日期，应提供对应月份明细。

在项目根目录运行：

```bash
python3 skills/calculate-manual-qikuan-withdrawal-rate/scripts/calculate.py --input "/实际路径/企宽.xlsx" --month 2026-10 --output outputs/企宽退单率_2026-10.json --county-map "/实际路径/区县信息汇总.xlsx" --mysql
python3 skills/calculate-manual-qikuan-withdrawal-rate/scripts/calculate.py --input "/实际路径/企宽.xlsx" --month 2026-10 --output outputs/企宽退单率_2026-10.json --no-county --mysql
```


## 计算后原始清单归档

CLI要求--month。计算成功后自动归档，默认D:\dev-projects\openclaw_data\outputs\withdrawal，可用--archive-root修改。
按报告月份/指标集/source、province、cities/11地市固定目录保存。source备份原始Excel，province及各地市输出原始清单.xlsx，保留全部原始列并增加归档_源行号、归档_标准地市、归档_标准区县、归档_匹配状态。
区县仅作为列，无区县目录；--no-county时不匹配区县。无法确定地市的原始行归入未归属地市。
全省和地市清单包含全部原始记录，未按分子筛选，企宽包含完整受理记录。每个技能使用独立固定目录，空地市也生成表头文件。
manifest记录原始文件哈希、行数与生成时间；计算期间源文件变更时归档失败。成功归档后才输出结果JSON并执行--mysql入库，结果的evidence保存归档根及相对路径。同月重跑覆盖该指标集的固定目录，先写临时目录，完成后替换；不会保留同月旧清单。
