"""Standalone Mirror provisioning and native target read guards."""

import ast
from pathlib import Path

import pytest

from backend.metadata.mirrors import service
from backend.metadata.mirrors.errors import MirrorError
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
    with pytest.raises(MirrorError, match="MIRROR_CONTROL_CONFLICT"):
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
    with pytest.raises(MirrorError, match="MIRROR_READ_UNAVAILABLE"):
        reads.release_run_pins(run_id="run", terminal_proof={"terminal": True})


MIRRORS = Path(__file__).resolve().parents[1] / "metadata" / "mirrors"


def _sources():
    return [(path, ast.parse(path.read_text())) for path in sorted(MIRRORS.glob("*.py")) if not path.name.startswith("test_")]


def test_orchestration_does_not_branch_on_the_memory_adapter():
    offenders = [
        path.name for path, tree in _sources() if path.name != "store.py"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "isinstance"
        and any(isinstance(arg, ast.Name) and arg.id == "MemoryMirrorStore" for arg in ast.walk(node.args[1]))
    ]
    assert offenders == []


def test_mirror_modules_do_not_import_private_names_across_modules():
    offenders = [
        f"{path.name}:{alias.name}" for path, tree in _sources() for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("backend.")
        for alias in node.names if alias.name.startswith("_")
    ]
    assert offenders == []
