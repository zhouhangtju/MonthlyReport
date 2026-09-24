"""Build auditable monthly automation orders from orchestration and asset records."""
import csv
import hashlib
import json
import sqlite3
import tempfile
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from storage.database import connect

OPENING_CLEAN_FIELDS = (
    '受理人', '方案设计处理人', '资源分配受理人',
    '配置激活处理人', '开通结果审核处理人', '报结人',
)
REMOVAL_CLEAN_FIELDS = (
    '受理人', '资源查询受理人', '配置激活处理人',
    '开通结果审核处理人', '报结人',
)
CLEAN_FIELDS_BY_ORDER_TYPE = {
    '开通': OPENING_CLEAN_FIELDS,
    '变更': OPENING_CLEAN_FIELDS,
    '拆除': REMOVAL_CLEAN_FIELDS,
}
ASSET_STAGES = ('组网方案', '资源反馈', '组织资源释放', '归档审核')
OPENING = [('受理', '受理人'), ('方案设计', '方案设计处理人'), ('组网方案', '组网方案'),
           ('资源分配', '资源分配受理人'), ('资源反馈', '资源反馈'), ('配置激活', '配置激活处理人'),
           ('开通结果审核', '开通结果审核处理人'), ('归档审核', '归档审核'), ('报结', '报结人')]
REMOVAL = [('受理', '受理人'), ('资源查询', '资源查询受理人'), ('配置激活', '配置激活处理人'),
           ('开通结果审核', '开通结果审核处理人'), ('组织资源释放', '组织资源释放'), ('报结', '报结人')]
STAGES = {'开通': OPENING, '变更': OPENING, '拆除': REMOVAL}
COLUMNS = ('订单号', '订单结束时间', '订单状态', '业务类型', '订单类型', '地市',
           *OPENING_CLEAN_FIELDS, '资源查询受理人', *ASSET_STAGES)
TABLE = 'intermediate_orchestration_orders'


def clean(value):
    return '' if value is None else str(value).strip()


def automatic(value):
    return '自动' in clean(value)


def excluded_fields(row):
    fields = CLEAN_FIELDS_BY_ORDER_TYPE.get(clean(row.get('订单类型')), ())
    return [field for field in fields if clean(row.get(field)) == '/']


def timestamp(value):
    value = clean(value).replace('/', '-').replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).isoformat(' ', timespec='microseconds')
        except ValueError:
            pass
    raise ValueError(f'资管结束时间无效：{value!r}，无法判定最新记录')


def load_assets(cache, path):
    """Disk-backed latest-per-order/stage index; equal times use last CSV row."""
    encoding = 'utf-8-sig'
    try:
        with path.open(encoding=encoding) as source:
            for _ in source:
                pass
    except UnicodeDecodeError:
        encoding = 'gb18030'
    counts = Counter()
    with path.open(encoding=encoding, newline='') as source:
        reader = csv.DictReader(source)
        required = {'二级编排工单号', '环节名称', '结束时间', '处理人', '处理意见'}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'资管CSV缺少字段：{sorted(missing)}')
        for line, row in enumerate(reader, 2):
            counts['csv_rows'] += 1
            stage = clean(row['环节名称'])
            if stage not in ASSET_STAGES:
                continue
            key = clean(row['二级编排工单号'])
            if not key:
                counts['csv_empty_order'] += 1
                continue
            try:
                ended = timestamp(row['结束时间'])
            except ValueError as exc:
                raise ValueError(f'{path.name} 第{line}行：{exc}') from exc
            payload = json.dumps({'处理人': clean(row['处理人']), '处理意见': clean(row['处理意见']),
                                  '结束时间': ended, 'csv_line': line}, ensure_ascii=False)
            cache.execute('INSERT INTO assets VALUES (?,?,?,?) ON CONFLICT(order_no,stage) '
                          'DO UPDATE SET ended=excluded.ended,payload=excluded.payload '
                          'WHERE excluded.ended>=assets.ended', (key, stage, ended, payload))
            counts['csv_target_rows'] += 1
    cache.commit()
    counts['csv_unique_order_stages'] = cache.execute('SELECT COUNT(*) FROM assets').fetchone()[0]
    return counts


