# 月报查询与更新服务

在能访问远程 MySQL 的机器部署。本目录是新增服务；使用 MySQL 版 MonthlyReport 的 storage、metrics 和 config，默认定位同级工程 projects/MonthlyReport。也可将 MONTHLYREPORT_ENGINE 指向部署机器的 MySQL 工程根目录。请安装该工程 requirements.txt 的依赖。

在服务进程环境中设置 MONTHLYREPORT_MYSQL_HOST、MONTHLYREPORT_MYSQL_USER、MONTHLYREPORT_MYSQL_PASSWORD、MONTHLYREPORT_MYSQL_DATABASE，端口可用 MONTHLYREPORT_MYSQL_PORT 指定（默认 3306）。通过部署环境注入凭据，不写入源码。账号需要能够查询源数据和写入计算结果；部分已有计算入口会初始化其所需表。服务不自动迁移旧结果表。

在 MonthlyReport-v1/MonthlyReport 目录运行：

    python -m report_api.server --port 8027

打开 http://127.0.0.1:8027/live 查询数据库指标。监听回环地址。首页 / 按报告月份请求 GET /api/v1/reports/YYYY-MM，所有展示值来自 MySQL 成功批次，缺失值显示为空。导入结果库联调时加 --read-only，以关闭查询未命中时的重算。

- GET /api/v1/catalog 返回可查询的模块及有成功批次的月份。
- POST /api/v1/query 接受 JSON，例如 {"month":"2026-10","owner":"dedicated_line_opening_withdrawal_rate"}。命中返回同一成功批次的所有维度；未命中则调用原计算函数，从 MySQL 源记录或源快照计算并写回结果。
- POST /api/v1/refresh 接受相同参数并增加 previous（当前展示的 metric_run_id）。同一进程串行执行写入；重复提交旧批次不会再触发计算。失败时界面保留已有结果。

结果表映射以 MySQL 工程 storage/metric_results.py 为准；原始采集仍由 collector 独立执行。查询不会自动登录上游系统。终端回收需要同周期的五类 MySQL 快照；编排正式指标重算按当前引擎要求读取资管 CSV，部署时设置 MONTHLYREPORT_ASSET_DIR，并在其中按 YYYY-MM.csv 提供对应月份文件。已有成功批次无需提供该文件。数据源或计算口径变化时请同步核对所部署版本的模块 README 与 skills。


## 非自动原因临时接入

当前测试链路读取 manual_metric_result 中 metric_set=internet_line_manual_automation、report_month=所选月份的已导入结果。
GET /api/v1/reports/YYYY-MM 在 manual 字段返回该记录，前端仅取 opening_network_nonautomatic_reasons 与 business_results 内对应业务的原因统计。
正式自动率仍来自 result_orchestration_opening，前端不使用辅助 JSON 的自动率覆盖正式结果。

后续迁移目标为由 metrics/opening/dedicated_line_metrics.py 统一计算并入库非自动原因，替代 calculate_manual_csv.py 的临时原因链路。待正式脚本写入全省、地市的非自动总数、工程施工数、空原因数及其占比后，统一调整接口和前端适配。当前不删除辅助脚本，不改变已有计算口径。
