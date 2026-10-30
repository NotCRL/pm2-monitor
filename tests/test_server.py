"""End-to-end checks of the HTTP layer on a throw-away server and config."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import server
from pm2monitor.service import ActionError, Monitor
from pm2monitor.store import ConfigStore


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        # No discovery: the test must not touch whatever pm2 daemons the machine has.
        with mock.patch("pm2monitor.service.discover_homes", return_value=[]):
            server.monitor = Monitor(ConfigStore(cls.tmp.name))
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def request(self, path, body=None, headers=None, content_type="application/json"):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=dict(headers or {}))
        if data is not None:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read()
            finally:
                e.close()

    def test_page_is_served(self):
        status, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"pm2 monitor", body)

    def test_state_has_version_and_empty_lists(self):
        status, body = self.request("/api/state")
        state = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual((state["daemons"], state["procs"]), ([], []))
        self.assertRegex(state["version"], r"^\d+\.\d+\.\d+$")

    def test_foreign_host_is_rejected(self):
        status, _ = self.request("/api/state", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_post_from_another_site_is_rejected(self):
        status, _ = self.request("/api/config", {"op": "scan"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_post_without_json_content_type_is_rejected(self):
        status, _ = self.request("/api/config", {"op": "scan"}, content_type="text/plain")
        self.assertEqual(status, 403)

    def test_errors_are_codes_with_params(self):
        status, body = self.request("/api/action", {"key": "nope/x", "action": "stop"})
        error = json.loads(body)
        self.assertEqual((status, error["ok"], error["error"], error["params"]), (400, False, "unknown_daemon", {"id": "nope"}))

    def test_setup_report_has_the_tools_and_the_os(self):
        report = json.loads(self.request("/api/setup")[1])
        self.assertEqual({"os", "home", "node", "npm", "pm2", "pm2Home"}, set(report))
        self.assertIn(report["os"], ("windows", "macos", "linux"))

    def test_browse_and_inspect_a_folder(self):
        project = tempfile.mkdtemp(dir=self.tmp.name)
        with open(project + "/package.json", "w") as f:
            json.dump({"name": "demo", "scripts": {"start": "x"}}, f)
        listing = json.loads(self.request("/api/browse?path=" + urllib.parse.quote(self.tmp.name))[1])
        self.assertIn(project, [f["path"] for f in listing["folders"]])
        suggestion = json.loads(self.request("/api/inspect?path=" + urllib.parse.quote(project))[1])
        self.assertEqual((suggestion["name"], suggestion["command"]), ("demo", "npm start"))

    def test_setup_errors_are_codes(self):
        status, body = self.request("/api/inspect?path=/definitely/not/here")
        self.assertEqual((status, json.loads(body)["error"]), (400, "folder_not_found"))
        status, body = self.request("/api/setup/add-process", {"name": "no good", "folder": "/tmp", "command": "x"})
        self.assertEqual((status, json.loads(body)["error"]), (400, "bad_process_name"))

    def test_error_params_may_be_named_like_the_http_status(self):
        """process_failed carries a 'status' param: it must reach the UI, not clash with the HTTP status."""
        failure = ActionError("process_failed", status="errored", log="boom")
        with mock.patch.object(server.monitor, "perform", side_effect=failure):
            status, body = self.request("/api/action", {"key": "x/y", "action": "start"})
        error = json.loads(body)
        self.assertEqual((status, error["error"], error["params"]), (400, "process_failed", {"status": "errored", "log": "boom"}))

    def test_domain_can_be_created_and_listed(self):
        status, _ = self.request("/api/config", {"op": "createDomain", "name": "backend"})
        self.assertEqual(status, 200)
        state = json.loads(self.request("/api/state")[1])
        self.assertIn("backend", [d["name"] for d in state["domains"]])


if __name__ == "__main__":
    unittest.main()
