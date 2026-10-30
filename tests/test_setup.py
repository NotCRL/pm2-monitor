"""Guided setup: diagnosis, project suggestions, validation and the pm2 install fallback."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pm2monitor import setup
from pm2monitor.service import ActionError
from pm2monitor.store import ConfigStore


def make_monitor(pm2_path="/bin/pm2", store_dir=None):
    return SimpleNamespace(pm2_path=pm2_path, store=ConfigStore(store_dir or tempfile.mkdtemp()),
                           refresh_pm2=lambda: pm2_path)


class SuggestCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_npm_start_script(self):
        (self.dir / "package.json").write_text(json.dumps({"name": "@shop/web", "scripts": {"start": "x"}}))
        self.assertEqual(setup.suggest_command(self.dir), {"name": "shop-web", "command": "npm start", "kind": "npm"})

    def test_node_entry_file_without_start_script(self):
        (self.dir / "package.json").write_text(json.dumps({"name": "api", "main": "src.js"}))
        (self.dir / "src.js").write_text("")
        self.assertEqual(setup.suggest_command(self.dir)["command"], "node src.js")

    def test_python_app(self):
        (self.dir / "app.py").write_text("")
        suggestion = setup.suggest_command(self.dir)
        self.assertEqual(suggestion["kind"], "python")
        self.assertTrue(suggestion["command"].endswith("app.py"))

    def test_unknown_project_gives_empty_command(self):
        self.assertEqual(setup.suggest_command(self.dir)["command"], "")

    def test_broken_package_json_does_not_crash(self):
        (self.dir / "package.json").write_text("{not json")
        self.assertEqual(setup.suggest_command(self.dir)["command"], "")

    def test_missing_folder(self):
        with self.assertRaises(ActionError) as caught:
            setup.suggest_command(self.dir / "nope")
        self.assertEqual(caught.exception.code, "folder_not_found")


class FolderListTest(unittest.TestCase):
    def test_lists_only_visible_folders_with_full_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("beta", "Alpha", ".hidden"):
                Path(tmp, name).mkdir()
            Path(tmp, "file.txt").write_text("")
            result = setup.list_folders(tmp)
        self.assertEqual([f["name"] for f in result["folders"]], ["Alpha", "beta"])
        self.assertTrue(result["folders"][0]["path"].endswith("Alpha"))
        self.assertTrue(result["parent"])


class LaunchTest(unittest.TestCase):
    def test_node_command_drops_the_interpreter_word(self):
        self.assertEqual(setup._pm2_launch(["node", "app.js", "--port", "3"]), ("app.js", ["--port", "3"], []))

    def test_python_command_uses_it_as_interpreter(self):
        self.assertEqual(setup._pm2_launch(["python3", "app.py"]), ("app.py", [], ["--interpreter", "python3"]))

    def test_npm_command_is_kept(self):
        self.assertEqual(setup._pm2_launch(["npm", "start"]), ("npm", ["start"], []))


class AddProcessValidationTest(unittest.TestCase):
    """Every check happens before pm2 is called, so these never start anything."""

    def code(self, **overrides):
        args = {"name": "web", "folder": tempfile.gettempdir(), "command": "npm start", **overrides}
        with self.assertRaises(ActionError) as caught:
            setup.add_process(make_monitor(), args["name"], args["folder"], args["command"])
        return caught.exception.code

    def test_bad_name(self):
        self.assertEqual(self.code(name="-web"), "bad_process_name")
        self.assertEqual(self.code(name="my app"), "bad_process_name")

    def test_missing_folder(self):
        self.assertEqual(self.code(folder="/definitely/not/here"), "folder_not_found")

    def test_empty_and_broken_commands(self):
        self.assertEqual(self.code(command="  "), "empty_command")
        self.assertEqual(self.code(command='npm "start'), "bad_command")

    def test_pm2_missing(self):
        with self.assertRaises(ActionError) as caught:
            setup.add_process(make_monitor(pm2_path=None), "web", tempfile.gettempdir(), "npm start")
        self.assertEqual(caught.exception.code, "pm2_not_found")


class DefaultDaemonTest(unittest.TestCase):
    def test_registered_once_and_unhidden(self):
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {"PM2_HOME": home}):
                monitor = make_monitor()
                first = setup.ensure_default_daemon(monitor)
                monitor.store.update_daemon(first, hidden=True)
                second = setup.ensure_default_daemon(monitor)
                self.assertEqual(first, second)
                self.assertFalse(monitor.store.data["daemons"][first]["hidden"])
                self.assertEqual(len(monitor.store.data["daemons"]), 1)


class InstallPm2Test(unittest.TestCase):
    def run_job(self, results, found_after=True):
        monitor = SimpleNamespace(refresh_pm2=lambda: "/x/pm2" if found_after else None)
        job = {"state": "running", "output": "", "fallback": False, "error": None}
        with mock.patch.object(setup, "_npm_install", side_effect=results) as install:
            setup._run_install(monitor, job, "/x/npm")
        return job, install

    @staticmethod
    def result(code, text=""):
        return SimpleNamespace(returncode=code, stdout=text, stderr="")

    def test_success(self):
        job, install = self.run_job([self.result(0, "added 1 package")])
        self.assertEqual((job["state"], job["fallback"], install.call_count), ("done", False, 1))

    def test_permission_error_retries_in_the_home_folder(self):
        job, install = self.run_job([self.result(1, "npm ERR! EACCES"), self.result(0)])
        self.assertEqual((job["state"], job["fallback"], install.call_count), ("done", True, 2))
        self.assertIn("--prefix", install.call_args_list[1][0][1])

    def test_other_failure_is_reported_without_retry(self):
        job, install = self.run_job([self.result(1, "network down")])
        self.assertEqual((job["state"], job["error"], install.call_count), ("failed", "install_failed", 1))

    def test_installed_but_not_found(self):
        job, _ = self.run_job([self.result(0)], found_after=False)
        self.assertEqual((job["state"], job["error"]), ("failed", "pm2_missing_after_install"))


class DoctorTest(unittest.TestCase):
    def test_reports_what_is_missing(self):
        with mock.patch.object(setup, "find_node", return_value=None), mock.patch.object(setup, "find_npm", return_value=None):
            report = setup.doctor(make_monitor(pm2_path=None))
        self.assertEqual((report["node"]["path"], report["npm"]["path"], report["pm2"]["path"]), (None, None, None))
        self.assertIn(report["os"], ("windows", "macos", "linux"))


if __name__ == "__main__":
    unittest.main()
