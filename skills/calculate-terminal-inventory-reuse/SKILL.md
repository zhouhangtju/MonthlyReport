---
name: calculate-terminal-inventory-reuse
description: 从库存快照及物料分类、不可利旧型号对照表生成六个库存利旧中间工作表，按物料分类与地市汇总，并保存MySQL中间结果。不计算装机利旧率。
---
# 库存利旧中间结果
从项目根目录调用 metrics/terminal_inventory_reuse/terminal_inventory_reuse.py。
必须明确--month、--material-names和--model-map；默认从MySQL读取该月最新integration_terminal_inventory_export平台工作簿快照，--input可指定原始库存Excel。
示例：
python metrics/terminal_inventory_reuse/terminal_inventory_reuse.py --month 2026-11 --material-names "物料名称表.xlsx" --model-map "可利旧与不可利旧设备型号对照表.xlsx" --mode both

输出固定六个sheet：物料仓库库存统计、物料名称表、可利旧与不可利旧设备型号对照表、不可利旧设备清单、sheet1、sheet2。
按原值精确匹配，不模糊匹配；未匹配留空。物料同名异类应停止核对，不擅自取第一条。型号对照只使用不可利旧设备型号列，空型号不匹配。
可利旧数量=返修物资-正常SN+回收物资-正常SN。命中不可利旧型号仍保留此数量；sheet2是该子集汇总，不把它误称为真正可复用设备。
两张汇总均按物料分类+地市分组，空分类保留。空数量按0，非法或负数报错。
file生成Excel和审计JSON；database仅存库；both同时输出。每次运算新建metric_run，历史批次不删除。按metric_run_id查询，不能跨批次累计。
MySQL intermediate_terminal_inventory_reuse保存全部六张表的行，row_data保留原列；terminal_inventory_reuse_audit保存表头、来源哈希与审计；计算写入一个事务。
验收检查明细及不可利旧子集数量分别等于sheet1及sheet2总数，重新打开Excel核对工作表行数，并核对对应数据库批次。
