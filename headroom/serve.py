"""Stream investigations to the dashboard while they run.

`headroom serve` follows an investigation's append-only event log and sends each
event to the browser as a Server-Sent Event the moment it is written. It can also
serve the built dashboard, so one command runs the whole live demo locally.
"""

import json
import mimetypes
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from headroom.agent.store import ROOT

BASE = "/headroom/"


def follow(path: Path, done: Callable[[], bool], poll: float = 0.25) -> Iterator[str]:
    """Yield every complete line of an append-only file, including lines written later, until done()."""
    position, pending = 0, ""
    while True:
        finished = done()  # checked before reading, so lines written just before finishing are not lost
        if path.exists():
            with path.open() as f:
                f.seek(position)
                pending += f.read()
                position = f.tell()
            *lines, pending = pending.split("\n")
            yield from (line for line in lines if line.strip())
        if finished:
            return
        time.sleep(poll)


def investigations(root: Path) -> list[str]:
    return sorted((p.name for p in root.iterdir() if (p / "events.jsonl").exists()), reverse=True) if root.exists() else []


def make_server(port: int, *, root: Path = ROOT, dist: Path | None = None) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/api/investigations":
                self._send(200, json.dumps(investigations(root)).encode(), "application/json")
            elif url.path == "/api/live":
                self._live(parse_qs(url.query).get("id", ["latest"])[0])
            elif dist and url.path.startswith(BASE):
                self._static(url.path[len(BASE):] or "index.html")
            elif dist and url.path == "/":
                self.send_response(302)
                self.send_header("Location", BASE)
                self.end_headers()
            else:
                self._send(404, b"not found", "text/plain")

        def _live(self, ref: str) -> None:
            names = investigations(root)
            name = names[0] if ref == "latest" and names else ref
            path = root / name
            if Path(name).name != name or not (path / "events.jsonl").exists():
                self._send(404, b"no such investigation", "text/plain")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(f"event: investigation\ndata: {json.dumps({'id': name})}\n\n".encode())
                self.wfile.flush()
                try:
                    last_event = int(self.headers.get("Last-Event-ID", "-1"))
                except ValueError:
                    last_event = -1
                for sequence, line in enumerate(follow(path / "events.jsonl", lambda: (path / "outcome.json").exists())):
                    if sequence <= last_event:
                        continue
                    self.wfile.write(f"id: {sequence}\ndata: {line}\n\n".encode())
                    self.wfile.flush()
                # save_outcome writes outcome.json before winner.diff; read the patch from
                # the outcome and tolerate the brief interval while JSON is being written.
                outcome = None
                for _ in range(20):
                    try:
                        outcome = json.loads((path / "outcome.json").read_text())
                        break
                    except (json.JSONDecodeError, FileNotFoundError):
                        time.sleep(0.05)
                if outcome is None:
                    return  # Reconnection will resume after the final event.
                result = {key: outcome.get(key) for key in ("winner", "diff")}
                self.wfile.write(f"event: done\ndata: {json.dumps(result)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser went away

        def _static(self, relative: str) -> None:
            file = (dist / relative).resolve()
            if not file.is_relative_to(dist.resolve()) or not file.is_file():
                file = dist / "index.html"
            content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            self._send(200, file.read_bytes(), content_type)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
