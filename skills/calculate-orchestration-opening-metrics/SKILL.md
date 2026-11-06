---
name: calculate-orchestration-opening-metrics
description: 一次完成编排专线正式指标与资管 CSV 辅助分析，分别输出数据库指标、JSON 和非自动原因结果。只有用户明确要求其中一项时才单独运行。
---

# 编排专线开通指标与资管环节分析

默认使用同一份当月完结工单资管 CSV，顺序运行本技能的 `scripts/calculate_manual_csv.py` 和 `metrics/opening/dedicated_line_metrics.py`，两步都成功才报告技能完成。前者产出各环节辅助自动率和开通组网非自动原因 JSON/CSV；后者从 MySQL `orch_opening` 读取工单，结合资管 CSV 生成正式开通指标并入库。只有用户明确要求单独分析 CSV 或单独重算正式指标时，才仅运行对应步骤。

PPT 的主要自动率取正式中间表结果；辅助 JSON 中的组网方案非自动原因也会由 `reporting/manual_results.py` 载入 PPT，其他辅助环节率仅在正式中间表结果不可用时作为补充。因此两份结果都要输出，并核对月报月份一致，但不要求两种不同口径的自动率数值相同。

同一组命令计算省级四类专线：互联网专线、MPLS-VPN专线、传输专线、视频监控MV专线。视频监控MV仅统计编排原始表中的“行业视频MV专线”，不包含“视频监控”。移机先筛选订单类型=变更且调整类型为移机、部分移机、内部移机，再关联资管；开通/移机各有9类候选环节，拆除有6类。采用有效环节口径：工单不因某人员字段为 `/` 而整单剔除；逐环节排除空值及完整为 `/` 的处理人，其余计入该环节分母，包含“自动”计入分子。整体分母为有效环节次数之和，不能使用工单数×9或×6。结果仍写入 `result_orchestration_opening`，指标前缀分别为 `internet_`、`mpls_`、`transmission_`、`video_`。规则版本 `3.11.0-log-no-data-slash` 写入正式批次及JSON审计。地市计算和绘图暂不迁移，不应使用地市旧算法重算新中间表。

资管四环节未匹配记录或处理人为空时先留空，再只对空值应用路径规则：订单类型=变更且调整类型为停机或复机时，四个资管环节均填 `/`，不再因资管空值触发日志查询；开通及全部变更的组织资源释放填 `/`；互联网专线、MPLS-VPN专线、传输专线的归档审核填 `/`（不限制订单类型）。已有处理人或 `/` 不覆盖。拆除的组织资源释放、语音专线拆除的归档审核等其他缺失保持为空。资源查询受理人不做任何补填，语音拆除也不例外。asset_matches保留真实关联记录。旧中间表已丢失被整单剔除的工单，应用新口径须从数据库原始表重建；不要用旧中间表或旧附件替代完整原始数据。无Cookie重算不自动继承旧附件中的人工/流程日志补齐值，需保留时应明确合并来源。

辅助结果保持原 `metric_set=internet_line_manual_automation` 和互联网专线顶层字段，新增 `business_results` 保存其他三类的辅助结果及非自动原因。资管名称映射：MPLS-VPN对应“MPLS_VPN专线”；视频监控MV对应“行业视频MPLS-VPN专线”（兼容“行业视频MV专线”同义名称），排除“视频监控专线”和“视频监控”。辅助CSV同时输出四类结果，旧版仅包含互联网专线的JSON需要重新计算后再生成扩展的12页自动率内容。

## 完整执行：先生成辅助结果

```bash
python3 skills/calculate-orchestration-opening-metrics/scripts/calculate_manual_csv.py \
  --input "/absolute/path/to/资管专线.csv" \
  --month 2026-08 \
  --json-output "outputs/manual_metrics/互联网专线自动率_2026-08.json" \
  --csv-output "outputs/manual_metrics/互联网专线自动率_2026-08.csv"
```

同一月份在 `outputs/manual_metrics` 中只保留一份 `internet_line_manual_automation` JSON，避免 PPT 读取时报重复。

