"""In-memory engine hooks for tests. Not a Channel Run."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from backend.admin.user_store import UserRecord
from backend.channel.nodes.spec import NodeResult

_ACTOR = {"id": "usr_system", "name": "System"}


class FakeHooks:
    def __init__(
        self,
        *,
        run_id: str = "run",
        channel_id: str = "chn",
        actor: Mapping[str, str] | None = None,
        started_at: str = "1970-01-01T00:00:00Z",
        user: UserRecord | None = None,
        schedule: Mapping[str, Any] | None = None,
        evaluate: Callable[[str], Any] | None = None,
        run_code: Callable[[str, float], Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.channel_id = channel_id
        self.actor = dict(actor) if actor is not None else dict(_ACTOR)
        self.started_at = started_at
        self.user = user if user is not None else _user()
        self.schedule = (
            dict(schedule)
            if schedule is not None
            else {
                "schedule_id": None,
                "name": "",
                "scheduled_for": started_at,
            }
        )
        self._evaluate = evaluate
        self._run_code = run_code
        self.order: list[str] = []
        self.outputs: dict[str, Any] = {}
        self.dropped: list[list[str]] = []
        self.statuses: list[tuple[str, str]] = []
        self.cancel_after: str | None = None

    def cancelled(self) -> bool:
        return bool(self.cancel_after and self.cancel_after in self.order)

    def superseded(self) -> bool:
        return False

    def on_start(self, node: Mapping[str, Any]) -> int:
        node_id = str(node["id"])
        self.order.append(node_id)
        self.statuses.append((node_id, "running"))
        return len(self.order)

    def on_finish(self, seq: int, node: Mapping[str, Any], result: NodeResult) -> None:
        del node
        node_id, _status = self.statuses[seq - 1]
        self.statuses[seq - 1] = (node_id, result.status)

    def on_output(self, node: Mapping[str, Any], output: Any) -> None:
        self.outputs[str(node["id"])] = output

    def drop_outputs(self, refs: list[str]) -> None:
        self.dropped.append(list(refs))

    def evaluate(self, expression: str) -> Any:
        if self._evaluate is None:
            return expression
        return self._evaluate(expression)

    def run_code(self, source: str, timeout_sec: float) -> Any:
        if self._run_code is None:
            raise AssertionError(source)
        return self._run_code(source, timeout_sec)


def _user() -> UserRecord:
    return UserRecord(
        id="usr_system",
        account="system",
        display_name="System",
        password_hash=None,
        role_id=None,
        status="active",
        identity_source="system",
    )
