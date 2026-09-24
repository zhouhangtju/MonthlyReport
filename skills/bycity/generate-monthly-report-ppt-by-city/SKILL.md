---
name: generate-monthly-report-ppt-by-city
description: 从 MySQL 已落库的地市及区县级编排专线指标生成月报前6页“业务发展情况”PPTX。用户要求生成杭州等地市版业务发展月报、展示地市总量及各区县互联网/MPLS/传输专线开通情况时使用；不生成省级月报或其他章节，也不在绘图阶段重新计算指标。
---

# 生成地市版业务发展情况 PPT

只调用 `reporting/by-city/build_internet_line_ppt_by_city.py`，从成功的 `orchestration_opening_metrics_by_city` 指标批次生成6页 PPT。现有省级 `reporting/build_internet_line_ppt.py` 保持不变。

## 页面结构

1. 集客综调月报封面，标明地市和月份。
2. 目录页，突出“业务发展情况”。
3. 互联网专线：地市产品总览、各区县分产品开通量、近12个月悦享专线趋势。
4. 互联网专线套餐和其他互联网产品近12个月趋势。
5. MPLS-VPN：地市产品总览、各区县分产品开通量、近12个月趋势。
6. 传输专线：地市产品总览、各区县分产品开通量、近12个月趋势。

视觉、字号、配色、母版和图表布局继承现有省级业务发展页面。省级页面中的“全省”替换为目标地市，“各地市”替换为目标地市各区县。不得用0掩盖缺失指标。

## 数据准备

运行前应先完成：

```bash
python3 metrics/opening/bycity/dedicated_line_metrics_by_city.py \
  --city 杭州 \
  --start-month 2025-09 \
  --end-month 2026-08 \
  --mode both
```

目标指标批次必须满足：

- `metric_run.metric_code='orchestration_opening_metrics_by_city'`
- `status='success'`
- `period_end` 等于月报月末
- 结果中的 `city` 与请求地市一致
- 目标月存在 `month_city_county_product` 区县分布
- 趋势月份、同比基期和环比基期完整

## 生成

```bash
python3 reporting/by-city/build_internet_line_ppt_by_city.py \
  --month 2026-08 \
  --city 杭州
```

默认输出：

```text
outputs/monthly_report/by_city/杭州市业务发展情况_2026年8月.pptx
outputs/monthly_report/by_city/杭州市业务发展情况_2026年8月.audit.json
```

可通过 `--output` 指定输出，通过 `--template` 指定 PPT 模板；`--keep-json` 保留绘图中间数据。`--database` 仅兼容旧命令，实际 MySQL 连接配置仍由 `storage/database.py` 决定。

## 验证

1. 构建命令退出为0，PPTX和审计JSON存在。
2. 审计中的 `missing` 必须为空，选中的指标批次、月份和地市正确。
3. PPTX可解压，页面数必须为6。
4. 使用 PowerPoint 兼容的本地渲染导出PDF，再逐页检查：母版、微软雅黑、标题、数据标签、区县横轴、图例、页码和口径说明均正确。
5. 第3、5、6页区县合计应与对应地市总量一致；“未归属区县”存在时必须保留显示并在交付说明中披露。

找不到成功指标批次或审计出现缺失时，先补取和补算，不得在 reporting 层直接查询原始订单临时计算。
