"""Database-first query service for the remote MySQL result contract."""
import calendar
import json
import tempfile
import os
from pathlib import Path
from report_api.backend import database
from storage.metric_results import read_results
from config.report_periods import integration_opening_period
from datetime import date, timedelta
from threading import Lock

from metrics.complaint.repeat_rate import LINE, QLY, run_metric
from metrics.installation import commercial_customer_install_fault_rate as commercial
from metrics.installation import dedicated_line_install_fault_rate as dedicated
from metrics.installation import qikuan_install_fault_rate as broadband
from metrics.opening import dedicated_line_metrics as opening, withdrawal

OPEN = "orchestration_opening_metrics"
COM = "commercial_customer_install_fault_rate"
LINE_FAULT = "dedicated_line_install_fault_rate"
BB_FAULT = "qikuan_install_fault_rate"
WITHDRAW = "dedicated_line_opening_withdrawal_rate"
RECOVER = "terminal_recovery"
QOPEN = "qikuan_opening_metrics"
SILENCE = "qikuan_activation_silence"
QIKUAN_REPEAT = "qikuan_repeat_complaint_rate"
COMMERCIAL_REPEAT = "commercial_repeat_complaint_rate"
MANUAL_METRICS = {QIKUAN_REPEAT: "qikuan_repeat_complaint_rate", COMMERCIAL_REPEAT: "combined_repeat_complaint_rate"}
NAMES = {OPEN: "专线开通与自动率", WITHDRAW: "专线撤退单率", LINE.metric_code: "专线重复投诉率",
         QLY.metric_code: "千里眼重复投诉率", QIKUAN_REPEAT: "企宽重复投诉率",
         COMMERCIAL_REPEAT: "商客重复投诉率",
         LINE_FAULT: "专线新装报障率",
         BB_FAULT: "企宽新装报障率", COM: "商客新装报障率", RECOVER: "终端回收", QOPEN:"企宽开通", SILENCE:"企宽激活即沉默"}
class MissingSource(Exception):
    pass


def period(owner, month):
    end_month = date.fromisoformat(month + "-01")
    if end_month.strftime("%Y-%m") != month or owner not in NAMES:
        raise ValueError("月份或指标模块无效")
    if owner in MANUAL_METRICS:
        return end_month, end_month.replace(day=calendar.monthrange(end_month.year, end_month.month)[1])
    if owner == WITHDRAW:
        return tuple(date.fromisoformat(v) for v in integration_opening_period(month))
    back = 11 if owner == OPEN else 0 if owner in (RECOVER,QOPEN,SILENCE) else 2
    year, m = divmod(end_month.year * 12 + end_month.month - 1 - back, 12)
    return date(year, m + 1, 1), end_month.replace(day=calendar.monthrange(end_month.year, end_month.month)[1])


class Service:
    def __init__(self, read_only=False):
        self.read_only = read_only
        self.write_lock = Lock()

    def connect(self):
        return database.connect()

    def latest(self, owner, start, end):
        # Opening runs can span different history windows for the same report month.
        comparison = "period_start<=?" if owner == OPEN else "period_start=?"
        lower = str(end.replace(day=1)) if owner == OPEN else str(start)
        with self.connect() as db:
            run = db.execute(f"""SELECT metric_run_id,finished_at,period_start,period_end
                FROM metric_run WHERE metric_code=? AND {comparison} AND period_end=? AND status='success'
                ORDER BY started_at DESC, metric_run_id DESC LIMIT 1""",
                (owner,lower,str(end))).fetchone()
            if run is None:
                return None
            rows = read_results(db,owner,run["metric_run_id"])
            if not rows:
                return None
            for row in rows:
                row["dimension"] = json.loads(row.pop("dimension_value"))
            return dict(run, results=rows, owner=owner, start=str(run["period_start"]), end=str(run["period_end"]))

    def latest_manual(self, owner, month):
        if owner not in MANUAL_METRICS:
            return None
        db_set = MANUAL_METRICS[owner]
        with self.connect() as db:
            row = db.execute(
                "SELECT result_json FROM manual_metric_result WHERE metric_set=? AND report_month=?",
                (db_set, month)).fetchone()
        if row is None:
            return None
        doc = json.loads(row["result_json"]) if isinstance(row["result_json"], str) else row["result_json"]
        results = []
        province = doc.get("province")
        if province:
            results.append({
                "metric_code": owner, "dimension_type": "province",
                "dimension": {"scope": "全省"},
                "numerator": province.get("numerator"), "denominator": province.get("denominator"),
                "metric_value": province.get("rate"),
            })
        cities = doc.get("cities")
        if isinstance(cities, dict):
            for city_name, city_data in cities.items():
                if not isinstance(city_data, dict):
                    continue
                results.append({
                    "metric_code": owner, "dimension_type": "city",
                    "dimension": {"city": city_name},
                    "numerator": city_data.get("numerator"), "denominator": city_data.get("denominator"),
                    "metric_value": city_data.get("rate"),
                })
        if not results:
            return None
        end_month = date.fromisoformat(month + "-01")
        period_end = end_month.replace(day=calendar.monthrange(end_month.year, end_month.month)[1])
        return {
            "metric_run_id": f"manual_{owner}_{month}",
            "finished_at": None,
            "period_start": str(end_month),
            "period_end": str(period_end),
            "results": results,
            "owner": owner,
            "start": str(end_month),
            "end": str(period_end),
        }

    def compute(self, owner, start, end, force):
        s, e = str(start), str(end)
        if owner == COM:
            for dep in (LINE_FAULT, BB_FAULT):
                if force or not self.latest(dep, start, end):
                    self.compute(dep, start, end, force)
        if owner == OPEN:
            assets = os.getenv("MONTHLYREPORT_ASSET_DIR")
            csv = Path(assets) / (e[:7]+".csv") if assets else None
            if csv is None or not csv.is_file():
                raise MissingSource(f"当前计算引擎需要 {e[:7]} 的资管环节 CSV，请配置 MONTHLYREPORT_ASSET_DIR")
            opening.run(None, s[:7], e[:7], mode="database", asset_csv=csv)
        elif owner in (LINE.metric_code, QLY.metric_code):
            run_metric(LINE if owner == LINE.metric_code else QLY, Path("."), s, e, "database", None)
        elif owner == QOPEN:
            from metrics.qikuan_opening.qikuan_opening_metrics import run
            run(e[:7],mode="database")
        elif owner == SILENCE:
            from metrics.qikuan_activation_silence.qikuan_activation_silence_metrics import run
            with tempfile.TemporaryDirectory() as tmp:
                run(e[:7],None,Path(tmp))
        elif owner == RECOVER:
            from metrics.terminal_recovery.terminal_recovery_export_online import export_database
            export_database(s, e, Path("."), mode="database")
        else:
            module = {COM: commercial, LINE_FAULT: dedicated, BB_FAULT: broadband, WITHDRAW: withdrawal}[owner]
            module.run(Path("."), s, e, mode="database")

    def query(self, owner, month, refresh=False, previous=None):
        start, end = period(owner, month)
        cached = self.latest(owner, start, end)
        if cached and not refresh:
            return dict(cached, source="database")
        if self.read_only:
            raise MissingSource("只读结果库：当前周期无结果或请求了重算")
        with self.write_lock:
            cached = self.latest(owner, start, end)
            if cached and (not refresh or cached["metric_run_id"] != previous):
                return dict(cached, source="database")
            self.compute(owner, start, end, refresh)
            result = self.latest(owner, start, end)
            if not result:
                raise MissingSource("计算已结束，但该周期没有指标结果")
            return dict(result, source="calculated")
