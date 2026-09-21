# 有数平台取数说明

## 1. 模块用途

本模块获取两类数据：

| 数据 | 数据集编码 | 主键 | 指标用途 |
|---|---|---|---|
| 企宽新装单 | `youshu_install` | `工单id` | 企宽新装报障率分母及新装时间 |
| 企宽投诉单 | `youshu_complaint` | `工单号` | 企宽新装报障率投诉匹配来源 |

本模块已将原 `export/有数平台` 中开发完成的登录、看板参数和异步导出逻辑迁入项目。运行时只使用 `collector/youshu/` 内的文件，不依赖原 `export` 目录，因此项目单独打包后仍可运行。

## 2. 文件结构

```text
collector/youshu/
├── README.md             本说明
├── client.py             调用本地取数脚本、检查文件完整性并衔接入库
├── refresh_login.py      调用youdata_autologin.js刷新登录配置
├── fetch_install.py      企宽新装单入口
├── fetch_complaints.py   企宽投诉单入口
├── fetch_data.py         有数异步导出实现
├── youdata_autologin.js
├── youdata_login.example.json
├── youdata_login.json    实际登录配置，不提交版本库
├── 有数配置.json         运行期认证配置，不提交版本库
├── task2_setcache.json
├── task3_setcache_44677.json
├── task3_summary_setcache_44677.json
└── task4_setcache.json
```

`youdata_login.json`和`有数配置.json`可能包含敏感信息，不要提交、复制到README或输出到日志。

## 3. 环境要求

- Python 3.10或更高版本；
- Node.js 22或更高版本；
- Microsoft Edge或Google Chrome；
- 能访问有数平台内网；
- Python依赖见项目根目录 `requirements.txt`。

```bash
cd "/Users/hzhou/Desktop/政企/projects/qualityAssessment/quality-assessment-pipeline"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## 4. 刷新登录

先确保以下文件已正确配置：

```text
collector/youshu/youdata_login.json
```

然后运行：

```bash
python3 collector/youshu/refresh_login.py
```

该脚本实际调用：

```bash
node collector/youshu/youdata_autologin.js
```

自动登录脚本会启动或复用带CDP端口的Edge/Chrome，登录有数平台，进入企宽报告页，监听真实API请求，并把最新的Cookie、CSRF、roomid和sid写回：

```text
collector/youshu/有数配置.json
```

如果浏览器不在标准路径，可设置：

```bash
export YOUDATA_BROWSER="浏览器可执行文件绝对路径"
python3 collector/youshu/refresh_login.py
```

## 5. 获取企宽新装单

### 5.1 推荐运行方式

```bash
python3 collector/youshu/fetch_install.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both \
  --two-phase
```

企宽新装单默认：

- 每3天一个日期批次；
- 每个日期批次按11个地市分别导出；
- 设置企宽类型筛选；
- 文件保存到 `data/raw/youshu/youshu_install/`；
- 每个文件按 `工单id`入库。

一个31天月份按3天切片时，预期生成：

```text
11个日期批次 × 11个地市 = 121个文件
```

`--two-phase`会先创建全部导出任务，再依次下载，适合导出任务较多的场景。

### 5.2 登录后立即取数

```bash
python3 collector/youshu/fetch_install.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both \
  --two-phase \
  --login-first
```

`--login-first`会先运行 `youdata_autologin.js`，刷新成功后再取数。

## 6. 获取企宽投诉单

```bash
python3 collector/youshu/fetch_complaints.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both \
  --two-phase
```

企宽投诉单默认每3天一个日期批次，不按地市拆分。31天月份预计生成11个批次文件。

`fetch_data.py`可能另外生成一个带“合并”字样的Excel。数据库入库使用各批次原始文件，不重复导入合并文件。

## 7. 存储模式

| 模式 | 文件 | 数据库 |
|---|---|---|
| `file` | 保留 | 不入库 |
| `database` | 使用临时目录，成功后清理 | 入库 |
| `both` | 保留 | 入库 |

默认模式为 `both`。

文件目录：

```text
data/raw/youshu/youshu_install/
data/raw/youshu/youshu_complaint/
```

## 8. 参数说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--start-date` | 必填 | 开始日期，格式 `YYYY-MM-DD` |
| `--end-date` | 必填 | 结束日期，包含当天 |
| `--mode` | `both` | `file`、`database`或`both` |
| `--output-dir` | `data/raw/youshu` | 文件输出根目录 |
| `--database` | 可省略 | 兼容旧命令；MySQL 连接信息写在 `storage/database.py` |
| `--chunk-days` | `3` | 每个日期批次天数 |
| `--interval` | `0.5` | 提交任务之间的等待秒数 |
| `--timeout` | `120` | 普通HTTP请求超时秒数 |
| `--poll-timeout` | `600` | 等待异步导出文件的总秒数 |
| `--two-phase` | 关闭 | 先生成全部exportId，再统一下载 |
| `--login-first` | 关闭 | 取数前先刷新登录配置 |
| `--refresh` | 关闭 | 忽略数据库已有周期并重新取数 |
| `--node` | `node` | Node.js可执行文件 |
| `--python` | 当前Python | 调用项目内 `fetch_data.py`的Python |

