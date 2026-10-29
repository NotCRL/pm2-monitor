#!/usr/bin/env python3
"""pm2-monitor — local web UI for the pm2 processes of any daemon on this computer.

Standard library only. Listens on 127.0.0.1:8440. Works on Linux, macOS and Windows.
Usage: python3 server.py [--port N] [--config PATH] [--version]
"""
import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pm2monitor import __version__
from pm2monitor.service import ActionError, Monitor, strip_ansi, tail
from pm2monitor.store import ConfigStore

HERE = Path(__file__).resolve().parent
PORT = 8440
MAX_BODY_BYTES = 64 * 1024

monitor = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, code, error, status, **params):
        """Errors are codes plus params: the UI translates them into the user's language."""
        self.send_json({"ok": False, "error": code, "params": params, "output": error}, status)

    def request_allowed(self):
        """The server controls pm2: reject non-local Host (DNS rebinding) and POSTs sent from other sites."""
        host = self.headers.get("Host", "")
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if host not in allowed:
            return False
        if self.command == "POST":
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{h}" for h in allowed}:
                return False
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return False
        return True

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY_BYTES:
            raise ValueError("request too large")
        body = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("a JSON object is required")
        return body

    def do_GET(self):
        if not self.request_allowed():
            return self.send_error(403)
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif url.path == "/api/state":
            self.send_json(monitor.snapshot())
        elif url.path == "/api/logs":
            try:
                line_count = min(int(query.get("n", 200)), 2000)
                out_path, err_path = monitor.find_logs(query.get("key", ""))
            except ActionError as e:
                return self.send_error_json(e.code, str(e), 400, **e.params)
            except (ValueError, subprocess.SubprocessError, OSError) as e:
                return self.send_error_json("error_detail", str(e), 400, detail=str(e))
            if not out_path and not err_path:
                return self.send_error_json("process_not_found", "process not found", 404)
            out, out_error = tail(out_path, line_count)
            err, err_error = tail(err_path, line_count)
            self.send_json({"out": out, "err": err, "out_error": out_error, "err_error": err_error,
                            "out_path": out_path, "err_path": err_path})
        elif url.path == "/api/job":
            job = monitor.get_job(query.get("id", ""))
            if job:
                self.send_json(job)
            else:
                self.send_error_json("unknown_job", "unknown job", 404)
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.request_allowed():
            return self.send_error(403)
        try:
            request = self.read_json_body()
        except ValueError as e:
            return self.send_error_json("bad_request", str(e), 400, detail=str(e))
        path = urlparse(self.path).path
        try:
            if path == "/api/action":
                output = monitor.perform(request.get("key", ""), request.get("action"))
                self.send_json({"ok": True, "output": output})
            elif path == "/api/domain-action":
                job_id = monitor.start_domain_job(request.get("domain"), request.get("action"))
                self.send_json({"ok": True, "job": job_id})
            elif path == "/api/config":
                monitor.apply_config(request)
                self.send_json({"ok": True})
            else:
                self.send_error(404)
        except ActionError as e:
            self.send_error_json(e.code, str(e), 400, **e.params)
        except (subprocess.SubprocessError, OSError) as e:
            detail = strip_ansi(str(e))
            self.send_error_json("error_detail", detail, 500, detail=detail)


def main():
    global monitor
    parser = argparse.ArgumentParser(description="Local web UI for pm2 processes.")
    parser.add_argument("--port", type=int, default=PORT, help=f"local port (default {PORT})")
    parser.add_argument("--config", metavar="PATH",
                        help="config .json file or directory (otherwise PM2_MONITOR_CONFIG or the per-OS default)")
    parser.add_argument("--version", action="version", version=f"pm2-monitor {__version__}")
    args = parser.parse_args()
    monitor = Monitor(ConfigStore(args.config))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"pm2-monitor on http://127.0.0.1:{args.port}  (pm2: {monitor.pm2_path or 'NOT FOUND'}, "
          f"config: {monitor.store.path})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
