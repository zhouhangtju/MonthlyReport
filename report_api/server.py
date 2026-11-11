"""Run with python -m report_api.server --port 8027."""
import argparse
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from report_api.backend import configure
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from http.server import BaseHTTPRequestHandler
from report_api.backend import V1
import os
WEB = Path(os.getenv("MONTHLYREPORT_WEB", V1.parents[1] / "monthly-report-web")).resolve()
from report_api.service import MissingSource, NAMES, MANUAL_METRICS, Service


def encode_value(value):
    if isinstance(value,(date,datetime)):
        return value.isoformat()
    if isinstance(value,Decimal):
        return float(value)
    raise TypeError("无法序列化指标结果")


class Handler(BaseHTTPRequestHandler):
    def send_body(self, status, body, mime):
        self.send_response(status)
        self.send_header("Content-Type", mime+"; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api(self, status, obj):
        self.send_body(status, json.dumps(obj, ensure_ascii=False, allow_nan=False, default=encode_value).encode(), "application/json")

    def do_GET(self):
        if self.path in ("/live","/historical"):
            self.send_body(200, Path(__file__).with_name("live.html").read_bytes(), "text/html")
        elif self.path == "/":
            html = (WEB/"index.html").read_text()
            html = html.replace('<div class="top">','<div class="top"><a href="/live" class="tab">数据库指标与更新 →</a></div><div class="top">',1)
            self.send_body(200, html.encode(), "text/html")
        elif self.path == "/api/v1/catalog":
            try:
                with closing(self.server.service.connect()) as db:
                    months = sorted({r["month"] for r in db.execute("SELECT DISTINCT LEFT(period_end,7) AS month FROM metric_run WHERE status='success'")
                                     } | {r["month"] for r in db.execute("SELECT DISTINCT report_month AS month FROM manual_metric_result")}, reverse=True)
                self.api(200, dict(modules=NAMES, months=months))
            except Exception:
                logging.exception("无法读取 MySQL 指标目录")
                self.api(503, {"error":"无法读取远程 MySQL，请检查网络、数据库配置及结果表权限。"})
        elif self.path.startswith("/api/v1/reports/"):
            self.report(self.path.removeprefix("/api/v1/reports/"))
        else:
            self.send_error(404)

    def report(self, month):
        from report_api.service import period
        try:
            groups = {}
            for owner in NAMES:
                if owner in MANUAL_METRICS:
                    try:
                        groups[owner] = self.server.service.latest_manual(owner, month)
                    except Exception as exc:
                        if getattr(exc,"args",())[:1] != (1146,):
                            raise
                        groups[owner] = None
                else:
                    start,end = period(owner,month)
                    try:
                        groups[owner] = self.server.service.latest(owner,start,end)
                    except Exception as exc:
                        if getattr(exc,"args",())[:1] != (1146,):
                            raise
                        groups[owner] = None
            with self.server.service.connect() as db:
                docs = db.execute("SELECT metric_set,result_json FROM manual_metric_result WHERE report_month=?", (month,)).fetchall()
            manual = {r["metric_set"]:json.loads(r["result_json"]) if isinstance(r["result_json"],str) else r["result_json"] for r in docs}
            from reporting.golden_metrics import build_golden
            try:
                golden = build_golden(month)
            except Exception as exc:
                if getattr(exc,"args",())[:1] != (1146,):
                    raise
                golden = None
            self.api(200,{"month":month,"modules":groups,"manual":manual,"golden":golden})
        except ValueError as exc:
            self.api(422,{"error":str(exc)})
        except Exception:
            logging.exception("月报结果读取失败")
            self.api(503,{"error":"MySQL 查询失败"})

    def do_POST(self):
        if self.path not in ("/api/v1/query","/api/v1/refresh"):
            return self.api(404, {"error":"接口不存在"})
        if self.headers.get_content_type() != "application/json":
            return self.api(415, {"error":"需要 JSON 请求"})
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self.api(403, {"error":"只接受同源请求"})
        try:
            size = int(self.headers.get("Content-Length",0))
            if not 0 < size <= 4096:
                raise ValueError("请求体大小无效")
            args = json.loads(self.rfile.read(size))
            if not isinstance(args,dict) or not all(isinstance(args.get(k),str) for k in ("owner","month")):
                raise ValueError("需要 owner 和 month 字符串")
            refresh = self.path.endswith("/refresh")
            if refresh and not isinstance(args.get("previous"),str):
                raise ValueError("更新需要提供当前成功批次 previous")
            result = self.server.service.query(args["owner"],args["month"],refresh,args.get("previous"))
            self.api(200,result)
        except (ValueError, UnicodeError) as exc:
            self.api(400,{"error":str(exc)})
        except (MissingSource, FileNotFoundError, RuntimeError) as exc:
            self.api(409,{"error":str(exc)})
        except Exception:
            logging.exception("查询或重算失败")
            self.api(503,{"error":"计算或数据库访问失败，请检查服务日志。"})


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8027)
    parser.add_argument("--read-only",action="store_true",help="仅查询已导入批次，禁止重算")
    args=parser.parse_args()
    configure()
    server=ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    server.service=Service(read_only=args.read_only)
    server.serve_forever()
