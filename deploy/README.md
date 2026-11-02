# 每日新装报障率

在项目根目录运行 `python3 tools/daily_installation.py`。默认采用北京时间当天，仅拉取执行日期前一天的数据，再检查数据库是否完整覆盖两套计算区间，最后分别计算企宽、专线、商客。复用现有采集器的覆盖跳过策略。历史数据需要提前单独补齐；每日任务不会自动回补三个月。

日期预览：`python3 tools/daily_installation.py --dry-run --date 2026-10-30`。

部署：在能访问业务系统及 MySQL 的 Linux/macOS 主机准备项目依赖及现有采集器登录配置，将 daily_installation.cron 的项目路径和 Python 解释器替换为实际绝对路径，并将该行追加到现有 crontab（不要覆盖其他任务）。主机时区须为 Asia/Shanghai，且每天05:00保持开机。此仓库配置尚未注册到任何主机的系统调度器。

运行状态：outputs/daily_installation/YYYY-MM-DD.json；详细日志位于同目录的 YYYY-MM-DD.log。status=success 表示采集覆盖检查和六项指标计算全部通过；failed 表示失败，error记录原因；running 长期不结束需检查进程和日志。文件锁防止重复并发运行。

当天成功检查：`python3 tests/test_daily_installation_task.py`，退出码0表示成功；未执行、失败或缺少结果返回非0。该检查读取实际结果，不会发起取数。

日期边界测试：`python3 -m unittest discover -s tests -p test_daily_installation_windows.py -v`。

每日任务会先调用 `collector/youshu/refresh_login.py` 更新 Cookie，再执行有数取数；登录失败或超过600秒则记录失败并停止，不继续计算。运行主机需安装登录脚本所需的 Node.js 及其依赖。cron 的 PATH 中若没有 node，可在任务命令后追加 `--node /absolute/path/to/node`。状态文件中的 youshu_login 记录登录阶段状态，登录输出写入当天日志。

登录编排测试（模拟子进程，不实际登录）：`python3 -m unittest discover -s tests -p test_daily_installation_login.py -v`。

EOMS投诉取数前也会执行 `collector/eoms/refresh_login.py` 更新 Token（login.db），使用当前Python解释器及原有 EOMS_ACCOUNT/EOMS_PASSWORD 环境变量或 eoms_login.json 配置，不在调度命令中传密码。登录失败或超过600秒立即停止，状态文件的 eoms_login 标记失败，不执行后续EOMS取数及指标计算。

每个时间范围计算完毕后自动生成 `outputs/daily_installation/YYYY-MM-DD_窗口名.xlsx`，状态文件的 excel_path 指向对应文件。第一页“汇总”固定展示全省和11个地市的专线、企宽、商客分子、分母和百分比；异常地市额外保留，零分母的报障率留空。四张明细页为专线分子/分母、企宽分子/分母，读取本次 metric_run_id 对应的数据库明细，不重新匹配；明细数量与全省指标不一致会使任务失败。商客清单即两类清单的合并，不重复导出。导出沿用现有指标口径，企宽新装派单时间不二次过滤。需安装 requirements.txt 中已有的 openpyxl。

两套Excel全部导出后，任务重新打开文件校验归档完整性、全省分子分母和四张明细的行数，随后在单个数据库事务中按本次六个 metric_run_id 删除计算明细、对应指标结果、计算批次。原始取数、其他任务及历史批次不清理。Excel/JSON文件保留，JSON中的批次ID作为历史追溯标识，不再指向仍存在的计算批次。导出失败不清理；删除失败事务回滚，任务标记failed。状态文件 cleanup.status 为success才表示清理完成。失败运行及之前已有的计算记录仍会保留；这不限制原始数据或文件占用增长。

输出目录已固定为 Windows 的 `C:\.openclaw\outputs`，Excel、指标JSON、状态JSON、日志和任务锁均保存在这里，目录不存在时自动创建。此设置面向Windows部署；原始取数文件仍遵循各采集器自身配置。

输出按业务和执行日期分目录：`C:\.openclaw\outputs\installation_fault_rate\YYYY-MM-DD\`。每份Excel必须包含汇总、专线分子、专线分母、企宽分子、企宽分母五张工作表；明细包含来源数据集及原始记录ID供反查。更新部署时须同时同步 tools/daily_installation.py 和 tools/installation_excel.py。

也可不使用系统调度器，直接执行 `python -u tools/daily_installation.py --schedule` 启动程序内定时模式。程序常驻等待北京时间每天05:00执行；启动时若已过05:00则等次日，不立即补跑。按Ctrl+C停止，关闭进程或重启电脑后需重新启动；不能与--date、--dry-run组合。可附加--node指定Node路径。不要同时启用系统每天05:00任务，避免重复触发。进程运行中的异常会打印并在次日继续尝试。
