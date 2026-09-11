---
name: collect-youshu-complaints
description: 从有数平台获取“企宽投诉清单”，按日期分批导出，并保存原始 Excel、写入 SQLite 或双存储。用户提到有数企宽投诉单、youshu_complaint、工单号，或准备企宽新装保障率分子时使用。
---

# 有数：企宽投诉清单取数

只负责取数与入库，不计算企宽新装保障率。

## 数据口径

- 数据集：`youshu_complaint`
- 源记录主键：`工单号`
- 文件目录：`data/raw/youshu/youshu_complaint/`
- 入口：`collector/youshu/fetch_complaints.py`
- 默认每 3 天一个日期批次，不按 11 地市拆分；31 天通常约 11 个文件。

## 执行

在项目根目录将周期换算成明确起止日期。默认用双存储；大批量任务建议两阶段导出：

```bash
python3 collector/youshu/fetch_complaints.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both \
  --two-phase
```

默认参数为 `--chunk-days 3 --interval 0.5 --timeout 120 --poll-timeout 600`。用户只要文件时改用 `--mode file`。

登录失效时运行 `python3 collector/youshu/refresh_login.py`，或增加 `--login-first`。刷新脚本会调用项目内的 `youdata_autologin.js`。不得输出登录配置、Cookie、CSRF、roomid 或 sid。默认不加 `--refresh`，只在用户明确要求强制重取时使用。

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
