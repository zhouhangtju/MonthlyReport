"""Read calculated offline metrics; never calculate from source workbooks here."""
import hashlib
import json
import math
from pathlib import Path

CITIES = ['杭州', '嘉兴', '宁波', '温州', '金华', '绍兴', '湖州', '台州', '衢州', '丽水', '舟山']
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / 'outputs' / 'manual_metrics'
WITHDRAWAL = 'dedicated_line_withdrawal_reasons_by_city'
AUTOMATION = 'internet_line_manual_automation'
REPEAT = 'qikuan_repeat_complaint_rate'
QIKUAN = 'qikuan_withdrawal_summary'
RETURN = 'qikuan_withdrawal_rate_by_city'
METRIC_SETS = {WITHDRAWAL, AUTOMATION, REPEAT, QIKUAN, RETURN}


def number(value, name, nullable=False):
    if value is None and nullable:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{name}: 必须为非负有限数值')
    return value


def count(value, name):
    value = number(value, name)
    if int(value) != value:
        raise ValueError(f'{name}: 数量必须为整数')
    return int(value)


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def check_rate(value, numerator, denominator, name):
    expected = ratio(numerator, denominator)
    if expected is None:
        if value not in (None, 0):
            raise ValueError(f'{name}: 零分母对应无数据')
        return None
    number(value, name)
    if not math.isclose(value, expected, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(f'{name}: 比率与分子分母不一致')
    return value


def city_array(values, cities, name):
    if not isinstance(values, list) or len(values) != len(cities):
        raise ValueError(f'{name}: 地市数组长度不一致')
    normalized = [c.removesuffix('市') for c in cities]
    if len(set(normalized)) != len(CITIES) or set(normalized) != set(CITIES):
        raise ValueError(f'{name}: 必须包含且仅包含11地市')
    return [values[normalized.index(c)] for c in CITIES]


def load_results(directory, month, required=METRIC_SETS):
    """Select one result per metric/month, rejecting ambiguous or corrupt input."""
    directory = Path(directory).resolve()
    found, audit = {}, []
    if not directory.is_dir():
        raise FileNotFoundError(f'手工结果目录不存在：{directory}')
    for path in sorted(directory.glob('*.json')):
        try:
            document = json.loads(path.read_text(encoding='utf-8-sig'))
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f'手工JSON无法解析：{path}') from exc
        if not isinstance(document, dict):
            raise ValueError(f'手工JSON顶层必须为对象：{path}')
        code = document.get('metric_set')
        if code not in METRIC_SETS:
            continue
        if document.get('report_month') != month:
            continue
        if code in found:
            raise ValueError(f'{month} 的 {code} 有多份结果，请仅保留一份')
        if document.get('schema_version') != '1.0':
            raise ValueError(f'不支持的手工结果版本：{path}')
        found[code] = document
        audit.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'metric_set': code, 'report_month': month,
                      'sources': document.get('sources', document.get('audit', {}).get('source_file'))})
    missing = set(required) - found.keys()
    if missing:
        raise ValueError(f'{month} 缺少手工结果（或月份不匹配）：{sorted(missing)}')
    return found, audit


def withdrawal_values(document):
    raw = document['ppt_overlay']['withdrawal']
    result = {}
    for prefix in ('network', 'customer', 'frontDesk', 'other'):
        values = city_array(raw[prefix+'Reasons'], document['dimensions']['cities'], prefix)
        result[prefix+'Reasons'] = [count(v, prefix) for v in values]
        result[prefix+'Count'] = count(raw[prefix+'Count'], prefix)
        if sum(values) != raw[prefix+'Count']:
            raise ValueError('专线原因地市合计与全省不一致')
    total = sum(result[p+'Count'] for p in ('network', 'customer', 'frontDesk', 'other'))
    if total != document['summary']['source_row_count']:
        raise ValueError('专线原因合计与源明细数不一致')
    for prefix in ('network', 'customer', 'frontDesk', 'other'):
        result[prefix+'Share'] = check_rate(raw[prefix+'Share'], result[prefix+'Count'], total, prefix)
    result['reasonTotal'] = total
    return result


