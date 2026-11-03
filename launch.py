#!/usr/bin/env python3
"""Starts pm2-monitor if it is not running yet and opens it in the browser.

The double-click launchers (Start pm2-monitor.bat / .command, start-pm2-monitor.sh) all run this file, so
the behaviour is the same on Linux, macOS and Windows. The server is started detached, with no console
window, and its output goes to a log file.

Usage: python3 launch.py [--port N] [--config PATH] [--no-browser] [--stop] [--install-shortcut]
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pm2monitor import control  # noqa: E402
from pm2monitor.osenv import IS_WINDOWS, config_dir  # noqa: E402

DEFAULT_PORT = 8440
START_TIMEOUT_SECONDS = 20
MIN_PYTHON = (3, 8)
# Windows process flags: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
WINDOWS_DETACHED = 0x00000008 | 0x00000200 | 0x08000000


def show_dialog(title, message):
    """With a double-click there may be no terminal to read: show the message in a window as well.
    PM2_MONITOR_NO_DIALOG=1 turns the window off (scripts and tests: it would wait for someone to close it)."""
    if os.environ.get("PM2_MONITOR_NO_DIALOG"):
        return
    try:
        if IS_WINDOWS:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
        elif sys.platform == "darwin":
            script = ["-e", "on run argv", "-e", 'display dialog (item 1 of argv) with title (item 2 of argv) buttons {"OK"} default button "OK"',
                      "-e", "end run"]
            subprocess.run(["osascript", *script, message, title], timeout=300)
        else:
            for tool in (["zenity", "--error", "--title", title, "--text", message], ["kdialog", "--title", title, "--error", message]):
                if shutil.which(tool[0]):
                    subprocess.run(tool, timeout=300)
                    break
    except Exception:  # noqa: BLE001 - the printed message is still there
        pass


def fail(message):
    print(message, file=sys.stderr)
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or IS_WINDOWS:
        show_dialog("pm2 monitor", message)
    sys.exit(1)


def server_command(port, config):
    python = sys.executable
    if IS_WINDOWS:  # pythonw runs without a console window
        pythonw = Path(python).with_name("pythonw.exe")
        python = str(pythonw) if pythonw.exists() else python
    command = [python, str(HERE / "server.py"), "--port", str(port)]
    return command + (["--config", config] if config else [])


def start_server(port, config):
    log_path = config_dir() / "server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    options = {"creationflags": WINDOWS_DETACHED} if IS_WINDOWS else {"start_new_session": True}
    with open(log_path, "ab") as log:
        process = subprocess.Popen(server_command(port, config), cwd=str(HERE), stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, **options)
    return process, log_path


def log_tail(path, lines=8):
    try:
        return "\n".join(Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def desktop_entry(python, launcher):
    """Contents of a Linux .desktop file that starts the monitor; Exec needs quoted, escaped paths."""
    def quote(path):
        return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'
    return ("[Desktop Entry]\nType=Application\nName=pm2 monitor\n"
            "Comment=Start pm2 monitor and open it in the browser\n"
            f"Exec={quote(python)} {quote(launcher)}\nTerminal=false\n"
            "Icon=utilities-system-monitor\nCategories=Development;System;\n")


def install_shortcut():
    if sys.platform.startswith("linux"):
        folder = Path.home() / ".local" / "share" / "applications"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "pm2-monitor.desktop"
        target.write_text(desktop_entry(sys.executable, HERE / "launch.py"), encoding="utf-8")
        print(f"Created {target}: pm2 monitor now appears in your applications menu.")
    elif sys.platform == "darwin":
        print('macOS: drag "Start pm2-monitor.command" to the Dock, or add it in System Settings > General > Login Items.')
    else:
        print('Windows: right-click "Start pm2-monitor.bat" > Send to > Desktop (create shortcut).')


def main():
    parser = argparse.ArgumentParser(description="Start pm2 monitor and open it in the browser.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--config", metavar="PATH")
    parser.add_argument("--no-browser", action="store_true", help="start the monitor but do not open the browser")
    parser.add_argument("--stop", action="store_true", help="turn off the monitor that is running")
    parser.add_argument("--install-shortcut", action="store_true", help="add pm2 monitor to your applications menu (Linux)")
    args = parser.parse_args()
    url = control.monitor_url(args.port)

    if sys.version_info < MIN_PYTHON:
        fail("pm2 monitor needs Python 3.8 or newer. Download it from https://www.python.org/downloads/")
    if args.install_shortcut:
        return install_shortcut()
    if args.stop:
        print("pm2 monitor is stopping." if control.request_shutdown(args.port) else "pm2 monitor is not running.")
        return

    if control.running_version(args.port):
        print(f"pm2 monitor is already running at {url}")
    else:
        if control.port_in_use(args.port):
            fail(f"Port {args.port} is used by another program. Start pm2 monitor on a free port, for example: python3 launch.py --port {args.port + 10}")
        process, log_path = start_server(args.port, args.config)
        deadline = time.time() + START_TIMEOUT_SECONDS
        while not control.running_version(args.port):
            if process.poll() is not None:
                fail("pm2 monitor stopped right after starting. Last lines of its log:\n\n" + log_tail(log_path) + f"\n\nFull log: {log_path}")
            if time.time() > deadline:
                fail(f"pm2 monitor did not answer within {START_TIMEOUT_SECONDS} seconds. Log: {log_path}")
            time.sleep(0.3)
        print(f"pm2 monitor is running at {url}")
    if not args.no_browser:
        webbrowser.open(url)
    print("You can close this window: pm2 monitor keeps running. Turn it off with the power button in its page.")


if __name__ == "__main__":
    main()
