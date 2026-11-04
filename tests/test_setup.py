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
        suggestion = setup.suggest_command(self.dir)
        self.assertEqual((suggestion["name"], suggestion["command"], suggestion["kind"]), ("shop-web", "npm start", "npm"))

    def test_node_entry_file_without_start_script(self):
        (self.dir / "package.json").write_text(json.dumps({"name": "api", "main": "src.js"}))
        (self.dir / "src.js").write_text("")
        self.assertEqual(setup.suggest_command(self.dir)["command"], "node src.js")

    def test_a_project_offers_every_way_to_start_it_most_likely_first(self):
        (self.dir / "package.json").write_text(json.dumps({"name": "site", "scripts": {"dev": "x", "start": "y"}}))
        (self.dir / "server.js").write_text("")
        (self.dir / "app.py").write_text("")
        commands = [c["command"] for c in setup.suggest_command(self.dir)["candidates"]]
        self.assertEqual(commands[:3], ["npm start", "npm run dev", "node server.js"])
        self.assertIn(commands[-1], ("python3 app.py", "python app.py"))

    def test_java_archives_are_found_where_build_tools_leave_them_and_quoted_when_needed(self):
        (self.dir / "target").mkdir()
        (self.dir / "target" / "my app.jar").write_text("")
        (self.dir / "target" / "my app-sources.jar").write_text("")
        (self.dir / "pom.xml").write_text("")
        candidates = setup.suggest_command(self.dir)["candidates"]
        self.assertEqual([(c["kind"], c["command"]) for c in candidates],
                         [("java", 'java -jar "target/my app.jar"'), ("maven", "mvn spring-boot:run")])

    def test_start_scripts_and_django(self):
        (self.dir / "manage.py").write_text("")
        (self.dir / "start.sh").write_text("")
        (self.dir / "run.bat").write_text("")
        kinds = {c["kind"]: c["command"] for c in setup.suggest_command(self.dir)["candidates"]}
        self.assertTrue(kinds["django"].endswith("manage.py runserver"))
        self.assertEqual(kinds["script"], "./start.sh")          # the .bat is for Windows only

    def test_there_are_never_more_than_six_candidates(self):
        (self.dir / "package.json").write_text(json.dumps({"scripts": {"start": "a", "dev": "b", "serve": "c"}}))
        for name in ("server.js", "app.js", "index.js", "main.py", "app.py"):
            (self.dir / name).write_text("")
        self.assertEqual(len(setup.suggest_command(self.dir)["candidates"]), 6)

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


