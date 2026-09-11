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

在项目根目录运行，将统计周期转换为明确的 `YYYY-MM-DD` 起止日期。默认模式为 `both`，默认数据库为 `data/quality_assessment.db`。

```bash
python3 collector/integration/fetch_withdrawal_orders.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

认证可使用环境变量 `INTEGRATION_ZYTOKEN`，或 `INTEGRATION_ACCOUNT` 与 `INTEGRATION_PASSWORD`；也可传对应命令行参数。不得输出凭据。数据库已覆盖时允许跳过，只有用户明确要求强制重取时加 `--refresh`。

## 验证

- 命令退出成功，输出文件存在且是有效 Excel。
- 数据库模式存在 ETL 批次，确认读取数和 `failed` 数。
- `database_already_covered` 是正常跳过标识。
- 缺少登录凭证时设置环境变量或显式参数后重试，不把凭据写入 Skill。

数据库按 `工单号` 幂等写入，相同记录不会重复。

## 限制

- 不在取数阶段剔除测试单或计算撤退单率。
- 不修改固定接口筛选条件，不默认刷新或删除原始文件。
- 详细说明见 `collector/integration/README.md`。
