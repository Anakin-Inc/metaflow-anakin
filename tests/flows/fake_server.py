"""A local fake of the Anakin scrape API (submit, then poll), run by the test process."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

KEY_SEEN: list[str | None] = []
JOBS: dict[str, str] = {}


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        KEY_SEEN.append(self.headers.get("X-API-Key"))
        if "fail" in str(body.get("url", "")):
            self._reply(400, {"error": "bad url", "code": "INVALID"})
            return
        job_id = "job-%d" % len(JOBS)
        JOBS[job_id] = body.get("url", "")
        self._reply(200, {"id": job_id, "jobId": job_id, "status": "pending"})

    def do_GET(self) -> None:
        job_id = self.path.rstrip("/").rsplit("/", 1)[-1]
        url = JOBS[job_id]
        self._reply(
            200,
            {
                "id": job_id,
                "url": url,
                "status": "completed",
                "cached": False,
                "markdown": f"# hello from {url}",
            },
        )

    def log_message(self, *args: Any) -> None:
        pass


def serve() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, "http://127.0.0.1:%d/v1" % server.server_address[1]
