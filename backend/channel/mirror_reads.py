"""Run-scoped authorized mirror gateway and conservative whole-run provenance."""

from typing import Any

from backend.admin.user_store import get_user_store
from backend.channel.run_store import get_run_store
from backend.core.errors import AppError
from backend.metadata.source_access import authorize_source_read_on
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.history import capture_bound, read_incremental
from backend.metadata.mirrors.service import resolve_object_binding, authorize_object_reads
from backend.channel.models import ChannelRunRow
from backend.core.db import session_scope
from backend.jobs.store import get_job_store
from backend.metadata.source_access import allows


class MirrorReadUnavailable(AppError):
    code = "MIRROR_READ_UNAVAILABLE"
    http_status = 503


class MirrorHistoryInvalid(AppError):
    code = "MIRROR_HISTORY_INVALID"
    http_status = 409


class MirrorDataForbidden(AppError):
    code = "AUTH_FORBIDDEN"
    http_status = 403


_reads: Reads | None = None


def bind_reads(reads: Reads | None) -> None:
    """Composition must supply the actual restricted Metadata gateway."""
    global _reads
    if reads is not None and not isinstance(reads, Reads):
        raise TypeError("Mirror reads require the Metadata Reads gateway")
    _reads = reads


def resolve_object(object_id: str, *, session=None) -> dict:
    if _reads is None:
        raise MirrorReadUnavailable()
    return resolve_object_binding(object_id, session=session)


def validate_terminal_proof(*, run_id: str, terminal_proof) -> None:
    """Only completed successful persistent runs are irrevocably unclaimable."""
    if not isinstance(terminal_proof, dict) or terminal_proof.get("run_id") != run_id:
        raise MirrorReadUnavailable()
    with session_scope() as session:
        run = session.get(ChannelRunRow, run_id)
        job = get_job_store().get(run_id, session=session)
        sealed = (run.mirror_state or {}).get("terminal_seal") if run is not None else None
        success = (job is not None and job.status == "succeeded" and run is not None
                   and run.outcome == "completed" and run.stopped_node_id is None
                   and run.failed_node_id is None)
        closed = (job is not None and job.status in {"failed", "cancelled"}
                  and sealed == {"status": job.status, "nonresumable": True})
        if (run is None or job is None or job.kind != "channel_run"
                or job.finished_at is None or not (success or closed)
                or not run.mirror_execution_user_id):
            raise MirrorReadUnavailable()
        state = run.mirror_state
        if not isinstance(state, dict) or not state.get("pins"):
            raise MirrorReadUnavailable()
        pins = state["pins"]
        inherited = state.get("inherited_source_ids", [])
        if (not isinstance(pins, dict) or any(
                not isinstance(pin, dict) or not pin.get("generation_id") or not pin.get("source_id")
                for pin in pins.values())
                or not isinstance(inherited, list)
                or any(not isinstance(source, str) or not source for source in inherited)
                or sorted(set(pin["source_id"] for pin in pins.values())
                          | {bound["source_id"] for bound in (state.get("history_bounds") or {}).values()}
                          | set(inherited)) != state.get("source_ids")):
            raise MirrorReadUnavailable()
        if terminal_proof != {"run_id": run_id, "pins": pins, "source_ids": state["source_ids"]}:
            raise MirrorReadUnavailable()


def release_completed_run(run) -> None:
    if getattr(run, "mirror_state", None) is None:
        return
    if not run.mirror_state.get("pins"):
        return
    if _reads is None:
        raise MirrorReadUnavailable()
    _reads.release_run_pins(run_id=run.job_id, terminal_proof={
        "run_id": run.job_id, "pins": run.mirror_state["pins"],
        "source_ids": run.mirror_state["source_ids"],
    })


def object_ids(graph: Any) -> list[str]:
    return sorted({node["config"]["object_id"] for node in graph.get("nodes", [])
                   if node.get("type") == "read.mirror"})


