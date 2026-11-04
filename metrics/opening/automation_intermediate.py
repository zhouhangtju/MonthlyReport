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
COLUMNS = ('订单号', '订单结束时间', '订单状态', '业务类型', '订单类型', '调整类型', '地市',
           *OPENING_CLEAN_FIELDS, '资源查询受理人', *ASSET_STAGES)
TABLE = 'intermediate_orchestration_orders'
AUTOMATION_RULE_VERSION = '3.11.0-log-no-data-slash'
STOP_RESUME_STAGES = [('受理', '受理人'), ('资源查询', '资源查询受理人'),
                      ('配置激活', '配置激活处理人'), ('报结', '报结人')]
MOVE_ADJUSTMENTS = ('移机', '部分移机', '内部移机')
INTERMEDIATE_ADJUSTMENTS = (*MOVE_ADJUSTMENTS, '停机', '复机')
BUSINESS_GROUPS = {
    'internet': ('互联网专线',),
    'mpls': ('MPLS-VPN专线',),
    'transmission': ('传输专线',),
    'video': ('行业视频MV专线',),
}
INTERMEDIATE_BUSINESSES = frozenset(business for group in BUSINESS_GROUPS.values() for business in group)


def clean(value):
    return '' if value is None else str(value).strip()


def automatic(value):
    return '自动' in clean(value)


def excluded_fields(row):
    """Raw slash fields for audit only; these no longer exclude the whole order."""
    fields = CLEAN_FIELDS_BY_ORDER_TYPE.get(clean(row.get('订单类型')), ())
    return [field for field in fields if clean(row.get(field)) == '/']


def stage_participates(value):
    """Only a nonblank handler other than the slash placeholder is a counted stage."""
    return clean(value) not in ('', '/')


def asset_handler(matches, stage):
    """Keep missing/blank handlers empty until explicit path rules are applied."""
    return clean(matches.get(stage, {}).get('处理人'))


def apply_asset_path_rules(row):
    """Fill only known non-passing stages; never overwrite an existing handler."""
    skipped = []
    if clean(row.get('订单类型')) == '变更' and clean(row.get('调整类型')) in ('停机', '复机'):
        skipped.extend(ASSET_STAGES)
    if clean(row.get('订单类型')) in ('开通', '变更'):
        skipped.append('组织资源释放')
    if clean(row.get('订单类型')) == '拆除':
        # 拆除不经过组网方案、资源反馈；只填空值，保留真实匹配处理人。
        skipped.extend(('组网方案', '资源反馈'))
    if clean(row.get('业务类型')) in ('互联网专线', 'MPLS-VPN专线', '传输专线'):
        skipped.append('归档审核')
    filled = []
    for stage in skipped:
        if not clean(row.get(stage)):
            row[stage] = '/'
            filled.append(stage)
    return filled


def pending_asset_stages(row):
    """An empty asset handler needs a log query; slash is not missing."""
    return [stage for stage in ASSET_STAGES if not clean(row.get(stage))]


def is_move_order(row):
    """Moves include exact 移机, 部分移机 and 内部移机 adjustment values."""
    if clean(row.get('订单类型')) != '变更':
        return False
    if '调整类型' in row:
        return clean(row.get('调整类型')) in MOVE_ADJUSTMENTS
    payload = row.get('source_payload')
    if not payload:
        return False
    try:
        source = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"变更工单{clean(row.get('订单号'))}的source_payload无效，无法确认调整类型") from exc
    if not isinstance(source, dict):
        raise ValueError('变更工单source_payload必须是对象，无法确认调整类型')
    return clean(source.get('调整类型')) in MOVE_ADJUSTMENTS


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


