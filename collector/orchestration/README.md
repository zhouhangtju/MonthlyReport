# 编排系统取数说明

## 1. 模块用途

本模块从编排系统获取两类数据：

1. 专线开通情况；
2. 互联网专线新装单。

取数后支持两种数据形态：

- 保存原始 Excel 文件，供人工核查和留档；
- 将 Excel 中的数据写入 MySQL，供后续指标计算。

默认使用 `both` 模式，即同时保留文件并入库。

本模块由 `export/编排` 中已经验证过的脚本迁移而来。所有运行逻辑均已写入 `collector/orchestration/`，运行、发布和打包不依赖原 `export` 目录；原路径只用于追溯迁移来源。

## 2. 文件说明

```text
collector/orchestration/
├── README.md           本说明
├── client.py           公共接口请求、日期分批、文件校验及入库衔接
├── fetch_opening.py    专线开通情况取数入口
└── fetch_install.py    互联网专线新装单取数入口
```

两个入口脚本共用 `client.py`，避免日期切分、认证、下载和错误处理逻辑重复。

## 3. 数据集与主键

| 数据集 | 脚本 | 数据集编码 | 入库主键 | 主要用途 |
|---|---|---|---|---|
| 专线开通情况 | `fetch_opening.py` | `orch_opening` | `订单号` | 开通量、同比环比、产品和地市分布、自动率等 |
| 互联网专线新装单 | `fetch_install.py` | `orch_install` | `订单号` | 专线新装报障率的分母及新装时间、地市来源 |

两类数据按 XLSX 表头逐列写入 `orch_opening`、`orch_install`，主键均为“订单号”。审计和历史版本另表保存，算数直接读取原始表，不再维护 ODS 副本或执行历史补写。

专线开通指标按“订单结束时间”筛选；互联网专线新装报障率继续使用原始表中的“订单创建时间”等字段，计算口径不变。

`产品实例编号`不是记录主键。它用于将互联网专线新装单与 EOMS 投诉工单的计费号码进行关联。

## 4. 运行环境

要求：

- Python 3.10 或更高版本；
- 能访问编排系统内网地址；
- Python 包：`requests`、`openpyxl`。

进入项目根目录：

```bash
cd "/Users/hzhou/Desktop/政企/projects/qualityAssessment/quality-assessment-pipeline"
```

首次安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

以后运行前：

```bash
cd "/Users/hzhou/Desktop/政企/projects/qualityAssessment/quality-assessment-pipeline"
source .venv/bin/activate
```

## 5. 认证信息

脚本支持 `zytoken` 和 Cookie。优先级为：

1. 命令行参数 `--zytoken`、`--cookie`；
2. 环境变量 `GDDL_ZYTOKEN`、`GDDL_COOKIE`；
3. 不携带认证信息直接请求。

推荐使用环境变量：

```bash
export GDDL_ZYTOKEN="实际 token"
export GDDL_COOKIE="实际 Cookie"
```

不要把 Token 或 Cookie 写入 README、Python 文件、Git 仓库或运行日志。

如果当前接口不要求认证，可以不设置这两个环境变量。

## 6. 获取专线开通情况

### 6.1 同时保存文件并入库

```bash
python3 collector/orchestration/fetch_opening.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

默认输出位置：

```text
data/raw/orchestration/orch_opening/
```

文件名示例：

```text
专线工单_2026-08-01_2026-08-03.xlsx
```

### 6.2 只保存文件

```bash
python3 collector/orchestration/fetch_opening.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode file
```

### 6.3 只入库

```bash
python3 collector/orchestration/fetch_opening.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode database
```

只入库模式会先把文件下载到临时目录，成功入库后清理临时文件。

## 7. 获取互联网专线新装单

### 7.1 同时保存文件并入库

```bash
python3 collector/orchestration/fetch_install.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

默认输出位置：

```text
data/raw/orchestration/orch_install/
```

文件名示例：

```text
互联网专线新装单_2026-08-01_2026-08-03.xlsx
```

### 7.2 只保存文件

```bash
python3 collector/orchestration/fetch_install.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode file
```

### 7.3 只入库

```bash
python3 collector/orchestration/fetch_install.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode database
```

## 8. 参数说明

两个脚本使用相同的运行参数：

