"""Transactional mirror intent and conservative Operations lifecycle."""

from contextlib import AbstractContextManager, ExitStack
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.time import utc_now
from backend.metadata.capture.store import load_binding
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.store import MemoryMirrorStore, SqlMirrorStore
from backend.metadata.mirrors.types import Authority, PartitionIdentity
from backend.metadata.models import SourceRow

__all__ = [
    "resolve_object_binding",
    "resolve_object_bindings",
    "authorize_object_reads",
    "bind_source_read_authorizer",
    "ensure_open_intent",
    "reconcile_references",
    "OpenGenerationBinding",
    "reconcile_open_generation",
    "OpenPublicationIdentity",
    "CommittedOpenPublication",
    "ObserveCommittedOpenPublication",
    "publication_certificate_ref",
    "reconcile_open_publication",
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


def initial_history_epoch(mirror_id):
    return uuid5(NAMESPACE_URL, f"refraq:mirror:initial-history:{mirror_id}").hex


def current_open_preparations(*, authority: Authority, published_scope):
    """Select committed opens and replace a claim that belongs to a retired authority."""
    store = _storage()
    source_id = authority.source_id
    with store.transaction() as session:
        store.lock_channel(session, None)
        store.lock_sources(session, {source_id})
        state = load_binding(None if isinstance(store, MemoryMirrorStore) else session, source_id)
        scope = read_published_scope(session, source_id)
        if not _current_open_authority(state, authority, scope) or scope != published_scope:
            _error("MIRROR_CONTROL_CONFLICT")
        assignment_fence = state.get("allocation", {}).get("evidence", {}).get("target_fence")
        assignment_receipts = {}
        if assignment_fence and all(state.get(key) == value for key, value in assignment_fence["authority"].items()):
            assignment_receipts = assignment_fence["mirror_receipts"]
        selected = []
        for entry in scope:
            if not entry["included"]:
                continue
            mirror_id, revision = entry["mirror_id"], entry["mirror_revision"]
            operations = [op for op in store.ops(session, mirror_id) if op["kind"] == "open"
                          and op["state"] == "pending" and op["control_revision"] == revision]
            if not operations:
                continue
            if len(operations) != 1:
                _error("MIRROR_CONTROL_CONFLICT")
            operation, = operations
            claim = operation.get("allocation")
            if claim is not None and claim["binding"]["authority"] != asdict(authority):
                old = Authority(**claim["binding"]["authority"])
                if (old.source_id != source_id or old.resource_binding_id != authority.resource_binding_id
                        or old.owner_epoch >= authority.owner_epoch):
                    _error("MIRROR_CONTROL_CONFLICT")
                store.save_op(session, dict(operation, state="superseded"))
                operation_id = _id()
                _operation(session, {"id": mirror_id, "control": {"control_revision": revision}}, "open", operation_id)
            else:
                operation_id = operation["id"]
            selected.append(dict(entry, operation_id=operation_id,
                                 history_epoch=_preparation_history_epoch(session, mirror_id),
                                 assignment_fence_receipt=assignment_receipts.get(mirror_id)))
        return selected


def _preparation_history_epoch(session, mirror_id, *, lock=False):
    gate = session.get(HistoryGateRow, mirror_id, with_for_update=lock) if session is not None else None
    if gate is not None and gate.status == "invalidating":
        _error("MIRROR_CONTROL_CONFLICT")
    return gate.history_epoch if gate else initial_history_epoch(mirror_id)


def require_current_open_allocations(session, *, authority: Authority, allocations):
    """Validate observed allocations under the caller's Source lock without acquiring the registry."""
    store = _storage()
    for opened, generation_id in sorted(allocations, key=lambda item: item[0]["mirror_id"]):
        mirror_id = opened["mirror_id"]
        operation = next((op for op in store.ops(session, mirror_id) if op["id"] == opened["operation_id"]), None)
        claim = operation.get("allocation") if operation else None
        if (not claim or operation["kind"] != "open" or operation["state"] != "pending"
                or operation["control_revision"] != opened["mirror_revision"]
                or claim["observed"] is not True or claim["generation_id"] != generation_id
                or claim["binding"]["authority"] != asdict(authority)
                or claim["binding"]["history_epoch"] != opened["history_epoch"]
                or opened["history_epoch"] != _preparation_history_epoch(session, mirror_id, lock=True)):
            _error("MIRROR_CONTROL_CONFLICT")


def _current_open_authority(state, authority, scope):
    expected = asdict(authority)
    expected["binding_id"] = expected.pop("resource_binding_id")
    lineage = expected.pop("capture_generation")
    return (state and state.get("desired") == "configured" and authority.owner_epoch > 0
            and authority.runtime_instance_id and authority.resource_binding_id
            and state.get("capture_generation") is not None and str(state["capture_generation"]) == lineage
            and all(state.get(key) == value for key, value in expected.items())
            and state.get("published_scope") == scope)


def _require_open_binding(session, store, mirror, binding):
    authority = binding.authority
    source_id = mirror["source_id"]
    identity = dict(source_id=authority.source_id, object_id=binding.object_id,
                    table_identity=binding.table_identity, qualified_table=binding.qualified_table)
    if any(mirror[key] != value for key, value in identity.items()):
        _error("MIRROR_CONTROL_CONFLICT")
    catalog = store.binding(session, binding.object_id)
    if catalog is None or any(catalog[key] != value for key, value in identity.items()):
        _error("MIRROR_CONTROL_CONFLICT")
    state = load_binding(None if isinstance(store, MemoryMirrorStore) else session, source_id)
    scope = read_published_scope(session, source_id)
    if (not _current_open_authority(state, authority, scope)
            or not any(entry["mirror_id"] == mirror["id"] and entry["included"] for entry in scope)):
        _error("MIRROR_CONTROL_CONFLICT")
    return state


def _current_open_operation(session, store, mirror_id, operation_id, binding):
    mirror = _lock_mirror_source(session, mirror_id)
    _require_open_binding(session, store, mirror, binding)
    if not isinstance(store, MemoryMirrorStore):
        gate = session.get(HistoryGateRow, mirror_id, with_for_update=True)
        if gate is not None and gate.history_epoch != binding.history_epoch:
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


@dataclass(frozen=True)
class OpenPublicationIdentity:
    authority: Authority
    generation_id: str
    history_epoch: str
    snapshot_operation_id: str
    scan_offset: int
    completion_offset: int
    certificate_ref: str


@dataclass(frozen=True)
class CommittedOpenPublication:
    published_generation_id: str
    allocation: dict
    certificate: dict
    applied_offset: int
    history_bound: dict


class ObserveCommittedOpenPublication(Protocol):
    def __call__(
        self, *, mirror_id: str, operation_id: str, binding: OpenGenerationBinding,
        expected: OpenPublicationIdentity,
    ) -> AbstractContextManager[CommittedOpenPublication | None]:
        """Authenticate and guard a current target view through Management commit or rollback.

        Return the committed pointer, delivery_metadata for that generation, the complete
        certificates row, the generation's applied offset and history_bound. The bounded
        guard must prevent changes to this view and must never acquire Management locks.
        """
        ...


def publication_certificate_ref(evidence: dict) -> str:
    """Reference the exact certificate evidence independently of target cursor movement."""
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + sha256(payload.encode()).hexdigest()


def _open_publication_binding(operation, expected):
    claim = operation.get("allocation")
    if (not claim or claim["observed"] is not True or claim["generation_id"] != expected.generation_id
            or claim["mirror_revision"] != operation["control_revision"]
            or claim["binding"]["authority"] != asdict(expected.authority)
            or claim["binding"]["history_epoch"] != expected.history_epoch):
        _error("MIRROR_CONTROL_CONFLICT")
    data = claim["binding"]
    return OpenGenerationBinding(**dict(data, authority=expected.authority, columns=dict(data["columns"]),
                                        key_columns=tuple(data["key_columns"]),
                                        partition_identity=PartitionIdentity(**data["partition_identity"])))


def _publication_snapshot(state, mirror_id, operation, binding, expected):
    snapshot = state.get("incremental_snapshots", {}).get("generations", {}).get(expected.generation_id)
    allocated = dict(authority=asdict(binding.authority), mirror_id=mirror_id,
                     mirror_revision=operation["control_revision"], allocation_operation_id=operation["id"],
                     generation_id=expected.generation_id, table_identity=binding.table_identity,
                     qualified_table=binding.qualified_table, history_epoch=binding.history_epoch,
                     schema_fingerprint=binding.schema_fingerprint, data_partition=asdict(binding.partition_identity))
    if (not snapshot or snapshot.get("state") != "catching_up" or snapshot.get("receipt") is not True
            or snapshot.get("id") != expected.snapshot_operation_id
            or snapshot.get("scan", {}).get("offset") != expected.scan_offset
            or snapshot.get("completion", {}).get("offset") != expected.completion_offset
            or any(snapshot.get("binding", {}).get(key) != value for key, value in allocated.items())):
        _error("MIRROR_CONTROL_CONFLICT")
    return snapshot["binding"]


def _validate_observed_publication(observed, *, mirror_id, operation_id, binding, expected, snapshot):
    if not isinstance(observed, CommittedOpenPublication) or observed.published_generation_id != expected.generation_id:
        _error("MIRROR_CONTROL_CONFLICT")
    allocation = observed.allocation
    certificate = observed.certificate
    shared = dict(operation_id=operation_id, generation_id=expected.generation_id,
                  table_identity=binding.table_identity, capture_generation=binding.authority.capture_generation,
                  schema_fingerprint=binding.schema_fingerprint, partition_identity=asdict(binding.partition_identity))
    aliases = {"timestamp": "timestamp without time zone", "timestamptz": "timestamp with time zone"}
    target_binding = dict(shared, authority=asdict(binding.authority), mirror_id=mirror_id,
                          history_epoch=binding.history_epoch, start_offset=binding.start_offset,
                          column_names=list(binding.columns), key_columns=list(binding.key_columns),
                          native_types={name: aliases.get(kind, kind) for name, kind in binding.columns.items()},
                          status="published", cleanup_pending=False)
    if (not isinstance(allocation, dict) or any(allocation.get(key) != value for key, value in target_binding.items())
            or not isinstance(certificate, dict) or certificate.get("published") is not True
            or not isinstance(certificate.get("verified_by"), str) or not certificate["verified_by"]
            or certificate.get("authority") != target_binding["authority"]
            or certificate.get("operation_id") != operation_id or certificate.get("generation_id") != expected.generation_id):
        _error("MIRROR_CONTROL_CONFLICT")
    evidence = certificate.get("evidence")
    if (not isinstance(evidence, dict) or any(evidence.get(key) != value for key, value in shared.items())
            or publication_certificate_ref(evidence) != expected.certificate_ref
            or type(evidence.get("end_offset")) is not int or type(observed.applied_offset) is not int
            or not binding.start_offset <= evidence["end_offset"] <= observed.applied_offset):
        _error("MIRROR_CONTROL_CONFLICT")
    completion = evidence.get("source_completion")
    if (not isinstance(completion, dict) or completion.get("operation") != expected.snapshot_operation_id
            or completion.get("table") != binding.qualified_table
            or any(completion.get(key) != snapshot[key] for key in ("notification_topic", "notification_partition"))):
        _error("MIRROR_CONTROL_CONFLICT")
    terminals = completion.get("terminals")
    required = (("TABLE_SCAN_COMPLETED", expected.scan_offset), ("COMPLETED", expected.completion_offset))
    if (not isinstance(terminals, list) or len(terminals) != len(required)
            or any(not isinstance(terminal, dict) or type(terminal.get("offset")) is not int
                   or terminal["offset"] != offset or not isinstance(terminal.get("event"), dict)
                   or terminal["event"].get("id") != expected.snapshot_operation_id
                   or terminal["event"].get("type") != kind
                   for terminal, (kind, offset) in zip(terminals, required))):
        _error("MIRROR_CONTROL_CONFLICT")


def reconcile_open_publication(
    *, mirror_id: str, operation_id: str, expected: OpenPublicationIdentity,
    observe_committed: ObserveCommittedOpenPublication,
) -> Literal["applied", "already_applied"]:
    """Project the first published generation or acknowledge its historical receipt."""
    from backend.metadata.mirrors.history import admit_observed_history

    store = _storage()
    if (not isinstance(store, SqlMirrorStore) or not isinstance(expected, OpenPublicationIdentity)
            or not isinstance(expected.authority, Authority)
            or not expected.snapshot_operation_id or not expected.certificate_ref
            or type(expected.scan_offset) is not int or type(expected.completion_offset) is not int
            or not 0 <= expected.scan_offset < expected.completion_offset):
        _error("MIRROR_CONTROL_CONFLICT")
    receipt = asdict(expected)
    authority = receipt["authority"]
    if any(type(authority[key]) is not int for key in ("owner_epoch", "control_revision", "credential_revision")):
        _error("MIRROR_CONTROL_CONFLICT")
    with ExitStack() as target_guard, store.transaction() as session:
        mirror = _lock_mirror_source(session, mirror_id)
        operation = next((op for op in store.ops(session, mirror_id) if op["id"] == operation_id), None)
        if operation is None or operation["kind"] != "open":
            _error("MIRROR_CONTROL_CONFLICT")
        if "publication_receipt" in operation:
            if operation["state"] != "applied" or operation["publication_receipt"] != receipt:
                _error("MIRROR_CONTROL_CONFLICT")
            return "already_applied"
        if (operation["state"] != "pending" or operation["control_revision"] != mirror["control"]["control_revision"]
                or mirror["published_generation_id"] is not None
                or expected.history_epoch != initial_history_epoch(mirror_id)):
            _error("MIRROR_CONTROL_CONFLICT")
        binding = _open_publication_binding(operation, expected)
        state = _require_open_binding(session, store, mirror, binding)
        source = session.get(SourceRow, mirror["source_id"], populate_existing=True)
        if (source.status != "active" or source.engine != "postgresql" or not source.capture_credential_ciphertext
                or source.capture_revision != expected.authority.credential_revision
                or state.get("applied_revision") != expected.authority.control_revision):
            _error("MIRROR_CONTROL_CONFLICT")
        snapshot = _publication_snapshot(state, mirror_id, operation, binding, expected)
        mirror_row = session.get(MirrorRow, mirror_id, with_for_update=True)
        gate = session.get(HistoryGateRow, mirror_id, with_for_update=True, populate_existing=True)
        if gate is not None and (gate.status != "available" or gate.history_epoch != expected.history_epoch):
            _error("MIRROR_CONTROL_CONFLICT")
        observed = target_guard.enter_context(observe_committed(
            mirror_id=mirror_id, operation_id=operation_id, binding=deepcopy(binding), expected=expected,
        ))
        _validate_observed_publication(observed, mirror_id=mirror_id, operation_id=operation_id,
                                       binding=binding, expected=expected, snapshot=snapshot)
        bound = observed.history_bound
        if not isinstance(bound, dict) or bound.get("mirror_id") != mirror_id:
            _error("MIRROR_CONTROL_CONFLICT")
        lower, upper = admit_observed_history(session, mirror=mirror_row, gate=gate,
                                              history_epoch=expected.history_epoch, bound=bound)
        store.save(session, dict(mirror, published_generation_id=observed.published_generation_id,
                                 capture_generation=binding.authority.capture_generation,
                                 history_epoch=bound["history_epoch"], retained_lower_bound=lower,
                                 committed_upper_bound=upper))
        store.save_op(session, dict(operation, state="applied", publication_receipt=receipt))
        return "applied"
    _error("MIRROR_CONTROL_CONFLICT")


def _present(session, mirror):
    result = deepcopy(mirror)
    gate = None if isinstance(session, MemoryMirrorStore) else session.get(HistoryGateRow, mirror["id"])
    result["history_epoch"] = gate.history_epoch if gate is not None else None
    if gate is None or gate.status != "available" or gate.history_epoch != mirror.get("history_epoch"):
        result["retained_lower_bound"] = result["committed_upper_bound"] = None
    result["published_reference_count"] = sum(
        mid == mirror["id"] for _, mid in _storage().refs(session)
    )
    result["operations"] = sorted(
        ({key: value for key, value in op.items() if key not in {"allocation", "publication_receipt"}}
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
