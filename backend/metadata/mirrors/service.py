"""Transactional mirror intent and conservative Operations lifecycle.

Registry primitives and operator intent live here. Capture-runtime reconciliation is
``reconciliation``; the Operations projection is ``presentation``.
"""

from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.core.time import utc_now
from backend.metadata.mirrors import journal, lifecycle, presentation
from backend.metadata.mirrors.deletion import deletion_proof, retire_replacement
from backend.metadata.mirrors.errors import MirrorError, reject
from backend.metadata.mirrors.lifecycle import current_open
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.store import MemoryMirrorStore, SqlMirrorStore, catalog_binding

__all__ = [
    "catalog_mirror",
    "list_catalog_mirror_tables",
    "enable_for_object",
    "set_enabled_for_object",
    "bind_management",
    "storage",
    "find_mirror",
    "lock_mirror_source",
    "add_operation",
    "new_operation_id",
    "clear_stop_control",
    "read_published_scope",
    "read_dispatch_scope",
    "get_mirror",
    "get_mirror_detail",
    "set_enabled",
    "delete_mirror",
    "delete_mirror_for_object",
    "resume_pending_deletions",
    "TargetLifecycle",
]


class TargetLifecycle(Protocol):
    def seal(self, mirror_id: str, operation_id: str, proof: dict) -> None:
        """Durably retire the identity and close all generations to new pins and writes."""
        ...

    def purge(self, mirror_id: str, operation_id: str, proof: dict) -> None:
        """Drop the sealed copies and preserve the retirement receipt."""
        ...


_store = None
_target = None


def catalog_mirror(object_id, *, source_id, can_read, can_write):
    """Show the saved setting and authorized actions for this Catalog object."""
    if not (can_read or can_write):
        return None
    store = storage()
    with store.transaction() as session:
        binding = store.preview_binding(session, object_id)
        mirror = store.get_by_object(session, source_id, object_id)
        return _catalog_setting(binding, mirror, can_read=can_read, can_write=can_write)


def list_catalog_mirror_tables(*, visible_ids, object_id, q, can_read, can_write, limit, offset):
    store = storage()
    with store.transaction() as session:
        rows, total = store.catalog_tables(
            session, visible_ids=visible_ids, object_id=object_id, q=q,
            include_bound=can_read or can_write, limit=limit, offset=offset,
        )
        published = {mirror["id"] for _, _, mirror in rows
                     if can_read and mirror and mirror["enabled"] and mirror.get("published_generation_id")}
        pending_opens = store.pending_opens(session, published) if published else {}
        contexts = {}
        items = []
        for obj, source, mirror in rows:
            qualified_table = f"{obj.schema_name}.{obj.name}"
            setting = None
            if can_read or can_write:
                binding = catalog_binding(obj, source)
                setting = _catalog_setting(binding, mirror, can_read=can_read, can_write=can_write)
            holder = None
            publication_wait = None
            if can_read and (not mirror or not mirror.get("published_generation_id")
                             or current_open(mirror, pending_opens.get(mirror["id"], ()))):
                if source.id not in contexts:
                    contexts[source.id] = presentation.source_lifecycle(store, session, source.id)
                context = contexts[source.id]
                slot = context.slot
                if slot and (mirror is None or slot["mirror_id"] != mirror["id"]):
                    holder = dict(mirror_id=slot["mirror_id"], qualified_table=slot["qualified_table"])
                if mirror is None or (mirror["enabled"] and mirror["id"] not in context.included):
                    publication_wait = context.publication_wait
            items.append(dict(object_id=obj.id, source_id=source.id, source_name=source.name,
                              source_key=source.key, qualified_table=qualified_table,
                              source_size_bytes=obj.source_size_bytes, estimated_rows=obj.estimated_rows,
                              storage_destination="source_mirror", mirror=setting, snapshot_holder=holder, publication_wait=publication_wait))
        return dict(items=items, total=total, limit=limit, offset=offset)


def _delete_token(mirror):
    return uuid5(NAMESPACE_URL, f"delete:{mirror['id']}:{mirror['control']['control_revision']}").hex


