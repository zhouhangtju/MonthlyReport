#!/usr/bin/env python3
"""获取有数平台企宽投诉单。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collector.youshu.client import run_script


if __name__ == "__main__":
    run_script("complaint")

