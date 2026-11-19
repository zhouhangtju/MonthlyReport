"""File adapter for existing automation matching and province/city formulas."""
import json
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path
from metrics.opening import automation_intermediate as auto
from metrics.opening.bycity.city_results import city_automation
from .calculate_development import Volumes


def build(rows, asset_csv):
    unique, counts = {}, Counter()
    for row in rows:
        counts['input_rows'] += 1
        key = auto.clean(row.get('订单号'))
        if (not key or auto.clean(row.get('业务类型')) not in auto.INTERMEDIATE_BUSINESSES or
            (auto.clean(row.get('订单类型')) == '变更' and
             auto.clean(row.get('调整类型')) not in auto.INTERMEDIATE_ADJUSTMENTS)):
            counts['excluded_rows'] += 1
            continue
        if key in unique:
            counts['duplicate_rows'] += 1
        unique[key] = row
    output = []
    with tempfile.TemporaryDirectory(prefix='daily-assets-') as directory:
        cache = sqlite3.connect(str(Path(directory) / 'assets.sqlite'))
        try:
            cache.execute('CREATE TABLE assets(order_no TEXT,stage TEXT,ended TEXT,payload TEXT,PRIMARY KEY(order_no,stage))')
            counts.update(auto.load_assets(cache, Path(asset_csv)))
            for key, raw in sorted(unique.items()):
                matches = {s: json.loads(p) for s, p in cache.execute(
                    'SELECT stage,payload FROM assets WHERE order_no=?', (key,))}
                row = {c: auto.clean(raw.get(c)) for c in auto.COLUMNS}
                for stage in auto.ASSET_STAGES:
                    row[stage] = auto.asset_handler(matches, stage)
                    counts[f'asset_matched_{stage}'] += stage in matches
                auto.apply_asset_path_rules(row)
                row.update(source_payload=json.dumps(raw, ensure_ascii=False, default=str),
                           asset_matches=json.dumps(matches, ensure_ascii=False))
                for field in ('标准地市', '标准区县', '区县清洗依据', '区县名称', '主题'):
                    row[field] = raw.get(field, '')
                output.append(row)
        finally:
            cache.close()
    counts['intermediate_rows'] = len(output)
    return output, dict(counts)


class FileRows:
    """Read-only protocol adapter for city_automation's one SELECT, no database IO."""
    def __init__(self, rows):
        self.rows = rows
        self._connection = self

    def cursor(self, *args):
        return FileCursor(self.rows)


class FileCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, parameters):
        expected = f'SELECT * FROM {auto.TABLE} WHERE report_month=%s AND build_id=%s AND 地市=%s'
        if ' '.join(sql.split()) != expected:
            raise ValueError('现有地市计算查询已变更，请更新daily适配器')
        self.selected = (dict(r) for r in self.rows if r['地市'] == parameters[2])

    def __iter__(self):
        return self.selected


def calculate(rows, month, mapping):
    province = []
    for prefix in auto.BUSINESS_GROUPS:
        province.extend(auto.aggregate(rows, month, prefix))
        if prefix != 'video':
            province.extend(auto.aggregate_stop_resume(rows, month, prefix))
    city = city_automation(FileRows(rows), Volumes(month, mapping), 'file', province)
    return province, city