class AutoStartTest(unittest.TestCase):
    """add_process is replaced, so nothing is really started."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "package.json").write_text(json.dumps({"name": "shop", "scripts": {"start": "x", "dev": "y"}}))

    def run_auto(self, outcomes, name=None):
        """outcomes: one result per call, either a dict (works) or an ActionError (raised)."""
        calls = []

        def fake(monitor, process_name, folder, command):
            calls.append((process_name, command))
            outcome = outcomes[len(calls) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with mock.patch.object(setup, "add_process", side_effect=fake):
            try:
                return setup.auto_start(make_monitor(), self.dir, name), calls
            except ActionError as error:
                return error, calls

    def test_the_first_command_that_works_is_used(self):
        result, calls = self.run_auto([{"key": "d/shop", "status": "online"}])
        self.assertEqual((result["name"], result["command"], result["failed"]), ("shop", "npm start", []))
        self.assertEqual(calls, [("shop", "npm start")])

    def test_failed_commands_are_skipped_and_reported(self):
        failure = ActionError("process_failed", status="errored", log="boom")
        result, calls = self.run_auto([failure, {"key": "d/shop", "status": "online"}])
        self.assertEqual(result["command"], "npm run dev")
        self.assertEqual(result["failed"], [{"command": "npm start", "status": "errored", "log": "boom"}])

    def test_a_taken_name_gets_a_number_and_the_same_command_is_kept(self):
        result, calls = self.run_auto([ActionError("process_exists", name="shop"), {"key": "d/shop-2", "status": "online"}])
        self.assertEqual(calls, [("shop", "npm start"), ("shop-2", "npm start")])
        self.assertEqual(result["name"], "shop-2")

    def test_when_nothing_works_every_attempt_is_returned(self):
        failure = ActionError("process_failed", status="errored", log="x")
        error, calls = self.run_auto([failure, failure])
        self.assertEqual(error.code, "auto_start_failed")
        self.assertEqual([a["command"] for a in error.params["tried"]], ["npm start", "npm run dev"])

    def test_an_error_no_other_command_could_fix_stops_at_once(self):
        error, calls = self.run_auto([ActionError("pm2_not_found")])
        self.assertEqual((error.code, len(calls)), ("pm2_not_found", 1))

    def test_a_folder_without_anything_to_start(self):
        (self.dir / "package.json").unlink()
        error, calls = self.run_auto([])
        self.assertEqual((error.code, calls), ("no_command_found", []))


class SplitCommandTest(unittest.TestCase):
    def test_quotes_keep_a_name_with_spaces_together(self):
        self.assertEqual(setup.split_command('java -jar "my app.jar"'), ["java", "-jar", "my app.jar"])

    def test_on_windows_the_quotes_are_not_passed_to_the_program(self):
        with mock.patch.object(setup, "IS_WINDOWS", True):
            self.assertEqual(setup.split_command('java -jar "my app.jar" --port=80'), ["java", "-jar", "my app.jar", "--port=80"])

    def test_unbalanced_quotes_are_refused(self):
        with self.assertRaises(ActionError) as caught:
            setup.split_command('npm "start')
        self.assertEqual(caught.exception.code, "bad_command")


class FolderListTest(unittest.TestCase):
    def test_hidden_folders_are_optional_and_pm2_homes_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".pm2").mkdir()
            Path(tmp, ".pm2", "dump.pm2").write_text("[]")
            Path(tmp, ".cache").mkdir()
            Path(tmp, "app").mkdir()
            plain = setup.list_folders(tmp)
            everything = setup.list_folders(tmp, hidden=True)
            inside = setup.list_folders(str(Path(tmp, ".pm2")), hidden=True)
        self.assertEqual([f["name"] for f in plain["folders"]], ["app"])
        self.assertEqual([(f["name"], f["pm2"]) for f in everything["folders"]], [(".cache", False), (".pm2", True), ("app", False)])
        self.assertEqual((plain["isPm2Home"], inside["isPm2Home"]), (False, True))

    def test_pm2_data_folders_are_offered_as_places(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home, ".pm2-work").mkdir()
            Path(home, ".pm2-work", "pm2.pid").write_text("1")
            Path(home, ".pm2-empty").mkdir()           # no pm2 files inside: not a pm2 home
            with mock.patch.object(setup, "HOME", Path(home)):
                places = setup._places()
        self.assertEqual([(p["name"], p.get("pm2", False)) for p in places[1:]], [(".pm2-work", True)])

    def test_places_start_with_home_and_have_no_duplicates(self):
        with tempfile.TemporaryDirectory() as home:
            Path(home, "Projects").mkdir()
            with mock.patch.object(setup, "HOME", Path(home)):
                places = setup._places()
        self.assertEqual([p["home"] for p in places], [True, False])
        self.assertTrue(places[1]["path"].endswith("Projects"))

    def test_places_use_the_folder_names_of_the_users_language(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / ".config").mkdir()
            (Path(home) / ".config" / "user-dirs.dirs").write_text(
                'XDG_DESKTOP_DIR="$HOME/Bureau"\nXDG_MUSIC_DIR="$HOME/Musique"\nXDG_DOWNLOAD_DIR="$HOME/Telechargements"\n')
            for name in ("Bureau", "Musique"):
                (Path(home) / name).mkdir()
            with mock.patch.object(setup, "HOME", Path(home)):
                names = [p["name"] for p in setup._places()]
        self.assertEqual(names[1:], ["Bureau"])  # Musique is not a project place; Telechargements does not exist

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
