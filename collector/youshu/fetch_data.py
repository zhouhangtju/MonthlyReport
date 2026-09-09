# -*- coding: utf-8 -*-
r"""有数平台工单取数工具

登录凭证(x-csrf-token / x-roomid / x-sid / cookie 等)保存在外部配置文件
`有数配置.json` 中, 脚本启动时自动读取。凭证过期时, 直接编辑该文件更新即可。

用法:
  python 有数取数.py --list
  python 有数取数.py --task 1 --outdir D:\out
  python 有数取数.py --task all --outdir D:\out
  python 有数取数.py --task 1 --start 2026-07-01 --end 2026-07-31
"""
import argparse
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import datetime, date, timedelta

import requests

# Windows 非法文件名字符（Python 3.11 f-string 正则兼容性修复）
_BAD_CHARS_RE = re.compile(r'[\\/:*?"<>|]')

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "有数配置.json")

DEFAULT_CFG = {
    "base": "http://10.76.134.138:30000",
    "headers": {
        "accept": "application/json",
        "content-type": "application/json",
        "x-csrf-token": "在此填入最新的 x-csrf-token",
        "x-resource-status": "view",
        "x-roomid": "在此填入最新的 x-roomid",
        "x-sid": "在此填入最新的 x-sid",
        "x-time-zone": "8",
        "cookie": "",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0",
    },
    "tasks": [
        {
            "name": "企宽开通交付及时率",
            "url": "http://10.76.134.138:30000/bi/api/dash/report/exportExcel?trigger=User",
            "referrer": "http://10.76.134.138:30000/bi/dash/folder/31?rid=38579",
            "body": {
                "type": "dashboard", "pid": 31, "reportId": 38579,
                "tempQueryId": "export_21270e468fb5002dad33f5fa01e16415",
                "dashboardId": 136622, "exportType": "xlsx",
                "enhance": False, "useOriginData": False, "conditionFormat": False,
                "includeTitle": True, "isAsync": True,
            },
        },
        {
            "name": "企宽投诉处理及时率",
            "url": "http://10.76.134.138:30000/bi/api/dash/report/exportExcel?trigger=User",
            "referrer": "http://10.76.134.138:30000/bi/dash/folder/31?rid=38660",
            "body": {
                "type": "dashboard", "pid": 31, "reportId": 38660,
                "tempQueryId": "export_a22eacb9d4bcfb744f556e8d3b3eec06",
                "dashboardId": 137142, "exportType": "xlsx",
                "enhance": False, "useOriginData": False, "conditionFormat": False,
                "includeTitle": True, "isAsync": True,
            },
        },
        {
            "name": "企宽新装清单",
            "url": "http://10.76.134.138:30000/bi/api/dash/report/exportExcel?trigger=User",
            "referrer": "http://10.76.134.138:30000/bi/dash/folder/31?rid=44677&did=159445",
            "body": {
                "type": "component", "pid": 31, "reportId": 44677,
                "tempQueryId": "@@NEW_TEMP_QUERY_ID@@",
                "dashboardId": 159445, "componentId": "c-tbSfqCuqWdjJ935weUuR6V",
                "exportType": "xlsx", "enhance": False, "useOriginData": True,
                "conditionFormat": False, "includeTitle": False,
                "excelSplitLimit": 1000000, "isAsync": True,
            },
            "setCacheBody": "@@FILE:task3_setcache_44677.json@@",
            "setCacheUrl": "http://10.76.134.138:30000/bi/api/dash/util/setCache?trigger=User",
            "flushReportUrl": "http://10.76.134.138:30000/bi/api/dash/report/flushReport?trigger=User&reportId=44677",
            "dateParameters": {"startField": "373559", "endField": "373560"},
            "regionFilterComponent": "c-qMN3SouTRfjzGvtqZr4juJ",
            "nettypeFilterComponent": "c-j4UCm5J3FUFBbaFfNfRDkb",
            "nettypeValue": "1",
        },
        {
            "name": "新装退单汇总",
            "url": "http://10.76.134.138:30000/bi/api/dash/report/exportExcel?trigger=User",
            "referrer": "http://10.76.134.138:30000/bi/dash/folder/31?rid=44677&did=159450",
            "body": {
                "type": "component", "pid": 31, "reportId": 44677,
                "tempQueryId": "@@NEW_TEMP_QUERY_ID@@",
                "dashboardId": 159450, "componentId": "c-qj9Mxf4qqvRTwa7hLUQdHT",
                "exportType": "xlsx", "enhance": False, "useOriginData": True,
                "conditionFormat": False, "includeTitle": False,
                "excelSplitLimit": 1000000, "isAsync": True,
            },
            "setCacheBody": "@@FILE:task3_summary_setcache_44677.json@@",
            "setCacheUrl": "http://10.76.134.138:30000/bi/api/dash/util/setCache?trigger=User",
            "flushReportUrl": "http://10.76.134.138:30000/bi/api/dash/report/flushReport?trigger=User&reportId=44677",
            "dateParameters": {"startField": "373559", "endField": "373560"},
            "nettypeFilterComponent": "c-2Dm5RkeMrfuW1g3LRnAJ3c",
            "nettypeValue": "1",
        },
        {
            "name": "企宽投诉清单",
            "url": "http://10.76.134.138:30000/bi/api/dash/report/exportExcel?trigger=User",
            "referrer": "http://10.76.134.138:30000/bi/dash/folder/31?rid=38660&did=137143",
            "body": {
                "type": "component", "pid": 31, "reportId": 38660,
                "tempQueryId": "@@NEW_TEMP_QUERY_ID@@",
                "dashboardId": 137143, "componentId": "c-eKLK26aStHXn18JiDQFzPD",
                "exportType": "xlsx", "enhance": False, "useOriginData": True,
                "conditionFormat": False, "includeTitle": False,
                "excelSplitLimit": 1000000, "isAsync": True,
            },
            "setCacheBody": "@@FILE:task4_setcache.json@@",
            "setCacheUrl": "http://10.76.134.138:30000/bi/api/dash/util/setCache?trigger=User",
            "flushReportUrl": "http://10.76.134.138:30000/bi/api/dash/report/flushReport?trigger=User&reportId=38660",
            "dateFilterComponent": "c-ncARTSYLR97sZG2aaksHNR",
        },
        {
            "name": "登录测试/组件数据(企宽投诉清单)",
            "url": "http://10.76.134.138:30000/bi/api/dash/component/flushComponent?trigger=User&id=c-eKLK26aStHXn18JiDQFzPD",
            "referrer": "http://10.76.134.138:30000/bi/dash/folder/31?rid=38660&did=137143",
            "method": "GET",
            "body": None,
        },
    ],
}


