"""HTTP protocol regression tests; no live requests or credentials required."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from collector.youshu.fetch_install_completed import build_task


def load_exporter():
    path = Path(__file__).resolve().parents[1] / "collector/youshu/fetch_data.py"
    spec = importlib.util.spec_from_file_location("exporter_under_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"requests": Mock()}):
        spec.loader.exec_module(module)
    return module


def response(body=None, status=200, content=None):
    result = Mock()
    result.status_code = status
    result.json.return_value = body
    result.content = content if content is not None else json.dumps(body).encode()
    result.text = result.content.decode(errors="replace")
    result.headers = {"content-type": "application/json" if content is None else "application/octet-stream"}
    return result


def xlsx():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("[Content_Types].xml", "test")
        z.writestr("xl/workbook.xml", "test")
    return stream.getvalue()


class ExportFlowTests(unittest.TestCase):
    def setUp(self):
        self.exporter = load_exporter()
        self.task = build_task("city", "http://example.test", "2026-08-01", "2026-08-31")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sleep = patch.object(self.exporter.time, "sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def run_export(self):
        return self.exporter.run_export(self.task, {}, {}, self.temp.name,
            "2026-08-01", "2026-08-31", 120, poll_timeout=20)

    def configure(self, downloads):
        self.exporter.requests.get.side_effect = [response({"code":200}), *downloads]
        self.exporter.requests.post.side_effect = [response({"code":200,"result":"temp-new"}),
                                                   response({"code":200,"result":"job-new"})]

    def test_entire_sequence(self):
        self.configure([response(content=xlsx())])
        path, kind = self.run_export()
        self.assertEqual(kind,"xlsx")
        self.assertTrue(Path(path).exists())
        posts = self.exporter.requests.post.call_args_list
        cache = json.loads(posts[0].kwargs["data"])
        dates = next(c for c in cache["data"]["state"]["components"] if c["type"]=="dateTimeFilter")
        self.assertEqual(dates["setting"]["data"]["date"]["period"]["minBound"],"2026-08-01 00:00:00")
        self.assertEqual(json.loads(posts[1].kwargs["data"])["tempQueryId"], "temp-new")
        self.assertTrue(self.exporter.requests.get.call_args_list[-1].args[0].endswith("download?id=job-new"))

    def test_cache_auth_error_is_actionable(self):
        self.configure([])
        self.exporter.requests.post.side_effect = [response({"code":610,"message":"expired"})]
        with self.assertRaisesRegex(RuntimeError,"stage=setCache.*code=610"):
            self.run_export()

    def test_flush_error_is_actionable(self):
        self.exporter.requests.get.return_value = response({"code":403,"message":"denied"},403)
        with self.assertRaisesRegex(RuntimeError,"stage=flushReport.*HTTP=403"):
            self.run_export()
        self.exporter.requests.post.assert_not_called()

    def test_download_auth_stops_polling(self):
        self.configure([response({"code":610})])
        with self.assertRaisesRegex(RuntimeError,"stage=download.*code=610"):
            self.run_export()
        self.assertEqual(self.exporter.requests.get.call_count,2)

    def test_task_list_does_not_take_unrelated_file(self):
        self.configure([response({"code":500}),response(content=xlsx())])
        self.exporter.requests.post.side_effect = [response({"code":200,"result":"temp-new"}),
            response({"code":200,"result":"job-new"}),
            response({"result":[{"id":"someone-else","link":"http://wrong.test/file"}]})]
        self.run_export()
        self.assertEqual(self.exporter.requests.get.call_count,3)
        self.assertTrue(all("wrong.test" not in c.args[0] for c in self.exporter.requests.get.call_args_list))

    def test_timeout_diagnostic(self):
        self.configure([response({"code":200}),response({"code":200})])
        with self.assertRaisesRegex(RuntimeError,"stage=timeout"):
            self.run_export()

    def test_direct_file_export_supported(self):
        self.configure([])
        self.exporter.requests.post.side_effect = [response({"result":"temp-new"}),response(content=xlsx())]
        self.assertEqual(self.run_export()[1],"xlsx")

    def test_error_redacts_auth(self):
        msg = self.exporter.export_failure(response({"code":610,"message":"secret-cookie secret-token"}),
            {"stage":"setCache"},{"cookie":"SESSION=secret-cookie","x-csrf-token":"secret-token"})
        self.assertNotIn("secret-cookie",msg)
        self.assertNotIn("secret-token",msg)


if __name__ == "__main__":
    unittest.main()
