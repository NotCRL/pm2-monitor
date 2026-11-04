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
from pm2monitor import control, notifier, service
from pm2monitor.service import ActionError, Monitor
from pm2monitor.store import ConfigStore


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        # No discovery: the test must not touch whatever pm2 daemons the machine has.
        with mock.patch("pm2monitor.service.discover_homes", return_value=[]):
            server.monitor = Monitor(ConfigStore(cls.tmp.name))
        server.event_log = notifier.EventLog()
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
        self.assertEqual({"os", "home", "node", "npm", "pm2", "pm2Home", "monitorFolder"}, set(report))
        self.assertIn(report["os"], ("windows", "macos", "linux"))

    def test_browse_and_inspect_a_folder(self):
        project = tempfile.mkdtemp(dir=self.tmp.name)
        with open(project + "/package.json", "w") as f:
            json.dump({"name": "demo", "scripts": {"start": "x"}}, f)
        listing = json.loads(self.request("/api/browse?path=" + urllib.parse.quote(self.tmp.name))[1])
        self.assertIn(project, [f["path"] for f in listing["folders"]])
        suggestion = json.loads(self.request("/api/inspect?path=" + urllib.parse.quote(project))[1])
        self.assertEqual((suggestion["name"], suggestion["command"]), ("demo", "npm start"))

    def test_browse_can_show_hidden_folders(self):
        project = tempfile.mkdtemp(dir=self.tmp.name, prefix=".hid")
        shown = json.loads(self.request("/api/browse?path=" + urllib.parse.quote(self.tmp.name) + "&hidden=1")[1])
        hidden = json.loads(self.request("/api/browse?path=" + urllib.parse.quote(self.tmp.name))[1])
        self.assertIn(project, [f["path"] for f in shown["folders"]])
        self.assertNotIn(project, [f["path"] for f in hidden["folders"]])

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

    def test_state_carries_the_notification_catalogue(self):
        state = json.loads(self.request("/api/state")[1])
        self.assertEqual(state["eventTypes"], notifier.EVENT_TYPES)
        self.assertEqual(state["notifyDefault"], notifier.DEFAULT_NOTIFY)

    def test_notification_settings_are_saved_per_domain_and_cleaned(self):
        self.request("/api/config", {"op": "createDomain", "name": "shop"})
        status, _ = self.request("/api/config", {"op": "setNotify", "scope": "shop",
                                                  "settings": {"levels": ["info", "bogus"], "memoryMb": "256"}})
        self.assertEqual(status, 200)
        shop = next(d for d in json.loads(self.request("/api/state")[1])["domains"] if d["name"] == "shop")
        self.assertEqual((shop["notify"]["levels"], shop["notify"]["memoryMb"]), (["info"], 256))
        status, body = self.request("/api/config", {"op": "setNotify", "scope": "missing", "settings": {}})
        self.assertEqual((status, json.loads(body)["error"]), (400, "unknown_domain"))

    def test_events_can_be_read_incrementally_and_cleared(self):
        first = server.event_log.add({"type": "process_crashed", "severity": "error"})
        server.event_log.add({"type": "process_stopped", "severity": "warning"})
        listing = json.loads(self.request(f"/api/events?after={first['id']}")[1])
        self.assertEqual([e["type"] for e in listing["events"]], ["process_stopped"])
        self.assertEqual(listing["last"], server.event_log.latest_id())
        self.request("/api/events/clear", {})
        self.assertEqual(json.loads(self.request("/api/events?after=0")[1])["events"], [])

    def test_desktop_test_reports_a_missing_tool_as_a_code(self):
        with mock.patch.object(notifier, "send_desktop", return_value=(False, "no_tool")):
            status, body = self.request("/api/notify/test", {})
        self.assertEqual((status, json.loads(body)["error"]), (400, "desktop_unavailable"))
        with mock.patch.object(notifier, "send_desktop", return_value=(True, "")):
            self.assertEqual(self.request("/api/notify/test", {})[0], 200)

    def test_language_is_remembered_for_desktop_messages(self):
        self.request("/api/config", {"op": "setLanguage", "language": "it"})
        self.assertEqual(json.loads(self.request("/api/state")[1])["language"], "it")
        self.request("/api/config", {"op": "setLanguage", "language": "xx"})  # unknown: ignored
        self.assertEqual(json.loads(self.request("/api/state")[1])["language"], "it")

    def test_ping_identifies_the_monitor(self):
        status, body = self.request("/api/ping")
        self.assertEqual((status, json.loads(body)["app"]), (200, "pm2-monitor"))
        self.assertEqual(control.running_version(self.httpd.server_port), json.loads(body)["version"])

    def test_shutdown_turns_the_server_off_and_answers_first(self):
        other = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)   # a second server: the shared one must stay up
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        port = other.server_port
        self.assertTrue(control.running_version(port))
        self.assertTrue(control.request_shutdown(port))
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        other.server_close()
        self.assertIsNone(control.running_version(port))
        self.assertFalse(control.request_shutdown(port))   # nothing left to stop

    def test_shutdown_refuses_requests_from_other_sites(self):
        status, _ = self.request("/api/shutdown", {}, headers={"Origin": "http://evil.example"})
        self.assertEqual(status, 403)
        self.assertTrue(control.running_version(self.httpd.server_port))

    def test_open_folder_reads_only_the_key_never_a_path(self):
        with mock.patch.object(service, "open_in_file_manager") as opener:
            status, body = self.request("/api/open-folder", {"key": "ghost/x", "path": "/etc", "folder": "/etc"})
        self.assertEqual((status, json.loads(body)["error"]), (400, "unknown_daemon"))
        opener.assert_not_called()

    def test_the_state_tells_the_home_folder_for_shortening_paths(self):
        self.assertTrue(json.loads(self.request("/api/state")[1])["home"])

    def test_domain_can_be_created_and_listed(self):
        status, _ = self.request("/api/config", {"op": "createDomain", "name": "backend"})
        self.assertEqual(status, 200)
        state = json.loads(self.request("/api/state")[1])
        self.assertIn("backend", [d["name"] for d in state["domains"]])


if __name__ == "__main__":
    unittest.main()
