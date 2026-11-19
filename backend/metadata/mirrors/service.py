"""Transactional mirror intent and conservative Operations lifecycle."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.time import utc_now
from backend.metadata.capture.store import load_binding
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.store import MemoryMirrorStore, SqlMirrorStore
from backend.metadata.mirrors.types import Authority, PartitionIdentity

__all__ = [
    "resolve_object_binding",
    "resolve_object_bindings",
    "authorize_object_reads",
    "bind_source_read_authorizer",
    "ensure_open_intent",
    "reconcile_references",
    "OpenGenerationBinding",
    "reconcile_open_generation",
    "bind_management",
    "get_mirror",
    "list_mirrors",
    "set_enabled",
    "delete_mirror",
    "TargetLifecycle",
]


class MirrorError(AppError):
    def __init__(self, code, status):
        self.code = code
        self.http_status = status
        super().__init__()


class TargetLifecycle(Protocol):
    def close_for_delete(
        self, *, mirror_id: str, source_id: str, control_revision: int
    ) -> None:
        """Atomically close all target generations to new pins or reject.

        Must prove the matching stopped authority and absence of all durable pins,
        including retired generations. Idempotent after management rollback; never
        drops Source resources. Raise on unknown/unreachable evidence.
        """
        ...


_store = None
_target = None
_source_read_authorizer = None


def bind_source_read_authorizer(authorizer=None):
    """Bind current-grant validation accepting the caller's management session."""
    global _source_read_authorizer
    if authorizer is not None and not callable(authorizer):
        raise TypeError("Source read authorizer must be callable")
    _source_read_authorizer = authorizer


def resolve_object_bindings(*, object_ids, session=None):
    """Preview supported bindings without reservations, locks or capture intent."""
    store = _storage()
    if session is None:
        with store.transaction() as owned:
            return resolve_object_bindings(object_ids=object_ids, session=owned)
    mirrors = store.preview_mirrors(session)
    result = []
    for object_id in sorted(set(object_ids)):
        binding = store.preview_binding(session, object_id)
        if binding is None:
            _error("MIRROR_NOT_FOUND", 404)
        mirror = next((row for row in mirrors if
                       (row["source_id"], row["table_identity"]) ==
                       (binding["source_id"], binding["table_identity"])), None)
        if mirror is not None and any(mirror[key] != binding[key] for key in
                                     ("source_id", "object_id", "qualified_table", "table_identity")):
            _error("MIRROR_CONTROL_CONFLICT")
        mid = mirror["id"] if mirror is not None else _mirror_id(binding)
        enabled = mirror["enabled"] if mirror is not None else False
        result.append(dict(binding, id=mid, mirror_id=mid, enabled=enabled,
                           needs_open=not enabled,
                           status=mirror["status"] if mirror is not None else "waiting"))
    return deepcopy(result)


def resolve_object_binding(object_id, *, session=None):
    return resolve_object_bindings(object_ids=[object_id], session=session)[0]


def authorize_object_reads(*, object_ids, execution_user_id, mirror_ids=(), session=None):
    """Resolve and authorize using one caller session; never open a nested session."""
    if _source_read_authorizer is None:
        _error("MIRROR_READ_UNAVAILABLE", 503)
    if session is None:
        with _storage().transaction() as owned:
            return authorize_object_reads(
                object_ids=object_ids, mirror_ids=mirror_ids,
                execution_user_id=execution_user_id, session=owned,
            )
    bindings = resolve_object_bindings(object_ids=object_ids, session=session)
    for mirror_id in sorted(set(mirror_ids)):
        mirror = _find(session, mirror_id)
        bindings.append({key: mirror[key] for key in
                         ("id", "source_id", "object_id", "table_identity", "qualified_table")})
    for source_id in sorted({binding["source_id"] for binding in bindings}):
        outcome = _source_read_authorizer(
            session=session, execution_user_id=execution_user_id, source_id=source_id,
        )
        if outcome is not None:
            _error("AUTH_FORBIDDEN", 403)
    return bindings


