"""Types (backend / frontend / your own) and labels: the guess, the stored data, the operations and their errors."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm2monitor import classify, service
from pm2monitor.service import ActionError
from pm2monitor.store import ConfigStore


def project(dependencies=None, dev=None, scripts=None):
    folder = tempfile.mkdtemp()
    Path(folder, "package.json").write_text(json.dumps({"dependencies": dependencies or {}, "devDependencies": dev or {}, "scripts": scripts or {}}))
    return folder


class GuessKindTest(unittest.TestCase):
    def test_programs_that_only_make_sense_on_a_server(self):
        for script, args in (("/usr/bin/java", ["-jar", "app.war"]), ("/x/dotnet", []), ("/usr/bin/python3", ["app.py"]), ("app.jar", [])):
            self.assertEqual(classify.guess_kind({"script": script, "args": args}), "backend", script)

    def test_a_java_archive_started_through_an_interpreter_is_a_backend(self):
        self.assertEqual(classify.guess_kind({"script": "/bin/sh", "args": ["-c", "run.sh app.jar"]}), "backend")

    def test_react_and_angular_projects_are_frontends(self):
        react = {"script": "npm", "args": ["start"], "cwd": project({"react": "18", "react-dom": "18"}, {"react-scripts": "5"}, {"start": "react-scripts start"})}
        self.assertEqual(classify.guess_kind(react), "frontend")
        angular = {"script": "npm", "cwd": project({"@angular/core": "17"}, scripts={"start": "ng serve"})}
        self.assertEqual(classify.guess_kind(angular), "frontend")

    def test_express_and_nest_projects_are_backends(self):
        self.assertEqual(classify.guess_kind({"script": "node", "cwd": project({"express": "4"})}), "backend")
        self.assertEqual(classify.guess_kind({"script": "npm", "cwd": project({"@nestjs/core": "10"})}), "backend")

    def test_a_dev_server_in_the_start_script_wins_over_server_packages(self):
        mixed = {"script": "npm", "cwd": project({"express": "4", "react": "18"}, scripts={"start": "vite --port 3000"})}
        self.assertEqual(classify.guess_kind(mixed), "frontend")

    def test_no_clear_answer_is_none(self):
        self.assertIsNone(classify.guess_kind(None))
        self.assertIsNone(classify.guess_kind({"script": "npm", "cwd": tempfile.mkdtemp()}))
        self.assertIsNone(classify.guess_kind({"script": "npm", "cwd": project({"react": "18", "express": "4"})}))   # both: do not guess
        self.assertIsNone(classify.guess_kind({"script": "npm", "cwd": project({"lodash": "4"})}))

    def test_a_broken_package_json_does_not_crash(self):
        folder = tempfile.mkdtemp()
        Path(folder, "package.json").write_text("{not json")
        self.assertIsNone(classify.guess_kind({"script": "npm", "cwd": folder}))

    def test_the_guess_follows_the_file_when_it_changes(self):
        folder = project({"express": "4"})
        self.assertEqual(classify.guess_kind({"script": "node", "cwd": folder}), "backend")
        Path(folder, "package.json").write_text(json.dumps({"dependencies": {"vue": "3"}}))
        Path(folder, "package.json").touch()
        self.assertEqual(classify.guess_kind({"script": "node", "cwd": folder}), "frontend")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = ConfigStore(tempfile.mkdtemp())

    def test_custom_kinds_cannot_repeat_a_builtin_or_each_other(self):
        self.assertEqual(self.store.add_kind("  worker   queue "), "worker queue")
        for clash in ("Backend", "FRONTEND", "Worker Queue"):
            with self.assertRaises(ValueError):
                self.store.add_kind(clash)
        self.assertEqual(self.store.all_kinds(), ["backend", "frontend", "worker queue"])

    def test_names_are_validated(self):
        for bad in ("", "   ", "x" * 31, "bad\x01name"):
            with self.assertRaises(ValueError):
                self.store.add_label(bad)
        self.assertEqual(self.store.add_label("tab\there"), "tab here")      # whitespace is tidied, not refused

    def test_renaming_and_deleting_a_kind_updates_the_processes(self):
        self.store.add_kind("worker")
        self.store.set_kind("d/a", "worker")
        self.store.rename_kind("worker", "job")
        self.assertEqual(self.store.data["processes"]["d/a"]["kind"], "job")
        self.store.delete_kind("job")
        self.assertIsNone(self.store.data["processes"]["d/a"]["kind"])         # back to the automatic guess

    def test_a_process_can_only_get_a_known_kind_and_empty_means_automatic(self):
        with self.assertRaises(ValueError):
            self.store.set_kind("d/a", "nonsense")
        self.store.set_kind("d/a", "frontend")
        self.store.set_kind("d/a", "")
        self.assertIsNone(self.store.data["processes"]["d/a"]["kind"])

    def test_labels_rename_and_delete_follow_the_processes(self):
        for name in ("critical", "legacy"):
            self.store.add_label(name)
        self.store.set_labels("d/a", ["critical", "legacy", "critical"])
        self.assertEqual(self.store.data["processes"]["d/a"]["labels"], ["critical", "legacy"])      # no duplicates
        self.store.rename_label("critical", "must-run")
        self.assertEqual(self.store.data["processes"]["d/a"]["labels"], ["must-run", "legacy"])
        self.store.delete_label("legacy")
        self.assertEqual(self.store.data["processes"]["d/a"]["labels"], ["must-run"])
        with self.assertRaises(ValueError):
            self.store.set_labels("d/a", ["never-created"])

    def test_label_colours_must_be_hex(self):
        self.store.add_label("x", "#aabbcc")
        with self.assertRaises(ValueError):
            self.store.set_label_color("x", "red")
        with self.assertRaises(ValueError):
            self.store.add_label("y", "javascript:alert(1)")
        self.store.set_label_color("x", None)
        self.assertIsNone(self.store.data["labels"]["x"]["color"])

    def test_it_all_survives_a_restart(self):
        self.store.add_kind("worker")
        self.store.add_label("critical", "#112233")
        self.store.set_labels("d/a", ["critical"])
        self.store.save()
        again = ConfigStore(self.store.directory)
        self.assertEqual((again.data["kinds"], again.data["labels"]["critical"]["color"], again.data["processes"]["d/a"]["labels"]),
                         (["worker"], "#112233", ["critical"]))


class ServiceTest(unittest.TestCase):
    def setUp(self):
        with mock.patch("pm2monitor.service.discover_homes", return_value=[]):
            self.monitor = service.Monitor(ConfigStore(tempfile.mkdtemp()))
        self.monitor.store.register_daemon("d", tempfile.mkdtemp())

    def code(self, request):
        with self.assertRaises(ActionError) as caught:
            self.monitor.apply_config(request)
        return caught.exception.code

    def test_the_operations_work_end_to_end(self):
        apply = self.monitor.apply_config
        apply({"op": "createKind", "name": "worker"})
        apply({"op": "createLabel", "name": "critical", "color": "#abcdef"})
        apply({"op": "setKind", "key": "d/api", "kind": "worker"})
        apply({"op": "setLabels", "key": "d/api", "labels": ["critical"]})
        entry = self.monitor.store.data["processes"]["d/api"]
        self.assertEqual((entry["kind"], entry["labels"]), ("worker", ["critical"]))
        apply({"op": "renameLabel", "old": "critical", "new": "must-run"})
        apply({"op": "setLabelColor", "name": "must-run", "color": "#000000"})
        self.assertEqual(self.monitor.store.data["labels"], {"must-run": {"color": "#000000"}})
        self.assertEqual(self.monitor._label_list(), [{"name": "must-run", "color": "#000000", "count": 1}])

    def test_errors_are_codes_the_ui_translates(self):
        self.assertEqual(self.code({"op": "createLabel", "name": ""}), "bad_label_name")
        self.monitor.apply_config({"op": "createLabel", "name": "x"})
        self.assertEqual(self.code({"op": "createLabel", "name": "X"}), "label_exists")
        self.assertEqual(self.code({"op": "renameLabel", "old": "nope", "new": "y"}), "unknown_label")
        self.assertEqual(self.code({"op": "createKind", "name": "backend"}), "kind_exists")
        self.assertEqual(self.code({"op": "setKind", "key": "d/a", "kind": "nonsense"}), "unknown_kind")
        self.assertEqual(self.code({"op": "setLabelColor", "name": "x", "color": "red"}), "bad_color")
        self.assertEqual(self.code({"op": "setKind", "key": "ghost/a", "kind": "backend"}), "unknown_process")

    def test_a_row_carries_the_chosen_kind_or_the_guess_and_only_labels_that_exist(self):
        folder = project({"react": "18"})
        self.monitor.store.data["processes"]["d/web"] = {"domain": None, "order": 100, "kind": None, "labels": ["ghost"],
                                                          "spec": {"script": "npm", "cwd": folder}}
        row = self.monitor._proc_row("d", "web", {}, None, 0, status="absent")
        self.assertEqual((row["kind"], row["kindAuto"], row["labels"]), (None, "frontend", []))
        self.monitor.apply_config({"op": "setKind", "key": "d/web", "kind": "backend"})
        row = self.monitor._proc_row("d", "web", {}, None, 0, status="absent")
        self.assertEqual((row["kind"], row["kindAuto"]), ("backend", None))


if __name__ == "__main__":
    unittest.main()