def _catalog_setting(binding, mirror, *, can_read, can_write):
    if binding is None and mirror is None:
        return None
    enabled = bool(mirror and mirror["enabled"])
    return dict(
        enabled=enabled,
        can_enable=can_write and not enabled and not (mirror or {}).get("deletion_operation_id") and not (mirror or {}).get("deletion_reservation") and _eligible_binding(binding, mirror),
        can_disable=can_write and enabled,
        mirror_id=mirror["id"] if mirror and can_read else None,
        **({"delete_token": _delete_token(mirror)} if mirror and not enabled and can_write else {}),
        **({"deletion_pending": True} if mirror and mirror.get("deletion_operation_id") else {}),
    )


def bind_management(*, store=None, target=None):
    global _store, _target
    _store = store
    _target = target


def storage():
    global _store
    if _store is None:
        _store = (
            MemoryMirrorStore()
            if get_settings().store_backend == "memory"
            else SqlMirrorStore()
        )
    return _store


def new_operation_id():
    return "mop_" + uuid4().hex


def find_mirror(session, mirror_id):
    mirror = storage().get(session, mirror_id)
    if mirror is None:
        reject("MIRROR_NOT_FOUND", 404)
    return mirror


def lock_mirror_source(session, mirror_id):
    store = storage()
    store.lock_registry(session)
    mirror = find_mirror(session, mirror_id)
    store.lock_sources(session, {mirror["source_id"]})
    return find_mirror(session, mirror_id)


def read_published_scope(session, source_id):
    """Read committed mirrors under the caller's Source lock, without locking the registry."""
    return storage().published_scope(session, source_id)


def read_dispatch_scope(session, source_id, *, state):
    return lifecycle.read_dispatch_scope(storage(), session, source_id, state=state)