def bind_management(*, store=None, target=None):
    global _store, _target
    _store = store
    _target = target


def _storage():
    global _store
    if _store is None:
        _store = (
            MemoryMirrorStore()
            if get_settings().store_backend == "memory"
            else SqlMirrorStore()
        )
    return _store


def _error(code, status=409):
    raise MirrorError(code, status)


def _id():
    return "mop_" + uuid4().hex


def _find(session, mirror_id):
    for row in _storage().list(session):
        if row["id"] == mirror_id:
            return row
    _error("MIRROR_NOT_FOUND", 404)


def _lock_mirror_source(session, mirror_id):
    store = _storage()
    store.lock_channel(session, None)
    for mirror in store.preview_mirrors(session):
        if mirror["id"] == mirror_id:
            store.lock_sources(session, {mirror["source_id"]})
            return mirror
    _error("MIRROR_NOT_FOUND", 404)


def read_published_scope(session, source_id):
    """Read committed mirrors under the caller's Source lock, without locking the registry."""
    return sorted((
        dict(mirror_id=mirror["id"], qualified_table=mirror["qualified_table"],
             table_identity=mirror["table_identity"],
             mirror_revision=mirror["control"]["control_revision"],
             included=mirror["enabled"] and referenced)
        for mirror, referenced in _storage().scope_rows(session, source_id)
    ), key=lambda table: (table["qualified_table"], table["mirror_id"]))


def _mirror_id(binding):
    return "mir_" + uuid5(
        NAMESPACE_URL,
        repr(("refraq:mirror", binding["source_id"], binding["table_identity"])),
    ).hex


def _new(binding):
    return dict(
        binding,
        id=_mirror_id(binding),
        enabled=True,
        status="waiting",
        published_generation_id=None,
        capture_generation=None,
        history_epoch=None,
        retained_lower_bound=None,
        committed_upper_bound=None,
        control=dict(
            control_revision=1,
            credential_revision=None,
            owner_epoch=None,
            runtime_instance_id=None,
            applied_revision=None,
            observed_at=None,
            stop_ack=None,
        ),
        progress=None,
        profile={"qualification": "unverified"},
        readiness=[
            dict(
                key="capture_admission",
                result="unknown",
                expected="verified profile and current evidence",
                observed=None,
                observed_at=None,
                owner="deployer",
                action="Qualify capture before admission",
            )
        ],
        fault=None,
    )


def _operation(session, mirror, kind, operation_id, **extra):
    store = _storage()
    for previous in store.ops(session, mirror["id"]):
        if (
            previous["state"] == "pending"
            and previous["control_revision"] < mirror["control"]["control_revision"]
        ):
            previous["state"] = "superseded"
            store.save_op(session, previous)
    op = dict(
        id=operation_id,
        mirror_id=mirror["id"],
        kind=kind,
        state="pending",
        control_revision=mirror["control"]["control_revision"],
        observed_evidence_refs=[],
        fault_code=None,
        requested_at=utc_now().isoformat(),
        **extra,
    )
    store.save_op(session, op)


def _resolve(session, object_ids):
    store = _storage()
    bindings = []
    for object_id in sorted(set(object_ids)):
        binding = store.binding(session, object_id)
        if binding is None:
            _error("MIRROR_NOT_FOUND", 404)
        bindings.append(binding)
    return bindings


def _check_version(session, channel_id, version, object_ids):
    old = _storage().publication(session, channel_id)
    if old and (
        old["channel_version"] > version
        or (old["channel_version"] == version and old["object_ids"] != list(object_ids))
    ):
        _error("MIRROR_CONTROL_CONFLICT")


def _lock_withdrawn_sources(session, channel_id):
    store = _storage()
    previous_ids = {mirror_id for cid, mirror_id in store.refs(session) if cid == channel_id}
    if previous_ids:
        store.lock_sources(session, {
            mirror["source_id"] for mirror in store.preview_mirrors(session)
            if mirror["id"] in previous_ids
        })


