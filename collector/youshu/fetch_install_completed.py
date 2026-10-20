#!/usr/bin/env python3
"""全省企宽装机报结量：整周期导出地市、区县并校验入库。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from storage import youshu_install_completed as storage
from storage.youshu_install_completed import initialize

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path(__file__).resolve().parent
COMPONENTS = {"city": "c-3RyRNeFPPpeMKBjJQA69rz", "county": "c-pYQPgF1TfDX2VsNYSXjeXe"}
DATE_COMPONENT = "c-nhA776eaE65rKUBeF3jUqB"


def build_task(level, base, start, end):
    storage.validate_period(start, end)
    template = json.loads((MODULE / "task_install_completed_38598.json").read_text("utf-8"))
    filters = [c for c in template["data"]["state"]["components"]
               if c.get("id") == DATE_COMPONENT and c.get("type") == "dateTimeFilter"]
    if len(filters) != 1:
        raise ValueError("报结量日期筛选组件缺失，拒绝使用模板旧日期")
    filters[0]["setting"]["data"]["date"] = {
        "$type": "DateTimeFilter", "mode": {"$type": "StaticTime"},
        "period": {"minBound": f"{start} 00:00:00", "maxBound": f"{end} 24:00:00"}}
    component = COMPONENTS[level]
    base = base.rstrip("/")
    return {
        "name": "企宽装机报结量_" + ("地市" if level == "city" else "区县"),
        "url": f"{base}/bi/api/dash/report/exportExcel?trigger=User",
        "referrer": f"{base}/bi/dash/folder/31?rid=38598&did=136752",
        "setCacheUrl": f"{base}/bi/api/dash/util/setCache?trigger=User",
        "flushReportUrl": f"{base}/bi/api/dash/component/flushComponent?trigger=User&id={component}",
        "setCacheBody": template,
        "dateFilterComponent": DATE_COMPONENT,
        "strictErrors": True,
        "body": {"type": "component", "pid": 31, "reportId": 38598,
                 "dashboardId": 136752, "componentId": component,
                 "tempQueryId": "@@NEW_TEMP_QUERY_ID@@", "exportType": "xlsx",
                 "enhance": False, "useOriginData": True, "conditionFormat": False,
                 "includeTitle": False, "excelSplitLimit": 1000000, "isAsync": True},
    }


def download_pair(directory, start, end, timeout, poll_timeout, *, exporter=None):
    if exporter is None:
        from collector.youshu import fetch_data as exporter
    # Read only authentication/base, not the legacy task list or its file references.
    config = json.loads((MODULE / "有数配置.json").read_text("utf-8"))
    base_headers = {str(k).lower(): v for k, v in config.get("headers", {}).items()}
    base_headers.setdefault("content-type", "application/json")
    base_headers.setdefault("accept", "application/json")
    base_headers.setdefault("x-resource-status", "view")
    base_headers.setdefault("x-time-zone", "8")
    for level in COMPONENTS:
        task = build_task(level, config.get("base", "http://10.76.134.138:30000"), start, end)
        headers = {**base_headers, "referer": task["referrer"]}
        path, kind = exporter.run_export(task, headers, base_headers, str(directory / level),
            start, end, timeout, poll_timeout=poll_timeout)
        if not path or kind != "xlsx" or not exporter.is_valid_xlsx(Path(path).read_bytes()):
            raise RuntimeError(f"{level} 导出失败或未返回完整 XLSX")
        yield level, Path(path)


def write_manifest(path, manifest):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect(start, end, *, mode="both", output_dir=None, refresh=False,
            login_first=False, node="node", timeout=120, poll_timeout=600,
            city_file=None, county_file=None):
    storage.validate_period(start, end)
    if mode not in {"file", "both", "database"}:
        raise ValueError("mode 必须是 file、both 或 database")
    if bool(city_file) != bool(county_file):
        raise ValueError("离线导入必须同时提供地市和区县文件")
    if timeout <= 0 or poll_timeout <= 0:
        raise ValueError("超时必须大于零")
    if mode != "file":
        initialize()
        if not refresh:
            covered = storage.latest_success(start, end)
            if covered:
                return {"skipped": True, "skip_reason": "exact_period_already_covered", "collection_run_id": covered}
    run_id = "completed_" + uuid.uuid4().hex
    root = Path(output_dir) if output_dir else ROOT / "data/raw/youshu"
    if not root.is_absolute():
        root = ROOT / root
    temporary = Path(tempfile.mkdtemp(prefix="youshu_completed_")) if mode == "database" else None
    directory = temporary or root.resolve() / "install_completed" / f"{start}_{end}" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    manifest = {"collection_run_id": run_id, "dataset": storage.DATASET,
        "period_start": start, "period_end": end, "report_id": 38598, "dashboard_id": 136752,
        "date_field": "OPERTIME", "status": "running", "started_at": storage.now(),
        "period_source": "caller_supplied" if city_file else "request_filter", "files": {}}
    write_manifest(manifest_path, manifest)
    started = False
    paths = {}
    try:
        if mode != "file":
            storage.start_run(run_id, start, end)
            started = True
        if city_file:
            for level, source in (("city", city_file), ("county", county_file)):
                destination = directory / level / f"企宽装机报结量_{level}_{start}_{end}.xlsx"
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                paths[level] = destination
        else:
            if login_first:
                from collector.youshu.client import refresh_login
                cfg = json.loads((MODULE / "有数配置.json").read_text("utf-8"))
                base = cfg.get("base", "http://10.76.134.138:30000").rstrip("/")
                refresh_login(node=node, env={**os.environ,
                    "YOUDATA_REPORT_URL": f"{base}/bi/dash/folder/31?rid=38598&did=136752"})
            for level, path in download_pair(directory, start, end, timeout, poll_timeout):
                paths[level] = path
        parsed = storage.validate_pair(paths["city"], paths["county"])
        manifest["files"] = {level: {"path": str(paths[level]), "component_id": COMPONENTS[level],
            "sha256": data["sha256"], "rows": len(data["rows"]), "platform_total": data["total"]}
            for level, data in parsed.items()}
        manifest["validation"] = "passed"
        manifest["status"] = "validated"
        write_manifest(manifest_path, manifest)
        if mode != "file":
            manifest["etl_run_ids"] = storage.import_pair(run_id, start, end, parsed)
        manifest.update(status="success", finished_at=storage.now())
    except Exception as exc:
        manifest.update(status="failed", error=str(exc), finished_at=storage.now(),
                        downloaded_files={k: str(p) for k, p in paths.items()})
        if started:
            try:
                storage.fail_run(run_id, [str(p) for p in paths.values()], exc)
            except Exception as audit_error:
                manifest["audit_error"] = str(audit_error)
        print(f"采集失败，文件和诊断保留于：{directory}", file=sys.stderr)
        write_manifest(manifest_path, manifest)
        raise
    # A manifest write error after a committed import must not mark the DB run failed.
    write_manifest(manifest_path, manifest)
    result = {"skipped": False, "collection_run_id": run_id, "mode": mode,
              "period_start": start, "period_end": end, "total": parsed["city"]["total"],
              "rows": {k: len(v["rows"]) for k, v in parsed.items()},
              "files": {k: str(p) for k, p in paths.items()} if temporary is None else {},
              "manifest": str(manifest_path) if temporary is None else None}
    if temporary:
        shutil.rmtree(temporary)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--mode", choices=("file", "database", "both"), default="both")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--login-first", action="store_true")
    parser.add_argument("--node", default="node")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--poll-timeout", type=int, default=600)
    parser.add_argument("--city-file", type=Path, help="离线导入地市文件；统计周期由调用者明确提供")
    parser.add_argument("--county-file", type=Path, help="离线导入区县文件")
    args = vars(parser.parse_args())
    start, end = args.pop("start_date"), args.pop("end_date")
    print(json.dumps(collect(start, end, **args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
