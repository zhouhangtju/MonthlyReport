"""自然月企宽开通量、同比与累计同比；输入为 MySQL 完整采集快照。"""
import argparse
import calendar
from datetime import date
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from storage import youshu_install_completed as source
from storage.database import connect
from storage.metric_results import insert_results

ROOT = Path(__file__).resolve().parents[2]
METRIC_CODE = 'qikuan_opening_metrics'
VERSION = '1.1.0'
CITY_ORDER = '杭州 湖州 嘉兴 金华 丽水 宁波 衢州 绍兴 台州 温州 舟山'.split()
COUNT_KEYS = ('current_month', 'previous_month', 'current_ytd', 'previous_ytd')


def shifted_month(month, offset):
    year, number = map(int, month.split('-'))
    absolute = year * 12 + number - 1 + offset
    year, zero_based = divmod(absolute, 12)
    return f'{year:04d}-{zero_based + 1:02d}'


def monthly_bounds(month):
    year, number = map(int, month.split('-'))
    return date(year, number, 1).isoformat(), date(year, number, calendar.monthrange(year, number)[1]).isoformat()


def rolling_months(month, count=12):
    return [shifted_month(month, offset) for offset in range(1-count, 1)]


def periods(month):
    if not re.fullmatch(r'\d{4}-\d{2}', month):
        raise ValueError('月份必须为 YYYY-MM')
    year, number = map(int, month.split('-'))
    date(year, number, 1)
    if year < 2:
        raise ValueError('报告年份必须存在有效的上一年')
    result = {}
    for role, y, first in [('current_month', year, number), ('previous_month', year-1, number),
                            ('current_ytd', year, 1), ('previous_ytd', year-1, 1)]:
        result[role] = (date(y, first, 1).isoformat(), date(y, number, calendar.monthrange(y, number)[1]).isoformat())
    return result


class MissingPeriods(ValueError):
    def __init__(self, missing):
        self.missing = missing
        super().__init__('缺少完整成功的源数据周期：' + '；'.join(f'{s} 至 {e}' for s, e in missing))


def load_sources(month, cumulative_mode='exact'):
    if cumulative_mode not in ('exact', 'monthly_sum'):
        raise ValueError('cumulative_mode 必须为 exact 或 monthly_sum')
    roles = periods(month)
    trend_bounds = {value: monthly_bounds(value) for value in rolling_months(month)}
    required = list(dict.fromkeys([*roles.values(), *trend_bounds.values()]))
    if cumulative_mode == 'monthly_sum':
        required = list(dict.fromkeys([
            *[(date(y,n,1).isoformat(),date(y,n,calendar.monthrange(y,n)[1]).isoformat())
              for y in (int(month[:4]),int(month[:4])-1) for n in range(1,int(month[-2:])+1)],
            *trend_bounds.values(),
        ]))
    cached, missing = {}, []
    for bounds in required:
        try:
            cached[bounds] = source.load_latest_city(*bounds)
        except ValueError as exc:
            if str(exc) != '该统计周期没有完整成功的报结量数据':
                raise
            missing.append(bounds)
    if missing:
        raise MissingPeriods(missing)
    if cumulative_mode == 'exact':
        result = {role: cached[bounds] for role, bounds in roles.items()}
        result['monthly_trend'] = {value: cached[bounds] for value, bounds in trend_bounds.items()}
        return result
    result = {role: cached[roles[role]] for role in ('current_month','previous_month')}
    for role in ('current_ytd','previous_ytd'):
        start,end = roles[role]
        totals = {city:0 for city in CITY_ORDER}
        batches = []
        for bounds in required:
            if bounds[0] < start or bounds[1] > end:
                continue
            snapshot = cached[bounds]
            values = city_values(snapshot,*bounds)
            for city in totals:
                totals[city] += values[city]
            batches.append({'period_start':bounds[0],'period_end':bounds[1],
                            'collection_run_id':snapshot['collection_run_id'],
                            'dataset_code':snapshot.get('dataset_code')})
        # Derived rows are in-memory only, never presented as a collected platform snapshot.
        result[role] = {'collection_run_id':None,'method':'monthly_sum','source_batches':batches,
            'city':[{'city':c,'completed_order_count':v,'period_start':start,'period_end':end,
                     'collection_run_id':None} for c,v in totals.items()]}
    result['monthly_trend'] = {value: cached[bounds] for value, bounds in trend_bounds.items()}
    return result


