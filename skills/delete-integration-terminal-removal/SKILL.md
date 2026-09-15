---
name: delete-integration-terminal-removal
description: 清理数据库中专线拆机工单及关联明细，保留指标结果和本地文件。用户明确要求清理 integration_removal_order 时使用；不在取数、算数或月报流程中自动调用。
---

# 一体化：终端回收专线拆机数据清理

只负责专线拆机工单清理，不取数、不计算指标、不绘制 PPT。对应取数技能为 `collect-integration-terminal-removal`，只调用已有清理入口，不另写 SQL 删除。

## 数据口径

- 数据集：`integration_removal_order`
- 源记录主键：工单号；按已有记录与批次关系定位，不按主键重新计算业务口径。
- 日期口径：专线拆机实际成功入库周期。
- 关联清理范围：原始记录、版本、终端源快照及快照行数据、对应算数明细，仅删除选中批次和脚本已验证的关联记录，不清空共享表。
- 入口：`delete/integration_terminal_removal.py`，使用模块方式 `python -m delete.integration_terminal_removal` 运行。
- 保留指标结果、月度汇总、取数及算数运行记录和全部本地原始文件。

## 执行

在包含 `pyproject.toml` 的项目根目录运行，使用 Python 3.10+。日期与数据库沿用对应取数任务：

- 优先原样复用本次 collect 实际使用的 `--database`、`--start-date`、`--end-date`；明确指定的测试库或自定义日期同样沿用，不切换到其他库。未指定数据库时，与 collect 一样使用项目根目录下的 `data/quality_assessment.db`，执行前解析并展示绝对路径。
- 与对应 collect 一致：同月起止日期，月报使用完整自然月。
- 用户显式指定日期优先；没有实际采集记录时，仅按对应 collect 规则拟定预览范围，并与 ETL 记录核对。缺少月报日期时询问，不使用系统日期猜测。下面是月报日期为 2026-08-31 的示例，不是固定默认值。
- 收集本次全部 ETL run_id，必要时重复传入 `--run-id` 限定。相同日期可能包含多次历史采集，预览须核对批次清单；不得为通过检查自动扩大范围。
- collect 的 `--mode`、`--output-dir`、`--chunk-days`、`--two-phase`、认证、分页与超时参数不传给 delete。delete 只操作数据库；本次 collect 若为 `file` 且未另行入库，不得清理同周期历史数据。保留删除专用的 `--apply`、`--run-id` 和 `--log-dir`。


先预览，以下命令不会删除数据：

```powershell
py -3.11 -m delete.integration_terminal_removal --database D:/MonthlyReport/data/quality_assessment.db --start-date 2026-08-01 --end-date 2026-08-31
```

核对数据库绝对路径、批次和预计数量，确认后续步骤不再需要明细。只有用户明确授权实际删除且 `blockers` 为空，才用同一命令添加 `--apply`。不要擅自复制或替换数据库。

## 参数与运行行为

- `--database`、`--start-date`、`--end-date` 必填；日期为闭区间，数据库必须存在。
- 默认只预览；`--apply` 才实际执行，`--run-id` 可重复指定，`--log-dir` 默认是数据库同级的 `cleanup_logs`。
- 根据 ETL 周期选批次，不逐行按业务日期筛选；与范围重叠但越界的批次会阻断，不自动扩大范围。
- 原始文件或已有归档必须存在且 SHA256 一致；相关指标必须完成并匹配源批次。跨批次共享历史或运行中任务会阻断。
- 实际删除在事务中执行，失败回滚；成功提交后不能靠事务撤销。不自动备份，不复制源文件，不执行 VACUUM。

## 验证

- 预览检查 `database`、`period_start`、`period_end`、`run_ids`、`counts`、`blockers`，不能只看命令是否正常结束。
- 实际执行检查 `applied`、各表数量和日志路径。退出码 0 表示正常返回，2 表示有阻断，1 表示执行错误；`applied=false` 不能当作已删除。
- 确认指标结果与本地文件保留。清理日志不是备份，数据库文件大小没有立即缩小不等于未删除。

## 故障处理

- 文件缺失或校验不符：停止并报告具体批次，不自动下载、复制或绕过检查。
- 指标缺失、批次不匹配、共享历史或范围越界：报告阻断，等待确认，不自动补跑计算或扩大删除范围。
- 数据库占用或事务失败：停止，报告脱敏错误；若日志停留在 prepared，核对清理记录后再判断是否提交，不盲目重试。
- 清理后需要重算：先完整重新入库；重新采集时显式使用原 collector 的 `--refresh`，不要直接从缺失明细的数据库重算。

## 限制

- 不接入主流程，不改变取数和算数口径，不输出账号、密码或 Token。
- 不删除本地源文件、结果文件或指标汇总，不自动备份或压缩数据库。
- 编排开通继续使用 `prepare-orchestration-opening-monthly` 的旧机制，本入口不代替它。
- 详细删除规则及边界见项目 `delete/README.md`。
