"""Explicit, restartable migration of legacy results; never deletes the source."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage.database import connect, initialize
from storage.metric_results import TABLES, insert_results, table_for


def identity(row):
    return (row['metric_code'], row['dimension_type'],
            json.dumps(json.loads(row['dimension_value']), ensure_ascii=False, sort_keys=True))


def numbers(row):
    return tuple(row[k] for k in ('numerator', 'denominator', 'metric_value'))


def migrate(apply=False):
    if apply:
        initialize(None)
    summary = {'apply': apply, 'runs': 0, 'source_rows': 0, 'inserted': 0}
    with connect(None) as conn:
        if not conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() "
                            "AND table_name='ads_metric_result'").fetchone():
            return summary
        runs = conn.execute('SELECT DISTINCT r.metric_run_id, r.metric_code FROM metric_run r '
                            'JOIN ads_metric_result a ON a.metric_run_id=r.metric_run_id '
                            'ORDER BY r.metric_run_id').fetchall()
    for run in runs:
        owner, run_id = run['metric_code'], run['metric_run_id']
        table = table_for(owner)  # Unknown owners fail loudly; do not discard data.
        with connect(None) as conn:
            if apply:
                conn.execute('SELECT metric_run_id FROM metric_run WHERE metric_run_id=? FOR UPDATE', (run_id,))
            rows = conn.execute('SELECT * FROM ads_metric_result WHERE metric_run_id=? ORDER BY result_id', (run_id,)).fetchall()
            summary['runs'] += 1
            summary['source_rows'] += len(rows)
            if not apply:
                continue
            existing = conn.execute(f'SELECT * FROM `{table}` WHERE metric_run_id=?', (run_id,)).fetchall()
            current = {identity(row): numbers(row) for row in existing}
            source = {identity(row): numbers(row) for row in rows}
            if len(source) != len(rows):
                raise ValueError(f'{run_id}: 旧结果包含重复维度，请先核对')
            if any(key not in source or source[key] != value for key, value in current.items()):
                raise ValueError(f'{run_id}: 新旧结果冲突，已回滚当前任务')
            missing = [dict(row, dimension=json.loads(row['dimension_value']))
                       for row in rows if identity(row) not in current]
            insert_results(conn, owner, run_id, missing)
            copied = conn.execute(f'SELECT * FROM `{table}` WHERE metric_run_id=?', (run_id,)).fetchall()
            if {identity(row): numbers(row) for row in copied} != source:
                raise ValueError(f'{run_id}: 迁移核对失败')
            summary['inserted'] += len(missing)
        print(f'[迁移] {run_id}: 已核对 {len(rows)} 条', flush=True)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='执行迁移；默认仅统计旧结果')
    args = parser.parse_args()
    print(json.dumps(migrate(args.apply), ensure_ascii=False, indent=2))
