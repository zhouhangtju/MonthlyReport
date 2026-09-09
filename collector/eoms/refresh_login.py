#!/usr/bin/env python3
"""刷新 EOMS Bearer Token。"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector.eoms.client import refresh_login


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="登录 EOMS 并刷新 collector/eoms/login.db")
    parser.add_argument("--account", help="推荐改用 EOMS_ACCOUNT 或 eoms_login.json")
    parser.add_argument("--password", help="推荐改用 EOMS_PASSWORD 或 eoms_login.json")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    refresh_login(python=args.python, account=args.account, password=args.password)