def ensure_open_intent(
    session, *, operation_id, channel_id, channel_version, object_ids,
    confirmed_mirrors_to_open=None,
):
    store = _storage()
    store.lock_channel(session, channel_id)
    ids = sorted(set(object_ids))
    request = dict(
        channel_id=channel_id, channel_version=channel_version, object_ids=ids
    )
    if confirmed_mirrors_to_open is not None:
        request["confirmed_mirrors_to_open"] = sorted(
            confirmed_mirrors_to_open, key=lambda item: item["object_id"],
        )
    receipt = store.receipt(session, operation_id)
    if receipt:
        if receipt["request"] != request:
            _error("MIRROR_CONTROL_CONFLICT")
        return deepcopy(receipt["result"])
    _check_version(session, channel_id, channel_version, ids)
    _lock_withdrawn_sources(session, channel_id)
    bindings = _resolve(session, ids)
    mirrors = store.list(session)
    if confirmed_mirrors_to_open is not None:
        expected = [
            {key: binding[key] for key in ("source_id", "object_id", "mirror_id")}
            for binding in resolve_object_bindings(object_ids=ids, session=session)
            if binding["needs_open"]
        ]
        if request["confirmed_mirrors_to_open"] != expected:
            _error("MIRROR_CONTROL_CONFLICT")
    result = []
    selected = []
    for binding in bindings:
        mirror = next(
            (
                m
                for m in mirrors
                if (m["source_id"], m["table_identity"])
                == (binding["source_id"], binding["table_identity"])
            ),
            None,
        )
        if mirror is None:
            mirror = _new(binding)
            store.save(session, mirror)
            _operation(session, mirror, "open", _id())
        elif any(
            mirror[key] != binding[key]
            for key in ("source_id", "object_id", "qualified_table", "table_identity")
        ):
            _error("MIRROR_CONTROL_CONFLICT")
        elif not mirror["enabled"]:
            mirror["enabled"] = True
            mirror["status"] = "unknown"
            mirror["control"]["control_revision"] += 1
            store.save(session, mirror)
            _operation(session, mirror, "open", _id())
        selected.append(mirror["id"])
        result.append(
            dict(
                source_id=mirror["source_id"],
                object_id=binding["object_id"],
                mirror_id=mirror["id"],
            )
        )
    store.replace_refs(session, channel_id, channel_version, selected)
    store.save_publication(session, channel_id, channel_version, ids)
    store.save_receipt(session, operation_id, request, result)
    return deepcopy(result)


def reconcile_references(session, *, channel_id, channel_version, object_ids):
    store = _storage()
    store.lock_channel(session, channel_id)
    ids = sorted(set(object_ids))
    _check_version(session, channel_id, channel_version, ids)
    _lock_withdrawn_sources(session, channel_id)
    bindings = _resolve(session, ids)
    mirrors = store.list(session)
    selected = []
    for binding in bindings:
        mirror = next(
            (
                m
                for m in mirrors
                if m["source_id"] == binding["source_id"]
                and m["table_identity"] == binding["table_identity"]
            ),
            None,
        )
        if mirror is None or any(
            mirror[key] != binding[key]
            for key in ("source_id", "object_id", "qualified_table", "table_identity")
        ):
            _error("MIRROR_CONTROL_CONFLICT")
        selected.append(mirror["id"])
    store.replace_refs(session, channel_id, channel_version, selected)
    store.save_publication(session, channel_id, channel_version, ids)


@dataclass(frozen=True)
class OpenGenerationBinding:
    authority: Authority
    object_id: str
    table_identity: str
    qualified_table: str
    history_epoch: str
    schema_fingerprint: str
    columns: dict[str, str]
    key_columns: tuple[str, ...]
    partition_identity: PartitionIdentity
    start_offset: int


