#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""短信登录并将子系统 Cookie 保存到本地文件。

安装：python -m pip install -U requests truststore
运行：python login_save_cookie.py
在能够访问业务系统的网络环境中运行；手机号由 PHONE 固定配置，运行时只需输入短信验证码。
登录后将子系统 Cookie 写入 COOKIE_FILE（每次成功登录覆盖更新），保存后结束。
"""

import time
import os
from getpass import getpass
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

# 必须在导入 requests 前启用系统证书库（truststore 需要 Python 3.10+）。
try:
    import truststore
except ImportError:
    truststore = None
else:
    truststore.inject_into_ssl()

import requests


PHONE = "15824470648"
SSO = "https://rmc-frontend-sso.oss.zj.chinamobile.com"
MAIN = "https://rmc.oss.zj.chinamobile.com"
ENTERPRISE = "https://rmc-static-process-enterprise.oss.zj.chinamobile.com:7415"
TOKEN_NAME = "irm-frontend-process-enterprise-token"
COOKIE_FILE = Path(__file__).resolve().with_name("cookie.txt")
ALLOWED_ORIGINS = {(urlsplit(u).hostname, urlsplit(u).port or 443)
                   for u in (SSO, MAIN, ENTERPRISE)}


def milliseconds():
    return int(time.time() * 1000)


def request(session, method, url, **kwargs):
    """显式处理重定向，防止接口失效时把登录页当成查询结果。"""
    response = session.request(method, url, timeout=(10, 60),
                               allow_redirects=False, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"接口 {urlsplit(url).path} 返回 HTTP {response.status_code}")
    return response


def follow_redirects(session, response):
    """跟随已知系统之间的页面跳转，Session 自动接收和更新 Cookie。"""
    for _ in range(10):
        if not response.is_redirect:
            return response
        target = urljoin(response.url, response.headers["Location"])
        parsed = urlsplit(target)
        if parsed.scheme != "https" or (parsed.hostname, parsed.port or 443) not in ALLOWED_ORIGINS:
            raise RuntimeError("跳转到了未配置的系统地址，请核对登录流程。")
        response = request(session, "GET", target)
    raise RuntimeError("页面重定向次数过多，请检查登录状态。")


def read_json(response):
    if response.is_redirect:
        raise RuntimeError("数据接口发生跳转，登录态可能失效，请重新运行登录。")
    try:
        result = response.json()
    except ValueError:
        raise RuntimeError("接口没有返回 JSON，可能返回了登录页面。") from None
    if not isinstance(result, dict):
        raise RuntimeError("接口返回的数据结构与抓包不一致。")
    return result


def login(session, phone):
    print("1/3 初始化登录会话并发送短信验证码……")
    follow_redirects(session, request(session, "GET", SSO + "/"))
    result = read_json(request(
        session, "GET", f"{SSO}/sso/getDynamicPwd/{phone}",
        params={"_": milliseconds()},
        headers={"Referer": SSO + "/", "X-Requested-With": "XMLHttpRequest"},
    ))
    if str(result.get("resultCode")) != "1":
        raise RuntimeError("短信发送失败：" + str(result.get("resultText", "未知原因")))

    code = getpass("请输入手机收到的短信验证码（输入不回显）：").strip()
    if not code:
        raise RuntimeError("验证码不能为空。")
    print("2/3 提交验证码并建立子系统登录态……")
    response = request(
        session, "POST", SSO + "/sso/doLogin",
        data={"mobilePhone": phone, "dynamicPwd": code,
              "originalUrl": MAIN, "loginType": "2"},
        headers={"Origin": SSO, "Referer": SSO + "/"},
    )
    location = urljoin(response.url, response.headers.get("Location", ""))
    token = parse_qs(urlsplit(location).query).get("token", [None])[0]
    if not response.is_redirect or not token:
        raise RuntimeError("登录未返回预期的 token 跳转地址，请检查验证码是否正确或过期。")
    follow_redirects(session, response)

    response = request(
        session, "GET", ENTERPRISE + "/api/seedToken",
        params={"token": token, "origin": ENTERPRISE + "/", "dc_": milliseconds()},
        headers={"Referer": ENTERPRISE + "/"},
    )
    follow_redirects(session, response)
    host = urlsplit(ENTERPRISE).hostname
    if not any(c.name == TOKEN_NAME and c.value and
               (host == c.domain.lstrip(".") or host.endswith("." + c.domain.lstrip(".")))
               for c in session.cookies):
        raise RuntimeError("seedToken 未建立子系统 Cookie，需要检查该接口实际响应。")


def save_cookie(session, path=COOKIE_FILE):
    """保存子系统 Cookie 请求头，后续脚本可直接读取这一行。"""
    prepared = session.prepare_request(requests.Request(
        "GET", ENTERPRISE + "/api/"))
    cookie_header = prepared.headers.get("Cookie", "")
    values = [part.strip() for part in cookie_header.split(";")
              if part.strip().startswith(TOKEN_NAME + "=")]
    if len(values) != 1 or not values[0].partition("=")[2]:
        raise RuntimeError("未找到唯一有效的子系统 Cookie，未保存文件。")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".txt.tmp")
    temporary.write_text(values[0] + "\n", encoding="utf-8")
    temporary.replace(path)
    print(f"3/3 子系统 Cookie 已保存：{path}")


def main():
    phone = PHONE
    if len(phone) != 11 or not phone.isascii() or not phone.isdigit():
        raise RuntimeError("请输入11位数字手机号。")
    with requests.Session() as session:
        ca_bundle = (os.environ.get("RMC_CA_BUNDLE")
                     or os.environ.get("REQUESTS_CA_BUNDLE")
                     or os.environ.get("CURL_CA_BUNDLE"))
        if ca_bundle:
            if not Path(ca_bundle).is_file():
                raise RuntimeError(f"CA 证书文件不存在：{ca_bundle}")
            session.verify = ca_bundle
        session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
        login(session, phone)
        save_cookie(session)


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.SSLError:
        print("HTTPS 证书校验失败，尚未完成登录。")
        if truststore is None:
            print("请在当前 Python 环境安装：python -m pip install -U requests truststore")
        print("若仍失败，请向管理员获取企业 CA 的 PEM 证书包，再在 PowerShell 设置：")
        print("  $env:RMC_CA_BUNDLE = 'D:\\5G\\crawl\\corp-ca.pem'")
        print("然后重新运行脚本。不会关闭证书校验。")
        raise SystemExit(1)
    except requests.RequestException as exc:
        # 不打印完整异常URL，避免把 token 或验证码输出到终端日志。
        print(f"网络请求失败（{type(exc).__name__}）：请检查网络、证书及系统可用性。")
        raise SystemExit(1)
    except (RuntimeError, OSError) as exc:
        print(f"执行失败：{exc}")
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。")
        raise SystemExit(1)
