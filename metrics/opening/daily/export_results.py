"""One city workbook/JSON contains city totals followed by its county results."""
from metrics.opening.dedicated_line_metrics import CITY_ORDER
from .split_evidence import dump, workbook


def export(directory, province, cities, metadata):
    def write(folder, name, items):
        dump(folder / f'{name}.json', {**metadata, 'results': items})
        data = []
        for r in items:
            d = r['dimension']
            data.append({'层级': '区县' if d.get('county') else '地市' if d.get('city') else '省级',
                         '地市': d.get('city', '全省'), '区县': d.get('county', ''),
                         '指标': r['metric_code'], '维度类型': r['dimension_type'],
                         '月份': d.get('month', metadata['month']), '产品': d.get('product', ''),
                         '环节': d.get('stage', ''), '分子或数量': r['numerator'],
                         '分母': r['denominator'], '指标值': r['metric_value'],
                         '状态': '数据缺失或分母为0' if r['metric_value'] is None else '已计算',
                         '其他维度': d})
        workbook(folder / f'{name}.xlsx', data)
    write(directory / '省级', '全省', [r for r in province if r['dimension'].get('city') in (None, '全省合计')])
    for city in CITY_ORDER:
        items = [r for r in cities if r['dimension'].get('city') == city]
        # All city summary rows precede all county rows; preserve indicator order within each group.
        items.sort(key=lambda r: bool(r['dimension'].get('county')))
        write(directory / '地市', city.removesuffix('市'), items)
