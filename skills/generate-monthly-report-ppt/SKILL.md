---
name: generate-monthly-report-ppt
description: 从质量评估 SQLite 指标结果生成互联网专线月报 PPTX，支持完整月报、单章节输出、模板或图片背景及审计检查。用户提到生成月报PPT、互联网专线产品开通情况、业务发展情况、专线自动情况、终端回收情况或业务支撑情况演示稿时使用；不用于重新计算指标或手工重画幻灯片。
---

# 从数据库生成月报 PPT

只调用 `reporting/` 中的既有脚本，从已落库的成功指标结果生成 PPTX。不要绕过数据库重新计算指标，也不要直接修改生成后的幻灯片来掩盖数据缺失。

## 脚本与模板职责

- 主入口：`reporting/build_internet_line_ppt.py`。校验参数和输入、读取数据库、生成审计文件、调用 Node 绘图并执行 PPTX 后处理。
- 数据映射：`reporting/database_results.py`。只读连接 SQLite，从 `metric_run` 和 `ads_metric_result` 选择成功批次，整理业务发展、自动率、终端回收、撤退单率、重复投诉率和新装报障率数据。
- 绘图脚本：`reporting/create_internet_line_ppt.js`。由主入口调用，不要单独运行；使用 PptxGenJS 创建 16:9、微软雅黑主题的 16 页完整月报。
- 辅助导出：`reporting/export_complaint_results.py`。只在需要核对已选中的投诉类指标结果时运行，不是生成 PPT 的必需步骤。
- 默认底板：`reporting/templates/通用模板.pptx`。`--background-mode ppt` 时由主入口应用其母版、版式和主题。
- 图片底板：`reporting/templates/template_background_image1.jpeg`。仅在 `--background-mode image` 时使用，此模式不能同时传 `--template`。
- 终端回收模板：`reporting/templates/终端回收页模版.pptx`。主入口存在该文件时会用其内容替换完整稿第 12～13 页并更新图表缓存和文本。
- `reporting/templates/撤退单模版.pptx` 当前没有被主入口引用；不要假设修改它会改变生成结果。

## 月份与输入

- `--month` 必须是 `YYYY-MM`。用户未显式指定月份时，从当前对话中的月报时间提取年月；对话中无法确定时先询问，不得使用系统当前月份猜测。
- 默认数据库是项目根目录下的 `data/quality_assessment.db`，也可用 `--database` 指定其他 SQLite 文件。
- 当前主流程只读取数据库，不读取 `reporting/data_sources/专线产品情况_*.xlsx`；代码中的 `DEFAULT_INPUT` 和 `default_input` 目前未参与生成。
- 数据库读取使用只读连接，生成月报不得改写源指标数据。

## 数据就绪要求

完整月报主要依赖以下成功指标批次：

- `orchestration_opening_metrics`：业务发展量、12 个月趋势和互联网专线开通/移机/拆机自动率。
- `terminal_recovery`：终端回收城市、设备和业务维度。
- `dedicated_line_opening_withdrawal_rate`：开通撤退单率。
- `dedicated_line_repeat_complaint_rate`、`qianliyan_repeat_complaint_rate`：重复投诉率。
- `dedicated_line_install_fault_rate`、`qikuan_install_fault_rate`、`commercial_customer_install_fault_rate`：新装报障率。

选择规则：指标批次必须为 `status=success` 且 `period_end` 等于月报月末。普通月度指标优先精确覆盖月初至月末；投诉和新装报障类支撑指标允许选择以该月月末结束的最近成功周期，并在页面显示实际统计周期；编排趋势结果允许较早的 `period_start`，但必须包含目标月需要的月份维度。

缺失、空值或非有限数会被程序填为 0，而不是让构建失败，并记录到审计文件。生成前后都要核对指标批次；不得仅凭 PPTX 文件存在就宣称数据完整。

## 运行前检查

1. 在包含 `pyproject.toml`、`reporting` 和 `data` 的项目根目录执行。
2. 确认数据库、所选模板、`reporting/create_internet_line_ppt.js` 和终端回收模板存在。
3. 使用安装了项目 Python 依赖的 Python 3.10+；至少需要 `pandas` 和 `openpyxl`。
4. 确认 Node.js 可执行文件存在，并且主脚本解析到的 `NODE_MODULES` 中可加载 `pptxgenjs`。项目本地 `reporting/node_modules` 优先；否则使用脚本配置的运行时路径。缺失时报告依赖问题，不把 Node 错误误判为数据问题。
5. 可先运行 `python3 reporting/build_internet_line_ppt.py --help` 检查 Python 入口和参数解析。

