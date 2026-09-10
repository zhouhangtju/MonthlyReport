#!/usr/bin/env python3
"""获取编排互联网专线新装单，支持文件保存和数据库入库。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from client import run_script


if __name__ == "__main__":
    run_script("install")