## 9. 取数流程

公共流程为：

```text
读取有数配置.json
  ↓
刷新看板flushReport
  ↓
修改日期、地市和企宽类型筛选
  ↓
调用setCache生成tempQueryId
  ↓
调用exportExcel生成exportId
  ↓
轮询exportExcelTask/download
  ↓
验证完整XLSX结构
  ↓
保存文件并入库
```

企宽新装单的日期通过看板参数字段注入，并按11个地市循环导出。企宽投诉单通过日期筛选组件注入统计周期。

## 10. 完整采集标识

有数一次取数会产生多个文件，不能用其中某个文件的ETL成功记录代表整月完整。

因此增加 `collection_run`整次采集记录，保存：

- 数据集；
- 统计周期；
- 预期文件数；
- 实际生成文件数；
- 成功入库文件数；
- 所有源文件；
- 所有ETL `run_id`；
- 整次采集状态和错误。

只有所有预期文件生成并全部入库后，才把该周期标记为成功覆盖。

再次请求相同周期时，如果数据库已完整覆盖，将返回：

```json
{
  "skipped": true,
  "skip_reason": "database_already_covered"
}
```

使用 `--refresh`可强制重新取数。

## 11. 文件完整性检查

包装脚本在项目内 `fetch_data.py`运行前后比较文件列表，并检查本次新增文件数量：

- 企宽新装单：日期批次数 × 11个地市；
- 企宽投诉单：日期批次数 × 1。

文件数量不足时，整次采集标记为失败，不会错误地标记数据库已覆盖该月。

## 12. 入库规则

### 企宽新装单

- 主键：`工单id`；
- `宽带账号`用于关联投诉，不是主键；
- 一个账号允许有多张新装工单。

### 企宽投诉单

- 主键：`工单号`；
- `客服流水号`和`宽带账号`允许重复；
- `宽带账号`用于与企宽新装单匹配。

同一主键重复导入时，内容相同记为 `unchanged`，内容变化记为 `updated`并保留历史版本。

## 13. 常见问题

### 返回610或认证失败

先运行：

```bash
python3 collector/youshu/refresh_login.py
```

然后重新取数。若失败的采集已记录为失败，不会阻止重新执行。

### 自动登录找不到浏览器

设置 `YOUDATA_BROWSER`为Edge或Chrome的可执行文件绝对路径。

### 导出文件数量不足

可能原因包括登录过期、个别地市导出失败、异步任务超时或看板参数变化。刷新登录后可增加 `--poll-timeout`，并使用 `--refresh`重新执行。

### 大批量任务持续返回500

优先使用 `--two-phase`，并适当增加 `--poll-timeout`。

### 数据库已经有该月数据

默认跳过取数。明确需要重新获取时使用 `--refresh`。

## 14. 样例验证

使用现有样例进行了临时数据库导入：

```text
企宽新装单（杭州样例）
读取：51,883
新增：51,883
失败：0

企宽投诉单
读取：32,906
新增：32,906
失败：0
```

测试数据库位于临时目录，未修改原始文件。

## 15. 后续封装为Skill时的调用规则

### 脚本选择

| 用户意图 | 脚本 |
|---|---|
| 刷新有数登录 | `refresh_login.py` |
| 下载企宽新装单 | `fetch_install.py` |
| 下载企宽投诉单 | `fetch_complaints.py` |
| 准备企宽新装报障率数据 | 依次运行新装单和投诉单脚本 |

### 推荐默认值

```text
mode         = both
chunk-days   = 3
interval     = 0.5
poll-timeout = 600
refresh      = false
```

新装单大批量导出建议启用 `--two-phase`。

### Skill执行逻辑

1. 将“8月”等自然语言周期转换成明确起止日期；
2. 检查数据库完整采集标识；
3. 已覆盖则不刷新登录、不重复取数；
4. 未覆盖时先取数；认证失效时运行刷新登录脚本再重试；
5. 用户明确要求重新获取时才使用 `--refresh`；
6. 检查预期文件数、采集状态、ETL数量及失败行数；
7. 只在两类数据都完整后，才进入企宽新装报障率计算。

### Skill不应做的事

- 不读取或输出 `youdata_login.json`的具体内容；
- 不回显 `有数配置.json`中的Cookie、CSRF、roomid和sid；
- 不修改看板ID、组件ID或筛选参数；
- 不把一份地市文件成功误判成全省整月完成；
- 不把合并文件和批次文件重复入库；
- 不默认使用 `--refresh`；
- 发布或打包时包含 `collector/youshu`中的脚本及非敏感任务配置；
- 实际的 `youdata_login.json`和`有数配置.json`不进入版本库，应在部署环境单独提供；
- 不在Skill里复制 `fetch_data.py`的复杂接口逻辑。
