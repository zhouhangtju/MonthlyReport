---
name: calculate-qikuan-opening
description: 从 MySQL 已入库的有数装机报结量快照计算企宽开通量、自然月同比及1至N月累计同比，输出全省和11地市结果、JSON及可选结果入库。用于企宽开通量月报计算，不用于企宽存量或新装报障率。
---

# 企宽开通量计算

历史 Sheet1 已按月导入时，计算命令增加 `--cumulative-mode monthly_sum`，明确说明累计按两年各自1至N月相加。
它支持历史地市补录成功批次，不要求历史区县；忽略 superseded 批次。每年每个月必须齐全，来源逐月追溯。
该模式不等同于平台跨月去重汇总。默认 `exact` 模式继续执行下文的四周期规则，不自动切换口径。

定位包含 `metrics/qikuan_opening/qikuan_opening_metrics.py` 的项目根目录，优先当前项目或用户指定部署目录。
明确报告月份 YYYY-MM；上下文不能确定年月时询问，不从附件文件名的下载日期推断。
复用项目现有 Python 3.10+ 环境；Windows 可使用 python 或 py -3。

在项目根目录执行：

```bash
python3 metrics/qikuan_opening/qikuan_opening_metrics.py --month 2026-07 --mode both
```

例中月份替换为用户月份。默认 both 输出 JSON 并入库；只要结果文件时用 file，仅入库用 database。
三种模式的输入都来自 MySQL，不将 file 理解为从 Excel 读取。需要自定义 JSON 路径时传 --output。

源数据为四个完整自然周期：本年当月、去年同月、本年1月至当月、去年1月至同月。
每周期选择最新完整成功采集批次，1月复用相同周期；累计不通过相加月度去重数计算。
缺少周期时读取程序返回的 missing_periods 并报告清单，不当作零，不生成部分结果。
仅当用户任务包含补取数据时，调用 `collector/youshu/fetch_install_completed.py` 补齐明确缺失周期；
已有相应取数技能时可遵循它，未安装时查阅项目 `collector/youshu/INSTALL_COMPLETED.md`。
仅要求计算时不自行联网取数。原始 Excel 须通过双文件离线导入链路入库后计算。

计算口径：本指标以有数装机报结工单量作为企宽开通量，日期字段为 OPERTIME。
同比=(本期-去年同期)/去年同期，累计同比=(本年累计-去年同期累计)/去年同期累计。
全省使用数量合计计算增长率，不平均地市比率。比率内部是小数，展示百分比保留两位。
同期为0时结果为空并说明“同期基数为0”，不显示为0%或无穷；增长率为0时说明持平。

成功后核对退出码、报告月份、84条结果（12个地域×6指标，加近12个月全省趋势）、来源周期和批次ID。
报告全省当月量、同比、累计量、累计同比，给出结果文件路径及计算批次ID。
JSON的charts、narratives和trend供后续PPT渲染使用，不宣称已生成PPT。trend按报告月向前取12个连续完整自然月，保存月度全省量、合计和月均；需要地市比较时读取cities，不跨历史计算批次求和。
file模式仅写文件，不能宣称结果已入库；数据库故障与数据缺失分开报告。
技术细节按需查阅项目 `metrics/qikuan_opening/qikuan_opening_metrics.README.md`。