def _new(binding):
    return dict(
        binding,
        id="mir_" + uuid4().hex,
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


def add_operation(session, mirror, kind, operation_id, **extra):
    store = storage()
    requested_at = utc_now().isoformat()
    for previous in store.ops(session, mirror["id"]):
        if (
            previous["state"] == "pending"
            and previous["control_revision"] < mirror["control"]["control_revision"]
        ):
            previous["state"] = "superseded"
            journal.result(previous, "superseded", requested_at, operation_id)
            store.save_op(session, previous)
    op = dict(
        id=operation_id,
        mirror_id=mirror["id"],
        kind=kind,
        state="pending",
        control_revision=mirror["control"]["control_revision"],
        observed_evidence_refs=[],
        fault_code=None,
        requested_at=requested_at,
        requested_epoch=mirror.get("history_epoch"),
        requested_generation=mirror.get("published_generation_id"),
        **extra,
    )
    store.save_op(session, op)
    return op


def enable_for_object(object_id, *, actor_user_id, actor_token_id=None, can_read=True):
    """Retain the full management response of the original enable endpoint."""
    store = storage()
    with store.transaction() as session:
        store.lock_registry(session)
        binding = store.binding(session, object_id)
        if binding is None:
            reject("MIRROR_NOT_FOUND", 404)
        mirror = store.get_by_object(session, binding["source_id"], binding["object_id"])
        mirror, operation_id = _set_object_intent(session, binding, mirror, True, actor_user_id, actor_token_id)
        if not can_read:
            return dict(enabled=mirror["enabled"], operation_id=operation_id)
        context = presentation.source_lifecycle(store, session, mirror["source_id"])
        return dict(mirror=presentation.present(store, session, mirror, context), operation_id=operation_id)


def set_enabled_for_object(object_id, *, source_id, enabled, can_read, actor_user_id, actor_token_id=None):
    store = storage()
    with store.transaction() as session:
        store.lock_registry(session)
        store.lock_sources(session, {source_id})
        binding = store.binding(session, object_id)
        if binding is not None and binding["source_id"] != source_id:
            reject("MIRROR_NOT_FOUND", 404)
        mirror = store.get_by_object(session, source_id, object_id)
        mirror, operation_id = _set_object_intent(session, binding, mirror, enabled, actor_user_id, actor_token_id)
        return dict(mirror=_catalog_setting(binding, mirror, can_read=can_read, can_write=True), operation_id=operation_id)


def _require_enable_binding(binding, mirror):
    if binding is None:
        reject("MIRROR_NOT_FOUND", 404)
    if not _eligible_binding(binding, mirror):
        reject("MIRROR_CONTROL_CONFLICT")


def _eligible_binding(binding, mirror):
    return binding is not None and (mirror is None or all(
        mirror[key] == binding[key] for key in ("source_id", "object_id", "qualified_table", "table_identity")
    ))


def _set_object_intent(session, binding, mirror, enabled, actor_user_id, actor_token_id):
    if enabled:
        _require_enable_binding(binding, mirror)
    if mirror is not None:
        return mirror, _apply_enabled(session, mirror, enabled, actor_user_id, actor_token_id)
    if binding is None:
        reject("MIRROR_NOT_FOUND", 404)
    if enabled:
        mirror = _new(binding)
        storage().save(session, mirror)
        operation_id = new_operation_id()
        add_operation(session, mirror, "open", operation_id, operator_intent=True)
        _audit(session, mirror, "enable", operation_id, actor_user_id, actor_token_id, enabled=True)
        return mirror, operation_id
    return None, None


def get_mirror(mirror_id):
    store = storage()
    with store.transaction() as session:
        mirror = find_mirror(session, mirror_id)
        return presentation.present(store, session, mirror, presentation.source_lifecycle(store, session, mirror["source_id"]))


def get_mirror_journal(mirror_id, *, before=None, limit=20):
    store = storage()
    with store.transaction() as session:
        mirror = find_mirror(session, mirror_id)
        context = presentation.source_lifecycle(store, session, mirror["source_id"])
        events = journal.timeline(store.ops(session, mirror_id), context.state.get("incremental_snapshots", {}), mirror)
        return journal.page(events, before, limit)


def get_mirror_detail(mirror_id):
    store = storage()
    with store.transaction() as session:
        mirror = find_mirror(session, mirror_id)
        binding = store.preview_binding(session, mirror["object_id"])
        obj = store.catalog_object(session, mirror["object_id"])
        context = presentation.source_lifecycle(store, session, mirror["source_id"])
        detail = presentation.present(store, session, mirror, context)
        operations = store.ops(session, mirror_id)
        events = journal.timeline(operations, context.state.get("incremental_snapshots", {}), mirror)
        latest_request = next((event for event in events if event["category"] == "request"), None)
        observation = next((event for event in events if event["category"] == "observation"), None)
        continuity = next((event for event in events if event["kind"].startswith("continuity_")), None)
        publication = next((event for event in events if event["kind"] == "published" and
                            event["generation_id"] == mirror["published_generation_id"]), None)
        opened = current_open(mirror, operations)
        allocated = opened.get("allocation") if opened and opened["state"] == "pending" else None
        blocker = mirror.get("blocker") if mirror["enabled"] else None
        open_request = next((event for event in events if event["category"] == "request" and event["kind"] in {"open", "resume"}
                             and event["control_revision"] == mirror["control"]["control_revision"]), None)
        detail.update(journal=journal.page(events, None, 3), latest_request=latest_request, open_request=open_request,
                      latest_observation=observation, continuity_check=continuity, blocker=blocker,
                      allocated_generation_id=allocated["generation_id"] if allocated else None,
                      published_at=publication["at"] if publication else None,
                      can_retry=bool(blocker and detail["history_epoch"] is not None and not any(
                          op["kind"] == "retry" and op["state"] == "pending" for op in operations)))
        detail.update(storage_destination="source_mirror", source_size_bytes=obj.source_size_bytes if obj else None,
                      estimated_rows=obj.estimated_rows if obj else None)
        return dict(mirror=detail, can_enable=not mirror["enabled"] and not mirror.get("deletion_operation_id") and not mirror.get("deletion_reservation") and _eligible_binding(binding, mirror))


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
        session=storage().database(session),
    )


def _change_enabled(session, mirror, enabled):
    if mirror["control"].get("stop_ack"):
        store = storage()
        for operation in store.ops(session, mirror["id"]):
            if journal.project_stop_receipt(mirror, operation):
                store.save_op(session, operation)
    mirror["enabled"] = enabled
    clear_stop_control(mirror["control"])
    mirror["control"]["control_revision"] += 1
    mirror["status"] = "unknown" if enabled else "disable_pending"
    storage().save(session, mirror)
    operation_id = new_operation_id()
    extra = {}
    if enabled:
        pointer = mirror["published_generation_id"]
        prior = sorted(storage().ops(session, mirror["id"]), key=lambda op: op["control_revision"], reverse=True)
        for op in prior:
            if op["kind"] != "open" or op["state"] != "superseded":
                continue
            baseline, allocated = op.get("reopen_baseline", {}), op.get("allocation", {})
            if baseline and baseline.get("previous_generation_id") == pointer:
                partition = baseline["partition_identity"]
            elif not pointer and allocated:
                partition = allocated["binding"]["partition_identity"]
            else:
                continue
            extra["interrupted_partition"] = partition
            break
    add_operation(session, mirror, "open" if enabled else "disable", operation_id, operator_intent=True, **extra)
    return operation_id