def aggregate(rows, month, business_prefix='internet'):
    from metrics.opening.dedicated_line_metrics import CITY_ORDER, result
    stage_totals, stage_counts, city_totals, city_counts = (Counter() for _ in range(4))
    for row in rows:
        kind = row['订单类型']
        if row['订单状态'] != '已完成' or row['业务类型'] not in BUSINESS_GROUPS[business_prefix] or kind not in STAGES:
            continue
        if kind == '变更' and not is_move_order(row):
            continue
        city = row['地市']
        for stage, field in STAGES[kind]:
            if not stage_participates(row.get(field)):
                continue
            stage_totals[kind, stage] += 1
            city_totals[kind, city, stage] += 1
            if automatic(row[field]):
                stage_counts[kind, stage] += 1
                city_counts[kind, city, stage] += 1
    output = []
    for kind, prefix in [('开通', 'opening'), ('变更', 'move'), ('拆除', 'removal')]:
        code = f'{business_prefix}_{prefix}_automation_rate'
        for stage, field in STAGES[kind]:
            output.append(result(code, 'month_stage', {'month': month, 'stage': stage, 'field': field,
                                 'automatic_value': '包含自动'}, stage_counts[kind, stage], stage_totals[kind, stage]))
            for city in CITY_ORDER:
                output.append(result(code, 'month_city_stage', {'month': month, 'city': city, 'stage': stage},
                                     city_counts[kind, city, stage], city_totals[kind, city, stage]))
        output.append(result(code, 'month_all_stages', {'month': month, 'stage': f'{len(STAGES[kind])}环节整体'},
                             sum(stage_counts[kind, s] for s, _ in STAGES[kind]),
                             sum(stage_totals[kind, s] for s, _ in STAGES[kind])))
        if kind != '开通':
            for city in [*CITY_ORDER, '全省合计']:
                n = stage_counts[kind, '配置激活'] if city == '全省合计' else city_counts[kind, city, '配置激活']
                d = stage_totals[kind, '配置激活'] if city == '全省合计' else city_totals[kind, city, '配置激活']
                output.append(result(f'{business_prefix}_{prefix}_activation_rate', 'month_city', {'month': month, 'city': city}, n, d))
    return output


def aggregate_stop_resume(rows, month, business_prefix):
    """Stop/resume is separate from moves and uses four orchestration stages."""
    from metrics.opening.dedicated_line_metrics import CITY_ORDER, result
    totals, autos, city_totals, city_autos = (Counter() for _ in range(4))
    for row in rows:
        if (row['订单状态'] != '已完成' or row['业务类型'] not in BUSINESS_GROUPS[business_prefix]
                or row['订单类型'] != '变更' or clean(row.get('调整类型')) not in ('停机', '复机')):
            continue
        city = row['地市']
        for stage, field in STOP_RESUME_STAGES:
            if not stage_participates(row.get(field)):
                continue
            totals[stage] += 1
            city_totals[city, stage] += 1
            if automatic(row[field]):
                autos[stage] += 1
                city_autos[city, stage] += 1
    code = f'{business_prefix}_stop_resume_automation_rate'
    output = []
    for stage, field in STOP_RESUME_STAGES:
        output.append(result(code, 'month_stage', {'month': month, 'stage': stage,
                             'field': field, 'automatic_value': '包含自动'}, autos[stage], totals[stage]))
        for city in CITY_ORDER:
            output.append(result(code, 'month_city_stage', {'month': month, 'city': city, 'stage': stage},
                                 city_autos[city, stage], city_totals[city, stage]))
    output.append(result(code, 'month_all_stages', {'month': month, 'stage': '4环节整体'},
                         sum(autos.values()), sum(totals.values())))
    for city in [*CITY_ORDER, '全省合计']:
        n = autos['配置激活'] if city == '全省合计' else city_autos[city, '配置激活']
        d = totals['配置激活'] if city == '全省合计' else city_totals[city, '配置激活']
        output.append(result(f'{business_prefix}_stop_resume_activation_rate', 'month_city',
                             {'month': month, 'city': city}, n, d))
    return output