def _current_open_operation(session, store, mirror_id, operation_id, binding):
    mirror = _lock_mirror_source(session, mirror_id)
    authority = binding.authority
    source_id = mirror["source_id"]
    identity = dict(source_id=authority.source_id, object_id=binding.object_id,
                    table_identity=binding.table_identity, qualified_table=binding.qualified_table)
    if any(mirror[key] != value for key, value in identity.items()):
        _error("MIRROR_CONTROL_CONFLICT")
    catalog = store.binding(session, binding.object_id)
    if catalog is None or any(catalog[key] != value for key, value in identity.items()):
        _error("MIRROR_CONTROL_CONFLICT")
    if not isinstance(store, MemoryMirrorStore):
        gate = session.get(HistoryGateRow, mirror_id, with_for_update=True)
        if gate is not None and gate.history_epoch != binding.history_epoch:
            _error("MIRROR_CONTROL_CONFLICT")
    state = load_binding(None if isinstance(store, MemoryMirrorStore) else session, source_id)
    scope = read_published_scope(session, source_id)
    expected = asdict(authority)
    expected["binding_id"] = expected.pop("resource_binding_id")
    expected.pop("capture_generation")
    if (not state or state.get("desired") != "configured" or authority.owner_epoch <= 0
            or not authority.runtime_instance_id or not authority.resource_binding_id
            or state.get("capture_generation") is None
            or str(state["capture_generation"]) != authority.capture_generation
            or any(state.get(key) != value for key, value in expected.items())
            or state.get("published_scope") != scope
            or not any(entry["mirror_id"] == mirror_id and entry["included"] for entry in scope)):
        _error("MIRROR_CONTROL_CONFLICT")
    revision = mirror["control"]["control_revision"]
    operation = next((op for op in store.ops(session, mirror_id) if op["id"] == operation_id), None)
    if (operation is None or operation["kind"] != "open" or operation["state"] != "pending"
            or operation["control_revision"] != revision):
        _error("MIRROR_CONTROL_CONFLICT")
    return operation, revision


def reconcile_open_generation(*, mirror_id: str, operation_id: str, binding: OpenGenerationBinding,
                              verify_binding, allocate) -> str:
    """Reconcile the pending open through deployment-supplied verification and committed allocation.

    The verifier checks previously gathered fence, full schema/key and transport evidence against
    the request under management locks, and returns True on an exact match. The allocator accepts
    bootstrap arguments, requires the prepared target fence and returns the generation id after
    target commit. Allocation evidence is private to the pending operation.
    """
    binding = deepcopy(binding)
    if (not binding.history_epoch or not binding.schema_fingerprint or not binding.key_columns
            or len(set(binding.key_columns)) != len(binding.key_columns)
            or not set(binding.key_columns) <= binding.columns.keys()
            or not binding.partition_identity.runtime_cluster_id or not binding.partition_identity.topic_incarnation_id
            or binding.partition_identity.partition != 0 or binding.start_offset < -1):
        _error("MIRROR_CONTROL_CONFLICT")
    binding_data = asdict(binding)
    binding_data["columns"] = [list(item) for item in binding.columns.items()]
    binding_data["key_columns"] = list(binding.key_columns)

    store = _storage()
    with store.transaction() as session:
        operation, revision = _current_open_operation(session, store, mirror_id, operation_id, binding)
        claim = operation.get("allocation")
        if claim is not None and (claim["binding"] != binding_data or claim["mirror_revision"] != revision):
            _error("MIRROR_CONTROL_CONFLICT")
        if verify_binding(binding=deepcopy(binding), mirror_id=mirror_id, operation_id=operation_id,
                          mirror_revision=revision) is not True:
            _error("MIRROR_CONTROL_CONFLICT")
        if claim is None:
            claim = dict(generation_id=uuid4().hex, mirror_revision=revision, binding=binding_data, observed=False)
            store.save_op(session, dict(operation, allocation=claim))
        generation_id = claim["generation_id"]
        if claim["observed"]:
            return generation_id

    if allocate(mirror_id=mirror_id, operation_id=operation_id, generation_id=generation_id,
                authority=binding.authority, table_identity=binding.table_identity, history_epoch=binding.history_epoch,
                schema_fingerprint=binding.schema_fingerprint, columns=dict(binding.columns),
                key_columns=binding.key_columns, partition_identity=binding.partition_identity,
                start_offset=binding.start_offset, require_prepared_fence=True) != generation_id:
        _error("MIRROR_CONTROL_CONFLICT")

    with store.transaction() as session:
        operation, revision = _current_open_operation(session, store, mirror_id, operation_id, binding)
        current = operation.get("allocation")
        if (revision != claim["mirror_revision"] or current is None
                or any(current[key] != claim[key] for key in ("generation_id", "mirror_revision", "binding"))):
            _error("MIRROR_CONTROL_CONFLICT")
        if not current["observed"]:
            store.save_op(session, dict(operation, allocation=dict(current, observed=True)))
    return generation_id


