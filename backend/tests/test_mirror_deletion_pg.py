"""Purge a stopped, pinned Mirror on real PostgreSQL and retry its management commit."""

from dataclasses import asdict, replace
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import create_engine
import pytest

from backend.core.time import utc_now
from backend.metadata.capture.control import replacement_blocks_lifecycle
from backend.metadata.capture.store import load_binding, save_binding, save_operation
from backend.metadata.mirrors import service
from backend.metadata.mirrors.bootstrap import create_generation, prepare_authority
from backend.metadata.mirrors.deletion import TargetDeletion
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.tests.test_mirror_generation_allocation import opened as opened, target_dsn as target_dsn, target_request


@pytest.mark.integration
def test_reader_protects_copy_then_purge_recovers_after_management_failure(opened, target_dsn, monkeypatch):
    store, mid, opened_id, authority = opened
    generation, sibling_generation = uuid4().hex, uuid4().hex
    sibling_id = "mir_" + uuid4().hex
    request = dict(target_request(authority), mirror_id=mid, generation_id=generation, operation_id=opened_id)
    app = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(
        target_dsn, options="-c role=refraq_mirror_applier"))
    monkeypatch.setattr(service, "_target", TargetDeletion(app))
    try:
        with psycopg.connect(target_dsn, autocommit=True) as admin:
            create_generation(admin, **request)
            create_generation(admin, **dict(request, mirror_id=sibling_id, table_identity="lines",
                                           generation_id=sibling_generation, operation_id=uuid4().hex))
            for mirror, gid in ((mid, generation), (sibling_id, sibling_generation)):
                table = admin.execute("UPDATE source_mirror_state.generations SET status='published' "
                                      "WHERE id=%s RETURNING table_name", (gid,)).fetchone()[0]
                admin.execute("UPDATE source_mirror_state.mirrors SET published_generation_id=%s WHERE id=%s", (gid, mirror))
                admin.execute(sql.SQL("INSERT INTO {}(tenant,id,amount) VALUES ('test',1,7.50)")
                              .format(sql.Identifier("source_mirror", table)))
            table = admin.execute("SELECT table_name FROM source_mirror_state.generations WHERE id=%s", (generation,)).fetchone()[0]
            admin.execute("INSERT INTO source_mirror_state.live_log(mirror_id,history_epoch,commit_seq,entry_seq,"
                          "generation_id,capture_generation,origin,operation,typed_key,after_image) "
                          "VALUES(%s,'epoch',1,1,%s,'1','live','upsert','{}','{}')", (mid, generation))
            pin = uuid4().hex
            admin.execute("SELECT source_mirror_state.acquire_pin(%s,%s)", (pin, mid))
            with store.transaction() as session:
                store.save(session, dict(store.get(session, mid), published_generation_id=generation, history_epoch="epoch"))
                session.add(HistoryGateRow(mirror_id=mid, history_epoch="epoch", lower_commit_seq=0,
                                           lower_entry_seq=0, status="available"))
                session.add(RecoveryRow(mirror_id=mid, source_id=authority.source_id, identity=uuid4().hex,
                                        operation_id=uuid4().hex, journal={"state": "applied"}))
            service.set_enabled(mid, enabled=False, actor_user_id="operator")
            source_operation = uuid4().hex
            stopped = replace(authority, control_revision=authority.control_revision + 1)
            prepare_authority(admin, mirror_id=mid, table_identity="orders", operation_id=source_operation,
                              history_epoch="epoch", expected_authority=authority, authority=stopped,
                              exclusion_proof=True, verify_exclusion=lambda *args: True)
            with store.transaction() as session:
                scope = service.read_published_scope(session, authority.source_id)
                state = load_binding(session, authority.source_id)
                # The last Source owner was installed to build this Mirror's replacement.
                state["allocation"] = {"command": dict(kind="replace_owner", operation_id=uuid4().hex,
                    replacement={"scope": {"submission": {"mirror_id": mid}}})}
                state.update(desired="stopped", control_revision=stopped.control_revision, applied_revision=stopped.control_revision,
                             published_scope=scope)
                save_binding(session, state)
                command = dict(asdict(stopped), kind="stop", capture_generation=1, operation_id=source_operation,
                               requested_at=utc_now().isoformat(), published_scope=scope)
                command["binding_id"] = command.pop("resource_binding_id")
                evidence = dict(observed_at=utc_now().isoformat())
                save_operation(session, command, evidence)
                service.record_mirror_stop_evidence(session, command, evidence)
            with pytest.raises(service.MirrorError, match="MIRROR_READERS_IN_USE"):
                service.delete_mirror(mid, actor_user_id="operator")
            assert admin.execute("SELECT to_regclass(%s) IS NOT NULL", ("source_mirror." + table,)).fetchone() == (True,)
            with store.transaction() as session:
                assert session.get(HistoryGateRow, mid).status == "available"
            admin.execute("SELECT source_mirror_state.release_run_pins(%s)", (pin,))
            # A failed reservation commit leaves target readers unaffected.
            with monkeypatch.context() as interrupted:
                persist = store.save
                def fail_reservation(session, state):
                    if state.get("deletion_reservation"):
                        raise service.MirrorError("MIRROR_READ_UNAVAILABLE", 503)
                    persist(session, state)
                interrupted.setattr(store, "save", fail_reservation)
                with pytest.raises(service.MirrorError, match="MIRROR_READ_UNAVAILABLE"):
                    service.delete_mirror(mid, actor_user_id="operator")
            assert admin.execute("SELECT (source_mirror_state.acquire_pin(%s,%s))->>'generation_id'",
                                 (pin, mid)).fetchone() == (generation,)
            admin.execute("SELECT source_mirror_state.release_run_pins(%s)", (pin,))
            # Lose the Management acceptance after the target sealed. The committed
            # reservation recovers the original target operation on retry.
            with monkeypatch.context() as interrupted:
                def fail_acceptance(session, state):
                    if state.get("deletion_operation_id"):
                        raise service.MirrorError("MIRROR_READ_UNAVAILABLE", 503)
                    persist(session, state)
                interrupted.setattr(store, "save", fail_acceptance)
                with pytest.raises(service.MirrorError, match="MIRROR_READ_UNAVAILABLE"):
                    service.delete_mirror(mid, actor_user_id="operator")
            with pytest.raises(psycopg.Error, match="MIRROR_READ_UNAVAILABLE"):
                admin.execute("SELECT source_mirror_state.acquire_pin(%s,%s)", (pin, mid))
            # A failed target purge keeps the copy closed to new readers and writers.
            with monkeypatch.context() as interrupted:
                def lose_purge_reply(*args):
                    raise service.MirrorError("MIRROR_READ_UNAVAILABLE", 503)
                interrupted.setattr(service._target, "purge", lose_purge_reply)
                accepted = service.delete_mirror(mid, actor_user_id="operator")
                assert accepted["state"] == "pending"
                with pytest.raises(psycopg.Error, match="MIRROR_READ_UNAVAILABLE"):
                    admin.execute("SELECT source_mirror_state.acquire_pin(%s,%s)", (pin, mid))
                fresh_allocation = dict(request, generation_id=uuid4().hex, operation_id=uuid4().hex,
                                        authority=stopped, require_prepared_fence=True)
                with pytest.raises(psycopg.Error, match="MIRROR_CONTROL_CONFLICT"):
                    create_generation(admin, **fresh_allocation)
                assert admin.execute("SELECT cleanup_pending AND write_closed FROM source_mirror_state.generations "
                                     "WHERE id=%s", (generation,)).fetchone() == (True,)
            with monkeypatch.context() as interrupted:
                def lose_management_reply(*args):
                    raise service.MirrorError("MIRROR_READ_UNAVAILABLE", 503)
                interrupted.setattr(store, "delete", lose_management_reply)
                accepted = service.delete_mirror(mid, actor_user_id="operator")
                assert accepted["state"] == "pending"
                assert service.get_mirror(mid)["deletion_operation_id"] == accepted["operation_id"]
                with store.transaction() as session:
                    gate = session.get(HistoryGateRow, mid)
                    assert gate.status == "invalidating" and gate.history_epoch != "epoch"
                with pytest.raises(service.MirrorError, match="MIRROR_CONTROL_CONFLICT"):
                    service.set_enabled(mid, enabled=True, actor_user_id="operator")
            assert admin.execute("SELECT to_regclass(%s)", ("source_mirror." + table,)).fetchone() == (None,)
            assert admin.execute("SELECT count(*) FROM source_mirror_state.live_log WHERE mirror_id=%s", (mid,)).fetchone() == (0,)
            assert admin.execute("SELECT (source_mirror_state.acquire_pin(%s,%s))->>'generation_id'",
                                 (pin, sibling_id)).fetchone() == (sibling_generation,)
            sibling_page = admin.execute("SELECT source_mirror_state.read_page(%s,%s,NULL,1)",
                                         (pin, sibling_id)).fetchone()[0]
            assert sibling_page["rows"][0]["tenant"] == "test"
            with pytest.raises(psycopg.Error, match="MIRROR_CONTROL_CONFLICT"):
                create_generation(admin, **request)
            records = []
            monkeypatch.setattr(service, "persist_audit_event", lambda **event: records.append(event))
            service.resume_pending_deletions()
            assert [r["action"] for r in records] == ["mirror.delete"]
            assert records[0]["actor_user_id"] == "operator"
            with pytest.raises(service.MirrorError, match="MIRROR_NOT_FOUND"):
                service.get_mirror(mid)
            with store.transaction() as session:
                assert session.get(HistoryGateRow, mid) is None
                binding = load_binding(session, authority.source_id)
                assert binding["binding_id"] == authority.resource_binding_id
                assert not replacement_blocks_lifecycle(session, binding)
            assert service.enable_for_object("orders", actor_user_id="operator")["mirror"]["id"] != mid
    finally:
        app.dispose()
