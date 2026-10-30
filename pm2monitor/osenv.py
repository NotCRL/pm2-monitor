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


_WINDOWS_EXECUTABLE = {"pm2": "pm2.cmd", "npm": "npm.cmd", "node": "node.exe"}
_tool_cache = {}


def os_name():
    """'windows', 'macos' or 'linux': the UI shows the commands that fit the user's system."""
    if IS_WINDOWS:
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def _tool_glob_patterns(tool):
    """Where node, npm and pm2 usually live when they are not on the PATH (e.g. just installed)."""
    if IS_WINDOWS:
        exe = _WINDOWS_EXECUTABLE[tool]
        folders = []
        for var, sub in (("APPDATA", "npm"), ("NVM_SYMLINK", ""), ("ProgramFiles", "nodejs"),
                         ("ProgramFiles(x86)", "nodejs"), ("LOCALAPPDATA", "Programs/nodejs")):
            base = os.environ.get(var)
            if base:
                folders.append(Path(base, sub))
        nvm_home = os.environ.get("NVM_HOME")
        if nvm_home:
            folders.append(Path(nvm_home, "v*"))
        patterns = [str(folder / exe) for folder in folders]
        patterns.append(str(HOME / ".volta" / "bin" / exe.replace(".cmd", ".exe")))
        return patterns
    return [
        str(HOME / ".nvm/versions/node/*/bin" / tool),
        str(HOME / ".local/share/fnm/node-versions/*/installation/bin" / tool),
        str(HOME / "Library/Application Support/fnm/node-versions/*/installation/bin" / tool),
        str(HOME / ".volta/bin" / tool),
        str(HOME / ".asdf/shims" / tool),
        str(HOME / ".npm-global/bin" / tool),
        "/opt/homebrew/bin/" + tool,
        "/usr/local/bin/" + tool,
        "/usr/bin/" + tool,
    ]


def find_tool(tool, configured=None, refresh=False):
    """Path of node / npm / pm2: the one set in the config, then PATH, then the usual install folders."""
    if configured and Path(configured).exists():
        return configured
    if not refresh and tool in _tool_cache:
        return _tool_cache[tool]
    found = shutil.which(tool)
    if not found:
        matches = [m for pattern in _tool_glob_patterns(tool) for m in glob.glob(pattern)]
        found = max(matches, key=_version_key) if matches else None
    if found:
        _tool_cache[tool] = found  # only found paths are cached: a missing tool may be installed any minute
    return found


def refresh_tool_cache():
    _tool_cache.clear()


def find_pm2(configured=None):
    return find_tool("pm2", configured, refresh=True)


def find_node():
    return find_tool("node")


def find_npm():
    return find_tool("npm")


def tool_environment(*tool_paths, pm2_home=None):
    """Environment for running node-based tools: their folders go first on PATH, because pm2 and npm
    are node scripts and the monitor's own PATH may predate the installation of node."""
    env = dict(os.environ)
    if pm2_home is not None:
        env["PM2_HOME"] = str(pm2_home)
    folders = [str(Path(p).parent) for p in tool_paths if p]
    env["PATH"] = os.pathsep.join(folders + [env.get("PATH", "")])
    return env


def pm2_environment(pm2_path, pm2_home):
    return tool_environment(pm2_path, find_node(), pm2_home=pm2_home)


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
