"""Application logic: process state, single and per-domain actions, config changes.

User-facing messages are not built here: errors carry a stable `code` plus `params`,
and the UI translates them (see the `err.*` entries in index.html).
"""
import json
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import ISSUES_URL, __version__
from .discovery import (daemon_alive, discover_homes, extract_launch_spec, looks_like_pm2_home,
                        make_daemon_id, read_dump)
from .osenv import find_pm2, pm2_environment, subprocess_flags
from .store import DEFAULT_ORDER

ACTIONS = {"start", "stop", "restart"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LOG_TAIL_BYTES = 256 * 1024
SCAN_INTERVAL_SECONDS = 30
STABLE_SECONDS = 2  # a process counts as started only if it stays online for this long
MAX_JOBS_KEPT = 20


class ActionError(Exception):
    """A failure the user should see: `code` identifies the message, `params` fills its blanks."""

    def __init__(self, code, **params):
        super().__init__(f"{code} {params}" if params else code)
        self.code = code
        self.params = params


def split_key(key):
    daemon_id, _, name = str(key).partition("/")
    return daemon_id, name


def strip_ansi(text):
    return ANSI.sub("", text).strip()


def tail(path, line_count):
    """Last lines of a log file as (text, error). `error` is a code when the file cannot be read."""
    if not path:
        return None, None
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - LOG_TAIL_BYTES))
            text = f.read().decode("utf-8", "replace")
    except OSError as e:
        return None, str(e)
    lines = strip_ansi(text).splitlines()
    if size > LOG_TAIL_BYTES:
        lines = lines[1:]  # the first line is cut in half
    return "\n".join(lines[-line_count:]), None


