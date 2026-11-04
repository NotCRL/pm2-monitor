"""Application logic: process state, single and per-domain actions, config changes.

User-facing messages are not built here: errors carry a stable `code` plus `params`,
and the UI translates them (see the `err.*` entries in index.html).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import ISSUES_URL, __version__, classify, ports
from .discovery import (daemon_alive, discover_homes, extract_launch_spec, looks_like_pm2_home,
                        make_daemon_id, read_dump)
from .notifier import EVENT_TYPES, LANGUAGES, normalize_settings
from .osenv import HOME, IS_WINDOWS, find_pm2, pm2_environment, subprocess_flags
from .store import BUILTIN_KINDS, DEFAULT_ORDER

ACTIONS = {"start", "stop", "restart"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LOG_TAIL_BYTES = 256 * 1024
SCAN_INTERVAL_SECONDS = 30
STABLE_SECONDS = 2  # a process counts as started only if it stays online for this long
MAX_JOBS_KEPT = 20
OPEN_WAIT_SECONDS = 3  # a file manager that is still running after this long has opened the folder
RETRY_PROBE_SECONDS = 60.0  # a port that did not answer like a web server may just not have been ready
PORTS_TTL_SECONDS = 8.0  # scanning the system for listening ports is dearer than reading pm2: do it less often
SNAPSHOT_TTL_SECONDS = 2.0  # the page and the notification watcher share one reading of pm2


TAXONOMY_OPS = frozenset({"createKind", "renameKind", "deleteKind", "setKind", "createLabel", "renameLabel",
                          "deleteLabel", "setLabelColor", "setLabels"})


class ActionError(Exception):
    """A failure the user should see: `code` identifies the message, `params` fills its blanks."""

    def __init__(self, code, **params):
        super().__init__(f"{code} {params}" if params else code)
        self.code = code
        self.params = params


def open_in_file_manager(path):
    """Shows a folder in the system's file manager. The caller decides which folder: this never takes one from a request."""
    path = str(path)
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606 - Windows only; opens the folder in Explorer
        return
    if sys.platform == "darwin":
        command = ["open", path]
    else:
        tool = shutil.which("xdg-open")
        if not tool:
            raise ActionError("open_unavailable")
        command = [tool, path]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        failed = process.wait(timeout=OPEN_WAIT_SECONDS) != 0
    except subprocess.TimeoutExpired:
        return  # still running: the file manager is up and keeps the command alive
    if failed:
        raise ActionError("open_failed")


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
        self.snapshot_lock = threading.Lock()
        self.snapshot_cache = (0.0, None)
        self.ports_cache = (0.0, {})
        self.probe_cache = {}  # (pid, port) -> (is a web page, when it was checked)
        self.expected = {}  # process key -> until when a change is expected (made through this monitor)
        self.on_job_finished = None
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

    def run_pm2(self, daemon_id, args, timeout=60, cwd=None, env_extra=None):
        if not self.pm2_path:
            raise ActionError("pm2_not_found")
        home = self.home_of(daemon_id)
        if args and args[0] != "jlist":
            self.invalidate_snapshot()  # anything but a read changes what the next snapshot must show
        env = {**pm2_environment(self.pm2_path, home), **(env_extra or {})}   # e.g. the Java a project needs
        return subprocess.run([self.pm2_path, *args], env=env,
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
    def invalidate_snapshot(self):
        self.snapshot_cache = (0.0, None)

    def expect(self, key, seconds=45):
        """A change of this process is about to be made through the monitor: it is not a surprise."""
        self.expected[key] = time.time() + seconds

    def is_expected(self, key):
        return self.expected.get(key, 0) > time.time()

    def snapshot(self):
        with self.snapshot_lock:
            taken, cached = self.snapshot_cache
            if cached is not None and time.time() - taken < SNAPSHOT_TTL_SECONDS:
                return cached
            fresh = self._build_snapshot()
            self.snapshot_cache = (time.time(), fresh)
            return fresh

    def _build_snapshot(self):
        if time.time() - self.last_scan > SCAN_INTERVAL_SECONDS:
            self.scan()
        now_ms = time.time() * 1000
        daemons, procs, specs_changed, link_sources = [], [], False, []
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
                row = self._proc_row(daemon_id, item.get("name"), pm2_env, item, now_ms)
                procs.append(row)
                if row["status"] == "online" and row["pid"]:
                    link_sources.append((row, row["pid"], pm2_env.get("pm_out_log_path")))
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
        self._attach_links(link_sources)
        if specs_changed:
            with self.store.lock:
                self.store.save()
        domains = [{"name": n, **cfg, "notify": normalize_settings(cfg.get("notify"))}
                   for n, cfg in sorted(self.store.data["domains"].items())]
        return {"time": time.time(), "language": self.store.data.get("language", "en"),
                "kinds": {"builtin": list(BUILTIN_KINDS), "custom": list(self.store.data["kinds"])}, "labels": self._label_list(),
                "notifyDefault": normalize_settings(self.store.data.get("notifyDefault")), "probeLinks": self.store.data.get("probeLinks", True), "eventTypes": EVENT_TYPES, "pm2": self.pm2_path, "warning": self.store.warning,
                "version": __version__, "home": str(HOME), "issuesUrl": ISSUES_URL,
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

    def _label_list(self):
        counts = {}
        for entry in self.store.data["processes"].values():
            for label in entry.get("labels", []):
                counts[label] = counts.get(label, 0) + 1
        return [{"name": name, "color": meta.get("color"), "count": counts.get(name, 0)}
                for name, meta in self.store.data["labels"].items()]

    def _attach_links(self, sources):
        """Adds to each running process the addresses it answers on (localhost:PORT), if it listens on any."""
        if not sources:
            return
        taken, found = self.ports_cache
        pids = {pid for _, pid, _ in sources}
        if time.time() - taken > PORTS_TTL_SECONDS or not pids <= set(found):
            scanned = ports.listening_ports(pids)
            found = {pid: scanned.get(pid, []) for pid in pids}   # a failed scan is remembered too, not retried at every poll
            self.ports_cache = (time.time(), found)
        hints = {pid: ports.log_hints(ports.read_log_hint(out_log)) if found.get(pid) else {} for _, pid, out_log in sources}
        probing = self.store.data.get("probeLinks", True)
        if probing:
            self._probe([(pid, port) for pid in pids for port in ports.needs_check(found.get(pid, []), hints.get(pid, {}))])
        for row, pid, _ in sources:
            web = {port for port in found.get(pid, []) if self.probe_cache.get((pid, port), (False,))[0]} if probing else None
            row["links"] = ports.build_links(found.get(pid, []), hints.get(pid, {}), web)

    def _probe(self, wanted):
        """Tests, in parallel and once per process, which of the listening ports answer like a web server."""
        now = time.time()
        live = set(wanted)
        self.probe_cache = {k: v for k, v in self.probe_cache.items() if k[0] in {pid for pid, _ in live} or now - v[1] < RETRY_PROBE_SECONDS}
        todo = [k for k in live if k not in self.probe_cache or (not self.probe_cache[k][0] and now - self.probe_cache[k][1] > RETRY_PROBE_SECONDS)]
        if not todo:
            return
        with ThreadPoolExecutor(max_workers=8) as pool:
            for key, answer in zip(todo, pool.map(lambda key: ports.speaks_http(key[1]), todo)):
                self.probe_cache[key] = (answer, now)

    def _proc_row(self, daemon_id, name, pm2_env, item, now_ms, status=None):
        key = f"{daemon_id}/{name}"
        saved = self.store.data["processes"].get(key) or {}
        status = status or pm2_env.get("status")
        online = status == "online"
        monit = (item or {}).get("monit", {})
        kind = saved.get("kind") if saved.get("kind") in self.store.all_kinds() else None
        return {
            "key": key, "name": name, "daemon": daemon_id, "status": status,
            "pid": (item or {}).get("pid") or None,
            "cpu": monit.get("cpu", 0), "memory": monit.get("memory", 0),
            "uptime": (now_ms - pm2_env["pm_uptime"]) / 1000 if online and pm2_env.get("pm_uptime") else None,
            "restarts": pm2_env.get("restart_time", 0), "unstable": pm2_env.get("unstable_restarts", 0),
            "cwd": pm2_env.get("pm_cwd") or (saved.get("spec") or {}).get("cwd"),
            "domain": saved.get("domain"), "order": saved.get("order", DEFAULT_ORDER), "links": [],
            "kind": kind, "kindAuto": None if kind else classify.guess_kind(saved.get("spec")),
            "labels": [label for label in saved.get("labels", []) if label in self.store.data["labels"]],
        }

    def open_folder(self, key):
        """Opens the working folder of a process the monitor knows (never a path coming from the request)."""
        daemon_id, _ = split_key(key)
        if daemon_id not in self.store.data["daemons"]:
            raise ActionError("unknown_daemon", id=daemon_id)
        row = next((p for p in self.snapshot()["procs"] if p["key"] == key), None)
        if not row:
            raise ActionError("unknown_process")
        folder = row.get("cwd")
        if not folder or not os.path.isdir(folder):
            raise ActionError("folder_not_found", path=str(folder or ""))
        open_in_file_manager(folder)

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
        self.expect(key)
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
        try:
            self._run_job_steps(job)
        finally:
            if self.on_job_finished:
                try:
                    self.on_job_finished(job)
                except Exception:  # noqa: BLE001 - telling the user must never break the job
                    pass

    def _run_job_steps(self, job):
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
    def _apply_taxonomy(self, op, request):
        """Types (backend / frontend / your own) and labels of processes. Errors become codes the UI translates."""
        store, name, subject = self.store, request.get("name"), "label" if "abel" in op else "kind"
        try:
            if op in ("setKind", "setLabels") and split_key(request.get("key", ""))[0] not in store.data["daemons"]:
                raise ActionError("unknown_process")
            if op == "createKind":
                store.add_kind(name)
            elif op == "renameKind":
                store.rename_kind(request.get("old"), request.get("new"))
            elif op == "deleteKind":
                store.delete_kind(name)
            elif op == "setKind":
                store.set_kind(request["key"], request.get("kind"))
            elif op == "createLabel":
                store.add_label(name, request.get("color"))
            elif op == "renameLabel":
                store.rename_label(request.get("old"), request.get("new"))
            elif op == "deleteLabel":
                store.delete_label(name)
            elif op == "setLabelColor":
                store.set_label_color(name, request.get("color"))
            elif op == "setLabels":
                store.set_labels(request["key"], request.get("labels") if isinstance(request.get("labels"), list) else [])
        except ValueError as e:
            raise ActionError({"bad_name": "bad_label_name", "exists": f"{subject}_exists", "unknown": f"unknown_{subject}",
                               "bad_color": "bad_color"}.get(str(e), "bad_label_name"))

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
            elif op == "setNotify":
                scope = (request.get("scope") or "").strip()
                if scope and scope not in store.data["domains"]:
                    raise ActionError("unknown_domain")
                store.set_notify(scope, normalize_settings(request.get("settings")))
            elif op in TAXONOMY_OPS:
                self._apply_taxonomy(op, request)
            elif op == "setProbeLinks":
                store.data["probeLinks"] = bool(request.get("enabled"))
                self.probe_cache.clear()
                self.ports_cache = (0.0, {})
            elif op == "setLanguage":
                if request.get("language") in LANGUAGES:
                    store.data["language"] = request["language"]
            else:
                raise ActionError("unknown_config_op")
            store.save()
            self.invalidate_snapshot()
