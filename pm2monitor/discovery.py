"""Finds the pm2 daemons on this computer and reads their configuration."""
import json
import os
import re
import subprocess
from pathlib import Path

from .osenv import HOME, IS_WINDOWS, pid_alive

DAEMON_TITLE = re.compile(r"PM2 v[\w.\-]+: God Daemon \((.+)\)")
HOME_MARKERS = ("pm2.pid", "dump.pm2", "pm2.log")


def looks_like_pm2_home(path):
    return path.is_dir() and any((path / marker).exists() for marker in HOME_MARKERS)


def running_daemon_homes():
    """The pm2 daemon writes its own PM2_HOME in the process title (not available on Windows)."""
    if IS_WINDOWS:
        return []
    try:
        out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [Path(m.group(1)) for m in DAEMON_TITLE.finditer(out)]


def discover_homes(extra_homes=()):
    """Valid PM2_HOME directories, deduplicated: environment, ~/.pm2*, running daemons, manual paths."""
    candidates = []
    if os.environ.get("PM2_HOME"):
        candidates.append(Path(os.environ["PM2_HOME"]))
    candidates.extend(sorted(HOME.glob(".pm2*")))
    candidates.extend(running_daemon_homes())
    candidates.extend(Path(h) for h in extra_homes)
    homes, seen = [], set()
    for candidate in candidates:
        real = os.path.realpath(candidate)
        if real not in seen and looks_like_pm2_home(Path(real)):
            seen.add(real)
            homes.append(Path(real))
    return homes


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def make_daemon_id(home, taken_ids):
    """'.pm2' -> 'default', '.pm2-work' -> 'work'; a number is appended on name clashes."""
    name = home.name.lstrip(".")
    base = slugify(re.sub(r"^pm2[-_.]?", "", name)) or ("default" if name == "pm2" else slugify(name)) or "pm2"
    candidate, n = base, 2
    while candidate in taken_ids:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def daemon_alive(home):
    """Checked without calling pm2: 'pm2 jlist' on a stopped daemon would start a new one."""
    try:
        return pid_alive(int((Path(home) / "pm2.pid").read_text().strip()))
    except (OSError, ValueError):
        return False


def read_dump(home):
    """Processes saved by 'pm2 save': the configuration that can be recovered while the daemon is down."""
    try:
        data = json.loads((Path(home) / "dump.pm2").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [entry for entry in data if isinstance(entry, dict) and entry.get("name")]


def extract_launch_spec(pm2_env):
    """What is needed to launch the process from scratch. The env is not saved: it is full of system variables."""
    exec_mode = (pm2_env.get("exec_mode") or "fork_mode").replace("_mode", "")
    spec = {
        "script": pm2_env.get("pm_exec_path"),
        "cwd": pm2_env.get("pm_cwd") or pm2_env.get("cwd"),
        "args": pm2_env.get("args") or [],
        "interpreter": pm2_env.get("exec_interpreter"),
        "exec_mode": exec_mode,
    }
    if exec_mode == "cluster" and pm2_env.get("instances"):
        spec["instances"] = pm2_env["instances"]
    return {key: value for key, value in spec.items() if value not in (None, "")}