def summarize_intermediate(database, month, build_id):
    """The same aggregation path for rebuilt and externally completed intermediates."""
    from pymysql.cursors import SSDictCursor
    fields = ','.join(f'`{field}`' for field in COLUMNS)
    results = []
    with connect(database) as source:
        with source._connection.cursor(SSDictCursor) as cursor:
            for prefix, business_types in BUSINESS_GROUPS.items():
                placeholders = ','.join(['%s'] * len(business_types))
                cursor.execute(f'SELECT {fields} FROM {TABLE} WHERE report_month=%s AND build_id=%s '
                               f'AND `业务类型` IN ({placeholders})', (month, build_id, *business_types))
                results.extend(aggregate(cursor, month, prefix))
                if prefix != 'video':
                    cursor.execute(f'SELECT {fields} FROM {TABLE} WHERE report_month=%s AND build_id=%s '
                                   f'AND `业务类型` IN ({placeholders}) AND `订单类型`=%s '
                                   'AND `调整类型` IN (%s,%s)',
                                   (month, build_id, *business_types, '变更', '停机', '复机'))
                    results.extend(aggregate_stop_resume(cursor, month, prefix))
    return results


def write_automation_outputs(results, audit, output_dir):
    output_dir = Path(output_dir)
    month = audit['month']
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


