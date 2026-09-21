#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EOMS 自动登录并导出 E企组网/安全卫士工单。"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import csv
import itertools
import tempfile
from contextlib import contextmanager
from collections import Counter
from datetime import date

from config.datasets import get_dataset
from storage.importer import file_sha256, import_file, iter_rows, row_payload
from storage.terminal_recovery import has_source_coverage, save_source

import calendar
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import parse_qs, urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ============================================================
# 登录配置
# ============================================================

ACCOUNT = "13738074615"
PASSWORD = "Zsins@126"

CAS_BASE = "http://10.76.149.228:9082"
EOMS_WEB_BASE = "http://eoms.zj.chinamobile.com"
EOMS_LOGIN_API = f"{EOMS_WEB_BASE}/prod-api"
APP_CODE = "casR15643"
RESOURCE_ID = "15643"
TARGET = f"{EOMS_WEB_BASE}/fouraLogin"


# ============================================================
# 导出配置
# ============================================================

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data/raw/eoms/eoms_service_removal_order"
EOMS_EXPORT_API = "http://188.104.246.86/prod-api"

REQUEST_TIMEOUT = 30
POLL_TIMEOUT = 600
POLL_INTERVAL = 5
FIXED_BEGIN_CREATE_TIME = "2026-02-26 00:00:00"


def ts():
    return datetime.now().strftime("%H:%M:%S")


# ============================================================
# 4A 自动登录
# ============================================================

def rsa_with_no_padding(modulus, exponent, value):
    raw = value.encode("utf-8")
    plain_int = int.from_bytes(raw, byteorder="big", signed=False)
    encrypted_int = pow(plain_int, exponent, modulus)
    size = (encrypted_int.bit_length() + 7) // 8
    return encrypted_int.to_bytes(size, byteorder="big").hex()


def get_rsa_key(session):
    # 沿用原自动登录脚本中已经验证过的 4A 公钥获取入口。
    url = (
        f"{CAS_BASE}/portalS/platform/iframeLoginZJ.do"
        "?appCode=casR15623&target=http://rmc-frontend-sso.oss.zj.chinamobile.com:80"
        "/redirect?originalUrl=http://rmc.oss.zj.chinamobile.com"
    )
    response = session.get(url, timeout=20)
    response.raise_for_status()
    match = re.search(
        r'getKeyPair\("10001",\s*"",\s*"([0-9a-fA-F]+)"\)',
        response.text,
    )
    if not match:
        raise RuntimeError("4A 登录页未找到 RSA 公钥")
    return int(match.group(1), 16), int("10001", 16)


def extract_pname(location):
    parsed = urlparse(location)
    pname = parse_qs(parsed.query, keep_blank_values=True).get("pname", [""])[0]
    if not pname:
        match = re.search(r"[?&]pname=([^&]+)", location)
        pname = match.group(1) if match else ""
    if not pname:
        raise RuntimeError(f"4A 跳转地址中未找到 pname: {location[:160]}")
    return pname


def auto_login(account=ACCOUNT, password=PASSWORD):
    """通过 4A 登录 EOMS，返回不带 Bearer 前缀的 Token。"""
    print(f"[{ts()}] 正在自动登录 EOMS，账号: {account}")
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "Referer": (
            f"{CAS_BASE}/portalS/platform/iframeLoginZJ.do"
            f"?appCode={APP_CODE}&target={TARGET}"
        ),
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": CAS_BASE,
    })

    modulus, exponent = get_rsa_key(session)
    form = {
        "username": rsa_with_no_padding(modulus, exponent, account),
        "password": rsa_with_no_padding(modulus, exponent, password),
        "userName": account,
        "passWord": password,
        "loginMode": "pwd",
        "code": "111111",
        "challengeCode": "111111",
        "appCode": APP_CODE,
        "resourceId": RESOURCE_ID,
        "isGroupUser": "true",
        "target": TARGET,
        "verifyRealCode": "false",
    }

    login_url = f"{CAS_BASE}/portalS/platform/iframeLoginZJ!login.do"
    response = session.post(
        login_url,
        data=form,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
    )
    location = response.headers.get("Location", "")
    if not location:
        response = session.post(
            login_url,
            data=form,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        location = response.url

    pname = extract_pname(location)
    response = session.post(
        f"{EOMS_LOGIN_API}/auth/a4login?t={int(time.time() * 1000)}",
        json={"pname": pname},
        headers={"Content-Type": "application/json", "Referer": location},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"EOMS a4login 返回的不是 JSON: {response.text[:200]}"
        ) from exc

    if payload.get("code") != 200:
        raise RuntimeError(
            f"EOMS a4login 失败: {payload.get('msg') or str(payload)[:160]}"
        )

    token = str((payload.get("data") or {}).get("token", ""))
    token = re.sub(r"^Bearer\s+", "", token, flags=re.IGNORECASE).strip()
    if not token:
        raise RuntimeError("EOMS a4login 返回中未找到 Token")

    print(f"[{ts()}] 自动登录成功，Token: {token[:12]}...（已隐藏）")
    return token


def create_export_session(token):
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36"
        ),
    })
    return session