def load_config():
    """读取外部配置文件; 不存在则生成模板并提示。支持 @@FILE:xxx@@ 引用独立 JSON 文件。"""
    if not os.path.exists(CFG_FILE):
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CFG, f, ensure_ascii=False, indent=2)
        print(f"[提示] 已生成配置文件模板: {CFG_FILE}")
        print("       请在其中填入最新的 x-csrf-token / x-roomid / x-sid / cookie 后重新运行。")
        sys.exit(1)
    with open(CFG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    _resolve_file_refs(cfg)
    return cfg


def _resolve_file_refs(obj, base_dir=None):
    """递归解析配置中的 "@@FILE:name.json@@" 占位符为对应文件内容。"""
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(CFG_FILE))
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            v = obj[k]
            if isinstance(v, str) and v.startswith("@@FILE:") and v.endswith("@@"):
                name = v[len("@@FILE:"):-2]
                path = os.path.join(base_dir, name)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        obj[k] = json.load(f)
                except Exception as e:
                    print(f"[警告] 无法加载引用文件 {path}: {e}")
            else:
                _resolve_file_refs(v, base_dir)
    elif isinstance(obj, list):
        for item in obj:
            _resolve_file_refs(item, base_dir)


def save_response(name, resp, outdir, start, end, index=None, tag=None):
    os.makedirs(outdir, exist_ok=True)
    ctype = resp.headers.get("content-type", "")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = re.sub(_BAD_CHARS_RE, "_", name)
    if index:
        fname = f"{index:02d}_{fname}"
    if tag:
        fname = f"{fname}_{re.sub(_BAD_CHARS_RE, '_', str(tag))}"
    if start:
        fname = f"{fname}_{start}"
    if end:
        fname = f"{fname}_至{end}"
    if "json" in ctype:
        path = os.path.join(outdir, f"{fname}_{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(resp.json(), f, ensure_ascii=False, indent=2) if _is_json(resp) \
                else f.write(resp.text)
        return path, "json"
    path = os.path.join(outdir, f"{fname}_{ts}.xlsx")
    with open(path, "wb") as f:
        f.write(resp.content)
    return path, "xlsx"


def _is_json(resp):
    try:
        resp.json()
        return True
    except Exception:
        return False


def is_valid_xlsx(content):
    """按文件结构判断是否为完整 xlsx，不用文件大小猜测。"""
    if not content or content[:2] != b"PK":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            return "[Content_Types].xml" in names and "xl/workbook.xml" in names
    except (OSError, zipfile.BadZipFile):
        return False


def inject_date_filter(setcache, component_id, start, end):
    """在 setCache body 中, 把指定 dateTimeFilter 组件的过滤改为静态时间范围。

    结构参考前端真实抓包 (dateTimeFilter 组件保存固定时间时的序列化):
      {"$type":"DateTimeFilter",
       "period":{"minBound":"YYYY-MM-DD 00:00:00","maxBound":"YYYY-MM-DD 24:00:00"},
       "mode":{"$type":"StaticTime"}}
    修改后调用 setCache 即可按受理时间范围导出。
    """
    state = (setcache or {}).get("data", {}).get("state", {})
    comps = state.get("components") or []
    for c in comps:
        if c.get("id") == component_id and c.get("type") == "dateTimeFilter":
            d = c.setdefault("setting", {}).setdefault("data", {}).setdefault("date", {})
            d.clear()
            d["$type"] = "DateTimeFilter"
            d["period"] = {"minBound": start, "maxBound": end}
            d["mode"] = {"$type": "StaticTime"}
            return True
    return False


def inject_list_filter(setcache, component_id, values):
    """在 setCache body 中, 把指定 listFilter 组件的 defaults.selected 设为 values。"""
    state = (setcache or {}).get("data", {}).get("state", {})
    for c in state.get("components") or []:
        if c.get("id") == component_id:
            data = c.setdefault("setting", {}).setdefault("data", {})
            data.setdefault("defaults", {})["selected"] = list(values)
            return True
    return False


def inject_date_parameters(setcache, start_field, end_field, start, end):
    """在 setCache body 中, 把 date 类型 parameters 的 componentValue 设为时间范围。

    部分看板（如企宽新装清单）不用 dateTimeFilter 组件，而是用 date 类型的全局参数，
    起止日期分别对应两个 fieldId, 通过 parameters[].componentValue 传值。
    同时 param 控制器组件(setting.data.parameterId/parameterValue)也要同步,
    因为导出时以 param 组件的 parameterValue 为准。
    """
    state = (setcache or {}).get("data", {}).get("state", {})
    params = state.get("parameters") or []
    hit = False
    for p in params:
        fid = str(p.get("fieldId") or "")
        if fid == str(start_field):
            p["componentValue"] = start
            hit = True
        elif fid == str(end_field):
            p["componentValue"] = end
            hit = True
    # 同步 param 控制器组件
    for c in state.get("components") or []:
        if c.get("type") != "param":
            continue
        d = c.setdefault("setting", {}).setdefault("data", {})
        pid = str(d.get("parameterId") or "")
        if pid == str(start_field):
            d["parameterValue"] = start
            hit = True
        elif pid == str(end_field):
            d["parameterValue"] = end
            hit = True
    return hit


def default_date_range():
    """返回近三个完整自然月: 上上上月1号 ~ 上月最后一天。如 8月9号 -> 5/1 ~ 7/31。"""
    today = datetime.now()
    first_this_month = today.replace(day=1)
    end = first_this_month.replace(month=first_this_month.month - 1) if first_this_month.month > 1 \
        else first_this_month.replace(year=first_this_month.year - 1, month=12)
    # end 现在是上月1号, 减一天得上月最后一天
    import calendar
    last_day = calendar.monthrange(end.year, end.month)[1]
    end = end.replace(day=last_day)
    start = end.replace(day=1)
    # start 再往前两个月
    m = start.month - 2
    y = start.year
    if m < 1:
        m += 12
        y -= 1
    start = datetime(y, m, 1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def request_dynamic(task, headers, timeout, start=None, end=None,
                    poll_timeout=600, poll_interval=10, region=None, nettype=None,
                    defer_download=False, clear_region=False):
    """动态导出流程: flushReport -> setCache -> exportExcel -> 轮询 GET 下载。

    若任务配置了 flushReportUrl，先刷新报表；随后 POST setCache 获取新的
    tempQueryId，替换导出 body 中的 @@NEW_TEMP_QUERY_ID@@ 占位后发送；最后轮询
    下载接口等待 xlsx 结果。返回 (resp, info)。
    """
    url = task["url"]
    setcache = task.get("setCacheBody")
    export_body = task.get("body") or {}

    # 未显式指定日期范围时, 若任务配置了默认日期范围则按默认计算
    if not (start and end) and (task.get("dateFilterComponent") or task.get("dateParameters")):
        dr = task.get("defaultDateRange")
        if dr:
            start, end = default_date_range()
            print(f"    [动态] 未指定日期, 按默认范围 {dr}: {start} ~ {end}")

    if setcache:
        sc_url = task.get("setCacheUrl") or (url.split("report/")[0] + "util/setCache?trigger=User")
        flush_url = task.get("flushReportUrl")
        if flush_url:
            print("    [动态] GET flushReport 刷新报表 ...")
            rf = requests.get(flush_url, headers=headers, timeout=timeout)
            flush_error = rf.status_code < 200 or rf.status_code >= 300
            try:
                jf = rf.json()
                if jf.get("code") not in (None, 0, 200):
                    flush_error = True
            except Exception:
                jf = {}
            if flush_error:
                return rf, {"stage": "flushReport", "detail": rf.text[:300]}
        body = setcache
        if (start and end and (task.get("dateFilterComponent") or task.get("dateParameters"))) \
                or region or clear_region or nettype:
            body = json.loads(json.dumps(setcache))
            dfc = task.get("dateFilterComponent")
            if start and end and dfc and inject_date_filter(body, dfc,
                                                            f"{start} 00:00:00", f"{end} 24:00:00"):
                print(f"    [动态] dateTimeFilter 已设为 {start} ~ {end}")
            dp = task.get("dateParameters")
            if start and end and dp and inject_date_parameters(body, dp.get("startField"),
                                                               dp.get("endField"), start, end):
                print(f"    [动态] date 参数已设为 {start} ~ {end}")
            rfc = task.get("regionFilterComponent")
            if clear_region and rfc and inject_list_filter(body, rfc, []):
                print("    [动态] 地市筛选已清空，导出全省")
            elif region and rfc and inject_list_filter(body, rfc, [region]):
                print(f"    [动态] 地市筛选已设为 {region}")
            nfc = task.get("nettypeFilterComponent")
            if nettype and nfc and inject_list_filter(body, nfc, [nettype]):
                print(f"    [动态] 宽带类型筛选已设为 {nettype}")
        print("    [动态] POST setCache 获取新 tempQueryId ...")
        r0 = requests.post(
            sc_url,
            headers=headers,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            timeout=timeout,
        )
        try:
            j0 = r0.json()
        except Exception:
            j0 = {}
        temp_id = j0.get("result")
        if not temp_id:
            return r0, {"stage": "setCache", "detail": r0.text[:300]}
        print(f"    [动态] tempQueryId = {temp_id}")
        export_body = dict(export_body)
        if export_body.get("tempQueryId") == "@@NEW_TEMP_QUERY_ID@@" or not export_body.get("tempQueryId"):
            export_body["tempQueryId"] = temp_id
    else:
        temp_id = export_body.get("tempQueryId")

    print("    POST exportExcel ...")
    r1 = requests.post(
        url,
        headers=headers,
        data=json.dumps(export_body, ensure_ascii=False).encode("utf-8"),
        timeout=timeout,
    )
    try:
        j1 = r1.json()
    except Exception:
        j1 = {}
    export_id = j1.get("result") if isinstance(j1, dict) else None
    print(f"    [导出响应] code={j1.get('code') if isinstance(j1, dict) else None} keys={list(j1.keys()) if isinstance(j1, dict) else None}")
    print(f"    [导出响应] {json.dumps(j1, ensure_ascii=False)[:400] if isinstance(j1, dict) else str(j1)[:400]}")
    if not export_id:
        return r1, {"stage": "exportExcel", "detail": r1.text[:300]}
    print(f"    exportId = {export_id}")

    # 下载文件: GET exportExcelTask/download?id=<taskId>
    # (前端源码确认: 导出后通过此接口直接下载 xlsx, 见
    #  index.*.js downloadFile(getPatchedDashPath(`/api/dash/exportExcelTask/download?id=${id}`));
    #  实测该接口对已完成的导出立即返回 application/octet-stream 的 xlsx 二进制)
    base = task.get("downloadBase") or re.sub(r"/report/.*", "", url)
    dl_url = f"{base}/exportExcelTask/download?id={export_id}"
    if defer_download:
        return r1, {
            "stage": "queued",
            "exportId": export_id,
            "tempQueryId": temp_id,
            "downloadUrl": dl_url,
        }
    elapsed = 0
    consecutive_500 = 0
    last_small = None
    while elapsed < poll_timeout:
        # 导出接口返回 exportId 只代表任务已创建，并不代表文件已经生成。
        # 第一轮也必须真实等待，避免刚创建任务就请求下载而触发 code=500。
        time.sleep(poll_interval)
        elapsed += poll_interval
        try:
            rp = requests.get(dl_url, headers=headers, timeout=timeout)
        except Exception as e:
            print(f"    [下载] {elapsed}s 请求失败: {e}")
            continue
        ct = rp.headers.get("content-type", "")
        body = rp.content
        # 用ZIP内部结构识别完整xlsx。短批次/零数据文件可能只有几KB，
        # 不能再仅凭文件大小将其误判为“仍在生成”。
        if rp.status_code == 200 and is_valid_xlsx(body):
            return rp, {"stage": "file", "exportId": export_id, "tempQueryId": temp_id}
        if "http" in rp.text and ("store" in rp.text or "X-Amz" in rp.text):
            return rp, {"stage": "url", "exportId": export_id, "tempQueryId": temp_id}
        try:
            info = rp.json()
            code = info.get("code")
        except Exception:
            code = None
            info = None
        if code == 500:
            consecutive_500 += 1
        else:
            consecutive_500 = 0
        print(f"    [下载] {elapsed}s HTTP {rp.status_code} ct={ct} bytes={len(body)} "
              f"prefix={body[:2]!r} code={code} "
              f"{json.dumps(info, ensure_ascii=False)[:120] if isinstance(info, dict) else rp.text[:120]}")
        if code == 500 and consecutive_500 == 1:
            print("    [提示] 导出任务可能仍在生成，将继续轮询；若持续500，"
                  "请重新运行 node youdata_autologin.js 刷新同一会话的cookie/roomid/sid")
        # 任务尚在生成或参数有误: 尝试查询任务列表获取状态/link
        if code not in (200, None):
            try:
                lr = requests.post(
                    f"{base}/exportExcelTask/list",
                    headers=headers,
                    data=json.dumps({"projectId": 31, "type": "excel"}).encode("utf-8"),
                    timeout=timeout,
                )
                lj = lr.json()
                items = lj.get("result") or lj.get("data") or []
                if isinstance(items, list) and items:
                    it = items[0]
                    status = it.get("status")
                    link = it.get("link")
                    print(f"    [任务] status={status} link={'有' if link else '无'} "
                          f"({json.dumps(it, ensure_ascii=False)[:160]})")
                    if link:
                        return r1, {"stage": "url_in_list", "exportId": export_id,
                                    "tempQueryId": temp_id, "url": link}
                    if status in ("fail", "failed", 3, 4):
                        print("    ! 任务失败")
                        break
            except Exception as e:
                print(f"    [任务列表] 失败: {e}")
    if last_small is not None:
        # 全程只有小文件(占位/空表), 把最后一次结果交给上层决定
        print("    [下载] 轮询超时仍为小文件, 返回最后一次结果")
        return last_small, {"stage": "file", "exportId": export_id, "tempQueryId": temp_id}
    return r1, {"stage": "timeout", "exportId": export_id, "tempQueryId": temp_id}


def month_ranges(start, end):
    """把 [start, end] 拆成自然月段, 返回 [(月首, 月末), ...]。"""
    import calendar
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    out = []
    y, m = s.year, s.month
    while True:
        seg_start = date(y, m, 1) if (y, m) != (s.year, s.month) else s
        seg_end = min(date(y, m, calendar.monthrange(y, m)[1]), e)
        out.append((seg_start.strftime("%Y-%m-%d"), seg_end.strftime("%Y-%m-%d")))
        if seg_end >= e:
            break
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def day_chunk_ranges(start, end, chunk_days):
    """把闭区间 [start, end] 按固定天数切片。"""
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    if s > e:
        raise ValueError("--start 不能晚于 --end")
    if chunk_days < 1:
        raise ValueError("--chunk-days 必须大于等于 1")
    out = []
    cursor = s
    while cursor <= e:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), e)
        out.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return out


