"""Serve the installed workbench on a loopback socket and own its active hardware session."""
import argparse
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import os
import secrets
import sys
import threading
from urllib.parse import urlsplit
import webbrowser

from filelock import Timeout

from . import api, engine
from .live import LiveSession


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_data(self, status, content_type, content):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.wfile.write(content)

    def json_reply(self, status, result):
        self.send_data(status, "application/json; charset=utf-8", json.dumps(result, allow_nan=False).encode())

    def valid_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def do_GET(self):
        if not self.valid_host():
            return self.send_error(403)
        path = urlsplit(self.path).path
        name = "index.html" if path == "/" else path.lstrip("/")
        allowed = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg":"image/svg+xml", ".woff2":"font/woff2"}
        extension = "." + name.rsplit(".",1)[-1]
        if "/" in name or "\\" in name or ".." in name or extension not in allowed:
            return self.send_error(404)
        resource = files("looptrial").joinpath("web", name)
        if not resource.is_file():
            return self.send_error(404)
        self.send_data(200, allowed[extension], resource.read_bytes())

    def do_POST(self):
        if not self.valid_host() or self.headers.get_content_type() != "application/json":
            return self.send_error(403)
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            return self.send_error(403)
        bearer = self.headers.get("Authorization", "")
        if secrets.compare_digest(bearer, "Bearer " + self.server.token):
            who = self.headers.get("X-LoopTrial-Actor")
            if who not in ("cli", "mcp"):
                return self.send_error(403)
        elif self.headers.get("X-LoopTrial") == "1":
            who = "human"
        else:
            return self.send_error(403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 131072:
                raise ValueError("Invalid JSON request length")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data,dict) or not self.path.startswith("/api/"):
                raise ValueError("Expected a JSON operation")
            name = self.path[5:]
            api.validate_remote_refs(name, data)
            result = api.local(name, data, who)
        except engine.OPERATION_ERRORS as error:
            return self.json_reply(400, engine.failure(error))
        self.json_reply(200, result)


def serve(port=0, open_browser=True):
    # The lock covers publication and removal, so there is exactly one owner per lab.
    with engine.lock_for("workbench-owner"):
        with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
            server.token = secrets.token_urlsafe(32)
            engine.runtime = LiveSession()
            path = api.descriptor()
            temp = path.with_suffix(".tmp")
            try:
                temp.write_text(json.dumps({"port":server.server_port,"token":server.token,"pid":os.getpid()}), encoding="utf-8")
                if os.name != "nt":
                    temp.chmod(0o600)
                os.replace(temp, path)
                url = f"http://127.0.0.1:{server.server_port}/"
                print(json.dumps({"url":url,"store":str(engine.home())}), flush=True)
                if open_browser:
                    threading.Thread(target=webbrowser.open, args=(url,),daemon=True).start()
                server.serve_forever()
            finally:
                path.unlink(missing_ok=True)
                engine.runtime.close()
                engine.runtime = None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Open the local LoopTrial workbench. CLI and MCP in the same lab share its connection.")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    options = parser.parse_args(argv)
    try:
        serve(options.port, not options.no_browser)
    except KeyboardInterrupt:
        return 0
    except Timeout:
        print("A workbench is already running in this LOOPTRIAL_HOME.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