# ============================================================
# 导出任务
# ============================================================

def build_export_variables(begin_finish_time, month_end_time, service_type):
    common = [
        {"pageNum": 1},
        {"pageSize": 10},
        {
            "params": {
                "beginCreateTime": FIXED_BEGIN_CREATE_TIME,
                "beginFinishTime": begin_finish_time,
                "endCreateTime": month_end_time,
                "endFinishTime": month_end_time,
            }
        },
        {"deleted": "0"},
        {"operateType": "拆除"},
        {"status": "COMPLETED"},
    ]

    if service_type == "E企组网":
        return common + [
            {"serviceLargeClass": "intranetService"},
            {"serviceTypeName": "E企组网"},
            {"serviceLargeClassName": "内网服务"},
            {"serviceType": "ff180eac0c6d4198a487fcf4dfaedcbb"},
        ], "E企组网"

    if service_type == "安全终端部署服务":
        return common + [
            {"serviceLargeClass": "securityService"},
            {"serviceTypeName": "安全终端部署服务"},
            {"serviceLargeClassName": "安全服务"},
            {"serviceType": "4c57208c9e1f4d6fa15ab66d5f93f161"},
        ], "安全卫士"

    return common, "全量"


def create_export_job(session, payload):
    url = (
        f"{EOMS_EXPORT_API}/system/exporter/create/job"
        f"?t={int(time.time() * 1000)}"
    )
    response = session.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(
            f"创建任务 HTTP {response.status_code}: {response.text[:300]}"
        )

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"创建任务接口返回的不是 JSON: {response.text[:300]}"
        ) from exc

    return result


def is_login_expired(result):
    message = str(result.get("msg") or "")
    return any(keyword in message for keyword in ("登录状态已过期", "未登录", "token失效", "Token失效"))


def poll_job(session, job_id, timeout=POLL_TIMEOUT):
    start_time = time.time()
    last_progress = None

    while time.time() - start_time < timeout:
        time.sleep(POLL_INTERVAL)
        url = (
            f"{EOMS_EXPORT_API}/system/exporter/job/{job_id}"
            f"?t={int(time.time() * 1000)}"
        )
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            print(f"[{ts()}] 轮询请求异常: {exc}，继续重试...")
            continue

        if response.status_code != 200:
            print(f"[{ts()}] 轮询请求失败 HTTP {response.status_code}，继续重试...")
            continue

        try:
            result = response.json()
        except ValueError:
            print(f"[{ts()}] 轮询接口返回非 JSON，继续重试...")
            continue

        if result.get("code") != 200:
            raise RuntimeError(f"轮询任务失败: {result.get('msg')}")

        data = result.get("data") or {}
        status = data.get("endStatus")
        progress = data.get("exportProgress")
        total = data.get("exportTotal")

        if progress != last_progress:
            print(f"[{ts()}] {status or 'RUNNING'}  progress={progress}  total={total}")
            last_progress = progress

        if status == "COMPLETED":
            print(f"[{ts()}] 任务完成")
            return data
        if status == "FAILED":
            raise RuntimeError(f"任务失败: {data.get('errorMsg')}")

    raise RuntimeError(f"轮询超时（超过 {timeout} 秒）")


def save_file(response, begin_finish_time, month_end_time, prefix, output_dir=None):
    start_dt = datetime.strptime(begin_finish_time.split()[0], "%Y-%m-%d")
    month_str = start_dt.strftime("%Y-%m")

    save_dir = output_dir or OUTPUT_DIR
    os.makedirs(save_dir, exist_ok=True)
    filename = f"服务类产品支撑工单_{month_str}.xlsx"
    filepath = os.path.join(save_dir, filename)

    with open(filepath, "wb") as file:
        file.write(response.content)

    print(f"[{ts()}] 已保存: {filepath} ({len(response.content):,} bytes)")
    return filepath


def download_export(session, job_id, begin_finish_time, month_end_time, prefix, output_dir=None):
    print(f"[{ts()}] 下载中...")
    url = (
        f"{EOMS_EXPORT_API}/system/exporter/export/job/{job_id}"
        f"?t={int(time.time() * 1000)}"
    )
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise RuntimeError(
            f"下载 HTTP {response.status_code}: {response.text[:300]}"
        )

    content_type = response.headers.get("Content-Type", "").lower()
    if "json" in content_type:
        try:
            result = response.json()
        except ValueError:
            result = {}
        if result:
            raise RuntimeError(
                f"下载失败: {result.get('msg') or str(result)[:300]}"
            )

    if not response.content:
        raise RuntimeError("下载失败：接口返回空文件")

    return save_file(
        response,
        begin_finish_time,
        month_end_time,
        prefix,
        output_dir,
    )