def merge_xlsx(paths, outpath):
    """用 pandas 合并多个同结构 xlsx 为一个; 失败返回 False。"""
    try:
        import pandas as pd
    except Exception as e:
        print(f"  ! 无法合并(缺 pandas): {e}")
        return False
    frames = []
    for p in paths:
        try:
            frames.append(pd.read_excel(p))
        except Exception as ex:
            print(f"  ! 读取 {p} 失败: {ex}")
    if not frames:
        return False
    pd.concat(frames, ignore_index=True).to_excel(outpath, index=False)
    return True


def run_export(task, headers, base_headers, outdir, start, end, timeout, index=None,
               poll_timeout=600, region=None, nettype=None, tag=None,
               clear_region=False):
    """执行一次动态导出并保存, 返回 (path, kind); 失败返回 (None, None)。"""
    try:
        resp, info = request_dynamic(task, headers, timeout, start=start, end=end,
                                     poll_timeout=poll_timeout, region=region, nettype=nettype,
                                     clear_region=clear_region)
    except Exception as e:
        print(f"  ! 请求失败: {e}")
        return None, None
    print(f"  HTTP {resp.status_code}, content-type: {resp.headers.get('content-type')}")
    if resp.status_code != 200:
        try:
            j = resp.json()
            code = j.get("code")
            print(f"  ! 返回异常: code={code}, message={j.get('message')}")
            if code == 610:
                print("  ! 提示: 认证未通过。请确认配置文件中的 cookie / x-csrf-token / x-sid 是否为最新: ")
                print("        浏览器登录有数平台 -> F12 -> Network -> 触发导出 -> 选任意一个 "
                      "exportExcel/asyncExportExcel 请求 -> Headers -> Request Headers,")
                print("        复制整个 Cookie 填入 有数配置.json 的 headers.cookie,")
                print("        并同时更新 x-csrf-token / x-roomid / x-sid 三个字段。")
        except Exception:
            print(f"  ! 返回异常: {resp.text[:500]}")
        return None, None
    if info and info.get("stage") == "timeout":
        print("  ! 轮询超时未取到文件/URL (exportId 有效, 可稍后手动下载)")
        return None, None
    if info and info.get("stage") == "url_in_list":
        dl = info.get("url")
        print("  [任务列表] 取到下载链接, 直接下载 ...")
        try:
            rd = requests.get(dl, headers=dict(base_headers), timeout=timeout)
        except Exception as e:
            print(f"  ! 下载链接请求失败: {e}")
            return None, None
        resp = rd
    path, kind = save_response(task["name"], resp, outdir, start, end, index, tag)
    print(f"  OK 已保存: {path}  ({kind})")
    return path, kind


