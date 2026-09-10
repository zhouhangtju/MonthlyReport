#!/usr/bin/env python3
"""获取一体化售中开通工单，为专线开通撤退单率提供数据。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collector.integration.client import run_script


if __name__ == "__main__":
    run_script()
