"""Select the MySQL MonthlyReport implementation for this dedicated service process."""
import os
import sys
from pathlib import Path

V1 = Path(__file__).resolve().parents[1]
# Deployed installations normally place report_api in the MySQL project itself.
default_engine = V1 if (V1 / "storage/metric_results.py").is_file() else V1.parents[1] / "MonthlyReport"
ENGINE = Path(os.getenv("MONTHLYREPORT_ENGINE", default_engine)).resolve()
if not (ENGINE / "storage/metric_results.py").is_file():
    raise RuntimeError("MONTHLYREPORT_ENGINE 必须指向包含 storage/metric_results.py 的 MySQL 版 MonthlyReport")
sys.path.insert(0, str(ENGINE))
from storage import database


def configure():
    keys = ("HOST", "USER", "PASSWORD", "DATABASE")
    missing = [key for key in keys if not os.getenv("MONTHLYREPORT_MYSQL_" + key)]
    if missing:
        raise RuntimeError("请在部署环境配置 MONTHLYREPORT_MYSQL_" + "、MONTHLYREPORT_MYSQL_".join(missing))
    for key in keys:
        setattr(database, "DEFAULT_" + key, os.environ["MONTHLYREPORT_MYSQL_" + key])
    database.DEFAULT_PORT = int(os.getenv("MONTHLYREPORT_MYSQL_PORT", "3306"))