def city_values(snapshot,start,end):
    values = {}
    for row in snapshot['city']:
        city = row['city']
        if city in values or city not in source.CITIES:
            raise ValueError(f'{start} 地市重复或未知：{city}')
        if str(row['period_start']) != start or str(row['period_end']) != end or row['collection_run_id'] != snapshot['collection_run_id']:
            raise ValueError(f'{start} 源数据周期或批次不一致')
        values[city] = source.count_value(row['completed_order_count'])
    if set(values) != source.CITIES:
        raise ValueError(f'{start} 未覆盖全省11地市')
    return values


def growth(current, previous):
    return (current - previous) / previous if previous else None


def rate_text(value):
    if value is None:
        return '—（同期基数为0）'
    if value == 0:
        return '持平'
    return ('上升' if value > 0 else '下降') + f'{abs(value):.2%}'


def calculate(month, snapshots):
    bounds = periods(month)
    data, provenance = {}, {}
    for role, (start, end) in bounds.items():
        snapshot = snapshots[role]
        run_id = snapshot['collection_run_id']
        values = city_values(snapshot,start,end)
        values['全省'] = sum(values.values())
        data[role] = values
        provenance[role] = {'period_start': start, 'period_end': end, 'collection_run_id': run_id,
            'method':snapshot.get('method','exact'), 'dataset_code':snapshot.get('dataset_code')}
        if 'source_batches' in snapshot:
            provenance[role]['source_batches'] = snapshot['source_batches']
    trend = []
    trend_sources = []
    for trend_month, snapshot in snapshots.get('monthly_trend', {}).items():
        start, end = monthly_bounds(trend_month)
        values = city_values(snapshot, start, end)
        total = sum(values.values())
        trend.append({'month': trend_month, 'value': total})
        trend_sources.append({'month': trend_month, 'period_start': start, 'period_end': end,
                              'collection_run_id': snapshot['collection_run_id'],
                              'dataset_code': snapshot.get('dataset_code')})
    if trend and [item['month'] for item in trend] != rolling_months(month):
        raise ValueError('近12个月趋势月份不连续或顺序不正确')
    provenance['monthly_trend'] = trend_sources
    summaries, results = [], []
    for city in ['全省', *CITY_ORDER]:
        item = {'city': city, **{key: data[key][city] for key in COUNT_KEYS}}
        item['yoy'] = growth(item['current_month'], item['previous_month'])
        item['ytd_yoy'] = growth(item['current_ytd'], item['previous_ytd'])
        item['yoy_status'] = 'zero_base' if item['yoy'] is None else 'ok'
        item['ytd_yoy_status'] = 'zero_base' if item['ytd_yoy'] is None else 'ok'
        summaries.append(item)
        dimension = {'month': month, 'scope': '全省'} if city == '全省' else {'month': month, 'city': city}
        for key in (*COUNT_KEYS, 'yoy', 'ytd_yoy'):
            if key in COUNT_KEYS:
                numerator, denominator = item[key], None
            else:
                current, previous = ('current_month', 'previous_month') if key == 'yoy' else ('current_ytd', 'previous_ytd')
                numerator, denominator = item[current]-item[previous], item[previous]
            results.append({'metric_code': f'qikuan_opening_{key}',
                'dimension_type': 'province' if city == '全省' else 'city', 'dimension': dimension,
                'numerator': numerator, 'denominator': denominator, 'metric_value': item[key]})
    for item in trend:
        results.append({'metric_code': 'qikuan_opening_monthly_trend', 'dimension_type': 'trend_month',
                        'dimension': {'month': item['month']}, 'numerator': item['value'],
                        'denominator': None, 'metric_value': item['value']})
    province, cities = summaries[0], summaries[1:]
    def city_text(key):
        groups = [('下降', [f"{r['city']}{abs(r[key]):.2%}" for r in cities if r[key] is not None and r[key] < 0]),
                  ('上升', [r['city'] for r in cities if r[key] is not None and r[key] > 0]),
                  ('持平', [r['city'] for r in cities if r[key] == 0]),
                  ('同期基数为0', [r['city'] for r in cities if r[key] is None])]
        if len(groups[1][1]) == 11:
            return '所有地市均上升'
        return '；'.join(label + '：' + '、'.join(names) for label, names in groups if names)
    number = int(month[-2:])
    return {'metric_code': METRIC_CODE, 'metric_version': VERSION, 'month': month,
        'period_start': bounds['current_month'][0], 'period_end': bounds['current_month'][1],
        'sources': provenance, 'rate_unit': 'ratio', 'province': province, 'cities': cities,
        'trend': {'months': [item['month'] for item in trend],
                  'values': [item['value'] for item in trend],
                  'total': sum(item['value'] for item in trend) if trend else None,
                  'average': sum(item['value'] for item in trend) / len(trend) if trend else None},
        'results': results, 'narratives': {
            'monthly': f"{number}月企宽开通{province['current_month']}条，同比{rate_text(province['yoy'])}；{city_text('yoy')}。",
            'ytd': f"1—{number}月累计开通{province['current_ytd']}条，累计同比{rate_text(province['ytd_yoy'])}；{city_text('ytd_yoy')}。"},
        'charts': {'province': {'labels': [f'{int(month[:4])-1}.{number:02}', f'{month[:4]}.{number:02}',
                    f'{int(month[:4])-1}.01—{number:02}', f'{month[:4]}.01—{number:02}'],
                    'values': [province[k] for k in ('previous_month','current_month','previous_ytd','current_ytd')]},
                   'city': {'labels': CITY_ORDER, 'yoy': [r['yoy'] for r in cities], 'ytd_yoy': [r['ytd_yoy'] for r in cities]}}}


