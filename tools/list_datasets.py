#!/usr/bin/env python3
"""列出当前支持的数据集及主键。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config.datasets import DATASETS


if __name__ == "__main__":
    for dataset in DATASETS.values():
        print(f"{dataset.code}\t{dataset.source_system}\t{dataset.name}\t主键={dataset.key_column}")

