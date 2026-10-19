---
name: calculate-terminal-recovery-by-city
description: 从省级terminal_recovery成功批次提取指定地市、标准区县、业务类型和设备类型指标，并写入地市终端回收结果批次。用户要求生成地市终端回收页面或核算区县回收指标时使用。
---

# 地市终端回收指标准备

先确认省级 `terminal_recovery` 成功批次已经生成。首次运行时，地市入口从数据库恢复该周期原始快照，一次计算全省业务类型与设备类型并写入 `terminal_recovery_bycity_preparation` 准备批次；后续地市复用该批次：

```bash
python3 metrics/terminal_recovery/bycity/terminal_recovery_metrics_by_city.py \
  --month "$REPORT_MONTH" \
  --city "$CITY" \
  --mode both
```

各地市结果任务编码为 `terminal_recovery_metrics_by_city`，继续写入 `result_terminal_recovery`，不会新增数据库表。默认 JSON 输出为 `outputs/终端回收地市指标_{地市}_{月份}.json`。

结果包含全省11地市对比、目标地市的 `district_summary`，以及在地市脚本内计算的 `city_business`。区县结果沿用省级流程已经完成的区县清洗，地市PPT只读取目标地市成功批次，不在绘图层重新计算。

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。
