"""Reuse provincial formulas without calling their database entry points."""
from metrics.opening import dedicated_line_metrics as dev
from metrics.opening.bycity.city_results import CityVolumes
from metrics.opening.bycity import dedicated_line_metrics_by_city as citydev
from .split_evidence import batches


class Volumes(CityVolumes):
    def __init__(self, month, mapping):
        # Parent initialization loads its hardcoded map; use the archived map instead.
        from collections import Counter, defaultdict
        self.month, self.cities, self.mapping = month, dev.CITY_ORDER, mapping
        self.counties, self.by_city, self.months = Counter(), defaultdict(list), set()


def calculate(rows, month, mapping, history):
    volumes = Volumes(month, mapping)
    report = dev.calculate_month_batches([(month, batches(rows))], dev.shift_month(month, -11),
                                        month, history['results'], city_volumes=volumes)
    required = {dev.shift_month(month, i) for i in range(-12, 1)}
    missing_city = volumes.complete(history['results'], required)
    province = [r for r in report['results'] if 'automation' not in r['metric_code']
                and 'activation' not in r['metric_code']]
    missing = set(history['missing_months'])
    for item in province:
        dim = item['dimension']
        affected = set()
        if dim.get('month') in missing:
            affected.add(dim['month'])
        if dim.get('comparison_month') in missing:
            affected.add(dim['comparison_month'])
        if item['dimension_type'].startswith('rolling_'):
            affected |= missing & {dev.shift_month(month, i) for i in range(-11, 1)}
        if affected:
            item.update(numerator=None, denominator=None, metric_value=None, missing_months=sorted(affected))
    # Same last-record-wins key as summarize_month; retain both counted and excluded products.
    unique, empty = {}, 0
    for row in rows:
        if dev.text(row.get('订单状态')) != dev.STATUS or row.get('订单类型') != '开通':
            continue
        business = dev.text(row.get('业务类型'))
        if business not in {g[0] for g in citydev.BUSINESS_GROUPS}:
            continue
        key = dev.text(row.get('订单号'))
        if not key:
            empty += 1
            key = f'__empty_order_{empty}'
        unique[business, key] = dict(row)
    for (business, key), row in unique.items():
        products = next(g[2] for g in citydev.BUSINESS_GROUPS if g[0] == business)
        row['产品在统计范围'] = '是' if row.get('产品名称') in products else '否'
    city = [r for values in volumes.by_city.values() for r in values]
    audit = {'missing_months': sorted(missing), 'city_missing_history': missing_city,
             'intermediate_rows': len(unique),
             'scope_note': '沿用现有省级规则：互联网全省开通总量包含未列名产品，地市产品汇总仅列名产品，二者可能存在差额',
             'unassigned_city_rows': sum(r['标准地市'] == '未归属地市' for r in unique.values()),
             'unassigned_county_rows': sum(r['标准区县'] == citydev.UNASSIGNED_COUNTY for r in unique.values())}
    return province, city, list(unique.values()), audit
