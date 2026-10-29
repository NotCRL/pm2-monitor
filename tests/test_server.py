"""End-to-end checks of the HTTP layer on a throw-away server and config."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import server
from pm2monitor.service import Monitor
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
            return e.code, e.read()

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

    def test_domain_can_be_created_and_listed(self):
        status, _ = self.request("/api/config", {"op": "createDomain", "name": "backend"})
        self.assertEqual(status, 200)
        state = json.loads(self.request("/api/state")[1])
        self.assertIn("backend", [d["name"] for d in state["domains"]])


if __name__ == "__main__":
    unittest.main()
