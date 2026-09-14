# -*- coding: utf-8 -*-
"""
复用物资脚本的一体化自动登录获取 token，按月份导出售中工单。

筛选口径：工单结束时间、拆除、结束类状态、二编。

示例：
    python collector/integration/zhuanxian_chaiji_export.py --start-date 2026-08-01 --end-date 2026-08-31
"""

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
from collector.integration import integration_dismantle as integration_auth
from storage.importer import file_sha256, import_file, iter_rows, row_payload
from storage.terminal_recovery import has_source_coverage, save_source

import io
import json
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import requests


BASE_DIR = r"D:\edge_download"
API_URL = (
    "http://188.105.165.237:18083"
    "/api/work/workmng/exop/exportHalfWayNew"
)


def load_token():
    """与物资取数使用相同的登录、Token 提取和凭据保存流程。"""
    account = integration_auth.DEFAULT_ACCOUNT
    with requests.Session() as session:
        session.verify = False
        session.headers.update({"User-Agent": "Mozilla/5.0", "Origin": integration_auth.CAS})
        session = integration_auth.login(session, account, integration_auth.DEFAULT_PASSWORD)
        token = integration_auth.extract_token(session)
        integration_auth.update_cred_json(account, token)
    return token, account


def build_headers(token):
    return {"content-type": "application/json", "zy_token": token, "zytoken": token}


EXPORT_LIMIT = 20000
EXPORT_TIMEOUT = 180
EXPORT_MAX_RETRIES = 3
END_STATUSES = [
    "已完成", "已结束", "已关闭", "结束",
    "自动归档", "自动归档", "关闭", "已报结",
]


def log(message):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), message))


def build_export_body(start_time, end_time):
    """按前端实际负载构造导出条件。"""
    return {
        # 以下筛选字段及层级与前端实际请求负载保持一致。
        "endTimeStart": start_time,
        "endTimeEnd": end_time,
        "ordertypeList": ["拆除"],
        "statusList": END_STATUSES.copy(),
        "dataSources": "二编",
        "serviceType": [],
        "isRecord": "",
        "headers": [
            "工单号", "工单主题", "工单数据来源", "上游工单号", "派单时间",
            "受理部门", "工单流向", "地市", "区县", "业务类型", "工单类型",
            "调整类型", "是否存在关联工单", "关联工单号", "工单状态", "是否超时",
            "是否撤单重录", "首次派单时间", "首次考核超时时限", "考核超时时限",
            "工单是否及时开通", "业务开通时间(h)", "工单历时/小时", "工单处理时限",
            "工单结束时间", "业务套餐类型", "业务保障等级", "计费号/产品实例编号",
            "是否派发工程施工",
        ],
        "headerEns": [
            "orderId", "title", "dataSources", "serialNo", "createTime", "dealPerson",
            "organizatonLev", "regionName", "countyName", "serviceType", "ordertype",
            "revisionType", "isExistsRelatedSerialNo", "relatedSerialNo", "status",
            "isOverTime", "isRecord", "firstCreateTime", "firstCriteriaDate",
            "criteriaLimitTime", "businessIsOver", "businessOpneTime", "finshUseTime",
            "limitTime", "endTime", "productName", "assuranceLevel", "productNo",
            "isProjectManagements",
        ],
    }


def normalize_export_dataframe(raw_df):
    """识别接口文件中的真正表头，兼容表格顶部存在标题行。"""
    if raw_df.empty:
        return raw_df

    expected_headers = {
        "工单号", "工单主题", "工单数据来源", "工单结束时间", "客户名称",
        "任务情况", "业务类型", "地市", "回访结果",
    }
    best_row = 0
    best_score = -1
    for row_no in range(min(10, len(raw_df))):
        values = {
            str(value).strip()
            for value in raw_df.iloc[row_no].tolist()
            if pd.notna(value)
        }
        score = len(values & expected_headers)
        if score > best_score:
            best_row = row_no
            best_score = score

    columns = [
        str(value).strip() if pd.notna(value) else "未命名列_%d" % index
        for index, value in enumerate(raw_df.iloc[best_row].tolist())
    ]
    df = raw_df.iloc[best_row + 1:].copy()
    df.columns = columns
    return df.dropna(how="all").reset_index(drop=True)


def read_export_content(content):
    """兼容读取接口返回的 xls、xlsx 或 HTML 表格。"""
    readers = (
        lambda: pd.read_excel(io.BytesIO(content), header=None),
        lambda: pd.read_excel(io.BytesIO(content), header=None, engine="openpyxl"),
        lambda: pd.read_excel(io.BytesIO(content), header=None, engine="xlrd"),
        lambda: pd.read_html(io.BytesIO(content), header=None)[0],
    )
    last_error = None
    for reader in readers:
        try:
            return normalize_export_dataframe(reader())
        except Exception as ex:
            last_error = ex
    raise RuntimeError("接口返回表格读取失败: %s" % last_error)


def filter_export_dataframe(df):
    """合并后按接口返回的中文字段再次兜底过滤。"""
    if df.empty:
        return df

    df.columns = [str(column).strip() for column in df.columns]
    mask = pd.Series(True, index=df.index)

    for column in ("工单类型", "订单类型", "操作类型"):
        if column in df.columns:
            mask &= df[column].astype(str).str.contains("拆除", na=False)
            break

    for column in ("工单状态", "订单状态", "任务情况"):
        if column in df.columns:
            mask &= df[column].astype(str).str.strip().isin(set(END_STATUSES))
            break

    if "工单数据来源" in df.columns:
        mask &= df["工单数据来源"].astype(str).str.contains(
            "二编|二编辑", na=False, regex=True
        )

    filtered = df[mask].copy().reset_index(drop=True)
    log("本地兜底过滤后保留 %d/%d 条" % (len(filtered), len(df)))
    return filtered


