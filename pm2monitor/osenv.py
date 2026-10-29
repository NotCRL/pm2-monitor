"""OS differences: config location, pm2 lookup, process liveness check."""
import glob
import os
import re
import shutil
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"
HOME = Path.home()
CREATE_NO_WINDOW = 0x08000000


def subprocess_flags():
    """On Windows, keep every pm2 call from opening a console window."""
    return {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}


def config_dir():
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA") or HOME / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = HOME / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
    return base / "pm2-monitor"


def resolve_config_file(location):
    """Accepts a .json file or a directory (which will hold config.json)."""
    path = Path(location).expanduser()
    return path if path.suffix.lower() == ".json" else path / "config.json"


def default_config_file():
    """PM2_MONITOR_CONFIG if set, otherwise the per-OS config directory."""
    override = os.environ.get("PM2_MONITOR_CONFIG")
    return resolve_config_file(override) if override else config_dir() / "config.json"


def _version_key(path):
    """Sort paths by node version (v9 before v18), not alphabetically."""
    match = re.search(r"v?(\d+)\.(\d+)\.(\d+)", path)
    return tuple(int(n) for n in match.groups()) if match else (0, 0, 0)


def _pm2_glob_patterns():
    if IS_WINDOWS:
        patterns = []
        for var in ("APPDATA", "NVM_SYMLINK", "ProgramFiles"):
            base = os.environ.get(var)
            if base:
                suffix = "npm" if var == "APPDATA" else ("" if var == "NVM_SYMLINK" else "nodejs")
                patterns.append(str(Path(base, suffix, "pm2.cmd")))
        nvm_home = os.environ.get("NVM_HOME")
        if nvm_home:
            patterns.append(str(Path(nvm_home, "v*", "pm2.cmd")))
        patterns.append(str(HOME / ".volta" / "bin" / "pm2.exe"))
        return patterns
    return [
        str(HOME / ".nvm/versions/node/*/bin/pm2"),
        str(HOME / ".local/share/fnm/node-versions/*/installation/bin/pm2"),
        str(HOME / "Library/Application Support/fnm/node-versions/*/installation/bin/pm2"),
        str(HOME / ".volta/bin/pm2"),
        str(HOME / ".asdf/shims/pm2"),
        str(HOME / ".npm-global/bin/pm2"),
        "/opt/homebrew/bin/pm2",
        "/usr/local/bin/pm2",
        "/usr/bin/pm2",
    ]


def find_pm2(configured=None):
    """pm2 path: the one set in the config, then PATH, then the node version managers."""
    if configured and Path(configured).exists():
        return configured
    on_path = shutil.which("pm2")
    if on_path:
        return on_path
    matches = [m for pattern in _pm2_glob_patterns() for m in glob.glob(pattern)]
    return max(matches, key=_version_key) if matches else None


def pm2_environment(pm2_path, pm2_home):
    """pm2 is a node script: its directory must be on PATH so it can find node."""
    env = dict(os.environ, PM2_HOME=str(pm2_home))
    env["PATH"] = str(Path(pm2_path).parent) + os.pathsep + env.get("PATH", "")
    return env


def pid_alive(pid):
    """On Windows os.kill(pid, 0) TERMINATES the process, so the system API is used there."""
    if pid <= 0:
        return False
    if IS_WINDOWS:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists but belongs to another user
    except OSError:
        return False
    return True