def authorize_graph(graph: Any, user_id: str | None, *, session=None) -> None:
    ids = object_ids(graph)
    mirror_ids = sorted({node["config"]["source"]["mirror_id"]
                         for node in (graph or {}).get("nodes", [])
                         if node.get("type") in {"read.changes", "volume.changes_dataset"}
                         and (node.get("config", {}).get("source") or {}).get("kind") == "mirror"})
    if not ids and not mirror_ids:
        return
    if _reads is None:
        raise MirrorReadUnavailable()
    if not user_id:
        raise MirrorDataForbidden()
    if session is not None or mirror_ids:
        authorize_object_reads(object_ids=ids, mirror_ids=mirror_ids,
                               execution_user_id=user_id, session=session)
        return
    sources = [resolve_object(object_id)["source_id"] for object_id in ids]
    _authorize(user_id, sources)


def mirror_graph(graph: Any) -> bool:
    if not isinstance(graph, dict):
        return False
    for node in graph.get("nodes") or []:
        config = node.get("config") or {}
        source = config.get("source") or {}
        if node.get("type") == "read.mirror" or source.get("kind") == "mirror":
            return True
    return False


def _authorize(user_id: str | None, sources: list[str]) -> None:
    user = get_user_store().get_by_id(user_id) if user_id else None
    if user is None or user.status != "active" or getattr(user, "identity_source", None) == "system":
        raise MirrorDataForbidden()
    if any(not allows(user_id, source, "sources:data_read") for source in sources):
        raise MirrorDataForbidden()


def execution_identity(graph: Any, *, trigger_kind: str, actor_id: str | None) -> str | None:
    if not mirror_graph(graph):
        return None
    selected = actor_id if trigger_kind == "user" else (graph.get("settings") or {}).get("mirror_execution_user_id")
    _authorize(selected, [])
    return selected


def require_run_data_access(run: Any, user_id: str | None, *, session=None) -> None:
    """Authorize the complete payload, including nested/mixed transforms."""
    state = getattr(run, "mirror_state", None)
    if (state is None and not getattr(run, "mirror_execution_user_id", None)
            and not mirror_graph(getattr(run, "graph", None))):
        return
    sources = state.get("source_ids") if isinstance(state, dict) else None
    if not isinstance(sources, list) or not sources or any(
        not isinstance(source, str) or not source for source in sources
    ):
        raise MirrorDataForbidden()
    if session is None:
        _authorize(user_id, sources)
    else:
        if not user_id:
            raise MirrorDataForbidden()
        for source in sources:
            authorize_source_read_on(session=session, execution_user_id=user_id, source_id=source)


def _history_identity(run):
    if run is None or _reads is None:
        raise MirrorReadUnavailable()
    user_id = getattr(run, "mirror_execution_user_id", None)
    _authorize(user_id, [])
    state = getattr(run, "mirror_state", None)
    if isinstance(state, dict) and state.get("terminal_seal") is not None:
        raise MirrorReadUnavailable()
    return user_id


def _history_state(run):
    state = getattr(run, "mirror_state", None)
    if state is None:
        return {}, {}
    if not isinstance(state, dict):
        raise MirrorHistoryInvalid()
    bounds = state.get("history_bounds", {})
    if not isinstance(bounds, dict):
        raise MirrorHistoryInvalid()
    return state, bounds


def _history_position(position, *, mirror_id, epoch):
    if (not isinstance(position, dict) or position.get("mirror_id") != mirror_id
            or position.get("history_epoch") != epoch):
        raise MirrorHistoryInvalid()
    pair = (position.get("commit_seq"), position.get("entry_seq"))
    if any(type(value) is not int or value < 0 for value in pair):
        raise MirrorHistoryInvalid()
    return pair


def _history_bounds(bound, mirror_id):
    if (not isinstance(bound, dict) or bound.get("mirror_id", mirror_id) != mirror_id
            or any(not isinstance(bound.get(field), str) or not bound[field]
                   for field in ("source_id", "history_epoch"))):
        raise MirrorHistoryInvalid()
    lower, upper = (
        _history_position(bound.get(field), mirror_id=mirror_id, epoch=bound["history_epoch"])
        for field in ("lower_bound", "upper_bound")
    )
    if upper < lower:
        raise MirrorHistoryInvalid()
    return lower, upper


