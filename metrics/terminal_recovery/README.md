# 终端回收：取数、算数和结果存储

终端回收与项目其他指标使用相同的分工：collector 取数入库，metrics 从 MySQL 算数，mode 控制结果输出。

三个取数脚本各自包含命令行参数、日期校验、下载目录管理、已取数判断逻辑，不再依赖 `collector/terminal_recovery.py`。这些规则调整时需同步维护三处；入库仍调用公共 `storage/importer.py` 和 `storage/terminal_recovery.py`。metrics 使用自身的日期校验。
算数使用数据库源快照恢复的临时 Excel。正式入口为 `terminal_recovery_export_online.py`；关联单据号在筛选后的候选记录中去重，保留源表第一次出现的记录，不再应用人工指定的保留规则。

## 模式

collector：
| mode | 行为 |
| --- | --- |
| file | 只下载 Excel 到本地 |
| database | 临时下载后将源数据、源快照写入 MySQL，清理临时文件 |
| both | 本地 Excel 和 MySQL 都保留 |

metrics 的三种模式全部从 MySQL 取源：
| mode | 输出 |
| --- | --- |
| file | 完整 Excel + 两个汇总 sheet 的 JSON，不写数据库结果 |
| database | 两个汇总 sheet 的结构化指标写入 MySQL，不保留本地结果文件 |
| both | 完整 Excel + JSON + MySQL 结构化指标 |

注意：metrics 的 file 只表示输出位置，不再表示从本地 Excel 取源。
只有 collector file 的文件、没有数据库源快照时，不能直接运行 metrics；需先以 database/both 入库。

## 运行

从 `D:\MonthlyReport` 执行，先完成三个 collector，再执行 metrics：

```powershell
py -3.10 collector/integration/zhuanxian_chaiji_export.py --start-date 2026-08-01 --end-date 2026-08-31 --mode both
py -3.10 collector/eoms/eoms_export_qiwan_auto_login.py --start-date 2026-08-01 --end-date 2026-08-31 --mode both
py -3.10 collector/integration/integration_dismantle.py --start-date 2026-08-01 --end-date 2026-08-31 --mode both
py -3.10 metrics/terminal_recovery/terminal_recovery_export_online.py --start-date 2026-08-01 --end-date 2026-08-31 --mode both
```

- 同一批次使用同一数据库和同一起止日期，日期必须在同一个月。
- 终端出库、入库查询统计月月初至次月 3 日（含当天）；例如参数为 2026-08-01 至 2026-08-31 时，实际查询到 2026-09-03 23:59:59。文件名及数据库所属周期仍为 8 月，其他 collector 的查询日期不变。升级前已取过同周期数据的，需加 `--refresh` 重新下载后再算数。
- 三个 collector 默认分别下载到项目的 `data/raw/integration/integration_removal_order/`、`data/raw/eoms/eoms_service_removal_order/`、`data/raw/integration/terminal_materials/`；可通过 `--output-dir` 指定。
- database/both 已存在完整、日期完全匹配的源快照时，collector 自动跳过取数；both 还要求对应本地文件存在。
- `--refresh` 强制重新下载和入库。
- `--reuse-existing` 跳过网络，直接从下载目录导入已有文件并补建快照，不删除已有文件；它优先于强制下载，不校验文件内实际日期。
- 账号密码和原请求筛选条件保持不变。专线拆机脚本复用物资脚本的自动登录获取新 Token，并保存至项目 `collector/credentials/zhengqi_yitihua.json`，不再读取旧 OpenClaw 工作区的凭据路径。
- 物资 collector 同时导入物料名称映射表，优先使用指定下载目录的版本，否则采用模块自带版本。
- metrics 不再接受 `--input-dir` 或 `--source`，从 MySQL 源快照读取；`--database` 仅为旧命令兼容参数。
- metrics 可用 `--output-dir` 指定本地输出目录，默认项目 `outputs`。
- 原始下载、辅助 CSV、算数中间 Excel 在 database 模式下使用临时目录并自动清理。

