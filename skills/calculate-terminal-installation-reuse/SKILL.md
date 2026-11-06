---
name: calculate-terminal-installation-reuse
description: 计算各业务旧终端耗用与利旧中的装机出库中间结果，合并一体化及EMOS开通清单、匹配物料、按地市区县汇总有SN数量，并输出Excel和MySQL批次。库存六表计算使用另一个库存利旧流程。
---

使用项目现有脚本 `metrics/terminal_installation_reuse/terminal_installation_reuse.py`，在项目根目录执行 `python metrics/terminal_installation_reuse/terminal_installation_reuse.py --month YYYY-MM --mode both`。

- 默认读取五类同月份数据库快照；需要文件覆盖时使用 `--opening`、`--eoms`、`--outbound`、`--material-names`、`--material-baseline`。缺失来源先补采集或取得对应文件，不借用其他月份。
- 出库按所属月份选批次，保留该批次跨月确认记录；三项数量必须是有SN字段。
- 型号匹配返回物料名称表的划分类型，分类来自全省物资基准库。不要改用不可利旧型号表。
- 工单冲突由脚本报错，查清来源后再运行；不得任意保留一条。未匹配工单仍保留在匹配sheet并参与统计，业务类别为空。
- 验证四张sheet行数，以及匹配明细、地市汇总、区县汇总三项数量各自相等。报告批次ID、结果文件、未匹配物料/工单数。
- 只做本中间结果，不自动推导装机利旧率或改写库存结果。完整字段、入库语义及命令参见 `metrics/terminal_installation_reuse/README.md`。
