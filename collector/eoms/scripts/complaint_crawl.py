#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
政企投诉工单爬虫
从EOMS系统自动拉取政企客户投诉工单数据
API: /prod-api/process/compt/govcustomercomplaint/list
数据源：投诉处理 → 政企客户投诉处理流程 → 工单查询

用法：
  python complaint_crawl.py                          # 默认近3个月
  python complaint_crawl.py --days 30                # 近30天
  python complaint_crawl.py --start 2026-03-01 --end 2026-05-12  # 指定日期
  python complaint_crawl.py --auto                   # 自动按自然月前推2个月
"""

import requests
import pandas as pd
import sqlite3
import os
import sys
import time
import json
import logging
import warnings
from datetime import datetime, timedelta
import argparse

# 允许脚本被直接执行，同时复用项目内可单测的数据转换规则。
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from collector.eoms.transform import fill_missing_account_with_phone

# 抑制 requests verify=False 的 SSL 警告
from urllib3.exceptions import InsecureRequestWarning
warnings.filterwarnings('ignore', category=InsecureRequestWarning)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

# ─── 配置 ──────────────────────────────────────────────────────────
# Token数据库路径（优先级：工具包目录 > 桌面\集客工单）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.dirname(_SCRIPT_DIR)
_CANDIDATES = [
    os.path.join(_PKG_ROOT, 'login.db'),                             # 工具包目录
    os.path.join(os.path.expanduser('~'), 'Desktop', '集客工单', 'login.db'),  # 桌面
]
DB_PATH = None
for _p in _CANDIDATES:
    if os.path.exists(_p):
        DB_PATH = _p
        break
if DB_PATH is None:
    DB_PATH = _CANDIDATES[-1]  # fallback for error message
PHONE_KEY = 'eoms_user'

# API地址
API_HOST = 'http://eoms.zj.chinamobile.com'
API_PATH = '/prod-api/process/compt/govcustomercomplaint/list'
API_URL = f'{API_HOST}{API_PATH}'

# 默认输出目录
OUTPUT_DIR = os.path.join(os.path.expanduser('~'), 'Desktop', '投诉工单')

# Detail API 地址（用于补全 list API 缺失的 extendInfo 字段）
DETAIL_API_BASE = f'{API_HOST}/prod-api/process/compt/govcustomercomplaint/show/detail'

# 保留的关键字段白名单（其余字段全部删除）
KEEP_COLUMNS = [
    # 工单基础信息
    'id', 'sheetId', 'title', 'createTime', 'updateTime', 'finishTime', 'dealExpiryDate',
    'status', 'statusName', 'flowNo', 'procName',
    # 客户信息
    'blocName', 'blocNum', 'groupcliNo', 'county', 'cityName', 'city',
    'accountCode', 'accountCodeFillSource', 'jtCalle', 'jtPhone', 'jtLinkman', 'jtLinkmanPhone',
    'jtLocationName', 'jtCustomerType', 'jtCustomerTypeName',
    'blocGrade', 'blocGradeName', 'isVipcustomer', 'isVipcustomerName',
    'busiAssurLevel', 'busiAssurLevelName', 'busiRangeName',
    # 业务信息
    'busiType', 'busiTypeName', 'lastBusiTypeName', 'busiTypeArr',
    'zqcomplaintType', 'zqcomplaintTypeName',
    'businessType', 'businessTypeName',
    'isSelfbuild', 'isMildept', 'dataOrigin',
    # 投诉内容
    'detail', 'advice', 'otherRemark', 'appendInfo', 'icdNumber', 'icdTime', 'assignTime',
    'speciallineNum', 'cpAscribe', 'cpAscribeName',
    # 处理信息
    'updateByName', 'updateByDeptname', 'createByName', 'createByDeptname',
    'processAssigneeName', 'participantName',
    'taskName', 'taskDefId',
    # 电子流信息
    'dealId', 'queryIndex',
    # 客户经理
    'climanagerName', 'climanagerPhone',
    'zBusinessOwnera', 'zBusinessOwneraTel',
    'zBusinessOwnerb', 'zBusinessOwnerbTel',
    'zEndAccessMarketgrid',
    # 统计筛选关键
    'stat.flowState', 'stat.flowStateName', 'stat.alarmResult',
    'stat.acceptTime', 'stat.dealTime', 'stat.firstTransferTime',
    'stat.backReason', 'stat.backRemark', 'stat.isBack',
    'stat.dealDeptName', 'stat.dealPersonName',
    'stat.acceptDeptName', 'stat.acceptPersonName',
    'stat.qualityDeptName', 'stat.qualityPersonName',
    'stat.endDeptName', 'stat.endPersonName', 'stat.endTime', 'stat.endOpinion',
    'stat.note', 'stat.settleState',
    'stat.isRepetitionOrders',
    'stattwo.netRepeatDispatchTimes',
    # 网格信息
    'nextTaskInfo.countyName', 'nextTaskInfo.cityName',
    'nextTaskInfo.sheetType', 'nextTaskInfo.queryIndex',
    'nextTaskInfo.industryCustType', 'nextTaskInfo.strategicCustTypeFL',
    'nextTaskInfo.vipCustType', 'nextTaskInfo.vipCustomTypeName',
    # 其他有用字段
    'finishSuggestion', 'finishSuggestionName',
    'slaLevel', 'slaLevelName',
    'acceptWay', 'pjProjectCity', 'pjProjectCounty',
    'netCode', 'cooperateModeName',
]
# ────────────────────────────────────────────────────────────────────


def get_token():
    """从login.db读取Bearer Token（与jike_crawl.py共用，格式一致）"""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f'[错误] Token数据库不存在: {DB_PATH}\n'
                                f'请先双击"获取Emos的Token.bat"获取Token')

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT token FROM login_info WHERE phone = ? ORDER BY rowid DESC LIMIT 1', (PHONE_KEY,))
    row = cur.fetchone()
    conn.close()

    if row is None or not row[0]:
        raise ValueError(f'[错误] 未找到 phone="{PHONE_KEY}" 的Token\n'
                         f'请先双击"获取Emos的Token.bat"获取Token')

    token = row[0].strip()
    # 数据库中存的是 "Bearer {uuid}" 格式，直接使用
    if not token.startswith('Bearer '):
        token = f'Bearer {token}'
    return token


def calculate_date_range(days=None, start_date=None, end_date=None, auto=False):
    """计算日期范围
    auto模式：start=当月前推2个月的第1天，end=昨天
    例：4月11日 → 2月1日~4月10日；5月11日 → 3月1日~5月10日
    """
    today = datetime.now()

    if start_date and end_date:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
    elif auto:
        end = today - timedelta(days=1)
        # start = 当月往前推2个月的第1天
        m = today.month - 2
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
        start = datetime(y, m, 1)
    elif days:
        end = today
        start = today - timedelta(days=days)
    else:
        # 默认近3个月
        end = today
        start = today - timedelta(days=90)

    return start.strftime('%Y-%m-%d 00:00:00'), end.strftime('%Y-%m-%d 23:59:59')


def fetch_all_pages(token, begin_time, end_time, page_size=500):
    """分页拉取全量投诉工单数据"""
    headers = {
        'Authorization': token,
        'Content-Type': 'application/json',
        'Origin': 'http://eoms.zj.chinamobile.com',
        'Referer': 'http://eoms.zj.chinamobile.com/compt/govcustomercomplaint/main',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }

    all_rows = []
    page_num = 1
    total_pages = None

    logger.info(f'开始拉取投诉工单数据...')
    logger.info(f'时间范围: {begin_time} ~ {end_time}')

    while True:
        t_param = int(time.time() * 1000)
        url = f'{API_URL}?t={t_param}'

        payload = {
            'pageNum': page_num,
            'pageSize': page_size,
            'params': {
                'beginCreateTime': begin_time,
                'endCreateTime': end_time,
                'isIncludeBusiTypeCode': '0',
            },
            'stat': {
                'extractPerson': '', 'remoteDeal': '', 'acceptPerson': '',
                'acceptDept': '', 'dealDept': '', 'dealPerson': '',
                'collaborateDept': '', 'endDept': '', 'qualityDept': '', 'qualityPerson': '',
            },
            'deleted': '0',
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if data.get('code') == 500 or data.get('msg') == '登录状态已过期':
                logger.error(f'Token已过期: {data.get("msg", "")}')
                logger.error('请重新双击"获取Emos的Token.bat"获取新Token')
                return None

            rows = data.get('rows', [])
            total = data.get('total', 0)

            if total_pages is None and page_size > 0:
                total_pages = (total + page_size - 1) // page_size
                logger.info(f'共 {total} 条数据，预计 {total_pages} 页')

            all_rows.extend(rows)
            logger.info(f'  第 {page_num}/{total_pages or "?"} 页 → 已获取 {len(rows)} 条 (累计 {len(all_rows)} 条)')

            if len(rows) < page_size:
                break

            page_num += 1
            time.sleep(0.5)  # 防止请求过快

        except requests.exceptions.RequestException as e:
            logger.error(f'请求失败: {e}')
            if page_num > 1:
                logger.info(f'已获取 {len(all_rows)} 条数据，继续处理')
                break
            return None

    logger.info(f'拉取完成，共 {len(all_rows)} 条投诉工单')
    return all_rows


def flatten_row(row, prefix=''):
    """展平嵌套的JSON字段"""
    flat = {}
    for key, value in row.items():
        if isinstance(value, dict):
            nested = flatten_row(value, f'{prefix}{key}.')
            flat.update(nested)
        else:
            flat[f'{prefix}{key}'] = value
    return flat


def fetch_detail_extend_info(main_id: str, token: str) -> dict:
    """
    调 Detail API 获取 extendInfo 字段。
    返回 dict，含 accountCode/businessTypeName/speciallineNum 等。
    失败返回空 dict。
    """
    url = f'{DETAIL_API_BASE}/{main_id}'
    headers = {
        'Authorization': token,
        'Content-Type': 'application/json',
        'Origin': 'http://eoms.zj.chinamobile.com',
        'Referer': 'http://eoms.zj.chinamobile.com/compt/govcustomercomplaint/show/detail/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    params = {'t': str(int(datetime.now().timestamp() * 1000))}
    try:
        resp = requests.get(url, params=params, headers=headers, verify=False, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') != 200:
            return {}
        pm = data['data']['processMain']
        stat = pm.get('stat', {}) if isinstance(pm, dict) else {}
        extend_info = stat.get('extendInfo', {}) if isinstance(stat, dict) else {}
        return dict(extend_info) if isinstance(extend_info, dict) else {}
    except Exception as e:
        logger.debug(f'  Detail API 失败 {main_id}: {e}')
        return {}


def supplement_rows_from_detail(rows: list, token: str, city_filter: str = None) -> list:
    """
    对 list API 返回的 rows，补全/修正 accountCode 等字段。
    优先级：附加报结信息(appendInfo) e55 > 其他文本字段 e55 > Detail API e55

    city_filter: 只补全指定地市的工单（如 '金华'），None 则全部补全。
    附加报结信息的 e55 优先级最高，即使 list API 已返回 accountCode 也会被覆盖。
    """
    import re
    _e55_re = re.compile(r'e55\d+', re.IGNORECASE)

    # ── 第0层：附加报结信息(appendInfo) 的 e55 优先级最高 ──
    # 对所有行扫描（不管 accountCode 是否已有值），找到即覆盖
    appendInfo_overridden = 0
    appendInfo_multi = 0
    for row in rows:
        val = row.get('appendInfo') if isinstance(row, dict) else None
        if val:
            matches = _e55_re.findall(str(val))
            if matches:
                unique_matches = []
                for m in matches:
                    low = m.lower()
                    if low not in unique_matches:
                        unique_matches.append(low)
                new_acct = unique_matches[0]  # 取第一个赋给 accountCode
                old_acct = str(row.get('accountCode', '') or '').strip()
                if new_acct != old_acct:
                    row['accountCode'] = new_acct
                    appendInfo_overridden += 1
                if len(unique_matches) > 1:
                    # 多个 e55 记录到扩展字段，供统计脚本识别
                    row['appendInfo_e55_all'] = '/'.join(unique_matches)
                    appendInfo_multi += 1
    if appendInfo_overridden:
        logger.info(f'附加报结信息(appendInfo) e55 覆盖: {appendInfo_overridden} 条（优先级高于 Detail API）')
    if appendInfo_multi:
        logger.info(f'附加报结信息含多个 e55: {appendInfo_multi} 条（已记录到 appendInfo_e55_all 字段）')

    # ── 第1层：统计仍缺失 accountCode 的行 ──
    missing_idx = []
    for i, row in enumerate(rows):
        acct = row.get('accountCode') or ''
        if not str(acct).strip() or str(acct).strip().lower() == 'nan':
            missing_idx.append(i)

    if not missing_idx:
        logger.info('所有工单均已含 accountCode，无需 Detail API 补全')
        return rows

    # ── 第2层：地市过滤 ──
    if city_filter:
        before_city = len(missing_idx)
        filtered_idx = []
        for idx in missing_idx:
            row = rows[idx]
            cn = str(row.get('cityName', '') or row.get('city', ''))
            if city_filter in cn or city_filter + '市' in cn:
                filtered_idx.append(idx)
        skipped = before_city - len(filtered_idx)
        missing_idx = filtered_idx
        if not missing_idx:
            logger.info(f'{city_filter}地市无需补全 accountCode（全省共 {before_city} 条缺失已跳过）')
            return rows
        logger.info(f'仅补全 {city_filter} 地市: {len(missing_idx)} 条缺失（跳过其他地市 {skipped} 条）')

    # ── 第3层：其他文本字段快速提取 e55 ──
    # appendInfo 已在第0层处理，这里排除它
    _text_fields = ['detail', 'advice', 'otherRemark', 'jtCalle',
                    'title', 'cpAscribe', 'stat.backRemark', 'stat.note']
    need_api_idx = []
    text_filled = 0
    for idx in missing_idx:
        row = rows[idx]
        found = None
        for field in _text_fields:
            val = row.get(field) if isinstance(row, dict) else None
            if val:
                m = _e55_re.search(str(val))
                if m:
                    found = m.group(0).lower()
                    break
        if found:
            row['accountCode'] = found
            text_filled += 1
        else:
            need_api_idx.append(idx)

    logger.info(f'其他文本字段 e55 匹配: {text_filled} 条（纯文本提取，无需API）')
    if not need_api_idx:
        logger.info(f'所有缺失 accountCode 已通过文本匹配补全，跳过 Detail API')
        return rows

    # ── 第4层：Detail API 兜底 ──
    logger.info(f'仍需 Detail API 补全: {len(need_api_idx)} 条')
    filled = 0
    for n, idx in enumerate(need_api_idx, 1):
        row = rows[idx]
        main_id = row.get('id') or row.get('mainId')
        if not main_id:
            continue
        extend = fetch_detail_extend_info(str(main_id), token)
        if extend:
            # 只补空白字段，不覆盖已有值（文本匹配的优先级高于 Detail API）
            for key in ['accountCode', 'businessType', 'businessTypeName',
                        'speciallineNum', 'blocName', 'county', 'cityName',
                        'jtCustomerLevel', 'jtCustomerLevelName',
                        'busiAssurLevel', 'busiAssurLevelName', 'isMonitored']:
                if key in extend and extend[key]:
                    # 跳过中文"无"和空值
                    val = str(extend[key]).strip()
                    if val == '' or val == '无':
                        continue
                    if key not in row or not row.get(key) or str(row.get(key)).strip() == '' or str(row.get(key)).strip().lower() == 'none':
                        row[key] = extend[key]
            filled += 1
        if n % 10 == 0:
            logger.info(f'  Detail API 进度: {n}/{len(need_api_idx)} (已补 {filled})')
        time.sleep(0.3)  # 防请求过快

    logger.info(f'Detail API 补全完成: 需补 {len(need_api_idx)} 条，成功补全 {filled} 条')
    return rows


def save_to_excel(rows, output_path):
    """保存原始数据到Excel（仅保留白名单关键字段）"""
    if not rows:
        logger.warning('无数据可保存')
        return False

    # 展平嵌套数据
    flat_rows = [flatten_row(row) for row in rows]
    df = pd.DataFrame(flat_rows)

    before = len(df.columns)

    # 只保留白名单中实际存在的列
    actual_keep = [c for c in KEEP_COLUMNS if c in df.columns]
    df = df[actual_keep].copy()

    # 英文字段名 → 中文名（按老大模板111111.xlsx的127个字段名对齐）
    col_rename = {
        'sheetId': '工单号',
        'flowNo': '客服流水号',
        'title': '工单主题',
        'jtLocationName': '归属地',
        'stat.flowStateName': '当前环节',
        'participantName': '当前责任班组',
        'createByName': '客服派单人工号',
        'icdTime': '客服受理时间',
        'createTime': '派单时间',
        'jtPhone': '手机号码',
        'jtCustomerTypeName': '客户类型',
        'busiTypeName': '业务类别',
        'zqcomplaintTypeName': '投诉类型',
        'isMildept': '是否多部门处理',
        'cityName': '所属地市',
        'county': '所属区县',
        'jtCustomerLevelName': '客户服务等级',
        'busiAssurLevelName': '业务保障等级',
        'busiRangeName': '业务覆盖范围',
        'speciallineNum': '专线编号',
        'detail': '投诉内容',
        'assignTime': '派单时间_系统',
        'dealExpiryDate': '处理超时时限',
        'advice': '退单附加说明',
        'stat.acceptDeptName': '受理班组',
        'stat.acceptPersonName': '受理人',
        'stat.acceptTime': '受理时间',
        'stat.flowState': '流程状态',
        'statusName': '工单状态',
        'updateByDeptname': '更新部门',
        'updateByName': '最后处理人',
        'stat.dealTime': '最后处理时间',
        'stat.backReason': '退单原因',
        'stat.dealPersonName': '报结人',
        'stat.qualityDeptName': '质检部门',
        'stat.qualityPersonName': '质检人',
        'stat.qualityTime': '质检时间',
        'stat.qualityRemark': '质检意见',
        'stat.settleState': '解决情况',
        'stat.backRemark': '退单备注',
        'otherRemark': '附加说明',
        'appendInfo': '附加报结信息',
        'stat.endOpinion': '结单意见',
        'stat.note': '处理备注',
        'stat.dealDeptName': '处理班组',
        'stat.firstTransferTime': '首次转派时间',
        'stat.delayReason': '延期原因',
        'blocNum': '集团编号',
        'blocName': '集团名称',
        'blocGradeName': '集团等级',
        'isVipcustomerName': 'VIP等级',
        'cpAscribeName': '投诉归因',
        'stat.autoTransfer': '自动转派',
        'accountCode': '计费号码',
        'accountCodeFillSource': '计费号码补位来源',
        'zEndAccessMarketgrid': '所属市场网格',
        'icdNumber': '新客服流水号',
        'stat.alarmResult': '告警匹配结果',
        'stat.isRepetitionOrders': '是否重复投诉',
        'stattwo.netRepeatDispatchTimes': '重复派单次数',
        'busiType': 'busitype',
        'lastBusiTypeName': 'lastbusitype',
        'businessTypeName': '业务类型',
        'nextTaskInfo.countyName': '下一环节区县',
        'nextTaskInfo.cityName': '下一环节地市',
        'queryIndex': '查询索引',
        'climanagerName': '客户经理',
        'climanagerPhone': '客户经理电话',
        'processAssigneeName': '处理人',
        'slaLevelName': 'SLA等级',
        'finishSuggestionName': '完成建议',
        'acceptWay': '受理方式',
        'cooperateModeName': '合作模式',
        'stat.isBack': '是否退单',
        'stat.endTime': '结单时间',
        'stat.endDeptName': '最后处理班组',
        'stat.endPersonName': '结单人',
        'finishTime': '完成时间',
    }
    df = df.rename(columns={k: v for k, v in col_rename.items() if k in df.columns})

    # 再从保留的列中删除全空/全零的
    df = df.dropna(axis=1, how='all')
    zero_cols = [c for c in df.columns
                 if all(v == 0 or v == 0.0 or str(v).strip() in ('0', '') for v in df[c].dropna())]
    if zero_cols:
        df = df.drop(columns=zero_cols)

    dropped = before - len(df.columns)
    if dropped > 0:
        logger.info(f'字段精简: {before} → {len(df.columns)} (删除了 {dropped} 个)')

    # 创建输出目录
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    df.to_excel(output_path, index=False, engine='openpyxl')
    logger.info(f'原始数据已保存: {output_path}')
    logger.info(f'  {len(df)} 行 × {len(df.columns)} 列')
    return True


def main():
    parser = argparse.ArgumentParser(description='政企投诉工单爬虫')
    parser.add_argument('--days', type=int, help='最近N天')
    parser.add_argument('--start', type=str, help='开始日期 YYYY-MM-DD')
    parser.add_argument('--end', type=str, help='结束日期 YYYY-MM-DD')
    parser.add_argument('--auto', action='store_true', help='自动模式：自然月前推2个月')
    parser.add_argument('--output', type=str, help='输出文件路径')
    parser.add_argument('--page-size', type=int, default=500, help='每页条数(默认500)')
    args = parser.parse_args()

    # 1. 读取Token
    try:
        token = get_token()
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        sys.exit(1)

    # 2. 计算日期范围
    begin_time, end_time = calculate_date_range(
        days=args.days,
        start_date=args.start,
        end_date=args.end,
        auto=args.auto
    )

    # 3. 拉取数据
    rows = fetch_all_pages(token, begin_time, end_time, page_size=args.page_size)

    if rows is None:
        sys.exit(1)

    if len(rows) == 0:
        logger.warning('未获取到任何投诉工单数据')
        sys.exit(0)

    # 4. Detail API 补全缺失的 extendInfo 字段（全省地市）
    rows = supplement_rows_from_detail(rows, token, city_filter=None)

    # 5. 详情及文本仍无法取得计费号码时，使用手机号码补位
    rows = fill_missing_account_with_phone(rows, logger=logger)

    # 6. 保存原始数据
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    date_label = begin_time[:10].replace('-', '') + '-' + end_time[:10].replace('-', '')

    if args.output:
        output_path = args.output
    else:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(OUTPUT_DIR, f'投诉工单_原始数据_{date_label}_{timestamp}.xlsx')

    save_to_excel(rows, output_path)

    # 打印关键统计
    print(f'\n{"="*50}')
    print(f'投诉工单爬取完成！')
    print(f'  时间范围: {begin_time} ~ {end_time}')
    print(f'  总工单数: {len(rows)}')
    print(f'  输出文件: {output_path}')
    print(f'{"="*50}')

    # 打印各区县统计概览
    df = pd.DataFrame(rows)
    if 'county' in df.columns:
        print(f'\n各区县工单数:')
        area_counts = df['county'].value_counts().head(15)
        for area, cnt in area_counts.items():
            print(f'  {area}: {cnt}')

    return output_path


if __name__ == '__main__':
    main()