def queue_export(task, headers, timeout, start, end, poll_timeout=600,
                 region=None, nettype=None, tag=None, clear_region=False):
    """只创建导出任务，不立即下载；返回待下载任务描述。"""
    try:
        resp, info = request_dynamic(
            task, headers, timeout, start=start, end=end,
            poll_timeout=poll_timeout, region=region, nettype=nettype,
            defer_download=True, clear_region=clear_region,
        )
    except Exception as exc:
        print(f"  ! 提交失败: {exc}")
        return None
    if not info or info.get("stage") != "queued":
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:300]
        print(f"  ! 未生成 exportId: {detail}")
        return None
    job = {
        "task": task,
        "exportId": info["exportId"],
        "tempQueryId": info.get("tempQueryId"),
        "downloadUrl": info["downloadUrl"],
        "start": start,
        "end": end,
        "tag": tag,
    }
    print(f"  [已排队] exportId={job['exportId']}")
    return job


def download_queued_export(job, headers, outdir, timeout, poll_timeout,
                           poll_interval=10):
    """轮询并下载第一阶段已创建的单个导出任务。"""
    task = job["task"]
    elapsed = 0
    consecutive_500 = 0
    while elapsed < poll_timeout:
        try:
            resp = requests.get(job["downloadUrl"], headers=headers, timeout=timeout)
        except Exception as exc:
            print(f"    [下载] {elapsed}s 请求失败: {exc}")
            time.sleep(poll_interval)
            elapsed += poll_interval
            continue
        ctype = resp.headers.get("content-type", "")
        body = resp.content
        if resp.status_code == 200 and is_valid_xlsx(body):
            path, kind = save_response(
                task["name"], resp, outdir, job["start"], job["end"],
                tag=job.get("tag"),
            )
            print(f"    OK 已保存: {path} ({kind}, {len(body)} bytes)")
            return path, kind
        try:
            info = resp.json()
            code = info.get("code")
        except Exception:
            info = None
            code = None
        consecutive_500 = consecutive_500 + 1 if code == 500 else 0
        print(f"    [下载] {elapsed}s HTTP {resp.status_code} ct={ctype} "
              f"bytes={len(body)} prefix={body[:2]!r} code={code} "
              f"{json.dumps(info, ensure_ascii=False)[:100] if isinstance(info, dict) else ''}")
        if code == 610:
            print("    ! 登录会话已失效，请重新刷新凭证")
            return None, None
        if code == 500 and consecutive_500 == 1:
            print("    [提示] 文件可能仍在生成，继续轮询")
        time.sleep(poll_interval)
        elapsed += poll_interval
    print(f"    ! exportId={job['exportId']} 下载轮询超时")
    return None, None


