---
name: collect-orchestration-install
description: 从编排系统获取“互联网专线新装单”并保存为原始 Excel、写入 SQLite 或双存储。用户提到编排互联网专线新装单、按派单时间取数、ods_orch_install，或准备互联网专线新装保障率分母时使用。
---

# 编排：互联网专线新装单取数

只调用项目已有脚本，不计算指标，也不复制接口实现。

## 数据口径

- 数据集：`orch_install`
- 业务表：`ods_orch_install`
- 源记录主键：`订单号`
- 日期口径：派单时间；接口参数为 `start_time`、`end_time`
- 文件目录：`data/raw/orchestration/orch_install/`
- 入口：`collector/orchestration/fetch_install.py`

不要与专线开通情况混淆：本表按派单时间取数，专线开通情况按订单结束时间取数。

## 执行

在项目根目录把自然语言周期换算为明确起止日期。未指定存储模式时用 `both`，未指定数据库时用 `data/quality_assessment.db`。

```bash
python3 collector/orchestration/fetch_install.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

默认 `--chunk-days 3 --interval 2 --timeout 180`。只在用户明确要求重新获取时增加 `--refresh`。认证使用 `--zytoken`/`--cookie` 或环境变量 `GDDL_ZYTOKEN`/`GDDL_COOKIE`，不得回显凭据。

## 验证

- 所有日期分段均成功，文件路径存在且文件为有效 Excel。
- 数据库模式下每段有 `etl.run_id` 且 `failed=0`。
- `database_already_covered` 表示已有完整覆盖，可正常跳过。
- 检查派单时间口径；不要因为受理时间、状态时间落在其他月份就自行删除记录。

入库按 `订单号` 幂等，`--refresh` 不会把完全相同的记录存两次。

## 限制

- 不修改固定筛选条件，不擅自改成结束时间口径。
- 不覆盖人工核验文件，除非用户明确要求刷新。
- 详细排障见 `collector/orchestration/README.md`。
