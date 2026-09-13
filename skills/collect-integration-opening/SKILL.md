---
name: collect-integration-opening
description: 从一体化平台获取“售中开通工单”并保存为原始 Excel、写入 SQLite 或双存储。用户提到一体化售中开通工单、开通撤退单数据、integration_opening 或按工单结束时间取数时使用。
---

# 一体化：售中开通工单取数

本 Skill 只负责源工单取数；测试单剔除和撤退单率计算属于指标模块。

## 数据口径

- 数据集：`integration_opening`
- 源记录主键：`工单号`
- 日期口径：`工单结束时间`
- 文件目录：`data/raw/integration/integration_opening/`
- 入口：`collector/integration/fetch_withdrawal_orders.py`

## 执行

在项目根目录运行，将统计周期转换为明确的 `YYYY-MM-DD` 起止日期。日期取值规则如下：

- 用户未显式指定日期时，以当前对话中的月报时间所在月份为统计周期：`start-date` 取该月第一天，`end-date` 取该月最后一天，即默认获取月报当月的数据。
- 用户显式指定起止日期时，以用户给出的日期为准。
- 当前对话没有可确定的月报时间时，先询问用户，不得擅自使用系统当前日期代替。

默认模式为 `both`，默认数据库为 `data/quality_assessment.db`。例如，对话中的月报时间为 `2026-08` 或该月内任意日期时：

```bash
python3 collector/integration/fetch_withdrawal_orders.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

## 环境与认证

- 需要 Python 3.10 或更高版本，并且当前网络能够访问浙江移动 4A 和一体化平台内网。缺少依赖时，在项目根目录运行 `python3 -m pip install -r requirements.txt`；项目已有虚拟环境时优先激活后再运行。
- 已有 Token 时优先使用环境变量 `INTEGRATION_ZYTOKEN`；也可用 `--token` 临时传入，但命令行参数可能进入终端历史。
- 没有 Token 时，同时设置环境变量 `INTEGRATION_ACCOUNT` 和 `INTEGRATION_PASSWORD`。脚本会自动执行 4A 登录并换取 `zy_token`；也可用 `--account`、`--password` 临时传入。
- 不保存、读取、记录或回显 Token、账号、密码，不将凭据写入 Skill、代码、配置示例、Git 或日志。

## 参数与运行行为

- `--start-date` 和 `--end-date` 使用工单结束时间闭区间，结束日期包含当天；格式必须为 `YYYY-MM-DD`，开始日期不得晚于结束日期。
- 默认参数为 `--mode both --timeout 180`。`both` 同时保存原始文件并入库；`file` 只保存文件；`database` 下载到临时目录，成功入库后清理临时文件。
- 未指定 `--output-dir` 时，文件保存到 `data/raw/integration/integration_opening/`，文件名包含整个请求周期的起止日期。
- 固定取数口径为：工单结束时间、工单类型“开通”、数据来源“二编”；保留全部工单状态和全部业务类型，避免漏掉驳回、撤单或待指标阶段筛选的记录。
- 不要自行把“是否撤单重录”“已驳回”或“失败”直接认定为撤退单；测试单剔除、专线业务范围和撤退状态都由指标模块处理。

## 文件、重复运行与刷新

- 接口可能返回 XLSX 或传统 XLS。脚本按文件头识别真实格式，也能处理扩展名为 `.xls` 但内容实际为 XLSX 的文件；非 Excel 登录页或错误 JSON 会被拒绝。
- 运行模式包含数据库时，下载前检查 `etl_run`。一个或多个成功批次的日期并集完整覆盖请求周期且 `failed=0` 时，不登录、不请求接口，结果应为 `skipped=true`、`skip_reason=database_already_covered`。
- 同周期文件已存在、但数据库尚未覆盖时，`both` 模式会复用现有文件并执行幂等入库。
- `--refresh`（或兼容参数 `--overwrite`）会忽略数据库周期和已有文件并强制重新拉取，只在用户明确要求重取或确认现有文件异常时使用。

## 验证

- 命令退出成功，并检查终端返回结果；跳过时确认原因是 `database_already_covered`。
- 文件模式下返回文件存在、内容非空且是真实 XLS/XLSX，不是登录页、错误 JSON 或残缺文件。
- 数据库模式下存在 ETL `run_id`，并核对 `read`、`inserted`、`updated`、`unchanged`、`failed`；`failed` 必须为 0，`read=0` 时应检查日期、认证、内网和权限。
- 数据库按 `工单号` 幂等：新工单记为 `inserted`；内容相同记为 `unchanged`；内容变化记为 `updated` 并保留历史版本；工单号为空记为 `failed` 且不写入业务记录。

## 故障处理

- 缺少登录凭证：优先设置 `INTEGRATION_ZYTOKEN`；没有 Token 时必须同时设置 `INTEGRATION_ACCOUNT` 和 `INTEGRATION_PASSWORD`。
- 自动登录未取得 `pname`：检查 4A 账号密码是否失效、4A 登录流程是否变化，以及当前网络能否访问 4A。
- 接口未返回 Excel：通常是 Token 失效、权限不足、内网不可达或接口返回错误 JSON；更新认证并确认网络和权限后重试，不保存错误响应。
- 请求超时：适当增加 `--timeout` 后重试。
- 数据库已有覆盖但用户明确要求重新下载：增加 `--refresh`。
- 文件存在但数据库没有数据：使用 `both` 模式复用文件并幂等入库，不必先删除原始文件。

## 限制

- 不在取数阶段剔除测试单、筛选专线范围、判断撤退状态或计算撤退单率。
- 不修改固定接口筛选条件、接口地址、日期字段，不复制登录、导出或入库逻辑到 Skill 中。
- 不默认刷新或删除原始文件，不迁移或新增任何硬编码凭据。
