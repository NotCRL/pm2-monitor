"""Persistent configuration: known daemons, domains, start order and launch specs."""
import json
import os
import threading
import time
from pathlib import Path

from .osenv import default_config_file, resolve_config_file

DEFAULT_START_TIMEOUT = 30
DEFAULT_ORDER = 100


def empty_config():
    return {"version": 1, "pm2Path": None, "extraHomes": [], "daemons": {}, "domains": {}, "processes": {}}


class ConfigStore:
    def __init__(self, location=None):
        """location: a .json file or a directory; if missing, PM2_MONITOR_CONFIG or the per-OS directory."""
        self.path = resolve_config_file(location) if location else default_config_file()
        self.directory = self.path.parent
        self.lock = threading.RLock()
        self.warning = None  # {"code": ..., "params": {...}}, translated by the UI
        self.data = self._load()

    def _load(self):
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return empty_config()
        except (OSError, ValueError):
            # Unreadable config: keep it aside instead of silently overwriting it
            backup = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
            try:
                os.replace(self.path, backup)
                self.warning = {"code": "config_corrupt", "params": {"backup": backup.name}}
            except OSError:
                self.warning = {"code": "config_corrupt_locked", "params": {}}
            return empty_config()
        return {**empty_config(), **loaded}

    def save(self):
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)  # atomic write: a crash never leaves a half-written file

    # --- daemons ------------------------------------------------------------
    def daemon_id_for_home(self, home):
        for daemon_id, entry in self.data["daemons"].items():
            if entry["home"] == str(home):
                return daemon_id
        return None

    def register_daemon(self, daemon_id, home):
        self.data["daemons"][daemon_id] = {"home": str(home), "label": daemon_id, "hidden": False}

    def update_daemon(self, daemon_id, label=None, hidden=None):
        entry = self.data["daemons"][daemon_id]
        if label is not None:
            entry["label"] = label.strip() or daemon_id
        if hidden is not None:
            entry["hidden"] = bool(hidden)

    def add_extra_home(self, home):
        if str(home) not in self.data["extraHomes"]:
            self.data["extraHomes"].append(str(home))

    # --- domains ------------------------------------------------------------
    def ensure_domain(self, name):
        self.data["domains"].setdefault(name, {"startTimeout": DEFAULT_START_TIMEOUT})

    def set_domain_timeout(self, name, seconds):
        self.data["domains"][name]["startTimeout"] = max(1, int(seconds))

    def rename_domain(self, old, new):
        if old not in self.data["domains"] or new in self.data["domains"]:
            raise ValueError("unknown domain or name already in use")
        self.data["domains"][new] = self.data["domains"].pop(old)
        for entry in self.data["processes"].values():
            if entry.get("domain") == old:
                entry["domain"] = new

    def delete_domain(self, name):
        self.data["domains"].pop(name, None)
        for entry in self.data["processes"].values():
            if entry.get("domain") == name:
                entry["domain"] = None

    # --- processes ----------------------------------------------------------
    def process_entry(self, key):
        return self.data["processes"].setdefault(key, {"domain": None, "order": DEFAULT_ORDER, "spec": None})

    def remember_spec(self, key, spec):
        """Updates the launch spec; True if it changed (and so must be written to disk)."""
        entry = self.process_entry(key)
        if entry.get("spec") == spec:
            return False
        entry["spec"] = spec
        return True

    def set_process(self, key, domain=None, order=None, clear_domain=False):
        entry = self.process_entry(key)
        if clear_domain:
            entry["domain"] = None
        elif domain is not None:
            self.ensure_domain(domain)
            entry["domain"] = domain
        if order is not None:
            entry["order"] = int(order)

    def forget_process(self, key):
        self.data["processes"].pop(key, None)