def build(database, month, asset_csv, output_dir, batch_size=5000, process_log_cookie=None):
    from pymysql.cursors import SSDictCursor
    from metrics.opening.dedicated_line_metrics import shift_month, log
    asset_csv = Path(asset_csv).resolve()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    build_id = uuid.uuid4().hex
    audit = {'month': month, 'build_id': build_id, 'asset_csv': str(asset_csv),
             'rule_version': AUTOMATION_RULE_VERSION,
             'intermediate_business_filter': sorted(INTERMEDIATE_BUSINESSES),
             'move_filter': '移机统计：订单类型=变更，调整类型为移机、部分移机、内部移机；先筛选后关联资管',
             'intermediate_change_filter': '变更保留移机、部分移机、内部移机、停机、复机；停机复机不计入移机指标',
             'denominator_rule': '各环节仅统计处理人非空且不等于/的次数；整体分母为各环节分母之和',
             'asset_missing_rule': '资管缺失先留空；变更停机复机四个资管环节空值填/；开通和全部变更组织资源释放空值填/；拆除组网方案和资源反馈空值填/；互联网、MPLS-VPN、传输专线归档审核空值填/；其他空值待查询，不处理资源查询列',
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
            counts = Counter()
            excluded_types, slash_columns = Counter(), Counter()
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
                            if clean(row.get('业务类型')) not in INTERMEDIATE_BUSINESSES:
                                counts['excluded_rows'] += 1
                                counts['excluded_other_businesses'] += 1
                                excluded_types[clean(row.get('订单类型'))] += 1
                                writer.writerow([clean(row.get('订单号')), row.get('订单类型'), row.get('业务类型'),
                                                 '业务类型不属于互联网专线、MPLS-VPN专线、传输专线、行业视频MV专线'])
                                continue
                            invalid = excluded_fields(row)
                            if invalid:
                                counts['orders_with_slash_fields'] += 1
                                slash_columns.update(invalid)
                            key = clean(row.get('订单号'))
                            if not key:
                                counts['excluded_rows'] += 1
                                excluded_types[clean(row.get('订单类型'))] += 1
                                writer.writerow([key, row.get('订单类型'), row.get('业务类型'), '订单号为空'])
                                continue
                            if clean(row.get('订单类型')) == '变更' and clean(row.get('调整类型')) not in INTERMEDIATE_ADJUSTMENTS:
                                counts['excluded_rows'] += 1
                                counts['excluded_other_changes'] += 1
                                excluded_types['变更'] += 1
                                writer.writerow([key, row.get('订单类型'), row.get('业务类型'),
                                                 '变更工单调整类型不属于移机、部分移机、内部移机、停机、复机'])
                                continue
                            cache.execute('INSERT OR REPLACE INTO orders VALUES (?,?)',
                                          (key, json.dumps(row, ensure_ascii=False, default=str)))
                        cache.commit()
            counts['intermediate_rows'] = cache.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
            counts.update(load_assets(cache, asset_csv))
            log(f'原始工单筛选完成：保留{counts["intermediate_rows"]}单；资管环节索引完成：{counts["csv_unique_order_stages"]}组')
            matched, unmatched = Counter(), Counter()
            columns_sql = ','.join(f'`{c}` LONGTEXT' for c in COLUMNS if c != '订单号')
            review_path = output_dir / f'专线自动率中间表_{month}.csv'
            with connect(database) as destination:
                destination.execute(f'CREATE TABLE IF NOT EXISTS {TABLE} (report_month CHAR(7) NOT NULL, build_id CHAR(32) NOT NULL, '
                                    f'`订单号` VARCHAR(255) NOT NULL,{columns_sql},source_payload LONGTEXT NOT NULL,asset_matches LONGTEXT NOT NULL,'
                                    'PRIMARY KEY(report_month,`订单号`)) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin')
                existing_columns = {item['Field'] for item in destination.execute(f'SHOW COLUMNS FROM {TABLE}').fetchall()}
                if '调整类型' not in existing_columns:
                    destination.execute(f'ALTER TABLE {TABLE} ADD COLUMN `调整类型` LONGTEXT AFTER `订单类型`')
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
                            row[stage] = asset_handler(matches, stage)
                            if not row[stage]:
                                counts[f'asset_missing_before_path_{stage}'] += 1
                            (matched if stage in matches else unmatched)[stage] += 1
                        for stage in apply_asset_path_rules(row):
                            counts[f'asset_path_slash_{stage}'] += 1
                        missing_stages = pending_asset_stages(row)
                        if missing_stages:
                            counts['pending_process_log_orders'] += 1
                        for stage in missing_stages:
                            counts[f'asset_pending_{stage}'] += 1
                        details = json.dumps(matches, ensure_ascii=False)
                        values = [row[c] for c in COLUMNS]
                        writer.writerow([*values, details])
                        pending.append((month, build_id, *values, payload, details))
                        if len(pending) >= batch_size:
                            destination.executemany(sql, pending)
                            pending.clear()
                    if pending:
                        destination.executemany(sql, pending)
            if process_log_cookie is not None:
                from metrics.opening.process_log_backfill import backfill

                process_log_audit = backfill(database, month, build_id, process_log_cookie)
                audit['process_log_backfill'] = {key: value for key, value in process_log_audit.items()
                                                 if key != 'details'}
                (output_dir / f'流程日志补齐明细_{month}.json').write_text(
                    json.dumps(process_log_audit, ensure_ascii=False, indent=2), encoding='utf-8')
            if process_log_cookie is not None:
                # The review CSV must show the committed post-fill handlers.
                with connect(database) as source, review_path.open('w', encoding='utf-8-sig', newline='') as target:
                    writer = csv.writer(target)
                    writer.writerow([*COLUMNS, '资管关联明细'])
                    with source._connection.cursor(SSDictCursor) as cursor:
                        cursor.execute(f'SELECT * FROM {TABLE} WHERE report_month=%s AND build_id=%s ORDER BY `订单号`',
                                       (month, build_id))
                        while batch := cursor.fetchmany(batch_size):
                            for row in batch:
                                writer.writerow([*(row[column] for column in COLUMNS), row['asset_matches']])
            # Compute only from the committed intermediate rows of this build.
            results = summarize_intermediate(database, month, build_id)
            audit['business_groups'] = BUSINESS_GROUPS
            audit.update(counts=dict(counts), matched={s: matched[s] for s in ASSET_STAGES},
                         unmatched={s: unmatched[s] for s in ASSET_STAGES},
                         excluded_by_order_type=dict(excluded_types), slash_by_column=dict(slash_columns),
                         intermediate_csv=str(review_path.resolve()), excluded_csv=str(excluded_path.resolve()))
            write_automation_outputs(results, audit, output_dir)
            return results, audit
        finally:
            cache.close()
