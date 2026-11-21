"""Standalone Mirror provisioning and native target read guards."""

import pytest

from backend.metadata.mirrors import service
from backend.metadata.mirrors.store import MemoryMirrorStore


def test_standalone_open_rejects_changed_table_binding(monkeypatch):
    store = MemoryMirrorStore()
    store.bindings["o1"] = dict(
        source_id="s1", object_id="o1", source_key="sales",
        source_name="Sales", qualified_table="public.orders", table_identity="o1",
    )
    monkeypatch.setattr(service, "_store", store)
    monkeypatch.setattr(service, "persist_audit_event", lambda **kwargs: None)

    opened = service.enable_for_object("o1", actor_user_id="operator")
    store.bindings["o1"]["qualified_table"] = "other.orders"
    with pytest.raises(service.MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        service.enable_for_object("o1", actor_user_id="operator")

    persisted = service.get_mirror(opened["mirror"]["id"])
    assert persisted["qualified_table"] == "public.orders"


def test_proof_validator_must_not_return_boolean_success():
    from backend.metadata.mirrors.reads import Reads

    class NeverConnect:
        def begin(self):
            pytest.fail("Unproven release must not reach target")

    reads = Reads(NeverConnect(), authorize_source_read=lambda **kw: None,
                  verify_terminal_proof=lambda **kw: True)
    with pytest.raises(service.MirrorError, match="MIRROR_READ_UNAVAILABLE"):
        reads.release_run_pins(run_id="run", terminal_proof={"terminal": True})
