"""One home for a Channel Run's trigger rule, minting, dispatch, and engine hooks."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from backend.admin.user_store import UserRecord, ensure_system_user, get_user_store
from backend.channel.checkpoints import LocalCheckpoints, RunCheckpoints
from backend.channel.context import channel_context, platform_context, run_context
from backend.channel.engine import RunOutcome, execute
from backend.channel.node_support import (
    InputCapture,
    bind_execution_input,
    reset_execution_input,
)
from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import EngineHooks, NodeResult
from backend.channel.references import ChannelReferenceResolver
from backend.channel.run_store import (
    ChannelRunRecord,
    PREVIEW_LIST_CAP,
    get_run_store,
    output_size,
)
from backend.channel.sandbox import SandboxSession
from backend.channel.store import get_channel_store
from backend.channel.tasks import run_job
from backend.core.time import format_instant, utc_now
from backend.jobs.store import (
    JobRecord,
    UniqueScheduledForError,
    create_queued_job,
    format_job_log_line,
    get_job_store,
)
from backend.worker.schedules import get_schedule_store

Dispatcher = Callable[[str], object]

__all__ = [
    "ScheduledMint",
    "dispatch",
    "trigger_node_id",
    "execute_channel_run",
    "expression_context",
    "mint_followup_run",
    "mint_on_demand_run",
    "mint_scheduled_run",
    "schedule_context",
    "schedule_key_for",
    "set_dispatcher",
]


@dataclass(frozen=True)
class ScheduledMint:
    status: Literal["missing_channel", "already_minted", "queued"]
    job_id: str
    job: JobRecord | None
    mint_at: datetime | None


def trigger_node_id(graph: dict[str, Any]) -> str | None:
    trigger_types = {item.type_id for item in list_node_types() if item.trigger}
    triggers = [
        node for node in graph.get("nodes") or [] if node.get("type") in trigger_types
    ]
    if len(triggers) != 1:
        return None
    return str(triggers[0]["id"])


def mint_on_demand_run(
    *,
    channel_id: str,
    channel_name: str,
    target: Literal["draft", "published"],
    ignore_checkpoints: bool,
    actor_id: str,
    trigger_node_id: str,
    version: int | None,
    draft_revision: int | None,
    graph: dict[str, Any] | None,
    stop_at_node_id: str | None,
    pin_version: bool = False,
) -> tuple[JobRecord, ChannelRunRecord]:
    payload: dict[str, Any] = {
        "channel_id": channel_id,
        "target": target,
        "ignore_checkpoints": ignore_checkpoints,
        "stop_at_node_id": stop_at_node_id,
    }
    if pin_version and version is not None:
        payload["pin_version"] = True
        payload["version"] = version
    job = create_queued_job(
        kind="channel_run",
        input=payload,
        trigger_kind="user",
        trigger_ref=actor_id,
        summary=f"channel_run {channel_name}",
        created_by=actor_id,
    )
    record = _channel_run_record(
        job_id=job.id,
        channel_id=channel_id,
        target=target,
        version=version if target == "published" else None,
        draft_revision=draft_revision,
        graph=graph if target == "draft" else None,
        trigger_node_id=trigger_node_id,
        ignore_checkpoints=ignore_checkpoints,
        created_at=utc_now(),
        stop_at_node_id=stop_at_node_id,
    )
    get_run_store().insert_run(record)
    return job, record


def mint_followup_run(
    *,
    channel_id: str,
    channel_name: str,
    trigger_kind: Literal["retry", "error"],
    trigger_ref: str,
    trigger_node: str,
    version: int | None,
    job_input: dict[str, Any],
) -> tuple[JobRecord, ChannelRunRecord]:
    """Queue a pinned retry or an error-workflow run. The caller dispatches it."""
    job = create_queued_job(
        kind="channel_run",
        input=job_input,
        trigger_kind=trigger_kind,
        trigger_ref=trigger_ref,
        summary=f"channel_run {channel_name}",
        created_by=None,
    )
    record = _channel_run_record(
        job_id=job.id,
        channel_id=channel_id,
        target="published",
        version=version,
        draft_revision=None,
        graph=None,
        trigger_node_id=trigger_node,
        ignore_checkpoints=False,
        created_at=utc_now(),
    )
    get_run_store().insert_run(record)
    return job, record


def mint_scheduled_run(
    *,
    schedule_id: str,
    channel_id: str | None,
    node_id: str | None,
    scheduled_for: datetime,
    now: datetime,
    session: Any,
) -> ScheduledMint:
    if not channel_id:
        return ScheduledMint("missing_channel", "", None, None)
    already = False
    try:
        job = create_queued_job(
            kind="channel_run",
            input={
                "channel_id": channel_id,
                "target": "published",
                "ignore_checkpoints": False,
            },
            created_by=None,
            summary=f"channel_run {channel_id}",
            trigger_kind="schedule",
            trigger_ref=schedule_id,
            log_body=format_job_log_line(
                level="info", message="queued channel run", at=now
            ),
            scheduled_for=scheduled_for,
            running_timeout_sec=None,
            session=session,
            created_at=now,
        )
    except UniqueScheduledForError as exc:
        already = True
        found = get_job_store().get(exc.existing_job_id or "", session=session)
        if found is None:
            return ScheduledMint(
                "already_minted", exc.existing_job_id or "", None, None
            )
        job = found
    if not already and get_channel_store().get(channel_id) is not None:
        get_run_store().insert_run(
            _channel_run_record(
                job_id=job.id,
                channel_id=channel_id,
                target="published",
                version=None,
                draft_revision=None,
                graph=None,
                trigger_node_id=node_id or "",
                ignore_checkpoints=False,
                created_at=now,
            )
        )
    return ScheduledMint(
        "already_minted" if already else "queued",
        job.id,
        job,
        job.created_at if already else now,
    )


def _channel_run_record(
    *,
    job_id: str,
    channel_id: str,
    target: str,
    version: int | None,
    draft_revision: int | None,
    graph: dict[str, Any] | None,
    trigger_node_id: str,
    ignore_checkpoints: bool,
    created_at: datetime,
    stop_at_node_id: str | None = None,
) -> ChannelRunRecord:
    return ChannelRunRecord(
        job_id=job_id,
        channel_id=channel_id,
        target=target,
        version=version,
        draft_revision=draft_revision,
        graph=graph,
        trigger_node_id=trigger_node_id,
        ignore_checkpoints=ignore_checkpoints,
        outcome=None,
        failed_node_id=None,
        skipped_node_ids=[],
        created_at=created_at,
        stop_at_node_id=stop_at_node_id,
    )


def _enqueue(job_id: str) -> None:
    task: Any = run_job
    task.apply_async(args=[job_id], task_id=job_id)


_dispatcher: Dispatcher = _enqueue


def set_dispatcher(dispatcher: Dispatcher) -> Dispatcher:
    global _dispatcher
    previous = _dispatcher
    _dispatcher = dispatcher
    return previous


def dispatch(job_id: str) -> None:
    _dispatcher(job_id)


def schedule_key_for(channel_id: str) -> str:
    return f"channel_run:{channel_id}"


def expression_context(
    channel: Any,
    run: Any,
    started: datetime,
    actor: dict[str, str],
    trigger_kind: str | None,
) -> dict[str, Any]:
    return {
        "channel": channel_context(channel, run),
        "run": run_context(run, started, actor, trigger_kind),
        "platform": platform_context(started),
    }


def schedule_context(
    *,
    channel_id: str,
    node: Mapping[str, Any],
    trigger_kind: str | None,
    when: datetime | None,
    trigger_ref: str | None = None,
    scheduled_for: datetime | None = None,
) -> dict[str, Any]:
    row = get_schedule_store().get_by_key(schedule_key_for(channel_id))
    node_name = str(node.get("name") or "")
    if trigger_kind == "schedule":
        instant = scheduled_for or when
        schedule_id = trigger_ref
    else:
        instant = when
        schedule_id = row.id if row is not None else None
    return {
        "schedule_id": schedule_id,
        "name": row.name if row is not None else node_name,
        "scheduled_for": format_instant(instant) if instant is not None else "",
    }


def execute_channel_run(
    *,
    graph: Mapping[str, Any],
    trigger_node_id: str,
    trigger_node: Mapping[str, Any],
    run: ChannelRunRecord,
    context: dict[str, Any],
    actor: dict[str, str],
    started_at: str,
    job: JobRecord,
    timeout_sec: int | None,
    started: float | None,
    pinned: bool = False,
) -> RunOutcome:
    user = ensure_system_user(get_user_store())
    schedule = schedule_context(
        channel_id=run.channel_id,
        node=trigger_node,
        trigger_kind=job.trigger_kind,
        when=job.created_at,
        trigger_ref=job.trigger_ref,
        scheduled_for=job.scheduled_for,
    )
    with _sandbox_session(context) as sandbox:
        hooks = _RunHooks(
            sandbox,
            run_id=run.job_id,
            actor=actor,
            started_at=started_at,
            user=user,
            schedule=schedule,
            target=run.target,
            channel_id=run.channel_id,
            run_version=run.version,
            pinned=pinned,
            run=run,
        )
        return _execute_graph(
            graph,
            trigger_node_id,
            run.channel_id,
            hooks,
            timeout_sec=timeout_sec,
            started=started,
            stop_at_node_id=run.stop_at_node_id,
        )


class _RunHooks:
    def __init__(
        self,
        sandbox: SandboxSession,
        *,
        run_id: str,
        actor: dict[str, str],
        started_at: str,
        user: UserRecord,
        schedule: dict[str, Any],
        target: str,
        channel_id: str,
        run_version: int | None,
        pinned: bool = False,
        run: Any | None = None,
    ) -> None:
        self._sandbox = sandbox
        self.run_id = run_id
        self.actor = actor
        self.started_at = started_at
        self.user = user
        self.schedule = schedule
        self.channel_id = channel_id
        self._target = target
        self._run_version = run_version
        self._pinned = pinned
        self._inputs: dict[int, InputCapture] = {}
        self.run_variables: dict[str, Any] = {}
        self.ignore_checkpoints = bool(getattr(run, "ignore_checkpoints", False))
        self.checkpoints = (
            RunCheckpoints(channel_id, run) if run is not None else LocalCheckpoints()
        )

    def evaluate(self, expression: str) -> Any:
        return self._sandbox.evaluate(expression)

    def run_code(self, source: str, timeout_sec: float) -> Any:
        return self._sandbox.run_code(source, timeout_sec)

    def on_output(self, node: Mapping[str, Any], output: Any) -> None:
        self._sandbox.put_output(
            ref=str(node.get("ref") or node["id"]),
            name=str(node.get("name") or ""),
            output=output,
        )

    def drop_outputs(self, refs: list[str]) -> None:
        self._sandbox.drop_outputs(refs)

    def cancelled(self) -> bool:
        record = get_job_store().get(self.run_id)
        return record is not None and record.status == "cancelled"

    def superseded(self) -> bool:
        if self._pinned or self._target != "published" or self._run_version is None:
            return False
        versions, _total = get_channel_store().list_versions(
            self.channel_id, limit=1, offset=0
        )
        if not versions:
            return False
        return versions[0].number > self._run_version

    def on_start(
        self,
        node: Mapping[str, Any],
        *,
        container_seq: int | None = None,
        round: int | None = None,
    ) -> int:
        record = get_run_store().start_execution(
            self.run_id,
            str(node["id"]),
            container_seq=container_seq,
            round=round,
        )
        return record.seq

    def open_input(self, seq: int) -> Any:
        capture = InputCapture()
        self._inputs[seq] = capture
        return bind_execution_input(capture)

    def close_input(self, token: Any) -> None:
        reset_execution_input(token)

    def on_round(self, seq: int, index: int, step: Any) -> None:
        clipped, totals = _preview_copy(step)
        get_run_store().insert_round(
            self.run_id,
            container_seq=seq,
            round=index,
            step=clipped,
            step_totals=totals,
        )

    def note_round_condition(self, seq: int, index: int, entry: Any) -> None:
        get_run_store().set_round_condition(
            self.run_id,
            container_seq=seq,
            round=index,
            condition=entry,
        )

    def on_finish(self, seq: int, node: Mapping[str, Any], result: NodeResult) -> None:
        store = get_run_store()
        record = store.get_execution(self.run_id, seq)
        captured = self._inputs.pop(seq, None)
        if record is None:
            return
        record.status = result.status
        record.finished_at = utc_now()
        record.output_bytes = output_size(result.output)
        record.error_code = result.error_code
        record.error_message = result.error_message
        record.error_detail = result.error_detail
        record.preview_only = False
        record.preview_totals = {}
        record.output = result.output
        if captured is not None:
            record.input, record.input_totals = _clip_captured(captured.fields)
        store.finish_execution(record)


@contextmanager
def _sandbox_session(context: dict[str, Any]) -> Iterator[SandboxSession]:
    with SandboxSession() as sandbox:
        sandbox.set_context(
            channel=context["channel"],
            run=context["run"],
            platform=context["platform"],
        )
        yield sandbox


def _clip_captured(fields: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """Clip lists inside captured field values with the output preview clipper."""
    stored: dict[str, Any] = {}
    totals: dict[str, int] = {}
    for path, entry in fields.items():
        if "value" not in entry:
            stored[path] = entry
            continue
        clipped, subtotals = _preview_copy(entry["value"])
        stored[path] = {"value": clipped}
        for sub, length in subtotals.items():
            totals[path if sub == "" else f"{path}.{sub}"] = int(length)
    return stored, totals


def _preview_copy(
    output: Any, *, cap: int = PREVIEW_LIST_CAP
) -> tuple[Any, dict[str, int]]:
    """Deep-copy ``output`` and keep the first ``cap`` elements of each list."""
    copied = copy.deepcopy(output)
    totals: dict[str, int] = {}
    _clip_lists(copied, cap, "", totals)
    return copied, totals


def _clip_lists(value: Any, cap: int, path: str, totals: dict[str, int]) -> None:
    if isinstance(value, list):
        totals[path] = len(value)
        if len(value) > cap:
            del value[cap:]
        for index, item in enumerate(value):
            child = str(index) if path == "" else f"{path}.{index}"
            _clip_lists(item, cap, child, totals)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            child = str(key) if path == "" else f"{path}.{key}"
            _clip_lists(item, cap, child, totals)


def _execute_graph(
    graph: Mapping[str, Any],
    trigger_node_id: str,
    channel_id: str,
    hooks: EngineHooks,
    *,
    timeout_sec: int | None,
    started: float | None,
    stop_at_node_id: str | None,
) -> RunOutcome:
    return execute(
        graph,
        trigger_node_id,
        list_node_types(),
        ChannelReferenceResolver(channel_id),
        hooks,
        timeout_sec=timeout_sec,
        started=started,
        stop_at_node_id=stop_at_node_id,
    )
