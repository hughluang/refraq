"""Incremental mirror node contracts and native target proof."""

from os import environ, getenv
from subprocess import run
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from backend.channel.checkpoints import LocalCheckpoints, MirrorCheckpointPosition
from backend.channel.nodes.read.changes import NODE_TYPE
from backend.tests.test_mirror_history import setup_history as setup_history


def point(commit, entry=0, epoch="epoch", mirror_id="mirror"):
    return dict(mirror_id=mirror_id, history_epoch=epoch, commit_seq=commit, entry_seq=entry)


class Hooks:
    ignore_checkpoints = False

    def __init__(self):
        self.checkpoints = LocalCheckpoints()
        self.calls = []

    def capture_mirror_history(self, *, mirror_id):
        return dict(history_epoch="epoch", source_id="source", lower_bound=point(0), upper_bound=point(2))

    def read_mirror_changes(self, **kwargs):
        self.calls.append(kwargs)
        return dict(entries=[dict(position=point(1, 1), origin="live", operation="insert", key={"id": 7}, typed_key={"id": 7}, before=None, after={"id": 7})], next_position=point(2), source_ids=["source"])


class HistoryHooks(Hooks):
    def __init__(self, history):
        super().__init__()
        self.history = history

    def capture_mirror_history(self, *, mirror_id):
        return self.history.capture_bound(mirror_id=mirror_id, execution_user_id="user")

    def read_mirror_changes(self, **kwargs):
        self.calls.append(kwargs)
        return self.history.read_incremental(execution_user_id="user", **kwargs)


def node(*, mirror_id="mirror", **config):
    return dict(id="read", config=dict(source=dict(kind="mirror", mirror_id=mirror_id), **config))


def test_catalog_accepts_mirror_without_entity_and_keeps_entity():
    validator = Draft202012Validator(NODE_TYPE.config_schema)
    assert not list(validator.iter_errors(node()["config"]))
    assert not list(validator.iter_errors(dict(entity_id="entity")))
    assert list(validator.iter_errors(dict(source=dict(kind="mirror", mirror_id=""))))


def test_node_reads_bounded_live_history_and_proposes_mirror_lineage():
    hooks = Hooks()
    result = NODE_TYPE.execute(node(limit=3), hooks)
    assert result.status == "succeeded"
    assert result.output["entries"][0]["after"] == {"id": 7}
    assert result.output["source_ids"] == ["source"]
    assert hooks.calls[0]["through"] == point(2)
    assert hooks.calls[0]["after"] == point(0)
    assert hooks.checkpoints.proposed("read", "mirror") == MirrorCheckpointPosition("epoch", 2, 0, ("source",))


def test_dataset_consumes_pages_before_proposal(monkeypatch):
    from backend.channel.nodes.volume import changes_dataset as module

    hooks = Hooks()
    hooks.run_id = "run"
    hooks.cancelled = lambda: False
    hooks.superseded = lambda: False
    rows = []

    class Registry:
        def __init__(self, store):
            pass

        def create_from_chunks(self, **kwargs):
            assert not hooks.checkpoints.proposals
            rows.extend(row for chunk in kwargs["chunks"] for row in chunk)
            return SimpleNamespace(id="dataset", columns=[], row_count=len(rows))

    monkeypatch.setattr(module, "DatasetRegistry", Registry)
    monkeypatch.setattr(module, "_execution_seq", lambda *_: 1)
    result = module.NODE_TYPE.execute(node(limit=10), hooks)
    assert result.status == "succeeded"
    assert result.output["source_ids"] == ["source"]
    assert len(rows) == 1
    assert hooks.checkpoints.proposed("read", "mirror").commit_seq == 2


def test_per_page_revocation_returns_no_output_or_proposal():
    from backend.channel.mirror_reads import MirrorDataForbidden

    hooks = Hooks()

    def read(**kwargs):
        hooks.calls.append(kwargs)
        if len(hooks.calls) == 2:
            raise MirrorDataForbidden()
        return dict(entries=[dict(position=point(1, 1), origin="live", operation="insert", typed_key={"id": 7}, before=None, after={"id": 7})], next_position=point(1, 1), source_ids=["source"])

    hooks.read_mirror_changes = read
    result = NODE_TYPE.execute(node(limit=1000), hooks)
    assert result.error_code == "AUTH_FORBIDDEN"
    assert result.output is None
    assert not hooks.checkpoints.proposals
    assert all(call["through"] == point(2) for call in hooks.calls)
    assert all(call["limit"] <= 500 for call in hooks.calls)


