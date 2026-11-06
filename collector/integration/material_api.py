"""Paged material APIs; preserve every response field and legacy outbound columns."""
import json
from pathlib import Path
from openpyxl import Workbook, load_workbook

FIELDS = json.loads(Path(__file__).with_name("material_fields.json").read_text(encoding="utf-8"))
LEGACY = dict(zip(
 ["地市","区县","班组名称","编号","标题","操作类型","关联单据类型","关联单据号","领用单编号","物料ID","物料名称","型号","计量单位","状态","厂家","新物资数量","返修物资数量","回收物资数量","总数量","申请时间","申请人","确认时间","确认人"],
 ["regionName","countyName","className","applyCode","title","operType","relatedFormType","relatedForm","useApplyCode","materialId","materialName","model","measurementUnit","status","manufacturer","newSnNum","repairSnNum","recoveryNosnNum","totalNum","applyTime","applier","confirmTime","confirmPerson"]))

def fetch_records(session, token, endpoint, filters, page_size=200):
    from collector.integration.integration_dismantle import BASE, export_headers
    rows, total, seen = [], None, set()
    page = 1
    while True:
        response = session.post(BASE + endpoint, json={**filters, "pageNum": page, "pageSize": page_size},
                                headers=export_headers(token), timeout=120, verify=False)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            raise RuntimeError("Material API returned no valid records page")
        current_total = int(data["total"])
        if total is None: total = current_total
        if current_total != total: raise RuntimeError("Material count changed during paging; retry")
        batch = data["records"]
        if not all(isinstance(row, dict) for row in batch): raise RuntimeError("Invalid material record")
        signature = json.dumps(batch, sort_keys=True, ensure_ascii=False)
        if batch and signature in seen: raise RuntimeError("Repeated material page")
        seen.add(signature)
        rows.extend(batch)
        if len(rows) == total: return rows
        if not batch or len(rows) > total: raise RuntimeError("Material pagination count mismatch")
        page += 1

def write_records(path, rows, kind):
    from storage.raw_tables import source_columns
    code = "integration_terminal_inventory" if kind == "inventory" else "integration_terminal_outbound"
    headers = source_columns(code)
    unknown = set().union(*(set(r) for r in rows)) - set(FIELDS[kind]) if rows else set()
    # Keep any newly introduced response fields too; importer adds them under its dataset lock.
    headers = headers + sorted(unknown - set(headers))
    workbook = Workbook()
    ws = workbook.active
    ws.append(headers)
    for row in rows:
        values = []
        for name in headers:
            value = row.get(name) if name in row else row.get(LEGACY.get(name)) if kind == "outbound" else None
            if isinstance(value, (dict,list)): value = json.dumps(value, ensure_ascii=False)
            values.append(value)
        ws.append(values)
        for cell in ws[ws.max_row]:
            if isinstance(cell.value, str): cell.data_type = "s"
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path); workbook.close()

def validate_outbound_file(path):
    wb = load_workbook(path, read_only=True)
    try:
        headers = next(wb.active.iter_rows(values_only=True))
        if not set(FIELDS["outbound"]).issubset(headers):
            raise ValueError("Old outbound workbook lacks API fields; collect again without --reuse-existing")
    finally: wb.close()
