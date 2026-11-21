"""Transactional mirror intent and conservative Operations lifecycle."""

from contextlib import AbstractContextManager, ExitStack
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.time import utc_now
from backend.metadata.capture.store import load_binding
from backend.metadata.mirrors.errors import MirrorError
from backend.metadata.mirrors.history import admit_observed_history
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.schemas import Operation
from backend.metadata.mirrors.store import MemoryMirrorStore, SqlMirrorStore
from backend.metadata.mirrors.types import Authority, PartitionIdentity
from backend.metadata.models import SourceRow

__all__ = [
    "catalog_mirror",
    "enable_for_object",
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


def catalog_mirror(object_id, *, source_id, can_read, can_write):
    """Project the eligible Catalog action and the caller-visible registry link."""
    store = _storage()
    with store.transaction() as session:
        binding = store.preview_binding(session, object_id)
        mirror = store.get_by_object(session, source_id, object_id)
        eligible = binding is not None and binding["source_id"] == source_id
        mirror_id = mirror["id"] if mirror and can_read else None
        if not eligible and mirror_id is None:
            return None
        can_enable = bool(can_write and eligible and (mirror is None or not mirror["enabled"]))
        return dict(can_enable=can_enable, mirror_id=mirror_id)


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
    mirror = _storage().get(session, mirror_id)
    if mirror is None:
        _error("MIRROR_NOT_FOUND", 404)
    return mirror


def _lock_mirror_source(session, mirror_id):
    store = _storage()
    store.lock_registry(session)
    mirror = _find(session, mirror_id)
    store.lock_sources(session, {mirror["source_id"]})
    return _find(session, mirror_id)


def read_published_scope(session, source_id):
    """Read committed mirrors under the caller's Source lock, without locking the registry."""
    return sorted((
        dict(mirror_id=mirror["id"], qualified_table=mirror["qualified_table"],
             table_identity=mirror["table_identity"],
             mirror_revision=mirror["control"]["control_revision"],
             included=mirror["enabled"])
        for mirror in _storage().scope_rows(session, source_id)
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


def enable_for_object(object_id, *, actor_user_id, actor_token_id=None):
    """Persist the explicit intent for a caller-authorized, canonical Catalog object."""
    store = _storage()
    with store.transaction() as session:
        store.lock_registry(session)
        binding = store.binding(session, object_id)
        if binding is None:
            _error("MIRROR_NOT_FOUND", 404)
        mirror = store.get_by_object(session, binding["source_id"], binding["object_id"])
        if mirror is not None:
            if any(mirror[key] != binding[key] for key in (
                "source_id", "object_id", "qualified_table", "table_identity",
            )):
                _error("MIRROR_CONTROL_CONFLICT")
            return _apply_enabled(session, mirror, True, actor_user_id, actor_token_id)

        mirror = _new(binding)
        store.save(session, mirror)
        operation_id = _id()
        _operation(session, mirror, "open", operation_id, operator_intent=True)
        _audit(session, mirror, "enable", operation_id, actor_user_id, actor_token_id, enabled=True)
        return dict(mirror=_present(session, mirror), operation_id=operation_id)


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


def _replacement_open(session, state, entry):
    allocation = state.get("allocation", {})
    command = allocation.get("command", {})
    if command.get("kind") != "replace_owner":
        return None
    operation_id = command["operation_id"]
    replacement = command["replacement"]["scope"]
    submission = replacement["submission"]
    recovery = session.get(RecoveryRow, operation_id, populate_existing=True)
    epoch = submission["history_epoch"]
    if (recovery is None or recovery.source_id != state["source_id"] or recovery.mirror_id != entry["mirror_id"]
            or recovery.identity != replacement["recovery_request_identity"]
            or recovery.journal.get("state") not in {"dispatched", "applied"}
            or recovery.journal.get("submission_command") != submission
            or submission["capture_generation"] != str(state["capture_generation"])
            or epoch != _preparation_history_epoch(session, entry["mirror_id"], lock=True)):
        _error("MIRROR_CONTROL_CONFLICT")
    return submission, recovery.journal.get("request", {}).get("action")


def current_open_preparations(*, authority: Authority, published_scope, observe_committed):
    """Select current applied opens before preparing pending allocations for the Source."""
    store = _storage()
    source_id = authority.source_id
    with store.transaction() as session:
        store.lock_registry(session)
        store.lock_sources(session, {source_id})
        state = load_binding(None if isinstance(store, MemoryMirrorStore) else session, source_id)
        scope = read_published_scope(session, source_id)
        if not _current_open_authority(state, authority, scope) or scope != published_scope:
            _error("MIRROR_CONTROL_CONFLICT")
        allocation = state.get("allocation", {})
        assignment_fence = allocation.get("evidence", {}).get("target_fence")
        assignment_receipts = {}
        if assignment_fence and all(state.get(key) == value for key, value in assignment_fence["authority"].items()):
            assignment_receipts = assignment_fence["mirror_receipts"]
        included = [entry for entry in scope if entry["included"]]
        pending, applied = [], []
        has_publication = False
        reopen = {}
        for entry in included:
            history = [op for op in store.ops(session, entry["mirror_id"]) if op["kind"] == "open"]
            if allocation.get("command", {}).get("kind") == "replace_owner":
                if len(included) != 1 or not isinstance(store, SqlMirrorStore):
                    _error("MIRROR_CONTROL_CONFLICT")
                submission, _ = _replacement_open(session, state, entry)
                operation_id = submission["operation_id"]
                operation = next((op for op in history if op["id"] == operation_id), None)
                if operation is None:
                    _operation(session, {"id": entry["mirror_id"], "control": {"control_revision": entry["mirror_revision"]}},
                               "open", operation_id, replacement_generation_id=submission["generation_id"])
                    operation = next(op for op in store.ops(session, entry["mirror_id"]) if op["id"] == operation_id)
                if (operation.get("replacement_generation_id") != submission["generation_id"]
                        or operation["control_revision"] != entry["mirror_revision"]
                        or operation["state"] not in {"pending", "applied"}):
                    _error("MIRROR_CONTROL_CONFLICT")
                (applied if operation["state"] == "applied" else pending).append((entry, operation))
                continue
            published = [op for op in history if "publication_receipt" in op and op["state"] == "applied"]
            has_publication |= bool(published)
            current = [op for op in history if op["state"] in {"pending", "applied"}
                       and op["control_revision"] == entry["mirror_revision"]]
            if len(current) > 1:
                _error("MIRROR_CONTROL_CONFLICT")
            if current:
                operation, = current
                if published and (operation["state"] == "pending" or operation.get("retained_open_id")):
                    mirror = _find(session, entry["mirror_id"])
                    generation = mirror["published_generation_id"]
                    retained = [op for op in published if generation
                                and op["publication_receipt"].get("generation_id") == generation]
                    if len(retained) != 1 or operation.get("retained_open_id", retained[0]["id"]) != retained[0]["id"]:
                        _error("MIRROR_CONTROL_CONFLICT")
                    if operation["state"] == "pending":
                        reopen[entry["mirror_id"]] = operation
                    applied.append((entry, retained[0]))
                else:
                    (applied if operation["state"] == "applied" else pending).append((entry, operation))
        if has_publication or applied:
            if len(applied) != len(included) or not isinstance(store, SqlMirrorStore):
                _error("MIRROR_CONTROL_CONFLICT")
            stamp = dict(asdict(authority), capture_generation=state["capture_generation"])
            stamp["binding_id"] = stamp.pop("resource_binding_id")
            if (not assignment_fence or assignment_fence.get("authority") != stamp
                    or assignment_fence.get("operation_id") != allocation["command"]["operation_id"]):
                _error("MIRROR_CONTROL_CONFLICT")
            source = session.get(SourceRow, source_id, populate_existing=True)
            if (source is None or source.status != "active" or source.engine != "postgresql"
                    or not source.capture_credential_ciphertext
                    or source.capture_revision != authority.credential_revision
                    or state.get("applied_revision") != authority.control_revision):
                _error("MIRROR_CONTROL_CONFLICT")
            preparations = []
            for entry, operation in applied:
                mirror_id = entry["mirror_id"]
                preparations.append(_observe_applied_open(session, store, state, entry, operation, authority,
                                                          assignment_receipts.get(mirror_id), observe_committed))
                if mirror_id in reopen:
                    store.save_op(session, dict(reopen[mirror_id], state="applied", retained_open_id=operation["id"]))
            return [], preparations
        selected = []
        for entry, operation in pending:
            mirror_id, revision = entry["mirror_id"], entry["mirror_revision"]
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
        return selected, []


def _preparation_history_epoch(session, mirror_id, *, lock=False):
    gate = (session.get(HistoryGateRow, mirror_id, with_for_update=lock)
            if session is not None and not isinstance(session, MemoryMirrorStore) else None)
    if gate is not None and gate.status == "invalidating":
        _error("MIRROR_CONTROL_CONFLICT")
    return gate.history_epoch if gate else initial_history_epoch(mirror_id)


def require_current_open_allocations(session, *, authority: Authority, allocations):
    """Validate observed allocations under the caller's Source lock without acquiring the registry."""
    store = _storage()
    snapshot_mode = "window"
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
        if operation.get("replacement_generation_id") is not None:
            state = load_binding(session, authority.source_id)
            replacement = _replacement_open(session, state, opened)
            if replacement is None:
                _error("MIRROR_CONTROL_CONFLICT")
            submission, action = replacement
            if submission["operation_id"] != opened["operation_id"] or submission["generation_id"] != generation_id:
                _error("MIRROR_CONTROL_CONFLICT")
            if action == "run_now":
                if len(allocations) != 1:
                    _error("MIRROR_CONTROL_CONFLICT")
                snapshot_mode = "run_now"
    return snapshot_mode


def require_current_retained_opens(session, *, authority: Authority, published_scope, candidates):
    """Recheck all applied opens under the caller's Source lock before live delivery."""
    store = _storage()
    entries = {entry["mirror_id"]: entry for entry in published_scope if entry["included"]}
    mirror_ids = {candidate.mirror_id for candidate in candidates}
    if not isinstance(store, SqlMirrorStore) or not candidates or len(mirror_ids) != len(candidates) or mirror_ids != entries.keys():
        _error("MIRROR_CONTROL_CONFLICT")
    for candidate in sorted(candidates, key=lambda item: item.mirror_id):
        mirror_id = candidate.mirror_id
        operations = store.ops(session, mirror_id)
        opened = next((operation for operation in operations if operation["id"] == candidate.operation_id), None)
        mirror = session.get(MirrorRow, mirror_id, with_for_update=True, populate_existing=True)
        gate = session.get(HistoryGateRow, mirror_id, with_for_update=True, populate_existing=True)
        if not opened or mirror is None or gate is None:
            _error("MIRROR_CONTROL_CONFLICT")
        epoch = candidate.binding.history_epoch
        receipt = opened.get("publication_receipt") or {}
        revision = entries[mirror_id]["mirror_revision"]
        current = any(op["kind"] == "open" and op["state"] == "applied" and op["control_revision"] == revision
                      and (op["id"] == opened["id"] or op.get("retained_open_id") == opened["id"])
                      for op in operations)
        if (opened["kind"] != "open" or opened["state"] != "applied" or not current
                or receipt.get("authority") != asdict(authority)
                or receipt.get("generation_id") != candidate.generation_id
                or receipt.get("certificate_ref") != candidate.certificate_ref
                or receipt.get("history_epoch") != epoch or gate.history_epoch != epoch
                or gate.status != "available" or mirror.state["history_epoch"] != epoch
                or mirror.state["published_generation_id"] != candidate.generation_id):
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
    state = _require_open_binding(session, store, mirror, binding)
    if not isinstance(store, MemoryMirrorStore):
        gate = session.get(HistoryGateRow, mirror_id, with_for_update=True)
        if gate is not None and gate.history_epoch != binding.history_epoch:
            _error("MIRROR_CONTROL_CONFLICT")
    revision = mirror["control"]["control_revision"]
    operation = next((op for op in store.ops(session, mirror_id) if op["id"] == operation_id), None)
    if (operation is None or operation["kind"] != "open" or operation["state"] != "pending"
            or operation["control_revision"] != revision):
        _error("MIRROR_CONTROL_CONFLICT")
    replacement = _replacement_open(session, state, {"mirror_id": mirror_id})
    if replacement is not None:
        submission, _ = replacement
        if (submission["operation_id"] != operation_id or submission["history_epoch"] != binding.history_epoch
                or submission["generation_id"] != operation.get("replacement_generation_id")):
            _error("MIRROR_CONTROL_CONFLICT")
    elif operation.get("replacement_generation_id") is not None:
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
            generation_id = operation.get("replacement_generation_id") or uuid4().hex
            claim = dict(generation_id=generation_id, mirror_revision=revision, binding=binding_data, observed=False)
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


@dataclass(frozen=True)
class AppliedOpenPreparation:
    mirror_id: str
    operation_id: str
    binding: OpenGenerationBinding
    identity: OpenPublicationIdentity
    observed: CommittedOpenPublication


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


def _observe_applied_open(session, store, state, entry, operation, authority, fence_receipt, observe_committed):
    mirror_id = entry["mirror_id"]
    receipt = operation.get("publication_receipt")
    replacement = _replacement_open(session, state, entry)
    epoch = replacement[0]["history_epoch"] if replacement is not None else initial_history_epoch(mirror_id)
    if (not isinstance(receipt, dict) or receipt.get("authority") != asdict(authority)
            or receipt.get("history_epoch") != epoch
            or not isinstance(fence_receipt, str) or not fence_receipt):
        _error("MIRROR_CONTROL_CONFLICT")
    expected = OpenPublicationIdentity(**dict(receipt, authority=authority))
    if (not expected.generation_id or not expected.snapshot_operation_id or not expected.certificate_ref
            or type(expected.scan_offset) is not int or type(expected.completion_offset) is not int
            or not 0 <= expected.scan_offset < expected.completion_offset):
        _error("MIRROR_CONTROL_CONFLICT")
    binding = _open_publication_binding(operation, expected)
    mirror_row = session.get(MirrorRow, mirror_id, with_for_update=True, populate_existing=True)
    if mirror_row is None:
        _error("MIRROR_CONTROL_CONFLICT")
    mirror = mirror_row.state
    if (mirror["published_generation_id"] != expected.generation_id
            or mirror.get("capture_generation") != authority.capture_generation
            or mirror.get("history_epoch") != expected.history_epoch):
        _error("MIRROR_CONTROL_CONFLICT")
    _require_open_binding(session, store, mirror, binding)
    snapshot = _publication_snapshot(state, mirror_id, operation, binding, expected)
    gate = session.get(HistoryGateRow, mirror_id, with_for_update=True, populate_existing=True)
    if gate is None or gate.status != "available" or gate.history_epoch != expected.history_epoch:
        _error("MIRROR_CONTROL_CONFLICT")
    operation_id = operation["id"]
    with observe_committed(mirror_id=mirror_id, operation_id=operation_id, binding=binding, expected=expected) as observed:
        _validate_observed_publication(observed, mirror_id=mirror_id, operation_id=operation_id,
                                       binding=binding, expected=expected, snapshot=snapshot)
        bound = observed.history_bound
        if (observed.allocation.get("fence_receipt") != fence_receipt or not isinstance(bound, dict)
                or bound.get("mirror_id") != mirror_id or bound.get("source_id") != authority.source_id
                or bound.get("history_epoch") != expected.history_epoch):
            _error("MIRROR_CONTROL_CONFLICT")
        return AppliedOpenPreparation(mirror_id, operation_id, binding, expected, observed)


def replacement_publication_allocation(session, *, mirror, operation_id, authority, generation_id, epoch, certificate_ref):
    state = load_binding(session, mirror.source_id)
    if state is None:
        return None
    store = _storage()
    scope = read_published_scope(session, mirror.source_id)
    if (not _current_open_authority(state, authority, scope)
            or state.get("applied_revision") != authority.control_revision):
        _error("MIRROR_PUBLICATION_BLOCKED")
    replacement = _replacement_open(session, state, {"mirror_id": mirror.id})
    operation = next((op for op in store.ops(session, mirror.id) if op["id"] == operation_id), None)
    if (replacement is None or replacement[0]["operation_id"] != operation_id
            or replacement[0]["generation_id"] != generation_id or replacement[0]["history_epoch"] != epoch
            or operation is None or operation["state"] != "pending" or operation["kind"] != "open"
            or operation["control_revision"] != mirror.state["control"]["control_revision"]):
        _error("MIRROR_PUBLICATION_BLOCKED")
    snapshot = state.get("incremental_snapshots", {}).get("generations", {}).get(generation_id) or {}
    expected = OpenPublicationIdentity(authority, generation_id, epoch, snapshot.get("id"),
                                       snapshot.get("scan", {}).get("offset"),
                                       snapshot.get("completion", {}).get("offset"), certificate_ref)
    if (not expected.snapshot_operation_id or type(expected.scan_offset) is not int
            or type(expected.completion_offset) is not int or not 0 <= expected.scan_offset < expected.completion_offset):
        _error("MIRROR_PUBLICATION_BLOCKED")
    binding = _open_publication_binding(operation, expected)
    _require_open_binding(session, store, mirror.state, binding)
    snapshot_binding = _publication_snapshot(state, mirror.id, operation, binding, expected)
    return operation, binding, expected, snapshot_binding


def record_replacement_publication(session, *, allocation, observed):
    operation, binding, expected, snapshot = allocation
    _validate_observed_publication(observed, mirror_id=operation["mirror_id"], operation_id=operation["id"],
                                   binding=binding, expected=expected, snapshot=snapshot)
    _storage().save_op(session, dict(operation, state="applied", publication_receipt=asdict(expected)))


def reconcile_open_publication(
    *, mirror_id: str, operation_id: str, expected: OpenPublicationIdentity,
    observe_committed: ObserveCommittedOpenPublication,
) -> Literal["applied", "already_applied"]:
    """Project the first published generation or acknowledge its historical receipt."""
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


def record_mirror_stop_evidence(session, command, evidence):
    """Project an accepted Source stop onto its exact excluded Mirror revisions."""
    store = _storage()
    if session is None:
        with store.transaction() as memory_session:
            record_mirror_stop_evidence(memory_session, command, evidence)
        return
    for entry in command["published_scope"]:
        if entry["included"]:
            continue
        mirror = store.get(session, entry["mirror_id"])
        if (mirror is None or mirror["enabled"] or mirror["status"] != "disable_pending"
                or mirror["source_id"] != command["source_id"]
                or mirror["control"]["control_revision"] != entry["mirror_revision"]
                or any(mirror[key] != entry[key] for key in ("table_identity", "qualified_table"))):
            continue
        for operation in store.ops(session, mirror["id"]):
            if (operation["kind"] != "disable" or operation["state"] != "pending"
                    or operation["control_revision"] != entry["mirror_revision"]
                    or datetime.fromisoformat(operation["requested_at"]) > datetime.fromisoformat(command["requested_at"])):
                continue
            mirror["control"].update(
                credential_revision=command["credential_revision"],
                owner_epoch=command["owner_epoch"],
                runtime_instance_id=command["runtime_instance_id"],
                applied_revision=entry["mirror_revision"],
                observed_at=evidence["observed_at"],
                stop_ack=dict(operation_id=operation["id"], source_operation_id=command["operation_id"],
                              observed_at=evidence["observed_at"]),
            )
            mirror["status"] = "disabled"
            store.save(session, mirror)
            store.save_op(session, dict(operation, state="applied", observed_evidence_refs=[command["operation_id"]]))


def clear_mirror_stop_evidence(session, published_scope, source_operation_id):
    """Retire projections when the acknowledged Source authority is superseded."""
    store = _storage()
    if session is None:
        with store.transaction() as memory_session:
            clear_mirror_stop_evidence(memory_session, published_scope, source_operation_id)
        return
    for entry in published_scope:
        mirror = store.get(session, entry["mirror_id"])
        if mirror is None:
            continue
        acknowledgment = mirror["control"].get("stop_ack")
        if acknowledgment is None or acknowledgment["source_operation_id"] != source_operation_id:
            continue
        _clear_stop_control(mirror["control"])
        mirror["status"] = "disable_pending"
        store.save(session, mirror)
        for operation in store.ops(session, mirror["id"]):
            if operation["id"] == acknowledgment["operation_id"]:
                store.save_op(session, dict(operation, state="pending", observed_evidence_refs=[]))


def _clear_stop_control(control):
    control.update(credential_revision=None, owner_epoch=None, runtime_instance_id=None,
                   applied_revision=None, observed_at=None, stop_ack=None)


def _snapshot_progress(session, mirror, operations):
    revision = mirror["control"]["control_revision"]
    for op in operations:
        allocation = op.get("allocation")
        if (not mirror["enabled"] or op["kind"] != "open" or op["state"] != "pending" or op["control_revision"] != revision
                or not allocation or not allocation["observed"] or allocation["mirror_revision"] != revision):
            continue
        generation = allocation["generation_id"]
        bound = allocation["binding"]
        authority = Authority(**bound["authority"])
        scope = read_published_scope(session, mirror["source_id"])
        state = load_binding(None if isinstance(session, MemoryMirrorStore) else session, mirror["source_id"])
        if (not _current_open_authority(state, authority, scope) or state.get("applied_revision") != authority.control_revision
                or not any(entry["mirror_id"] == mirror["id"] and entry["included"] for entry in scope)
                or authority.source_id != mirror["source_id"] or bound["object_id"] != mirror["object_id"]
                or any(bound[k] != mirror[k] for k in ("table_identity", "qualified_table"))):
            continue
        ledger = state.get("incremental_snapshots", {})
        snapshot = ledger.get("generations", {}).get(generation, {})
        expected = dict(authority=bound["authority"], mirror_id=mirror["id"], mirror_revision=revision,
                        allocation_operation_id=op["id"], generation_id=generation, table_identity=mirror["table_identity"],
                        qualified_table=mirror["qualified_table"], history_epoch=bound["history_epoch"],
                        schema_fingerprint=bound["schema_fingerprint"], data_partition=bound["partition_identity"])
        if (snapshot.get("receipt") is not True or not snapshot.get("id") or not snapshot.get("scan")
                or any(snapshot.get("binding", {}).get(k) != v for k, v in expected.items())):
            continue
        if snapshot["state"] == "catching_up" and snapshot.get("completion"):
            stage, evidence = "catching_up", snapshot["completion"]
        elif snapshot["state"] == "snapshotting" and ledger.get("active") == generation:
            stage, evidence = "scan", snapshot["scan"]
        else:
            continue
        milliseconds = evidence.get("timestamp")
        observed_at = (datetime.fromtimestamp(milliseconds / 1000, UTC)
                       if type(milliseconds) is int and 0 <= milliseconds < 253402300800000 else None)
        return dict(stage=stage, generation_id=generation, notification_offset=evidence["offset"], observed_at=observed_at)
    return None


def _present(session, mirror):
    result = deepcopy(mirror)
    gate = None if isinstance(session, MemoryMirrorStore) else session.get(HistoryGateRow, mirror["id"])
    result["history_epoch"] = gate.history_epoch if gate is not None else None
    if gate is None or gate.status != "available" or gate.history_epoch != mirror.get("history_epoch"):
        result["retained_lower_bound"] = result["committed_upper_bound"] = None
    operations = _storage().ops(session, mirror["id"])
    result["progress"] = _snapshot_progress(session, mirror, operations)
    result["operations"] = sorted(
        ({key: op[key] for key in Operation.model_fields} for op in operations),
        key=lambda op: (op["requested_at"], op["id"]),
    )
    return result


def get_mirror(mirror_id):
    with _storage().transaction() as session:
        return _present(session, _find(session, mirror_id))


def list_mirrors(*, limit=100, offset=0, source_id=None, status=None, q=None):
    store = _storage()
    with store.transaction() as session:
        rows, total = store.page(session, source_id=source_id, status=status, q=q, limit=limit, offset=offset)
        return dict(items=[_present(session, row) for row in rows],
                    total=total, limit=limit, offset=offset)


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


def _change_enabled(session, mirror, enabled):
    mirror["enabled"] = enabled
    _clear_stop_control(mirror["control"])
    mirror["control"]["control_revision"] += 1
    mirror["status"] = "unknown" if enabled else "disable_pending"
    _storage().save(session, mirror)
    operation_id = _id()
    _operation(session, mirror, "open" if enabled else "disable", operation_id, operator_intent=True)
    return operation_id


def set_enabled(mirror_id, *, enabled, actor_user_id, actor_token_id=None):
    store = _storage()
    with store.transaction() as session:
        mirror = _lock_mirror_source(session, mirror_id)
        return _apply_enabled(session, mirror, enabled, actor_user_id, actor_token_id)


def _apply_enabled(session, mirror, enabled, actor_user_id, actor_token_id):
    store = _storage()
    mirror_id = mirror["id"]
    if mirror["enabled"] == enabled:
        kinds = {"open", "enable"} if enabled else {"disable"}
        current = [op for op in store.ops(session, mirror_id) if op["kind"] in kinds
                   and op["control_revision"] == mirror["control"]["control_revision"]
                   and (op.get("operator_intent") or op["state"] in {"pending", "applied"})]
        if not current:
            _error("MIRROR_CONTROL_CONFLICT")
        operation = max(current, key=lambda op: (bool(op.get("operator_intent")), op["requested_at"], op["id"]))
        return dict(mirror=_present(session, mirror), operation_id=operation["id"])
    operation_id = _change_enabled(session, mirror, enabled)
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
        mirror = _lock_mirror_source(session, mirror_id)
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