@pytest.mark.parametrize("origin", ["snapshot", "baseline"])
def test_non_live_entries_are_never_dispatched(origin):
    hooks = Hooks()
    read = hooks.read_mirror_changes

    def page(**kwargs):
        result = read(**kwargs)
        result["entries"][0]["origin"] = origin
        return result

    hooks.read_mirror_changes = page
    result = NODE_TYPE.execute(node(), hooks)
    assert result.error_code == "CHANNEL_CHECKPOINT_INVALID"
    assert not hooks.checkpoints.proposals


def test_run_gateway_persists_bound_and_provenance_before_read(monkeypatch):
    from backend.channel import mirror_reads

    run = SimpleNamespace(job_id="run", mirror_execution_user_id="user", mirror_state=None)
    saved = []
    monkeypatch.setattr(mirror_reads, "_reads", object())
    monkeypatch.setattr(mirror_reads, "_authorize", lambda *_: None)
    monkeypatch.setattr(mirror_reads, "get_run_store", lambda: SimpleNamespace(update_run=lambda value: saved.append(value.mirror_state.copy())))
    monkeypatch.setattr(mirror_reads, "capture_bound", lambda **_: Hooks().capture_mirror_history(mirror_id="mirror"))
    bound = mirror_reads.capture_run_history(run, mirror_id="mirror")
    assert saved[0]["source_ids"] == ["source"]

    def read(**kwargs):
        assert saved[0]["history_bounds"]["mirror"]["upper_bound"] == point(2)
        assert kwargs["execution_user_id"] == "user"
        return dict(source_ids=["source"], entries=[], next_position=point(2))

    monkeypatch.setattr(mirror_reads, "read_incremental", read)
    mirror_reads.read_run_history(run, mirror_id="mirror", after=point(0), through=bound["upper_bound"], limit=5)
    monkeypatch.setattr(mirror_reads, "capture_bound", lambda **_: dict(bound, upper_bound=point(9)))
    assert mirror_reads.capture_run_history(run, mirror_id="mirror")["upper_bound"] == point(2)


