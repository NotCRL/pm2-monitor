"""Guided setup for people who have never used pm2.

Checks what is installed, installs pm2 on request, suggests how to start a project and starts a
first process. Like the rest of the server it reports failures as ActionError codes, which the UI
translates.
"""
import json
import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .discovery import make_daemon_id
from .osenv import (HOME, IS_WINDOWS, find_node, find_npm, os_name, refresh_tool_cache,
                    subprocess_flags, tool_environment)
from .service import ActionError, strip_ansi, tail

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,59}$")
STABLE_SECONDS = 3  # a first app counts as running only if it is still online after this long
INSTALL_TIMEOUT_SECONDS = 900
MAX_FOLDERS_LISTED = 500
LOG_LINES_SHOWN = 15

_install_jobs = {}
_install_lock = threading.Lock()


# --- diagnosis ----------------------------------------------------------------------------------
def _run_version(command):
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=10,
                             env=tool_environment(command[0], find_node()), **subprocess_flags()).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out.strip().splitlines()[0] if out.strip() else None


def pm2_version(pm2_path):
    """Read from pm2's package.json: running 'pm2 --version' loads pm2 and may create its home folder."""
    if not pm2_path:
        return None
    candidates = [Path(os.path.realpath(pm2_path)).parent.parent / "package.json",
                  Path(pm2_path).parent / "node_modules" / "pm2" / "package.json"]
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("name") == "pm2":
            return data.get("version")
    return None


def default_pm2_home():
    return Path(os.environ.get("PM2_HOME") or HOME / ".pm2")


def doctor(monitor):
    """What is installed on this computer, so the UI can tell the user what is missing."""
    refresh_tool_cache()
    monitor.refresh_pm2()
    node, npm = find_node(), find_npm()
    return {
        "os": os_name(),
        "home": str(HOME),
        "node": {"path": node, "version": _run_version([node, "--version"]) if node else None},
        "npm": {"path": npm, "version": _run_version([npm, "--version"]) if npm else None},
        "pm2": {"path": monitor.pm2_path, "version": pm2_version(monitor.pm2_path)},
        "pm2Home": str(default_pm2_home()),
    }


# --- installing pm2 -------------------------------------------------------------------------------
def start_install_pm2(monitor):
    """Runs 'npm install -g pm2' in the background; returns a job id to poll."""
    npm = find_npm()
    if not npm:
        raise ActionError("npm_not_found")
    with _install_lock:
        if any(job["state"] == "running" for job in _install_jobs.values()):
            raise ActionError("install_in_progress")
        job = {"id": uuid.uuid4().hex[:8], "state": "running", "output": "", "fallback": False,
               "error": None, "started": time.time()}
        _install_jobs[job["id"]] = job
    threading.Thread(target=_run_install, args=(monitor, job, npm), daemon=True).start()
    return job["id"]


def _npm_install(npm, extra_args):
    return subprocess.run([npm, "install", "-g", "pm2", *extra_args], capture_output=True, text=True,
                          timeout=INSTALL_TIMEOUT_SECONDS, env=tool_environment(npm, find_node()),
                          **subprocess_flags())


def _run_install(monitor, job, npm):
    try:
        result = _npm_install(npm, [])
        output = strip_ansi(result.stdout + result.stderr)
        if result.returncode != 0 and ("EACCES" in output or "EPERM" in output):
            # The system folder is protected: install in the user's own folder, no sudo needed.
            prefix = HOME / ".npm-global"
            job["fallback"] = True
            result = _npm_install(npm, ["--prefix", str(prefix)])
            output += "\n\n" + strip_ansi(result.stdout + result.stderr)
        job["output"] = output[-4000:]
        refresh_tool_cache()
        if result.returncode != 0:
            job["error"], job["state"] = "install_failed", "failed"
        elif not monitor.refresh_pm2():
            job["error"], job["state"] = "pm2_missing_after_install", "failed"
        else:
            job["state"] = "done"
    except (OSError, subprocess.SubprocessError) as e:
        job["output"] = str(e)
        job["error"], job["state"] = "install_failed", "failed"


def get_install_job(job_id):
    with _install_lock:
        job = _install_jobs.get(job_id)
        return dict(job) if job else None


