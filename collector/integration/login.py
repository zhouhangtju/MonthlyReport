"""政企一体化平台 4A 自动登录，仅从显式参数或环境变量读取凭证。"""

from __future__ import annotations

import os
import re
from typing import Any


CAS = "http://10.76.149.228:9082"
APP_CODE = "casR146464"
RESOURCE_ID = "146464"
BASE_URL = "http://188.105.165.237:18083"
TARGET = f"{BASE_URL}/plat/auth/loginZj4A"


def rsa_no_padding(modulus: int, exponent: int, value: str) -> str:
    raw = value.encode("utf-8")
    encrypted = pow(int.from_bytes(raw, "big"), exponent, modulus)
    length = (encrypted.bit_length() + 7) // 8
    return encrypted.to_bytes(length, "big").hex()


def credentials(account: str | None, password: str | None) -> tuple[str, str]:
    resolved_account = account or os.getenv("INTEGRATION_ACCOUNT")
    resolved_password = password or os.getenv("INTEGRATION_PASSWORD")
    if not resolved_account or not resolved_password:
        raise ValueError(
            "缺少一体化登录凭证，请设置 INTEGRATION_ACCOUNT 和 "
            "INTEGRATION_PASSWORD，或传入 --account 和 --password"
        )
    return resolved_account, resolved_password


def login_token(account: str, password: str, session: Any | None = None) -> str:
    if session is None:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("缺少 requests，请安装 requirements.txt") from exc
        client = requests.Session()
    else:
        client = session
    client.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    login_page = client.get(
        f"{CAS}/portalS/platform/iframeLoginZJ.do?appCode={APP_CODE}&target={TARGET}",
        timeout=20,
    )
    login_page.raise_for_status()
    match = re.search(r'getKeyPair\("10001", "", "([0-9a-fA-F]+)"\)', login_page.text)
    if not match:
        raise RuntimeError("4A 登录页未找到 RSA 公钥")
    modulus = int(match.group(1), 16)
    exponent = int("10001", 16)
    form = {
        "username": rsa_no_padding(modulus, exponent, account),
        "password": rsa_no_padding(modulus, exponent, password),
        "userName": account,
        "passWord": password,
        "loginMode": "pwd",
        "code": "111111",
        "challengeCode": "111111",
        "appCode": APP_CODE,
        "resourceId": RESOURCE_ID,
        "isGroupUser": "",
        "target": TARGET,
        "verifyRealCode": "false",
    }
    response = client.post(
        f"{CAS}/portalS/platform/iframeLoginZJ!login.do",
        data=form,
        timeout=30,
    )
    response.raise_for_status()
    match = re.search(r"(pname=[^&]+)", response.url)
    if not match:
        raise RuntimeError("4A 登录后未取得 pname 票据")
    token_response = client.get(
        f"{BASE_URL}/plat/auth/loginZj4APname?{match.group(1)}",
        timeout=30,
    )
    token_response.raise_for_status()
    try:
        token = (token_response.json().get("data") or {}).get("token")
    except (TypeError, ValueError):
        token = None
    token = token or client.cookies.get_dict().get("zy_token")
    if not token:
        raise RuntimeError("一体化登录响应中未找到 zy_token")
    return str(token)

