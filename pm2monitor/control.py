"""Talking to a monitor that is already running: is it there, and can it be asked to stop."""
import json
import socket
import urllib.request


def monitor_url(port):
    return f"http://127.0.0.1:{port}"


def running_version(port):
    """Version of the pm2-monitor listening on this port; None if nothing answers or it is another program."""
    try:
        with urllib.request.urlopen(monitor_url(port) + "/api/ping", timeout=3) as response:
            data = json.loads(response.read())
        return str(data["version"]) if isinstance(data, dict) and data.get("app") == "pm2-monitor" else None
    except (OSError, ValueError, KeyError):  # URLError and HTTPError are OSError
        return None


def port_in_use(port):
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def request_shutdown(port):
    """Asks the running monitor to turn itself off. The apps it watches are not touched."""
    request = urllib.request.Request(monitor_url(port) + "/api/shutdown", b"{}", {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(request, timeout=5).close()
        return True
    except OSError:
        return False
