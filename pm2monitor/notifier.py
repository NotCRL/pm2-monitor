"""Notifications: notices what changed in the pm2 state and tells the user, per domain.

A background watcher compares each new snapshot with the previous one and turns the differences into
events (a process crashed, a daemon stopped, ...). Every domain chooses which severities and which kinds of
event it wants, and through which channels: the page (history, pop-ups, browser notifications, sound) and,
optionally, the operating system's own notifications, which also work while the page is closed.
"""
import json
import os
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path

from .osenv import IS_WINDOWS, subprocess_flags, os_name

SEVERITIES = ("error", "warning", "info")
LANGUAGES = ("en", "it")
EVENT_TYPES = {  # event type -> severity
    "process_crashed": "error", "daemon_stopped": "error", "job_failed": "error",
    "process_stopped": "warning", "process_removed": "warning", "process_restarted": "warning", "memory_high": "warning",
    "process_recovered": "info", "daemon_started": "info", "job_done": "info",
}
DEFAULT_NOTIFY = {
    "enabled": True,
    "levels": ["error", "warning"],
    "mute": [],
    "memoryMb": 0,  # 0 = do not watch memory
    "channels": {"browser": True, "sound": False, "desktop": False},
}
WATCH_INTERVAL_SECONDS = 5
EXPECTED_SECONDS = 45  # changes made through this monitor are not "surprises" for this long
RESTART_COOLDOWN_SECONDS = 60  # a crash loop produces one notice a minute, not one every few seconds
MEMORY_RELEASE_RATIO = 0.9  # memory must drop below 90% of the limit before it can warn again
EVENTS_KEPT = 200

MESSAGES = {
    "en": {
        "process_crashed": "{name} crashed (status: {status}).",
        "process_stopped": "{name} stopped.",
        "process_removed": "{name} was removed from pm2.",
        "process_restarted": "{name} restarted by itself {count} time(s).",
        "memory_high": "{name} is using {memory} MB (limit {limit} MB).",
        "process_recovered": "{name} is back online.",
        "daemon_stopped": "The pm2 daemon \"{daemon}\" stopped: {count} process(es) of this group are down.",
        "daemon_started": "The pm2 daemon \"{daemon}\" is running again.",
        "job_failed": "{action} of \"{domain}\" was interrupted at {name}.",
        "job_done": "{action} of \"{domain}\" completed.",
        "title": "pm2 monitor · {scope}",
        "no_domain": "No domain",
        "test_title": "pm2 monitor",
        "test_body": "Test notification: if you can read this, desktop notifications work.",
    },
    "it": {
        "process_crashed": "{name} è andato in errore (stato: {status}).",
        "process_stopped": "{name} si è fermato.",
        "process_removed": "{name} è stato rimosso da pm2.",
        "process_restarted": "{name} si è riavviato da solo {count} volta/e.",
        "memory_high": "{name} usa {memory} MB (limite {limit} MB).",
        "process_recovered": "{name} è di nuovo online.",
        "daemon_stopped": "Il demone pm2 \"{daemon}\" si è fermato: {count} processo/i di questo gruppo sono giù.",
        "daemon_started": "Il demone pm2 \"{daemon}\" è di nuovo in esecuzione.",
        "job_failed": "{action} di \"{domain}\" interrotto su {name}.",
        "job_done": "{action} di \"{domain}\" completato.",
        "title": "pm2 monitor · {scope}",
        "no_domain": "Senza dominio",
        "test_title": "pm2 monitor",
        "test_body": "Notifica di prova: se leggi questo, le notifiche del desktop funzionano.",
    },
}
ACTION_WORDS = {
    "en": {"start": "Start", "stop": "Stop", "restart": "Restart"},
    "it": {"start": "Avvio", "stop": "Arresto", "restart": "Riavvio"},
}


def normalize_settings(raw):
    """Valid notification settings from whatever is stored: unknown values are dropped, gaps get defaults."""
    raw = raw if isinstance(raw, dict) else {}
    channels = raw.get("channels") if isinstance(raw.get("channels"), dict) else {}
    levels = raw.get("levels") if isinstance(raw.get("levels"), list) else DEFAULT_NOTIFY["levels"]
    mute = raw.get("mute") if isinstance(raw.get("mute"), list) else []
    try:
        memory = max(0, int(raw.get("memoryMb", 0)))
    except (TypeError, ValueError):
        memory = 0
    return {
        "enabled": bool(raw.get("enabled", True)),
        "levels": [level for level in SEVERITIES if level in levels],
        "mute": sorted({m for m in mute if m in EVENT_TYPES}),
        "memoryMb": memory,
        "channels": {name: bool(channels.get(name, default)) for name, default in DEFAULT_NOTIFY["channels"].items()},
    }


