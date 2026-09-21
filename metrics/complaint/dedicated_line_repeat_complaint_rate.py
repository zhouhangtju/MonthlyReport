"""从数据库计算专线/专网重复投诉率。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from metrics.complaint.repeat_rate import LINE, run_metric


def main() -> None:
    parser = argparse.ArgumentParser(description="从数据库计算专线/专网重复投诉率")
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_metric(LINE, args.database, args.start_date, args.end_date, args.mode, args.output)
    print(json.dumps({key: report[key] for key in ("metric_run_id", "quality", "results", "output_file")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