def export_order_data(start_date, end_date, month_text, output_dir, headers):
    """按天导出；某个时间段达到 20000 条时自动拆成两个时间段。"""
    os.makedirs(output_dir, exist_ok=True)
    frames = []
    request_count = 0

    def request_range(range_start, range_end):
        nonlocal request_count

        start_text = range_start.strftime("%Y-%m-%d %H:%M:%S")
        end_text = range_end.strftime("%Y-%m-%d %H:%M:%S")
        body = build_export_body(start_text, end_text)
        log("正在导出 %s 至 %s" % (start_text, end_text))

        last_error = None
        day_df = None
        for attempt in range(1, EXPORT_MAX_RETRIES + 1):
            request_count += 1
            try:
                response = requests.post(
                    API_URL,
                    json=body,
                    headers=headers,
                    timeout=EXPORT_TIMEOUT,
                )
                if response.status_code != 200:
                    last_error = "HTTP %d: %s" % (
                        response.status_code, response.text[:300]
                    )
                elif "json" in response.headers.get("content-type", "").lower():
                    last_error = "接口返回 JSON: %s" % response.text[:300]
                else:
                    day_df = read_export_content(response.content)
                    log("当前时间段取得 %d 条" % len(day_df))
                    break
            except Exception as ex:
                last_error = str(ex)

            log("警告：第 %d 次请求失败：%s" % (attempt, last_error))
            if attempt < EXPORT_MAX_RETRIES:
                time.sleep(3)
        else:
            raise RuntimeError(
                "%s 至 %s 连续请求失败：%s"
                % (start_text, end_text, last_error)
            )

        if len(day_df) >= EXPORT_LIMIT:
            if range_start >= range_end:
                raise RuntimeError(
                    "时间点 %s 仍达到 %d 条，无法继续拆分"
                    % (start_text, EXPORT_LIMIT)
                )
            midpoint = range_start + (range_end - range_start) // 2
            right_start = midpoint + timedelta(seconds=1)
            log("当前时间段达到 %d 条上限，自动拆分后重新请求" % EXPORT_LIMIT)
            request_range(range_start, midpoint)
            request_range(right_start, range_end)
            return

        frames.append(day_df)

    full_start = datetime.strptime(start_date, "%Y-%m-%d")
    full_end = datetime.strptime(end_date, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59
    )
    if full_start > full_end:
        raise ValueError("开始日期不能晚于结束日期")

    current_start = full_start
    while current_start <= full_end:
        current_end = min(
            current_start.replace(hour=23, minute=59, second=59), full_end
        )
        request_range(current_start, current_end)
        current_start = current_end + timedelta(seconds=1)

    merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    filtered = filter_export_dataframe(merged)

    filename = "一体化专线拆机清单_%s.xlsx" % month_text
    filepath = os.path.join(output_dir, filename)
    filtered.to_excel(filepath, index=False, engine="openpyxl")

    log("合并完成，共 %d 条，请求接口 %d 次" % (len(filtered), request_count))
    log("已保存：%s" % filepath)
    return filepath


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
    result.add_argument("--database", type=Path, default=Path("data/quality_assessment.db"))
    result.add_argument("--output-dir", type=Path, default=Path(r"D:\edge_download"))
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
            from storage.raw_archive import archive_download
            archive_download(source, database, code, start_date, end_date)
            continue
        dataset = get_dataset(code)
        import_source = source
        # Keep the Excel untouched. Content + occurrence preserves duplicate detail
        # lines and makes re-imports independent of the exported row order.
        if dataset.key_column == "导入行主键":
            target_dir = staging_dir / code
            target_dir.mkdir(parents=True, exist_ok=True)
            import_source = target_dir / f"{file_sha256(source)[:12]}_{source.stem}.csv"
            rows = iter_rows(source)
            first = next(rows, None)
            occurrences = Counter()
            with import_source.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=[dataset.key_column, *(first or {})])
                writer.writeheader()
                for row in itertools.chain([first] if first is not None else [], rows):
                    _, digest = row_payload(row)
                    occurrences[digest] += 1
                    key = f"{start_date[:7]}:{digest}:{occurrences[digest]}"
                    writer.writerow({dataset.key_column: key, **row})
        etl = import_file(Path(database), dataset, import_source,
                          period_start=start_date, period_end=end_date)
        result["etl"][code] = etl
        if etl["failed"]:
            raise RuntimeError(f"{code}: {etl['failed']} rows failed import")
        etl["snapshot_id"] = save_source(database, code, source, start_date, end_date, etl["run_id"])
    return result



def collect(start_date, end_date, *, mode="both", database=Path("data/quality_assessment.db"),
            output_dir=Path(BASE_DIR), reuse_existing=False, refresh=False):
    month = validate_dates(start_date, end_date)
    if mode not in {"file", "database", "both"}:
        raise ValueError("Unsupported mode")
    cached = covered_result({"integration_removal_order": Path(output_dir) / f"一体化专线拆机清单_{month}.xlsx"},
                            start_date, end_date, mode, database, refresh, reuse_existing)
    if cached is not None:
        return cached
    with download_directory(mode, output_dir, reuse_existing) as target_dir:
        path = target_dir / f"一体化专线拆机清单_{month}.xlsx"
        if not reuse_existing:
            token, account = load_token()
            path = export_order_data(start_date, end_date, month, target_dir, build_headers(token))
        return finish_exports({"integration_removal_order": path}, start_date, end_date, mode, database)



def main():
    args = parser("一体化专线拆机取数及入库").parse_args()
    print(json.dumps(collect(**vars(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
