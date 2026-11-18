"""Offline tests of the published target adapter seams; no PostgreSQL qualification."""

from contextlib import contextmanager

import pytest

from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.types import Authority, PartitionIdentity, Record
from backend.metadata.mirrors.publication import persist_verified_certificate
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.bootstrap import create_generation, validate_target


class Result:
    def scalar_one(self):
        return {"offset": 2, "commit_seq": 1}


class Connection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, parameters=None):
        self.calls.append((str(statement), parameters))
        return Result()


class Engine:
    def __init__(self):
        self.connection = Connection()
        self.committed = False

    @contextmanager
    def begin(self):
        yield self.connection
        self.committed = True


def authority():
    return Authority("source", "binding", 3, "runtime", 4, 2, "capture")


def test_apply_returns_coverage_only_after_transaction_commit():
    engine = Engine()
    result = Application(engine).apply_batch(
        authority=authority(), generation_id="generation",
        partition_identity=PartitionIdentity("cluster", "topic", 0),
        records=[Record(2, "table", "capture", "upsert", "live", {"id": 1}, {"id": 1, "name": "value"})],
    )
    assert engine.committed
    assert result == {"offset": 2, "commit_seq": 1}
    sql, params = engine.connection.calls[0]
    assert "source_mirror_state.apply_batch" in sql
    assert "value" not in sql
    assert '"offset": 2' in params["records"]


def test_unsupported_envelope_never_calls_target():
    engine = Engine()
    with pytest.raises(ValueError, match="operation"):
        Application(engine).apply_batch(
            authority=authority(), generation_id="generation",
            partition_identity=PartitionIdentity("cluster", "topic", 0),
            records=[Record(0, "table", "capture", "truncate", "live", {}, None)],
        )
    assert not engine.connection.calls


def test_negative_delivery_offset_is_rejected_before_target():
    engine = Engine()
    with pytest.raises(ValueError, match="offset"):
        Application(engine).apply_batch(
            authority=authority(), generation_id="gen",
            partition_identity=PartitionIdentity("cluster", "topic", 0),
            records=[Record(-1, "table", "capture", "control", "live", {}, None)])
    assert not engine.connection.calls


def test_incomplete_certificate_is_not_evidence():
    with pytest.raises(ValueError, match="Incomplete"):
        persist_verified_certificate(None, operation_id="op", authority=authority(),
                                     generation_id="gen", certificate={"complete": True}, verifier=None)


def test_revoked_reader_cannot_acquire_pin():
    engine = Engine()

    def deny(**kwargs):
        raise PermissionError("revoked")

    reader = Reads(engine, authorize_source_read=deny, verify_terminal_proof=deny)
    with pytest.raises(PermissionError):
        reader.acquire_pin(run_id="run", mirror_id="mirror", execution_user_id="user")
    assert len(engine.connection.calls) == 1
    assert "resolve_source" in engine.connection.calls[0][0]
    assert not engine.committed


def test_pin_release_requires_non_resumable_proof():
    engine = Engine()

    def deny(**kwargs):
        raise ValueError("Uncertain run")

    with pytest.raises(ValueError, match="Uncertain"):
        Reads(engine, authorize_source_read=deny, verify_terminal_proof=deny).release_run_pins(
            run_id="run", terminal_proof={"ttl_expired": True})
    assert not engine.connection.calls


def test_serving_validation_rejects_admin_identity():
    with pytest.raises(ValueError, match="restricted"):
        validate_target(None, expected_role="refraq_mirror_owner")


def test_bootstrap_accepts_management_mirror_identity():
    from dataclasses import asdict

    mid = "mir_" + "a" * 32
    gid = "b" * 32

    class Admin:
        @contextmanager
        def transaction(self):
            yield

        def execute(self, statement, parameters=None):
            self.parameters = parameters
            return self

        def fetchone(self):
            if self.parameters == (mid,):
                return ("source", "table", asdict(authority()))
            return None

    create_generation(
        Admin(), mirror_id=mid, generation_id=gid, authority=authority(),
        table_identity="table", history_epoch="epoch", operation_id="op",
        schema_fingerprint="schema", columns={"id": "bigint"}, key_columns=("id",),
        partition_identity=PartitionIdentity("cluster", "topic", 0), start_offset=-1,
    )


def test_apply_does_not_return_coverage_when_commit_fails():
    class CommitFailure(Engine):
        @contextmanager
        def begin(self):
            yield self.connection
            raise RuntimeError("commit failed")

    with pytest.raises(RuntimeError, match="commit failed"):
        Application(CommitFailure()).apply_batch(
            authority=authority(), generation_id="gen",
            partition_identity=PartitionIdentity("cluster", "topic", 0), records=[])
