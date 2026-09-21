# 一体化平台售中开通工单取数说明

## 1. 模块用途

本模块从政企一体化平台导出售中开通工单，为“专线开通撤退单率”提供原始数据。

平台页面路径：

```text
综调管理 → 装维过程管理 → 工单查询 → 售中工单查询
```

本模块只负责取数、文件保存和数据库入库，不在取数阶段计算撤退单率，也不提前删除测试单或非专线业务。

## 2. 文件说明

```text
collector/integration/
├── README.md                    本说明
├── login.py                     4A自动登录并获取zy_token
├── client.py                    导出请求、文件校验、周期检查及入库衔接
└── fetch_withdrawal_orders.py   直接运行的取数入口
```

本模块由 `export/一体化/撤退单/` 的实现迁移而来。导出及4A登录逻辑均已写入 `collector/integration/`，运行、发布和打包不依赖原 `export` 目录；原路径只用于追溯迁移来源。

## 3. 数据集定义

| 项目 | 内容 |
|---|---|
| 数据集名称 | 一体化售中开通工单 |
| 数据集编码 | `integration_opening` |
| 源记录主键 | `工单号` |
| 时间口径 | 工单结束时间 |
| 数据来源 | 二编 |
| 工单类型 | 开通 |
| 工单状态 | 全部 |
| 业务类型 | 全部，指标计算阶段再筛选 |

样例文件共40,055条记录、29个字段，工单号全部非空且唯一。

## 4. 环境准备

要求Python 3.10或更高版本，并能访问浙江移动4A和一体化平台内网。

```bash
cd "/Users/hzhou/Desktop/政企/projects/qualityAssessment/quality-assessment-pipeline"
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## 5. 登录与认证

支持两种认证方式，已有Token优先。

### 5.1 使用已有Token

推荐使用环境变量：

```bash
export INTEGRATION_ZYTOKEN="实际zy_token"
```

也可以使用 `--token`临时传入，但命令行参数可能进入终端历史。

### 5.2 使用4A账号自动登录

```bash
export INTEGRATION_ACCOUNT="4A账号"
export INTEGRATION_PASSWORD="4A密码"
```

没有Token时，脚本会获取4A RSA公钥、加密账号密码、以密码模式登录、取得 `pname`票据，再调用一体化登录接口换取 `zy_token`。

新脚本没有默认账号或默认密码，也不会把凭证写入代码或配置文件。原脚本中的硬编码凭证没有迁移。

## 6. 运行方法

### 6.1 同时保存文件并入库

```bash
python3 collector/integration/fetch_withdrawal_orders.py \
  --month 2026-08 \
  --mode both
```

默认目录和文件名：

```text
data/raw/integration/integration_opening/
售中开通工单_2026-07-26_至_2026-08-25.xlsx
```

### 6.2 只保存文件

```bash
python3 collector/integration/fetch_withdrawal_orders.py \
  --month 2026-08 \
  --mode file
```

### 6.3 只入库

```bash
python3 collector/integration/fetch_withdrawal_orders.py \
  --month 2026-08 \
  --mode database
```

只入库模式会下载到临时目录，入库成功后清理临时文件。

### 6.4 强制重新拉取

```bash
python3 collector/integration/fetch_withdrawal_orders.py \
  --month 2026-08 \
  --mode both \
  --refresh