## 再计算正式指标

统计月份按订单结束时间归属。将用户周期转换成 `YYYY-MM`；`start-month` 是趋势起点，`end-month` 是最新统计月。未指定模式时用 `both`。`--database` 仅兼容旧命令；MySQL 连接信息写在 `storage/database.py`。

```bash
python3 metrics/opening/dedicated_line_metrics.py \
  --start-month 2025-09 \
  --end-month 2026-08 \
  --asset-csv "/absolute/path/to/资管专线.csv" \
  --mode both
```

正式指标命令默认先执行同目录的 `login_save_cookie.py`，发送短信后交互输入验证码；成功后将子系统 Cookie 原子覆盖保存到 `metrics/opening/cookie.txt`，再由 `process_log_backfill.py` 读取本地文件。登录失败立即停止，不回退旧凭证。不再接受 `--process-log-cookie`；明确不补采时使用 `--skip-process-log`。手机号沿用已验证登录脚本的 PHONE 配置，Cookie 文件及临时文件已加入 Git 忽略。

先重建当月中间表并应用路径规则，再对四个资管字段任一仍为空的订单补采；每环节取 updateDate 最新、同时间第一条，只修改空字段。查询成功但无订单或无指定环节填 `/`；处理人为空或技术异常继续留空。补齐后计算指标并重写核查CSV，不在审计中保存Cookie。每次正式重算默认重新短信登录。

脚本一次读取明细并一次遍历计算完整指标集，不要为18个子Sheet重复运行。基础口径是 `订单状态=已完成`；产品开通量按订单号去重、空订单号按行计数；自动率中间表剔除空订单号，并在关联资管前排除调整类型不属于移机、部分移机、内部移机、停机、复机的变更工单；不按 `/` 整单剔除。默认JSON为 `outputs/编排专线指标_YYYY-MM.json`。

## 验证

- 运行日志应从 `[Sheet 1/18]` 到 `[Sheet 18/18]`，并打印各项摘要。
- 数据库模式应产生成功的 `metric_run`，结果写入 `result_orchestration_opening`。
- 核对 `quality.rows_missing_order_month`；缺失业务月份的记录不会进入结果。
- 分母为0的自动率应为 `null`，不能解释成0%。
- 核对 `internet_product_average_monthly_orders`：悦享专线动态 IP 版和互联网专线套餐都应保存滚动12个月累计量（`numerator`）及月均量（`metric_value`）；有趋势数据时不得缺失或显示为0。
- 前几个月为0时先检查数据库是否有对应结束月份的 `orch_opening` 数据。
- 数据库模式成功后，确认 `orch_opening_monthly_summary` 和
  `orch_opening_monthly_quality` 已保存 `end-month` 快照。历史明细已按保留期清理时，程序会自动使用这些快照补齐趋势和同比，不应要求重新拉取全部历史明细。

不要改变结束时间口径、订单号去重和产品分类。详细口径见 `metrics/opening/dedicated_line_metrics.README.md`。

## 资管 CSV 辅助分析口径

源 CSV 至少包含 `二级编排工单号`、`环节名称`、`地市`、`业务类型`、`工单类型`、`处理人`、`处理意见`。筛选 `业务类型=互联网专线`，以 `二级编排工单号` 唯一标识工单，分别分析开通的组网方案、变更的组网方案和资源反馈、拆除的组织资源释放。移机范围先从MySQL编排原始表筛选：统计月已完成、订单类型=变更、调整类型完整等于移机、部分移机、内部移机之一；得到订单号后再关联资管CSV的二级编排工单号。CSV无调整类型，不在资管关联后再次确认；停机、复机不纳入移机指标，但保留在中间表。辅助命令参数保持不变，但移机辅助分析需要数据库中的同周期编排原始数据。

辅助脚本的自动条件为处理人包含“自动”或等于“系统管理员”，先去除首尾空格；不能凭处理意见中的“自动”判断。同一工单目标环节的全部记录都自动才算自动，任一人工、空值或未知账号均判为非自动。分母是含目标环节的去重工单数；缺少目标环节和工单跨地市冲突须单独审计。分母为零时自动率为 `null`，全省率用全省分子除以全省分母。源文件已是指定完结周期工单全集时，不再按单条环节结束时间筛选。

