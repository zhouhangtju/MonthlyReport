#!/usr/bin/env python3
"""初始化质量评估 SQLite 数据库。"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage.database import initialize


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="初始化质量评估 SQLite 数据库")
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    args = parser.parse_args()
    initialize(args.database)
    print(f"数据库已初始化：{args.database.resolve()}")

