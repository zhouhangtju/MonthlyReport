# 企宽开通量同比计算

## 历史月度补录数据

计算读取器已支持历史地市单文件批次及线上双文件批次，忽略被替换的 superseded 批次。
Sheet1 按月导入后使用：

```bash
python metrics/qikuan_opening/qikuan_opening_metrics.py --month 2026-09 --mode both --cumulative-mode monthly_sum
```

monthly_sum 模式读取两年各自1至N月的有效地市快照并按月相加；缺少任何月份均报错，不补零。
这是历史月报的按月累计口径，不等同于平台跨月去重汇总。来源逐月记录于 sources.source_batches，
不向源表创建虚构的累计采集批次。两个年度始终采用相同累计模式。
默认 exact 模式仍按下文要求读取四个精确周期；不自动在两种口径间回退。

输入为 MySQL 中 `youshu_install_completed_city` 的完整成功采集快照；平台装机报结量按本指标口径作为企宽开通量。
不读取原始 Excel，不自动联网取数，不使用派单时间口径的 `youshu_install`。

```bash
python3 metrics/qikuan_opening/qikuan_opening_metrics.py --month 2026-07 --mode both
```

月份必须为 YYYY-MM。程序读取本年当月、去年同月、本年1月至当月、去年1月至同月四个精确周期的最新成功批次；
1月复用相同周期。缺失时列出全部缺失周期并退出（退出码2），不产生部分指标，不将缺失视为零。
数据库连接异常会原样报错，不伪装为缺少数据。先运行取数入口补齐周期，再重新计算。

全省与11个地市各输出六项指标，共72条结果：current_month、previous_month、current_ytd、previous_ytd、yoy、ytd_yoy。
同比为 `(本期-同期)/同期`，累计同比为 `(本年累计-去年累计)/去年累计`。
全省按地区数量合计后计算，不平均地区增长率。累计直接读取完整周期去重汇总，不累加各月去重数。
零基数的增长率为 null，展示“—（同期基数为0）”；零增长显示持平。内部比率不乘100，展示为两位小数百分比。

`--mode file` 仍从 MySQL 读取，只输出 JSON、不建结果表和写结果；`database` 只写计算结果；默认 `both` 两者都做。
默认文件位置：`data/results/qikuan_opening/<月份>/<计算批次>.json`，可用 `--output` 指定路径。
JSON 包含 province、cities、results、charts、narratives 和四周期 sources；图表字段可供后续 PPT 渲染接入。
本模块不生成 PPT，也不改变现有 PPT 模板。

数据库结果存入 `result_qikuan_opening`，使用项目标准长表结构；数量指标的 denominator 为 null，
增长率指标的 numerator 为数量差、denominator 为同期数量、metric_value 为小数比率。
`metric_run.source_runs` 对本模块保存按四个角色组织的周期和 collection_run_id 映射（不是工单 ETL ID 列表）。
来源是不可变的成功批次，因此可追溯计算使用的具体快照。
每次计算产生独立计算批次，不覆盖源数据；查询历史结果应筛选所需成功 metric_run_id，不跨批次累计。

已有数据库必须具有 metric_run 和取数模块的源表。数据库模式自动创建缺失结果表，
或手动执行 `sql/create_result_qikuan_opening.sql`。完整 schema.sql 已同步。
结果写入与成功标记同事务提交，失败回滚结果并记录失败批次。
both 模式先提交数据库，再输出 JSON；文件写出失败时数据库成功批次仍保留，应检查该批次再重试文件输出。

验证命令：`python3 -m unittest tests.test_qikuan_opening_metrics -v`。
截图数量用于公式测试：85139 对 75103 为13.36%，538968 对461737为16.73%。
测试使用模拟源快照和隔离SQL事务替身，不代表生产MySQL联调。
