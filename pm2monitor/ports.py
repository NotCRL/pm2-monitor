"""Finds the addresses an app answers on (localhost:3000, ...).

An app started by pm2 is often just a wrapper (`npm start`): the web server that really listens is one of its
children. So for each pm2 process we look at the TCP ports in LISTEN state of the process and of every
program it started. Linux reads /proc, macOS asks `lsof`, Windows asks `netstat` and PowerShell. The parsers
are plain functions on text so they can be tested without those systems.
"""
import os
import re
import socket
import struct
import subprocess
import sys
from collections import defaultdict

from .osenv import IS_WINDOWS, subprocess_flags

# Programs that listen on a port but do not speak HTTP, or are debugging doors: a link would only confuse.
NON_HTTP_PORTS = frozenset({22, 25, 53, 110, 143, 389, 445, 1433, 1521, 2181, 3306, 5005, 5432, 5672, 5900, 6379, 9042,
                            9092, 9229, 11211, 27017, 27018})
HTTPS_PORTS = frozenset({443, 8443, 9443})
LOCAL_HOSTS = frozenset({"*", "0.0.0.0", "127.0.0.1", "[::]", "[::1]", "::", "::1", "localhost"})  # reachable as localhost
LOG_URL = re.compile(r"(https?)://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]):(\d+)(/[^\s'\"<>)\]]*)?")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
LOG_HINT_BYTES = 32 * 1024
COMMAND_TIMEOUT_SECONDS = 15
PROBE_TIMEOUT_SECONDS = 0.6


# --- pure parsers ------------------------------------------------------------------------------------------
def _hex_address_is_local(hex_address):
    """True for an address in /proc/net/tcp[6] that a 'localhost' link can reach (any address, or loopback)."""
    try:
        if len(hex_address) == 8:
            ip = socket.inet_ntoa(struct.pack("<I", int(hex_address, 16)))
            return ip == "0.0.0.0" or ip.startswith("127.")
        words = struct.unpack("<4I", bytes.fromhex(hex_address))
        packed = struct.pack("!4I", *words)
        ip = socket.inet_ntop(socket.AF_INET6, packed)
        return ip in ("::", "::1") or ip.startswith("::ffff:127.") or ip == "::ffff:0.0.0.0"
    except (ValueError, struct.error, OSError):
        return False


def parse_proc_net_tcp(text):
    """{socket inode: port} for the listening sockets of a /proc/net/tcp or tcp6 table."""
    found = {}
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 10 or parts[3] != "0A":  # 0A = LISTEN
            continue
        address, _, port = parts[1].rpartition(":")
        if _hex_address_is_local(address):
            found[int(parts[9])] = int(port, 16)
    return found


def _host_port(name):
    host, _, port = name.rpartition(":")
    return (host, int(port)) if port.isdigit() else (None, None)


def parse_lsof(text):
    """{pid: set(ports)} from `lsof -nP -iTCP -sTCP:LISTEN -Fpn`."""
    found, pid = defaultdict(set), None
    for line in text.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            host, port = _host_port(line[1:])
            if port is not None and host in LOCAL_HOSTS:
                found[pid].add(port)
    return dict(found)


def parse_netstat(text):
    """{pid: set(ports)} from Windows `netstat -ano -p TCP`."""
    found = defaultdict(set)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING" and parts[4].isdigit():
            host, port = _host_port(parts[1])
            if port is not None and host in LOCAL_HOSTS:
                found[int(parts[4])].add(port)
    return dict(found)


def parse_pid_pairs(text):
    """{parent pid: [child pids]} from lines of 'pid ppid' (ps) or 'pid,ppid' (PowerShell)."""
    children = defaultdict(list)
    for line in text.splitlines():
        parts = line.replace(",", " ").split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            children[int(parts[1])].append(int(parts[0]))
    return dict(children)


def process_tree(children, root):
    """The process and every program it started, directly or not."""
    tree, queue = {root}, [root]
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in tree:
                tree.add(child)
                queue.append(child)
    return tree


