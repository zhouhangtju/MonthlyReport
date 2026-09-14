"""政企一体化平台售中开通工单取数与入库。"""

from __future__ import annotations

import argparse
import base64
import json
import os
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from collector.integration.login import BASE_URL, credentials, login_token
from config.datasets import get_dataset
from storage.database import has_successful_coverage
from storage.importer import import_file


EXPORT_URL = f"{BASE_URL}/api/work/workmng/exop/exportHalfWayNew"
DATASET_CODE = "integration_opening"

EXPORT_HEADERS = [
    "工单号", "工单主题", "工单数据来源", "上游工单号", "派单时间", "受理部门",
    "工单流向", "地市", "区县", "业务类型", "工单类型", "调整类型",
    "是否存在关联工单", "关联工单号", "工单状态", "是否超时", "是否撤单重录",
    "首次派单时间", "首次考核超时时限", "考核超时时限", "工单是否及时开通",
    "业务开通时间(h)", "工单历时/小时", "工单处理时限", "工单结束时间",
    "业务套餐类型", "业务保障等级", "计费号/产品实例编号", "是否派发工程施工",
]

EXPORT_HEADER_ENS = [
    "orderId", "title", "dataSources", "serialNo", "createTime", "dealPerson",
    "organizatonLev", "regionName", "countyName", "serviceType", "ordertype",
    "revisionType", "isExistsRelatedSerialNo", "relatedSerialNo", "status", "isOverTime",
    "isRecord", "firstCreateTime", "firstCriteriaDate", "criteriaLimitTime",
    "businessIsOver", "businessOpneTime", "finshUseTime", "limitTime", "endTime",
    "productName", "assuranceLevel", "productNo", "isProjectManagements",
]


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"日期 {value!r} 无效，请使用 YYYY-MM-DD 格式") from exc


def request_body(start: str, end: str) -> dict[str, object]:
    if parse_date(start) > parse_date(end):
        raise ValueError("开始日期不能晚于结束日期")
    return {
        "endTimeStart": f"{start} 00:00:00",
        "endTimeEnd": f"{end} 23:59:59",
        "ordertypeList": ["开通"],
        "statusList": [],
        "dataSources": "二编",
        "serviceType": [],
        "headers": EXPORT_HEADERS,
        "headerEns": EXPORT_HEADER_ENS,
        "isRecord": "",
    }


def token_identity(token: str) -> tuple[str | None, str | None]:
    try:
        jwt = token[4:] if token.startswith("web_") else token
        payload = jwt.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        return data.get("sub"), data.get("netUserid") or data.get("netUserId")
    except Exception:
        return None, None


def build_session(token: str) -> Any:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests，请安装 requirements.txt") from exc
    account_id, net_user_id = token_identity(token)
    session = requests.Session()
    session.verify = False
    session.headers.update(
        {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": BASE_URL,
            "Referer": f"{BASE_URL}/dc-form/show/operationSupervision?pageType=zd",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Zy_token": token,
            "Zytoken": token,
        }
    )
    cookie_options = {"domain": "188.105.165.237", "path": "/"}
    session.cookies.set("zy_token", token, **cookie_options)
    if account_id:
        session.cookies.set("zy-user-id", str(account_id), **cookie_options)
    if net_user_id:
        session.cookies.set("zy-netuser-id", str(net_user_id), **cookie_options)
    session.cookies.set("zy-systemTime", time.strftime("%Y-%m-%d %H:%M:%S"), **cookie_options)
    return session


def excel_extension(content: bytes) -> str | None:
    if content.startswith(b"PK\x03\x04"):
        return ".xlsx"
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        return ".xls"
    return None


def response_preview(response: Any, limit: int = 800) -> str:
    content_type = response.headers.get("Content-Type", "")
    if "json" in content_type.lower():
        try:
            return json.dumps(response.json(), ensure_ascii=False)[:limit]
        except Exception:
            pass
    return response.content[:limit].decode("utf-8", errors="replace")