def format_text(event_type, params, language):
    template = MESSAGES.get(language, MESSAGES["en"])[event_type]
    return template.format(**{k: ("" if v is None else v) for k, v in params.items()})


# --- history ----------------------------------------------------------------------------------------
class EventLog:
    """The most recent events, kept in memory and in a small JSON file so they survive a restart."""

    def __init__(self, path=None, limit=EVENTS_KEPT):
        self.path = Path(path) if path else None
        self.limit = limit
        self.lock = threading.Lock()
        self.events = []
        self.next_id = 1
        self._load()

    def _load(self):
        if not self.path:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.events = [e for e in data.get("events", []) if isinstance(e, dict) and "id" in e][-self.limit:]
            self.next_id = max([data.get("next", 1)] + [e["id"] + 1 for e in self.events])
        except (OSError, ValueError, AttributeError, TypeError):
            self.events, self.next_id = [], 1

    def _save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"next": self.next_id, "events": self.events}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass  # history is a convenience: never let it break monitoring

    def add(self, event):
        with self.lock:
            event = dict(event, id=self.next_id)
            self.next_id += 1
            self.events = (self.events + [event])[-self.limit:]
            self._save()
            return event

    def since(self, after=0):
        with self.lock:
            return [e for e in self.events if e["id"] > after]

    def latest_id(self):
        with self.lock:
            return self.events[-1]["id"] if self.events else 0

    def clear(self):
        with self.lock:
            self.events = []
            self._save()


# --- operating system notifications ---------------------------------------------------------------------
def desktop_command(title, body, severity):
    """The command that shows a native notification on this OS, or None if the system has no way to."""
    system = os_name()
    if system == "linux":
        import shutil
        tool = shutil.which("notify-send")
        urgency = {"error": "critical", "warning": "normal"}.get(severity, "low")
        return [tool, "-u", urgency, "-a", "pm2 monitor", title, body] if tool else None
    if system == "macos":
        script = ["-e", "on run argv", "-e", "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run"]
        return ["osascript", *script, title, body]
    # Windows: a balloon/toast from a PowerShell one-liner; the text travels in environment variables, never in the script
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing;"
              "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information;"
              "$n.Visible = $true; $n.ShowBalloonTip(6000, $env:PM2MON_TITLE, $env:PM2MON_BODY, [System.Windows.Forms.ToolTipIcon]::None);"
              "Start-Sleep -Seconds 7; $n.Dispose()")
    return ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script]


def send_desktop(title, body, severity="info"):
    """Shows an operating-system notification. Returns (ok, detail); never raises."""
    command = desktop_command(title[:120], body[:300], severity)
    if not command:
        return False, "no_tool"
    env = dict(os.environ, PM2MON_TITLE=title[:120], PM2MON_BODY=body[:300])
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15 if not IS_WINDOWS else 20,
                                env=env, **subprocess_flags())
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return result.returncode == 0, (result.stderr or "").strip()[:200]


