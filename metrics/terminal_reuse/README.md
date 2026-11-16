# 当月终端利旧指标

只从数据库两张中间结果表计算，不使用人工工作簿或PPT截图作输入。

```powershell
python metrics/terminal_reuse/terminal_reuse_metrics.py --month 2026-09 --inventory-run inventory_reuse_c5f7466836c748a7a7a9de43ff9b670b --inventory-data-month 2026-09 --source-note "用户确认该批次原始库存为9月数据；11月是模拟入库时标签"
python reporting/build_internet_line_ppt.py --month 2026-09 --section 终端回收情况 --keep-json
```

装机批次自动选择报告月最新成功且仍有中间数据的批次。库存须显式指定批次，默认使用登记月份；与登记月份不同的原始数据月份须以参数及说明明确确认，不改写原始批次。

利旧数=返修有SN+回收有SN；出库数=新物资有SN+利旧数；库存=sheet1数量减sheet2不可利旧型号数量。总体库存沿用既有汇总的全物料范围（包含未分类），ONU分别按型号匹配、物料分类筛选。三类业务图按业务类别分组，ONU总体包含所有业务。利用率=当月利旧/月底可利旧库存，允许大于100%；零分母为null，排名置后，不标为0。地市按比例降序、同率按名称排序；靠后名单按ONU全部业务耗用占比升序。

登记 metric_run；分子分母和比率保存至 result_terminal_reuse，完整结果、规则和来源保存至 terminal_reuse_result_audit。结果写入同一事务。生成阶段仅读成功结果，不重新计算或读取人工文件。结果表不存在/当月缺结果时显示缺失提示。

新页位于完整月报第29页，终端回收两页之后，业务支撑之前；终端回收章节输出保留封面、目录及三张内容页。旧累计页面暂缓，不在本流程内补历史值。人工截图ONU利用率34.30%修正为27.30%，台州MPLS利旧数169修正为165，靠后三地市按计算结果生成。


## 累计终端利旧页（正式接入）

先准备当月装机利旧中间结果和终端回收成功批次，再运行：

```bash
python metrics/terminal_reuse/recalculate_cumulative.py --month 2026-09
python reporting/build_internet_line_ppt.py --month 2026-09 --section 终端回收情况 --output outputs/9月终端回收情况.pptx --keep-json
```

累计脚本读取 intermediate_terminal_reuse_history 的装机利旧数、拆回终端数；当月装机从 installation 中间表sheet5取得，当月拆回复用已确认的terminal_recovery结果。自动选择当月最新成功批次，按月份和层级幂等追加历史，不重新导入人工核验文件。期初库存默认data/24年5月库存数量.xls，可用--opening-stock指定；库存数减拆回设备数加利旧设备总数还原2024年5月基数，地市64050、区县59999。

利旧=返修有SN+回收有SN；耗用=累计利旧/累计装机数量；利用率=累计利旧/(累计拆回+还原期初库存)。地市按耗用降序，区县两类后10名按比率升序。三类标签沿用原回收匹配结果，不重新剔除。已确认的9月拆回18288，不强行覆盖人工18280。松阳2024-07、景宁2025-03历史空白已按用户确认修订0；兰溪2024-06回收15、新109，保留总124。

结果写入metric_run、result_terminal_reuse和terminal_reuse_cumulative_audit；绘图从成功审计结果读取。累计页为全量月报29页，原三页设备利旧顺延30—32页，支撑页顺延34—35页。终端章节输出含封面目录共8页；章节多选仍有效。没有使用--cumulative-slide外部PPT合并参数。

部署须同时迁移历史中间表及其修订记录和期初库存文件；仅复制代码不能补齐历史数据。历史仅到8月时可计算9月，此后按月依次生成，不应跳过历史月份。
