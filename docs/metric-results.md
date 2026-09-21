# 指标结果存储与升级

## 表与职责

| metric_run.metric_code | 结果表 |
|---|---|
| terminal_recovery | result_terminal_recovery |
| dedicated_line_opening_withdrawal_rate | result_opening_withdrawal |
| dedicated_line_install_fault_rate | result_dedicated_line_install_fault |
| qikuan_install_fault_rate | result_qikuan_install_fault |
| commercial_customer_install_fault_rate | result_commercial_install_fault |
| dedicated_line_repeat_complaint_rate | result_dedicated_line_repeat_complaint |
| qianliyan_repeat_complaint_rate | result_qianliyan_repeat_complaint |
| orchestration_opening_metrics | result_orchestration_opening |

metric_run 保存任务周期、版本、状态和来源。结果表通过 metric_run_id 关联，不重复维护任务周期。
每次重算创建新任务，历史结果保留。result_id 只在各自结果表内唯一；追溯时必须同时保留模块和任务编号。
ads_metric_detail 继续保存已有的计算明细，编排月度汇总/质量表继续供历史趋势使用。

## 查询列

各表均含 result_id、metric_run_id、metric_code、dimension_type、numerator、denominator、metric_value。
维度额外暴露为以下可直接查询的列：

- 比率模块：scope、city、business_type（不适用的列为空）。
- 编排：month、comparison_month、end_month、city、product、stage、source_field、automatic_value。
- 终端回收：sheet_name、summary_type、row_index、column_index、label_column、row_label、column_label。

终端回收维度保留原汇总表语义：city_summary 的 row_label 是地市；business/city 交叉表的 row_label 是设备类型，column_label 是业务/地市或总计。不要把所有行都当成地市回收率。

dimension_value 保留完整、规范化 JSON，保证原 PPT 接口与汇总顺序不丢失；上述查询列是 STORED 生成列，由 JSON 自动生成，禁止手动双写。修改维度应更新 dimension_value。未映射的维度在保存/迁移时会报错，不会丢弃。
唯一约束为任务、具体指标、维度类型、规范化维度摘要。空分母、零分母、空指标值沿用原计算结果，不在存储层改写。

## 部署已有数据库

1. 暂停旧版算数/报表进程，备份结果数据，部署全部代码与 schema.sql。
2. 在项目根目录初始化新表：`python storage/init_database.py`。
3. 预览历史结果数量：`python storage/migrate_metric_results.py`。
4. 执行并核对迁移：`python storage/migrate_metric_results.py --apply`。
5. 重跑报表，核对周期、选中任务、数值和明细；再恢复新代码任务。

迁移按任务提交，保留任务编号和所有旧结果；可重跑，已存在且一致的行跳过，冲突或未知维度会回滚当前任务并报错。前面已完成的任务保留。迁移期间不要运行旧版写入程序。
旧 ads_metric_result 不再由初始化创建，新计算不会写入它；已有旧表不会被自动删除。未迁移的旧任务被读取时会报迁移提示，避免误当成无结果。确认归档和所有下游切换后，可由数据库管理员另行删除旧表。

## 查询一个周期最新成功结果

以下示例整批选择企宽新装报障率，避免混合不同任务的地市记录：

```sql
SELECT r.*, m.period_start, m.period_end
FROM result_qikuan_install_fault r
JOIN metric_run m ON m.metric_run_id=r.metric_run_id
WHERE r.metric_run_id=(
    SELECT metric_run_id FROM metric_run
    WHERE metric_code='qikuan_install_fault_rate' AND status='success'
      AND period_start='2026-06-01' AND period_end='2026-08-31'
    ORDER BY started_at DESC, metric_run_id DESC LIMIT 1
);
```

商客沿用完整周期匹配，保存实际使用的两个上游任务编号。PPT 沿用现有周期选择规则（支撑指标匹配报告月结束的三个月周期），读取层将模块结果转换为原 JSON 接口，版式和图表代码无需修改。数据迁移后的 result_id 可能改变，业务维度和数值应保持一致。

## 本次修改文件

实现与表结构：

- storage/metric_results.py（新增）
- storage/migrate_metric_results.py（新增）
- sql/schema.sql
- metrics/installation/common.py
- metrics/installation/commercial_customer_install_fault_rate.py
- metrics/opening/withdrawal.py
- metrics/opening/dedicated_line_metrics.py
- reporting/database_results.py

测试：

- tests/test_metric_result_modules.py（新增）
- tests/test_dedicated_line_metrics.py

文档：

- README.md
- docs/metric-results.md（新增）
- metrics/terminal_recovery/README.md
- metrics/opening/withdrawal.README.md
- metrics/opening/dedicated_line_metrics.README.md
- metrics/installation/dedicated_line_install_fault_rate.README.md
- metrics/installation/qikuan_install_fault_rate.README.md
- metrics/installation/commercial_customer_install_fault_rate.README.md
- metrics/complaint/dedicated_line_repeat_complaint_rate.README.md
- metrics/complaint/qianliyan_repeat_complaint_rate.README.md
- skills/calculate-commercial-customer-install-fault-rate/SKILL.md
- skills/calculate-dedicated-line-repeat-complaint-rate/SKILL.md
- skills/calculate-qianliyan-repeat-complaint-rate/SKILL.md
- skills/calculate-orchestration-opening-metrics/SKILL.md
- skills/calculate-opening-withdrawal-rate/SKILL.md
- skills/calculate-qikuan-install-fault-rate/SKILL.md
- skills/calculate-terminal-recovery/SKILL.md
- skills/generate-monthly-report-ppt/SKILL.md
