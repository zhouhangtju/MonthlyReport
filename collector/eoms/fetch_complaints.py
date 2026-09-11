#!/usr/bin/env python3
"""获取 EOMS 政企投诉工单，支持文件与数据库双存储。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector.eoms.client import run_script


if __name__ == "__main__":
    run_script()
