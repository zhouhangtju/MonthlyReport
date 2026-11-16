---
name: calculate-terminal-reuse
description: 从已入库的装机出库和库存利旧中间表计算当月终端利旧页面指标、ONU三业务地市图和库存利用率，保存结果到MySQL供月报读取。不计算累计历史页面，不使用人工核验表作为输入。
---

运行项目 `metrics/terminal_reuse/terminal_reuse_metrics.py`，指定 `--month YYYY-MM --inventory-run 批次号`。默认严格要求库存所属月一致；若历史导入月份填错，只有取得原始数据月份确认后才能使用 `--inventory-data-month` 和 `--source-note`，不得猜测或改写源批次。

计算读取 `intermediate_terminal_installation_reuse` 的双重匹配明细和 `intermediate_terminal_inventory_reuse` 的sheet1/sheet2；核对结果来源批次、全省数量及11地市四图。报告结果批次和JSON文件位置。零分母不补零，利用率超过100%保留原值。

计算成功后通过现有生成技能执行 `python reporting/build_internet_line_ppt.py --month YYYY-MM --section 终端回收情况 --keep-json`。仅读取入库成功结果，新增页放在终端回收末尾。执行流程、字段与月份处理见 `metrics/terminal_reuse/README.md`。
