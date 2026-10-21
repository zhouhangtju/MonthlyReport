"""Extract the validated Sheet2 history ledger into the skill's compact JSON asset."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from calculate import DEFAULT_HISTORY, read_history_workbook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--sheet", default="Sheet2")
    parser.add_argument("--output", type=Path, default=DEFAULT_HISTORY)
    args = parser.parse_args()
    history = read_history_workbook(args.input, args.sheet)
    history["audit"]["source_file"] = args.input.name
    document = {"schema_version": "1.0", "metric_set": "qikuan_stock_history",
                "months": history["months"], "source": history["audit"],
                "generated_at": datetime.now(timezone.utc).isoformat()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"保留历史月份 {history['audit']['first_month']} 至 {history['audit']['last_month']}，"
          f"共 {history['audit']['month_count']} 个月：{args.output.resolve()}")


if __name__ == "__main__":
    main()