def download_job_list(jobs, headers, outdir, timeout, poll_timeout):
    """第二阶段按提交顺序统一下载任务。"""
    paths = []
    print(f"\n{'=' * 68}\n[第二阶段] 开始统一下载，共 {len(jobs)} 个 exportId\n{'=' * 68}")
    for index, job in enumerate(jobs, 1):
        print(f"\n[下载 {index}/{len(jobs)}] exportId={job['exportId']} "
              f"{job['start']} ~ {job['end']} {job.get('tag') or ''}")
        path, kind = download_queued_export(
            job, headers, outdir, timeout, poll_timeout,
        )
        if path and kind == "xlsx":
            paths.append(path)
    return paths


def main():
    ap = argparse.ArgumentParser(description="有数平台工单取数工具")
    ap.add_argument("--list", action="store_true", help="列出所有任务")
    ap.add_argument("--task", help="任务名或序号，或 all 全部")
    ap.add_argument("--start", help="起始日期, 可选, 如 2026-07-01 (逻辑后续补充)")
    ap.add_argument("--end", help="结束日期, 可选, 如 2026-07-31 (逻辑后续补充)")
    ap.add_argument("--region", help="地市x月份模式下只导出指定地市, 如 杭州")
    ap.add_argument("--no-split-region", action="store_true",
                    help="企宽新装清单不按地市拆分，每个日期批次导出全省数据")
    ap.add_argument("--province-by-region", action="store_true",
                    help="全省按11地市拆分：日期使用完整范围不切批，"
                         "先生成所有exportId，再统一下载")
    ap.add_argument("--getcache", metavar="TEMPQUERYID",
                    help="从服务端拉取指定 tempQueryId 的真实 store 并保存为模板文件(用于修复抓包脱敏)")
    ap.add_argument("--outdir", default=".", help="输出目录, 默认当前目录")
    ap.add_argument("--timeout", type=int, default=120, help="请求超时秒数")
    ap.add_argument("--poll-timeout", type=int, default=600,
                    help="导出结果轮询总超时秒数, 大数据量可调大(默认600)")
    ap.add_argument("--interval", type=float, default=0.5,
                    help="批次/任务之间的暂停秒数，默认0.5")
    ap.add_argument("--chunk-days", type=int, default=0,
                    help="按固定天数分批导出；0 表示沿用任务默认策略，建议大区间设为3或7")
    ap.add_argument("--two-phase", action="store_true",
                    help="两阶段执行：先生成全部exportId，再统一轮询下载")
    args = ap.parse_args()

    cfg = load_config()
    tasks = cfg.get("tasks", [])
    base_headers = dict(cfg.get("headers", {}))

    if args.list:
        print("序号\t任务名\t\t接口类型")
        for i, t in enumerate(tasks, 1):
            url = t.get("url", "")
            kind = "异步" if "async" in url else ("GET" if t.get("method") == "GET" else "同步")
            print(f"{i}\t{t['name']}\t{kind}")
        return

    if args.getcache:
        # 用用户手动导出成功时的 tempQueryId 从服务端取回真实(未脱敏) store, 存为模板
        base = cfg.get("base", "http://10.76.134.138:30000")
        headers = dict(base_headers)
        url = f"{base}/bi/api/dash/util/getCache?id={args.getcache}"
        print(f"  GET {url}")
        r = requests.get(url, headers=headers, timeout=args.timeout)
        print(f"  HTTP {r.status_code}, content-type: {r.headers.get('content-type')}")
        try:
            j = r.json()
        except Exception:
            print("  非 JSON 响应:", r.text[:500])
            return
        result = j.get("result") if isinstance(j, dict) else None
        if not result:
            print("  响应无 result:", json.dumps(j, ensure_ascii=False)[:800])
            return
        print(f"  result keys: {list(result.keys()) if isinstance(result, dict) else type(result).__name__}")
        # getCache 返回 {state:{...看板状态...}, temporary:{...}}。导出 setCache 需要的
        # state 就是 result.state, temporary 就是 result.temporary
        rstate = result.get("state", result) if isinstance(result, dict) else result
        rtemporary = result.get("temporary", {}) if isinstance(result, dict) else {}
        # 存原始 result 以及包装成 setCache body 的格式
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw = os.path.join(args.outdir, f"getcache_{ts}.json")
        with open(raw, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        print(f"  已保存真实 store: {raw}")
        body = {"data": {"state": rstate, "temporary": rtemporary}, "keyword": "export"}
        wrapped = os.path.join(args.outdir, f"getcache_body_{ts}.json")
        with open(wrapped, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
        print(f"  已保存 setCache body 模板: {wrapped}")
        print("  提示: 把该文件拷回脚本目录并更新任务配置的 setCacheBody 为 @@FILE:文件名@@")
        return

    if not args.task:
        ap.print_help()
        return

    def pick(t):
        if t.isdigit():
            return [tasks[int(t) - 1]]
        exact = [x for x in tasks if t == x["name"]]
        if exact:
            return exact
        return [x for x in tasks if t in x["name"]]

    if args.task == "all":
        selected = list(tasks)
    else:
        selected = pick(args.task)
        if not selected:
            print(f"未找到任务: {args.task}")
            sys.exit(1)

    for i, task in enumerate(selected, 1):
        print(f"\n[{i}/{len(selected)}] 正在请求: {task['name']} ...")
        headers = dict(base_headers)
        headers["referer"] = task.get("referrer", "")
        method = task.get("method", "POST")
        is_export = "exportexcel" in task.get("url", "").lower()
        idx = i if args.task == "all" else None
        try:
            if method == "GET":
                resp = requests.get(task["url"], headers=headers, timeout=args.timeout)
                print(f"  HTTP {resp.status_code}, content-type: {resp.headers.get('content-type')}")
                path, kind = save_response(task["name"], resp, args.outdir,
                                           args.start, args.end, idx)
                print(f"  OK 已保存: {path}  ({kind})")
            elif is_export and task.get("splitRegion"):
                # 按 地市 x 月份 循环导出, 每个组合一个文件, 不合并(避免单文件过大)
                if args.province_by_region:
                    regions = task.get("regions") or []
                elif args.no_split_region:
                    regions = [None]
                else:
                    regions = [args.region] if args.region else (task.get("regions") or [])
                nettype = task.get("nettypeValue")
                s, e = args.start, args.end
                if not (s and e) and (task.get("dateFilterComponent") or task.get("dateParameters")):
                    s, e = default_date_range()
                if args.province_by_region:
                    ranges = [(s, e)] if (s and e) else [(None, None)]
                    mode = "完整日期范围不切批"
                else:
                    ranges = (day_chunk_ranges(s, e, args.chunk_days)
                              if (s and e and args.chunk_days)
                              else (month_ranges(s, e) if (s and e) else [(None, None)]))
                    mode = f"每批{args.chunk_days}天" if args.chunk_days else "按自然月"
                region_mode = (f"全省按地市拆分 {len(regions)} 个（自动 two-phase）"
                               if args.province_by_region else
                               ("全省不拆地市" if args.no_split_region
                                else f"地市 {len(regions)} 个"))
                print(f"  [日期批次] 范围 {s} ~ {e}, {mode}, "
                      f"{region_mode} x 批次 {len(ranges)} 个")
                jobs = []
                for ms, me in ranges:
                    for rg in regions:
                        mtag = f"{ms[:7]}" if ms else ""
                        scope_tag = rg if rg else "全省"
                        batch_tag = (f"{scope_tag}_{mtag}_{ms.replace('-', '')}-{me.replace('-', '')}"
                                     if ms else scope_tag)
                        print(f"\n  [导出] {scope_tag} {ms} ~ {me} ...")
                        if args.two_phase or args.province_by_region:
                            job = queue_export(
                                task, headers, args.timeout, ms, me,
                                poll_timeout=args.poll_timeout,
                                region=rg, nettype=nettype, tag=batch_tag,
                                clear_region=args.no_split_region,
                            )
                            if job:
                                jobs.append(job)
                        else:
                            p, k = run_export(
                                task, headers, base_headers, args.outdir,
                                ms, me, args.timeout, None,
                                poll_timeout=args.poll_timeout,
                                region=rg, nettype=nettype, tag=batch_tag,
                                clear_region=args.no_split_region,
                            )
                        if me:
                            time.sleep(args.interval)
                if args.two_phase or args.province_by_region:
                    print(f"\n[第一阶段完成] 成功生成 {len(jobs)} 个 exportId")
                    download_job_list(
                        jobs, headers, args.outdir, args.timeout,
                        args.poll_timeout,
                    )
            elif is_export and task.get("splitMonthly"):
                # 平台多月导出 bug, 按月拆分逐月导出后自动合并
                s, e = args.start, args.end
                if not (s and e) and (task.get("dateFilterComponent") or task.get("dateParameters")):
                    s, e = default_date_range()
                ranges = (day_chunk_ranges(s, e, args.chunk_days)
                          if (s and e and args.chunk_days)
                          else (month_ranges(s, e) if (s and e) else None))
                mode = f"每批{args.chunk_days}天" if args.chunk_days else "按自然月"
                print(f"  [分批] 目标范围: {s} ~ {e}, {mode}逐次导出")
                if not ranges:
                    path, kind = run_export(task, headers, base_headers, args.outdir,
                                            args.start, args.end, args.timeout, idx,
                                            poll_timeout=args.poll_timeout)
                else:
                    paths = []
                    for ms, me in ranges:
                        print(f"\n  [分批] 导出 {ms} ~ {me} ...")
                        p, k = run_export(task, headers, base_headers, args.outdir,
                                          ms, me, args.timeout, None,
                                          poll_timeout=args.poll_timeout)
                        if p:
                            paths.append(p)
                        time.sleep(args.interval)
                    if len(paths) > 1:
                        os.makedirs(args.outdir, exist_ok=True)
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        fname = re.sub(r'[\\/:*?"<>|]', "_", task["name"])
                        merged = os.path.join(args.outdir, f"{fname}_{s}_至{e}_{ts}.xlsx")
                        if merge_xlsx(paths, merged):
                            print(f"  OK 合并为: {merged}")
                            for p in paths:
                                try:
                                    os.remove(p)
                                except Exception:
                                    pass
                        else:
                            print("  ! 合并失败, 保留各月文件")
            elif is_export and args.chunk_days and args.start and args.end:
                # 普通任务（如企宽投诉清单）按固定天数串行导出，
                # 避免大跨度请求导致服务端生成任务失败。
                ranges = day_chunk_ranges(args.start, args.end, args.chunk_days)
                print(f"  [分批] 每批 {args.chunk_days} 天，共 {len(ranges)} 批")
                paths = []
                jobs = []
                for batch_index, (bs, be) in enumerate(ranges, 1):
                    print(f"\n  [批次 {batch_index}/{len(ranges)}] {bs} ~ {be}")
                    tag = f"batch{batch_index:03d}"
                    if args.two_phase:
                        job = queue_export(
                            task, headers, args.timeout, bs, be,
                            poll_timeout=args.poll_timeout, tag=tag,
                        )
                        if job:
                            jobs.append(job)
                    else:
                        p, k = run_export(
                            task, headers, base_headers, args.outdir,
                            bs, be, args.timeout, None,
                            poll_timeout=args.poll_timeout, tag=tag,
                        )
                        if p and k == "xlsx":
                            paths.append(p)
                    if batch_index < len(ranges) and args.interval:
                        time.sleep(args.interval)
                if args.two_phase:
                    print(f"\n[第一阶段完成] 成功生成 {len(jobs)} 个 exportId")
                    paths = download_job_list(
                        jobs, headers, args.outdir, args.timeout,
                        args.poll_timeout,
                    )
                if len(paths) > 1:
                    os.makedirs(args.outdir, exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    fname = re.sub(_BAD_CHARS_RE, "_", task["name"])
                    merged = os.path.join(
                        args.outdir,
                        f"{fname}_{args.start}_至{args.end}_合并_{ts}.xlsx",
                    )
                    if merge_xlsx(paths, merged):
                        print(f"  OK 分批文件已合并: {merged}")
                    else:
                        print("  ! 自动合并失败，已保留所有分批 Excel")
                elif len(paths) == 1:
                    print(f"  OK 共生成 1 个分批文件: {paths[0]}")
                else:
                    print("  ! 所有批次均未生成有效 Excel")
            elif is_export:
                path, kind = run_export(task, headers, base_headers, args.outdir,
                                        args.start, args.end, args.timeout, idx,
                                        poll_timeout=args.poll_timeout)
            else:
                resp = requests.post(
                    task["url"],
                    headers=headers,
                    data=json.dumps(task["body"], ensure_ascii=False).encode("utf-8"),
                    timeout=args.timeout,
                )
                print(f"  HTTP {resp.status_code}, content-type: {resp.headers.get('content-type')}")
                path, kind = save_response(task["name"], resp, args.outdir,
                                           args.start, args.end, idx)
                print(f"  OK 已保存: {path}  ({kind})")
        except Exception as e:
            print(f"  ! 请求失败: {e}")
        if i < len(selected):
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