## 源数据

通过公共 `storage/importer.py` 按 XLSX 业务列导入原始表，并保存 `tr_source_snapshot`、`tr_source_row`，以保留原行序、重复记录、类型和样式。
metrics 读取日期完全匹配的每类最新源快照，缺失时直接报错，不自动读取下载目录。
使用专线拆机、EOMS 服务类工单、终端入库、物资基准库、物料名称映射五类源数据。
终端出库仍取数入库，但不参与原汇总算法。
各源快照关联的 etl_run ID 会记录在指标计算批次中。

## 本地结果

file/both 输出两份同名不同扩展名的文件：
- `终端回收率汇总表_YYYY-MM.xlsx`：保留原全部 11 个 sheet、公式和样式，供 PPT 读取。
- `终端回收率汇总表_YYYY-MM.json`：仅转换两个目标 sheet 的数据，附日期、计算版本、源批次及标准指标列表。

JSON 结构：
```text
sheets
  按地市回收率汇总
    columns / rows
  sheet1
    business：按业务的交叉表，columns / rows
    city：按地市的交叉表，columns / rows
results：上述表格对应的标准指标记录
```

保留原表头、数据排列和总计项。JSON 的回收率是数值（如 0.99569），按 Excel 的分子、分母计算，不依赖公式缓存。
空白分隔行不作为业务记录输出。

## 数据库结果

复用项目已有的两张表：
- `metric_run`：metric_code 为 `terminal_recovery`，记录起止日期、版本、来源批次和成功/失败状态。
- `result_terminal_recovery`：仅保存两个指定 sheet 的数值和维度，metric_code 分为 `terminal_recovery_rate`、`terminal_recovery_count`。

`dimension_value` 中的 sheet、table、label、column 标明来源工作表、交叉表、行标签和列名；row_index、column_index 保留顺序。
回收率同时保存分子、分母、计算值；计数的 denominator 为 1。
sheet1 两张交叉表的总计项也保存，因此查询时需区分总计与明细，不能直接对全部结果求和。

新运行不向 `tr_report` 保存完整 Excel，也不写旧 `tr_report_sheet`、`tr_result_*`。
历史整份文件和历史分表保留，不自动删除。
源数据快照中的原始 Excel 属于输入资料，不受结果存储策略变化影响。

查询最近一次成功计算的地市回收率：
```sql
SELECT json_extract(dimension_value, '$.label') AS 地市,
       numerator AS 已拆回设备数, denominator AS 应拆回设备数,
       metric_value AS 终端回收率
FROM result_terminal_recovery
WHERE metric_code = 'terminal_recovery_rate'
  AND metric_run_id = (
    SELECT metric_run_id FROM metric_run
    WHERE metric_code = 'terminal_recovery' AND status = 'success'
      AND period_start = '2026-08-01' AND period_end = '2026-08-31'
    ORDER BY started_at DESC, metric_run_id DESC LIMIT 1
  )
ORDER BY json_extract(dimension_value, '$.row_index');
```

## 本地验证

使用已经完成源数据入库的数据库运行线上版；以下默认数据库必须包含对应月份的源快照。
```powershell
py -3.10 metrics/terminal_recovery/terminal_recovery_export_online.py --start-date 2026-08-01 --end-date 2026-08-31 --mode both --output-dir outputs/terminal_recovery_online
py -3.10 -m unittest discover -s tests -p 'test_terminal_recovery*.py' -v
```

删除复现版脚本不会删除或更新数据库中的历史结果。部署后应运行线上版生成新的结果批次，再生成 PPT；仅生成 PPT 仍会使用数据库里已有的结果。

物料名称表以“物料名称”为主键，物资基准库以“物料基准ID”为主键；出入库采用自增 id，并通过独立周期关联表记录同周期明细；全部业务列完全相同的行不重复插入，跨周期复用已有行。原工作簿快照仍保留原始重复行，终端回收算数继续使用周期快照。原始表列名与 config/raw_columns.json 的文件表头对应，去除首尾空格。
