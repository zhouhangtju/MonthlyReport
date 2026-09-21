#!/usr/bin/env python3
"""初始化质量评估 MySQL 数据库。"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage.database import _database_name, initialize


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="初始化质量评估 MySQL 数据库")
    parser.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
    args = parser.parse_args()
    initialize(args.database)
    print(f"MySQL 数据库已初始化：{_database_name()}")

