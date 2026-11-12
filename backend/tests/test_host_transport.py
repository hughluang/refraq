"""Host acquisition at the HTTP boundary, without a deployed series store."""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.admin.host.errors import HostSeriesUnavailable
from backend.admin.host.series import read_host
from backend.core.config import reset_settings_cache


@pytest.fixture
def upstream(monkeypatch):
    class Server(ThreadingHTTPServer):
        daemon_threads = True

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            server.opened += 1

        def finish(self):
            super().finish()
            server.closed += 1

        def do_GET(self):
            server.calls += 1
            time.sleep(0.01)
            failed = server.calls == server.fail_at
            if failed and server.failure == "disconnect":
                self.close_connection = True
                return
            payload = {"status": "success", "data": {"result": []}}
            if failed and server.failure == "envelope":
                payload = {"status": "error", "error": "private upstream detail"}
            if failed and server.failure == "result":
                payload = {"status": "success", "data": {"result": None}}
            body = json.dumps(payload).encode()
            if failed and server.failure == "json":
                body = b"private non-JSON upstream detail"
            self.send_response(500 if failed and server.failure == "status" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = Server(("127.0.0.1", 0), Handler)
    server.opened = server.closed = server.calls = 0
    server.fail_at = None
    server.failure = "status"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("REFRAQ_PROMETHEUS_URL", f"http://127.0.0.1:{server.server_port}")
    reset_settings_cache()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        reset_settings_cache()


@pytest.mark.parametrize(
    ("fail_at", "failure"),
    [(None, "status"), (12, "status"), (34, "status"),
     (12, "disconnect"), (12, "json"), (12, "envelope"), (12, "result")],
)
def test_host_read_reuses_and_releases_its_connection(upstream, fail_at, failure):
    upstream.fail_at = fail_at
    upstream.failure = failure
    started = time.perf_counter()
    if fail_at is None:
        result = read_host("hour")
        assert result.charts.cpu_modes == []
        assert result.tiles.cpu.busy_share is None
    else:
        with pytest.raises(HostSeriesUnavailable) as error:
            read_host("hour")
        assert "127.0.0.1" not in str(error.value)
        assert "private" not in str(error.value)
    elapsed = time.perf_counter() - started
    deadline = time.monotonic() + 1
    while upstream.closed != upstream.opened and time.monotonic() < deadline:
        time.sleep(0.005)
    print(f"host transport: calls={upstream.calls} connections={upstream.opened} "
          f"closed={upstream.closed} elapsed={elapsed:.4f}s")
    assert upstream.calls == (34 if fail_at is None else fail_at)
    assert upstream.closed == upstream.opened
    assert upstream.opened == 1

    if fail_at is None:
        # A second read must own a new connection, not a process-wide client.
        read_host("hour")
        assert upstream.calls == 68
        assert upstream.opened == 2
        deadline = time.monotonic() + 1
        while upstream.closed != 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert upstream.closed == 2
