"""Links to running apps: reading listening ports, telling web pages from other services, building the URLs."""
import http.server
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from pm2monitor import ports, service
from pm2monitor.store import ConfigStore

PROC_NET_TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:0BB8 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 11111 1 0000000000000000 100 0 0 10 0
   1: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 22222 1 0000000000000000 100 0 0 10 0
   2: 0101A8C0:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 33333 1 0000000000000000 100 0 0 10 0
   3: 0100007F:1F91 0100007F:C350 01 00000000:00000000 00:00000000 00000000  1000        0 44444 1 0000000000000000 100 0 0 10 0
"""
LSOF = "p100\nf12\nn*:3000\nf13\nn127.0.0.1:3001\np200\nn[::1]:4000\nn192.168.1.5:5000\n"
NETSTAT = """  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       4321
  TCP    [::]:8080              [::]:0                 LISTENING       4321
  TCP    192.168.1.9:445        0.0.0.0:0              LISTENING       4
  TCP    127.0.0.1:50000        127.0.0.1:3000         ESTABLISHED     999
"""


class ParserTest(unittest.TestCase):
    def test_proc_net_tcp_keeps_only_listening_local_sockets(self):
        self.assertEqual(ports.parse_proc_net_tcp(PROC_NET_TCP), {11111: 3000, 22222: 8080})

    def test_ipv6_and_mapped_addresses(self):
        self.assertTrue(ports._hex_address_is_local("00000000000000000000000001000000"))     # ::1
        self.assertTrue(ports._hex_address_is_local("00000000000000000000000000000000"))     # ::
        self.assertTrue(ports._hex_address_is_local("0000000000000000FFFF00000100007F"))     # ::ffff:127.0.0.1
        self.assertFalse(ports._hex_address_is_local("0000000000000000FFFF00000101A8C0"))    # ::ffff:192.168.1.1

    def test_lsof(self):
        self.assertEqual(ports.parse_lsof(LSOF), {100: {3000, 3001}, 200: {4000}})

    def test_netstat_ignores_other_states_and_lan_addresses(self):
        self.assertEqual(ports.parse_netstat(NETSTAT), {4321: {3000, 8080}})

    def test_process_tree_follows_children_of_children(self):
        children = ports.parse_pid_pairs("10 1\n11 10\n12 11\n13 1\n")
        self.assertEqual(ports.process_tree(children, 10), {10, 11, 12})
        self.assertEqual(ports.parse_pid_pairs("5,1\n6,5\n"), {1: [5], 5: [6]})


class LinkTest(unittest.TestCase):
    def test_log_hints_give_scheme_and_path_and_survive_colours(self):
        log = "ready\n  Local: \x1b[1mhttp://localhost:3000/app\x1b[22m.\nsecure https://127.0.0.1:8443/\n"
        self.assertEqual(ports.log_hints(log), {3000: ("http", "/app"), 8443: ("https", "/")})

    def test_non_web_ports_never_become_links(self):
        self.assertEqual(ports.build_links([5432, 27017, 9229]), [])

    def test_only_checked_web_ports_are_kept_when_checking_is_on(self):
        links = ports.build_links([3000, 5701], web={3000})
        self.assertEqual([l["label"] for l in links], ["localhost:3000"])
        self.assertEqual(links[0]["url"], "http://localhost:3000/")

    def test_every_port_is_listed_when_checking_is_off(self):
        self.assertEqual([l["port"] for l in ports.build_links([5701, 3000], web=None)], [3000, 5701])

    def test_the_log_vouches_for_a_port_without_a_test(self):
        hints = {3000: ("http", "/")}
        self.assertEqual(ports.needs_check([3000, 5701, 443, 5432], hints), [5701])
        self.assertEqual([l["url"] for l in ports.build_links([3000], hints, web=set())], ["http://localhost:3000/"])

    def test_https_ports_get_an_https_address(self):
        self.assertEqual(ports.build_links([8443], web=set())[0]["url"], "https://localhost:8443/")


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ProbeTest(unittest.TestCase):
    def test_a_web_server_is_recognised_a_silent_service_and_a_closed_port_are_not(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        silent = socket.socket()
        silent.bind(("127.0.0.1", 0))
        silent.listen(5)                      # accepts connections, never answers: like a database
        self.addCleanup(silent.close)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.assertTrue(ports.speaks_http(server.server_address[1]))
        self.assertFalse(ports.speaks_http(silent.getsockname()[1], timeout=0.3))
        self.assertFalse(ports.speaks_http(free_port()))


@unittest.skipUnless(sys.platform.startswith("linux"), "reads /proc")
class LinuxScanTest(unittest.TestCase):
    def test_the_port_of_a_child_program_is_attributed_to_its_wrapper(self):
        port = free_port()
        # like `npm start`: a wrapper shell whose child is the real server
        wrapper = subprocess.Popen(["sh", "-c", f"{sys.executable} -m http.server {port} --bind 127.0.0.1; true"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(wrapper.wait)
        self.addCleanup(wrapper.terminate)
        deadline = time.time() + 10
        while time.time() < deadline and port not in ports.listening_ports({wrapper.pid}).get(wrapper.pid, []):
            time.sleep(0.2)
        self.assertIn(port, ports.listening_ports({wrapper.pid})[wrapper.pid])


class SnapshotLinksTest(unittest.TestCase):
    """Monitor._attach_links with the system and the network replaced by fakes."""

    def setUp(self):
        with mock.patch("pm2monitor.service.discover_homes", return_value=[]):
            self.monitor = service.Monitor(ConfigStore(tempfile.mkdtemp()))
        self.rows = [{"status": "online", "pid": 10, "links": []}, {"status": "online", "pid": 20, "links": []}]
        self.sources = [(self.rows[0], 10, None), (self.rows[1], 20, None)]

    def attach(self, probe_answer=lambda port: port == 3000):
        found = {10: [3000, 5701], 20: []}
        with mock.patch.object(ports, "listening_ports", return_value=found) as scan, \
             mock.patch.object(ports, "speaks_http", side_effect=probe_answer) as probe:
            self.monitor._attach_links(self.sources)
        return scan, probe

    def test_links_come_only_from_ports_that_answer_like_a_web_page(self):
        self.attach()
        self.assertEqual([l["label"] for l in self.rows[0]["links"]], ["localhost:3000"])
        self.assertEqual(self.rows[1]["links"], [])

    def test_a_port_is_tested_once_not_at_every_snapshot(self):
        _, first = self.attach()
        _, second = self.attach()
        self.assertEqual(first.call_count, 2)       # 3000 and 5701, once
        self.assertEqual(second.call_count, 0)

    def test_turning_the_check_off_lists_every_port_and_sends_nothing(self):
        self.monitor.store.data["probeLinks"] = False
        _, probe = self.attach()
        self.assertEqual(probe.call_count, 0)
        self.assertEqual([l["port"] for l in self.rows[0]["links"]], [3000, 5701])

    def test_the_setting_can_be_changed_through_the_api_and_resets_the_cache(self):
        self.attach()
        self.monitor.apply_config({"op": "setProbeLinks", "enabled": False})
        self.assertFalse(self.monitor.store.data["probeLinks"])
        self.assertEqual(self.monitor.probe_cache, {})


if __name__ == "__main__":
    unittest.main()
