"""File-only processLog fill; successful absence follows the existing slash rule."""
import os
import re
from urllib.parse import urlsplit
from metrics.opening import process_log_backfill as logs
from metrics.opening.automation_intermediate import pending_asset_stages
from .split_evidence import dump


def backfill(rows, directory, cookie_file, use_existing_cookie=False, fetch=None):
    import requests
    session = requests.Session()
    if fetch is None:
        if not use_existing_cookie:
            if cookie_file.resolve() != logs.COOKIE_FILE.resolve():
                raise ValueError('自定义Cookie路径请同时指定 --use-existing-cookie')
            logs.refresh_cookie()
        token = logs.read_cookie_file(cookie_file)
        try:
            import truststore
            truststore.inject_into_ssl()
        except ImportError:
            pass
        ca = (os.getenv('RMC_CA_BUNDLE') or os.getenv('REQUESTS_CA_BUNDLE') or os.getenv('CURL_CA_BUNDLE'))
        if ca and not os.path.isfile(ca):
            raise ValueError('CA证书文件不存在')
        session.verify = ca or True
        session.cookies.set(logs.TOKEN_NAME, token, domain=urlsplit(logs.ENTERPRISE).hostname, path='/', secure=True)
        session.headers['User-Agent'] = 'Mozilla/5.0'
        fetch = lambda order: logs._fetch_logs(session, order)
    audit = {'selected_orders': 0, 'failed_orders': 0, 'no_data_orders': 0, 'filled_stages': 0}
    try:
        for index, row in enumerate(rows):
            pending = pending_asset_stages(row)
            if not pending:
                continue
            audit['selected_orders'] += 1
            order = row['订单号']
            entry = {'order': order, 'pending_before': pending}
            try:
                if not re.fullmatch(r'[A-Za-z0-9_-]+', order):
                    raise ValueError('订单号格式不支持')
                try:
                    response = fetch(order)
                    proposed, reasons = logs.resolve_log_fills(response, pending)
                    entry.update(status='success', response=response, slash_reasons=reasons)
                except logs.NoDataFound as exc:
                    proposed = dict.fromkeys(pending, '/')
                    audit['no_data_orders'] += 1
                    entry.update(status='no_data', reason=str(exc))
                row.update(proposed)
                audit['filled_stages'] += len(proposed)
                entry['filled'] = proposed
            except (requests.RequestException, ValueError, RuntimeError, KeyError, TypeError, AttributeError) as exc:
                audit['failed_orders'] += 1
                # Avoid recording URLs/request headers that may contain credentials.
                entry.update(status='failed', error_type=type(exc).__name__)
            entry['remaining'] = pending_asset_stages(row)
            dump(directory / f'{index:07d}.json', entry)
            if audit['selected_orders'] % 100 == 0:
                print(f"日志回填：已查询{audit['selected_orders']}单，失败{audit['failed_orders']}单", flush=True)
    finally:
        session.close()
    audit['remaining_orders'] = sum(bool(pending_asset_stages(row)) for row in rows)
    dump(directory / 'audit.json', audit)
    return audit