def save(report):
    schema = (ROOT / 'sql/create_result_qikuan_opening.sql').read_text('utf-8')
    with connect() as conn:
        conn.executescript(schema)
    run_id = 'qikuan_opening_' + uuid.uuid4().hex
    with connect() as conn:
        conn.execute('''INSERT INTO metric_run (metric_run_id,metric_code,metric_version,
            period_start,period_end,started_at,status,source_runs)
            VALUES (?,?,?,?,?,?,'running',?)''', (run_id, METRIC_CODE, VERSION,
            report['period_start'], report['period_end'], source.now(),
            json.dumps(report['sources'], ensure_ascii=False)))
    try:
        with connect() as conn:
            insert_results(conn, METRIC_CODE, run_id, report['results'])
            conn.execute("UPDATE metric_run SET status='success',finished_at=? WHERE metric_run_id=?", (source.now(), run_id))
    except Exception as exc:
        with connect() as conn:
            conn.execute("UPDATE metric_run SET status='failed',finished_at=?,error_message=? WHERE metric_run_id=?",
                         (source.now(), str(exc), run_id))
        raise
    return run_id


def run(month, mode='both', output=None, cumulative_mode='exact'):
    if mode not in ('file', 'database', 'both'):
        raise ValueError('mode 必须是 file、database 或 both')
    if mode == 'database' and output is not None:
        raise ValueError('database 模式不接受 --output，请使用 both 或 file')
    report = calculate(month, load_sources(month,cumulative_mode))
    report['cumulative_mode'] = cumulative_mode
    report['metric_run_id'] = save(report) if mode != 'file' else None
    path = None
    if mode != 'database':
        path = Path(output) if output else ROOT / 'data/results/qikuan_opening' / month / f"{report['metric_run_id'] or uuid.uuid4().hex}.json"
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        temp.replace(path)
    return {'month': month, 'metric_run_id': report['metric_run_id'], 'output': str(path) if path else None,
            'province': report['province'], 'sources': report['sources'], 'result_rows': len(report['results'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month', required=True)
    parser.add_argument('--mode', choices=('file','database','both'), default='both')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cumulative-mode', choices=('exact','monthly_sum'),default='exact',
                        help='exact读取平台累计快照；monthly_sum按1至N月逐月相加（历史补录口径）')
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.month, args.mode, args.output,args.cumulative_mode), ensure_ascii=False, indent=2))
    except MissingPeriods as exc:
        print(json.dumps({'status': 'missing_source_periods', 'missing_periods': [
            {'start': s, 'end': e} for s, e in exc.missing]}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
