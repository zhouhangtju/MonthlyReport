"""Optionally fill remaining empty asset-stage handlers from online process logs."""

from __future__ import annotations

import json
import os
import re
import time
import subprocess
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime
from urllib.parse import urlsplit

from storage.database import connect

STAGES = ('组网方案', '资源反馈', '组织资源释放', '归档审核')
ENTERPRISE = 'https://rmc-static-process-enterprise.oss.zj.chinamobile.com:7415'
TOKEN_NAME = 'irm-frontend-process-enterprise-token'
DATE_RANGE = 90
COOKIE_FILE = Path(__file__).resolve().with_name("cookie.txt")


def read_cookie_file(path=None):
    """Read the login output without echoing credentials."""
    path = Path(path) if path is not None else COOKIE_FILE
    try:
        content = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("无法读取流程日志 Cookie 文件，请先执行 login_save_cookie.py") from exc
    return parse_cookie(content)


def refresh_cookie():
    """Run SMS login interactively; never fall back to a stale cookie on failure."""
    script = Path(__file__).resolve().with_name("login_save_cookie.py")
    try:
        subprocess.run([sys.executable, str(script)], check=True)
    except subprocess.CalledProcessError:
        raise RuntimeError("短信登录未成功，已停止流程日志补采") from None
    read_cookie_file()



class NoDataFound(RuntimeError):
    """Successful query without matching data, distinct from technical errors."""


def parse_cookie(value: str) -> str:
    """Accept the subsystem token, its Cookie pair, or a complete Cookie header."""
    value = value.strip()
    if value.lower().startswith('cookie:'):
        value = value.split(':', 1)[1].strip()
    if '\n' in value or '\r' in value:
        raise ValueError('流程日志 Cookie 必须是单行')
    if TOKEN_NAME + '=' in value or TOKEN_NAME + ' =' in value:
        matches = []
        for part in value.split(';'):
            key, sep, token = part.strip().partition('=')
            if sep and key.strip() == TOKEN_NAME:
                matches.append(token.strip())
        if len(matches) != 1:
            raise ValueError('流程日志 Cookie 中的子系统 token 缺失或重复')
        value = matches[0]
    if not re.fullmatch(r'[A-Za-z0-9_+/.-]+={0,2}', value):
        raise ValueError('流程日志 Cookie 或 token 无效')
    return value


def latest_updaters(response: dict) -> dict[str, str | None]:
    """Latest updateDate wins; equal timestamps retain the first log row."""
    rows = response.get('data')
    if not isinstance(rows, list):
        raise ValueError('流程日志 data 不是列表')
    latest = {}
    for row in rows:
        stage = row.get('taskDisplayName')
        if stage not in STAGES:
            continue
        updated = datetime.strptime(row['updateDate'], '%Y-%m-%d %H:%M:%S')
        if stage not in latest or updated > latest[stage][0]:
            latest[stage] = (updated, row)
    return {stage: latest[stage][1]['updater'] if stage in latest else None for stage in STAGES}


def _get_data(session, path: str, **params) -> dict:
    response = session.get(
        ENTERPRISE + path,
        params={'_dc': int(time.time() * 1000), **params},
        headers={'Accept': 'application/json', 'Referer': ENTERPRISE + '/',
                 'X-Requested-With': 'XMLHttpRequest'},
        timeout=(10, 60), allow_redirects=False,
    )
    if response.is_redirect:
        raise RuntimeError('流程日志接口发生跳转，登录态可能失效')
    if response.status_code >= 400:
        raise RuntimeError(f'流程日志接口 {path} 返回 HTTP {response.status_code}')
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError('流程日志接口未返回 JSON，登录态可能失效') from None
    if not isinstance(result, dict) or result.get('success') is not True or str(result.get('resultCode')) != '1':
        raise RuntimeError(f'流程日志接口 {path} 查询失败')
    return result


