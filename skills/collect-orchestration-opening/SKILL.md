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
2. 将日期转换为明确的 `YYYY-MM-DD`：用户未显式指定日期时，`end-date` 默认取当前对话中的月报时间，`start-date` 取该月报时间向前推 12 个月的同一日期，即默认获取最近一年的数据；用户显式指定起止日期时，以用户输入为准；当前对话没有可确定的月报时间时先询问，不得擅自使用系统当前日期代替。
3. 未指定存储模式时用 `both`；只要文件用 `file`，只入库用 `database`。
4. 未指定数据库时用 `data/quality_assessment.db`，用户指定测试库时原样使用。
5. 默认不加 `--refresh`，只有用户明确要求强制重取或覆盖异常文件时才加。

```bash
# 对话中的月报时间为 2026-08-31
python3 collector/orchestration/fetch_opening.py \
  --database data/quality_assessment.db \
  --start-date 2025-08-31 \
  --end-date 2026-08-31 \
  --mode both
```

### 环境与认证

- 需要 Python 3.10 或更高版本、`requests`、`openpyxl`，并且当前网络能够访问编排系统内网。缺少依赖时在项目根目录运行 `python3 -m pip install -r requirements.txt`；项目已有虚拟环境时优先激活后再运行。
- 认证优先级依次为命令行 `--zytoken`/`--cookie`、环境变量 `GDDL_ZYTOKEN`/`GDDL_COOKIE`、不带认证直接请求。优先使用环境变量，不把 Token 或 Cookie 写入 Skill、代码、Git 或日志，也不得读取、记录或回显凭据内容。
- 接口未返回 Excel 时，先判断认证是否失效、是否连接内网、接口权限是否正常，再缩短日期范围重试；不得把登录页、错误 JSON 或其他错误响应改名为 Excel。

### 参数与运行行为

- `--start-date` 和 `--end-date` 都是闭区间，结束日期包含当天；开始日期不得晚于结束日期。
- 默认参数为 `--mode both --chunk-days 3 --interval 2 --timeout 180`。例如 `2026-08-01` 至 `2026-08-08` 会拆为 `01～03`、`04～06`、`07～08`，各批次连续且不重叠。
- `both` 同时保留原始 Excel 并入库；`file` 只保留文件；`database` 先下载到临时目录，成功入库后清理临时文件。
- 未指定 `--output-dir` 时，文件保存到 `data/raw/orchestration/orch_opening/`。文件名包含该分段的起止日期。
- 接口压力大、空响应或超时时，将参数改为 `--chunk-days 1 --interval 5 --timeout 300` 后重试。

### 重复运行与刷新

- 目标文件已存在时默认不重新下载：`file` 保留现有文件，`both` 会继续将现有文件幂等入库。
- 数据库已有成功批次、已有日期并集完整覆盖本次周期且 `failed=0` 时，不再请求接口，结果应为 `skipped=true`、`skip_reason=database_already_covered`。多个历史批次可以共同组成完整覆盖。
- 数据库只覆盖部分日期时，脚本仍处理未覆盖日期所在的分段；因 3 天为默认最小下载批次，可能重新包含少量已覆盖日期，入库时会自动去重。
- `--refresh` 会忽略已有周期和文件并强制重新拉取，只在用户明确要求重取或确认现有文件异常时使用。

## 验证

- 命令退出成功，终端返回 JSON，且请求周期内每个日期分段都有结果。
- `downloaded=true` 表示本次重新下载；`downloaded=false` 表示复用已有文件。`database` 模式的 `file` 为 `null`，`file` 模式的 `etl` 为 `null`，都属于正常结果。
- 文件模式下每个返回路径都存在，文件不是 `.part`，内容非空且确认为 Excel。脚本只在下载完成后将 `.part` 替换为正式 `.xlsx`，失败时不应遗留 `.part`。
- 数据库模式下每个实际处理分段都有 `etl.run_id`，并核对 `read`、`inserted`、`updated`、`unchanged`、`failed`；`failed` 必须为 0。
- `skipped=true` 时，确认 `skip_reason=database_already_covered`。
- 整个请求周期 `read=0` 或返回空内容时，检查日期、认证、内网和接口权限，不把空结果直接当作成功。

数据库按 `订单号` 幂等：相同内容不重复，内容变化则更新当前版本并保留历史版本。

## 故障处理

- 日期错误：改为 `YYYY-MM-DD`，并确认开始日期不晚于结束日期。
- 请求超时：使用 `--chunk-days 1 --timeout 300`，必要时增加 `--interval 5`。
- 接口未返回 Excel：更新 Token 或 Cookie，确认内网和权限正常，再用较短日期范围重试。
- 文件或数据库已有数据但用户明确要求重新获取：增加 `--refresh`。
- 缺少 Python 包：在项目根目录安装 `requirements.txt` 后重试。

## 限制

- 不修改接口固定筛选参数、接口地址或日期字段；接口的 `limit=10` 是沿用的导出请求参数，不代表只导出 10 条数据。
- 不把产品实例编号当主键，不绕过 Excel 响应校验，不另写日期切片或入库逻辑。
- 不删除原始文件，不在用户未授权时使用 `--refresh`。