@pytest.mark.parametrize("node_type", ["read.changes", "volume.changes_dataset"])
@pytest.mark.parametrize("case,expected_code", [
    ("epoch", "MIRROR_HISTORY_INVALID"),
    ("invalidating", "MIRROR_HISTORY_INVALID"),
    ("source", "MIRROR_HISTORY_INVALID"),
    ("retention", "CHANNEL_CHECKPOINT_INVALID"),
    ("retention_past_upper", "MIRROR_HISTORY_INVALID"),
    ("ignored_resume_cursor", "CHANNEL_CHECKPOINT_INVALID"),
    ("future_upper", "MIRROR_HISTORY_INVALID"),
    ("future_lower", "MIRROR_HISTORY_INVALID"),
    ("wrong_stream", "MIRROR_HISTORY_INVALID"),
    ("bad_position", "MIRROR_HISTORY_INVALID"),
    ("null_bound", "MIRROR_HISTORY_INVALID"),
    ("outage", "MIRROR_READ_UNAVAILABLE"),
    ("revoked", "AUTH_FORBIDDEN"),
    ("unchanged", None),
    ("retained_resume", None),
    ("concurrent_advance", None),
])
def test_incremental_nodes_resume_saved_history(setup_history, monkeypatch, node_type, case, expected_code):
    from backend.channel import mirror_reads
    from backend.channel.nodes.volume import changes_dataset
    from backend.metadata.mirrors.history_models import HistoryGateRow
    from backend.metadata.mirrors.models import MirrorRow

    history, factory, target, auth = setup_history
    saved_upper = point(2, 1, mirror_id="a")
    saved = history.capture_bound(mirror_id="a", execution_user_id="user")
    run = SimpleNamespace(job_id="run", mirror_execution_user_id="user", mirror_state={
        "source_ids": ["source"], "history_bounds": {"a": saved},
    })
    hooks = Hooks()
    hooks.run_id = run.job_id
    hooks.cancelled = lambda: False
    hooks.superseded = lambda: False
    hooks.capture_mirror_history = lambda **kw: mirror_reads.capture_run_history(run, **kw)
    hooks.read_mirror_changes = lambda **kw: mirror_reads.read_run_history(run, **kw)
    hooks.ignore_checkpoints = case in {"epoch", "ignored_resume_cursor"}
    monkeypatch.setattr(mirror_reads, "_reads", object())
    monkeypatch.setattr(mirror_reads, "_authorize", lambda *_: None)
    monkeypatch.setattr(mirror_reads, "capture_bound", history.capture_bound)
    monkeypatch.setattr(mirror_reads, "read_incremental", history.read_incremental)
    monkeypatch.setattr(mirror_reads, "get_run_store", lambda: SimpleNamespace(
        update_run=lambda _: pytest.fail("Resumed history overwrote its snapshot"),
    ))
    target_pages = []
    original_read = target.read_incremental

    def read(**kwargs):
        target_pages.append(kwargs)
        return original_read(**kwargs)

    monkeypatch.setattr(target, "read_incremental", read)
    landed = []

    class Registry:
        def __init__(self, store):
            pass

        def create_from_chunks(self, **kwargs):
            landed.extend(row for chunk in kwargs["chunks"] for row in chunk)
            return SimpleNamespace(id="dataset", columns=[], row_count=len(landed))

    monkeypatch.setattr(changes_dataset, "DatasetRegistry", Registry)
    monkeypatch.setattr(changes_dataset, "_execution_seq", lambda *_: 1)
    with factory.begin() as session:
        gate = session.get(HistoryGateRow, "a")
        if case == "epoch":
            gate.history_epoch = "replacement"
            target.bounds["a"].update(history_epoch="replacement",
                                      lower_bound=point(0, epoch="replacement", mirror_id="a"),
                                      upper_bound=point(2, 1, epoch="replacement", mirror_id="a"))
        elif case == "invalidating":
            gate.status = "invalidating"
        elif case == "source":
            session.get(MirrorRow, "a").source_id = "replacement"
            target.bounds["a"]["source_id"] = "replacement"
        elif case in {"retention", "retained_resume", "ignored_resume_cursor"}:
            gate.lower_commit_seq = 1
            target.bounds["a"]["lower_bound"] = point(1, mirror_id="a")
            if case == "retained_resume":
                hooks.checkpoints.propose("read", "a", MirrorCheckpointPosition("epoch", 1, 0, ("source",)))
            elif case == "ignored_resume_cursor":
                hooks.checkpoints.durable = lambda *_: MirrorCheckpointPosition("epoch", 1, 0, ("source",))
        elif case == "future_upper":
            target.bounds["a"]["upper_bound"] = point(1, 1, mirror_id="a")
        elif case == "future_lower":
            saved["lower_bound"] = point(1, 1, mirror_id="a")
        elif case == "wrong_stream":
            saved["upper_bound"]["mirror_id"] = "b"
        elif case == "bad_position":
            saved["upper_bound"]["entry_seq"] = True
        elif case == "null_bound":
            run.mirror_state["history_bounds"]["a"] = None
        elif case == "retention_past_upper":
            gate.lower_commit_seq = 3
            target.bounds["a"].update(lower_bound=point(3, mirror_id="a"),
                                      upper_bound=point(4, mirror_id="a"))
        elif case == "outage":
            target.fail = True
        elif case == "revoked":
            auth["allowed"] = False
        elif case in {"unchanged", "concurrent_advance"}:
            target.bounds["a"]["upper_bound"] = point(3, mirror_id="a")

    durable_reads = []
    if case == "concurrent_advance":
        def durable(node_id, stream):
            durable_reads.append((node_id, stream))
            commit = 0 if len(durable_reads) == 1 else 3
            return MirrorCheckpointPosition("epoch", commit, 0, ("source",))

        hooks.checkpoints.durable = durable

    spec = NODE_TYPE if node_type == "read.changes" else changes_dataset.NODE_TYPE
    result = spec.execute(node(mirror_id="a"), hooks)

    if expected_code:
        assert result.status == "failed"
        assert result.error_code == expected_code
        assert result.output is None
        assert not target_pages and not landed and not hooks.checkpoints.proposals
    else:
        assert result.status == "succeeded"
        assert result.output["count"] == 1
        assert target_pages[0]["through"] == saved_upper
        assert target_pages[0]["after"] == point(int(case == "retained_resume"), mirror_id="a")
        assert run.mirror_state["history_bounds"]["a"]["upper_bound"] == saved_upper
        assert hooks.checkpoints.proposed("read", "a") == MirrorCheckpointPosition("epoch", 2, 1, ("source",))
        if case == "concurrent_advance":
            assert durable_reads == [("read", "a")]


