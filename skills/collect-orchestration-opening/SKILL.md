---
name: collect-orchestration-opening
description: 从编排系统获取“专线开通情况”并保存为原始 Excel、写入 SQLite 或双存储。用户提到编排专线开通情况、专线开通工单、按订单结束时间取数、ods_orch_opening，或准备专线开通类指标数据时使用。
---

# 编排：专线开通情况取数

只调用项目已有脚本，不另写接口、日期切片或入库逻辑。不要计算指标。

## 数据口径

- 数据集：`orch_opening`
- 业务表：`ods_orch_opening`
- 源记录主键：`订单号`
- 日期口径：订单结束时间；接口参数为 `finish_start_time`、`finish_end_time`
- 文件目录：`data/raw/orchestration/orch_opening/`
- 入口：`collector/orchestration/fetch_opening.py`

## 执行

1. 在包含入口脚本的项目根目录执行。
2. 将“8月”“上个月”等换算成明确的 `YYYY-MM-DD` 起止日期；不确定年份时先询问。
3. 未指定存储模式时用 `both`；只要文件用 `file`，只入库用 `database`。
4. 未指定数据库时用 `data/quality_assessment.db`，用户指定测试库时原样使用。
5. 默认不加 `--refresh`，只有用户明确要求强制重取或覆盖异常文件时才加。

```bash
python3 collector/orchestration/fetch_opening.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

默认每 3 天一批。接口压力大或空响应时，可改用 `--chunk-days 1 --interval 5 --timeout 300`。认证使用命令行 `--zytoken`/`--cookie` 或环境变量 `GDDL_ZYTOKEN`/`GDDL_COOKIE`，不得读取、记录或回显凭据内容。

## 验证

- 命令退出成功，每个日期分段都完整。
- 文件模式下路径存在，文件不是 `.part` 且确认为 Excel。
- 数据库模式下每段有 `etl.run_id`，并确认 `failed=0`。
- `skipped=true` 时合理的 `skip_reason` 是 `database_already_covered`，这表示数据库已覆盖。
- 整月读取量为 0 或接口返回空内容时，检查认证、内网和日期，不要把错误页面当 Excel。

数据库按 `订单号` 幂等：相同内容不重复，内容变化则更新当前版本并保留历史版本。

## 限制

- 不修改固定筛选参数或日期字段，不把产品实例编号当主键。
- 不删除原始文件，不在用户未授权时使用 `--refresh`。
- 需要更多故障说明时读取 `collector/orchestration/README.md`。
