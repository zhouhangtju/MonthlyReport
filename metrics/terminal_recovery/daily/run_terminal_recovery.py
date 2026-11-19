import argparse
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from metrics.terminal_recovery import terminal_recovery_export_online as calc
from metrics.terminal_recovery import districts
from split_terminal_recovery import split_raw, split_intermediate, clean_sources, clean_intermediate
from export_terminal_recovery_results import export_results


def collect(raw, start, end, month):
    import requests
    from collector.integration import integration_dismantle as api, zhuanxian_chaiji_export as line
    from collector.eoms import eoms_export_qiwan_auto_login as service
    integration = raw / "integration"
    line.collect(start, end, mode="file", output_dir=integration)
    service.collect(start, end, mode="file", output_dir=raw / "eoms")
    with requests.Session() as session:
        session.verify = False
        session.headers.update({"User-Agent": "Mozilla/5.0", "Origin": api.CAS})
        session = api.login(session, api.DEFAULT_ACCOUNT, api.DEFAULT_PASSWORD)
        token = api.extract_token(session)
        if not api.export_inbound(session, token, month, start, end, integration):
            raise RuntimeError("终端入库导出失败")
        if not api.export_material_baseline(session, token, integration):
            raise RuntimeError("物资基准库导出失败")


def run(start, end, root, today, collector=collect):
    month = calc.validate_dates(start, end)
    batch = f"{today}_{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".lock"
    with lock.open("x") as handle:
        handle.write(batch)
    try:
        with TemporaryDirectory(dir=root) as temp:
            stage = Path(temp)
            raw = stage / "raw"
            for name in ("eoms", "integration"):
                (raw / name).mkdir(parents=True)
            collector(raw, start, end, month)
            evidence = stage / "evidence"
            archive = evidence / "raw"
            shutil.copytree(raw, archive)
            line, service, inbound = calc.get_business_source_files(month)
            sources = [archive / "integration" / line, archive / "eoms" / service, archive / "integration" / inbound]
            inputs = stage / "inputs"
            inputs.mkdir()
            references = evidence / "参考资料"
            references.mkdir()
            material = Path(shutil.copy2(calc.MATERIAL_NAME_SOURCE_FILE, references))
            for path in [*sources, archive / "integration" / "全省物资基准库.xlsx", material]:
                shutil.copy2(path, inputs)
            mapping = shutil.copy2(districts.resolve_mapping(evidence), references)
            district_map = districts.load_mapping(mapping)
            clean_sources(sources, district_map)
            split_raw(archive, sources)
            report, _ = calc.export(start, end, inputs, evidence)
            district_file = stage / "district_work.xlsx"
            district_report = districts.build_district_report(sources[0], sources[1], report, mapping, district_file)
            clean_intermediate(report, district_map, district_file)
            split_intermediate(report)
            export_results(report, stage / "results", batch, start, end, district_report["rows"])
            moves = []
            try:
                for folder in ("evidence", "results/省级", "results/地市", "results/区县"):
                    (root / folder).mkdir(parents=True, exist_ok=True)
                    target = root / folder / batch
                    (stage / folder).rename(target)
                    moves.append((target, stage / folder))
                if (root / "raw").exists():
                    (root / "raw").rename(stage / "previous")
                    moves.append((stage / "previous", root / "raw"))
                raw.rename(root / "raw")
            except OSError:
                for source, target in reversed(moves):
                    source.rename(target)
                raise
    finally:
        lock.unlink()
    print(root / "results", batch)
    return batch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, action="store_true")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output-dir", type=Path, default=Path("D:/dev-projects/openclaw_data/outputs/terminal_recovery_rate"))
    args = parser.parse_args()
    today = datetime.now(timezone(timedelta(hours=8))).date()
    if bool(args.start_date) != bool(args.end_date):
        parser.error("--start-date 和 --end-date 需要同时指定")
    if not args.start_date and today.day == 1:
        print("本月暂无已结束统计日")
        return
    run(args.start_date or today.replace(day=1).isoformat(), args.end_date or (today-timedelta(days=1)).isoformat(), args.output_dir, today)


if __name__ == "__main__":
    main()