def _find_order_id(session, order: str):
    filters = [
        {'property': 'dateRange', 'value': DATE_RANGE},
        {'property': 'IMEPWORKORDERCODE', 'value': order},
        {'property': 'fromIrm', 'value': 0},
        {'property': 'processGroupType', 'value': 1},
        {'property': 'taskView', 'value': 'all'},
        {'property': '_Auth_', 'value': True},
    ]
    query = {'filter': json.dumps(filters, separators=(',', ':')), 'limit': 25}
    count = _get_data(session, '/api/entity/task', **query, count='true', page=1, start=0)
    total = count.get('total')
    if not isinstance(total, int) or total < 0:
        raise RuntimeError('工单查询总数异常')
    if total == 0:
        raise NoDataFound('订单查询成功，但当前90天范围及账号可见范围内无匹配订单')
    ids = set()
    matched_without_id = False
    for start in range(0, total, 25):
        result = _get_data(session, '/api/entity/task', **query, page=start // 25 + 1, start=start)
        rows = result.get('data')
        if not isinstance(rows, list) or not rows:
            raise RuntimeError('工单查询分页结果异常')
        for row in rows:
            attrs = row.get('extension', {}).get('attributes', {})
            if attrs.get('SOSERIALNO') == order:
                if row.get('orderId') is None:
                    matched_without_id = True
                else:
                    ids.add(row['orderId'])
    if matched_without_id:
        raise RuntimeError('匹配订单缺少orderId，无法确认流程日志')
    if not ids:
        raise NoDataFound('订单查询成功，但未返回订单号精确匹配的记录')
    if len(ids) != 1:
        raise RuntimeError('未找到唯一匹配的 orderId，请核对日期范围及账号权限')
    return ids.pop()


def _fetch_logs(session, order: str) -> dict:
    order_id = _find_order_id(session, order)
    result = _get_data(session, '/api/model/processLog', filter=json.dumps(
        [{'property': 'orderId', 'value': order_id, 'exactMatch': True}], separators=(',', ':')))
    rows = result.get('data')
    if not isinstance(rows, list) or any(str(row.get('ticketId')) != str(order_id) for row in rows):
        raise RuntimeError('流程日志 data 或 ticketId 与 orderId 不一致')
    return result


def resolve_log_fills(response, pending):
    """Only an absent stage or explicit slash yields slash; blank updater stays blank."""
    from metrics.opening.automation_intermediate import clean
    updaters = latest_updaters(response)
    present = {row.get('taskDisplayName') for row in response['data']}
    handlers = {stage: clean(updaters.get(stage)) for stage in pending
                if clean(updaters.get(stage)) not in ('', '/')}
    slash_reasons = {stage: '流程日志查询成功，但没有该指定环节'
                     for stage in pending if stage not in present}
    slash_reasons.update({stage: '日志该环节处理人明确为/' for stage in pending
                          if stage in present and clean(updaters.get(stage)) == '/'})
    return {**handlers, **dict.fromkeys(slash_reasons, '/')}, slash_reasons


def backfill(database, month: str, build_id: str) -> dict:
    """Query orders with any empty asset handler after explicit path rules."""
    token = read_cookie_file()
    try:
        import truststore
    except ImportError:
        pass
    else:
        truststore.inject_into_ssl()
    import requests

    from metrics.opening.automation_intermediate import TABLE, pending_asset_stages

    ca_bundle = (os.environ.get('RMC_CA_BUNDLE') or os.environ.get('REQUESTS_CA_BUNDLE')
                 or os.environ.get('CURL_CA_BUNDLE'))
    if ca_bundle and not os.path.isfile(ca_bundle):
        raise ValueError('流程日志 CA 证书文件不存在')
    missing = ' OR '.join(f"TRIM(COALESCE(`{stage}`,''))=''" for stage in STAGES)
    with connect(database) as source:
        orders = source.execute(
            f"SELECT `订单号`," + ','.join(f'`{stage}`' for stage in STAGES)
            + f" FROM {TABLE} WHERE report_month=? AND build_id=? "
            f"AND ({missing}) ORDER BY `订单号`", (month, build_id)).fetchall()
    audit = {'selected_orders': len(orders), 'fetched_orders': 0, 'filled_orders': 0,
             'failed_orders': 0, 'filled_stages': dict.fromkeys(STAGES, 0),
             'slash_filled_stages': dict.fromkeys(STAGES, 0), 'no_order_data_orders': 0, 'details': []}
    with requests.Session() as session:
        session.verify = ca_bundle or True
        session.headers['User-Agent'] = 'Mozilla/5.0'
        session.cookies.set(TOKEN_NAME, token, domain=urlsplit(ENTERPRISE).hostname,
                            path='/', secure=True)
        for row in orders:
            order = row['订单号']
            pending = pending_asset_stages(row)
            try:
                if not re.fullmatch(r'[A-Za-z0-9_-]+', order):
                    raise ValueError('订单号包含不支持的字符')
                reason = None
                try:
                    proposed, slash_reasons = resolve_log_fills(_fetch_logs(session, order), pending)
                    audit['fetched_orders'] += 1
                except NoDataFound as exc:
                    proposed = dict.fromkeys(pending, '/')
                    reason = str(exc)
                    slash_reasons = dict.fromkeys(pending, reason)
                    audit['no_order_data_orders'] += 1
                filled = {}
                with connect(database) as destination:
                    for stage, updater in proposed.items():
                        cursor = destination.execute(
                            f"UPDATE {TABLE} SET `{stage}`=? WHERE report_month=? AND build_id=? "
                            f"AND `订单号`=? AND TRIM(COALESCE(`{stage}`,''))=''",
                            (updater, month, build_id, order))
                        if cursor._cursor.rowcount and str(updater).strip():
                            filled[stage] = updater
                            audit['filled_stages'][stage] += 1
                            if updater == '/':
                                audit['slash_filled_stages'][stage] += 1
                if filled:
                    audit['filled_orders'] += 1
                audit['details'].append({'order': order, 'status': 'no_data' if reason else 'success',
                                         'filled': filled, 'slash_reasons': slash_reasons,
                                         'pending_before': pending,
                                         'remaining': [stage for stage in pending if stage not in filled]})
            except requests.RequestException as exc:
                audit['failed_orders'] += 1
                audit['details'].append({'order': order, 'status': 'failed',
                                         'reason': f'网络请求失败：{type(exc).__name__}'})
            except (ValueError, KeyError, RuntimeError, TypeError, AttributeError) as exc:
                audit['failed_orders'] += 1
                audit['details'].append({'order': order, 'status': 'failed', 'reason': str(exc)})
    return audit
