# -*- coding: utf-8 -*-
"""
政企一体化平台 (govEnt) 自动登录并导出终端出库、入库数据及全省物资基准库

模仿 EOMS(eoms_autorelogin.py) 的 4A 密码方式登录 (loginMode=pwd)，
但 target = http://188.105.165.237:18083/plat/auth/loginZj4A

流程:
  1. GET 4A iframeLoginZJ.do -> 取 RSA 公钥 + JSESSIONID
  2. RSA 无填充加密账号/密码, POST iframeLoginZJ!login.do (loginMode=pwd, 无需短信/图形验证码)
  3. 302 到 http://188.105.165.237:18083/plat/auth/loginZj4A?pname=...
  4. 该页 XHR GET /plat/auth/loginZj4APname?pname=...  -> 设置 zy_token cookie
  5. 从 cookie 提取 zy_token，并写入 credentials/zhengqi_yitihua.json

用法:
  python zhengqi_login.py               # 交互终端登录
  python zhengqi_login.py --print       # 只打印 token 不写文件
  python zhengqi_login.py --account .. --password ..
  python zhengqi_login.py --check       # 登录后用真实业务接口校验
  python integration_dismantle.py --date 2026-07

正常运行时，登录成功后会依次导出指定月份的终端出库、终端入库数据，
并下载全省物资基准库。
不传 --date 时默认导出当前月份；--print 保持原逻辑，只打印 token，不导出文件。
"""
import requests, re, json, os, sys, time, argparse, base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import csv
import itertools
import tempfile
from contextlib import contextmanager
from collections import Counter
from datetime import date

from config.datasets import get_dataset
from storage.importer import file_sha256, import_file, iter_rows, row_payload
from storage.terminal_recovery import has_source_coverage, save_source
from datetime import datetime, timedelta
from io import BytesIO

from openpyxl import load_workbook
import urllib3
urllib3.disable_warnings()
sys.stdout.reconfigure(encoding="utf-8")

CAS = "http://10.76.149.228:9082"
APPCODE = "casR146464"
RESOURCE_ID = "146464"
TARGET = "http://188.105.165.237:18083/plat/auth/loginZj4A"
BASE = "http://188.105.165.237:18083"
EXPORT_DIR = r"D:\edge_download"

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRED = os.path.join(WS, "credentials", "zhengqi_yitihua.json")

DEFAULT_ACCOUNT = "13738074615"
DEFAULT_PASSWORD = "Zsins@126"

# 数据源单次最多返回 20000 条。
EXPORT_PAGE_SIZE = 20000
EXPORT_TIMEOUT = 120
EXPORT_MAX_RETRIES = 3


def rsa_with_no_padding(m, e, input_str):
    """RSA 无填充加密 (与前端 rsa.js 一致), 返回 hex 字符串。"""
    data = input_str.encode('utf-8')
    int_data = int.from_bytes(data, byteorder='big', signed=False)
    encrypted_int = pow(int_data, e, m)
    byte_len = (encrypted_int.bit_length() + 7) // 8
    return encrypted_int.to_bytes(byte_len, byteorder='big').hex()


def get_rsa_key(session):
    r = session.get(
        f"{CAS}/portalS/platform/iframeLoginZJ.do?appCode={APPCODE}&target={TARGET}",
        timeout=20,
    )
    m = re.search(r'getKeyPair\("10001", "", "([0-9a-fA-F]+)"\)', r.text)
    if not m:
        raise RuntimeError("4A 登录页未找到 getKeyPair")
    m_int = int(m.group(1), 16)
    e_int = int("10001", 16)
    return m_int, e_int