def request_recheck(mirror_id, *, expected_epoch, expected_revision, actor_user_id, actor_token_id=None, reason=None):
    store = storage()
    with store.transaction() as session:
        mirror = lock_mirror_source(session, mirror_id)
        epoch = store.available_history_epoch(session, mirror, lock=True)
        revision = mirror["control"]["control_revision"]
        if (not mirror["enabled"] or not mirror.get("blocker") or not mirror["published_generation_id"]
                or epoch is None or str(epoch) != str(expected_epoch)
                or (expected_revision is not None and expected_revision != revision)):
            reject("MIRROR_CONTROL_CONFLICT")
        current = journal.recheck_request(store.ops(session, mirror_id), mirror)
        if current and current["kind"] == "retry" and current["state"] == "pending":
            return dict(operation_id=current["id"], state="pending")
        op = add_operation(session, mirror, "retry", new_operation_id(), operator_intent=True)
        _audit(session, mirror, "recovery_request", op["id"], actor_user_id, actor_token_id,
               action="retry", expected_history_epoch=str(epoch), reason=reason)
        return dict(operation_id=op["id"], state="pending")


def set_enabled(mirror_id, *, enabled, actor_user_id, actor_token_id=None, can_read=True):
    store = storage()
    with store.transaction() as session:
        mirror = lock_mirror_source(session, mirror_id)
        if enabled and not mirror["enabled"]:
            _require_enable_binding(store.binding(session, mirror["object_id"]), mirror)
        operation_id = _apply_enabled(session, mirror, enabled, actor_user_id, actor_token_id)
        if not can_read:
            return dict(enabled=mirror["enabled"], operation_id=operation_id)
        context = presentation.source_lifecycle(store, session, mirror["source_id"])
        return dict(mirror=presentation.present(store, session, mirror, context), operation_id=operation_id)


def _apply_enabled(session, mirror, enabled, actor_user_id, actor_token_id):
    if mirror.get("deletion_operation_id") or mirror.get("deletion_reservation"):
        reject("MIRROR_CONTROL_CONFLICT")
    store = storage()
    mirror_id = mirror["id"]
    if mirror["enabled"] == enabled:
        kinds = {"open", "enable"} if enabled else {"disable"}
        current = [op for op in store.ops(session, mirror_id) if op["kind"] in kinds
                   and op["control_revision"] == mirror["control"]["control_revision"]
                   and (op.get("operator_intent") or op["state"] in {"pending", "applied"})]
        if not current:
            reject("MIRROR_CONTROL_CONFLICT")
        operation = max(current, key=lambda op: (bool(op.get("operator_intent")), op["requested_at"], op["id"]))
        return operation["id"]
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
    return operation_id


def delete_mirror_for_object(object_id, *, source_id, delete_token, actor_user_id, actor_token_id=None):
    store = storage()
    with store.transaction() as session:
        store.lock_registry(session)
        store.lock_sources(session, {source_id})
        mirror = store.get_by_object(session, source_id, object_id)
        if mirror is None or _delete_token(mirror) != delete_token:
            reject("MIRROR_CONTROL_CONFLICT")
        revision = mirror["control"]["control_revision"]
    return delete_mirror(mirror["id"], expected_control_revision=revision,
                         actor_user_id=actor_user_id, actor_token_id=actor_token_id)