def log_hints(log_text):
    """{port: (scheme, path)} for the addresses an app printed in its own log ('Local: http://localhost:3000/')."""
    hints = {}
    for scheme, port, path in LOG_URL.findall(ANSI.sub("", log_text or "")):
        hints[int(port)] = (scheme, (path or "/").rstrip(".,;:") or "/")  # the latest mention wins
    return hints


def needs_check(ports, hints):
    """Ports that neither the app's log nor the port number vouch for as web pages: only a test can tell."""
    return [p for p in sorted(set(ports)) if p not in NON_HTTP_PORTS and p not in hints and p not in HTTPS_PORTS]


def speaks_http(port, timeout=PROBE_TIMEOUT_SECONDS):
    """One harmless `HEAD /` to localhost: does whatever listens answer like a web server?"""
    try:
        with socket.create_connection(("localhost", port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            connection.sendall(b"HEAD / HTTP/1.0\r\nHost: localhost\r\nUser-Agent: pm2-monitor-link-check\r\nConnection: close\r\n\r\n")
            return connection.recv(16).startswith(b"HTTP/")
    except OSError:
        return False


def build_links(ports, hints=None, web=None):
    """Clickable addresses for some ports. `hints` (from the log) give scheme and path; `web`, when given, is the set
    of checked ports that really are web pages: the others are left out (None = do not filter, show every port)."""
    hints, links = hints or {}, []
    for port in sorted(set(ports)):
        if port in NON_HTTP_PORTS:
            continue
        if not (port in hints or port in HTTPS_PORTS or web is None or port in web):
            continue
        scheme, path = hints.get(port, ("https" if port in HTTPS_PORTS else "http", "/"))
        links.append({"port": port, "url": f"{scheme}://localhost:{port}{path}", "label": f"localhost:{port}"})
    return links


def read_log_hint(path):
    """The end of an app's log, where it usually prints 'listening on http://localhost:3000'."""
    if not path:
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - LOG_HINT_BYTES))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


# --- reading the system ----------------------------------------------------------------------------------------
def _run(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS,
                          **subprocess_flags()).stdout


def _linux_children():
    children = defaultdict(list)
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", "rb") as f:
                after_name = f.read().decode("utf-8", "replace").rsplit(")", 1)[1].split()
            children[int(after_name[1])].append(int(entry))
        except (OSError, IndexError, ValueError):
            continue  # the process ended while we were looking
    return children


def _linux_ports(pids):
    inode_port = {}
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table, encoding="utf-8") as f:
                inode_port.update(parse_proc_net_tcp(f.read()))
        except OSError:
            continue
    if not inode_port:
        return {}
    children, result = _linux_children(), {}
    for root in pids:
        ports = set()
        for pid in process_tree(children, root):
            try:
                descriptors = os.listdir(f"/proc/{pid}/fd")
            except OSError:
                continue  # gone, or not ours to look at
            for descriptor in descriptors:
                try:
                    target = os.readlink(f"/proc/{pid}/fd/{descriptor}")
                except OSError:
                    continue
                if target.startswith("socket:[") and int(target[8:-1]) in inode_port:
                    ports.add(inode_port[int(target[8:-1])])
        result[root] = sorted(ports)
    return result


def listening_ports(pids):
    """{pid: sorted ports} for each pm2 process id: its own listening ports plus those of what it started."""
    pids = {pid for pid in pids if pid}
    if not pids:
        return {}
    try:
        if sys.platform.startswith("linux"):
            return _linux_ports(pids)
        if IS_WINDOWS:
            listening = parse_netstat(_run(["netstat", "-ano", "-p", "TCP"]))
            children = parse_pid_pairs(_run(["powershell", "-NoProfile", "-Command",
                                             "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId),$($_.ParentProcessId)\" }"]))
        else:
            listening = parse_lsof(_run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"]))
            children = parse_pid_pairs(_run(["ps", "-axo", "pid=,ppid="]))
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}  # no tool, no permission: the column is simply empty
    return {root: sorted(set().union(*(listening.get(pid, set()) for pid in process_tree(children, root)))) for root in pids}
