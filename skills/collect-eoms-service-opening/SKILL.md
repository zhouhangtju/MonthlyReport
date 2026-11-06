---
name: collect-eoms-service-opening
description: 为旧终端耗用与利旧采集EOMS服务类已完成开通工单，复用拆除采集流程但独立存储；不用于终端回收拆除或投诉工单。
---
# EOMS服务类开通取数
在项目根目录运行：
python collector/eoms/fetch_service_opening.py --start-date 2026-10-01 --end-date 2026-10-31 --mode both

起止日期必须同月。操作类型开通，状态COMPLETED，deleted=0，不限定服务类型。
完成时间按参数，创建时间固定从2026-02-26到end-date，继承拆除脚本现有口径。
自动登录、异步导出全量结果，非仅当前页。凭据沿用既有登录配置，不复制到skill。
数据集eoms_service_opening_order，主键工单号；保存对应ETL及原始快照。
默认目录data/raw/eoms/eoms_service_opening_order，文件名服务类产品支撑开通工单_YYYY-MM.xlsx。
file只下载；database临时下载并入库；both保留文件并入库。
--refresh重新采集；--reuse-existing从指定目录复用已有文件，需确认文件确为开通工单。
核对failed=0、数据集、操作类型、状态、日期和快照ID。保持拆除入口原行为不变。
现有全库初始化若因其他旧表字段不匹配报错，应先处理兼容问题，不删除旧表强行运行。