def export_qiwan(begin_finish_time, month_end_time, service_type=None, output_dir=None):
    variables, prefix = build_export_variables(
        begin_finish_time,
        month_end_time,
        service_type,
    )
    payload = {
        "datasource_id": "",
        "task_id": "process_serviceproductsupport_main",
        "variables": variables,
        "start_time": None,
        "queue": False,
        "export_current_page": False,
    }

    token = auto_login()
    session = create_export_session(token)

    print(
        f"[{ts()}] 创建导出任务 [{prefix}]: "
        f"创建时间 {FIXED_BEGIN_CREATE_TIME} ~ {month_end_time}，"
        f"完成时间 {begin_finish_time} ~ {month_end_time}"
    )
    result = create_export_job(session, payload)

    # 极少数情况下，登录后取得的 Token 可能立即失效；自动重登并重试一次。
    if result.get("code") != 200 and is_login_expired(result):
        print(f"[{ts()}] Token 已失效，正在自动重新登录并重试一次...")
        token = auto_login()
        session = create_export_session(token)
        result = create_export_job(session, payload)

    if result.get("code") != 200:
        raise RuntimeError(f"创建任务失败: {result.get('msg')}")

    job_id = result.get("data")
    if not job_id:
        raise RuntimeError(f"创建任务成功但未返回 job_id: {result}")

    print(f"[{ts()}] Job created: {job_id}")
    poll_job(session, job_id)
    return download_export(
        session,
        job_id,
        begin_finish_time,
        month_end_time,
        prefix,
        output_dir,
    )


def valid_month(value):
    try:
        datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"月份格式错误: {value}，正确格式为 YYYY-MM"
        ) from exc
    return value


# Keep CLI and persistence support local so this collector is self-contained.
def validate_dates(start_date, end_date):
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if start.isoformat() != start_date or end.isoformat() != end_date:
        raise ValueError("Dates must use YYYY-MM-DD")
    if start > end or start.strftime("%Y-%m") != end.strftime("%Y-%m"):
        raise ValueError("Date range must be ordered and within one month")
    return start.strftime("%Y-%m")


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--start-date", required=True)
    result.add_argument("--end-date", required=True)
    result.add_argument("--mode", choices=("file", "database", "both"), default="both")
    result.add_argument("--database", type=Path, help="兼容旧命令；始终使用 database.py 中的 MySQL 配置")
    result.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    result.add_argument("--reuse-existing", action="store_true", help="Import existing exports without downloading")
    result.add_argument("--refresh", action="store_true", help="Download again even if the database already covers the period")
    return result


def covered_result(files, start, end, mode, database, refresh, reuse_existing):
    if refresh or reuse_existing or mode == "file":
        return None
    if mode == "both" and not all(Path(path).is_file() for path in files.values()):
        return None
    if not has_source_coverage(database, files, start, end):
        return None
    return {"start": start, "end": end,
            "files": {code: str(Path(path).resolve()) for code, path in files.items()} if mode == "both" else {},
            "etl": {}, "skipped": True, "skip_reason": "database_already_covered"}


@contextmanager
def download_directory(mode, output_dir, reuse_existing=False):
    if mode == "database" and not reuse_existing:
        with tempfile.TemporaryDirectory(prefix="terminal_download_") as directory:
            yield Path(directory)
    else:
        yield Path(output_dir)


def finish_exports(files, start_date, end_date, mode, database):
    with tempfile.TemporaryDirectory(prefix="terminal_import_") as directory:
        return _finish_exports(files, start_date, end_date, mode, database, Path(directory))


def _finish_exports(files, start_date, end_date, mode, database, staging_dir):
    validate_dates(start_date, end_date)
    if mode not in {"file", "database", "both"}:
        raise ValueError("Unsupported mode")
    result = {"start": start_date, "end": end_date, "files": {}, "etl": {}}
    for code, source in files.items():
        source = Path(source).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if mode != "database":
            result["files"][code] = str(source)
        if mode == "file":
            continue
        dataset = get_dataset(code)
        import_source = source
        etl = import_file(database, dataset, import_source,
                          period_start=start_date, period_end=end_date)
        result["etl"][code] = etl
        if etl["failed"]:
            raise RuntimeError(f"{code}: {etl['failed']} rows failed import")
        etl["snapshot_id"] = save_source(database, code, source, start_date, end_date, etl["run_id"])
    return result



def collect(start_date, end_date, *, mode="both", database=None,
            output_dir=Path(OUTPUT_DIR), reuse_existing=False, refresh=False):
    month = validate_dates(start_date, end_date)
    if mode not in {"file", "database", "both"}:
        raise ValueError("Unsupported mode")
    cached = covered_result({"eoms_service_removal_order": Path(output_dir) / f"服务类产品支撑工单_{month}.xlsx"},
                            start_date, end_date, mode, database, refresh, reuse_existing)
    if cached is not None:
        return cached
    with download_directory(mode, output_dir, reuse_existing) as target_dir:
        path = target_dir / f"服务类产品支撑工单_{month}.xlsx"
        if not reuse_existing:
            path = export_qiwan(start_date + " 00:00:00", end_date + " 23:59:59",
                                service_type="全量", output_dir=str(target_dir))
        return finish_exports({"eoms_service_removal_order": path}, start_date, end_date, mode, database)



def main():
    args = parser("EOMS服务类工单取数及入库").parse_args()
    print(json.dumps(collect(**vars(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
