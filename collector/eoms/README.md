# EOMS 政企投诉工单取数说明

## 1. 模块范围

本模块只负责获取 EOMS 政企投诉原始工单，并同时支持文件留存和 SQLite 入库。专线、千里眼重复投诉率以及专线投诉率属于 `metrics` 指标模块，不在取数时计算。

| 数据集 | 编码 | 主键 | 指标用途 |
|---|---|---|---|
| 政企投诉工单 | `eoms_complaint` | 优先 `id` | 专线投诉率、专线重复投诉率、千里眼重复投诉率及专线新装报障率 |

本模块由原 `export/EOMS-投诉工单工具包-精简版` 迁移而来。运行、发布和打包只依赖 `collector/eoms/` 内的脚本，不要求原 `export` 目录存在。

## 2. 目录结构

```text
collector/eoms/
├── README.md
├── client.py                 双存储、周期跳过和取数包装
├── fetch_complaints.py       投诉工单取数入口
├── refresh_login.py          刷新Token入口
├── eoms_login.example.json   登录配置示例
├── eoms_login.json           实际账号配置，不提交版本库
├── login.db                  Token缓存，运行后生成，不提交版本库
└── scripts/
    ├── auto_login_token.py   4A登录及Token获取
    └── complaint_crawl.py    列表分页、详情补全和Excel输出
```

## 3. 认证流程

复制并填写配置：

```bash
cp collector/eoms/eoms_login.example.json collector/eoms/eoms_login.json
python3 collector/eoms/refresh_login.py
```

账号读取优先级为：命令行参数、环境变量 `EOMS_ACCOUNT`/`EOMS_PASSWORD`、`eoms_login.json`、终端交互输入。

登录脚本会：

1. 从浙江移动4A取得RSA公钥；
2. 加密账号密码并登录；
3. 从跳转地址取得 `pname`；
4. 调用 EOMS `/prod-api/auth/a4login` 换取 Bearer Token；
5. 将 Token 写入 `collector/eoms/login.db`。

`eoms_login.json`含明文密码，`login.db`含Token，两者已加入 `.gitignore`。部署时应由运行环境单独提供登录配置，不能写入README或程序源码。

## 4. 获取投诉工单

推荐同时保存文件并入库：

```bash
python3 collector/eoms/fetch_complaints.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both
```

需要先刷新Token再取数：

```bash
python3 collector/eoms/fetch_complaints.py \
  --start-date 2026-08-01 \
  --end-date 2026-08-31 \
  --mode both \
  --login-first
```

取数文件默认保存在：

```text
data/raw/eoms/eoms_complaint/投诉工单_原始数据_20260801-20260831.xlsx
```

## 5. 实际取数逻辑

取数脚本从本模块的 `login.db` 读取 Bearer Token，然后：

1. 分页 POST `/prod-api/process/compt/govcustomercomplaint/list`；
2. 使用开始时间、结束时间、`deleted=0`筛选，默认每页500条；
3. 对缺少计费号码等扩展字段的记录，GET `/prod-api/process/compt/govcustomercomplaint/show/detail/{id}`；
4. 展平列表和详情字段；
5. 从附加报结信息、其他工单文本及详情扩展字段提取或补全 `e55...`计费号码；
6. 上述渠道处理后计费号码仍为空时，使用手机号码补位，已有计费号码绝不覆盖，并记录 `计费号码补位来源=手机号码补位`；
7. 输出字段精简后的原始分析Excel；
8. 按 `id`幂等写入数据库，并保留记录版本。

列表接口和详情接口都使用请求头：

```text
Authorization: Bearer <token>
```

## 6. 存储模式

| 模式 | 原始文件 | 数据库 |
|---|---|---|
| `file` | 保留 | 不入库 |
| `database` | 临时生成，入库后清理 | 入库 |
| `both` | 保留 | 入库 |

数据库已有成功且无失败的ETL批次完整覆盖请求周期时，`database`和`both`模式默认不登录、不调用网络接口，返回：

```json
{
  "skipped": true,
  "skip_reason": "database_already_covered"
}
```

明确需要重新获取时使用 `--refresh`。

## 7. 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--start-date` | 必填 | 开始日期，`YYYY-MM-DD` |
| `--end-date` | 必填 | 结束日期，包含当天 |
| `--mode` | `both` | `file`、`database`或`both` |
| `--output-dir` | `data/raw/eoms` | 文件输出根目录 |
| `--database` | `data/quality_assessment.db` | SQLite路径 |
| `--page-size` | `500` | 列表接口每页条数 |
| `--login-first` | 关闭 | 取数前刷新Token |
| `--refresh` | 关闭 | 忽略数据库周期覆盖并重新取数 |

## 8. 字段补全边界

输出的“原始工单”不是完全未经处理的接口JSON。取数阶段会做必要的数据工程处理：字段展平、详情字段补全、计费号码提取、空计费号码使用手机号补位和Excel列名转换。补位不会覆盖原有计费号码，原“手机号码”列也会保留，以便审计。

产品筛选、非自建判断、重复投诉Key、短时间重复派单剔除以及指标分子分母计算，均应留在 `metrics` 模块。

## 9. 后续指标依赖

- 专线投诉率：EOMS投诉工单作为分子，分母来自业务量数据；
- 专线重复投诉率：EOMS单系统计算，分母是有效范围内唯一客户标识数；
- 千里眼重复投诉率：EOMS单系统计算，分母同样是有效范围内唯一客户标识数，但产品筛选、Key和分子排除规则不同；
- 专线新装报障率：EOMS投诉工单与编排互联网专线新装单联合计算。

指标正式口径以原工具包README中标注“客服流水号口径”的统计脚本为迁移来源，历史BAT和旧口径脚本不作为正式入口。
