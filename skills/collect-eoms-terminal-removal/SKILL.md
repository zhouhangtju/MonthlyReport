---
name: collect-eoms-terminal-removal
description: 从 EOMS 获取终端回收所需的服务类产品支撑工单，下载 Excel 并按模式入库。用户提到终端回收的 EOMS 拆机、服务类工单或 eoms_service_removal_order 数据准备时使用，不用于政企投诉工单。
---

# EOMS：终端回收服务类工单取数

只调用 `collector/eoms/eoms_export_qiwan_auto_login.py`，不重新实现登录、筛选或回收率算法。

## 前置条件与口径

- 确认项目根目录包含 `pyproject.toml`、`collector` 和 `storage`；不要把 Skill 所在目录当作运行目录。以下命令均在项目根目录执行。
- 使用已安装项目依赖的 Python 3.10+；Windows 示例使用 `py -3.11`。其他平台须先确认解释器和路径适配，不能直接照搬 Windows 路径。
- 将日期转成明确的 `YYYY-MM-DD`：用户未显式指定日期时，`end-date` 默认取当前对话中的月报时间，`start-date` 取该月报时间向前推 1 个日历月的同一日期，即默认获取最近 1 个月的数据；若目标月份没有同一日，则取该月最后一天。用户显式指定起止日期时以用户输入为准；当前对话没有可确定的月报时间时先询问，不得擅自使用系统当前日期代替。多个步骤使用同一周期和数据库绝对路径。
- 数据集为 `eoms_service_removal_order`，源主键为工单号，文件为 `服务类产品支撑工单_YYYY-MM.xlsx`。
- 运行主机必须能访问 EOMS 登录和导出接口。脚本已有自动登录；不把账号、密码、Token 写入 Skill 或回复。

## 执行

```powershell
py -3.11 collector/eoms/eoms_export_qiwan_auto_login.py --start-date 2026-07-31 --end-date 2026-08-31 --mode both
```

上例对应对话中的月报时间 `2026-08-31`。日期和路径按实际部署替换，不将示例月份当作默认业务周期。

- `both`：保留本地文件，并调用现有 importer 入库、保存源快照；默认模式。
- 默认保存到项目 `data/raw/eoms/eoms_service_removal_order/`；可用 `--output-dir` 指定其他目录。
- `database`：临时下载并入库，自动清理本次临时文件，不要求保留本地 Excel。
- `file`：仅下载，不写库；后续算数前仍需入库。
- 已有完整同周期快照时可跳过，`both` 还检查文件存在。只有明确要求重取时使用 `--refresh`。
- 仅当用户要求使用已有下载文件时使用 `--reuse-existing`；它不验证文件内的真实日期，不能作为真实线上下载成功的证据。

## 验证与失败处理

等待进程结束，记录退出状态、文件路径、ETL 批次、读取条数、失败条数或跳过原因。数据库模式核对源快照及 `failed=0`；文件模式不要求数据库批次。失败时停止后续算数，报告脱敏错误，不循环登录或盲目刷新。

本步骤只完成一种源数据；完整回收流程还需两个一体化取数 Skill 和 `calculate-terminal-recovery`。详细模式见 `metrics/terminal_recovery/README.md`。
