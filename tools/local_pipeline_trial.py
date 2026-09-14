"""Offline integration trial using exported files, never live collector requests."""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config.datasets import get_dataset
from storage.importer import import_file
from storage.raw_archive import digest_file


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("D:/edge_download"))
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--phase", choices=["import", "metrics", "ppt", "cleanup", "verify"], required=True)
    args = parser.parse_args()
    trial = args.trial.resolve()
    if ROOT not in trial.parents or trial == ROOT / "data":
        raise ValueError("Use a dedicated trial folder inside the project")
    db = trial / "data" / "quality_assessment.db"
    trial.mkdir(parents=True, exist_ok=True)
    logs = trial / "logs"
    logs.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(ROOT))

    def run(script, extra, name):
        cmd = [sys.executable, str(ROOT / script), "--database", str(db), *extra]
        started = datetime.now().isoformat()
        print("START", name, flush=True)
        with (logs / (name + ".log")).open("w", encoding="utf-8") as log:
            proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        write(logs / (name + ".json"), dict(command=cmd, started=started,
              finished=datetime.now().isoformat(), returncode=proc.returncode))
        print("END", name, proc.returncode, flush=True)
        return proc.returncode == 0

    if args.phase == "import":
        if db.exists():
            raise ValueError("Import requires a new trial database")
        selected = []
        for platform, code in [("eoms", "eoms_complaint"), ("integration", "integration_opening"),
                               ("orchestration", "orch_opening"), ("orchestration", "orch_install"),
                               ("youshu", "youshu_install"), ("youshu", "youshu_complaint")]:
            files = sorted((args.source / platform / code).glob("*.xlsx"))
            if code == "eoms_complaint":
                files = [p for p in files if "20260601-20260831" in p.name]
            elif code == "integration_opening":
                files = [p for p in files if "2026-08-31" in p.name]
            elif code == "youshu_complaint":
                files = [p for p in files if "合并" in p.name][-1:]
            elif code == "orch_install":
                files = [p for p in files if "2026-08-01_2026-08-03" not in p.name]
            if not files:
                raise ValueError("Missing source: " + code)
            for path in files:
                start, end = ("2026-08-01", "2026-08-31") if code == "integration_opening" else ("2026-06-01", "2026-08-31")
                if code.startswith("orch_"):
                    start, end = re.findall(r"\d{4}-\d{2}-\d{2}", path.name)[:2]
                selected.append(dict(dataset=code, path=str(path), start=start, end=end, sha256=digest_file(path)))
        originals = selected + [dict(path=str(p), sha256=digest_file(p)) for p in sorted((args.source / "终端回收").glob("*.xlsx"))]
        write(trial / "source_inventory.json", originals)
        imports = []
        for item in selected:
            print("IMPORT", item["dataset"], Path(item["path"]).name, flush=True)
            result = import_file(db, get_dataset(item["dataset"]), Path(item["path"]),
                                 period_start=item["start"], period_end=item["end"])
            imports.append({**item, **result})
            write(trial / "imports.json", imports)
            print(result, flush=True)
            if result["failed"]:
                raise ValueError("Source has missing business keys; inspect imports.json")
        for script in ["collector/eoms/eoms_export_qiwan_auto_login.py", "collector/integration/zhuanxian_chaiji_export.py", "collector/integration/integration_dismantle.py"]:
            if not run(script, ["--start-date", "2026-08-01", "--end-date", "2026-08-31", "--mode", "both", "--reuse-existing", "--refresh", "--output-dir", str(args.source / "终端回收")], Path(script).stem):
                raise RuntimeError("Terminal simulation failed")
    elif args.phase == "metrics":
        for month in ["2026-06", "2026-07"]:
            run("metrics/opening/dedicated_line_metrics.py", ["--start-month", month, "--end-month", month,
                "--mode", "both", "--output", str(trial / ("opening_" + month + ".json"))], "opening_" + month)
        jobs = [
            ("metrics/opening/dedicated_line_metrics.py", ["--start-month", "2026-06", "--end-month", "2026-08"]),
            ("metrics/opening/withdrawal.py", ["--start-date", "2026-08-01", "--end-date", "2026-08-31"]),
        ]
        for name in ["complaint/dedicated_line_repeat_complaint_rate", "complaint/qianliyan_repeat_complaint_rate", "installation/qikuan_install_fault_rate", "installation/dedicated_line_install_fault_rate", "installation/commercial_customer_install_fault_rate"]:
            jobs.append(("metrics/" + name + ".py", ["--start-date", "2026-06-01", "--end-date", "2026-08-31"]))
        results = {}
        for script, extra in jobs:
            name = Path(script).stem
            results[name] = run(script, extra + ["--mode", "both", "--output", str(trial / (name + ".json"))], name)
        script = "metrics/terminal_recovery/terminal_recovery_export_online.py"
        results["terminal_recovery"] = run(script, ["--start-date", "2026-08-01", "--end-date", "2026-08-31", "--mode", "both", "--output-dir", str(trial / "terminal")], "terminal_recovery")
        write(trial / "metrics_status.json", results)
    elif args.phase == "ppt":
        name = "ppt_after_cleanup" if (trial / "checks.json").exists() else "ppt"
        run("reporting/build_internet_line_ppt.py", ["--month", "2026-08", "--keep-json", "--output", str(trial / "monthly_report_2026-08.pptx")], name)
    elif args.phase == "verify":
        from contextlib import closing
        from metrics.installation.common import load_dataset
        with closing(sqlite3.connect(db)) as conn:
            report = dict(etl=conn.execute("SELECT dataset_code,count(*),sum(rows_read),sum(rows_failed) FROM etl_run GROUP BY dataset_code").fetchall(),
                          metric_batches=conn.execute("SELECT metric_code,status,count(*) FROM metric_run GROUP BY metric_code,status").fetchall(),
                          results=conn.execute("SELECT count(*) FROM ads_metric_result").fetchone()[0],
                          free_bytes=conn.execute("PRAGMA freelist_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0])
            matches = {}
            for path in [*trial.glob("*.json"), *(trial / "terminal").glob("*.json")]:
                obj = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(obj, dict) or not obj.get("metric_run_id") or "results" not in obj:
                    continue
                stored = conn.execute("SELECT metric_code,dimension_type,dimension_value,numerator,denominator,metric_value FROM ads_metric_result WHERE metric_run_id=?", (obj["metric_run_id"],)).fetchall()
                actual = [(r[0], r[1], json.loads(r[2]), r[3], r[4], r[5]) for r in stored]
                expected = [(r["metric_code"], r["dimension_type"], r["dimension"], r["numerator"], r["denominator"], r["metric_value"]) for r in obj["results"]]
                # Python numeric equality treats SQLite REAL and JSON integer counts equally.
                key = lambda r: json.dumps(r[:3], ensure_ascii=False, sort_keys=True)
                matches[path.name] = sorted(actual, key=key) == sorted(expected, key=key)
            report["json_sqlite_matches"] = matches
            archives = conn.execute("SELECT archived_file,file_sha256 FROM etl_run").fetchall()
            report["all_import_archives_intact"] = all(Path(p).is_file() and digest_file(p) == sha for p, sha in archives)
        try:
            load_dataset(db, "eoms_complaint")
            report["missing_source_guard"] = False
        except RuntimeError as exc:
            report["missing_source_guard"] = str(exc)
        imported = json.loads((trial / "imports.json").read_text(encoding="utf-8"))[0]
        recovery_db = trial / "restore_smoke" / datetime.now().strftime("%Y%m%d_%H%M%S_%f") / "quality_assessment.db"
        if recovery_db.exists():
            raise ValueError("Restore smoke test must use a fresh database")
        result = import_file(recovery_db, get_dataset("eoms_complaint"), Path(imported["archived_file"]), period_start="2026-06-01", period_end="2026-08-31")
        with closing(sqlite3.connect(recovery_db)) as conn:
            count = conn.execute("SELECT count(*) FROM raw_source_record").fetchone()[0]
        report["restore_smoke"] = dict(dataset="eoms_complaint", rows=count, expected=imported["read"], failed=result["failed"])
        write(trial / "verification.json", report)
        print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)
    elif args.phase == "cleanup":
        from metrics.cleanup.common import cleanup
        from contextlib import closing
        from reporting.database_results import build_data
        def state():
            with closing(sqlite3.connect(db)) as conn:
                return {t: conn.execute('SELECT * FROM "' + t + '" ORDER BY rowid').fetchall() for t in ["ads_metric_result", "orch_opening_monthly_summary", "orch_opening_monthly_quality"]}
        before = state()
        ppt_before = build_data(db, "2026-08")
        write(trial / "results_before_cleanup.json", before)
        jobs = [
            ("eoms", ["eoms_complaint"], "2026-06-01"),
            ("eoms", ["eoms_service_removal_order"], "2026-08-01"),
            ("integration", ["integration_opening", "integration_removal_order", "integration_terminal_inbound", "integration_terminal_outbound", "integration_material_baseline", "terminal_material_names"], "2026-08-01"),
            ("orchestration", ["orch_install"], "2026-06-01"),
            ("orchestration", ["orch_opening"], "2026-06-01"),
            ("youshu", ["youshu_install", "youshu_complaint"], "2026-06-01"),
        ]
        reports = []
        for platform, datasets, start in jobs:
            try:
                report = cleanup(db, platform, datasets, start, "2026-08-31")
                if not report["blockers"]:
                    report = cleanup(db, platform, datasets, start, "2026-08-31", apply=True)
            except Exception as exc:
                report = dict(platform=platform, datasets=datasets, blockers=[str(exc)], applied=False)
            reports.append(report)
            write(trial / "cleanup_report.json", reports)
            print(platform, datasets, report.get("applied"), report["blockers"], flush=True)
        unchanged = before == state()
        ppt_after = build_data(db, "2026-08")
        write(trial / "ppt_data_after_cleanup.json", ppt_after)
        sources = json.loads((trial / "source_inventory.json").read_text(encoding="utf-8"))
        intact = all(digest_file(r["path"]) == r["sha256"] for r in sources)
        with closing(sqlite3.connect(db)) as conn:
            checks = dict(results_unchanged=unchanged, originals_unchanged=intact,
                          ppt_data_unchanged=ppt_before == ppt_after,
                          integrity=conn.execute("PRAGMA integrity_check").fetchall(),
                          foreign_keys=conn.execute("PRAGMA foreign_key_check").fetchall(),
                          remaining_raw=conn.execute("SELECT dataset_code,count(*) FROM raw_source_record GROUP BY dataset_code").fetchall())
        write(trial / "checks.json", checks)
        print(checks, flush=True)


if __name__ == "__main__":
    main()
