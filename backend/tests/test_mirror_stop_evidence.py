"""Current runtime stop evidence through Source capture and Mirror management."""

from dataclasses import replace

import pytest

from backend.core.time import utc_now
from backend.metadata.capture import control
from backend.metadata.capture.scope import AUTHORITY_KEYS
from backend.metadata.capture.test_published_scope import (
    SOURCE,
    management as management,
    pending_capture_commands,
)
from backend.metadata.errors import SourceCaptureControlConflict
from backend.metadata.mirrors import service
from backend.metadata.mirrors.schemas import MirrorResponse
from backend.metadata.sources.store import get_source_store
from backend.tests.mirror_inventory import inventory
from backend.tests.test_capture_preparation import management_engine as management_engine
from backend.tests.test_mirror_generation_allocation import target_dsn as target_dsn

pytestmark = pytest.mark.integration


def _next_command():
    control.reconcile_published_scope(SOURCE)
    command, = pending_capture_commands()
    return command


def _accept(command, **changes):
    # record_applied_evidence is called after the protected runtime verifies signed observations.
    refs = {"target_fence", "owner_exclusion"}
    if command["kind"] == "stop":
        refs |= {"retired_commands_rejected", "task_stopped", "source_session_stopped", "inflight_drained"}
    else:
        refs |= {"credential_installed", "credential_revoked"}
    evidence = {
        **{key: command[key] for key in AUTHORITY_KEYS},
        **{f"{key}_ref": f"fixture:{key}" for key in refs},
        "operation_id": command["operation_id"],
        "observed_at": utc_now().isoformat(),
        **changes,
    }
    return control.record_applied_evidence(source_id=SOURCE, operation_id=command["operation_id"], evidence=evidence)


def _assign_runtime(transaction):
    with transaction() as session:
        state = control.load_binding(session, SOURCE)
        state.update(owner_epoch=1, runtime_instance_id="assigned-runtime")
        control.save_binding(session, state)


def test_confirmed_stop_tracks_the_current_disable_and_preserves_publication(management):
    transaction, _ = management
    mirror_id = service.enable_for_object("orders", actor_user_id="operator")["mirror"]["id"]
    with transaction() as session:
        store = service.storage()
        store.save(session, dict(store.get(session, mirror_id), published_generation_id="published-orders"))
    _assign_runtime(transaction)
    _next_command()

    pending = service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
    assert pending["mirror"]["status"] == "disable_pending"
    assert inventory(status="disabled")["total"] == 0
    stop = _next_command()
    with pytest.raises(SourceCaptureControlConflict):
        _accept(stop, runtime_instance_id="another-runtime")
    assert service.get_mirror(mirror_id)["control"]["stop_ack"] is None

    observed = _accept(stop)
    mirror = MirrorResponse(mirror=service.get_mirror(mirror_id)).mirror
    assert mirror.status == "disabled"
    assert mirror.published_generation_id == "published-orders"
    assert mirror.control.stop_ack.operation_id == pending["operation_id"]
    assert mirror.control.stop_ack.source_operation_id == stop["operation_id"]
    assert next(op for op in mirror.operations if op.id == pending["operation_id"]).state == "applied"
    assert inventory(status="disable_pending")["total"] == 0
    page = inventory(status="disabled")
    assert page["total"] == 1 and page["items"][0]["id"] == mirror_id
    assert service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")["operation_id"] == pending["operation_id"]
    assert control.record_applied_evidence(
        source_id=SOURCE, operation_id=stop["operation_id"], evidence=observed,
    ) == observed

    with control.source_control_transaction(SOURCE) as (session, source):
        updated = replace(source, capture_revision=source.capture_revision + 1)
        get_source_store().save_source_on(session, updated)
        control.record_source_intent(session, source, updated, actor_user_id="operator", actor_token_id=None)
    with pytest.raises(SourceCaptureControlConflict):
        _accept(stop)
    assert inventory(status="disabled")["total"] == 0
    assert inventory(status="disable_pending")["total"] == 1
    assert service.get_mirror(mirror_id)["control"]["stop_ack"] is None


