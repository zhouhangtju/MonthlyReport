---
name: collect-youshu-complaints
description: 从有数平台获取“企宽投诉清单”，按日期分批导出，并保存原始 Excel、写入 MySQL。用户提到有数企宽投诉单、youshu_complaint、工单号，或准备企宽新装保障率分子时使用。
---

# 有数：企宽投诉清单取数

只负责取数与入库，不计算企宽新装保障率。

## 数据口径

- 数据集：`youshu_complaint`
- 源记录主键：`工单号`
- 文件目录：`data/raw/youshu/youshu_complaint/`
- 入口：`collector/youshu/fetch_complaints.py`
- 本 Skill 默认使用 `--chunk-days 100`，让不超过 100 天的三个月周期作为一个日期批次下载；投诉单不按 11 地市拆分，因此通常只生成 1 个批次文件。

## 执行

在项目根目录将周期换算成明确的 `YYYY-MM-DD` 起止日期。日期取值规则如下：

- 用户未显式指定日期时，`end-date` 默认取当前对话中的月报时间，`start-date` 取该月报时间向前推 3 个月的同一日期，即默认获取最近 3 个月的数据。
- 用户显式指定起止日期时，以用户输入为准。
- 当前对话没有可确定的月报时间时，先询问用户，不得擅自使用系统当前日期代替。

默认用双存储；大批量任务建议两阶段导出。`--database` 仅兼容旧命令；MySQL 连接信息写在 `storage/database.py`。例如，对话中的月报时间为 `2026-08-31` 时：

```bash
python3 collector/youshu/fetch_complaints.py \
  --start-date 2026-05-31 \
  --end-date 2026-08-31 \
  --chunk-days 100 \
  --mode both \
  --two-phase
```

调用时显式传入 `--chunk-days 100`；其余默认参数为 `--interval 0.5 --timeout 120 --poll-timeout 600`。请求周期不超过 100 天时会一次提交整个周期，超过 100 天时才继续按每 100 天拆分。用户只要文件时改用 `--mode file`。

不要在正常取数前默认刷新登录。仅当返回 610、明确提示认证失败或登录会话失效时，强调并执行以下重新登录流程：

1. 停止当前失败的采集，在项目根目录运行 `python3 collector/youshu/refresh_login.py`。
2. 等待脚本启动或复用 Edge/Chrome、完成自动登录并刷新认证配置；不得读取、记录或回显登录配置、Cookie、CSRF、roomid 或 sid。
3. 登录刷新成功后，重新执行原取数命令；也可在重试命令中增加 `--login-first`，让脚本先重新登录再取数。
4. 若提示找不到浏览器，让用户将 `YOUDATA_BROWSER` 设置为 Edge 或 Chrome 的可执行文件绝对路径后，再运行刷新登录命令。

刷新脚本会调用项目内的 `youdata_autologin.js`。默认不加 `--refresh`，只在用户明确要求强制重取时使用。

## 验证

- 所有日期批次均有结果，文件数与日期切片相符。
- 文件有效，数据库批次存在，`failed=0`。
- `collection_run` 已完整覆盖时跳过是正常行为。
- 不要求每条记录的所有时间字段都落在请求周期，以看板实际筛选字段为准。
- 若持续出现 500 或排队超时，使用 `--two-phase` 并增加 `--poll-timeout`。

## 限制

- 不修改看板参数或接口实现。
- 不把合并文件和分批文件重复导入，不默认刷新、删除原始文件或计算指标。
- 详细说明见 `collector/youshu/README.md`。
