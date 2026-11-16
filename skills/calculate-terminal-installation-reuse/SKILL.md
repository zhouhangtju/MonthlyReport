---
name: calculate-terminal-installation-reuse
description: 计算各业务旧终端耗用与利旧中的装机出库中间结果，合并一体化及EMOS开通清单、匹配物料、按地市区县汇总有SN数量，并输出Excel和MySQL批次。库存六表计算使用另一个库存利旧流程。
---

使用项目现有脚本 `metrics/terminal_installation_reuse/terminal_installation_reuse.py`，在项目根目录执行 `python metrics/terminal_installation_reuse/terminal_installation_reuse.py --month YYYY-MM --mode both`。

- 默认读取五类同月份数据库快照；需要文件覆盖时使用 `--opening`、`--eoms`、`--outbound`、`--material-names`、`--material-baseline`。缺失来源先补采集或取得对应文件，不借用其他月份。
- 出库按所属月份选批次，保留该批次跨月确认记录；三项数量必须是有SN字段。
- 型号匹配返回物料名称表的划分类型，分类来自全省物资基准库。不要改用不可利旧型号表。
- 工单冲突由脚本报错，查清来源后再运行；不得任意保留一条。匹配sheet要求物料名称匹配与关联单据号匹配均有值；未匹配工单只保留在原始明细及审计，不参与统计。
- 验证四张sheet行数，以及匹配明细、地市汇总、区县汇总三项数量各自相等。报告批次ID、结果文件、未匹配物料/工单数。
- 只做本中间结果，不自动推导装机利旧率或改写库存结果。完整字段、入库语义及命令参见 `metrics/terminal_installation_reuse/README.md`。

区县汇总保留原始区县，新增标准区县、区县清洗依据；复用终端回收区县信息汇总.xlsx，支持 --district-mapping 覆盖。依次按本地市区县别名精确匹配、标题最长关键词匹配；不跨已知地市归属，不套用拆机专用业务剔除。中心及无法识别记录的标准区县为空，进入本地市“未匹配区县”组并审计，保留数量核对。