# --- choosing a project --------------------------------------------------------------------------
def list_folders(path):
    """Sub-folders of a folder, for the folder picker (files are never listed)."""
    base = Path(path).expanduser() if path else HOME
    if not base.is_dir():
        raise ActionError("folder_not_found", path=str(path))
    base = base.resolve()
    try:
        names = [e.name for e in os.scandir(base) if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")]
    except OSError:
        raise ActionError("folder_unreadable", path=str(base))
    names.sort(key=str.lower)
    return {"path": str(base), "parent": str(base.parent) if base.parent != base else None,
            "folders": [{"name": n, "path": str(base / n)} for n in names[:MAX_FOLDERS_LISTED]]}


def sanitize_name(text):
    return re.sub(r"[^A-Za-z0-9_.\-]+", "-", text or "").strip("-.")[:60]


def suggest_command(folder):
    """Guesses name and start command of the project in a folder. command is empty when unsure."""
    path = Path(str(folder or "")).expanduser()
    if not path.is_dir():
        raise ActionError("folder_not_found", path=str(folder))
    name = sanitize_name(path.name) or "my-app"
    package = path / "package.json"
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        name = sanitize_name(str(data.get("name") or "")) or name
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        if "start" in scripts:
            return {"name": name, "command": "npm start", "kind": "npm"}
        for candidate in (data.get("main"), "server.js", "app.js", "index.js"):
            if isinstance(candidate, str) and (path / candidate).is_file():
                return {"name": name, "command": f"node {candidate}", "kind": "node"}
    python = "python" if IS_WINDOWS else "python3"
    for candidate in ("main.py", "app.py", "server.py"):
        if (path / candidate).is_file():
            return {"name": name, "command": f"{python} {candidate}", "kind": "python"}
    return {"name": name, "command": "", "kind": None}


# --- starting the first app -----------------------------------------------------------------------
def ensure_default_daemon(monitor):
    """Registers pm2's default daemon (PM2_HOME or ~/.pm2) even if it does not exist yet: pm2 creates it
    the first time something is started."""
    home = default_pm2_home()
    with monitor.store.lock:
        daemon_id = monitor.store.daemon_id_for_home(os.path.realpath(home))
        if daemon_id is None:
            daemon_id = make_daemon_id(home, set(monitor.store.data["daemons"]))
            monitor.store.register_daemon(daemon_id, os.path.realpath(home))
        monitor.store.update_daemon(daemon_id, hidden=False)
        monitor.store.save()
    return daemon_id


def _pm2_launch(tokens):
    """(script, arguments, extra pm2 options) for a typed command such as 'node app.js' or 'npm start'."""
    first = Path(tokens[0]).name.lower()
    if first in ("node", "nodejs", "node.exe") and len(tokens) > 1:
        return tokens[1], tokens[2:], []
    if (first.startswith("python") or first in ("py", "py.exe")) and len(tokens) > 1:
        return tokens[1], tokens[2:], ["--interpreter", tokens[0]]
    return tokens[0], tokens[1:], []


def _log_tail(monitor, key):
    out_path, err_path = monitor.find_logs(key)
    parts = [text for text, _ in (tail(err_path, LOG_LINES_SHOWN), tail(out_path, LOG_LINES_SHOWN)) if text]
    return "\n".join(parts)


def add_process(monitor, name, folder, command):
    """Starts a first app under pm2 and saves the list. If it does not stay up, it is removed again
    so the user can retry with another command."""
    name = (name or "").strip()
    if not NAME_PATTERN.match(name):
        raise ActionError("bad_process_name")
    cwd = Path(str(folder or "").strip()).expanduser()
    if not cwd.is_dir():
        raise ActionError("folder_not_found", path=str(folder))
    try:
        tokens = shlex.split(command or "", posix=not IS_WINDOWS)
    except ValueError:
        raise ActionError("bad_command")
    if not tokens:
        raise ActionError("empty_command")
    if not monitor.pm2_path:
        raise ActionError("pm2_not_found")
    daemon_id = ensure_default_daemon(monitor)
    if monitor.live_entry(daemon_id, name):
        raise ActionError("process_exists", name=name)

    script, args, extra = _pm2_launch(tokens)
    start = ["start", script, "--name", name, *extra] + (["--", *args] if args else [])
    result = monitor.run_pm2(daemon_id, start, timeout=90, cwd=str(cwd))
    if result.returncode != 0:
        raise ActionError("pm2_failed", output=strip_ansi(result.stdout + result.stderr)[-1500:])

    time.sleep(STABLE_SECONDS)
    key = f"{daemon_id}/{name}"
    item = monitor.live_entry(daemon_id, name)
    pm2_env = (item or {}).get("pm2_env", {})
    status = pm2_env.get("status", "unknown")
    if status == "online" and not pm2_env.get("restart_time"):
        monitor.run_pm2(daemon_id, ["save"], timeout=30)
        return {"key": key, "status": status}
    log = _log_tail(monitor, key)
    monitor.run_pm2(daemon_id, ["delete", name], timeout=30)
    raise ActionError("process_failed", status=status, log=log)
