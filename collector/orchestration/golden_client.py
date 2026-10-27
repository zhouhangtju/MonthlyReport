"""整周期点金统计报表采集；文件和周期数据库快照共用校验。"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from typing import Any
from config.datasets import get_dataset
from storage.database import connect, initialize
from storage.importer import import_file, iter_excel, read_headers
from storage.raw_tables import source_columns
from collector.orchestration.client import parse_date
from collector.orchestration.golden_config import REPORTS

BASE_URL = 'http://188.103.124.75:9527'


def validate_file(path: Path, code: str) -> None:
    if read_headers(path, code) != source_columns(code):
        raise ValueError('点金报表表头与配置不一致')
    rows = list(iter_excel(path, code))
    dimensions = ['地市'] if code.endswith('_cloud') else ['有无资源开通场景', '接入方式', '地市']
    keys = [tuple(str(row.get(c, '')).strip() for c in dimensions) for row in rows]
    if any(not key[-1] for key in keys) or len(keys) != len(set(keys)):
        raise ValueError('点金报表存在空地市或重复统计维度')


def has_snapshot(code: str, start: str, end: str) -> bool:
    initialize(None)
    with connect(None) as connection:
        return connection.execute(
            """SELECT b.run_id FROM raw_period_batch b JOIN etl_run e ON e.run_id=b.run_id
               WHERE b.dataset_code=? AND b.period_start=? AND b.period_end=?
               AND e.status='success' AND e.rows_failed=0""", (code, start, end)
        ).fetchone() is not None


def download(report: dict, start: str, end: str, directory: Path, *, session: Any,
             token: str | None, cookie: str | None, timeout: float, refresh: bool) -> tuple[Path, bool]:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{report['title']}_{start}_{end}.xls"
    if target.exists() and not refresh:
        validate_file(target, report['code'])
        return target, False
    headers = {}
    if token:
        headers.update({'authorization': token, 'token': token})
    if cookie:
        headers['Cookie'] = cookie
    params = {**report['params'], 'start_time': start, 'end_time': end}
    partial = target.with_suffix('.xls.part')
    try:
        with session.post(BASE_URL + '/PSM/bus/sml/export/export',
                          data={'FileTitle': report['title'], 'params': json.dumps(params, ensure_ascii=False),
                                'HeaderTitle': report['header_title']},
                          headers=headers, stream=True, timeout=timeout) as response:
            response.raise_for_status()
            with partial.open('wb') as output:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        output.write(chunk)
        with partial.open('rb') as probe:
            signature = probe.read(8)
        if not (signature.startswith(b'\xd0\xcf\x11\xe0') or signature.startswith(b'PK\x03\x04')):
            raise ValueError('编排接口未返回 XLS/XLSX 文件，请检查认证和接口')
        validate_file(partial, report['code'])
        partial.replace(target)
        return target, True
    finally:
        partial.unlink(missing_ok=True)


def collect(kind: str, start: str, end: str, *, mode: str = 'both',
            output_dir: Path = Path('data/raw/orchestration'), token: str | None = None,
            cookie: str | None = None, timeout: float = 180, refresh: bool = False,
            session: Any = None) -> list[dict]:
    if kind not in {*REPORTS, 'all'}:
        raise ValueError(f'未知报表类型：{kind}')
    if mode not in {'file', 'database', 'both'}:
        raise ValueError('mode 必须为 file、database 或 both')
    if parse_date(start) > parse_date(end):
        raise ValueError('开始日期不能晚于结束日期')
    if timeout <= 0:
        raise ValueError('timeout 必须大于0')
    owned = session is None
    if owned:
        import requests
        session = requests.Session()
    results = []
    try:
        with tempfile.TemporaryDirectory(prefix='orch_golden_') as temporary:
            for name in (REPORTS if kind == 'all' else [kind]):
                report = REPORTS[name]
                code = report['code']
                directory = Path(temporary) / code if mode == 'database' else Path(output_dir) / code
                covered = mode != 'file' and not refresh and has_snapshot(code, start, end)
                item = dict(kind=name, dataset_code=code, start=start, end=end, file=None,
                            downloaded=False, etl=None, skipped=False, skip_reason=None)
                if covered and mode == 'database':
                    item.update(skipped=True, skip_reason='database_exact_period_exists')
                else:
                    path, downloaded = download(report, start, end, directory, session=session,
                                                token=token, cookie=cookie, timeout=timeout, refresh=refresh)
                    item.update(file=str(path.resolve()) if mode != 'database' else None, downloaded=downloaded)
                    # both 模式始终校验并导入实际文件，避免文件与数据库快照不一致。
                    if mode != 'file':
                        item['etl'] = import_file(None, get_dataset(code), path,
                                                  period_start=start, period_end=end)
                results.append(item)
    finally:
        if owned:
            session.close()
    return results
