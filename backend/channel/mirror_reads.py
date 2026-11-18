"""Run-scoped authorized mirror gateway and conservative whole-run provenance."""

from typing import Any

from backend.admin.user_store import get_user_store
from backend.channel.run_store import get_run_store
from backend.core.errors import AppError
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.service import resolve_object_binding, authorize_object_reads
from backend.channel.models import ChannelRunRow
from backend.core.db import session_scope
from backend.jobs.store import get_job_store
from backend.metadata.source_access import allows


class MirrorReadUnavailable(AppError):
    code = "MIRROR_READ_UNAVAILABLE"
    http_status = 503


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
        if (not isinstance(pins, dict) or any(
                not isinstance(pin, dict) or not pin.get("generation_id") or not pin.get("source_id")
                for pin in pins.values())
                or sorted(set(pin["source_id"] for pin in pins.values())) != state.get("source_ids")):
            raise MirrorReadUnavailable()
        if terminal_proof != {"run_id": run_id, "pins": pins, "source_ids": state["source_ids"]}:
            raise MirrorReadUnavailable()


def release_completed_run(run) -> None:
    if getattr(run, "mirror_state", None) is None:
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
    if not ids:
        return
    if _reads is None:
        raise MirrorReadUnavailable()
    if session is not None:
        authorize_object_reads(object_ids=ids, execution_user_id=user_id, session=session)
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


def require_run_data_access(run: Any, user_id: str | None) -> None:
    """Authorize the complete payload, including nested/mixed transforms."""
    state = getattr(run, "mirror_state", None)
    if state is None and not mirror_graph(getattr(run, "graph", None)):
        return
    sources = state.get("source_ids") if isinstance(state, dict) else None
    if not isinstance(sources, list) or not sources or any(
        not isinstance(source, str) or not source for source in sources
    ):
        raise MirrorDataForbidden()
    _authorize(user_id, sources)


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
