"""Independent whole-month, files-first orchestration reports."""
import argparse
import calendar
import json
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'storage/database.py').is_file())
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
    __package__ = 'metrics.opening.daily'

from metrics.opening import dedicated_line_metrics as dev
from metrics.opening import automation_intermediate as auto
from metrics.opening import process_log_backfill as logs
from metrics.opening.bycity import dedicated_line_metrics_by_city as citydev
from collector.orchestration import client
from . import calculate_development, calculate_automation, load_history, backfill_process_logs
from .split_evidence import dump, workbook, read_sources, split_workbooks, hashes, file_sha256
from .export_results import export


def dates(month):
    try:
        start = datetime.strptime(month, '%Y-%m')
        if start.strftime('%Y-%m') != month:
            raise ValueError()
    except ValueError:
        raise ValueError('--month必须为YYYY-MM') from None
    today = datetime.now(timezone(timedelta(hours=8))).date()
    end = start.date().replace(day=calendar.monthrange(start.year, start.month)[1])
    if end >= today:
        raise ValueError('仅允许已经结束的完整自然月')
    return start.date().isoformat(), end.isoformat()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--file', action='store_true', required=True)
    p.add_argument('--month', required=True)
    p.add_argument('--section', choices=('both', 'development', 'automation'), default='both')
    p.add_argument('--asset-csv', type=Path)
    p.add_argument('--county-map', type=Path, default=ROOT / 'metrics/terminal_recovery/区县信息汇总.xlsx')
    p.add_argument('--output-dir', type=Path, default=Path('D:/dev-projects/openclaw_data/outputs/opening'))
    p.add_argument('--cookie-file', type=Path, default=logs.COOKIE_FILE)
    group = p.add_mutually_exclusive_group()
    group.add_argument('--use-existing-cookie', action='store_true')
    group.add_argument('--skip-process-log', action='store_true', help='仅模拟核验，不作为完成回填的正式结果')
    p.add_argument('--input-dir', type=Path, help='重放本地编排文件目录，替代在线取数；只放本月编排文件')
    p.add_argument('--history-file', type=Path, help='重放既有evidence/history/history.json，替代MySQL查询')
    return p


def publish(stage, root, batch):
    moves = []
    old = stage / 'previous_raw'
    had_raw = (root / 'raw').exists()
    try:
        if had_raw:
            (root / 'raw').rename(old)
        for source, destination in ((stage / 'raw', root / 'raw'),
                                    (stage / 'evidence', root / 'evidence' / batch),
                                    (stage / 'results', root / 'results' / batch)):
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
            moves.append((source, destination))
    except OSError:
        for source, destination in reversed(moves):
            destination.rename(source)
        if had_raw:
            old.rename(root / 'raw')
        raise