def qikuan_values(document, combined):
    raw = document['ppt_overlay']['qikuanWithdrawal']
    result = dict(raw, cities=CITIES)
    fields = ['acceptedCounts', 'withdrawalCounts', 'rates']
    if combined:
        fields += ['returnCounts', 'cancellationCounts']
    for field in fields:
        result[field] = city_array(raw[field], raw['cities'], field)
        if field != 'rates':
            result[field] = [count(v, field) for v in result[field]]
    for field, total in [('acceptedCounts', 'acceptedTotal'), ('withdrawalCounts', 'withdrawalTotal')]:
        if sum(result[field]) != count(raw[total], total):
            raise ValueError(f'{field} 地市合计与全省不一致')
    for i, city in enumerate(CITIES):
        result['rates'][i] = check_rate(result['rates'][i], result['withdrawalCounts'][i], result['acceptedCounts'][i], city)
        if result['withdrawalCounts'][i] > result['acceptedCounts'][i]:
            raise ValueError(f'{city} 撤退量大于受理量')
        if combined and result['returnCounts'][i] + result['cancellationCounts'][i] != result['withdrawalCounts'][i]:
            raise ValueError(f'{city} 撤单+退单不等于撤退量')
    result['overallRate'] = check_rate(raw['overallRate'], raw['withdrawalTotal'], raw['acceptedTotal'], '全省企宽')
    if sum(count(v['count'], '原因') for v in raw['reasons'].values()) != raw['withdrawalTotal']:
        raise ValueError('企宽原因数量与撤退总量不一致')
    for reason in raw['reasons'].values():
        check_rate(reason['share'], reason['count'], raw['withdrawalTotal'], '原因占比')
    result['topThreeRateCities'] = sorted(
        [{'city': c, 'rate': r} for c, r in zip(CITIES, result['rates']) if r is not None],
        key=lambda x: (-x['rate'], CITIES.index(x['city'])))[:3]
    return result


