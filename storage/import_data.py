#!/usr/bin/env python3
"""把已有 Excel/CSV 文件导入数据库。"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.datasets import DATASETS, get_dataset
from storage.importer import import_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入已有质量评估数据文件")
    parser.add_argument("--dataset", required=True, choices=sorted(DATASETS))
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
    parser.add_argument("--archive-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--period-start")
    parser.add_argument("--period-end")
    args = parser.parse_args()
    result = import_file(
        args.database,
        get_dataset(args.dataset),
        args.file,
        None if args.no_archive else args.archive_root,
        args.period_start,
        args.period_end,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