## 生成命令

生成完整月报：

```bash
python3 reporting/build_internet_line_ppt.py \
  --month 2026-08 \
  --database data/quality_assessment.db
```

默认输出：

```text
outputs/monthly_report/互联网专线产品开通情况_2026年8月.pptx
outputs/monthly_report/互联网专线产品开通情况_2026年8月.audit.json
```

指定输出、模板或保留中间 JSON：

```bash
python3 reporting/build_internet_line_ppt.py \
  --month 2026-08 \
  --database data/quality_assessment.db \
  --output outputs/monthly_report/互联网专线产品开通情况_2026年8月.pptx \
  --background-mode ppt \
  --template reporting/templates/通用模板.pptx \
  --keep-json
```

默认会删除与 PPT 同名的中间 `.json`；`.audit.json` 始终保留。

## 完整稿与章节稿

不传 `--section` 时生成 16 页完整稿。需要单独章节时只允许以下值：

| 章节 | 保留的原始页 | 结果页数 |
| --- | --- | --- |
| `业务发展情况` | 1、2、3、4、5、6 | 6 |
| `专线自动情况` | 1、2、8、9、10 | 5 |
| `终端回收情况` | 1、2、12、13 | 4 |
| `业务支撑情况` | 1、2、15、16 | 4 |

示例：

```bash
python3 reporting/build_internet_line_ppt.py \
  --month 2026-08 \
  --section 业务支撑情况 \
  --output outputs/monthly_report/业务支撑情况_2026年8月.pptx
```

章节模式仍会先构建完整数据模型和完整 PPT，再按原始页码裁剪；审计文件可能包含其他章节的已知占位缺失，判定时只关注所选章节使用的数据。

## 辅助结果导出

需要核对数据库实际选择的投诉指标批次和结果时：

```bash
python3 reporting/export_complaint_results.py \
  --month 2026-08 \
  --database data/quality_assessment.db \
  --output-dir outputs/monthly_report/complaint_audit
```

不传 `--metric` 时导出千里眼和专线重复投诉率；可用 `--metric` 单独选择 `qianliyan_repeat_complaint_rate`、`dedicated_line_repeat_complaint_rate` 或 `commercial_customer_install_fault_rate`。该脚本只导出已存结果 JSON，不会重新计算指标。

## 构建后处理

主入口在 Node 生成后依次执行：应用通用模板母版、修正多系列地市图数据标签颜色、格式化撤退单率折线、格式化投诉与新装报障组合图、用专用模板替换终端回收第 12～13 页，最后按需裁剪章节。任一步失败都应视为整个 PPT 构建失败，不交付半成品。

## 验证

1. 命令退出为 0，PPTX 和 `.audit.json` 均存在；保留中间 JSON 时还应存在同名 `.json`。
2. PPTX 是可正常解压的 Office 文件，完整稿有 16 页；章节稿页数与上表一致。
3. 检查 `.audit.json` 的 `selected_batches`、`used_results` 和 `missing`：所需指标批次月份正确，所选章节不得有未解释的 `missing_result` 或 `null_or_nonfinite_value`。
4. `reason=no_corresponding_stored_result` 表示当前映射明确没有对应落库结果并以 0 占位；包括部分终端装维单位、撤退原因和重复投诉合计字段。必须向用户披露相关页面存在占位，不能把 0 表述为真实业务值。
5. 渲染 PPTX 进行视觉检查：母版和背景正确、标题月份正确、中文字体为微软雅黑、图表未溢出或遮挡、百分比和正负方向正确，第 12～13 页确实采用终端回收模板。
6. 若只生成章节稿，确认保留页顺序与原始页码一致，页脚数字保持原稿编号属于预期行为。

## 失败处理与边界

- 找不到数据库或模板：修正路径后重试，不创建空数据库或空模板。
- 找不到 Node 或 `pptxgenjs`：先解决运行时依赖；不要跳过 Node 绘图或提交空 PPTX。
- 找不到成功指标批次：先运行对应计算 skill，或向用户报告缺少的指标和周期；不要在 reporting 层从原始表临时重算。
- 审计出现未解释的数据缺失：停止交付并列出缺失项。只有用户明确接受占位值时才继续使用该稿。
- 不删除数据库、模板或既有输出，不覆盖用户指定文件之外的产物。
