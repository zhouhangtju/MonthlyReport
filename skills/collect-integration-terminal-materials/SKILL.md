---
name: collect-integration-terminal-materials
description: 从一体化平台获取终端出入库、全省物资基准库，并导入物料名称映射，为终端回收算数准备物资数据。用户提到终端入库、终端出库、物资基准库或 integration_dismantle 时使用。
---

# 一体化：终端回收物资取数

入口为 `collector/integration/integration_dismantle.py`。在项目根目录运行，使用安装项目依赖的 Python 3.10+。确认年份、月份和共用数据库绝对路径。

## 日期与数据口径

- 参数代表统计周期，月报用月初至月末；日期必须在同一个月。
- 当前代码对出入库的实际查询范围为统计月月初至次月 **3 日（含当天）**。8 月示例实际查询到 9 月 3 日 23:59:59，文件名和入库周期仍为 8 月，不要自行改成次月 6 日。
- 若目标截止日尚未到来，说明数据可能不完整，不能宣称完整月报已准备好。

| 数据集 | 文件 |
| --- | --- |
| `integration_terminal_outbound` | `终端出库_YYYY-MM.xlsx` |
| `integration_terminal_inbound` | `终端入库_YYYY-MM.xlsx` |
| `integration_material_baseline` | `全省物资基准库.xlsx` |
| `terminal_material_names` | `物料名称表.xlsx` |

物料名称表优先使用下载目录版本，否则使用 `metrics/terminal_recovery/物料名称表.xlsx`，它不是平台下载的数据。保留无天然主键源数据的重复明细，由现有脚本补导入行主键；不要提前删重。出库仍采集入库，但不参与当前终端回收算法。

## 执行

```powershell
py -3.11 collector/integration/integration_dismantle.py --start-date 2026-08-01 --end-date 2026-08-31 --mode both
```

替换实际日期、路径；Windows 使用 `py -3.11`，其他环境先确认解释器和路径兼容。

- 默认 `both` 保留下载文件并入库、保存快照；`database` 使用临时下载目录并入库；`file` 只保留本地资料，不能直接支持数据库算数。
- 默认文件目录为项目 `data/raw/integration/terminal_materials/`；可用 `--output-dir` 指定其他目录。
- 已有完整快照可跳过；`both` 还检查文件存在。只有用户明确重取才加 `--refresh`。
- 用户明确复用已下载文件时可加 `--reuse-existing`，先确认目录中各文件所属周期；该选项不验证内容日期，也不证明线上接口可用。
- 使用原有自动登录，Token 写入项目 `collector/credentials/zhengqi_yitihua.json`，需有写入权限。专线拆机脚本复用同一登录流程并自行获取新 Token，无需依赖本步骤先运行。不要回显登录信息。

## 验证

等待所有导出结束，检查实际查询截止日期、每类文件/ETL/源快照、`failed=0`；数据库模式不要求保留本地文件。下载失败不得拿旧文件冒充本次结果，停止后续算数并报告脱敏错误，不无限重试。

完整流程还需两个工单取数 Skill。全部入库后执行 `calculate-terminal-recovery`；使用同一数据库时按顺序运行，避免并发写入和覆盖同名文件。详见 `metrics/terminal_recovery/README.md`。
