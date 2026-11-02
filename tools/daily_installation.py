"""Daily installation metrics; all dates use Asia/Shanghai."""
import argparse
import calendar
import os
from contextlib import contextmanager
import json
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT_DIR = Path(r'C:\.openclaw\outputs')


@contextmanager
def task_lock(path):
    """Nonblocking OS lock; released automatically even when the process exits."""
    with path.open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0, 2)
            if lock.tell() == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError('无法取得任务锁，可能已有每日任务正在运行') from exc
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('无法取得任务锁，可能已有每日任务正在运行') from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def windows(day):
    def back(n):
        y, m = divmod(day.year * 12 + day.month - 1 - n, 12)
        return date(y, m + 1, min(day.day, calendar.monthrange(y, m + 1)[1]))
    end = (day - timedelta(days=1)).isoformat()
    return {'rolling_three_months': (back(3).isoformat(), end),
            'calendar_three_months': (back(2).replace(day=1).isoformat(), end)}


def validate_excel(path, reports):
    """Read the finished archive before allowing database cleanup."""
    from openpyxl import load_workbook
    from zipfile import ZipFile
    with ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f'损坏的Excel: {path}')
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        if book.sheetnames != ['汇总', '专线分子', '专线分母', '企宽分子', '企宽分母']:
            raise ValueError('Excel工作表不完整')
        summary = list(book['汇总'].iter_rows(min_row=2, max_row=2, values_only=True))[0]
        for index, (metric, title) in enumerate([
            ('dedicated_line', '专线'), ('qikuan', '企宽'), ('commercial_customer', '商客')]):
            province = next(r for r in reports[metric]['results'] if r['dimension_type'] == 'province')
            if tuple(summary[1 + index * 3:3 + index * 3]) != (province['numerator'], province['denominator']):
                raise ValueError('Excel全省汇总与计算结果不一致')
            if metric != 'commercial_customer':
                for role, suffix in [('numerator', '分子'), ('denominator', '分母')]:
                    count = sum(1 for _ in book[title + suffix].iter_rows(min_row=2))
                    if count != province[role]:
                        raise ValueError(f'{title}{suffix}Excel明细数量不一致')
    finally:
        book.close()


def cleanup_current_runs(runs):
    """Delete only the six verified current runs, atomically, children first."""
    from storage.database import connect
    from storage.metric_results import table_for
    allowed = {f'{name}_install_fault_rate' for name in ('qikuan', 'dedicated_line', 'commercial_customer')}
    if len(runs) != 6 or len({r['metric_run_id'] for r in runs}) != 6:
        raise ValueError('清理必须包含本次六个独立计算批次')
    if any(r['metric_code'] not in allowed for r in runs):
        raise ValueError('不允许清理其他指标')
    with connect(None) as connection:
        # Validate every identity before deleting any rows; lock until commit.
        for run in runs:
            row = connection.execute(
                'SELECT metric_code, period_start, period_end, status FROM metric_run '
                'WHERE metric_run_id=? FOR UPDATE', (run['metric_run_id'],)).fetchone()
            if row is None or any(str(row[k]) != str(run[k]) for k in ('metric_code', 'period_start', 'period_end')) or row['status'] != 'success':
                raise ValueError(f"清理批次校验失败: {run['metric_run_id']}")
        for run in runs:
            args = (run['metric_run_id'],)
            connection.execute('DELETE FROM ads_metric_detail WHERE metric_run_id=?', args)
            connection.execute(f"DELETE FROM `{table_for(run['metric_code'])}` WHERE metric_run_id=?", args)
        for run in runs:
            connection.execute('DELETE FROM metric_run WHERE metric_run_id=?', (run['metric_run_id'],))