对开通组网非自动原因，只检查非自动处理记录的 `处理意见`：包含“工程施工”及空意见分别按工单去重计数；同一工单可以同时进入两类，各类别最多计一次。两类占比均以非自动工单数为分母，工程施工前三地市按工单数降序、并列按地市名排序。

运行后核对 JSON `audit` 中缺失目标环节、混合处理和地市冲突，报告各指标的分子、分母，以及开通组网非自动原因的数量、占比和前三地市。脚本支持 UTF-8、UTF-8 BOM 和 GB18030 CSV。

## Python 解释器

若 `python3` 不可用，改用 `python` 执行本技能中的 Python 命令（包括安装依赖命令）；先确认该命令对应 Python 3.10 及以上且已安装项目依赖。Windows 已提供的 `py -3.11` 示例可保留。

中间表保留停机、复机数据并展示调整类型；移机汇总仅统计移机、部分移机、内部移机三类，停机和复机不计入移机自动率。

中间表业务范围：关联资管前，仅保留互联网专线、MPLS-VPN专线、传输专线、行业视频MV专线。其他业务不进入中间表，原始表数据不删除。四类业务的停机、复机仍保留，但不计入移机指标；空值填充及日志补齐规则不变。审计 excluded_other_businesses 记录业务范围过滤数。地市入口仅统计互联网专线，本次不会移除其业务数据，地市算法仍暂不迁移。

## 停复机自动率及本轮资管空值补填

互联网专线、MPLS-VPN专线、传输专线新增停复机指标。范围：统计月、已完成、订单类型=变更、调整类型为停机或复机；两者合并。四个环节为受理、资源查询、配置激活、报结，沿用非空且不等于 `/` 计分母、包含“自动”计分子的规则。整体按四环节有效次数加权。停复机不混入移机，行业视频MV本次不新增停复机页面。

新增指标继续写入 result_orchestration_opening：internet/mpls/transmission 前缀的 stop_resume_automation_rate（month_stage、month_city_stage、month_all_stages）及 stop_resume_activation_rate（month_city）。8月基准和环比暂为空，不显示环比，不填0%。


项目根目录命令（python3不可用时使用python）：

```powershell
python metrics/opening/dedicated_line_metrics.py --start-month 2025-10 --end-month 2026-09 --asset-csv "data/offline_data/结束时间为9月1日-9月30日的资管专线数据清单_1008.csv" --mode both
python reporting/build_internet_line_ppt.py --month 2026-09 --section 专线自动情况 --keep-json --output "outputs/monthly_report/专线自动情况_2026-09_含停复机.pptx"
```

省级自动率新增两页：互联网与VPN为第一页，传输为第二页。图片脚注原文保留。省级完整稿新增页为23、24，终端目录25、内容26～27，业务支撑目录28、内容29～30；地市版页码不变。

### 2026-11-02 资管路径规则补充

- 拆除不经过组网方案和资源反馈：两列空值填 `/`。
- 全部变更不经过组织资源释放：该列空值填 `/`，含移机、部分移机、内部移机、停机、复机。
- 已有处理人或 `/` 均保留；原始资管关联信息 asset_matches 不修改。其他规则继续执行。
- 当前中间表为持久化表 intermediate_orchestration_orders，按月替换数据；重新构建9月不删除其他月份、原始表或正式结果批次。

日志补齐最新规则：查无订单或指定环节填 `/`，日志处理人明确为 `/` 时可回填该占位符；技术异常及环节存在但处理人为空时继续留空。多orderId或缺少orderId不当作查无数据。查询仍沿用90天范围，审计区分查无数据、填斜杠和失败。已删除统一补填全部资管空值的参数及函数。线上仍从编排原始表重建、关联资管、可选日志补齐、汇总入库，不提供CSV导入参数。本次用户回传CSV仅作线下模拟，不新增项目入口。
