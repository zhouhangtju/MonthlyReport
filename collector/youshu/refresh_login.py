#!/usr/bin/env python3
"""运行有数平台原有自动登录脚本，刷新有数配置。"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collector.youshu.client import refresh_login


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="刷新有数平台登录凭证")
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    refresh_login(node=args.node)