def apply_results(data, documents, audit, db):
    """Only explicitly mapped fields can override the database presentation model."""
    filled = set()
    if WITHDRAWAL in documents:
        values = withdrawal_values(documents[WITHDRAWAL])
        data['withdrawal'].update(values)
        filled.update('withdrawal.'+k for k in values)
    if QIKUAN in documents:
        data['qikuanWithdrawal'] = qikuan_values(documents[QIKUAN], True)
    if RETURN in documents:
        data['qikuanReturn'] = qikuan_values(documents[RETURN], False)
    if QIKUAN in documents and RETURN in documents:
        a, b = data['qikuanWithdrawal'], data['qikuanReturn']
        if a['acceptedCounts'] != b['acceptedCounts'] or a['returnCounts'] != b['withdrawalCounts']:
            raise ValueError('企宽撤退和退单结果的分母或退单数不一致')
    if AUTOMATION in documents:
        document = documents[AUTOMATION]
        mappings = [('开通', '组网方案', 'internetAuto', 'network'),
                    ('移机', '组网方案', 'internetMoveAuto', 'network'),
                    ('移机', '资源反馈', 'internetMoveAuto', 'resource'),
                    ('拆机', '组织资源释放', 'internetRemovalAuto', 'release')]
        for action, stage, target, name in mappings:
            metric = document['metrics'][f'互联网专线-{action}-{stage}自动率']
            rows = {c.removesuffix('市'): v for c, v in metric['地市'].items()}
            if set(rows) - set(CITIES):
                raise ValueError('自动率存在未知地市')
            ns, ds, rates = [], [], []
            for city in CITIES:
                row = rows.get(city, {'自动工单数': 0, '目标环节工单数': 0, '自动率': None})
                n, d = count(row['自动工单数'], city), count(row['目标环节工单数'], city)
                if n > d:
                    raise ValueError('自动工单数超过目标环节工单数')
                ns.append(n); ds.append(d); rates.append(check_rate(row['自动率'], n, d, city))
            province = metric['全省']
            if sum(ns) != province['自动工单数'] or sum(ds) != province['目标环节工单数']:
                raise ValueError('自动率全省与地市数量不一致')
            data[target][name] = {'cities': CITIES, 'numerators': ns, 'denominators': ds, 'rates': rates,
                                  'rate': check_rate(province['自动率'], sum(ns), sum(ds), name)}
        reasons = document['opening_network_nonautomatic_reasons']
        rows = {c.removesuffix('市'): v for c, v in reasons['地市'].items()}
        values = [count(rows.get(c, {}).get('工程施工工单数', 0), c) for c in CITIES]
        if sum(values) != reasons['全省']['工程施工工单数']:
            raise ValueError('工程施工数量合计不一致')
        data['internetAuto']['manualReasons'] = {'cities': CITIES, 'constructionCounts': values,
                                                 'province': reasons['全省'], 'byCity': rows}
    if REPEAT in documents:
        document = documents[REPEAT]
        rows = {c.removesuffix('市'): v for c, v in document['cities'].items()}
        for c, row in rows.items():
            check_rate(row['rate'], count(row['numerator'], c), count(row['denominator'], c), c)
        province = document['province']
        for field in ('numerator', 'denominator'):
            if sum(r[field] for r in rows.values()) != province[field]:
                raise ValueError('企宽投诉全省与全部地市（含其他）数量不一致')
        check_rate(province['rate'], province['numerator'], province['denominator'], '企宽投诉')
        repeat = data['complaintFault']['repeat']
        repeat['qikuanRates'] = [rows[c]['rate'] if c in rows else None for c in CITIES]
        repeat['qikuanAverage'] = province['rate']
        repeat['qikuanPeriod'] = document['report_month']
        repeat['qikuanHighNames'] = sorted([c for c in CITIES if c in rows and rows[c]['rate'] is not None], key=lambda c: -rows[c]['rate'])[:3]
        code = 'dedicated_line_repeat_complaint_rate'
        combined_audit = []
        def combined(kind, manual, **dims):
            row = db.find(code, code, kind, **dims)
            if row is None or manual is None or any(row.get(f) is None for f in ('numerator', 'denominator')):
                return None
            n = number(row['numerator'], '专线分子') + manual['numerator']
            d = number(row['denominator'], '专线分母') + manual['denominator']
            combined_audit.append(dict(dims, numerator=n, denominator=d, rate=ratio(n,d),
                                       line_run_id=row['metric_run_id'], line_numerator=row['numerator'],
                                       line_denominator=row['denominator'], qikuan_numerator=manual['numerator'],
                                       qikuan_denominator=manual['denominator']))
            return ratio(n, d)
        repeat['totalRates'] = [combined('city', rows.get(c), city=c) for c in CITIES]
        repeat['totalAverage'] = combined('province', province, scope='全省')
        for field in ('totalRates', 'totalAverage'):
            filled.add('complaintFault.repeat.'+field)
        audit['derived_results']['complaintFault.repeat.combined'] = {
            'formula': '(专线分子+企宽分子)/(专线分母+企宽分母)，千里眼不参与',
            'period_note': '专线使用已选数据库周期；企宽使用月报当月分母及历史月份判重；按用户指定口径合计',
            'values': combined_audit, 'other_cities': {k:v for k,v in rows.items() if k not in CITIES}}
        if repeat['totalAverage'] is None or any(v is None for v in repeat['totalRates']):
            audit['missing'].append({'ppt_field': 'complaintFault.repeat.combined', 'reason': 'missing_numerator_or_denominator', 'filled_value': None})
    audit['missing'] = [m for m in audit['missing'] if m.get('ppt_field') not in filled]
