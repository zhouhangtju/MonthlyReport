---
name: calculate-manual-withdrawal-reasons
description: 从用户在对话中上传或指定的 Excel 撤退单明细中，按地市和原因大类统计专线撤退单，并生成可供月报后续使用的标准化 JSON。用户提到手工统计撤退原因、撤退单原因分地市汇总或解析撤退原因 Excel 时使用；不用于计算撤退单率或生成 PPT。
---

# 统计专线撤退单原因

调用技能包内的 `scripts/calculate.py` 读取 Excel 明细，不要手工计数，不要修改源文件。

## 输入选择

- 用户在对话中上传了一个 `.xlsx` 或 `.xls` 时，直接使用该附件的本地路径。
- 同时有多个表格时，优先选择文件名或工作表中明确包含“撤退单”的文件；仍无法唯一确定时询问用户。
- 默认读取“撤退单清单”工作表。如果工作表名不同，先只读检查工作表名和表头，再用 `--sheet` 指定。
- 用于月报时，必须从用户请求获取 `YYYY-MM` 月份并传入 `--month`。不得根据类似 `7.26-8.25` 的文件名猜测年份或月报归属。

## 统计口径

- 每一行明细计为 1 张撤退单，不根据工单号自动去重。
- 必需列为“地市”和“大类”。任一列缺失或值为空时构建失败，不把空值视为其他原因。
- 地市只允许浙江 11 地市，输出顺序固定为：杭州、嘉兴、宁波、温州、金华、绍兴、湖州、台州、衢州、丽水、舟山。
- 大类只允许：网络建设原因、用户原因、前台原因、其他原因。未知值必须报错，不得悄悄归入“其他原因”。
- 未出现的“地市 × 大类”组合补 0，并在输出审计信息中列出。
- 大类占比 = 该大类条数 / 所有有效明细条数。

## 运行

在包含 `pyproject.toml` 和 `reporting/` 的项目根目录执行：

```bash
python3 scripts/calculate.py \
  --input "/absolute/path/to/撤退单.xlsx" \
  --month 2026-08 \
  --output outputs/manual_metrics/专线撤退单原因_2026-08.json
```

使用已安装项目依赖的 Python 3.10+；至少需要 `pandas` 和对应 Excel 引擎。如系统 `python3` 缺少这些依赖，改用项目虚拟环境或 Codex 工作区依赖运行时，不要将导入错误视为源文件错误。

用户只要独立统计且未指定月报月份时，可以省略 `--month`，输出中 `report_month` 为 `null`。

## 验证与交付

1. 命令退出为 0，且 JSON 可用 `allow_nan=False` 序列化。
2. `summary.source_row_count` 必须等于四个大类合计，四个 `*Share` 之和在数值误差内等于 1（空表除外）。
3. 向用户报告源明细数、四类合计、零值组合数和输出路径。
4. 如果源文件本身没有某个大类，明确说明该大类统计为 0；不得声称这证明业务上没有该类撤退单。
5. 该技能只产出标准化统计，不写数据库、不修改 Excel、不生成或修改 PPT。

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。

### MySQL 入库

需要同时入库时，在计算命令中传入 `--mysql --month YYYY-MM`。结果写入 `manual_metric_result`，同指标同月份再次运行会更新该月结果。


## 区县维度与入库

区县统计默认开启，--no-county 可关闭；Python 调用传 include_county=False。映射表默认 data/区县信息汇总.xlsx，必须包含“地市、区县、标准区县”，可用 --county-map 指定其他路径。映射缺失时明确报错。

区县统计要求输入包含“区县、工单主题”。按“地市”限定映射，依次匹配区县原值、区县关键词、工单主题，失败归入该地市“未归属区县”。区县输出 sample_count 及各原因 count、share，占比分母为该区县原因样本总数。

保留原全省、地市及 ppt_overlay 字段，新增顶层 counties 列表。无工单的标准区县数量为零，比率为 null。--mysql 将完整 JSON（含 counties）保存到 manual_metric_result.result_json，按 metric_set、report_month 更新同月结果。关闭区县后再次入库会以本次无区县结果替换同月 JSON。

在项目根目录运行：

```bash
python3 skills/calculate-manual-withdrawal-reasons/scripts/calculate.py --input "/实际路径/明细.xlsx" --month 2026-10 --output "outputs/calculate-manual-withdrawal-reasons_2026-10.json" --county-map "/实际路径/区县信息汇总.xlsx" --mysql
python3 skills/calculate-manual-withdrawal-reasons/scripts/calculate.py --input "/实际路径/明细.xlsx" --month 2026-10 --output "outputs/calculate-manual-withdrawal-reasons_2026-10.json" --no-county --mysql
```


## 计算后原始清单归档

CLI要求--month。计算成功后自动归档，默认D:\dev-projects\openclaw_data\outputs\withdrawal，可用--archive-root修改。
按报告月份/指标集/source、province、cities/11地市固定目录保存。source备份原始Excel，province及各地市输出原始清单.xlsx，保留全部原始列并增加归档_源行号、归档_标准地市、归档_标准区县、归档_匹配状态。
区县仅作为列，无区县目录；--no-county时不匹配区县。无法确定地市的原始行归入未归属地市。
全省和地市清单包含全部原始记录，未按分子筛选，企宽包含完整受理记录。每个技能使用独立固定目录，空地市也生成表头文件。
manifest记录原始文件哈希、行数与生成时间；计算期间源文件变更时归档失败。成功归档后才输出结果JSON并执行--mysql入库，结果的evidence保存归档根及相对路径。同月重跑覆盖该指标集的固定目录，先写临时目录，完成后替换；不会保留同月旧清单。
