"""Parent-side client for the expression sandbox."""

from __future__ import annotations

import json
import select
import subprocess
import sys
from typing import Any


class ExpressionError(Exception):
    def __init__(self, message: str, *, expression: str) -> None:
        super().__init__(message)
        self.expression = expression


class SandboxFailed(Exception):
    pass


class SandboxSession:
    """One child process. A timed-out eval kills and restarts it."""

    def __init__(self, *, timeout_sec: float = 5.0) -> None:
        self._timeout = timeout_sec
        self._context: dict[str, Any] = {}
        self._outputs: list[dict[str, Any]] = []
        self._proc: subprocess.Popen[str] | None = None
        self._seq = 0

    def __enter__(self) -> SandboxSession:
        self._start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def set_context(self, *, channel: dict, run: dict, platform: dict) -> None:
        self._context = {"channel": channel, "run": run, "platform": platform}
        self._send({"op": "put_context", **self._context})

    def put_output(self, *, ref: str, name: str, output: Any) -> None:
        message = {"op": "put_output", "ref": ref, "name": name, "output": output}
        self._outputs.append(message)
        self._send(message)

    def evaluate(self, expression: str) -> Any:
        self._seq += 1
        ident = self._seq
        try:
            reply = self._send(
                {"op": "eval", "id": ident, "expression": expression},
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:
            self._restart()
            raise ExpressionError("expression timed out", expression=expression) from exc
        except SandboxFailed:
            self._restart()
            raise
        if not reply.get("ok"):
            error = reply.get("error") or {}
            raise ExpressionError(
                str(error.get("message") or "expression failed"),
                expression=expression,
            )
        return reply.get("value")

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        proc.stdin.close()
        proc.kill()
        proc.wait(timeout=2)

    def _start(self) -> None:
        # Stay in the runner's process group so a cancel killpg reaps this child.
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "backend.channel.sandbox.child"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=False,
            text=True,
        )

    def _restart(self) -> None:
        self.close()
        self._start()
        if self._context:
            self._send({"op": "put_context", **self._context})
        for message in self._outputs:
            self._send(message)

    def _send(self, message: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise SandboxFailed("sandbox is not running")
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()
        if timeout is not None:
            ready, _, _ = select.select([proc.stdout], [], [], timeout)
            if not ready:
                proc.kill()
                raise subprocess.TimeoutExpired(proc.args, timeout)
        line = proc.stdout.readline()
        if not line:
            raise SandboxFailed("sandbox closed its output")
        return json.loads(line)
