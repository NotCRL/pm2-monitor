"""The double-click launchers: the files for each system, and the launcher that all of them run."""
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import launch
from pm2monitor import control

ROOT = Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class LauncherFilesTest(unittest.TestCase):
    def test_each_system_has_its_file_and_they_all_call_the_same_launcher(self):
        for name in ("Start pm2-monitor.bat", "Start pm2-monitor.command", "start-pm2-monitor.sh"):
            self.assertIn(b"launch.py", (ROOT / name).read_bytes(), name)

    def test_windows_file_has_windows_line_endings(self):
        data = (ROOT / "Start pm2-monitor.bat").read_bytes()
        self.assertIn(b"\r\n", data)
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))  # labels and goto break with bare LF on some Windows versions

    def test_unix_files_have_unix_line_endings_a_shebang_and_can_be_run(self):
        for name in ("Start pm2-monitor.command", "start-pm2-monitor.sh", "launch.py"):
            path = ROOT / name
            self.assertNotIn(b"\r", path.read_bytes(), name)
            self.assertTrue(path.read_bytes().startswith(b"#!"), name)
            if os.name != "nt":
                self.assertTrue(path.stat().st_mode & stat.S_IXUSR, f"{name} is not executable")


class DesktopEntryTest(unittest.TestCase):
    def test_paths_with_spaces_and_quotes_are_quoted_for_the_exec_line(self):
        entry = launch.desktop_entry("/usr/bin/python3", '/home/me/my "tools"/launch.py')
        self.assertIn('Exec="/usr/bin/python3" "/home/me/my \\"tools\\"/launch.py"', entry)
        self.assertIn("Terminal=false", entry)


@unittest.skipIf(os.name == "nt", "the detached-process path on Windows is checked by hand")
class LauncherRunTest(unittest.TestCase):
    def run_launcher(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "launch.py"), "--port", str(self.port), *args], env=self.env,
                              capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port = free_port()
        self.env = dict(os.environ, HOME=self.tmp.name, XDG_CONFIG_HOME=self.tmp.name, APPDATA=self.tmp.name,
                        PM2_MONITOR_NO_DIALOG="1")   # an error window would wait for a human and freeze the test
        self.addCleanup(control.request_shutdown, self.port)

    def wait_until(self, condition, seconds=15):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if condition():
                return True
            time.sleep(0.2)
        return False

    def test_start_is_idempotent_and_stop_turns_it_off(self):
        config = str(Path(self.tmp.name) / "config.json")
        first = self.run_launcher("--config", config, "--no-browser")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(control.running_version(self.port))          # still up after the launcher exited: it is detached
        self.assertTrue((Path(self.tmp.name) / "pm2-monitor" / "server.log").exists())
        again = self.run_launcher("--config", config, "--no-browser")
        self.assertEqual(again.returncode, 0)
        self.assertIn("already running", again.stdout)
        stop = self.run_launcher("--stop")
        self.assertEqual(stop.returncode, 0)
        self.assertTrue(self.wait_until(lambda: control.running_version(self.port) is None))
        self.assertIn("not running", self.run_launcher("--stop").stdout)

    def test_a_port_used_by_another_program_is_reported(self):
        with socket.socket() as other:
            other.bind(("127.0.0.1", self.port))
            other.listen(1)
            result = self.run_launcher("--no-browser")
        self.assertEqual(result.returncode, 1)
        self.assertIn("used by another program", result.stderr)


if __name__ == "__main__":
    unittest.main()
