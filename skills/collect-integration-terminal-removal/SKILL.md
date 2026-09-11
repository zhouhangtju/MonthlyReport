---
name: collect-integration-terminal-removal
description: 从一体化平台获取终端回收所需的专线拆机清单并按模式入库。用户提到专线拆机、integration_removal_order 或终端回收源工单时使用，不用于售中开通撤退单。
---

# 一体化：终端回收专线拆机取数

入口为 `collector/integration/zhuanxian_chaiji_export.py`。沿用脚本已有筛选和标准化，不在 Skill 中重新计算设备数量或去重。

## 前置条件

- 定位含 `pyproject.toml` 的项目根目录，并在该目录运行；Python 3.10+ 且已安装项目依赖。
- 确认同一个月的起止日期；月报使用完整自然月，并显式指定本次流程共用的数据库。
- 实际下载前复用 `integration_dismantle.py` 的账号配置、自动登录、Token 提取和保存函数，Token 写入项目 `collector/credentials/zhengqi_yitihua.json`。无需预先准备旧 OpenClaw 工作区的 Token 文件，也无需先运行物资取数。
- 确认凭据保存目录可写，不回显凭据。登录失败或平台不可达时停止并请维护者处理，不反复重试。

## 执行

在 Windows 项目根目录执行，替换实际日期与路径：

```powershell
py -3.11 collector/integration/zhuanxian_chaiji_export.py --start-date 2026-08-01 --end-date 2026-08-31 --mode both --database D:/MonthlyReport/data/quality_assessment.db --output-dir D:/edge_download
```

- 数据集 `integration_removal_order`，主键为工单号；文件 `一体化专线拆机清单_YYYY-MM.xlsx`。
- 默认 `both` 保留 Excel 和 SQLite 源记录、源快照。`database` 临时下载后入库并清理临时文件；`file` 仅下载。
- 同周期已覆盖可正常跳过，`both` 还要求本地文件存在。强制重取只在用户明确要求时加 `--refresh`。
- `--reuse-existing` 用于用户指定的本地文件复用，不访问平台、不自动确认文件内日期；与 `--refresh` 不应同时用于真实下载验证。
- Linux/WSL 需显式指定适用的下载目录和数据库路径，不能直接照搬 Windows 示例。

## 验证

等待命令结束，检查退出状态；文件模式检查本地文件，数据库模式检查 ETL 的 `failed=0` 和对应源快照。保留运行批次和跳过原因，错误时停止下游，不删除历史数据。

完整流程还需要 `collect-eoms-terminal-removal`、`collect-integration-terminal-materials` 和 `calculate-terminal-recovery`。详见 `metrics/terminal_recovery/README.md`。
