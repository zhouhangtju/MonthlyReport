---
name: calculate-orchestration-automation-metrics-by-city
description: 从已生成的专线自动率中间表计算指定地市及标准区县的互联网专线开通、移机、拆机自动率，并写入MySQL结果表。用户要求计算地市版专线自动情况或为地市月报准备自动率数据时使用。
---

# 计算地市及区县专线自动率

先确认目标月份的 `intermediate_orchestration_orders` 已由省级自动率流程生成。该表已经完成订单去重、斜杠字段剔除和资管四环节匹配，本技能不得重复读取资管 CSV 或重建中间表。

执行：

```bash
python3 metrics/opening/bycity/automation_metrics_by_city.py \
  --month "$REPORT_MONTH" \
  --city "$CITY" \
  --mode both
```

脚本按 `data/区县信息汇总.xlsx` 将原始区县和主题关键字映射为标准区县，分别计算开通、变更（PPT显示为移机）、拆除（PPT显示为拆机）的地市各环节、地市整体、区县各环节和区县整体自动率。

结果任务编码为 `orchestration_automation_metrics_by_city`，写入 `metric_run` 和 `result_orchestration_opening`；默认 JSON 输出为 `outputs/编排专线自动率地市指标_{地市}_{月份}.json`。省级自动率结果和中间表不被改写。

计算成功后检查任务状态为 `success`，目标地市、月份和中间表 `build_id` 唯一。若中间表没有目标月数据，先运行省级自动率准备流程，不得在本技能内回退读取原始 CSV。

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。
