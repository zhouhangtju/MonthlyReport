---
name: collect-integration-terminal-inventory
description: 月底手动采集一体化终端库存统计表，按地市、区县、仓库、项目和物资批次分组，下载平台Excel并将完整接口明细入库。
---
# 终端库存取数
项目根目录运行：
python collector/integration/fetch_terminal_inventory.py --month 2026-11 --mode both

用户在月底最后一个工作日手动执行。month默认北京时间当前月。
复用一体化登录，不从附件复制Cookie。
count-all分页取全部明细，count-all/export下载同筛选平台Excel。
分类固定终端，groupFields包含a.batch_no。物资批次batchNo与采集批次分别保留。
file只保存文件；database保存原始表及两份工作簿快照；both同时保留文件与数据库。
每次执行生成新采集快照，原始行由公共导入器按哈希复用，不能跨快照相加库存。
检查record_count、导入失败数、snapshot_id及平台导出。缺页、重复页或总数变化时停止。
本技能不计算利旧率，不改变终端回收算法。
