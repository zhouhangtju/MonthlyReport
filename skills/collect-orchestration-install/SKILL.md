---
name: collect-orchestration-install
description: 从编排系统获取“互联网专线新装单”并保存为原始 Excel、写入 MySQL。用户提到编排互联网专线新装单、按派单时间取数、orch_install，或准备互联网专线新装保障率分母时使用。
---

# 编排：互联网专线新装单取数

只调用项目已有脚本，不计算指标，也不复制接口实现。

## 数据口径

- 数据集：`orch_install`
- 原始表（算数直接读取）：`orch_install`
- 源记录主键：`订单号`
- 日期口径：派单时间；接口参数为 `start_time`、`end_time`
- 文件目录：`data/raw/orchestration/orch_install/`
- 入口：`collector/orchestration/fetch_install.py`

不要与专线开通情况混淆：本表按派单时间取数，专线开通情况按订单结束时间取数。

## 执行

在项目根目录把周期换算为明确的 `YYYY-MM-DD` 起止日期。日期取值规则如下：

- 用户未显式指定日期时，`end-date` 默认取当前对话中的月报时间，`start-date` 取该月报时间向前推 3 个月的同一日期，即默认获取最近 3 个月的数据。
- 用户显式指定起止日期时，以用户输入为准。
- 当前对话没有可确定的月报时间时，先询问用户，不得擅自使用系统当前日期代替。

未指定存储模式时用 `both`。`--database` 仅兼容旧命令；MySQL 连接信息写在 `storage/database.py`。例如，对话中的月报时间为 `2026-08-31` 时：

```bash
python3 collector/orchestration/fetch_install.py \
  --start-date 2026-05-31 \
  --end-date 2026-08-31 \
  --mode both
```

## 环境与认证

- 需要 Python 3.10 或更高版本、`requests`、`openpyxl`，并且当前网络能够访问编排系统内网。缺少依赖时，在项目根目录运行 `python3 -m pip install -r requirements.txt`；项目已有虚拟环境时优先激活后再运行。
- 认证优先级依次为命令行 `--zytoken`/`--cookie`、环境变量 `GDDL_ZYTOKEN`/`GDDL_COOKIE`、不带认证直接请求。优先使用环境变量，避免凭据进入终端历史。
- 不保存、读取、记录或回显 Token、Cookie，不将凭据写入 Skill、代码、Git 或日志。

本模块没有自动登录脚本，也不支持 `--login-first`。仅当接口返回登录页、认证失败或 Token/Cookie 明确失效时，强调以下重新登录方式：

1. 停止当前失败的采集，在浏览器中按单位现有登录流程重新登录编排系统。
2. 按现有合规运维方式从新登录会话更新本机的 `GDDL_ZYTOKEN` 和/或 `GDDL_COOKIE`；只在本机环境变量中设置，不让用户把实际值发到对话中。
3. 先用较短日期范围验证认证和内网连通性，再重新执行原三个月取数命令。
4. 若重新登录后仍返回登录页或错误响应，检查账号权限和内网，不要循环重试或把错误响应保存成 Excel。

## 参数与运行行为

- `--start-date` 和 `--end-date` 使用派单时间闭区间，结束日期包含当天；格式必须为 `YYYY-MM-DD`，开始日期不得晚于结束日期。
- 默认参数为 `--mode both --chunk-days 3 --interval 2 --timeout 180`。每 3 个自然日一个批次，各批次连续且不重叠。
- `both` 同时保留原始 Excel 并入库；`file` 只保留文件；`database` 下载到临时目录，成功入库后清理临时文件。
- 未指定 `--output-dir` 时，文件保存到 `data/raw/orchestration/orch_install/`，文件名包含该分段的起止日期。
- 固定接口筛选为 `order_type=2`、`service_type=ProvInternetLine`，日期参数是 `start_time`、`end_time`。公共参数中的 `limit=10` 是导出请求参数，不代表只导出 10 条记录。
- 接口压力大、空响应或超时时，将参数改为 `--chunk-days 1 --interval 5 --timeout 300` 后重试。

## 重复运行与刷新

- 目标文件已存在时默认不重新下载：`file` 保留现有文件，`both` 会继续将现有文件幂等入库。
- 数据库已有成功批次、已有日期并集完整覆盖本次周期且 `failed=0` 时，不再请求接口，结果应为 `skipped=true`、`skip_reason=database_already_covered`。多个历史批次可以共同组成完整覆盖。
- 数据库只覆盖部分日期时，脚本仍处理未覆盖日期所在的分段；因 3 天为默认最小下载批次，可能重新包含少量已覆盖日期，入库时会自动去重。
- `--refresh`（或兼容参数 `--overwrite`）会忽略已有周期和文件并强制重新拉取，只在用户明确要求重取或确认现有文件异常时使用。

## 验证

- 命令退出成功，终端返回 JSON，且三个月周期内每个日期分段都有结果。
- `downloaded=true` 表示本次重新下载；`downloaded=false` 表示复用已有文件。`database` 模式的 `file` 为 `null`，`file` 模式的 `etl` 为 `null`，都属于正常结果。
- 文件模式下每个返回路径都存在，文件不是 `.part`，内容非空且确认为 Excel。脚本下载完成后才将 `.part` 替换为正式 `.xlsx`，失败时不应遗留 `.part`。
- 数据库模式下每个实际处理分段都有 `etl.run_id`，并核对 `read`、`inserted`、`updated`、`unchanged`、`failed`；`failed` 必须为 0。
- 跳过时确认 `skip_reason=database_already_covered`。整个周期 `read=0` 或接口返回空内容时，检查日期、认证、内网和权限，不把空结果直接当作成功。
- 检查派单时间口径；不要因为受理时间或状态时间落在其他月份就自行删除记录。

入库按 `订单号` 幂等：新订单号记为 `inserted`；整行内容相同记为 `unchanged`；内容变化记为 `updated` 并保留历史版本；订单号为空记为 `failed` 且不写入业务记录。`产品实例编号`只用于和 EOMS 投诉的计费号码关联，不是主键。

## 故障处理

- 日期错误：改为 `YYYY-MM-DD`，并确认开始日期不晚于结束日期。
- 接口返回登录页或未返回 Excel：按上面的重新登录步骤更新本机认证，确认内网和权限后，用较短日期范围重试；不得把登录页或错误 JSON 改名为 Excel。
- 请求超时：使用 `--chunk-days 1 --timeout 300`，必要时增加 `--interval 5`。
- 文件或数据库已有数据，但用户明确要求重新获取：增加 `--refresh`。
- 缺少 Python 包：在项目根目录安装 `requirements.txt` 后重试。

## 限制

- 不修改接口固定筛选参数、接口地址或日期字段，不擅自改成结束时间口径，不复制底层请求、日期切片或入库逻辑到 Skill 中。
- 不把产品实例编号当主键，不绕过 Excel 响应校验。
- 不覆盖人工核验文件、不删除原始文件，除非用户明确要求刷新。
