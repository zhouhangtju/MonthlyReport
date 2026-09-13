---
name: collect-eoms-complaints
description: 从 EOMS 获取“政企投诉工单”，补齐详情并保存为原始 Excel、写入 SQLite 或双存储。用户提到 EOMS 投诉工单、eoms_complaint、千里眼或专线重复投诉率的数据准备时使用。
---

# EOMS：政企投诉工单取数

只负责投诉工单采集和项目既有字段整理，不计算重复投诉率或报障率。

## 数据口径

- 数据集：`eoms_complaint`
- 源记录主键：优先 `id`
- 文件目录：`data/raw/eoms/eoms_complaint/`
- 入口：`collector/eoms/fetch_complaints.py`
- 采集会调用列表与详情接口，沿用现有逻辑补齐字段、提取 `e55...` 计费号；计费号仍为空时用手机号补齐。

## 执行

在项目根目录将周期转换为明确的 `YYYY-MM-DD` 起止日期。日期取值规则如下：

- 用户未显式指定日期时，`end-date` 默认取当前对话中的月报时间，`start-date` 取该月报时间向前推 3 个月的同一日期，即默认获取最近 3 个月的数据。
- 用户显式指定起止日期时，以用户输入为准。
- 当前对话没有可确定的月报时间时，先询问用户，不得擅自使用系统当前日期代替。

默认模式为 `both`，默认数据库为 `data/quality_assessment.db`。例如，对话中的月报时间为 `2026-08-31` 时：

```bash
python3 collector/eoms/fetch_complaints.py \
  --database data/quality_assessment.db \
  --start-date 2026-05-31 \
  --end-date 2026-08-31 \
  --mode both
```

## 环境与登录

- 运行主机需要能访问浙江移动 4A 和 EOMS，并安装项目 `requirements.txt` 中的 Python 依赖。项目已有虚拟环境时优先激活；缺少依赖时，在项目根目录运行 `python3 -m pip install -r requirements.txt`。
- 底层登录脚本的凭据读取优先级为命令行参数、环境变量 `EOMS_ACCOUNT`/`EOMS_PASSWORD`、本地 `collector/eoms/eoms_login.json`、终端交互输入。当前 `refresh_login.py` 在未显式同时传入账号密码时会先检查本地 `eoms_login.json` 是否存在，因此部署环境应保留该文件；实际凭据优先使用环境变量或部署环境单独提供的本地配置，避免进入终端历史。
- `eoms_login.json` 含登录配置，`collector/eoms/login.db` 含 Bearer Token，两者都不得读取具体值、复制到 Skill、提交 Git 或输出到日志。

不要在数据库已完整覆盖或 Token 仍有效时默认重新登录。仅当 `login.db` 不存在、返回“登录状态已过期”、Token 失效或认证失败时，强调并执行以下重新登录流程：

1. 确认本地 `collector/eoms/eoms_login.json` 存在，并由部署环境通过该文件或 `EOMS_ACCOUNT`/`EOMS_PASSWORD` 提供凭据；不得要求用户把实际账号密码发到对话中。
2. 在项目根目录运行 `python3 collector/eoms/refresh_login.py`。脚本会完成 4A 登录、换取 Bearer Token，并更新 `collector/eoms/login.db`。
3. Token 刷新成功后重新执行原取数命令；也可在重试命令中增加 `--login-first`，先刷新 Token 再取数。
4. 登录刷新或重试仍失败时，停止并报告脱敏错误，不循环登录；检查 4A 账号密码、内网、RSA 公钥流程、`pname` 跳转和 EOMS 权限。

## 参数、采集与存储

- `--start-date` 和 `--end-date` 是闭区间，结束日期包含当天；格式必须为 `YYYY-MM-DD`，开始日期不得晚于结束日期。
- 默认参数为 `--mode both --page-size 500`。脚本按页调用投诉列表接口，并使用 `beginCreateTime`、`endCreateTime` 和 `deleted=0` 筛选。
- `both` 同时保留原始 Excel 并入库；`file` 只保留文件；`database` 临时生成文件，成功入库后清理。默认文件目录为 `data/raw/eoms/eoms_complaint/`，文件名包含整个请求周期。
- 采集会展开列表字段，对缺少计费号码等信息的记录调用详情接口；优先从附加报结信息、其他文本和详情字段提取 `e55...` 计费号。仍为空时才用手机号补位，并记录补位来源；已有计费号不得覆盖，原手机号字段必须保留以便审计。
- 数据库已有成功、无失败的 ETL 批次完整覆盖请求周期时，`database` 和 `both` 模式默认不登录、不请求接口，返回 `skipped=true`、`skip_reason=database_already_covered`。
- 默认不加 `--refresh`。只有用户明确要求重新获取，或确认现有周期数据异常时，才用 `--refresh` 绕过数据库覆盖检查。

## 验证

- 命令退出成功，终端返回结果中的起止日期和文件名周期与请求周期一致。
- 文件模式下文件存在且为有效 Excel；若脚本退出成功但未生成预期 Excel，仍视为失败。
- 数据库模式下存在 ETL `run_id`，并核对 `read`、`inserted`、`updated`、`unchanged`、`failed`；`failed` 必须为 0。`read=0` 时检查日期、Token、内网和权限，不直接当作有效成功。
- 跳过时确认 `skip_reason=database_already_covered`，且已有成功批次的日期并集确实覆盖本次三个月周期。
- 检查分页采集完整、详情补全已执行、已有计费号未被手机号覆盖，并保留 `计费号码补位来源` 供审计。
- Token 失效时只刷新并重试一次；仍失败则报告脱敏错误，不循环登录。

数据库优先按 `id` 幂等写入：同一主键内容相同记为 `unchanged`，内容变化记为 `updated` 并保留历史版本。

## 故障处理

- Token 缓存不存在：运行 `python3 collector/eoms/refresh_login.py` 生成 `collector/eoms/login.db` 后重试。
- 登录状态过期或认证失败：按上面的重新登录流程刷新 Token，重试一次。
- 登录脚本未生成 `login.db`：检查账号来源、4A 内网与登录流程，停止取数并报告脱敏错误。
- 请求失败、分页中断或详情接口异常：不要把部分数据视为完整三个月结果；确认网络和 Token 后重新执行。
- 数据库已覆盖但用户明确要求重新获取：增加 `--refresh`。
- 页面数据量较大或分页异常：保留默认 `--page-size 500`；只有确认接口承载需要调整时再改变页大小。

## 限制

- 不输出 Token、账号或密码。
- 不在 Skill 中新写区县反推、产品筛选、非自建判断、重复投诉 Key、短时间重复派单剔除或指标分子分母逻辑，沿用采集脚本已有整理逻辑。
- 不把“正常结束”“已完成”等指标条件提前用于取数过滤。
- 不默认刷新或删除历史文件，不复制登录、列表分页、详情补全或入库实现到 Skill 中。
