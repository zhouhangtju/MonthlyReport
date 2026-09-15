"""EOMS 政企投诉工单取数、文件留存及数据库入库。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from config.datasets import get_dataset
from storage.database import has_successful_coverage
from storage.importer import import_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = Path(__file__).resolve().parent
LOGIN_SCRIPT = MODULE_ROOT / "scripts" / "auto_login_token.py"
CRAWL_SCRIPT = MODULE_ROOT / "scripts" / "complaint_crawl.py"
LOGIN_CONFIG = MODULE_ROOT / "eoms_login.json"
TOKEN_DATABASE = MODULE_ROOT / "login.db"
DATASET_CODE = "eoms_complaint"


def resolve_project_path(path: Path) -> Path:
    path = path.expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def validate_runtime_files(*, require_login_config: bool = False) -> None:
    required = [LOGIN_SCRIPT, CRAWL_SCRIPT]
    if require_login_config:
        required.append(LOGIN_CONFIG)
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("EOMS 缺少运行文件：" + ", ".join(map(str, missing)))


def refresh_login(
    *,
    python: str = sys.executable,
    account: str | None = None,
    password: str | None = None,
) -> None:
    validate_runtime_files(require_login_config=not (account and password))
    command = [python, str(LOGIN_SCRIPT)]
    if account:
        command.extend(["--account", account])
    if password:
        command.extend(["--password", password])
    result = subprocess.run(command, cwd=MODULE_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"EOMS 自动登录失败，退出码 {result.returncode}")
    if not TOKEN_DATABASE.is_file():
        raise RuntimeError("EOMS 登录脚本执行完成，但没有生成 login.db")


def run_crawl(
    start: str,
    end: str,
    output: Path,
    *,
    page_size: int = 500,
    python: str = sys.executable,
) -> Path:
    validate_runtime_files()
    if not TOKEN_DATABASE.is_file():
        raise FileNotFoundError(
            f"EOMS Token 缓存不存在：{TOKEN_DATABASE}；请先运行 collector/eoms/refresh_login.py"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        python,
        str(CRAWL_SCRIPT),
        "--start", start,
        "--end", end,
        "--output", str(output),
        "--page-size", str(page_size),
    ]
    result = subprocess.run(command, cwd=MODULE_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"EOMS 投诉工单取数失败，退出码 {result.returncode}")
    if not output.is_file():
        raise RuntimeError("EOMS 取数脚本执行完成，但没有生成预期 Excel")
    signature = output.read_bytes()[:8]
    if not (signature.startswith(b"PK\x03\x04") or signature.startswith(b"\xd0\xcf\x11\xe0")):
        raise RuntimeError("EOMS 输出文件不是有效的 Excel 文件")
    return output


def collect(
    start: str,
    end: str,
    *,
    mode: str = "both",
    output_dir: Path = Path("data/raw/eoms"),
    database: Path = Path("data/quality_assessment.db"),
    page_size: int = 500,
    refresh: bool = False,
    login_first: bool = False,
    account: str | None = None,
    password: str | None = None,
    python: str = sys.executable,
) -> dict[str, object]:
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    if page_size < 1:
        raise ValueError("page_size 必须大于等于 1")
    database = resolve_project_path(database)
    output_dir = resolve_project_path(output_dir)
    if mode in {"database", "both"} and not refresh and has_successful_coverage(
        database, DATASET_CODE, start, end
    ):
        expected = output_dir / DATASET_CODE / f"投诉工单_原始数据_{start.replace('-', '')}-{end.replace('-', '')}.xlsx"
        return {
            "dataset": DATASET_CODE,
            "start": start,
            "end": end,
            "file": str(expected) if mode == "both" and expected.exists() else None,
            "downloaded": False,
            "etl": None,
            "skipped": True,
            "skip_reason": "database_already_covered",
        }
    if login_first:
        refresh_login(python=python, account=account, password=password)

    temporary_dir: Path | None = None
    if mode == "database":
        temporary_dir = Path(tempfile.mkdtemp(prefix="qa_eoms_"))
        target_dir = temporary_dir
    else:
        target_dir = output_dir / DATASET_CODE
    target = target_dir / f"投诉工单_原始数据_{start.replace('-', '')}-{end.replace('-', '')}.xlsx"
    try:
        path = run_crawl(start, end, target, page_size=page_size, python=python)
        etl = None
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
            "dataset": DATASET_CODE,
            "start": start,
            "end": end,
            "file": str(path.resolve()) if mode in {"file", "both"} else None,
            "downloaded": True,
            "etl": etl,
            "skipped": False,
            "skip_reason": None,
        }
    finally:
        if temporary_dir is not None:
            shutil.rmtree(temporary_dir)


def run_script() -> None:
    parser = argparse.ArgumentParser(description="从 EOMS 获取政企投诉工单")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/eoms"))
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--login-first", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--account", help="推荐改用 EOMS_ACCOUNT 环境变量或 eoms_login.json")
    parser.add_argument("--password", help="推荐改用 EOMS_PASSWORD 环境变量或 eoms_login.json")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    result = collect(
        args.start_date,
        args.end_date,
        mode=args.mode,
        output_dir=args.output_dir,
        database=args.database,
        page_size=args.page_size,
        refresh=args.refresh,
        login_first=args.login_first,
        account=args.account,
        password=args.password,
        python=args.python,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