# --- the watcher ---------------------------------------------------------------------------------------------
class Watcher:
    def __init__(self, monitor, log, deliver=None, clock=time.time):
        self.monitor = monitor
        self.log = log
        self.deliver = deliver or send_desktop
        self.clock = clock
        self.previous = None  # (daemon alive map, processes by key) of the last snapshot
        self.reported_restarts = {}
        self.last_restart_notice = {}
        self.over_memory = set()
        self.thread = None

    # -- detecting changes
    def detect(self, snapshot):
        """Raw events (before the per-domain preferences) for what changed since the previous snapshot."""
        now = self.clock()
        daemons = {d["id"]: d for d in snapshot["daemons"] if not d["hidden"]}
        alive = {daemon_id: d["alive"] for daemon_id, d in daemons.items()}
        procs = {p["key"]: p for p in snapshot["procs"] if p["daemon"] in daemons}
        previous, self.previous = self.previous, (alive, procs)
        if previous is None:
            return []  # first look: this is the baseline, not news
        was_alive, was_procs = previous
        found, changed = [], set()
        for daemon_id, is_alive in alive.items():
            if daemon_id not in was_alive or was_alive[daemon_id] == is_alive:
                continue
            changed.add(daemon_id)
            members = Counter(p["domain"] or "" for p in procs.values() if p["daemon"] == daemon_id)
            for scope, count in members.items():
                found.append(self._raw("daemon_started" if is_alive else "daemon_stopped", scope,
                                       daemon=daemons[daemon_id]["label"], count=count))
        for key, proc in procs.items():
            if proc["daemon"] in changed or not alive[proc["daemon"]] or key not in was_procs:
                continue  # a daemon going up or down already explains its processes
            found.extend(self._process_events(key, proc, was_procs[key], now))
        return found

    def _raw(self, event_type, scope, key="", name="", **params):
        return {"type": event_type, "scope": scope, "key": key, "name": name, "params": dict(params, name=name)}

    def _process_events(self, key, proc, before, now):
        events, scope, name = [], proc["domain"] or "", proc["name"]
        status, was = proc["status"], before["status"]
        expected = self.monitor.is_expected(key)
        if status != was:
            if status == "errored":
                events.append(self._raw("process_crashed", scope, key, name, status=status))
            elif status == "stopped" and was == "online" and not expected:
                events.append(self._raw("process_stopped", scope, key, name))
            elif status == "absent" and was == "online" and not expected:
                events.append(self._raw("process_removed", scope, key, name))
            elif status == "online" and was != "online" and not expected:
                events.append(self._raw("process_recovered", scope, key, name))
        if status in ("online", "launching"):
            reported = self.reported_restarts.setdefault(key, before["restarts"])
            if proc["restarts"] > reported and now - self.last_restart_notice.get(key, 0) >= RESTART_COOLDOWN_SECONDS:
                events.append(self._raw("process_restarted", scope, key, name, count=proc["restarts"] - reported))
                self.reported_restarts[key] = proc["restarts"]
                self.last_restart_notice[key] = now
        limit = normalize_settings(self.monitor.store.get_notify(scope))["memoryMb"]
        if limit and status == "online":
            megabytes = round((proc["memory"] or 0) / (1024 * 1024))
            if megabytes > limit and key not in self.over_memory:
                self.over_memory.add(key)
                events.append(self._raw("memory_high", scope, key, name, memory=megabytes, limit=limit))
            elif megabytes < limit * MEMORY_RELEASE_RATIO:
                self.over_memory.discard(key)
        return events

    # -- applying the preferences and delivering
    def publish(self, raw):
        """Stores and delivers one raw event if its domain wants it. Returns the stored event or None."""
        settings = normalize_settings(self.monitor.store.get_notify(raw["scope"]))
        severity = EVENT_TYPES[raw["type"]]
        if not settings["enabled"] or severity not in settings["levels"] or raw["type"] in settings["mute"]:
            return None
        text = {lang: format_text(raw["type"], self._localized(raw["params"], lang), lang) for lang in LANGUAGES}
        event = self.log.add({
            "time": self.clock(), "severity": severity, "type": raw["type"], "scope": raw["scope"],
            "key": raw["key"], "name": raw["name"], "text": text, "channels": settings["channels"],
        })
        if settings["channels"]["desktop"]:
            language = self.monitor.store.data.get("language", "en")
            language = language if language in LANGUAGES else "en"
            scope = raw["scope"] or MESSAGES[language]["no_domain"]
            title = MESSAGES[language]["title"].format(scope=scope)
            threading.Thread(target=self.deliver, args=(title, text[language], severity), daemon=True).start()
        return event

    @staticmethod
    def _localized(params, language):
        params = dict(params)
        if "action" in params:
            params["action"] = ACTION_WORDS[language].get(params["action"], params["action"])
        return params

    def process(self, snapshot):
        return [e for e in (self.publish(raw) for raw in self.detect(snapshot)) if e]

    def job_finished(self, job):
        """Called by the monitor when a start / stop / restart of a whole domain ends."""
        failed = next((s for s in reversed(job["steps"]) if not s["ok"]), None)
        if job["state"] == "failed":
            name = failed["key"].split("/", 1)[-1] if failed and failed["key"] else ""
            raw = self._raw("job_failed", job["domain"], failed["key"] if failed else "", name,
                            domain=job["domain"], action=job["action"])
        else:
            raw = self._raw("job_done", job["domain"], "", "", domain=job["domain"], action=job["action"])
        self.publish(raw)

    # -- running
    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            try:
                self.process(self.monitor.snapshot())
            except Exception:  # noqa: BLE001 - a bad cycle must not kill the watcher
                pass
            time.sleep(WATCH_INTERVAL_SECONDS)