def _present(session, mirror):
    result = deepcopy(mirror)
    gate = None if isinstance(session, MemoryMirrorStore) else session.get(HistoryGateRow, mirror["id"])
    result["history_epoch"] = gate.history_epoch if gate is not None else None
    result["published_reference_count"] = sum(
        mid == mirror["id"] for _, mid in _storage().refs(session)
    )
    result["operations"] = sorted(
        ({key: value for key, value in op.items() if key != "allocation"}
         for op in _storage().ops(session, mirror["id"])),
        key=lambda op: (op["requested_at"], op["id"]),
    )
    return result


def get_mirror(mirror_id):
    with _storage().transaction() as session:
        return _present(session, _find(session, mirror_id))


def list_mirrors(*, limit=100, offset=0, source_id=None, status=None, q=None):
    with _storage().transaction() as session:
        rows = _storage().list(session)
        needle = (q or "").casefold()
        rows = [
            row
            for row in rows
            if (source_id is None or row["source_id"] == source_id)
            and (status is None or row["status"] == status)
            and (
                not needle
                or any(
                    needle in row[key].casefold()
                    for key in ("source_key", "source_name", "qualified_table")
                )
            )
        ]
        rows.sort(
            key=lambda row: (row["source_key"], row["qualified_table"], row["id"])
        )
        return dict(
            items=[_present(session, row) for row in rows[offset : offset + limit]],
            total=len(rows),
            limit=limit,
            offset=offset,
        )


def _audit(
    session, mirror, audit_action, operation_id, actor_user_id, actor_token_id, **detail
):
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="mirror",
        resource_id=mirror["id"],
        action="mirror." + audit_action,
        result="success",
        detail=dict(operation_id=operation_id, source_id=mirror["source_id"], **detail),
        session=None if isinstance(session, MemoryMirrorStore) else session,
    )


def set_enabled(mirror_id, *, enabled, actor_user_id, actor_token_id=None):
    store = _storage()
    with store.transaction() as session:
        _lock_mirror_source(session, mirror_id)
        mirror = _find(session, mirror_id)
        operation_id = _id()
        mirror["enabled"] = enabled
        mirror["control"]["control_revision"] += 1
        mirror["status"] = "unknown" if enabled else "disable_pending"
        store.save(session, mirror)
        _operation(session, mirror, "enable" if enabled else "disable", operation_id)
        _audit(
            session,
            mirror,
            "enable" if enabled else "disable",
            operation_id,
            actor_user_id,
            actor_token_id,
            enabled=enabled,
        )
        return dict(mirror=_present(session, mirror), operation_id=operation_id)


def delete_mirror(mirror_id, *, actor_user_id, actor_token_id=None):
    store = _storage()
    with store.transaction() as session:
        _lock_mirror_source(session, mirror_id)
        mirror = _find(session, mirror_id)
        if any(mid == mirror_id for _, mid in store.refs(session)):
            _error("MIRROR_REFERENCED")
        if mirror["enabled"]:
            _error("MIRROR_IN_USE")
        if _target is None:
            _error("MIRROR_READ_UNAVAILABLE", 503)
        _target.close_for_delete(
            mirror_id=mirror_id,
            source_id=mirror["source_id"],
            control_revision=mirror["control"]["control_revision"],
        )
        _audit(session, mirror, "delete", _id(), actor_user_id, actor_token_id)
        store.delete(session, mirror_id)
