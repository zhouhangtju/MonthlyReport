"""编排系统取数连接器。

由历史 `export/编排` 脚本迁移而来，运行时不依赖该目录，包含两类下载：
- 专线开通情况（orch_opening）
- 互联网专线新装单（orch_install）
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from config.datasets import get_dataset
from storage.database import has_successful_coverage
from storage.importer import import_file


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class OrchestrationExport:
    code: str
    filename_prefix: str
    base_url: str

    def params(self, start: str, end: str) -> dict[str, Any]:
        common: dict[str, Any] = {
            "isExplortConfRsult": 0,
            "status": 1,
            "service_catalog": "ProvGCDedicatedLine",
            "page": 1,
            "limit": 10,
            "is_child": 0,
        }
        if self.code == "orch_opening":
            return {**common, "finish_start_time": start, "finish_end_time": end}
        return {
            **common,
            "order_type": 2,
            "service_type": "ProvInternetLine",
            "start_time": start,
            "end_time": end,
        }


EXPORTS = {
    "opening": OrchestrationExport(
        "orch_opening",
        "专线工单",
        "http://188.103.124.75:9527/soc/export/order/submittedZj/download/tzzhanglifeng",
    ),
    "install": OrchestrationExport(
        "orch_install",
        "互联网专线新装单",
        "http://188.103.124.75:9527/soc/export/order/submittedZj/download/sundongchuan",
    ),
}


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"日期 {value!r} 无效，请使用 YYYY-MM-DD 格式") from exc


def date_ranges(start: str, end: str, chunk_days: int = 3) -> list[tuple[str, str]]:
    start_date = parse_date(start)
    end_date = parse_date(end)
    if start_date > end_date:
        raise ValueError("start_date 不能晚于 end_date")
    if chunk_days < 1:
        raise ValueError("chunk_days 必须大于等于 1")
    ranges: list[tuple[str, str]] = []
    cursor = start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end_date)
        ranges.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return ranges


def looks_like_excel(first_bytes: bytes, content_type: str) -> bool:
    content_type = content_type.lower()
    return (
        first_bytes.startswith(b"PK\x03\x04")
        or first_bytes.startswith(b"\xd0\xcf\x11\xe0")
        or "spreadsheet" in content_type
        or "excel" in content_type
        or "octet-stream" in content_type
    )


def download_one(
    export: OrchestrationExport,
    start: str,
    end: str,
    output_dir: Path,
    *,
    timeout: float = 180,
    zytoken: str | None = None,
    cookie: str | None = None,
    overwrite: bool = False,
    session: Any | None = None,
) -> tuple[Path, bool]:
    parse_date(start)
    parse_date(end)
    if start > end:
        raise ValueError("start_date 不能晚于 end_date")
    if timeout <= 0:
        raise ValueError("timeout 必须大于 0")
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{export.filename_prefix}_{start}_{end}.xlsx"
    if target.exists() and not overwrite:
        return target, False

    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if zytoken:
        headers["zytoken"] = zytoken
    if cookie:
        headers["Cookie"] = cookie
    if session is None:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("缺少 requests，请先执行 python3 -m pip install -r requirements.txt") from exc
        client = requests.Session()
    else:
        client = session
    partial = target.with_suffix(".xlsx.part")
    try:
        with client.get(
            export.base_url,
            params=export.params(start, end),
            headers=headers,
            stream=True,
            timeout=timeout,
        ) as response:
            response.raise_for_status()
            chunks = response.iter_content(chunk_size=8192)
            first = next(chunks, b"")
            content_type = response.headers.get("content-type", "")
            if not first:
                raise ValueError("编排接口返回空内容")
            if not looks_like_excel(first, content_type):
                preview = first[:300].decode("utf-8", errors="replace")
                raise ValueError(
                    f"编排接口未返回 Excel，content-type={content_type!r}，"
                    f"响应摘要={preview!r}"
                )
            with partial.open("wb") as target_file:
                target_file.write(first)
                for chunk in chunks:
                    if chunk:
                        target_file.write(chunk)
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        if session is None:
            client.close()
    return target, True


def collect(
    kind: str,
    start: str,
    end: str,
    *,
    mode: str = "both",
    output_dir: Path = Path("data/raw/orchestration"),
    database: Path = Path("data/quality_assessment.db"),
    chunk_days: int = 3,
    interval: float = 2,
    timeout: float = 180,
    overwrite: bool = False,
    zytoken: str | None = None,
    cookie: str | None = None,
    session: Any | None = None,
) -> list[dict[str, object]]:
    if kind not in EXPORTS:
        raise ValueError(f"未知编排取数类型：{kind}")
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    if interval < 0:
        raise ValueError("interval 不能小于 0")
    export = EXPORTS[kind]
    ranges = date_ranges(start, end, chunk_days)
    results: list[dict[str, object]] = []

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if mode == "database":
        temporary = tempfile.TemporaryDirectory(prefix="qa_orchestration_")
        download_dir = Path(temporary.name)
    else:
        download_dir = output_dir / export.code

    try:
        for index, (batch_start, batch_end) in enumerate(ranges, 1):
            expected_path = download_dir / f"{export.filename_prefix}_{batch_start}_{batch_end}.xlsx"
            if (
                mode in {"database", "both"}
                and not overwrite
                and has_successful_coverage(database, export.code, batch_start, batch_end)
            ):
                results.append(
                    {
                        "start": batch_start,
                        "end": batch_end,
                        "file": (
                            str(expected_path.resolve())
                            if mode == "both" and expected_path.exists()
                            else None
                        ),
                        "downloaded": False,
                        "etl": None,
                        "skipped": True,
                        "skip_reason": "database_already_covered",
                    }
                )
                continue
            path, downloaded = download_one(
                export,
                batch_start,
                batch_end,
                download_dir,
                timeout=timeout,
                zytoken=zytoken,
                cookie=cookie,
                overwrite=overwrite,
                session=session,
            )
            item: dict[str, object] = {
                "start": batch_start,
                "end": batch_end,
                "file": str(path.resolve()) if mode in {"file", "both"} else None,
                "downloaded": downloaded,
                "etl": None,
                "skipped": False,
                "skip_reason": None,
            }
            if mode in {"database", "both"}:
                item["etl"] = import_file(
                    database,
                    get_dataset(export.code),
                    path,
                    archive_root=None,
                    period_start=batch_start,
                    period_end=batch_end,
                )
            results.append(item)
            if index < len(ranges) and interval:
                time.sleep(interval)
    finally:
        if temporary is not None:
            temporary.cleanup()
    return results


def environment_credentials() -> tuple[str | None, str | None]:
    return os.getenv("GDDL_ZYTOKEN"), os.getenv("GDDL_COOKIE")


def run_script(kind: str) -> None:
    label = "专线开通情况" if kind == "opening" else "互联网专线新装单"
    parser = argparse.ArgumentParser(description=f"从编排系统获取{label}")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/orchestration"))
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    parser.add_argument("--chunk-days", type=int, default=3)
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument(
        "--refresh",
        "--overwrite",
        dest="overwrite",
        action="store_true",
        help="忽略数据库已有周期和已有文件，强制重新拉取",
    )
    parser.add_argument("--zytoken")
    parser.add_argument("--cookie")
    args = parser.parse_args()
    env_token, env_cookie = environment_credentials()
    result = collect(
        kind,
        args.start_date,
        args.end_date,
        mode=args.mode,
        output_dir=args.output_dir,
        database=args.database,
        chunk_days=args.chunk_days,
        interval=args.interval,
        timeout=args.timeout,
        overwrite=args.overwrite,
        zytoken=args.zytoken or env_token,
        cookie=args.cookie or env_cookie,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
