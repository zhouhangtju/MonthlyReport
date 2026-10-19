# 地市终端回收指标

本目录提供与 `metrics/opening/bycity` 一致的地市级计算入口。脚本读取 `terminal_recovery` 最新成功省级批次。首次运行时从数据库恢复同周期原始快照，一次重建全省业务类型与设备类型匹配结果并写入 `terminal_recovery_bycity_preparation` 准备批次；后续地市直接复用该批次。输出包含：

- 全省11地市回收率和设备类型对比；
- 指定地市的标准区县回收结果；
- 指定地市“业务类型 × 设备类型”结果。

运行方式：

```powershell
.\.venv\python.exe metrics/terminal_recovery/bycity/terminal_recovery_metrics_by_city.py `
  --month 2026-08 --city 杭州 --mode both
```

默认输出 `outputs/终端回收地市指标_杭州_2026-08.json`。数据库任务编码为
`terminal_recovery_metrics_by_city`，结果继续写入 `result_terminal_recovery`，不会新增结果表。

