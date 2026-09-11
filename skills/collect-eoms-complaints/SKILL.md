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

在项目根目录将周期转换为明确起止日期。默认模式为 `both`，默认数据库为 `data/quality_assessment.db`。

```bash
python3 collector/eoms/fetch_complaints.py \
  --database data/quality_assessment.db \
  --start-date 2026-05-01 \
  --end-date 2026-07-31 \
  --mode both
```

若 Token 已过期，执行 `python3 collector/eoms/refresh_login.py`，也可增加 `--login-first`。登录信息使用 `EOMS_ACCOUNT`、`EOMS_PASSWORD` 或本地 `collector/eoms/eoms_login.json`；不得读取或回显内容。默认 `--page-size 500`。只在用户明确要求强制重取时加 `--refresh`。

## 验证

- 命令退出成功，文件名周期与请求周期一致。
- 文件存在且为有效 Excel，数据库批次有 `run_id`，`failed=0`。
- `database_already_covered` 表示完整周期已有数据，可正常跳过。
- Token 过期时刷新登录后重试一次；仍失败则报告错误，不循环登录。
- “只保留正常结束/已完成”等条件由指标模块处理，不属于取数验证。

## 限制

- 不输出 Token、账号或密码。
- 不在 Skill 中新写区县反推、重复投诉分组或指标逻辑，沿用采集脚本已有整理逻辑。
- 不默认刷新或删除历史文件。
- 详细说明见 `collector/eoms/README.md`。
