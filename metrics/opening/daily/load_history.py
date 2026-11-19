"""Historical inputs only: read-only MySQL snapshot, no initialize/DDL/DML."""
import json
from pathlib import Path
from storage import database
from metrics.opening import dedicated_line_metrics as dev
from metrics.opening.bycity import dedicated_line_metrics_by_city as citydev
from .calculate_development import Volumes
from .split_evidence import dump


def complete(items, month):
    keys = {(r['metric_code'], r['dimension_type'], r['dimension'].get('city'),
             r['dimension'].get('product')) for r in items if r.get('numerator') is not None}
    expected = {('other_internet_opening_orders', 'month', None, None)}
    for _, code, products in citydev.BUSINESS_GROUPS:
        expected.add((code, 'month', None, None))
        expected.update((code, 'month_product', None, p) for p in products)
        for city in dev.CITY_ORDER:
            expected.add((code, 'month_city', city, None))
            expected.update((code, 'month_city_product', city, p) for p in products)
    return expected <= keys


def load(month, mapping, directory):
    import pymysql
    from pymysql.cursors import DictCursor
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    results, missing, sources = [], [], {}
    connection = pymysql.connect(**database._config(), cursorclass=DictCursor)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            cursor.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            for offset in range(-12, 0):
                period = dev.shift_month(month, offset)
                dev.log(f'只读加载历史数据：{period}')
                try:
                    cursor.execute('SELECT metric_code,dimension_type,dimension_value,numerator,denominator,metric_value '
                                   'FROM orch_opening_monthly_summary WHERE metric_version=%s AND month=%s',
                                   (dev.METRIC_VERSION, period))
                    summary = []
                    for row in cursor.fetchall():
                        row['dimension'] = json.loads(row.pop('dimension_value'))
                        summary.append(row)
                except pymysql.err.ProgrammingError as exc:
                    if exc.args[0] != 1146:
                        raise
                    summary = []
                if complete(summary, period):
                    results.extend(summary)
                    sources[period] = 'orch_opening_monthly_summary'
                    dump(directory / f'{period}_汇总.json', summary)
                    continue
                count = 0
                volumes = Volumes(month, mapping)
                # Buffered keyset pages avoid a long idle streaming cursor during local calculation.
                def pages():
                    nonlocal count
                    last = ''
                    with (directory / f'{period}_原始.jsonl').open('w', encoding='utf-8') as target:
                        while True:
                            cursor.execute('SELECT ' + ','.join(f'`{c}`' for c in dev.READ_COLUMNS) +
                                           ' FROM orch_opening WHERE `订单号`>%s AND `订单结束时间` >= %s '
                                           'AND `订单结束时间` < %s ORDER BY `订单号` LIMIT 5000',
                                           (last, period + '-01', dev.shift_month(period, 1) + '-01'))
                            batch = cursor.fetchall()
                            if not batch:
                                break
                            last = batch[-1]['订单号']
                            count += len(batch)
                            for row in batch:
                                target.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
                            yield batch
                computed, _ = dev.summarize_month(pages(), period, city_volumes=volumes)
                if count:
                    computed.extend(r for group in volumes.by_city.values() for r in group)
                    results.extend(computed)
                    sources[period] = 'orch_opening'
                else:
                    missing.append(period)  # no rows is not evidence of a verified zero month
                    sources[period] = 'missing'
    finally:
        connection.rollback()
        connection.close()
    data = {'results': results, 'missing_months': missing, 'sources': sources}
    dump(directory / 'history.json', data)
    return data