def download_one(
    start: str,
    end: str,
    output_dir: Path,
    token: str,
    *,
    timeout: float = 180,
    overwrite: bool = False,
    session: Any | None = None,
) -> tuple[Path, bool]:
    request_body(start, end)
    if timeout <= 0:
        raise ValueError("timeout 必须大于 0")
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = list(output_dir.glob(f"售中开通工单_{start}_至_{end}.*"))
    if existing and not overwrite:
        return sorted(existing)[-1], False
    client = session or build_session(token)
    response = client.post(
        EXPORT_URL,
        json=request_body(start, end),
        timeout=timeout,
        verify=False,
        allow_redirects=True,
    )
    if response.status_code != 200:
        raise RuntimeError(f"一体化导出失败，HTTP {response.status_code}：{response_preview(response)}")
    extension = excel_extension(response.content)
    if extension is None:
        raise RuntimeError(f"一体化接口未返回 Excel：{response_preview(response)}")
    target = output_dir / f"售中开通工单_{start}_至_{end}{extension}"
    partial = target.with_suffix(target.suffix + ".part")
    try:
        partial.write_bytes(response.content)
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        if session is None:
            client.close()
    return target, True


def collect(
    start: str,
    end: str,
    *,
    mode: str = "both",
    output_dir: Path = Path("data/raw/integration"),
    database: Path = Path("data/quality_assessment.db"),
    timeout: float = 180,
    refresh: bool = False,
    token: str | None = None,
    account: str | None = None,
    password: str | None = None,
    session: Any | None = None,
) -> dict[str, object]:
    request_body(start, end)
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    if mode in {"database", "both"} and not refresh and has_successful_coverage(
        database, DATASET_CODE, start, end
    ):
        candidates = list((output_dir / DATASET_CODE).glob(f"售中开通工单_{start}_至_{end}.*"))
        return {
            "start": start,
            "end": end,
            "file": str(sorted(candidates)[-1].resolve()) if mode == "both" and candidates else None,
            "downloaded": False,
            "etl": None,
            "skipped": True,
            "skip_reason": "database_already_covered",
        }

    resolved_token = token or os.getenv("INTEGRATION_ZYTOKEN")
    if not resolved_token:
        resolved_account, resolved_password = credentials(account, password)
        resolved_token = login_token(resolved_account, resolved_password)

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if mode == "database":
        temporary = tempfile.TemporaryDirectory(prefix="qa_integration_")
        target_dir = Path(temporary.name)
    else:
        target_dir = output_dir / DATASET_CODE
    try:
        path, downloaded = download_one(
            start, end, target_dir, resolved_token, timeout=timeout, overwrite=refresh, session=session
        )
        etl = None
        if mode == "file":
            from storage.raw_archive import archive_download
            archive_download(path, database, DATASET_CODE, start, end)
        if mode in {"database", "both"}:
            etl = import_file(
                database,
                get_dataset(DATASET_CODE),
                path,
                archive_root=None,
                period_start=start,
                period_end=end,
            )
        return {
            "start": start,
            "end": end,
            "file": str(path.resolve()) if mode in {"file", "both"} else None,
            "downloaded": downloaded,
            "etl": etl,
            "skipped": False,
            "skip_reason": None,
        }
    finally:
        if temporary is not None:
            temporary.cleanup()


def run_script() -> None:
    parser = argparse.ArgumentParser(description="从一体化平台获取售中开通工单")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/integration"))
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--refresh", "--overwrite", dest="refresh", action="store_true")
    parser.add_argument("--token", help="一体化 zy_token，推荐改用 INTEGRATION_ZYTOKEN")
    parser.add_argument("--account", help="4A 账号，推荐改用 INTEGRATION_ACCOUNT")
    parser.add_argument("--password", help="4A 密码，推荐改用 INTEGRATION_PASSWORD")
    args = parser.parse_args()
    result = collect(
        args.start_date,
        args.end_date,
        mode=args.mode,
        output_dir=args.output_dir,
        database=args.database,
        timeout=args.timeout,
        refresh=args.refresh,
        token=args.token,
        account=args.account,
        password=args.password,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

