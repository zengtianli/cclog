"""Local HTTP server for cclog dashboard with live API."""

import json
import webbrowser
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from tempfile import mkdtemp

from cclog.config import Config
from cclog.indexer import Indexer
from cclog.site import generate_site


class DashboardHandler(SimpleHTTPRequestHandler):
    """Serves static site + handles API requests."""

    def __init__(self, *args, indexer: Indexer, **kwargs):
        self.indexer = indexer
        super().__init__(*args, **kwargs)

    def do_POST(self):
        if self.path == "/api/delete":
            self._handle_delete()
        else:
            self.send_error(404)

    def _handle_delete(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        session_id = body.get("session_id", "")

        if not session_id:
            self._json_response(400, {"error": "missing session_id"})
            return

        session = self.indexer.get_session(session_id)
        if not session:
            self._json_response(404, {"error": "session not found"})
            return

        ok = self.indexer.delete_session(session.session_id, delete_files=True)
        if ok:
            self._json_response(200, {"deleted": session.session_id})
        else:
            self._json_response(500, {"error": "delete failed"})

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        msg = str(args[0]) if args else ""
        if "/api/" in msg or "DELETE" in msg:
            super().log_message(format, *args)


def serve_dashboard(config: Config, port: int = 8899):
    """Generate site and serve with live API."""
    output_dir = Path(mkdtemp(prefix="cclog-serve-"))
    generate_site(config, output_dir, api_mode=True)

    indexer = Indexer(config)
    handler = partial(DashboardHandler, directory=str(output_dir), indexer=indexer)

    server = HTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Serving dashboard at {url}")
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        indexer.close()
        server.server_close()
