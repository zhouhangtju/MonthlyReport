# 专线业务发展与自动率文件模块

只新增本目录代码，不修改省级/地市月报入口。按已结束的完整自然月执行；不生成PPT，不写入MySQL。目录名daily不代表月初至昨天。

## 线上部署

将整个 `metrics/opening/daily` 目录复制到线上项目同一位置。依赖当前项目已有的 `metrics/opening`、`metrics/opening/bycity`、`collector/orchestration/client.py`、`storage/importer.py` 等模块，不能单独把本目录移出项目运行。

新增生产脚本7个：run_opening.py、load_history.py、calculate_development.py、calculate_automation.py、backfill_process_logs.py、split_evidence.py、export_results.py。test_simulation.py是可选模拟测试文件。本README为部署说明。

Python依赖沿用项目requirements：openpyxl、pymysql、requests，传统xls另需xlrd。MySQL连接使用原项目storage/database.py配置，但本模块不调用initialize，历史查询使用只读一致性事务，结束时rollback。

准备：

- 编排系统取数凭证按现有方式设置GDDL_ZYTOKEN/GDDL_COOKIE；这是编排凭证，与自动率流程日志Cookie不同。
- 当月资管CSV：必须包含二级编排工单号、环节名称、结束时间、处理人、处理意见。
- 区县映射：默认metrics/terminal_recovery/区县信息汇总.xlsx，支持--county-map指定；包含地市、区县、标准区县，覆盖11地市。
- 流程日志Cookie：默认metrics/opening/cookie.txt，支持--cookie-file指定。有效Cookie配--use-existing-cookie直接读取；不指定该开关时调用既有短信登录脚本更新默认Cookie。
- 业务发展历史数据：MySQL的orch_opening_monthly_summary或orch_opening。所需范围为报告月前12个月；加当月共13个月，可覆盖同比、12个月趋势和环比。

## 命令（项目根目录）

两个模块：

```text
python metrics/opening/daily/run_opening.py --file --month 2026-10 --asset-csv "data/offline_data/2026-10/资管环节明细.csv" --use-existing-cookie
```

仅业务发展（不需要资管和日志Cookie）：

```text
python metrics/opening/daily/run_opening.py --file --month 2026-10 --section development
```

仅自动率（不连接MySQL）：

```text
python metrics/opening/daily/run_opening.py --file --month 2026-10 --section automation --asset-csv "data/offline_data/2026-10/资管环节明细.csv" --use-existing-cookie
```

更新默认日志Cookie：

```text
python metrics/opening/login_save_cookie.py
```

附加参数：--output-dir指定根目录；--cookie-file指定已有Cookie（需同时--use-existing-cookie）。默认输出D:/dev-projects/openclaw_data/outputs/opening。

## 输出

```text
opening/
  raw/orchestration/                      最新成功批次原始取数文件
  evidence/日期_批次/
    raw/orchestration/                    原文件副本
    raw/已清洗/全省_编排工单.xlsx         保留原字段，新增标准地市、标准区县、清洗依据
    raw/已清洗/地市/地市名/编排工单.xlsx
    references/                           本批资管CSV、区县映射
    history/                              实际使用的历史汇总或原始JSONL及history.json
    logs/                                 每个查询的流程日志和回填审计，不含Cookie
    业务发展/全省_业务发展中间结果.xlsx
    业务发展/地市/地市名/业务发展中间结果.xlsx
    专线自动情况/全省_专线自动率中间结果.xlsx
    专线自动情况/地市/地市名/专线自动率中间结果.xlsx
    manifest.json                         批次、口径、缺失情况、文件哈希
  results/日期_批次/
    业务发展/省级/全省.xlsx及json
    业务发展/地市/杭州.xlsx及json等11地市
    专线自动情况/省级/全省.xlsx及json
    专线自动情况/地市/杭州.xlsx及json等11地市
    manifest.json
  failed/日期_批次/                       失败批次证据，不发布正式结果
```

每个地市结果工作簿为一张长表：表头下先列地市各指标，随后列该市各区县指标；不另建区县Excel。JSON同样包含city/county维度。指标值是数值（比率如0.95表示95%），保留分子、分母。业务发展是现有三类专线，不包括企宽、点金行动。

## 口径与质量

- 业务发展复用summarize_month、calculate_month_batches、CityVolumes，历史缺失的趋势、同比环比及滚动指标置空并审计，不按0冒充。完整历史汇总优先，不足才按订单号分页读取历史原始表。读到0条且无完整汇总，视为未知，不断言真实零单。
- 现有规则下，互联网全省总量含未列名产品，地市产品汇总只含列名产品；不能要求二者无条件相等。中间表“产品在统计范围”可核验此差异。
- 区县标准化沿用业务发展规则：限定地市映射，原区县精确/关键字，再主题关键字。保留未归属区县。统计本身沿用原代码地市名称要求（杭州市等）；标准地市字段供拆分核验，不擅自改变原字段口径。
- 自动率复用资管最新结束时间匹配、相同时间最后CSV行优先、路径填/、aggregate与aggregate_stop_resume。地市及区县直接复用city_automation，通过只读文件适配器提供已回填中间表，不访问MySQL。
- 全省日志仅查一次，再拆分地市。自动标识为现有“包含自动”，不启用暂停的非自动原因改造。
- 日志查询成功但无订单或无环节按既有规则填/；明确空处理人仍留空。接口技术失败保留失败证据，整批不发布。查询仍受现有90天及账号可见范围限制。
- status=completed表示本模块执行完整；completed_with_gaps表示历史或日志有缺口。即使completed，也应核验no_data_orders以及资管匹配情况。
- 原始文件、中间文件保存完整字段；自动率source_payload和asset_matches用于审计与现有规则复用。Excel单元格超过32767字符时明确报错，不静默截断。
- .lock防止并发覆盖；全部计算成功后发布本批结果并替换raw；已有evidence/results批次保留。失败批次不覆盖旧结果。

## 离线模拟与重放

```text
python -m metrics.opening.daily.test_simulation
```

测试人工构造223行当期数据、12个月历史和模拟日志，覆盖11地市、四类业务、开通/移机/拆除/停机/复机、重复订单、未列名产品、未归属区县、缺历史、接口失败和只读历史查询。不是生产数据准确性认证，也不验证真实线上接口可用性。

可用--input-dir指定仅含本月编排原文件的目录，替代在线取数；用--history-file指定已归档history.json替代MySQL查询。它们是重放输入，manifest标记replay。不要把含中间表或别的月份的目录当输入。

--skip-process-log只用于离线核验，会显式标记日志未完成。全省和地市结果不会写回现有数据库。