def aggregate(rows, month):
    from metrics.opening.dedicated_line_metrics import CITY_ORDER, result
    totals, stage_counts, city_totals, city_counts = (Counter() for _ in range(4))
    for row in rows:
        kind = row['订单类型']
        if row['订单状态'] != '已完成' or row['业务类型'] != '互联网专线' or kind not in STAGES:
            continue
        city = row['地市']
        totals[kind] += 1
        city_totals[kind, city] += 1
        for stage, field in STAGES[kind]:
            if automatic(row[field]):
                stage_counts[kind, stage] += 1
                city_counts[kind, city, stage] += 1
    output = []
    for kind, prefix in [('开通', 'opening'), ('变更', 'move'), ('拆除', 'removal')]:
        code = f'internet_{prefix}_automation_rate'
        for stage, field in STAGES[kind]:
            output.append(result(code, 'month_stage', {'month': month, 'stage': stage, 'field': field,
                                 'automatic_value': '包含自动'}, stage_counts[kind, stage], totals[kind]))
            for city in CITY_ORDER:
                output.append(result(code, 'month_city_stage', {'month': month, 'city': city, 'stage': stage},
                                     city_counts[kind, city, stage], city_totals[kind, city]))
        output.append(result(code, 'month_all_stages', {'month': month, 'stage': f'{len(STAGES[kind])}环节整体'},
                             sum(stage_counts[kind, s] for s, _ in STAGES[kind]), totals[kind] * len(STAGES[kind])))
        if kind != '开通':
            for city in [*CITY_ORDER, '全省合计']:
                n = stage_counts[kind, '配置激活'] if city == '全省合计' else city_counts[kind, city, '配置激活']
                d = totals[kind] if city == '全省合计' else city_totals[kind, city]
                output.append(result(f'internet_{prefix}_activation_rate', 'month_city', {'month': month, 'city': city}, n, d))
    return output