def capture_run_history(run, *, mirror_id):
    user_id = _history_identity(run)
    state, bounds = _history_state(run)
    if mirror_id in bounds:
        saved = bounds[mirror_id]
        saved_lower, saved_upper = _history_bounds(saved, mirror_id)
        bound = capture_bound(mirror_id=mirror_id, execution_user_id=user_id)
        lower, upper = _history_bounds(bound, mirror_id)
        if (saved["history_epoch"] != bound["history_epoch"]
                or saved["source_id"] != bound["source_id"]
                or not saved_lower <= lower <= saved_upper <= upper):
            raise MirrorHistoryInvalid()
        return {**saved, "retained_lower_bound": bound["lower_bound"]}
    bound = capture_bound(mirror_id=mirror_id, execution_user_id=user_id)
    _history_bounds(bound, mirror_id)
    run.mirror_state = {**state, "history_bounds": {**bounds, mirror_id: bound},
                        "source_ids": sorted(set(state.get("source_ids") or []) | {bound["source_id"]})}
    get_run_store().update_run(run)
    return bound


def read_run_history(run, *, mirror_id, after, through, limit):
    user_id = _history_identity(run)
    _, bounds = _history_state(run)
    bound = bounds.get(mirror_id)
    lower, upper = _history_bounds(bound, mirror_id)
    epoch = bound["history_epoch"]
    if (_history_position(through, mirror_id=mirror_id, epoch=epoch) != upper
            or not lower <= _history_position(after, mirror_id=mirror_id, epoch=epoch) <= upper):
        raise MirrorHistoryInvalid()
    require_run_data_access(run, user_id)
    page = read_incremental(mirror_id=mirror_id, execution_user_id=user_id,
                            after=after, through=through, limit=limit)
    if page.get("source_ids") != [bound["source_id"]]:
        raise MirrorHistoryInvalid()
    return page


def read_run_page(run: Any, *, mirror_id: str, after_key: Any, limit: int) -> dict:
    """The target's durable (run, mirror) pin remains authoritative on restart."""
    user_id = getattr(run, "mirror_execution_user_id", None)
    _authorize(user_id, [])
    if _reads is None:
        raise MirrorReadUnavailable()
    state = getattr(run, "mirror_state", None)
    if isinstance(state, dict) and state.get("terminal_seal") is not None:
        raise MirrorReadUnavailable()
    if state is not None:
        require_run_data_access(run, user_id)
    pin = _reads.acquire_pin(
        run_id=run.job_id, mirror_id=mirror_id, execution_user_id=user_id,
    )
    if pin.run_id != run.job_id or pin.mirror_id != mirror_id or not pin.source_id:
        raise MirrorReadUnavailable()
    _authorize(user_id, [pin.source_id])
    # Save provenance before any row can enter the sandbox, dataset or execution store.
    pins = dict((state or {}).get("pins") or {})
    reference = {"generation_id": pin.generation_id, "source_id": pin.source_id}
    if mirror_id in pins and pins[mirror_id] != reference:
        raise MirrorReadUnavailable()
    pins[mirror_id] = reference
    sources = sorted(set((state or {}).get("source_ids") or []) | {pin.source_id})
    run.mirror_state = {**(state or {}), "pins": pins, "source_ids": sources}
    get_run_store().update_run(run)
    page = _reads.read_page(
        pin=pin, execution_user_id=user_id, after_key=after_key, limit=limit,
    )
    if page.get("source_ids") != [pin.source_id] or page.get("generation_id") != pin.generation_id:
        raise MirrorReadUnavailable()
    _authorize(user_id, sources)
    freshness = dict(run.mirror_state.get("freshness") or {})
    freshness[mirror_id] = page.get("freshness")
    run.mirror_state = {**run.mirror_state, "freshness": freshness}
    get_run_store().update_run(run)
    return page
