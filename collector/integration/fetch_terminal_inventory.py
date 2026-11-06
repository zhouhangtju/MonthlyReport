"""Collect terminal stock manually at month end, with full API records and export."""
import argparse
import calendar
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from openpyxl import load_workbook
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import requests
from collector.integration import integration_dismantle as common
from collector.integration.material_api import fetch_records, write_records

def collect(month, mode="both", output_dir=None):
    period = datetime.strptime(month, "%Y-%m")
    if period.strftime("%Y-%m") != month: raise ValueError("Use YYYY-MM")
    start = month + "-01"
    end = month + f"-{calendar.monthrange(period.year, period.month)[1]:02d}"
    output_dir = Path(output_dir or Path(__file__).resolve().parents[2] / "data/raw/integration/terminal_inventory")
    filters = {"regionCode":"","countyCode":"","warehouseName":"","projectName":"",
               "classification":"终端","materialsId":"","materialsName":"","materialsKeys":[],
               "model":"","groupFields":["a.region_name","a.county_name","a.warehouse_name","a.project_name","a.batch_no"]}
    with common.download_directory(mode, output_dir) as target:
        target.mkdir(parents=True, exist_ok=True)
        captured = datetime.now(ZoneInfo("Asia/Shanghai"))
        stamp = captured.strftime("%Y%m%d_%H%M%S_%f")
        normalized = target / f"终端库存明细_{month}_{stamp}.xlsx"
        original = target / f"终端库存平台导出_{month}_{stamp}.xlsx"
        with requests.Session() as session:
            session.verify = False
            session.headers.update({"User-Agent":"Mozilla/5.0","Origin":common.CAS})
            session = common.login(session, common.DEFAULT_ACCOUNT, common.DEFAULT_PASSWORD)
            token = common.extract_token(session)
            rows = fetch_records(session, token, "/api/materials/materialsmng/materials-warehouse-storage/count-all", filters)
            write_records(normalized, rows, "inventory")
            response = session.post(common.BASE + "/api/materials/materialsmng/materials-warehouse-storage/count-all/export",
                                    json=filters, headers=common.export_headers(token), timeout=180, verify=False)
            response.raise_for_status()
            original.write_bytes(response.content)
            wb = load_workbook(original, read_only=True); wb.close()
        result = common.finish_exports({"integration_terminal_inventory":normalized}, start, end, mode, None)
        result.update(captured_at=captured.isoformat(), filters=filters, record_count=len(rows))
        if mode != "file":
            from storage.terminal_recovery import save_source
            etl = result["etl"]["integration_terminal_inventory"]
            # Same ETL batch, separate source artifact; no second import of exported rows.
            result["platform_export_snapshot"] = save_source(None, "integration_terminal_inventory_export",
                                                              original, start, end, etl["run_id"])
        if mode != "database":
            result["platform_export"] = str(original)
            (target / f"采集记录_{month}_{stamp}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m"))
    parser.add_argument("--mode", choices=["file","database","both"], default="both")
    parser.add_argument("--output-dir", type=Path)
    print(json.dumps(collect(**vars(parser.parse_args())), ensure_ascii=False, indent=2))
if __name__ == "__main__": main()
