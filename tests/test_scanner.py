"""What the scanner proposes for different kinds of project. Tools and Javas are stand-ins: nothing is run."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm2monitor import scanner, setup


class ScannerTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.jdks = [{"home": "/opt/j8", "major": 8, "jdk": True}, {"home": "/opt/j17", "major": 17, "jdk": True}]
        self.missing = set()
        for patcher in (mock.patch.object(scanner.jdk, "installed_jdks", side_effect=lambda: self.jdks),
                        mock.patch.object(scanner, "tool_available", side_effect=lambda token, *a, **k: Path(token).name not in self.missing)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, name, text=""):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def commands(self):
        return [c["command"] for c in scanner.suggest_command(self.dir)["candidates"]]

    def test_the_projects_own_maven_wrapper_beats_a_global_mvn(self):
        self.write("pom.xml", "<parent>spring-boot</parent><java.version>1.8</java.version>")
        self.write("mvnw")
        self.assertEqual(self.commands(), ["./mvnw spring-boot:run"])

    def test_a_default_goal_in_the_pom_means_the_wrapper_alone(self):
        self.write("pom.xml", "<parent>spring-boot</parent><defaultGoal>spring-boot:run</defaultGoal>")
        self.write("mvnw")
        self.write("src/main/resources/application-dev.yml")
        self.assertEqual(self.commands(), ["./mvnw"])

    def test_without_wrapper_plain_mvn_with_the_development_profile(self):
        self.write("pom.xml", "<parent>spring-boot</parent>")
        self.write("src/main/resources/application-dev.yml")
        self.assertEqual(self.commands(), ["mvn spring-boot:run -Dspring-boot.run.profiles=dev"])

    def test_a_jhipster_archive_runs_with_dev_and_swagger(self):
        self.write(".yo-rc.json", "{}")
        self.write("src/main/resources/config/application-dev.yml")
        self.write("target/app-1.0.war")
        self.assertEqual(self.commands()[0], "java -Dspring.profiles.active=dev,swagger -Dfile.encoding=UTF-8 -jar target/app-1.0.war")

    def test_the_java_version_is_matched_and_reported(self):
        self.write("pom.xml", "<parent>spring-boot</parent><java.version>1.8</java.version>")
        java = scanner.suggest_command(self.dir)["candidates"][0]["java"]
        self.assertEqual((java["required"], java["major"], java["home"], java["exact"]), (8, 8, "/opt/j8", True))
        self.jdks = [{"home": "/opt/j17", "major": 17, "jdk": True}]
        self.assertFalse(scanner.suggest_command(self.dir)["candidates"][0]["java"]["exact"])

    def test_a_java_that_is_not_installed_is_flagged(self):
        self.write("pom.xml", "<parent>spring-boot</parent><java.version>11</java.version>")
        self.jdks = [{"home": "/opt/j8", "major": 8, "jdk": True}]
        result = scanner.suggest_command(self.dir)
        self.assertEqual(result["notes"], [{"note": "java_missing", "params": {"version": 11}}])

    def test_a_java_server_with_web_tooling_starts_the_server_first(self):
        self.write("pom.xml", "<parent>spring-boot</parent>")
        self.write("src/main/java/Main.java")
        self.write("mvnw")
        self.write("package.json", json.dumps({"scripts": {"start": "webpack"}}))
        self.assertEqual(self.commands(), ["./mvnw spring-boot:run", "npm start"])

    def test_fastapi_uses_the_projects_python_and_the_source_folder(self):
        self.write("pyproject.toml", 'dependencies = ["fastapi", "uvicorn"]')
        self.write("src/shop/main.py", "def make():\n    return FastAPI()\n\napp = make()\n")
        venv = self.write(".venv/bin/python")
        with mock.patch.object(scanner, "IS_WINDOWS", False):
            self.assertEqual(self.commands()[0], f"{venv} -m uvicorn shop.main:app --app-dir src")

    def test_flask_and_packages_with_a_main_module(self):
        self.write("app.py", "from flask import Flask\napp = Flask(__name__)\n")
        self.write("tool/__init__.py")
        self.write("tool/__main__.py")
        commands = self.commands()
        self.assertTrue(any(c.endswith("-m flask --app app run") for c in commands))
        self.assertTrue(any(c.endswith("-m tool") for c in commands))

    def test_makefile_start_targets_but_not_the_other_ones(self):
        self.write("Makefile", ".PHONY: up avvia test\nup:\n\tdocker compose up\navvia:\n\tuvicorn x\ntest:\n\tpytest\n")
        self.assertEqual(self.commands(), ["make avvia"])

    def test_docker_compose_is_a_note_never_a_candidate(self):
        self.write("docker-compose.yml")
        self.write("server.js")
        result = scanner.suggest_command(self.dir)
        self.assertEqual([n["note"] for n in result["notes"]], ["services"])
        self.assertNotIn("docker", " ".join(c["command"] for c in result["candidates"]))

    def test_commands_whose_tool_is_missing_go_last_and_are_marked(self):
        self.write("package.json", json.dumps({"scripts": {"start": "x"}}))
        self.write("server.py")
        self.missing = {"npm"}
        candidates = scanner.suggest_command(self.dir)["candidates"]
        self.assertEqual([(c["command"].split()[-1], c["available"]) for c in candidates], [("server.py", True), ("start", False)])

    def test_auto_start_skips_missing_tools_and_says_so_when_nothing_is_left(self):
        self.write("package.json", json.dumps({"scripts": {"start": "x"}}))
        self.missing = {"npm"}
        with mock.patch.object(setup, "add_process") as start, self.assertRaises(setup.ActionError) as caught:
            setup.auto_start(mock.Mock(), self.dir)
        start.assert_not_called()
        self.assertEqual((caught.exception.code, caught.exception.params["missing"], caught.exception.params["tried"]), ("auto_start_failed", ["npm start"], []))


class LaunchTest(unittest.TestCase):
    def test_python_dash_m_runs_the_interpreter_itself(self):
        self.assertEqual(setup._pm2_launch(["/p/python", "-m", "uvicorn", "a:app"]), ("/p/python", ["-m", "uvicorn", "a:app"], []))

    def test_on_windows_batch_files_and_npm_go_through_cmd(self):
        with mock.patch.object(setup, "IS_WINDOWS", True):
            self.assertEqual(setup._pm2_launch(["mvnw.cmd", "spring-boot:run"]), ("cmd", ["/c", "mvnw.cmd", "spring-boot:run"], []))
            self.assertEqual(setup._pm2_launch(["npm", "start"]), ("cmd", ["/c", "npm", "start"], []))
            self.assertEqual(setup._pm2_launch(["java", "-jar", "a.war"]), ("java", ["-jar", "a.war"], ["--interpreter", "none"]))

    def test_programs_are_run_as_programs_not_as_javascript(self):
        for tokens in (["./mvnw"], ["npm", "start"], ["make", "avvia"], ["/jdk/bin/java", "-jar", "a.war"]):
            self.assertEqual(setup._pm2_launch(tokens)[2], ["--interpreter", "none"], tokens)
        for tokens in (["server.js"], ["./start.sh"]):
            self.assertEqual(setup._pm2_launch(tokens)[2], [], tokens)

    def test_the_chosen_java_reaches_pm2(self):
        from pm2monitor.service import Monitor
        from pm2monitor.store import ConfigStore
        with mock.patch("pm2monitor.service.discover_homes", return_value=[]):
            monitor = Monitor(ConfigStore(tempfile.mkdtemp()))
        monitor.pm2_path = "/bin/pm2"
        monitor.store.register_daemon("d", tempfile.mkdtemp())
        with mock.patch("pm2monitor.service.subprocess.run") as run:
            monitor.run_pm2("d", ["list"], env_extra={"JAVA_HOME": "/opt/j8"})
        self.assertEqual(run.call_args.kwargs["env"]["JAVA_HOME"], "/opt/j8")


if __name__ == "__main__":
    unittest.main()