def test_reconcile_of_other_mirrors_does_not_confirm_per_table_stop(management):
    transaction, _ = management
    mirror_id = service.enable_for_object("orders", actor_user_id="operator")["mirror"]["id"]
    service.enable_for_object("items", actor_user_id="operator")
    _assign_runtime(transaction)
    _next_command()
    service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")

    command = _next_command()
    assert command["kind"] == "reconcile"
    assert [entry["qualified_table"] for entry in command["published_scope"] if entry["included"]] == ["public.items"]
    _accept(command)
    assert service.get_mirror(mirror_id)["control"]["stop_ack"] is None
    assert inventory(status="disabled")["total"] == 0
    assert inventory(status="disable_pending")["total"] == 1

    excluded, = [entry for entry in command["published_scope"] if not entry["included"]]
    refs = dict(connector_excluded_ref="sha256:" + "1" * 64, inflight_drained_ref="sha256:" + "2" * 64,
                target_fence_ref="sha256:" + "3" * 64)
    proof = dict(scope_entry=excluded, **refs)
    with transaction() as session:
        original = control.load_operation(session, command["operation_id"])["evidence"]
    observed = dict(original, observed_at=utc_now().isoformat(), table_exclusions=[proof])
    args = dict(source_id=SOURCE, operation_id=command["operation_id"], refresh_table_exclusions=True)
    for malformed in (dict(proof, scope_entry=dict(excluded, mirror_revision=1)),
                      dict(proof, scope_entry=next(entry for entry in command["published_scope"] if entry["included"])),
                      dict(proof, target_fence_ref="not-a-receipt")):
        with pytest.raises(SourceCaptureControlConflict):
            control.record_applied_evidence(**args, evidence=dict(observed, table_exclusions=[malformed]))
    assert service.get_mirror(mirror_id)["status"] == "disable_pending"
    control.record_applied_evidence(**args, evidence=observed)
    control.record_applied_evidence(**args, evidence=observed)
    disabled = service.get_mirror(mirror_id)
    assert disabled["status"] == "disabled"
    assert disabled["control"]["stop_ack"]["source_operation_id"] == command["operation_id"]
    assert set(disabled["operations"][-1]["observed_evidence_refs"]) == {command["operation_id"], *refs.values()}
    assert control.capture_status(SOURCE)["control"]["stop_ack"] is None
    service.set_enabled(mirror_id, enabled=True, actor_user_id="operator")
    with pytest.raises(SourceCaptureControlConflict):
        control.record_applied_evidence(**args, evidence=observed)


def test_stop_cannot_confirm_a_later_disable_before_the_scope_is_reconciled(management):
    transaction, _ = management
    mirror_id = service.enable_for_object("orders", actor_user_id="operator")["mirror"]["id"]
    _assign_runtime(transaction)
    _next_command()
    service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
    stale_stop = _next_command()

    service.set_enabled(mirror_id, enabled=True, actor_user_id="operator")
    service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
    _accept(stale_stop)
    assert service.get_mirror(mirror_id)["control"]["stop_ack"] is None
    assert inventory(status="disable_pending")["total"] == 1
    _accept(_next_command())
    assert service.get_mirror(mirror_id)["status"] == "disabled"


def test_stop_cannot_confirm_a_disable_after_another_table_enrolls(management):
    transaction, _ = management
    mirror_id = service.enable_for_object("orders", actor_user_id="operator")["mirror"]["id"]
    _assign_runtime(transaction)
    _next_command()
    service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
    stale_stop = _next_command()

    service.enable_for_object("items", actor_user_id="operator")
    _accept(stale_stop)
    assert service.get_mirror(mirror_id)["status"] == "disable_pending"
    assert service.get_mirror(mirror_id)["control"]["stop_ack"] is None
    assert _next_command()["kind"] == "reconcile"
