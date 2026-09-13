---
name: collect-youshu-install
description: 从有数平台获取“企宽新装清单”，按日期和地市分批导出，并保存原始 Excel、写入 SQLite 或双存储。用户提到有数企宽新装单、youshu_install、工单id，或准备企宽新装保障率分母时使用。
---

# 有数：企宽新装清单取数

只调用已有有数采集脚本，不计算新装保障率。

## 数据口径

- 数据集：`youshu_install`
- 源记录主键：`工单id`
- 文件目录：`data/raw/youshu/youshu_install/`
- 入口：`collector/youshu/fetch_install.py`
- 本 Skill 默认使用 `--chunk-days 100`，让不超过 100 天的三个月周期作为一个日期批次下载；仍按 11 个地市分别导出，因此通常是 1 个日期批次乘 11 个地市。

## 执行

在项目根目录将周期转换为明确的 `YYYY-MM-DD` 起止日期。日期取值规则如下：

- 用户未显式指定日期时，`end-date` 默认取当前对话中的月报时间，`start-date` 取该月报时间向前推 3 个月的同一日期，即默认获取最近 3 个月的数据。
- 用户显式指定起止日期时，以用户输入为准。
- 当前对话没有可确定的月报时间时，先询问用户，不得擅自使用系统当前日期代替。

默认使用双存储和两阶段导出。例如，对话中的月报时间为 `2026-08-31` 时：

```bash
python3 collector/youshu/fetch_install.py \
  --database data/quality_assessment.db \
  --start-date 2026-05-31 \
  --end-date 2026-08-31 \
  --chunk-days 100 \
  --mode both \
  --two-phase
```

## 环境与登录

- 需要 Python 3.10 或更高版本、Node.js 22 或更高版本、Microsoft Edge 或 Google Chrome，并且当前网络能够访问有数平台内网。缺少 Python 依赖时，在项目根目录运行 `python3 -m pip install -r requirements.txt`；项目已有虚拟环境时优先激活后再运行。
- `collector/youshu/youdata_login.json` 是自动登录输入，`collector/youshu/有数配置.json` 是运行期认证配置。两者可能包含敏感信息，不得读取具体值、复制到 Skill、提交 Git 或输出到日志。

不要在正常取数前默认刷新登录。仅当返回 610、明确提示认证失败或登录会话失效时，强调并执行以下重新登录流程：

1. 停止当前失败的采集，在项目根目录运行 `python3 collector/youshu/refresh_login.py`。
2. 等待脚本调用 `youdata_autologin.js`，启动或复用 Edge/Chrome，完成自动登录并刷新 Cookie、CSRF、roomid 和 sid；不得读取或回显这些值。
3. 刷新成功后重新执行原取数命令；也可在重试命令中增加 `--login-first`，让脚本先登录再取数。
4. 若提示找不到浏览器，让用户把 `YOUDATA_BROWSER` 设置为 Edge 或 Chrome 的可执行文件绝对路径，再运行刷新登录命令。

## 参数与运行行为

- 调用时显式传入 `--chunk-days 100`；其余默认参数为 `--mode both --interval 0.5 --timeout 120 --poll-timeout 600`，并启用 `--two-phase`。
- `--start-date` 和 `--end-date` 是闭区间。请求周期不超过 100 天时只生成 1 个日期批次，超过 100 天时才按每 100 天继续拆分；每个日期批次仍按 11 个地市分别导出。
- `--two-phase` 先为全部日期和地市创建异步导出任务，再统一轮询下载，适合本 Skill 的三个月批量采集。
- `both` 同时保留文件并入库；`file` 只保留文件；`database` 使用临时目录，成功入库后清理文件。默认数据库为 `data/quality_assessment.db`，默认文件目录为 `data/raw/youshu/youshu_install/`。
- 取数日期通过看板参数注入，并固定循环 11 个地市和企宽类型筛选。Excel 中以派单时间为筛选口径；受理时间或工单状态时间落在其他月份，不代表日期筛选失败。

## 完整覆盖与重复运行

- 不能以某一个地市文件或单个 ETL 批次成功代表整个周期完成。预期文件数为“日期批次数 × 11 个地市”；默认三个月且不超过 100 天时通常应有 11 个批次文件。
- `collection_run` 记录预期文件数、实际文件数、成功入库数、全部源文件、ETL `run_id` 和整次状态。只有全部预期文件生成并成功入库，才标记数据库完整覆盖。
- 数据库已完整覆盖相同周期时，允许跳过，并确认 `skipped=true`、`skip_reason=database_already_covered`。失败的采集记录不会阻止修复后重新执行。
- 同一 `工单id` 内容相同记为 `unchanged`，内容变化记为 `updated` 并保留历史版本。`宽带账号`只用于关联投诉，不是主键，一个账号允许有多张新装工单。
- 默认不加 `--refresh`。只有用户明确要求重新获取，或确认不完整文件需要覆盖后，才使用 `--refresh`。

## 验证

- 命令退出成功，所有“日期批次 × 11 地市”都有结果，实际文件数等于预期文件数，不能把一个地市成功当作全周期完成。
- 每个文件路径存在且是完整 XLSX；文件数量不足时，整次采集必须保持失败状态，不能写成数据库已覆盖。
- 数据库模式下，每个源文件都有对应 ETL 批次，核对 `run_id` 和 `failed=0`，并确认 `collection_run` 的成功入库数等于预期文件数。
- 只导入日期和地市批次原始文件；若底层脚本另有生成带“合并”字样的 Excel，不要与批次文件重复入库。
- 跳过时确认 `skip_reason=database_already_covered`，并确认它来自完整 `collection_run`，而不是单个文件的成功记录。

## 故障处理

- 返回 610、认证失败或会话失效：先运行 `python3 collector/youshu/refresh_login.py`，成功后重试原命令。
- 自动登录找不到浏览器：设置 `YOUDATA_BROWSER` 为 Edge 或 Chrome 的可执行文件绝对路径。
- 文件数量不足：检查登录是否过期、个别地市是否失败、异步任务是否超时或看板参数是否变化；刷新登录后保留 `--two-phase`，适当增加 `--poll-timeout`，需要覆盖不完整文件时在用户授权后加 `--refresh`。
- 持续返回 500 或轮询超时：保留 `--two-phase` 并增加 `--poll-timeout`；不要把部分下载结果当作成功。
- 数据库已覆盖但用户明确要求重新获取：加 `--refresh` 后执行。

## 限制

- 不修改看板 ID、组件 ID、城市、企宽类型或日期筛选参数，不在 Skill 中复制底层异步接口逻辑。
- 不把合并文件和批次文件重复入库，不默认刷新、删除文件或计算指标。
- 发布或提交时不包含实际的 `youdata_login.json`、`有数配置.json` 或任何登录敏感值。