```

## 7. 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `--month` | 条件必填 | 无 | 月报月份`YYYY-MM`，自动取上月26日至本月25日 |
| `--start-date` | 条件必填 | 无 | 与`--end-date`同时使用，不能与`--month`并用 |
| `--end-date` | 条件必填 | 无 | 工单结束时间结束日期，包含当天 |
| `--mode` | 否 | `both` | `file`、`database`或`both` |
| `--output-dir` | 否 | `data/raw/integration` | 文件输出根目录 |
| `--database` | 否 | 可省略 | 兼容旧命令；MySQL 连接信息写在 `storage/database.py` |
| `--timeout` | 否 | `180` | 导出请求超时秒数 |
| `--refresh` | 否 | 关闭 | 忽略数据库周期和已有文件，强制重新拉取 |
| `--overwrite` | 否 | 关闭 | `--refresh`的兼容别名 |
| `--token` | 否 | 环境变量 | 临时指定 `zy_token` |
| `--account` | 否 | 环境变量 | 临时指定4A账号 |
| `--password` | 否 | 环境变量 | 临时指定4A密码 |

查看参数：

```bash
python3 collector/integration/fetch_withdrawal_orders.py --help
```

## 8. 接口请求口径

导出接口：

```text
POST http://188.105.165.237:18083/api/work/workmng/exop/exportHalfWayNew
```

核心请求体：

```json
{
  "endTimeStart": "2026-07-26 00:00:00",
  "endTimeEnd": "2026-08-25 23:59:59",
  "ordertypeList": ["开通"],
  "statusList": [],
  "dataSources": "二编",
  "serviceType": [],
  "isRecord": ""
}
```

- 日期字段使用工单结束时间闭区间；
- `ordertypeList=["开通"]`只取开通工单；
- `dataSources="二编"`只取二编来源；
- `statusList=[]`保留全部状态，避免漏掉已撤单和已驳回；
- `serviceType=[]`保留全部业务类型，指标阶段再筛选；
- 同时提交页面支持的29个中英文字段。

Token通过请求头 `Zy_token`、`Zytoken`和Cookie `zy_token`携带。

## 9. 导出字段

```text
工单号、工单主题、工单数据来源、上游工单号、派单时间、受理部门、
工单流向、地市、区县、业务类型、工单类型、调整类型、
是否存在关联工单、关联工单号、工单状态、是否超时、是否撤单重录、
首次派单时间、首次考核超时时限、考核超时时限、工单是否及时开通、
业务开通时间(h)、工单历时/小时、工单处理时限、工单结束时间、
业务套餐类型、业务保障等级、计费号/产品实例编号、是否派发工程施工
```

测试单剔除、专线业务筛选及撤退状态判断都留给指标模块处理。

## 10. 文件识别

接口可能返回XLSX，也可能返回传统XLS。脚本根据文件头选择扩展名，不仅依赖响应头。数据库导入器同时支持正常XLSX、真正的传统XLS，以及扩展名为 `.xls`但实际内容为XLSX的文件。

非Excel响应会被拒绝，不会把登录页或错误JSON保存成数据文件。

## 11. 数据库周期覆盖检查

运行模式包含数据库时，下载前检查 `etl_run`：

- 数据集为 `integration_opening`；
- 批次状态成功；
- 失败行数为0；
- 一个或多个成功批次的日期并集完整覆盖请求周期。

完整覆盖时不登录、不请求接口，返回：

```json
{
  "downloaded": false,
  "skipped": true,
  "skip_reason": "database_already_covered"
}
```

使用 `--refresh`可以忽略覆盖检查并重新拉取。

## 12. 入库与去重

数据集主键为 `工单号`：

- 新工单号记为 `inserted`；
- 工单号相同且内容相同记为 `unchanged`；
- 工单号相同但内容变化记为 `updated`，并保留历史版本；
- 工单号为空记为 `failed`，不写入业务记录。

每次入库记录源文件、文件哈希、周期、读取数、新增数、更新数、未变化数、失败数和执行状态。

## 13. 与撤退单率的关系

取数阶段只固定“工单结束时间 + 二编 + 开通”。指标阶段再执行：

1. 剔除测试单；
2. 筛选正式专线业务范围；
3. 直接统计周期内原始表记录，指标阶段不二次去重；
4. 统计开通工单分母；
5. 根据正式确认的撤退状态计算分子。

仍待业务确认：

- “已驳回”是否等同于退单；
- “失败”是否计入撤退单；
- 专线包含哪些业务类型；
- 测试单使用哪些字段和规则识别。

## 14. 样例验证

原目录样例文件已完成临时数据库导入测试：

```text
读取：40,055
新增：40,055
更新：0
未变化：0
失败：0
```

测试没有修改原始样例。

## 15. 常见问题

### 缺少登录凭证

没有 `INTEGRATION_ZYTOKEN`时，必须设置 `INTEGRATION_ACCOUNT`和`INTEGRATION_PASSWORD`。

### 自动登录未取得pname

通常表示4A账号密码失效、登录流程改变，或当前网络无法访问4A。

### 接口未返回Excel

通常是Token失效、权限不足或接口返回错误JSON。脚本会拒绝保存该响应。

### 数据库已有数据但需要重新下载

使用 `--refresh`。

### 文件存在但数据库没有数据

在 `both`模式且数据库未覆盖周期时，脚本会复用同周期已有文件并执行幂等入库。

## 16. 后续封装为Skill时的调用规则

Skill应调用：

```text
collector/integration/fetch_withdrawal_orders.py
```

必要输入为开始日期和结束日期。未指定存储模式时默认 `both`。

推荐默认值：

```text
mode    = both
timeout = 180
refresh = false
```

Skill执行前应判断用户是否明确要求重新拉取，只有明确要求时才使用 `--refresh`。已有Token时优先使用Token，没有Token时才使用4A账号密码自动登录。

执行后检查：

1. 脚本是否成功退出；
2. 跳过时原因是否为数据库已覆盖；
3. 文件模式下返回文件是否存在；
4. 数据库模式下是否返回ETL `run_id`；
5. `failed`是否为0；
6. `read`是否异常为0；
7. 是否出现认证失败、非Excel响应或超时。

Skill不应：

- 保存或回显完整Token、账号和密码；
- 迁移原脚本中的硬编码凭证；
- 把“是否撤单重录”直接当作撤退单标志；
- 在取数阶段擅自确定撤退状态或专线业务范围；
- 默认使用 `--refresh`；
- 删除原始文件；
- 复制登录、导出或入库逻辑到Skill中。
