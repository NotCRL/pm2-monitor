import json
import re
import tempfile
import unittest
from pathlib import Path

from pm2monitor import discovery, osenv
from pm2monitor.service import ActionError, split_key
from pm2monitor.store import ConfigStore


class DaemonIdTest(unittest.TestCase):
    def test_default_home(self):
        self.assertEqual(discovery.make_daemon_id(Path("/home/u/.pm2"), set()), "default")

    def test_suffix_becomes_id(self):
        self.assertEqual(discovery.make_daemon_id(Path("/home/u/.pm2-work"), set()), "work")

    def test_collision_gets_number(self):
        self.assertEqual(discovery.make_daemon_id(Path("/x/.pm2-work"), {"work"}), "work-2")


class VersionOrderTest(unittest.TestCase):
    def test_numeric_not_alphabetic(self):
        paths = ["/n/v9.11.2/bin/pm2", "/n/v18.20.8/bin/pm2", "/n/v10.0.0/bin/pm2"]
        self.assertEqual(max(paths, key=osenv._version_key), "/n/v18.20.8/bin/pm2")


class LaunchSpecTest(unittest.TestCase):
    def test_extracts_what_is_needed_and_drops_env(self):
        spec = discovery.extract_launch_spec({
            "pm_exec_path": "/bin/npm", "pm_cwd": "/app", "args": ["start"], "exec_mode": "fork_mode",
            "exec_interpreter": "node", "env": {"SECRET": "x"}})
        self.assertEqual(spec, {"script": "/bin/npm", "cwd": "/app", "args": ["start"],
                                "interpreter": "node", "exec_mode": "fork"})


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_roundtrip(self):
        store = ConfigStore(self.tmp.name)
        store.set_process("myapp/api", domain="backend", order=20)
        store.save()
        again = ConfigStore(self.tmp.name)
        self.assertEqual(again.data["processes"]["myapp/api"]["order"], 20)
        self.assertIn("backend", again.data["domains"])

    def test_corrupt_config_is_kept_aside(self):
        Path(self.tmp.name, "config.json").write_text("{not json")
        store = ConfigStore(self.tmp.name)
        self.assertIsNotNone(store.warning)
        self.assertEqual(store.data["processes"], {})
        self.assertTrue(list(Path(self.tmp.name).glob("config.json.corrupt-*")))

    def test_rename_domain_moves_members(self):
        store = ConfigStore(self.tmp.name)
        store.set_process("d/a", domain="old")
        store.rename_domain("old", "new")
        self.assertEqual(store.data["processes"]["d/a"]["domain"], "new")

    def test_delete_domain_keeps_processes(self):
        store = ConfigStore(self.tmp.name)
        store.set_process("d/a", domain="old")
        store.delete_domain("old")
        self.assertIsNone(store.data["processes"]["d/a"]["domain"])


class ConfigLocationTest(unittest.TestCase):
    def test_directory_gets_config_json(self):
        self.assertEqual(osenv.resolve_config_file("/x/dir"), Path("/x/dir/config.json"))

    def test_json_file_is_used_as_is(self):
        self.assertEqual(osenv.resolve_config_file("/x/mine.JSON"), Path("/x/mine.JSON"))

    def test_store_accepts_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ConfigStore(Path(tmp, "settings.json"))
            store.save()
            self.assertTrue(Path(tmp, "settings.json").exists())


class MiscTest(unittest.TestCase):
    def test_split_key_keeps_slashes_in_name(self):
        self.assertEqual(split_key("myapp/a/b"), ("myapp", "a/b"))

    def test_pid_alive(self):
        import os
        self.assertTrue(osenv.pid_alive(os.getpid()))
        self.assertFalse(osenv.pid_alive(0))

    def test_looks_like_pm2_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(discovery.looks_like_pm2_home(Path(tmp)))
            Path(tmp, "dump.pm2").write_text(json.dumps([]))
            self.assertTrue(discovery.looks_like_pm2_home(Path(tmp)))


class TranslationsTest(unittest.TestCase):
    """The UI holds the only translation table: keys must match across languages and cover every code the server can send."""

    root = Path(__file__).resolve().parent.parent

    def table(self, lang):
        """Keys of the translation table for one language, read from index.html."""
        html = (self.root / "index.html").read_text(encoding="utf-8")
        block = html.split(f"\n  {lang}: {{", 1)[1].split("\n  }", 1)[0]
        return {quoted or bare for quoted, bare in
                re.findall(r"(?:^|[,{\s])(?:'([^']+)'|([A-Za-z]\w*))\s*:\s*['\"]", block)}

    def test_same_keys_in_both_languages(self):
        self.assertEqual(self.table("en"), self.table("it"))

    def test_keys_used_by_the_page_exist(self):
        html = (self.root / "index.html").read_text(encoding="utf-8")
        used = set(re.findall(r"\bt\('([\w.]+)'", html)) | set(re.findall(r'data-i18n(?:-title|-placeholder)?="(\w+)"', html))
        used = {key for key in used if not key.endswith(".")}  # dynamic keys such as 'status.' + value
        self.assertEqual(used - self.table("en"), set())

    def test_every_server_error_code_is_translated(self):
        sources = "".join(p.read_text(encoding="utf-8") for p in
                          [*(self.root / "pm2monitor").glob("*.py"), self.root / "server.py"])
        codes = set(re.findall(r'ActionError\("(\w+)"', sources))
        codes |= set(re.findall(r'send_error_json\("(\w+)"', sources))
        codes |= set(re.findall(r'"error"\] = "(\w+)"', sources))
        codes |= set(re.findall(r'"code": "(\w+)"', sources))
        codes |= {"read_failed", "error_detail", "start_timeout"}  # raised through variables, not literals
        missing = {c for c in codes if f"err.{c}" not in self.table("en")}
        self.assertEqual(missing, set())

    def test_every_job_step_label_is_translated(self):
        sources = (self.root / "pm2monitor" / "service.py").read_text(encoding="utf-8")
        labels = set(re.findall(r'_step\(job, [^,]+, "(\w+)"', sources))
        self.assertTrue(labels)
        self.assertEqual({l for l in labels if f"step.{l}" not in self.table("en")}, set())

    def test_action_error_carries_code_and_params(self):
        error = ActionError("domain_busy", domain="x")
        self.assertEqual((error.code, error.params), ("domain_busy", {"domain": "x"}))


if __name__ == "__main__":
    unittest.main()