def delete_mirror(mirror_id, *, actor_user_id, actor_token_id=None, expected_control_revision=None):
    store = storage()
    # Commit the request identity before sealing. Recovery can inspect the same
    # target receipt even if either database lost its transaction reply.
    with store.transaction() as session:
        mirror = lock_mirror_source(session, mirror_id)
        if expected_control_revision is not None and mirror["control"]["control_revision"] != expected_control_revision:
            reject("MIRROR_CONTROL_CONFLICT")
        if mirror["enabled"]:
            reject("MIRROR_IN_USE")
        accepted = mirror.get("deletion_operation_id")
        reservation = mirror.get("deletion_reservation")
        if not accepted and not reservation:
            proof = deletion_proof(store.database(session), mirror, store.ops(session, mirror_id))
            if proof is None:
                _audit(session, mirror, "delete", new_operation_id(), actor_user_id, actor_token_id)
                store.delete(session, mirror_id)
                return None
            if _target is None:
                reject("MIRROR_READ_UNAVAILABLE", 503)
            gate = store.history_gate(session, mirror_id, lock=True)
            if gate is not None and gate.status != "available":
                reject("MIRROR_HISTORY_INVALID")
            reservation = dict(id=new_operation_id(), proof=proof, actor_user_id=actor_user_id, actor_token_id=actor_token_id)
            store.save(session, dict(mirror, deletion_reservation=reservation))

    try:
        rejection = None
        with store.transaction() as session:
            store.lock_registry(session)
            store.lock_sources(session, {mirror["source_id"]})
            current = store.get(session, mirror_id)
            if current is None:
                return None
            accepted = current.get("deletion_operation_id")
            if accepted:
                command = next(op for op in store.ops(session, mirror_id) if op["id"] == accepted)
                proof = command["purge_proof"]
            elif not reservation or current.get("deletion_reservation") != reservation:
                reject("MIRROR_CONTROL_CONFLICT")
            else:
                if _target is None:
                    reject("MIRROR_READ_UNAVAILABLE", 503)
                gate = store.history_gate(session, mirror_id, lock=True)
                proof = reservation["proof"]
                try:
                    _target.seal(mirror_id, reservation["id"], proof)
                except MirrorError as exc:
                    if exc.code not in {"MIRROR_READERS_IN_USE", "MIRROR_STOP_UNCONFIRMED"}:
                        raise
                    rejection = exc
                current.pop("deletion_reservation")
                if rejection is None:
                    if gate is not None:
                        gate.history_epoch = uuid4().hex
                        gate.lower_commit_seq = gate.lower_entry_seq = 0
                        gate.status = "invalidating"
                    current["deletion_operation_id"] = reservation["id"]
                    add_operation(session, current, "delete", reservation["id"], purge_proof=proof,
                               actor_user_id=reservation["actor_user_id"], actor_token_id=reservation["actor_token_id"])
                store.save(session, current)
        if rejection:
            raise rejection
        accepted = current["deletion_operation_id"]
        if _target is None:
            reject("MIRROR_READ_UNAVAILABLE", 503)
        _target.purge(mirror_id, accepted, proof)

        with store.transaction() as session:
            store.lock_registry(session)
            store.lock_sources(session, {mirror["source_id"]})
            current = store.get(session, mirror_id)
            if current is not None:
                if current.get("deletion_operation_id") != accepted:
                    reject("MIRROR_CONTROL_CONFLICT")
                operation = next(op for op in store.ops(session, mirror_id) if op["id"] == accepted)
                retire_replacement(store.database(session), current)
                _audit(session, current, "delete", accepted, operation["actor_user_id"], operation["actor_token_id"])
                store.delete(session, mirror_id)
        return None
    except DBAPIError:
        if accepted:
            return dict(operation_id=accepted, state="pending")
        raise
    except AppError as exc:
        if accepted and exc.http_status in (409, 503):
            return dict(operation_id=accepted, state="pending")
        raise


def resume_pending_deletions():
    store = storage()
    if _target is None or not isinstance(store, SqlMirrorStore):
        return
    with store.transaction() as session:
        pending = session.scalars(select(MirrorRow.id).where(
            (MirrorRow.state["deletion_operation_id"].as_string().is_not(None)
             | MirrorRow.state["deletion_reservation"]["id"].as_string().is_not(None)))).all()
    for mirror_id in pending:
        try:
            delete_mirror(mirror_id, actor_user_id=None)
        except MirrorError as exc:
            if exc.code not in {"MIRROR_NOT_FOUND", "MIRROR_READERS_IN_USE", "MIRROR_STOP_UNCONFIRMED", "MIRROR_CONTROL_CONFLICT"}:
                raise


def clear_stop_control(control):
    control.update(credential_revision=None, owner_epoch=None, runtime_instance_id=None,
                   applied_revision=None, observed_at=None, stop_ack=None)
