#!/usr/bin/env python3
"""采集点金行动三类整周期报表。"""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from collector.orchestration.golden_client import collect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=('transport', 'internet', 'cloud', 'all'), default='all')
    parser.add_argument('--start-date', required=True)
    parser.add_argument('--end-date', required=True)
    parser.add_argument('--mode', choices=('file', 'database', 'both'), default='both')
    parser.add_argument('--output-dir', type=Path, default=Path('data/raw/orchestration'))
    parser.add_argument('--token', default=os.getenv('GDDL_TOKEN'))
    parser.add_argument('--cookie', default=os.getenv('GDDL_COOKIE'))
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--refresh', '--overwrite', action='store_true')
    args = parser.parse_args()
    print(json.dumps(collect(args.kind, args.start_date, args.end_date, mode=args.mode,
                             output_dir=args.output_dir, token=args.token, cookie=args.cookie,
                             timeout=args.timeout, refresh=args.refresh), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
