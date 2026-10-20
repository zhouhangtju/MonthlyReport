# 企宽装机报结量（地市、区县）

独立于 `fetch_install.py` 的派单明细链路。入口为 `fetch_install_completed.py`，
共用已有登录配置和 `fetch_data.run_export` 导出能力，不使用旧任务列表、按日拆批或旧明细入库器。

## 口径

- 报表 38598，看板 136752；日期筛选为 `OPERTIME`（当前状态时间）。
- 保留抓包的工单类型 1、宽带类型 `1` 或 `企业宽带` 筛选。
- 指标为符合条件的 `ORDERID` 去重计数。
- 地市组件 `c-3RyRNeFPPpeMKBjJQA69rz`；区县组件 `c-pYQPgF1TfDX2VsNYSXjeXe`。
- 每个完整查询周期导出两份文件。月度、累计必须分别查询，不将分段去重数相加。
- 起止日期均包含当天，沿用平台抓包的 `00:00:00` 至末日 `24:00:00` 表达。
- 不从文件名推断统计周期；离线文件的周期必须由调用者确认并提供。

## 使用

在项目根目录执行（部署依赖沿用 `requirements.txt`）：

```bash
python3 collector/youshu/fetch_install_completed.py \
  --start-date 2026-08-01 --end-date 2026-08-31 --mode both
```

需要刷新登录时增加 `--login-first`。登录认证沿用本目录的 `有数配置.json`，
代码模板不包含抓包请求头或凭证。在线取数需要可访问有数内网及有效登录。
此入口通过 `YOUDATA_REPORT_URL` 指定报表 38598，让自动登录脚本进入本次目标报表后
重新捕获会话；未指定该环境变量时，其他旧入口继续使用原有报表选择规则。

导出失败会将阶段（`flushReport`、`setCache`、`exportExcel`、`download`、`timeout`）、
HTTP 状态和平台错误码写入异常及失败 manifest。`610` 或 `401/403` 需要检查登录和权限；
`timeout` 表示在等待时间内未获得文件。任务列表回退只接受当前导出 ID 对应的任务，
不会直接采用列表第一条其他任务的文件。没有平台实际响应时，不能仅凭通用异常判断根因。

离线导入两份已下载文件：

```bash
python3 collector/youshu/fetch_install_completed.py \
  --start-date 2026-08-01 --end-date 2026-08-31 \
  --city-file /path/to/city.xlsx --county-file /path/to/county.xlsx \
  --mode both
```

上述日期仅为命令示例；手工导出文件须确认查询周期后再入库。

| 参数 | 说明 |
|---|---|
| `--mode file` | 保存原始文件和 manifest，执行校验，不连接数据库 |
| `--mode both` | 默认；保留原始文件、manifest，同时入库 |
| `--mode database` | 临时下载、校验和入库；成功后清理临时文件，失败保留诊断目录 |
| `--output-dir` | 默认项目下 `data/raw/youshu`；相对路径按项目根目录解释 |
| `--refresh` | 绕过相同周期覆盖检查，创建新的快照批次 |
| `--timeout` / `--poll-timeout` | 默认 120 / 600 秒 |
| `--city-file` / `--county-file` | 必须成对提供；无需认证或 requests 即可离线解析 |

该入口有意不提供 `--chunk-days`。`both`/`database` 在相同周期已经完整入库时跳过；
`file` 总是重新生成文件。两张业务表作为成对快照维护，不注册到通用工单明细数据集，
不要通过 `storage/import_data.py` 导入它们。

## 原始文件目录

```text
data/raw/youshu/install_completed/
  <开始日期>_<结束日期>/
    <采集批次ID>/
      city/*.xlsx
      county/*.xlsx
      manifest.json
```

原文件包含总计行，保持原样。manifest 记录周期来源、报表和组件 ID、
文件 SHA256、地区行数、平台总计、校验状态、ETL ID。
`database` 模式的临时路径在成功后不再可用；文件校验值和来源路径仍在 ETL 审计中保留。
需要原文件追溯时使用默认 `both` 模式。

## MySQL 初始化

既有数据库必须先具有项目共享审计表 `collection_run`、`etl_run`。
新入口在数据库模式下会自动执行仅包含两张新表的幂等建表脚本，不运行旧表迁移。
也可先手工执行：

```bash
mysql --default-character-set=utf8mb4 -u root -p quality_assessment \
  < sql/create_youshu_install_completed.sql
```

全新数据库使用项目原有初始化流程；`sql/schema.sql` 已包含相同的新表定义。

- `youshu_install_completed_city`：每批次、周期、地市一条。
- `youshu_install_completed_county`：每批次、周期、地市、区县一条。
- 数量使用 `BIGINT UNSIGNED`，起止日期使用 `DATE`；采集时间保存带 UTC 时区的 ISO 字符串。
- 每次强制重取保留新批次，无需额外版本表。
- 同批次、相同源文件重复导入幂等；已成功批次不允许更换源文件。
- 两张业务表、两条 ETL 成功记录和采集成功标记在同一事务内提交。

读取同周期最新完整快照：

```python
from storage.youshu_install_completed import load_latest
data = load_latest("2026-08-01", "2026-08-31")
# data['city']、data['county'] 来自同一 collection_run_id。
province_total = sum(row['completed_order_count'] for row in data['city'])
```

不得直接对历史所有批次求和。全年汇总不能覆盖单月汇总，覆盖判断仅匹配完全相同的起止日期。

## 校验与失败处理

1. 必须为单工作表，表头严格匹配地市或区县结构。
2. 数量必须为非负整数；空值、公式、布尔值、非数字、超出 BIGINT 的值拒绝。
3. 地市覆盖必须为浙江 11 地市；地区重复、空区县拒绝。区县数量不固定写死为 90。
4. 原始区县名称保持不变，如“嘉禾”“绍兴县”；不替换为行政区名称。
5. 必须有唯一平台总计，且与明细合计相同；总计不写入业务表。
6. 区县分地市合计必须与地市文件逐项一致；两份平台总计必须相同。
7. 任一下载、解析、校验或入库失败，整批不标成功，保留文件和 manifest；数据库写入失败回滚两表。
8. 当前全省完整性策略会拒绝缺失地市，即使缺失可能代表零，也不会自动补零。

## 验证

```bash
python3 -m unittest tests.test_youshu_install_completed tests.test_youshu_export_flow -v
```

测试覆盖完整周期双导出、解析校验、失败审计、事务回滚、重复入库、精确周期覆盖和最新快照。
单元测试使用隔离的 SQLite 事务替身，不连接实际 MySQL；不代表已完成内网接口或 MySQL 联调。