| 参数 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `--start-date` | 是 | 无 | 开始日期，格式为 `YYYY-MM-DD` |
| `--end-date` | 是 | 无 | 结束日期，格式为 `YYYY-MM-DD`，包含当天 |
| `--mode` | 否 | `both` | `file`、`database` 或 `both` |
| `--output-dir` | 否 | `data/raw/orchestration` | 文件输出根目录 |
| `--database` | 否 | 可省略 | 兼容旧命令；MySQL 连接信息写在 `storage/database.py` |
| `--chunk-days` | 否 | `3` | 每个下载批次包含的自然日数 |
| `--interval` | 否 | `2` | 相邻批次之间等待的秒数 |
| `--timeout` | 否 | `180` | 单次请求超时秒数 |
| `--refresh` | 否 | 关闭 | 忽略数据库已有周期和已有文件，强制重新拉取 |
| `--overwrite` | 否 | 关闭 | `--refresh`的兼容别名，作用相同 |
| `--zytoken` | 否 | 环境变量 | 临时指定编排 Token |
| `--cookie` | 否 | 环境变量 | 临时指定 Cookie |

查看完整参数：

```bash
python3 collector/orchestration/fetch_opening.py --help
python3 collector/orchestration/fetch_install.py --help
```

## 9. 日期分批规则

开始、结束日期均为闭区间。默认每 3 天一个批次，批次连续且不重叠。

例如：

```text
开始日期：2026-08-01
结束日期：2026-08-08
批次天数：3
```

将拆分为：

```text
2026-08-01 ～ 2026-08-03
2026-08-04 ～ 2026-08-06
2026-08-07 ～ 2026-08-08
```

如接口压力较大，可以缩小批次并增加间隔：

```bash
python3 collector/orchestration/fetch_opening.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --chunk-days 1 \
  --interval 5 \
  --mode both
```

## 10. 接口取数口径

### 10.1 公共参数

两类取数均使用：

```text
isExplortConfRsult = 0
status             = 1
service_catalog    = ProvGCDedicatedLine
page               = 1
limit              = 10
is_child           = 0
```

这里的 `limit=10`沿用原有导出接口请求参数。接口返回的是导出文件，不代表只导出 10 条数据。

### 10.2 专线开通情况

接口：

```text
GET /soc/export/order/submittedZj/download/tzzhanglifeng
```

日期字段：

```text
finish_start_time
finish_end_time
```

即按原脚本中的完成时间范围导出专线工单。

### 10.3 互联网专线新装单

接口：

```text
GET /soc/export/order/submittedZj/download/sundongchuan
```

额外筛选：

```text
order_type  = 2
service_type = ProvInternetLine
```

日期字段：

```text
start_time
end_time
```

这两个参数对应新装单的派单时间范围。

## 11. 文件校验与重复运行

脚本下载响应后会检查：

- 内容不能为空；
- 文件头或响应类型必须能识别为 Excel；
- 下载过程先写入 `.part` 临时文件；
- 下载成功后才替换为正式 `.xlsx` 文件；
- 请求或写入失败时删除残留 `.part` 文件。

这样可以避免把登录页、错误 JSON 或半截文件当作正式数据。

如果目标文件已经存在：

- 默认跳过网络下载；
- `file` 模式直接保留现有文件；
- `both` 模式仍会将现有文件执行幂等入库；
- 使用 `--refresh` 才会强制重新下载。

如果运行模式包含数据库，脚本还会在下载前检查 ETL 批次：

- 同一数据集已有成功批次；
- 已有批次的日期并集完整覆盖本次日期；
- 已有批次的失败行数为 0。

同时满足以上条件时，不再请求编排接口，返回：

```json
{
  "downloaded": false,
  "skipped": true,
  "skip_reason": "database_already_covered"
}
```

多个历史批次可以共同组成完整覆盖。例如已有 `8月1日至15日`和`8月16日至31日`两个成功批次，再请求完整 8 月时也会跳过。

如果数据库只覆盖部分日期，脚本仍会处理未覆盖日期所在的分段。日期下载以 `chunk-days`为最小批次，因此可能重新获取该分段中少量已经覆盖的日期，入库时会自动去重。

## 12. 数据库写入规则

数据库内部使用自增 `record_id`，编排两类数据的源记录主键均为 `订单号`。

重复导入时：

- 新订单号：记为 `inserted`；
- 订单号相同、整行内容相同：记为 `unchanged`；
- 订单号相同、内容发生变化：记为 `updated`，更新当前版本并保留历史版本；
- 订单号为空：记为 `failed`，不写入业务记录。