class Monitor:
    def __init__(self, store):
        self.store = store
        self.pm2_path = find_pm2(store.data["pm2Path"])
        self.mutation_locks = {}
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.last_scan = 0.0
        self.scan()

    # --- pm2 ----------------------------------------------------------------
    def home_of(self, daemon_id):
        entry = self.store.data["daemons"].get(daemon_id)
        if not entry:
            raise ActionError("unknown_daemon", id=daemon_id)
        return Path(entry["home"])

    def refresh_pm2(self):
        """Looks for pm2 again: it may have been installed after the monitor started."""
        self.pm2_path = find_pm2(self.store.data["pm2Path"])
        return self.pm2_path

    def run_pm2(self, daemon_id, args, timeout=60, cwd=None):
        if not self.pm2_path:
            raise ActionError("pm2_not_found")
        home = self.home_of(daemon_id)
        return subprocess.run([self.pm2_path, *args], env=pm2_environment(self.pm2_path, home),
                              capture_output=True, text=True, timeout=timeout, cwd=cwd, **subprocess_flags())

    def read_live(self, daemon_id):
        """Live processes from the daemon. Never called on a stopped daemon: 'pm2 jlist' would start an empty one."""
        out = self.run_pm2(daemon_id, ["jlist"], timeout=15).stdout
        try:
            return json.loads(out[out.index("["):])  # pm2 sometimes prints warnings before the JSON
        except ValueError as e:
            raise ActionError("pm2_bad_output", detail=str(e))

    def live_entry(self, daemon_id, name):
        if not daemon_alive(self.home_of(daemon_id)):
            return None
        return next((p for p in self.read_live(daemon_id) if p.get("name") == name), None)

    # --- scan ---------------------------------------------------------------
    def scan(self):
        """Registers newly found pm2 daemons. Known ones keep their id and label."""
        with self.store.lock:
            changed = False
            for home in discover_homes(self.store.data["extraHomes"]):
                if self.store.daemon_id_for_home(home) is None:
                    taken = set(self.store.data["daemons"])
                    self.store.register_daemon(make_daemon_id(home, taken), home)
                    changed = True
            if changed:
                self.store.save()
            self.last_scan = time.time()

    # --- state --------------------------------------------------------------
    def snapshot(self):
        if time.time() - self.last_scan > SCAN_INTERVAL_SECONDS:
            self.scan()
        now_ms = time.time() * 1000
        daemons, procs, specs_changed = [], [], False
        for daemon_id, entry in list(self.store.data["daemons"].items()):
            home = Path(entry["home"])
            info = {"id": daemon_id, "label": entry["label"], "home": str(home),
                    "hidden": entry["hidden"], "alive": False, "error": None, "errorParams": {}}
            daemons.append(info)
            if entry["hidden"]:
                continue
            if not home.is_dir():
                info["error"] = "folder_missing"
                continue
            dump = read_dump(home)
            live = None
            if daemon_alive(home):
                info["alive"] = True
                try:
                    live = self.read_live(daemon_id)
                except ActionError as e:
                    info["error"], info["errorParams"] = e.code, e.params
                except (subprocess.SubprocessError, OSError) as e:
                    info["error"], info["errorParams"] = "read_failed", {"detail": str(e)}
            else:
                info["error"] = "daemon_stopped"
            seen = set()
            for item in live or []:
                pm2_env = item.get("pm2_env", {})
                seen.add(item.get("name"))
                specs_changed |= self._remember(daemon_id, item.get("name"), extract_launch_spec(pm2_env), overwrite=True)
                procs.append(self._proc_row(daemon_id, item.get("name"), pm2_env, item, now_ms))
            if live is None:  # daemon down: recover the config from the dump (with a live daemon the dump may be stale)
                for pm2_env in dump:
                    specs_changed |= self._remember(daemon_id, pm2_env["name"], extract_launch_spec(pm2_env), overwrite=False)
                    if pm2_env["name"] not in seen:
                        seen.add(pm2_env["name"])
                        procs.append(self._proc_row(daemon_id, pm2_env["name"], pm2_env, None, now_ms, status="offline"))
            for key, saved in self.store.data["processes"].items():
                saved_daemon, name = split_key(key)
                if saved_daemon == daemon_id and name not in seen and saved.get("spec"):
                    seen.add(name)
                    procs.append(self._proc_row(daemon_id, name, {}, None, now_ms, status="absent"))
        if specs_changed:
            with self.store.lock:
                self.store.save()
        domains = [{"name": n, **cfg} for n, cfg in sorted(self.store.data["domains"].items())]
        return {"time": time.time(), "pm2": self.pm2_path, "warning": self.store.warning,
                "version": __version__, "issuesUrl": ISSUES_URL,
                "configPath": str(self.store.path), "daemons": daemons, "domains": domains,
                "procs": procs, "jobs": self.active_jobs()}

    def _remember(self, daemon_id, name, spec, overwrite):
        """Stores the launch spec; without overwrite an already saved one is left alone."""
        key = f"{daemon_id}/{name}"
        with self.store.lock:
            has_spec = bool((self.store.data["processes"].get(key) or {}).get("spec"))
            if has_spec and not overwrite:
                return False
            return self.store.remember_spec(key, spec)

    def _proc_row(self, daemon_id, name, pm2_env, item, now_ms, status=None):
        key = f"{daemon_id}/{name}"
        saved = self.store.data["processes"].get(key) or {}
        status = status or pm2_env.get("status")
        online = status == "online"
        monit = (item or {}).get("monit", {})
        return {
            "key": key, "name": name, "daemon": daemon_id, "status": status,
            "pid": (item or {}).get("pid") or None,
            "cpu": monit.get("cpu", 0), "memory": monit.get("memory", 0),
            "uptime": (now_ms - pm2_env["pm_uptime"]) / 1000 if online and pm2_env.get("pm_uptime") else None,
            "restarts": pm2_env.get("restart_time", 0), "unstable": pm2_env.get("unstable_restarts", 0),
            "cwd": pm2_env.get("pm_cwd") or (saved.get("spec") or {}).get("cwd"),
            "domain": saved.get("domain"), "order": saved.get("order", DEFAULT_ORDER),
        }

    def find_logs(self, key):
        """Log paths as reported by pm2 itself (live or from the dump), never guessed."""
        daemon_id, name = split_key(key)
        item = self.live_entry(daemon_id, name)
        pm2_env = (item or {}).get("pm2_env") or next(
            (e for e in read_dump(self.home_of(daemon_id)) if e["name"] == name), None)
        if not pm2_env:
            return None, None
        return pm2_env.get("pm_out_log_path"), pm2_env.get("pm_err_log_path")

    # --- single process actions ---------------------------------------------
    def _mutation_lock(self, daemon_id):
        with self.jobs_lock:
            return self.mutation_locks.setdefault(daemon_id, threading.Lock())

    def _write_ecosystem(self, daemon_id, name, spec):
        app = {"name": name, "script": spec["script"], **{k: v for k, v in spec.items() if k != "script"}}
        directory = self.store.directory / "ecosystems"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{daemon_id}.json"
        path.write_text(json.dumps({"apps": [app]}, indent=2), encoding="utf-8")
        return path

    def perform(self, key, action):
        """Runs start/stop/restart and returns pm2's output. Raises ActionError on failure."""
        if action not in ACTIONS:
            raise ActionError("invalid_action")
        daemon_id, name = split_key(key)
        with self._mutation_lock(daemon_id):
            item = self.live_entry(daemon_id, name)
            online = bool(item) and item.get("pm2_env", {}).get("status") == "online"
            if action == "stop":
                if not item:
                    raise ActionError("process_not_in_daemon")
                args = ["stop", name]
            elif item and (action == "restart" and online):
                args = ["restart", name]
            elif item:
                args = ["start", name]
            else:
                spec = (self.store.data["processes"].get(key) or {}).get("spec")
                if not spec or not spec.get("script"):
                    raise ActionError("no_saved_spec")
                args = ["start", str(self._write_ecosystem(daemon_id, name, spec))]
            result = self.run_pm2(daemon_id, args)
        output = strip_ansi(result.stdout + result.stderr)[-2000:]
        if result.returncode != 0:
            raise ActionError("pm2_failed", output=output)
        return output

    def wait_started(self, key, timeout):
        """Waits until the process is online and stays so for STABLE_SECONDS; False on error or timeout."""
        daemon_id, name = split_key(key)
        deadline = time.time() + timeout
        while time.time() < deadline:
            item = self.live_entry(daemon_id, name)
            status = (item or {}).get("pm2_env", {}).get("status")
            if status == "errored":
                return False
            if status == "online":
                time.sleep(STABLE_SECONDS)
                again = self.live_entry(daemon_id, name)
                if (again or {}).get("pm2_env", {}).get("status") == "online":
                    return True
            time.sleep(1)
        return False

    # --- per-domain actions -------------------------------------------------
    def domain_members(self, domain):
        """Domain members in start order (ascending order, then by key)."""
        members = [(entry.get("order", DEFAULT_ORDER), key)
                   for key, entry in self.store.data["processes"].items() if entry.get("domain") == domain]
        return [key for _, key in sorted(members)]

    def start_domain_job(self, domain, action):
        if domain not in self.store.data["domains"]:
            raise ActionError("unknown_domain")
        if action not in ACTIONS:
            raise ActionError("invalid_action")
        with self.jobs_lock:
            if any(j["domain"] == domain and j["state"] == "running" for j in self.jobs.values()):
                raise ActionError("domain_busy", domain=domain)
            job = {"id": uuid.uuid4().hex[:8], "domain": domain, "action": action,
                   "state": "running", "steps": [], "started": time.time()}
            self.jobs[job["id"]] = job
            for old in sorted(self.jobs.values(), key=lambda j: j["started"])[:-MAX_JOBS_KEPT]:
                self.jobs.pop(old["id"], None)
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return job["id"]

    def _is_online(self, key):
        daemon_id, name = split_key(key)
        try:
            item = self.live_entry(daemon_id, name)
        except (ActionError, subprocess.SubprocessError, OSError):
            return False
        return bool(item) and item.get("pm2_env", {}).get("status") == "online"

    def _step(self, job, key, label, ok, message="", **params):
        """label and message are codes translated by the UI."""
        job["steps"].append({"key": key, "label": label, "ok": ok, "message": message, "params": params})

    def _run_job(self, job):
        domain, action = job["domain"], job["action"]
        timeout = self.store.data["domains"][domain]["startTimeout"]
        members = self.domain_members(domain)
        try:
            if action in ("stop", "restart"):
                for key in reversed(members):  # shut down in the reverse of the start order
                    if self._is_online(key):
                        self.perform(key, "stop")
                        self._step(job, key, "stop", True)
                    else:
                        self._step(job, key, "already_stopped", True)
            if action in ("start", "restart"):
                for key in members:
                    if action == "start" and self._is_online(key):
                        self._step(job, key, "already_running", True)
                        continue
                    self.perform(key, "start")
                    if not self.wait_started(key, timeout):
                        self._step(job, key, "start", False, "start_timeout", timeout=timeout)
                        job["state"] = "failed"
                        return
                    self._step(job, key, "start", True)
            job["state"] = "done"
        except ActionError as e:
            self._step(job, "", "error", False, e.code, **e.params)
            job["state"] = "failed"
        except (subprocess.SubprocessError, OSError) as e:
            self._step(job, "", "error", False, "error_detail", detail=str(e))
            job["state"] = "failed"

    def active_jobs(self):
        with self.jobs_lock:
            return [dict(j) for j in self.jobs.values() if j["state"] == "running"]

    def get_job(self, job_id):
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            return dict(job, steps=list(job["steps"])) if job else None

    # --- config changes -----------------------------------------------------
    def apply_config(self, request):
        op = request.get("op")
        store = self.store
        with store.lock:
            if op == "scan":
                self.scan()
                return
            if op == "setProcess":
                key = request.get("key", "")
                if split_key(key)[0] not in store.data["daemons"]:
                    raise ActionError("unknown_process")
                domain = (request.get("domain") or "").strip()[:40]
                store.set_process(key, domain=domain or None, order=request.get("order"),
                                  clear_domain="domain" in request and not domain)
            elif op == "createDomain":
                name = (request.get("name") or "").strip()[:40]
                if not name:
                    raise ActionError("empty_domain_name")
                store.ensure_domain(name)
            elif op == "renameDomain":
                new_name = (request.get("new") or "").strip()[:40]
                if not new_name:
                    raise ActionError("empty_domain_name")
                try:
                    store.rename_domain(request.get("old"), new_name)
                except ValueError:
                    raise ActionError("domain_rename_invalid")
            elif op == "deleteDomain":
                store.delete_domain(request.get("name"))
            elif op == "setDomainTimeout":
                if request.get("name") not in store.data["domains"]:
                    raise ActionError("unknown_domain")
                store.set_domain_timeout(request["name"], request.get("seconds", 30))
            elif op == "updateDaemon":
                if request.get("id") not in store.data["daemons"]:
                    raise ActionError("unknown_daemon", id=request.get("id"))
                store.update_daemon(request["id"], label=request.get("label"), hidden=request.get("hidden"))
            elif op == "addHome":
                home = Path(str(request.get("home", "")).strip()).expanduser()
                if not looks_like_pm2_home(home):
                    raise ActionError("not_pm2_home")
                store.add_extra_home(home)
                self.scan()
            elif op == "forgetProcess":
                store.forget_process(request.get("key"))
            else:
                raise ActionError("unknown_config_op")
            store.save()
