---
name: collect-youshu-install-list
description: 采集有数报表47422的全省企宽装机清单明细，默认按北京时间T-3完整自然月，固定宽带类型1和已报结状态，支持Excel保存与MySQL入库。区别于派单口径企宽新装清单和报表38598装机报结量。
---

# 有数：企宽装机清单取数

使用项目入口 `collector/youshu/fetch_install_list.py`。源看板为报表 47422、看板 171531，导出“装机清单”组件。日期过滤字段为 `opertime`（最新操作时间），不是派单时间；固定 `nettype=1`、工单状态“已报结”，其余选择“全部”。因此业务类型可能包含“宽带预拆机”，不要擅自按新装过滤。

## 执行

不传日期时，入口按北京时间计算 T-3 的完整自然月。例如在 2026 年 10 月运行，取 2026-07-01 至 2026-07-31。默认同时保存 Excel 和写入 MySQL：

```bash
python3 collector/youshu/fetch_install_list.py --mode both
```

补采或指定周期时同时提供起止日期：

```bash
python3 collector/youshu/fetch_install_list.py \
  --start-date 2026-07-01 --end-date 2026-07-31 --mode both
```

`--mode file` 只保存原始文件，`--mode database` 只入库；默认文件目录为 `data/raw/youshu/youshu_install_list/`。完整自然月默认一个全省导出批次，显式传入超过 35 天的周期时按 `--chunk-days 35` 分批。数据库数据集与原始表是 `youshu_install_list`，主键为 `工单id`，不会覆盖现有的 `youshu_install`。只使用本次完整采集的文件入库；成功的相同周期可由 `collection_run` 跳过，需要强制重新采集时显式加 `--refresh`。

导出文件名仅包含取数起止日期，例如 `企宽装机清单_2026-07-01_2026-07-31.xlsx`；再次导出同一日期范围会替换同名文件。

下载后核对程序返回的预期文件数、19 列表头、`宽带类型=1`、`工单状态=已报结`、工单 ID 去重及 `collection_run` 状态。导出表不含 `opertime` 列，日期正确性依据提交给看板的筛选参数和采集周期记录，不能用“派单时间”或“报结时间”逐行代替检查。样例中的其他业务类型应保留。

认证过期时运行 `python3 collector/youshu/refresh_login.py`，成功后重试；也可在重试命令中加 `--login-first`。不要读取、回显或提交本地登录凭据文件。若 `python3` 不可用，可使用指向 Python 3.10 及以上且装有项目依赖的 `python`。