def login(session, account, password):
    session.headers.update({
        "Referer": f"{CAS}/portalS/platform/iframeLoginZJ.do?appCode={APPCODE}&target={TARGET}",
    })
    m, e = get_rsa_key(session)
    form = {
        "username": rsa_with_no_padding(m, e, account),
        "password": rsa_with_no_padding(m, e, password),
        "userName": account,
        "passWord": password,
        "loginMode": "pwd",
        "code": "111111",
        "challengeCode": "111111",
        "appCode": APPCODE,
        "resourceId": RESOURCE_ID,
        "isGroupUser": "",
        "target": TARGET,
        "verifyRealCode": "false",
    }
    # login.do 302 -> /plat/auth/loginZj4A?pname=..&sso_ticket=..&IP=..
    r = session.post(
        f"{CAS}/portalS/platform/iframeLoginZJ!login.do",
        data=form, timeout=30,
    )
    # 登录成功后会 302 -> /plat/auth/loginZj4A?pname=.. 再 302 -> views/iframeLoginZJ4A.html?pname=..
    # 最终 URL (绝对或相对) 必含 pname= 票据
    final = r.url
    if "pname=" not in final:
        raise RuntimeError(f"登录后未拿到 pname 票据, 最终URL: {final}")

    # 取 pname 参数 (iframeLoginZJ4A.html 用 url.split('?')[1] 再拼到 /plat/auth/loginZj4APname)
    if "?" in final:
        params = final.split("?", 1)[1]
    else:
        params = final
    # 抽出 pname= (base64 可能含 =/+/), 只取第一个参数名
    pname_m = re.search(r'(pname=[^&]+)', final)
    pname_param = pname_m.group(1) if pname_m else params

    # 构造 XHR 用的 query: 原页面用整个 ?后 作为 query，但二次请求只需 pname
    session.headers["Referer"] = final
    r2 = session.get(
        f"{BASE}/plat/auth/loginZj4APname?{pname_param}",
        timeout=30,
    )
    print(f"[loginZj4APname] HTTP {r2.status_code}")
    if not r2.ok:
        raise RuntimeError(f"loginZj4APname 失败 HTTP {r2.status_code}")
    try:
        j = r2.json()
        token = (j.get("data") or {}).get("token")
        if token:
            # 成功：token 在返回 JSON 的 data.token，同时会作为 zy_token cookie
            session._govent_token = token
            return session
    except Exception:
        pass
    # 失败：退回从 cookie 取
    zy = session.cookies.get_dict().get("zy_token")
    if zy:
        session._govent_token = zy
        return session
    raise RuntimeError(f"loginZj4APname 响应中未找到 token，body: {r2.text[:200]}")


def extract_token(session):
    token = getattr(session, "_govent_token", None)
    if token:
        return token
    cookies = session.cookies.get_dict()
    zy = cookies.get("zy_token") or cookies.get("zytoken")
    if not zy:
        raise RuntimeError(f"cookie 中未找到 zy_token，当前cookie: {list(cookies.keys())}")
    return zy


def check_token(token):
    """用真实业务接口校验 token"""
    h = {
        "zytoken": token,
        "zy_token": token,
        "Content-Type": "application/json",
    }
    try:
        r = requests.get(
            f"{BASE}/api/res/resmng/deline/generalBusinessList?busType=3&busLevel=%E6%9C%AC%E5%9C%B0&accessPointProvinceA=330000&accessPointPrefectureA=330800&pageNum=1&pageSize=1",
            headers=h, timeout=20, verify=False,
        )
        print(f"[check] HTTP {r.status_code}: {r.text[:120]}")
        return r.status_code == 200
    except Exception as ex:
        print(f"[check] ERR {ex}")
        return False


def normalize_month(month_str=None):
    """解析 YYYY-MM，并返回月份、月初日期和次月 6 日。"""
    if not month_str:
        month_str = datetime.now().strftime("%Y-%m")
    try:
        month_date = datetime.strptime(month_str, "%Y-%m")
    except (TypeError, ValueError):
        raise ValueError(f"月份格式错误: {month_str}，正确格式为 YYYY-MM")

    export_month = month_date.strftime("%Y-%m")
    start_date = f"{export_month}-01"

    # 数据源存在约 6 天延迟：例如导出 2026-07 时，实际查询区间为
    # 2026-07-01 00:00:00 至 2026-08-03 23:59:59。
    if month_date.month == 12:
        next_month_year = month_date.year + 1
        next_month = 1
    else:
        next_month_year = month_date.year
        next_month = month_date.month + 1
    end_date = f"{next_month_year:04d}-{next_month:02d}-03"
    return export_month, start_date, end_date


def export_headers(token):
    """构造终端出入库导出接口需要的请求头。"""
    return {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "cache-control": "max-age=0",
        "content-type": "application/json",
        "origin": BASE,
        "zy_token": token,
        "zytoken": token,
        "referer": f"{BASE}/dc-form/show/statisticalTable",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    }


