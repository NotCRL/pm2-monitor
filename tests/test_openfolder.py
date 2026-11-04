"""Opening a process's folder in the file manager. No real file manager is ever started: the launchers are fakes."""
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm2monitor import service
from pm2monitor.service import ActionError, Monitor, open_in_file_manager
from pm2monitor.store import ConfigStore


def fake_tool(directory, name, body):
    path = Path(directory, name)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@unittest.skipUnless(sys.platform.startswith("linux"), "uses a stand-in for xdg-open")
class LinuxOpenTest(unittest.TestCase):
    def setUp(self):
        self.bin, self.log, self.folder = (tempfile.mkdtemp() for _ in range(3))
        self.record = Path(self.log, "args")

    def with_path(self, directory):
        return mock.patch.dict(os.environ, {"PATH": directory})

    def test_the_folder_is_handed_to_xdg_open(self):
        fake_tool(self.bin, "xdg-open", f'echo "$@" > "{self.record}"')
        with self.with_path(self.bin):
            open_in_file_manager(self.folder)
        self.assertEqual(self.record.read_text().strip(), self.folder)

    def test_a_folder_name_cannot_inject_options_or_commands(self):
        tricky = Path(self.folder, "-x; touch pwned $(id)")
        tricky.mkdir()
        fake_tool(self.bin, "xdg-open", f'echo "$#:$1" > "{self.record}"')
        with self.with_path(self.bin):
            open_in_file_manager(tricky)
        self.assertEqual(self.record.read_text().strip(), f"1:{tricky}")      # one argument, untouched, nothing run
        self.assertFalse(Path("pwned").exists())

    def test_a_failing_file_manager_is_reported(self):
        fake_tool(self.bin, "xdg-open", "exit 3")
        with self.with_path(self.bin), self.assertRaises(ActionError) as caught:
            open_in_file_manager(self.folder)
        self.assertEqual(caught.exception.code, "open_failed")

    def test_a_slow_file_manager_counts_as_opened(self):
        script = Path(self.bin, "xdg-open")               # a file manager that stays up keeps the command alive
        script.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(1)\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        started, real_popen = [], service.subprocess.Popen

        def spy(*args, **kwargs):
            started.append(real_popen(*args, **kwargs))
            return started[-1]

        with self.with_path(self.bin), mock.patch.object(service, "OPEN_WAIT_SECONDS", 0.2), \
             mock.patch.object(service.subprocess, "Popen", side_effect=spy):
            open_in_file_manager(self.folder)             # no error: it was still running when we stopped waiting
        for process in started:
            process.wait()                                # the stand-in ends by itself

    def test_without_xdg_open_the_user_is_told(self):
        with self.with_path(self.bin), self.assertRaises(ActionError) as caught:     # an empty folder on the PATH
            open_in_file_manager(self.folder)
        self.assertEqual(caught.exception.code, "open_unavailable")


class OtherSystemsTest(unittest.TestCase):
    def test_macos_uses_open(self):
        with mock.patch.object(service, "IS_WINDOWS", False), mock.patch.object(service.sys, "platform", "darwin"), \
             mock.patch.object(service.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 0
            open_in_file_manager("/some/folder")
        self.assertEqual(popen.call_args[0][0], ["open", "/some/folder"])

    def test_windows_uses_the_explorer(self):
        with mock.patch.object(service, "IS_WINDOWS", True), mock.patch.object(os, "startfile", create=True) as startfile:
            open_in_file_manager("C:\\work\\app")
        startfile.assert_called_once_with("C:\\work\\app")


class MonitorOpenFolderTest(unittest.TestCase):
    def setUp(self):
        with mock.patch("pm2monitor.service.discover_homes", return_value=[]):
            self.monitor = Monitor(ConfigStore(tempfile.mkdtemp()))
        self.monitor.store.register_daemon("d", tempfile.mkdtemp())
        self.folder = tempfile.mkdtemp()

    def rows(self, *rows):
        return mock.patch.object(self.monitor, "snapshot", return_value={"procs": list(rows)})

    def code(self, key):
        with self.assertRaises(ActionError) as caught:
            self.monitor.open_folder(key)
        return caught.exception.code

    def test_opens_the_folder_of_a_known_process(self):
        with self.rows({"key": "d/api", "cwd": self.folder}), mock.patch.object(service, "open_in_file_manager") as opener:
            self.monitor.open_folder("d/api")
        opener.assert_called_once_with(self.folder)

    def test_unknown_things_are_refused_and_nothing_is_opened(self):
        with self.rows({"key": "d/api", "cwd": self.folder}), mock.patch.object(service, "open_in_file_manager") as opener:
            self.assertEqual(self.code("ghost/api"), "unknown_daemon")
            self.assertEqual(self.code("d/other"), "unknown_process")
            self.assertEqual(self.code("/etc"), "unknown_daemon")           # a path is not a key
        opener.assert_not_called()

    def test_a_process_whose_folder_is_gone_or_unknown(self):
        with self.rows({"key": "d/a", "cwd": "/definitely/not/here"}, {"key": "d/b", "cwd": None}):
            self.assertEqual(self.code("d/a"), "folder_not_found")
            self.assertEqual(self.code("d/b"), "folder_not_found")


if __name__ == "__main__":
    unittest.main()