def run(args, fetch_logs=None):
    start, end = dates(args.month)
    want_dev = args.section in ('both', 'development')
    want_auto = args.section in ('both', 'automation')
    if want_auto and (not args.asset_csv or not args.asset_csv.is_file()):
        raise ValueError('自动率必须提供当月 --asset-csv')
    mapping = citydev.load_county_mapping(args.county_map)
    if any(c.removesuffix('市') not in mapping['standards'] for c in dev.CITY_ORDER):
        raise ValueError('区县映射表必须覆盖11个地市')
    if want_auto and args.use_existing_cookie and fetch_logs is None:
        logs.read_cookie_file(args.cookie_file)  # fail before expensive collection
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    batch = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d_') + uuid.uuid4().hex[:12]
    lock = root / '.lock'
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError:
        raise RuntimeError(f'已有运行锁：{lock}，确认无进程后再处理') from None
    try:
        with handle:
            handle.write(batch)
        with tempfile.TemporaryDirectory(prefix='.opening-', dir=root) as temporary:
            stage = Path(temporary)
            raw = stage / 'raw' / 'orchestration'
            evidence, results = stage / 'evidence', stage / 'results'
            raw.mkdir(parents=True)
            evidence.mkdir()
            results.mkdir()
            meta = {'batch_id': batch, 'month': args.month, 'start': start, 'end': end,
                    'section': args.section, 'database_mode': 'read_only_history',
                    'replay': bool(args.input_dir or args.history_file or fetch_logs),
                    'rule_version': auto.AUTOMATION_RULE_VERSION, 'status': 'running'}
            try:
                if args.input_dir:
                    paths = sorted(p for p in args.input_dir.rglob('*')
                                   if p.suffix.lower() in ('.xlsx', '.xls', '.csv') and not p.name.startswith('~$'))
                    if not paths:
                        raise ValueError('本地输入目录没有编排文件')
                    for n, source in enumerate(paths):
                        shutil.copy2(source, raw / f'{n:03d}_{source.name}')
                else:
                    dev.log(f'开始文件取数：{start}至{end}')
                    token, cookie = client.environment_credentials()
                    client.collect('opening', start, end, mode='file', output_dir=raw,
                                   overwrite=True, zytoken=token, cookie=cookie)
                paths = sorted(p for p in raw.rglob('*') if p.suffix.lower() in ('.xlsx', '.xls', '.csv'))
                if not paths:
                    raise ValueError('取数未生成文件')
                shutil.copytree(stage / 'raw', evidence / 'raw')
                refs = evidence / 'references'
                refs.mkdir()
                shutil.copy2(args.county_map, refs / '区县信息汇总.xlsx')
                if want_auto:
                    shutil.copy2(args.asset_csv, refs / '资管环节明细.csv')
                rows = list(read_sources(paths, args.month, mapping, want_auto))
                meta['raw_rows'] = len(rows)
                dev.log(f'编排文件读取完成：{len(rows)}行，开始区县清洗及分地市归档')
                # Each original remains in evidence/raw; cleaned versions are separate and traceable.
                split_workbooks(evidence / 'raw' / '已清洗', rows, '编排工单')
                if want_dev:
                    if args.history_file:
                        history = json.loads(args.history_file.read_text(encoding='utf-8-sig'))
                        required = {dev.shift_month(args.month, i) for i in range(-12, 0)}
                        present = {r['dimension'].get('month') for r in history['results']}
                        for m in present & required:
                            if not load_history.complete([r for r in history['results'] if r['dimension'].get('month') == m], m):
                                raise ValueError(f'重放历史汇总维度不完整：{m}')
                        history['missing_months'] = sorted(required - present)
                        history['results'] = [r for r in history['results'] if r['dimension'].get('month') in required]
                        dump(evidence / 'history' / 'history.json', history)
                    else:
                        history = load_history.load(args.month, mapping, evidence / 'history')
                    province, cities, intermediate, audit = calculate_development.calculate(rows, args.month, mapping, history)
                    split_workbooks(evidence / '业务发展', intermediate, '业务发展中间结果')
                    dump(evidence / '业务发展' / 'audit.json', audit)
                    export(results / '业务发展', province, cities, {**meta, 'status': 'partial_history' if history['missing_months'] else 'calculated'})
                    meta['development'] = audit
                if want_auto:
                    dev.log('开始构建自动率中间表')
                    intermediate, audit = calculate_automation.build(rows, refs / '资管环节明细.csv')
                    if args.skip_process_log:
                        log_audit = {'skipped': True, 'remaining_orders': sum(bool(auto.pending_asset_stages(r)) for r in intermediate)}
                    else:
                        log_audit = backfill_process_logs.backfill(intermediate, evidence / 'logs', args.cookie_file,
                                                                  args.use_existing_cookie, fetch=fetch_logs)
                    split_workbooks(evidence / '专线自动情况', intermediate, '专线自动率中间结果')
                    dump(evidence / '专线自动情况' / 'audit.json', {'build': audit, 'logs': log_audit})
                    if log_audit.get('failed_orders'):
                        raise RuntimeError('存在日志技术查询失败；保留失败批次证据，不发布结果，请更新凭证或排查接口')
                    province, cities = calculate_automation.calculate(intermediate, args.month, mapping)
                    status = 'incomplete_logs' if args.skip_process_log or log_audit.get('remaining_orders') else 'calculated'
                    export(results / '专线自动情况', province, cities, {**meta, 'status': status})
                    meta['automation'] = {'build': audit, 'logs': log_audit}
                meta['status'] = 'completed_with_gaps' if (meta.get('development', {}).get('missing_months') or
                    (want_auto and (args.skip_process_log or log_audit.get('remaining_orders')))) else 'completed'
                meta['files'] = hashes(evidence)
                meta['result_files'] = hashes(results)
                dump(evidence / 'manifest.json', meta)
                dump(results / 'manifest.json', meta)
                publish(stage, root, batch)
                return {'batch_id': batch, 'status': meta['status'], 'evidence': str(root / 'evidence' / batch),
                        'results': str(root / 'results' / batch)}
            except Exception as exc:
                meta.update(status='failed', error_type=type(exc).__name__)
                dump(evidence / 'manifest.json', meta)
                failed = root / 'failed' / batch
                failed.parent.mkdir(exist_ok=True)
                evidence.rename(failed)
                raise
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    print(json.dumps(run(parser().parse_args()), ensure_ascii=False, indent=2))