def _find_header_row(sheet):
    """识别导出文件的表头行，兼容“标题行 + 表头行”的格式。"""
    candidates = []
    for row_no in range(1, min(sheet.max_row, 10) + 1):
        non_empty = sum(
            cell.value is not None and str(cell.value).strip() != ""
            for cell in sheet[row_no]
        )
        candidates.append((non_empty, -row_no, row_no))
    return max(candidates)[2] if candidates else 1


def _request_export_range(session, token, url, body, start_time, end_time):
    """请求一个时间段，失败时最多重试 3 次。"""
    request_body = dict(body)
    request_body["pageNum"] = 1
    request_body["pageSize"] = EXPORT_PAGE_SIZE
    request_body["confirmTimeStart"] = start_time.strftime("%Y-%m-%d %H:%M:%S")
    request_body["confirmTimeEnd"] = end_time.strftime("%Y-%m-%d %H:%M:%S")

    last_error = None
    for attempt in range(1, EXPORT_MAX_RETRIES + 1):
        try:
            r = session.post(
                url,
                json=request_body,
                headers=export_headers(token),
                timeout=EXPORT_TIMEOUT,
            )
            if r.status_code != 200:
                last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            elif "json" in r.headers.get("content-type", "").lower():
                last_error = f"返回 JSON 而非 Excel: {r.text[:300]}"
            else:
                return r.content
        except requests.RequestException as ex:
            last_error = str(ex)

        print(
            f"[WARN] {start_time} 至 {end_time} 第 {attempt} 次请求失败: "
            f"{last_error}"
        )
        if attempt < EXPORT_MAX_RETRIES:
            time.sleep(3)

    raise RuntimeError(last_error)