def test_missing_gateway_fails_closed(monkeypatch):
    from backend.channel import mirror_reads

    monkeypatch.setattr(mirror_reads, "_reads", None)
    with pytest.raises(mirror_reads.MirrorReadUnavailable):
        mirror_reads.capture_run_history(SimpleNamespace(), mirror_id="mirror")


def test_empty_history_does_not_propose():
    hooks = Hooks()
    hooks.capture_mirror_history = lambda **_: dict(history_epoch="epoch", source_id="source", lower_bound=point(0), upper_bound=point(0))
    result = NODE_TYPE.execute(node(), hooks)
    assert result.status == "succeeded"
    assert result.output["entries"] == []
    assert result.output["has_more"] is False
    assert not hooks.checkpoints.proposals


def writer_entry(entry_seq, operation, typed_key, before, after):
    return dict(position=point(1, entry_seq, mirror_id="a"), origin="live", operation=operation,
                source_id="source", generation_id="generation", capture_generation="capture",
                typed_key=typed_key, before=before, after=after)


def test_writer_shaped_history_folds_typed_keys_and_preserves_endpoints(setup_history):
    history, _, target, _ = setup_history
    existing_key = {"tenant": "x", "id": 8}
    numeric_key = {"tenant": "x", "id": 7}
    text_key = {"tenant": "x", "id": "7"}
    old_row = {**existing_key, "value": "old"}
    replacement = {**existing_key, "value": "replacement"}
    new_row = {**numeric_key, "value": None}
    updated = {**numeric_key, "value": "updated"}
    text_row = {**text_key, "value": "text"}
    target.entries["a"] = [
        writer_entry(1, "delete", existing_key, old_row, None),
        writer_entry(2, "upsert", numeric_key, None, new_row),
        writer_entry(3, "upsert", text_key, None, text_row),
        writer_entry(4, "upsert", {"id": 7, "tenant": "x"}, new_row, updated),
        writer_entry(5, "upsert", existing_key, None, replacement),
    ]
    upper = point(1, 5, mirror_id="a")
    target.bounds["a"]["upper_bound"] = upper

    chronological = NODE_TYPE.execute(node(mirror_id="a"), HistoryHooks(history))
    assert chronological.status == "succeeded"
    assert [entry["operation"] for entry in chronological.output["entries"]] == [
        "delete", "insert", "insert", "update", "insert",
    ]
    assert [entry["position"] for entry in chronological.output["entries"]] == [
        point(1, entry, mirror_id="a") for entry in range(1, 6)
    ]

    hooks = HistoryHooks(history)
    result = NODE_TYPE.execute(node(mirror_id="a", shape="net"), hooks)
    assert result.status == "succeeded"
    assert [(
        entry["typed_key"], entry["operation"], entry["before"], entry["after"],
        entry["first_position"]["entry_seq"], entry["position"]["entry_seq"], entry["last_position"]["entry_seq"],
    ) for entry in result.output["entries"]] == [
        (existing_key, "update", old_row, replacement, 1, 5, 5),
        (numeric_key, "insert", None, updated, 2, 4, 4),
        (text_key, "insert", None, text_row, 3, 3, 3),
    ]
    assert result.output["last_position"] == upper