def run(day, node="node"):
    from storage.database import has_collection_coverage, has_successful_coverage
    base_output = OUTPUT_DIR / 'installation_fault_rate'
    output = base_output / day.isoformat()
    output.mkdir(parents=True, exist_ok=True)
    with task_lock(base_output / '.lock'):
        periods = windows(day)
        record = dict(run_date=day.isoformat(), status='running', collection_complete=False, windows={})
        target = output / f'{day}.json'
        def save():
            tmp = target.with_suffix('.tmp')
            tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(target)
        save()
        current_runs = []
        record['cleanup'] = {'status': 'not_started'}
        try:
            with (output / f'{day}.log').open('a', encoding='utf-8') as log:
                def execute(script, start, end, extra=()):
                    subprocess.run([sys.executable, str(ROOT / script), '--start-date', start,
                                    '--end-date', end, '--mode', 'both', *extra], cwd=ROOT,
                                   stdout=log, stderr=subprocess.STDOUT, check=True, timeout=21600)
                record['youshu_login'] = 'running'
                save()
                subprocess.run(
                    [sys.executable, str(ROOT / 'collector/youshu/refresh_login.py'), '--node', node],
                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
                record['youshu_login'] = 'success'
                save()
                coverage_start = min(v[0] for v in periods.values())
                yesterday = (day - timedelta(days=1)).isoformat()
                record['collection_period'] = {'start_date': yesterday, 'end_date': yesterday}
                save()
                sources = [
                    ('youshu/fetch_install.py', 'youshu_install', has_collection_coverage),
                    ('youshu/fetch_complaints.py', 'youshu_complaint', has_collection_coverage),
                    ('orchestration/fetch_install.py', 'orch_install', has_successful_coverage),
                    ('eoms/fetch_complaints.py', 'eoms_complaint', has_successful_coverage)]
                for script, code, check in sources:
                    if code == 'eoms_complaint':
                        record['eoms_login'] = 'running'
                        save()
                        subprocess.run(
                            [sys.executable, str(ROOT / 'collector/eoms/refresh_login.py')],
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            check=True, timeout=600)
                        record['eoms_login'] = 'success'
                        save()
                    execute('collector/' + script, yesterday, yesterday)
                    if not check(None, code, yesterday, yesterday):
                        raise RuntimeError(f'Incomplete collection: {code} {yesterday}')
                for _, code, check in sources:
                    if not check(None, code, coverage_start, yesterday):
                        raise RuntimeError(f'历史数据覆盖不完整，请单独补齐：{code} {coverage_start} 至 {yesterday}；每日任务仅拉取前一天')
                record['collection_complete'] = True
                from tools.installation_excel import export_excel
                for name, (start, end) in periods.items():
                    reports = {}
                    result = dict(start_date=start, end_date=end, metrics={})
                    record['windows'][name] = result
                    for metric in ('qikuan', 'dedicated_line', 'commercial_customer'):
                        path = output / f'{day}_{name}_{metric}.json'
                        execute(f'metrics/installation/{metric}_install_fault_rate.py', start, end,
                                ['--output', str(path)])
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        if not payload.get('metric_run_id') or not payload.get('results'):
                            raise RuntimeError(f'Invalid metric result: {path}')
                        current_runs.append({k: payload[k] for k in ('metric_run_id', 'metric_code', 'period_start', 'period_end')})
                        reports[metric] = payload
                        result['metrics'][metric] = dict(status='success', evidence_path=str(path), metric_run_id=payload['metric_run_id'])
                        save()
                    result['excel_path'] = export_excel(
                        reports, output / f'{day}_{name}.xlsx',
                        '滚动三个月' if name == 'rolling_three_months' else '包含当月的三个月')
                    validate_excel(result['excel_path'], reports)
                    result['excel_verified'] = True
                    save()
            record['cleanup'] = {'status': 'running', 'metric_run_ids': [r['metric_run_id'] for r in current_runs]}
            save()
            cleanup_current_runs(current_runs)
            record['cleanup']['status'] = 'success'
            record['status'] = 'success'
        except Exception as exc:
            if record['cleanup']['status'] == 'running':
                record['cleanup'].update(status='failed', error=str(exc))
            for stage in ('youshu_login', 'eoms_login'):
                if record.get(stage) == 'running':
                    record[stage] = 'failed'
            record.update(status='failed', error=str(exc))
            raise
        finally:
            save()


def next_schedule(now):
    local = now.astimezone(ZoneInfo('Asia/Shanghai'))
    target = local.replace(hour=5, minute=0, second=0, microsecond=0)
    return target if local <= target else target + timedelta(days=1)


def serve(node='node'):
    base = OUTPUT_DIR / 'installation_fault_rate'
    base.mkdir(parents=True, exist_ok=True)
    with task_lock(base / '.scheduler.lock'):
        print('定时模式已启动：北京时间每天05:00执行，按Ctrl+C停止。', flush=True)
        while True:
            target = next_schedule(datetime.now(ZoneInfo('Asia/Shanghai')))
            print(f'下次执行：{target.isoformat()}', flush=True)
            while True:
                remaining = (target - datetime.now(ZoneInfo('Asia/Shanghai'))).total_seconds()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 30))
            day = datetime.now(ZoneInfo('Asia/Shanghai')).date()
            print(f'开始执行：{day}', flush=True)
            try:
                run(day, node=node)
            except Exception as exc:
                print(f'任务失败：{exc}；下一天继续运行。', flush=True)
            else:
                print(f'任务完成：{day}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=date.fromisoformat, default=None)
    parser.add_argument('--node', default='node', help='Node.js executable for Youshu login')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--schedule', action='store_true', help='常驻运行，北京时间每天05:00执行')
    args = parser.parse_args()
    if args.schedule and (args.date is not None or args.dry_run):
        parser.error('--schedule 不能与 --date 或 --dry-run 一起使用')
    if args.date is None:
        args.date = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    if args.schedule:
        try:
            serve(node=args.node)
        except KeyboardInterrupt:
            print('定时模式已停止。', flush=True)
    elif args.dry_run:
        print(json.dumps(windows(args.date), indent=2))
    else:
        run(args.date, node=args.node)
