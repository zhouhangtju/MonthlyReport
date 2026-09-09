"""调用项目内置的有数取数脚本，并衔接双存储和完整采集审计。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config.datasets import get_dataset
from storage.database import connect, has_collection_coverage, initialize
from storage.importer import import_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = Path(__file__).resolve().parent
FETCH_SCRIPT = MODULE_ROOT / "fetch_data.py"
LOGIN_SCRIPT = MODULE_ROOT / "youdata_autologin.js"
LOGIN_CONFIG = MODULE_ROOT / "youdata_login.json"
DATA_CONFIG = MODULE_ROOT / "有数配置.json"

TASKS = {
    "install": {
        "task_name": "企宽新装清单",
        "dataset_code": "youshu_install",
        "prefix": "企宽新装清单_",
        "regions": 11,
    },
    "complaint": {
        "task_name": "企宽投诉清单",
        "dataset_code": "youshu_complaint",
        "prefix": "企宽投诉清单_batch",
        "regions": 1,
    },
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def day_chunks(start: str, end: str, chunk_days: int) -> list[tuple[str, str]]:
    from collector.orchestration.client import date_ranges

    return date_ranges(start, end, chunk_days)


def validate_runtime_files() -> None:
    missing = [
        path for path in (
            FETCH_SCRIPT, LOGIN_SCRIPT, LOGIN_CONFIG, DATA_CONFIG,
        ) if not path.exists()
    ]
    if missing:
        raise FileNotFoundError("有数平台缺少文件：" + ", ".join(str(path) for path in missing))


def refresh_login(node: str = "node", env: dict[str, str] | None = None) -> None:
    validate_runtime_files()
    result = subprocess.run(
        [node, str(LOGIN_SCRIPT)],
        cwd=MODULE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    safe_output = re.sub(
        r"(自动填写账号密码并登录:)\s*.*",
        r"\1 [已隐藏账号]",
        (result.stdout or "") + (result.stderr or ""),
    )
    if safe_output.strip():
        print(safe_output.rstrip())
    if result.returncode != 0:
        raise RuntimeError(f"有数自动登录失败，退出码 {result.returncode}")


def matching_files(directory: Path, kind: str) -> list[Path]:
    prefix = TASKS[kind]["prefix"]
    return sorted(path for path in directory.glob(f"{prefix}*.xlsx") if "合并" not in path.name)


def expected_file_count(kind: str, start: str, end: str, chunk_days: int) -> int:
    return len(day_chunks(start, end, chunk_days)) * int(TASKS[kind]["regions"])


def run_fetch(
    kind: str,
    start: str,
    end: str,
    output_dir: Path,
    *,
    chunk_days: int,
    interval: float,
    timeout: int,
    poll_timeout: int,
    two_phase: bool,
    python: str,
) -> list[Path]:
    validate_runtime_files()
    output_dir.mkdir(parents=True, exist_ok=True)
    before = {path.resolve() for path in matching_files(output_dir, kind)}
    command = [
        python,
        str(FETCH_SCRIPT),
        "--task", str(TASKS[kind]["task_name"]),
        "--start", start,
        "--end", end,
        "--chunk-days", str(chunk_days),
        "--interval", str(interval),
        "--timeout", str(timeout),
        "--poll-timeout", str(poll_timeout),
        "--outdir", str(output_dir),
    ]
    if two_phase:
        command.append("--two-phase")
    result = subprocess.run(command, cwd=MODULE_ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"有数取数脚本执行失败，退出码 {result.returncode}")
    after = {path.resolve() for path in matching_files(output_dir, kind)}
    produced = sorted(after - before)
    expected = expected_file_count(kind, start, end, chunk_days)
    if len(produced) < expected:
        raise RuntimeError(
            f"有数取数文件不完整：预期至少 {expected} 个，本次生成 {len(produced)} 个。"
            "可能是登录凭证失效或部分导出任务失败，请刷新登录后重试。"
        )
    return produced


def collect(
    kind: str,
    start: str,
    end: str,
    *,
    mode: str = "both",
    output_dir: Path = Path("data/raw/youshu"),
    database: Path = Path("data/quality_assessment.db"),
    chunk_days: int = 3,
    interval: float = 0.5,
    timeout: int = 120,
    poll_timeout: int = 600,
    two_phase: bool = False,
    refresh: bool = False,
    login_first: bool = False,
    node: str = "node",
    python: str = sys.executable,
) -> dict[str, object]:
    if kind not in TASKS:
        raise ValueError("kind 必须是 install 或 complaint")
    if mode not in {"file", "database", "both"}:
        raise ValueError("mode 必须是 file、database 或 both")
    output_dir = (
        output_dir.expanduser().resolve()
        if output_dir.is_absolute()
        else (PROJECT_ROOT / output_dir).resolve()
    )
    database = (
        database.expanduser().resolve()
        if database.is_absolute()
        else (PROJECT_ROOT / database).resolve()
    )
    chunks = day_chunks(start, end, chunk_days)
    if not chunks:
        raise ValueError("日期范围为空")
    dataset_code = str(TASKS[kind]["dataset_code"])
    if mode in {"database", "both"} and not refresh and has_collection_coverage(
        database, dataset_code, start, end
    ):
        return {
            "dataset": dataset_code,
            "start": start,
            "end": end,
            "skipped": True,
            "skip_reason": "database_already_covered",
            "files": [],
            "etl_runs": [],
        }
    if login_first:
        refresh_login(node=node)

    collection_id = f"collect_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    expected = expected_file_count(kind, start, end, chunk_days)
    if mode in {"database", "both"}:
        initialize(database)
        with connect(database) as connection:
            connection.execute(
                """INSERT INTO collection_run (
                    collection_run_id, dataset_code, period_start, period_end,
                    started_at, status, expected_files
                ) VALUES (?, ?, ?, ?, ?, 'running', ?)""",
                (collection_id, dataset_code, start, end, now(), expected),
            )

    working_dir = output_dir / dataset_code
    temporary_dir: Path | None = None
    if mode == "database":
        import tempfile
        temporary_dir = Path(tempfile.mkdtemp(prefix="qa_youshu_"))
        working_dir = temporary_dir
    files: list[Path] = []
    etl_results: list[dict[str, object]] = []
    try:
        files = run_fetch(
            kind, start, end, working_dir,
            chunk_days=chunk_days, interval=interval, timeout=timeout,
            poll_timeout=poll_timeout, two_phase=two_phase, python=python,
        )
        if mode in {"database", "both"}:
            for path in files:
                etl_results.append(
                    import_file(
                        database,
                        get_dataset(dataset_code),
                        path,
                        archive_root=None,
                        period_start=start,
                        period_end=end,
                    )
                )
            with connect(database) as connection:
                connection.execute(
                    """UPDATE collection_run SET finished_at=?, status='success',
                       produced_files=?, imported_files=?, source_files=?, etl_run_ids=?
                       WHERE collection_run_id=?""",
                    (
                        now(), len(files), len(etl_results),
                        json.dumps([str(path) for path in files], ensure_ascii=False),
                        json.dumps([item["run_id"] for item in etl_results]),
                        collection_id,
                    ),
                )
    except Exception as exc:
        if mode in {"database", "both"}:
            with connect(database) as connection:
                connection.execute(
                    """UPDATE collection_run SET finished_at=?, status='failed',
                       produced_files=?, imported_files=?, error_message=?
                       WHERE collection_run_id=?""",
                    (now(), len(files), len(etl_results), str(exc), collection_id),
                )
        raise
    finally:
        if temporary_dir is not None:
            shutil.rmtree(temporary_dir)
    return {
        "collection_run_id": collection_id if mode in {"database", "both"} else None,
        "dataset": dataset_code,
        "start": start,
        "end": end,
        "skipped": False,
        "skip_reason": None,
        "files": [str(path.resolve()) for path in files] if mode in {"file", "both"} else [],
        "etl_runs": etl_results,
    }


def run_script(kind: str) -> None:
    label = "企宽新装单" if kind == "install" else "企宽投诉单"
    parser = argparse.ArgumentParser(description=f"从有数平台获取{label}")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/youshu"))
    parser.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    parser.add_argument("--chunk-days", type=int, default=3)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--poll-timeout", type=int, default=600)
    parser.add_argument("--two-phase", action="store_true")
    parser.add_argument("--login-first", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--node", default="node")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    result = collect(
        kind, args.start_date, args.end_date,
        mode=args.mode, output_dir=args.output_dir, database=args.database,
        chunk_days=args.chunk_days, interval=args.interval, timeout=args.timeout,
        poll_timeout=args.poll_timeout, two_phase=args.two_phase,
        refresh=args.refresh, login_first=args.login_first,
        node=args.node, python=args.python,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
