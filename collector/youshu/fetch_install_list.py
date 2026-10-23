#!/usr/bin/env python3
"""采集有数报表 47422 的企宽装机清单，默认北京时间 T-3 整月。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collector.youshu.client import run_script


if __name__ == "__main__":
    run_script("install_list")
