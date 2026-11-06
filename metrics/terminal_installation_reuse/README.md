# 装机出库利旧中间结果

在项目根目录运行：

```powershell
python metrics/terminal_installation_reuse/terminal_installation_reuse.py --month 2026-09 --mode both
```

`file` 仅输出 Excel 和审计 JSON；`database` 仅入库；`both` 同时执行。
可通过 `--opening`、`--eoms`、`--outbound`、`--material-names`、`--material-baseline` 指定 Excel 文件（支持真正的 XLS 和 XLSX）。未指定时，严格读取所属月份最新数据库快照，缺失即报错，不回退到其他月份或原始表最新状态。出库在平台原始导出快照和标准采集快照之间按时间选择最新批次；不截断跨月确认时间。

输出固定四个 sheet：开通清单、物料确认退库明细、匹配、sheet5。开通清单排除两类行业视频，追加安全终端部署服务/E企组网，再按七类业务映射。型号匹配实际是按物料名称返回划分类型；分类来自全省物资基准库。物料查询按终端回收口径取重复名称首条，三类标签的划分类型置零。只筛物料名称匹配成功行，不套用终端回收的额外业务筛选或去重。

同一工单号多个业务类别报错；相同类别的重复工单保留在开通清单，但关联索引唯一，不放大出库行数。未匹配工单的物料明细保留，业务类别为空，仍参与地区汇总。业务类别未命中映射的已知工单才归为其他专线。

sheet5 按地市和地市+区县分别求和三项有SN数量，不再按业务类别分组。两个统计层级不能相加。API字段使用 newSnNum/repairSnNum/recoverySnNum，禁止以旧简写数量替代。空数量为零，非法非空数值报出源行号。负数保留用于反向调整。Excel是计算结果快照，修改输入后需重跑脚本。

数据库独立建表脚本为 sql/create_terminal_installation_reuse.sql，计算时自动执行。四个sheet完整行数据存入 intermediate_terminal_installation_reuse，表头和来源/计数/数量审计存入 terminal_installation_reuse_audit，同时登记 metric_run（metric_code=terminal_installation_reuse）。不向原始采集数据集注册计算结果。写入批次使用单个事务；重跑保留历史批次。默认输出 outputs/terminal_installation_reuse。