每个日期分段产生一个 ETL 批次，记录源文件、文件哈希、周期、读取行数、新增数、更新数、未变化数、失败数及执行状态。

## 13. 返回结果

脚本结束后在终端输出 JSON。每个分段包含：

```json
{
  "start": "2026-08-01",
  "end": "2026-08-03",
  "file": "原始文件绝对路径",
  "downloaded": true,
  "etl": {
    "run_id": "etl_...",
    "read": 1000,
    "inserted": 900,
    "updated": 20,
    "unchanged": 80,
    "failed": 0
  }
}
```

其中：

- `downloaded=true`表示本次从接口重新下载；
- `downloaded=false`表示使用了已有同名文件；
- `file`在 `database` 模式下为 `null`；
- `etl`在 `file` 模式下为 `null`。

## 14. 常见错误

### 日期格式错误

日期必须使用：

```text
YYYY-MM-DD
```

开始日期不能晚于结束日期。

### 接口未返回 Excel

可能原因：

- Token 或 Cookie 已失效；
- 当前网络无法访问编排内网；
- 接口返回登录页面或错误信息；
- 接口地址或权限发生变化。

先更新认证信息，再使用较短日期范围重试。不要直接把错误响应改名为 Excel。

### 请求超时

可以缩小批次或增加超时时间：

```bash
python3 collector/orchestration/fetch_opening.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --chunk-days 1 \
  --timeout 300 \
  --mode both
```

### 数据库已有数据或文件存在，但需要重新获取

增加：

```text
--refresh
```

### 缺少依赖

在项目根目录执行：

```bash
python3 -m pip install -r requirements.txt
```

## 15. 后续封装为 Skill 时的调用规则

后续把本模块制作成 Skill 时，建议 Skill 只负责识别用户意图、补齐参数并调用已有脚本，不复制 `client.py` 的业务逻辑。

### 15.1 脚本选择

| 用户意图 | 调用脚本 |
|---|---|
| 获取专线开通情况、专线开通工单、编排工单 | `fetch_opening.py` |
| 获取互联网专线新装单、为专线新装报障率准备分母 | `fetch_install.py` |
| 两类都获取 | 按相同周期依次运行两个脚本 |

### 15.2 必须明确的参数

Skill 在执行前至少需要得到：

- 开始日期；
- 结束日期；
- 存储模式。

若用户没有指定存储模式，可默认使用 `both`。

若用户只说“上个月”，Skill 应先根据执行环境日期计算完整自然月，再把明确的起止日期传给脚本。

### 15.3 默认行为

建议 Skill 使用以下默认值：

```text
mode       = both
chunk-days = 3
interval   = 2
timeout    = 180
refresh    = false
```

不要默认使用 `--refresh`。已有文件可能是人工核验过的留档，只有用户明确要求重新下载或确认文件异常时才覆盖。

### 15.4 执行后的检查

Skill 应检查：

1. 脚本退出状态是否成功；
2. 期望日期是否全部拆分并生成结果；
3. 文件模式下每个返回路径是否存在；
4. 数据库模式下每个分段是否都有 `run_id`；
5. `failed`是否为 0；
6. 跳过时 `skip_reason`是否为 `database_already_covered`；
7. `read`是否明显异常，例如整月全部为 0；
8. 是否有接口未返回 Excel、认证失效或超时提示。

### 15.5 Skill 不应做的事

- 不在 Skill 中保存明文 Token 或 Cookie；
- 不直接修改接口固定筛选参数；
- 不绕过 Excel 响应校验；
- 不把 `产品实例编号`改成数据库主键；
- 不删除原始文件；
- 不在未确认的情况下使用 `--refresh`覆盖已有文件和刷新数据库；
- 不在 Skill 内另写一套日期切分或入库逻辑。

## 16. 原脚本映射

| 历史来源（非运行依赖） | 当前项目入口 |
|---|---|
| `export/编排/专线开通情况/order_data_fetcher_v5.py` | `collector/orchestration/fetch_opening.py` |
| `export/编排/互联网专线新装报障率-专线新装单/internet_line_install_fetcher.py` | `collector/orchestration/fetch_install.py` |

公共能力统一放在：

```text
collector/orchestration/client.py
```

原脚本作为迁移来源和历史对照保留，新脚本作为后续运行及 Skill 调用入口。
