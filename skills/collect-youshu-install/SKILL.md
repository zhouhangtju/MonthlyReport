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
- 默认每 3 天、每个地市分别导出；31 天通常是 11 个日期批次乘 11 个地市。

## 执行

在项目根目录将周期转换为明确起止日期。默认使用双存储和两阶段导出：

```bash
python3 collector/youshu/fetch_install.py \
  --database data/quality_assessment.db \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both \
  --two-phase
```

默认参数为 `--chunk-days 3 --interval 0.5 --timeout 120 --poll-timeout 600`。用户只要文件时用 `--mode file`，只入库时用 `--mode database`。

登录失效时执行 `python3 collector/youshu/refresh_login.py`；它会调用项目内的 `youdata_autologin.js`。也可增加 `--login-first`。浏览器无法定位时设置 `YOUDATA_BROWSER`。不得读取或回显登录配置中的敏感值。只有用户明确要求重新拉取时才使用 `--refresh`。

## 验证

- 检查所有“日期批次 × 11 地市”均成功，不能把一个地市成功当作整月完成。
- 文件路径存在，数据库导入均有批次，`failed=0`。
- `collection_run` 显示完整覆盖时允许跳过。
- Excel 中派单时间是筛选口径；受理时间或工单状态时间落在其他月份不代表筛选失效。
- 大批量出现 500 或异步超时时，保留 `--two-phase` 并适当增加 `--poll-timeout`。

## 限制

- 不修改看板 ID、组件 ID、城市或日期筛选参数。
- 不把合并文件和分批文件重复入库，不默认刷新、删除文件或计算指标。
- 详细说明见 `collector/youshu/README.md`。
