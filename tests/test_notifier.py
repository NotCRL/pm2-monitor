"""Notifications: what is detected, what each domain's preferences let through, history and messages."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pm2monitor import notifier
from pm2monitor.notifier import EVENT_TYPES, EventLog, MESSAGES, Watcher, format_text, normalize_settings
from pm2monitor.store import ConfigStore

MB = 1024 * 1024


def proc(name, status="online", daemon="d", domain=None, restarts=0, memory=10 * MB):
    return {"key": f"{daemon}/{name}", "name": name, "daemon": daemon, "status": status, "domain": domain,
            "restarts": restarts, "memory": memory}


def snap(procs, alive=True, daemons=("d",)):
    return {"daemons": [{"id": d, "label": d, "hidden": False, "alive": alive} for d in daemons], "procs": procs}


class FakeMonitor:
    def __init__(self):
        self.store = ConfigStore(tempfile.mkdtemp())
        self.expected = set()

    def is_expected(self, key):
        return key in self.expected


class WatcherTest(unittest.TestCase):
    def setUp(self):
        self.monitor = FakeMonitor()
        self.now = 1000.0
        self.delivered = []
        self.watcher = Watcher(self.monitor, EventLog(), deliver=lambda *a: self.delivered.append(a), clock=lambda: self.now)

    def types(self, procs, **kwargs):
        return [e["type"] for e in self.watcher.detect(snap(procs, **kwargs))]

    def test_first_snapshot_is_only_a_baseline(self):
        self.assertEqual(self.types([proc("a", "errored")]), [])

    def test_crash_stop_and_removal(self):
        self.types([proc("a"), proc("b"), proc("c")])
        found = self.types([proc("a", "errored"), proc("b", "stopped"), proc("c", "absent")])
        self.assertEqual(found, ["process_crashed", "process_stopped", "process_removed"])

    def test_changes_made_through_the_monitor_are_not_surprises(self):
        self.types([proc("a")])
        self.monitor.expected.add("d/a")
        self.assertEqual(self.types([proc("a", "stopped")]), [])
        self.assertEqual(self.types([proc("a", "online")]), [])

    def test_a_crash_is_reported_even_if_expected(self):
        self.types([proc("a")])
        self.monitor.expected.add("d/a")
        self.assertEqual(self.types([proc("a", "errored")]), ["process_crashed"])

    def test_recovery(self):
        self.types([proc("a", "errored")])
        self.assertEqual(self.types([proc("a", "online")]), ["process_recovered"])

    def test_restart_loop_is_summarised_once_a_minute(self):
        self.types([proc("a")])
        self.assertEqual(self.types([proc("a", restarts=2)]), ["process_restarted"])
        self.now += 10
        self.assertEqual(self.types([proc("a", restarts=5)]), [])  # still cooling down, counted for later
        self.now += 60
        events = self.watcher.detect(snap([proc("a", restarts=9)]))
        self.assertEqual([e["params"]["count"] for e in events], [7])  # 9 - 2 reported before

    def test_daemon_down_explains_its_processes(self):
        self.types([proc("a", domain="shop"), proc("b", domain="shop"), proc("c")])
        events = self.watcher.detect(snap([proc("a", "offline", domain="shop"), proc("b", "offline", domain="shop"),
                                           proc("c", "offline")], alive=False))
        self.assertEqual(sorted((e["type"], e["scope"], e["params"]["count"]) for e in events),
                         [("daemon_stopped", "", 1), ("daemon_stopped", "shop", 2)])

    def test_daemon_back_does_not_flood_with_recoveries(self):
        self.types([proc("a", "offline")], alive=False)
        self.assertEqual(self.types([proc("a", "online")]), ["daemon_started"])

    def test_memory_limit_warns_once_until_it_drops(self):
        self.monitor.store.data["domains"]["shop"] = {"startTimeout": 30, "notify": {"memoryMb": 100}}
        self.types([proc("a", domain="shop")])
        self.assertEqual(self.types([proc("a", domain="shop", memory=150 * MB)]), ["memory_high"])
        self.assertEqual(self.types([proc("a", domain="shop", memory=160 * MB)]), [])
        self.assertEqual(self.types([proc("a", domain="shop", memory=50 * MB)]), [])
        self.assertEqual(self.types([proc("a", domain="shop", memory=150 * MB)]), ["memory_high"])


class PreferencesTest(unittest.TestCase):
    def setUp(self):
        self.monitor = FakeMonitor()
        self.monitor.store.data["domains"]["shop"] = {"startTimeout": 30}
        self.delivered = []
        self.log = EventLog()
        self.watcher = Watcher(self.monitor, self.log, deliver=lambda *a: self.delivered.append(a))

    def raw(self, event_type="process_crashed", scope="shop"):
        return self.watcher._raw(event_type, scope, "d/a", "a", status="errored", count=1, daemon="d")

    def test_defaults_let_errors_and_warnings_through_but_not_info(self):
        self.assertIsNotNone(self.watcher.publish(self.raw("process_crashed")))
        self.assertIsNotNone(self.watcher.publish(self.raw("process_stopped")))
        self.assertIsNone(self.watcher.publish(self.raw("process_recovered")))

    def test_levels_can_be_changed_per_domain(self):
        self.monitor.store.set_notify("shop", {"levels": ["info"]})
        self.assertIsNone(self.watcher.publish(self.raw("process_crashed")))
        self.assertIsNotNone(self.watcher.publish(self.raw("process_recovered")))

    def test_a_domain_can_be_switched_off_or_a_kind_muted(self):
        self.monitor.store.set_notify("shop", {"enabled": False})
        self.assertIsNone(self.watcher.publish(self.raw()))
        self.monitor.store.set_notify("shop", {"mute": ["process_crashed"]})
        self.assertIsNone(self.watcher.publish(self.raw()))
        self.assertIsNotNone(self.watcher.publish(self.raw("process_stopped")))

    def test_each_domain_is_independent(self):
        self.monitor.store.data["domains"]["other"] = {"startTimeout": 30}
        self.monitor.store.set_notify("other", {"enabled": False})
        self.assertIsNone(self.watcher.publish(self.raw(scope="other")))
        self.assertIsNotNone(self.watcher.publish(self.raw(scope="shop")))

    def test_processes_without_domain_use_the_default_settings(self):
        self.monitor.store.set_notify("", {"levels": ["error"]})
        self.assertIsNotNone(self.watcher.publish(self.raw("process_crashed", scope="")))
        self.assertIsNone(self.watcher.publish(self.raw("process_stopped", scope="")))

    def test_event_carries_both_languages_and_its_channels(self):
        event = self.watcher.publish(self.raw())
        self.assertEqual(event["text"]["en"], "a crashed (status: errored).")
        self.assertEqual(event["text"]["it"], "a è andato in errore (stato: errored).")
        self.assertEqual(event["severity"], "error")
        self.assertEqual(event["channels"], {"browser": True, "sound": False, "desktop": False})

    def test_desktop_notification_only_when_the_domain_asks_for_it(self):
        self.watcher.publish(self.raw())
        import time
        time.sleep(0.05)
        self.assertEqual(self.delivered, [])
        self.monitor.store.data["language"] = "it"
        self.monitor.store.set_notify("shop", {"channels": {"desktop": True}})
        self.watcher.publish(self.raw())
        time.sleep(0.2)
        self.assertEqual(self.delivered[0][0], "pm2 monitor · shop")
        self.assertIn("è andato in errore", self.delivered[0][1])
        self.assertEqual(self.delivered[0][2], "error")

    def test_finished_domain_jobs(self):
        failed = {"domain": "shop", "action": "start", "state": "failed",
                  "steps": [{"key": "d/db", "ok": True}, {"key": "d/api", "ok": False}]}
        self.watcher.job_finished(failed)
        self.monitor.store.set_notify("shop", {"levels": ["error", "info"]})
        self.watcher.job_finished({"domain": "shop", "action": "stop", "state": "done", "steps": []})
        events = self.log.since(0)
        self.assertEqual([e["type"] for e in events], ["job_failed", "job_done"])
        self.assertEqual(events[0]["text"]["en"], "Start of \"shop\" was interrupted at api.")
        self.assertEqual(events[1]["text"]["it"], "Arresto di \"shop\" completato.")


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(normalize_settings(None), notifier.DEFAULT_NOTIFY)

    def test_garbage_is_cleaned(self):
        cleaned = normalize_settings({"enabled": 0, "levels": ["error", "bogus"], "mute": ["nope", "job_done"],
                                      "memoryMb": "-5", "channels": {"sound": 1, "other": True}})
        self.assertEqual(cleaned, {"enabled": False, "levels": ["error"], "mute": ["job_done"], "memoryMb": 0,
                                   "channels": {"browser": True, "sound": True, "desktop": False}})


class EventLogTest(unittest.TestCase):
    def test_history_survives_a_restart_and_ids_keep_growing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            first = EventLog(path)
            first.add({"type": "a"})
            first.add({"type": "b"})
            again = EventLog(path)
            self.assertEqual([e["id"] for e in again.since(0)], [1, 2])
            self.assertEqual(again.add({"type": "c"})["id"], 3)
            self.assertEqual([e["type"] for e in again.since(2)], ["c"])

    def test_old_events_are_dropped_and_clear_works(self):
        log = EventLog(limit=3)
        for n in range(5):
            log.add({"n": n})
        self.assertEqual([e["n"] for e in log.since(0)], [2, 3, 4])
        log.clear()
        self.assertEqual((log.since(0), log.latest_id()), ([], 0))

    def test_corrupt_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.json"
            path.write_text("{broken")
            self.assertEqual(EventLog(path).since(0), [])


class MessagesTest(unittest.TestCase):
    def test_both_languages_have_the_same_messages_and_cover_every_event(self):
        self.assertEqual(set(MESSAGES["en"]), set(MESSAGES["it"]))
        self.assertTrue(set(EVENT_TYPES) <= set(MESSAGES["en"]))

    def test_every_message_formats_with_the_params_the_watcher_sends(self):
        params = {"name": "api", "status": "errored", "count": 2, "memory": 120, "limit": 100, "daemon": "d",
                  "domain": "shop", "action": "Start"}
        for lang in notifier.LANGUAGES:
            for event_type in EVENT_TYPES:
                self.assertTrue(format_text(event_type, params, lang))


if __name__ == "__main__":
    unittest.main()
