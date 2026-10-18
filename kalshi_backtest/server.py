"""Serve the results page on this computer only.

    python serve.py                     http://127.0.0.1:8816
    python serve.py --results results-free

The page reads results.json, which backtest.py wrote. Nothing here calls Predictefy,
so opening the page costs no credits and needs no key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from . import config

WEB = Path(__file__).resolve().parent / "web"


def make_handler(results: Path, data: Path):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("content-type", kind)
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - the base class's name
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/results":
                file = results / "results.json"
                if file.exists():
                    self._send(200, file.read_bytes(), "application/json")
                    return
                blocked = data / "plan-required.json"
                note = json.loads(blocked.read_text(encoding="utf-8")) if blocked.exists() else None
                body = {"missing": True, "planRequired": note, "upgradeUrl": config.UPGRADE_URL, "plans": list(config.PLANS)}
                self._send(200, json.dumps(body).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, *args) -> None:  # keep the console quiet
            return

    return Handler


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results", type=Path, default=config.RESULTS, help="folder holding results.json")
    parser.add_argument("--data", type=Path, default=config.DATA, help="folder written by fetch.py")
    parser.add_argument("--port", type=int, default=int(os.environ.get("BACKTEST_PORT", "8816")))
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.results, args.data))
    print(f"Results page: http://127.0.0.1:{args.port}   (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