def post_export(session, token, url, body, output_path):
    """按时间分段导出，并把所有时间段的数据合并为一个 Excel。"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    full_start = datetime.strptime(body["confirmTimeStart"], "%Y-%m-%d %H:%M:%S")
    full_end = datetime.strptime(body["confirmTimeEnd"], "%Y-%m-%d %H:%M:%S")

    total_rows = 0
    request_count = 0
    result_workbook = None
    result_sheet = None

    def fetch_range(start_time, end_time):
        """拉取一个区间；达到 20000 条时自动将时间段一分为二。"""
        nonlocal total_rows, request_count, result_workbook, result_sheet
        request_count += 1
        print(
            f"[INFO] 正在请求 {start_time.strftime('%Y-%m-%d %H:%M:%S')} 至 "
            f"{end_time.strftime('%Y-%m-%d %H:%M:%S')}..."
        )

        content = _request_export_range(
            session, token, url, body, start_time, end_time
        )
        try:
            workbook = load_workbook(BytesIO(content))
            sheet = workbook.active
            header_row = _find_header_row(sheet)
            rows = [
                tuple(cell.value for cell in row)
                for row in sheet.iter_rows(min_row=header_row + 1)
                if any(cell.value is not None for cell in row)
            ]
        except Exception as ex:
            raise RuntimeError(f"返回内容不是有效 Excel: {ex}") from ex

        row_count = len(rows)
        print(f"[INFO] 当前时间段取得 {row_count} 条。")

        # 达到接口上限时，不能相信这已经是全部数据。将时间段切半后重取，
        # 不把本次可能被截断的 20000 条写入结果，以免重复。
        if row_count >= EXPORT_PAGE_SIZE:
            workbook.close()
            if start_time >= end_time:
                raise RuntimeError(
                    f"时间点 {start_time} 仍达到 {EXPORT_PAGE_SIZE} 条，"
                    "无法继续细分，请确认接口是否支持其他筛选字段。"
                )
            midpoint = start_time + (end_time - start_time) // 2
            right_start = midpoint + timedelta(seconds=1)
            print(
                f"[INFO] 当前时间段达到 {EXPORT_PAGE_SIZE} 条上限，"
                "自动拆成两个更小时间段重新请求。"
            )
            fetch_range(start_time, midpoint)
            fetch_range(right_start, end_time)
            return

        if result_workbook is None:
            # 第一段保留接口原始标题、表头、列宽和样式。
            result_workbook = workbook
            result_sheet = result_workbook.active
        else:
            for row_values in rows:
                result_sheet.append(row_values)
            workbook.close()

        total_rows += row_count
        print(f"[INFO] 当前累计 {total_rows} 条。")

    try:
        # 先按天请求，避免直接查询整月导致接口超时。
        current_start = full_start
        while current_start <= full_end:
            current_end = min(
                current_start.replace(hour=23, minute=59, second=59),
                full_end,
            )
            fetch_range(current_start, current_end)
            current_start = current_end + timedelta(seconds=1)

        if result_workbook is None:
            raise RuntimeError("没有取得可保存的 Excel 内容")

        result_workbook.save(output_path)
        result_workbook.close()
    except Exception as ex:
        if result_workbook is not None:
            result_workbook.close()
        print(f"[FAIL] 导出失败: {ex}")
        return False

    print(
        f"[OK] 已导出: {output_path}，共 {total_rows} 条，"
        f"共请求接口 {request_count} 次。"
    )
    return True


def export_outbound(session, token, export_month, start_date, end_date, output_dir=EXPORT_DIR):
    """导出指定月份的终端出库数据。"""
    body = {
        "pageNum": 1,
        "pageSize": EXPORT_PAGE_SIZE,
        "operTypes": ["装机物资确认", "修障物资确认"],
        "confirmTimeStart": start_date + " 00:00:00",
        "confirmTimeEnd": end_date + " 23:59:59",
        "fieldNames": [
            "regionName", "countyName", "className", "applyCode", "title",
            "operType", "relatedFormType", "relatedForm", "useApplyCode",
            "materialId", "materialName", "model", "measurementUnit",
            "status", "manufacturer", "newSnNum", "repairSnNum",
            "recoveryNosnNum", "totalNum", "applyTime", "applier",
            "confirmTime", "confirmPerson",
        ],
    }
    output_path = os.path.join(output_dir, f"终端出库_{export_month}.xlsx")
    url = f"{BASE}/api/materials/materialsmng/materials-return-log/detail/export"
    return post_export(session, token, url, body, output_path)


def export_inbound(session, token, export_month, start_date, end_date, output_dir=EXPORT_DIR):
    """导出指定月份的终端入库数据。"""
    body = {
        "pageNum": 1,
        "pageSize": EXPORT_PAGE_SIZE,
        "operTypes": ["拆机物资拆回", "修障物资拆回"],
        "confirmTimeStart": start_date + " 00:00:00",
        "confirmTimeEnd": end_date + " 23:59:59",
        "fieldNames": [
            "regionName", "countyName", "className", "applyCode", "title",
            "operType", "relatedFormType", "relatedForm", "useApplyCode",
            "materialId", "materialName", "model", "measurementUnit",
            "status", "manufacturer", "newSnNum", "repairSnNum",
            "recoveryNosnNum", "totalNum", "applyTime", "applier",
            "confirmTime", "confirmPerson",
        ],
    }
    output_path = os.path.join(output_dir, f"终端入库_{export_month}.xlsx")
    url = f"{BASE}/api/materials/materialsmng/materials-return-log/detail/export"
    return post_export(session, token, url, body, output_path)


def export_material_baseline(session, token, output_dir=EXPORT_DIR):
    """下载全省物资基准库。"""
    url = f"{BASE}/api/materials/materialsmng/materials-kind/export"
    body = {
        "classification": "",
        "model": "",
        "material_name": "",
        "material_id": "",
        "manufacturer": "",
        "terminal_type": "",
        "is_main_device": "",
        "device_classification": "",
        "terminal_type_esop": "",
    }
    output_path = os.path.join(output_dir, "全省物资基准库.xlsx")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    last_error = None
    for attempt in range(1, EXPORT_MAX_RETRIES + 1):
        try:
            response = session.post(
                url,
                json=body,
                headers=export_headers(token),
                timeout=EXPORT_TIMEOUT,
            )
            content_type = response.headers.get("content-type", "").lower()
            if response.status_code != 200:
                last_error = (
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
            elif "json" in content_type:
                last_error = f"返回 JSON 而非 Excel: {response.text[:300]}"
            else:
                # 下载完成后先验证内容确实是可读取的 Excel，再写入文件。
                workbook = load_workbook(BytesIO(response.content), read_only=True)
                workbook.close()
                with open(output_path, "wb") as output_file:
                    output_file.write(response.content)
                print(f"[OK] 已导出: {output_path}")
                return True
        except (requests.RequestException, OSError, ValueError) as ex:
            last_error = str(ex)
        except Exception as ex:
            last_error = f"返回内容不是有效 Excel: {ex}"

        print(
            f"[WARN] 全省物资基准库第 {attempt} 次下载失败: {last_error}"
        )
        if attempt < EXPORT_MAX_RETRIES:
            time.sleep(3)

    print(f"[FAIL] 全省物资基准库下载失败: {last_error}")
    return False


def decode_jwt_payload(token):
    try:
        seg = token.split(".")[1]
        pad = "=" * (-len(seg) % 4)
        obj = json.loads(base64.urlsafe_b64decode(seg + pad))
        exp = obj.get("exp")
        account_id = obj.get("sub")
        net_user = obj.get("netUserid")
        return exp, account_id, net_user, obj
    except Exception as ex:
        return None, None, None, {"err": str(ex)}


def update_cred_json(account, token, extra=None):
    data = {}
    if os.path.exists(CRED):
        try:
            with open(CRED, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    exp, account_id, net_user, payload = decode_jwt_payload(token)
    exp_str = time.strftime("%Y-%m-%d %H:%M:%S CST", time.localtime(exp)) if exp else "?"
    entry = {
        "user": account,
        "netUserid": net_user,
        "accountId": account_id,
        "module": "res/work+materials",
        "exp": exp,
        "exp_str": exp_str,
        "zytoken": token,
        "note": f"{time.strftime('%Y-%m-%d %H:%M:%S')} 自动登录(govent zhengqi_login.py)",
    }
    if extra:
        entry.update(extra)
    data[f"{account_id}_{net_user}"] = entry if account_id else f"auto_{account}"
    if not account_id:
        data[f"auto_{account}"] = entry
    os.makedirs(os.path.dirname(CRED), exist_ok=True)
    with open(CRED, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] 已写入 {CRED}")
    return exp_str


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
            output_dir=Path(EXPORT_DIR), reuse_existing=False, refresh=False,
            account=DEFAULT_ACCOUNT, password=DEFAULT_PASSWORD):
    month = validate_dates(start_date, end_date)
    if mode not in {"file", "database", "both"}:
        raise ValueError("Unsupported mode")
    material_names = Path(output_dir) / "物料名称表.xlsx"
    if not material_names.is_file():
        material_names = Path(__file__).resolve().parents[2] / "metrics/terminal_recovery/物料名称表.xlsx"
    cached = covered_result({
        "integration_terminal_outbound": Path(output_dir) / f"终端出库_{month}.xlsx",
        "integration_terminal_inbound": Path(output_dir) / f"终端入库_{month}.xlsx",
        "integration_material_baseline": Path(output_dir) / "全省物资基准库.xlsx",
        "terminal_material_names": material_names,
    }, start_date, end_date, mode, database, refresh, reuse_existing)
    if cached is not None:
        return cached
    with download_directory(mode, output_dir, reuse_existing) as target_dir:
        files = {
            "integration_terminal_outbound": target_dir / f"终端出库_{month}.xlsx",
            "integration_terminal_inbound": target_dir / f"终端入库_{month}.xlsx",
            "integration_material_baseline": target_dir / "全省物资基准库.xlsx",
        }
        if not reuse_existing:
            # Query the delayed monthly exports without changing the report period.
            _, query_start, query_end = normalize_month(month)
            print(f"[INFO] 统计周期：{start_date} 至 {end_date}；出入库查询范围：{query_start} 00:00:00 至 {query_end} 23:59:59", flush=True)
            with requests.Session() as session:
                session.verify = False
                session.headers.update({"User-Agent": "Mozilla/5.0", "Origin": CAS})
                session = login(session, account, password)
                token = extract_token(session)
                update_cred_json(account, token)
                if not export_outbound(session, token, month, query_start, query_end, target_dir):
                    raise RuntimeError("Terminal outbound export failed")
                if not export_inbound(session, token, month, query_start, query_end, target_dir):
                    raise RuntimeError("Terminal inbound export failed")
                if not export_material_baseline(session, token, target_dir):
                    raise RuntimeError("Material baseline export failed")
        files["terminal_material_names"] = material_names
        return finish_exports(files, start_date, end_date, mode, database)



def main():
    ap = parser("一体化终端出入库及物资基准库取数、入库")
    ap.add_argument("--account", default=DEFAULT_ACCOUNT)
    ap.add_argument("--password", default=DEFAULT_PASSWORD)
    print(json.dumps(collect(**vars(ap.parse_args())), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