def build(database, month, asset_csv, output_dir, batch_size=5000):
    from pymysql.cursors import SSDictCursor
    from metrics.opening.dedicated_line_metrics import shift_month, log
    asset_csv = Path(asset_csv).resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    build_id = uuid.uuid4().hex
    audit = {'month': month, 'build_id': build_id, 'asset_csv': str(asset_csv),
             'same_time_rule': '结束时间相同保留CSV最后一行', 'counts': {}, 'matched': {}, 'unmatched': {}}
    with asset_csv.open('rb') as source:
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    audit['asset_sha256'] = digest.hexdigest()
    with tempfile.TemporaryDirectory(prefix='automation_') as temp:
        cache = sqlite3.connect(str(Path(temp) / 'stage.sqlite'))
        try:
            cache.executescript('CREATE TABLE assets(order_no TEXT,stage TEXT,ended TEXT,payload TEXT,PRIMARY KEY(order_no,stage));'
                                'CREATE TABLE orders(order_no TEXT PRIMARY KEY,payload TEXT);')
            counts = load_assets(cache, asset_csv)
            excluded_types, excluded_columns = Counter(), Counter()
            log(f'资管环节索引完成：{counts["csv_unique_order_stages"]}组')
            excluded_path = output_dir / f'自动率剔除工单_{month}.csv'
            with excluded_path.open('w', encoding='utf-8-sig', newline='') as excluded, connect(database) as source:
                writer = csv.writer(excluded)
                writer.writerow(['订单号', '订单类型', '业务类型', '剔除原因'])
                with source._connection.cursor(SSDictCursor) as cursor:
                    cursor.execute('SELECT * FROM orch_opening WHERE `订单结束时间` >= %s AND `订单结束时间` < %s ORDER BY `订单号`',
                                   (month + '-01', shift_month(month, 1) + '-01'))
                    while True:
                        batch = cursor.fetchmany(batch_size)
                        if not batch:
                            break
                        for row in batch:
                            counts['raw_month_rows'] += 1
                            invalid = excluded_fields(row)
                            key = clean(row.get('订单号'))
                            if invalid or not key:
                                counts['excluded_rows'] += 1
                                excluded_types[clean(row.get('订单类型'))] += 1
                                excluded_columns.update(invalid)
                                writer.writerow([key, row.get('订单类型'), row.get('业务类型'), ','.join(invalid) or '订单号为空'])
                                continue
                            cache.execute('INSERT OR REPLACE INTO orders VALUES (?,?)',
                                          (key, json.dumps(row, ensure_ascii=False, default=str)))
                        cache.commit()
            counts['intermediate_rows'] = cache.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
            matched, unmatched = Counter(), Counter()
            columns_sql = ','.join(f'`{c}` LONGTEXT' for c in COLUMNS if c != '订单号')
            review_path = output_dir / f'专线自动率中间表_{month}.csv'
            with connect(database) as destination:
                destination.execute(f'CREATE TABLE IF NOT EXISTS {TABLE} (report_month CHAR(7) NOT NULL, build_id CHAR(32) NOT NULL, '
                                    f'`订单号` VARCHAR(255) NOT NULL,{columns_sql},source_payload LONGTEXT NOT NULL,asset_matches LONGTEXT NOT NULL,'
                                    'PRIMARY KEY(report_month,`订单号`)) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
                destination.execute(f'DELETE FROM {TABLE} WHERE report_month=?', (month,))
                insert_columns = ('report_month', 'build_id', *COLUMNS, 'source_payload', 'asset_matches')
                sql = f'INSERT INTO {TABLE} (' + ','.join(f'`{c}`' for c in insert_columns) + ') VALUES (' + ','.join('?' for _ in insert_columns) + ')'
                pending = []
                with review_path.open('w', encoding='utf-8-sig', newline='') as target:
                    writer = csv.writer(target)
                    writer.writerow([*COLUMNS, '资管关联明细'])
                    for key, payload in cache.execute('SELECT order_no,payload FROM orders ORDER BY order_no'):
                        raw = json.loads(payload)
                        matches = {stage: json.loads(detail) for stage, detail in cache.execute('SELECT stage,payload FROM assets WHERE order_no=?', (key,))}
                        row = {c: clean(raw.get(c)) for c in COLUMNS}
                        for stage in ASSET_STAGES:
                            row[stage] = matches.get(stage, {}).get('处理人', '')
                            (matched if stage in matches else unmatched)[stage] += 1
                        details = json.dumps(matches, ensure_ascii=False)
                        values = [row[c] for c in COLUMNS]
                        writer.writerow([*values, details])
                        pending.append((month, build_id, *values, payload, details))
                        if len(pending) >= batch_size:
                            destination.executemany(sql, pending)
                            pending.clear()
                    if pending:
                        destination.executemany(sql, pending)
            # Compute only from the committed intermediate rows of this build.
            with connect(database) as source:
                with source._connection.cursor(SSDictCursor) as cursor:
                    cursor.execute(f'SELECT * FROM {TABLE} WHERE report_month=%s AND build_id=%s', (month, build_id))
                    results = aggregate(cursor, month)
            audit.update(counts=dict(counts), matched={s: matched[s] for s in ASSET_STAGES},
                         unmatched={s: unmatched[s] for s in ASSET_STAGES},
                         excluded_by_order_type=dict(excluded_types), excluded_by_column=dict(excluded_columns),
                         intermediate_csv=str(review_path.resolve()), excluded_csv=str(excluded_path.resolve()))
            (output_dir / f'专线自动率审计_{month}.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
            (output_dir / f'专线自动率结果_{month}.json').write_text(
                json.dumps({'month': month, 'audit': audit, 'results': results}, ensure_ascii=False, indent=2), encoding='utf-8')
            with (output_dir / f'专线自动率结果_{month}.csv').open('w', encoding='utf-8-sig', newline='') as target:
                writer = csv.writer(target)
                writer.writerow(['指标', '维度类型', '月份', '地市', '环节', '自动数', '总数', '自动率'])
                for item in results:
                    d = item['dimension']
                    writer.writerow([item['metric_code'], item['dimension_type'], month, d.get('city', '全省'),
                                     d.get('stage', '配置激活'), item['numerator'], item['denominator'],
                                     '' if item['metric_value'] is None else f'{item["metric_value"]:.6%}'])
            return results, audit
        finally:
            cache.close()