def test_empty_net_across_authorized_pages_proposes_consumed_prefix(setup_history):
    history, _, target, auth = setup_history
    key = {"tenant": "x", "id": 7}
    target.entries["a"] = [
        writer_entry(index, "upsert", key, None if index == 1 else {**key, "value": index - 1},
                     {**key, "value": index})
        for index in range(1, 501)
    ] + [
        writer_entry(501, "delete", key, {**key, "value": 500}, None),
        writer_entry(502, "upsert", key, None, {**key, "value": "next range"}),
    ]
    upper = point(1, 502, mirror_id="a")
    target.bounds["a"]["upper_bound"] = upper
    hooks = HistoryHooks(history)

    result = NODE_TYPE.execute(node(mirror_id="a", shape="net", limit=501), hooks)

    assert result.status == "succeeded"
    assert result.output == dict(entries=[], count=0, has_more=True,
                                 last_position=point(1, 501, mirror_id="a"), source_ids=["source"])
    assert hooks.checkpoints.proposed("read", "a") == MirrorCheckpointPosition("epoch", 1, 501, ("source",))
    assert [call["limit"] for call in hooks.calls] == [500, 1]
    assert all(call["through"] == upper for call in hooks.calls)
    assert len(auth["calls"]) == 3


@pytest.fixture
def disposable_mirror_target():
    from sqlalchemy import URL

    if getenv("REFRAQ_RUN_MIRROR_NATIVE_TEST") != "1":
        pytest.skip("Set REFRAQ_RUN_MIRROR_NATIVE_TEST=1 to start a disposable PostgreSQL container")

    docker = ["docker", "--host", "unix:///var/run/docker.sock"]
    password = uuid4().hex
    container = run(
        [*docker, "create", "--pull=never", "--tmpfs", "/var/lib/postgresql",
         "--publish", "127.0.0.1::5432", "--env", "POSTGRES_PASSWORD", "postgres:18.6-bookworm"],
        env={**environ, "POSTGRES_PASSWORD": password},
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout.strip()
    try:
        run([*docker, "start", container], capture_output=True, check=True, timeout=15)
        deadline = monotonic() + 30
        while monotonic() < deadline:
            ready = run(
                [*docker, "exec", container, "pg_isready", "-q", "-h", "127.0.0.1"],
                capture_output=True, timeout=5,
            )
            if ready.returncode == 0:
                break
            sleep(0.25)
        else:
            pytest.fail("Disposable mirror target did not become ready")
        address = run(
            [*docker, "port", container, "5432/tcp"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
        host, port = address.rsplit(":", 1)
        assert host == "127.0.0.1"
        yield URL.create(
            "postgresql+psycopg", username="postgres", password=password,
            host=host, port=int(port), database="postgres",
            query={"hostaddr": host, "connect_timeout": "3"},
        )
    finally:
        run([*docker, "rm", "--force", "--volumes", container], capture_output=True, check=True, timeout=15)


@pytest.mark.integration
def test_native_target_writer_to_channel_history(setup_history, disposable_mirror_target):
    from sqlalchemy import create_engine

    from backend.metadata.mirrors.application import Application
    from backend.metadata.mirrors.bootstrap import create_generation, install
    from backend.metadata.mirrors.history import History, SqlHistoryTarget
    from backend.metadata.mirrors.models import MirrorRow
    from backend.metadata.mirrors.types import Authority, PartitionIdentity, Record

    admin = create_engine(disposable_mirror_target)
    applier = create_engine(disposable_mirror_target, connect_args={"options": "-c role=refraq_mirror_applier"})
    gateway = create_engine(disposable_mirror_target, connect_args={"options": "-c role=refraq_mirror_gateway"})
    try:
        offline_history, factory, _, _ = setup_history
        mirror_id, generation = f"mir_{uuid4().hex}", uuid4().hex
        authority = Authority("source", "binding", 1, "runtime", 1, 1, "capture")
        partition = PartitionIdentity("cluster", "topic", 0)
        with admin.connect() as connection:
            driver = connection.connection.driver_connection
            install(driver)
            create_generation(
                driver, mirror_id=mirror_id, generation_id=generation, authority=authority,
                table_identity="table", history_epoch="epoch", operation_id=generation,
                schema_fingerprint="schema", columns={"tenant": "text", "id": "bigint", "value": "text"},
                key_columns=("tenant", "id"), partition_identity=partition, start_offset=-1,
            )
        history = History(session_factory=factory, target=SqlHistoryTarget(
            engine=gateway, invalidation_engine=applier, timeout_ms=2000,
        ), authorize_source_read=offline_history.authorize_source_read)
        with factory.begin() as session:
            session.add(MirrorRow(id=mirror_id, source_id="source", table_identity="table", enabled=True,
                                  state={"history_epoch": "epoch"}))

        original = {"tenant": "x", "id": 8, "value": "original"}
        changed = {**original, "value": "changed"}
        replacement = {**original, "value": "replacement"}
        transient = {"tenant": "x", "id": 7, "value": None}
        existing_key = {"tenant": "x", "id": 8}
        application = Application(applier)
        application.apply_batch(authority=authority, generation_id=generation, partition_identity=partition, records=[
            Record(0, "table", "capture", "upsert", "baseline", existing_key, original),
            Record(1, "table", "capture", "upsert", "live", {"id": "007", "tenant": "x"}, transient),
            Record(2, "table", "capture", "upsert", "live", existing_key, changed),
        ])
        application.apply_batch(authority=authority, generation_id=generation, partition_identity=partition, records=[
            Record(3, "table", "capture", "delete", "live", {"tenant": "x", "id": 7}, None),
            Record(4, "table", "capture", "delete", "live", existing_key, None),
            Record(5, "table", "capture", "upsert", "live", existing_key, replacement),
        ])

        chronological = NODE_TYPE.execute(node(mirror_id=mirror_id), HistoryHooks(history))
        assert chronological.status == "succeeded"
        assert [(entry["operation"], entry["before"], entry["after"]) for entry in chronological.output["entries"]] == [
            ("insert", None, transient), ("update", original, changed), ("delete", transient, None),
            ("delete", changed, None), ("insert", None, replacement),
        ]
        assert chronological.output["entries"][0]["typed_key"] == {"tenant": "x", "id": 7}

        hooks = HistoryHooks(history)
        result = NODE_TYPE.execute(node(mirror_id=mirror_id, shape="net"), hooks)
        assert result.status == "succeeded"
        entry, = result.output["entries"]
        assert (entry["operation"], entry["typed_key"], entry["before"], entry["after"]) == (
            "update", existing_key, original, replacement,
        )
        assert entry["first_position"] == point(1, 2, mirror_id=mirror_id)
        assert entry["position"] == entry["last_position"] == point(2, 3, mirror_id=mirror_id)
        assert hooks.checkpoints.proposed("read", mirror_id) == MirrorCheckpointPosition("epoch", 2, 3, ("source",))
    finally:
        gateway.dispose()
        applier.dispose()
        admin.dispose()


def test_dataset_failure_does_not_propose_or_expose_driver_details(monkeypatch):
    from backend.channel.nodes.volume import changes_dataset as module

    class Registry:
        def __init__(self, store):
            pass

        def create_from_chunks(self, **kwargs):
            list(kwargs["chunks"])
            raise RuntimeError("sensitive row image")

    hooks = Hooks()
    hooks.run_id = "run"
    hooks.cancelled = lambda: False
    hooks.superseded = lambda: False
    monkeypatch.setattr(module, "DatasetRegistry", Registry)
    monkeypatch.setattr(module, "_execution_seq", lambda *_: 1)
    result = module.NODE_TYPE.execute(node(), hooks)
    assert result.status == "failed"
    assert "sensitive" not in result.error_message
    assert not hooks.checkpoints.proposals


def test_old_epoch_never_reads_or_proposes_even_when_ignoring_checkpoints():
    hooks = Hooks()
    hooks.checkpoints.durable_positions[("read", "mirror")] = MirrorCheckpointPosition("old", 1, 0, ("source",))
    hooks.ignore_checkpoints = True
    result = NODE_TYPE.execute(node(), hooks)
    assert result.error_code == "CHANNEL_CHECKPOINT_INVALID"
    assert not hooks.calls
    assert not hooks.checkpoints.proposals
