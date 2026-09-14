---
name: prepare-orchestration-opening-monthly
description: 采用低占用方式按月准备编排专线开通月报数据，同时保留原始 Excel 和指标 JSON，并依次完成数据库入库、月度汇总、归档和明细清理。用户明确调用本技能，或要求逐月补编排历史数据并在汇总后删除数据库明细、控制 orch_opening 数据库大小时使用；普通取数或不希望删除明细时不要使用。
---

# 按月准备编排开通数据

在项目根目录完成“单月取数 → 单月汇总 → 验证 → 归档清理”。每个月汇总成功后只处理当月对应采集批次，不连带清理更早月份。清理默认委托 `cleanup-source-data` 技能，先预览，检查通过后自动执行，无需重复确认。若计算技能已完成同范围清理，核对记录后跳过重复执行。用户要求保留明细时禁用默认清理，使用独立取数和计算技能，不自行编写 SQL 删除。

## 确定月份

- 月报目标月必须来自用户输入或当前对话；无法确定时先询问，不使用系统月份猜测。
- 日历月取数范围为当月第一天至最后一天，首尾均包含；正确处理大小月和闰年。
- 第一次为目标月补齐历史时，通常需要目标月及同比基期，共 13 个自然月。例如 2026-08 月报依次处理 `2025-08` 至 `2026-08`：趋势使用 `2025-09` 至 `2026-08`，同比另需 `2025-08`。
- 数据库已有某月成功覆盖时，取数脚本会幂等跳过；仍应确认该月是否存在月度汇总。

## 每月固定流程

对周期中的每个月按时间升序执行；上一步失败就停止，不继续汇总或清理该月。每个月都必须完整完成以下三步后，才能处理下一个月。

### 1. 拉取单月明细

使用 `both`，同时将原始分段 Excel 保存到 `data/raw/orchestration/orch_opening/` 并写入数据库：

```bash
python3 collector/orchestration/fetch_opening.py \
  --database data/quality_assessment.db \
  --start-date 2025-08-01 \
  --end-date 2025-08-31 \
  --mode both
```

验证命令退出为 0；每个返回的 Excel 路径存在且文件有效，实际处理分段的 `etl.failed` 必须为 0。整月被标记为 `database_already_covered` 也属于正常结果，但仍需确认该月原始 Excel 已存在；缺失时停止并报告，不以数据库记录代替用户要求保留的文件。`read=0` 且不是覆盖跳过时停止排查，不生成空汇总。

### 2. 立即生成单月汇总

`start-month` 和 `end-month` 都使用当前处理月，使用 `both` 将结果同时写入数据库和月度 JSON：

```bash
python3 metrics/opening/dedicated_line_metrics.py \
  --database data/quality_assessment.db \
  --start-month 2025-08 \
  --end-month 2025-08 \
  --mode both
```

默认 JSON 保存到 `outputs/编排专线指标_YYYY-MM.json`；验证该文件存在、可解析且月份正确。

验证生成成功的 `metric_run`，并确认：

- `orch_opening_monthly_quality` 存在该月、当前 `metric_version` 的记录；
- `orch_opening_monthly_summary` 存在该月结果；
- `quality.rows_missing_order_month` 已核对；
- 当月应有业务但 `quality.snapshot_database_rows=0` 时停止，不清理。

月度汇总使用幂等更新；重复计算同月会以最新成功结果替换该月快照。后续年度趋势、同比、环比和 12 个月均值会自动组合历史月度汇总与保留期内明细。

### 3. 立即归档并清理当月明细

使用平台清理入口，起止日期为当前月，不再使用旧 `before-month` 清理入口。先读取 `metrics/cleanup/README.md`，确认没有其他取数、算数任务正在进行。

先预览：

```bash
python3 metrics/cleanup/orchestration.py \
  --database data/quality_assessment.db \
  --dataset orch_opening \
  --start-date 2025-08-01 --end-date 2025-08-31
```

预览成功后核对 `blockers` 必须为空，批次及条数符合当前月份，且无后续步骤需要该月原始明细；按默认收尾流程执行：

```bash
python3 metrics/cleanup/orchestration.py \
  --database data/quality_assessment.db \
  --dataset orch_opening \
  --start-date 2025-08-01 --end-date 2025-08-31 \
  --apply
```

脚本先验证原始文件及月度汇总，将将要删除的明细写入 gzip 归档并校验，再事务清理 ODS、raw/版本及对应审计明细，保留指标和月度汇总。确认退出为0、`applied=true`、manifest路径已记录后再处理下个月。无可删除记录时核对原因，不反复删除。保留原始Excel、月度JSON、清理归档；不默认每月执行 VACUUM。

## 生成目标月完整指标

全部月份准备完成后，为月报生成一次完整周期的指标。例如 2026-08 月报：

```bash
python3 metrics/opening/dedicated_line_metrics.py \
  --database data/quality_assessment.db \
  --start-month 2025-09 \
  --end-month 2026-08 \
  --mode both
```

历史明细已清理时，程序应从月度汇总补齐。检查日志覆盖 `[Sheet 1/18]` 至 `[Sheet 18/18]`，同比基期为 `2025-08`，并确认生成成功的目标月指标批次后，再进入月报 PPT 技能。

## 边界

- 不使用跨 13 个月的一次性取数代替逐月流程，避免数据库峰值过大。
- 不把 Shell 展开式用于跨年份月份；应准确计算每个月月末并逐月执行。
- 不因已有月度汇总而跳过用户明确要求的当月重取；强制重取仍必须由用户授权 `--refresh`。
- 某月汇总缺失、取数失败、存在失败行或归档失败时，不清理该月明细。
- 某月原始 Excel 或月度指标 JSON 未成功保存时，不清理该月数据库明细。
- 用户要求保留任意期限的数据库明细时，不执行本技能的默认清理流程；改用独立取数和计算技能，并按用户指定策略处理。
