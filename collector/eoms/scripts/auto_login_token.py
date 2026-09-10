#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EOMS 4A 密码登录，获取 Bearer Token 并保存到 login.db。"""

import argparse
import getpass
import json
import os
import re
import sqlite3
import sys
import time
from urllib.parse import parse_qs, urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PACKAGE_ROOT, "login.db")
CONFIG_PATH = os.path.join(PACKAGE_ROOT, "eoms_login.json")
CAS_BASE = "http://10.76.149.228:9082"
EOMS_BASE = "http://eoms.zj.chinamobile.com"
EOMS_API = f"{EOMS_BASE}/prod-api"
APP_CODE = "casR15643"
RESOURCE_ID = "15643"
TARGET = f"{EOMS_BASE}/fouraLogin"


def rsa_with_no_padding(modulus, exponent, value):
    raw = value.encode("utf-8")
    plain_int = int.from_bytes(raw, byteorder="big", signed=False)
    encrypted_int = pow(plain_int, exponent, modulus)
    size = (encrypted_int.bit_length() + 7) // 8
    return encrypted_int.to_bytes(size, byteorder="big").hex()


def load_credentials(account_arg=None, password_arg=None):
    account = account_arg or os.environ.get("EOMS_ACCOUNT", "")
    password = password_arg or os.environ.get("EOMS_PASSWORD", "")
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
        account = account or str(config.get("account", "")).strip()
        password = password or str(config.get("password", ""))
    if not account:
        account = input("EOMS 4A 账号: ").strip()
    if not password:
        password = getpass.getpass("EOMS 4A 密码: ")
    if not account or not password:
        raise RuntimeError("账号或密码为空")
    return account, password


def get_rsa_key(session):
    # 沿用 OpenClaw-32 已验证的 4A 公钥获取入口。
    url = (
        f"{CAS_BASE}/portalS/platform/iframeLoginZJ.do"
        "?appCode=casR15623&target=http://rmc-frontend-sso.oss.zj.chinamobile.com:80"
        "/redirect?originalUrl=http://rmc.oss.zj.chinamobile.com"
    )
    response = session.get(url, timeout=20)
    response.raise_for_status()
    match = re.search(r'getKeyPair\("10001",\s*"",\s*"([0-9a-fA-F]+)"\)', response.text)
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


def login(account, password):
    session = requests.Session()
    session.verify = False
    session.allow_redirects = False
    session.headers.update({
        "Referer": f"{CAS_BASE}/portalS/platform/iframeLoginZJ.do?appCode={APP_CODE}&target={TARGET}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
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
    response = session.post(login_url, data=form, timeout=30, allow_redirects=False)
    location = response.headers.get("Location", "")
    if not location:
        response = session.post(login_url, data=form, timeout=30, allow_redirects=True)
        location = response.url
    pname = extract_pname(location)
    response = session.post(
        f"{EOMS_API}/auth/a4login?t={int(time.time() * 1000)}",
        json={"pname": pname},
        headers={"Content-Type": "application/json", "Referer": location},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"EOMS a4login 失败: {payload.get('msg') or str(payload)[:160]}")
    token = str((payload.get("data") or {}).get("token", "")).replace("Bearer ", "").strip()
    if not token:
        raise RuntimeError("EOMS a4login 返回中未找到 token")
    return token


def save_token(token):
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS login_info (phone TEXT, token TEXT, login_time TEXT)")
        cur.execute("DELETE FROM login_info WHERE phone = ?", ("eoms_user",))
        cur.execute(
            "INSERT INTO login_info (phone, token, login_time) VALUES (?, ?, datetime('now', 'localtime'))",
            ("eoms_user", f"Bearer {token}"),
        )
        conn.commit()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="EOMS 4A 密码登录并刷新 login.db")
    parser.add_argument("--account", help="EOMS 4A 账号")
    parser.add_argument("--password", help="EOMS 4A 密码")
    args = parser.parse_args()
    account, password = load_credentials(args.account, args.password)
    masked_account = account[:2] + "***" + account[-2:] if len(account) > 4 else "***"
    print(f"[login] EOMS 4A 账号: {masked_account}")
    token = login(account, password)
    save_token(token)
    print(f"[OK] EOMS Token 已更新: {DB_PATH}")
    print(f"[OK] Token: {token[:12]}...（已隐藏）")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
