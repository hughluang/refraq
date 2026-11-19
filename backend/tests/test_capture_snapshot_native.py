import json
import os
import time
from dataclasses import asdict, replace
from uuid import UUID

import pytest

from backend.metadata.capture.control import source_control_transaction
from backend.metadata.capture.store import load_binding, save_binding
from backend.metadata.capture.test_snapshot import SignalFixture, coordinator, prepared as prepared
from backend.metadata.mirrors.types import PartitionIdentity
from backend.tests.cdc.signal import EMPTY_TABLE, POPULATED_TABLE, SIGNAL_TABLE, SnapshotSignalProbe
from backend.tests.cdc.trial import DATA, disposable_profile


class NativeSnapshotSignals(SignalFixture):
    def __init__(self, probe):
        super().__init__()
        self.probe = probe
        self.profile = probe.profile
        self.profile.sql(f"""
            CREATE ROLE snapshot_submit NOLOGIN;
            CREATE ROLE snapshot_receipt NOLOGIN;
            GRANT INSERT, SELECT (id) ON {SIGNAL_TABLE} TO snapshot_submit;
            GRANT SELECT ON {SIGNAL_TABLE} TO snapshot_receipt;
        """)

    def baseline(self, binding, operation_id, *, challenge):
        assert binding.signal_table == SIGNAL_TABLE and binding.notification_topic == self.probe.notifications
        return self.signed("notifications", "snapshot:baseline", binding, operation_id, {
            "offset": self.probe.end(binding.notification_topic), "idle": True, "exclusive": True,
        }, challenge=challenge)

    def submit(self, binding, signal):
        operation_id = str(UUID(signal["id"]))
        payload = json.dumps(signal["data"]).replace("'", "''")
        assert signal["type"] == "execute-snapshot"
        self.signals.append((binding, signal))
        sql = (f"SET ROLE snapshot_submit; BEGIN; INSERT INTO {SIGNAL_TABLE} "
               f"VALUES ('{operation_id}', 'execute-snapshot', '{payload}') "
               "ON CONFLICT (id) DO NOTHING; COMMIT;")
        if binding.qualified_table == POPULATED_TABLE:
            assert self.profile.sql(sql + " SELECT 1 / 0;", check=False) is None
            raise TimeoutError
        self.profile.sql(sql)

    def receipt(self, binding, operation_id):
        operation_id = str(UUID(operation_id))
        result = self.profile.sql(f"SET ROLE snapshot_receipt; SELECT json_build_object('id', id, 'type', type, "
                                  f"'data', data::json) FROM {SIGNAL_TABLE} WHERE id = '{operation_id}';")
        if not result:
            return None
        print(f"native_receipt generation={binding.generation_id} signal={result}")
        return self.signed("receipt", "snapshot:receipt", binding, operation_id, json.loads(result))

    def notifications(self, binding, operation_id, offset, *, challenge):
        cluster, topic_ids = broker_lineage(self.probe)
        assert binding.notification_partition == PartitionIdentity(cluster, topic_ids[binding.notification_topic], 0)
        end = self.probe.end(binding.notification_topic)
        batch = self.probe.read(binding.notification_topic, offset, end) if end > offset else []
        for position, _, value in batch:
            print(f"native_notification generation={binding.generation_id} operation={operation_id} "
                  f"offset={position} value={json.dumps(value, sort_keys=True)}")
        return self.signed("notifications", "snapshot:notifications", binding, operation_id, {
            "start": offset, "end": end, "high_water": end, "exclusive": True,
            "records": [dict(offset=position, key=key, value=value) for position, key, value in batch],
        }, challenge=challenge)


def broker_lineage(probe):
    topic_ids, _, _ = probe.lineage()
    cluster = probe.profile.exe('broker', 'sed', '-n', 's/^cluster.id=//p', f'{DATA["broker"]}/meta.properties')
    assert cluster
    return cluster, topic_ids


def catch_up(worker, binding, operation_id):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        result = worker.reconcile(binding)
        assert result.operation_id == operation_id
        assert result.state in {"submission_uncertain", "snapshotting", "catching_up"}
        if result.state == "catching_up":
            assert result.scan_offset < result.completion_offset
            print(f"native_catch_up binding={asdict(binding)} result={asdict(result)}")
            return result
    raise AssertionError("Native terminal notifications did not advance the generation")


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("REFRAQ_CDC_SIGNAL_TRIAL") != "1", reason="disposable Docker signal trial only")
@pytest.mark.parametrize("prepared", ["postgresql"], indirect=True)
def test_coordinator_correlates_pinned_native_snapshots_after_lost_response(tmp_path, prepared):
    with disposable_profile() as profile:
        profile.deadline += 120
        probe = SnapshotSignalProbe(profile)
        probe.configure()
        live_end, baseline_lsn = probe.seed_live_stream(POPULATED_TABLE)
        probe.await_checkpoint(baseline_lsn)
        cluster, topic_ids = broker_lineage(probe)
        relation = profile.sql(f"SELECT oid || ':' || '{SIGNAL_TABLE}'::regclass::oid "
                               "FROM pg_database WHERE datname = current_database();")
        empty, populated = [replace(
            binding, qualified_table=table, connector_name=probe.source, signal_relation_identity=relation,
            notification_topic=probe.notifications,
            notification_partition=PartitionIdentity(cluster, topic_ids[probe.notifications], 0),
            data_partition=PartitionIdentity(cluster, topic_ids[probe.topic(table)], 0),
        ) for binding, table in zip(prepared, (EMPTY_TABLE, POPULATED_TABLE), strict=True)]
        with source_control_transaction(empty.authority.source_id) as (session, _):
            state = load_binding(session, empty.authority.source_id)
            for entry, binding in zip(state["published_scope"], (empty, populated), strict=True):
                entry["qualified_table"] = binding.qualified_table
            save_binding(session, state)
        signals = NativeSnapshotSignals(probe)
        worker = coordinator(tmp_path, signals)
        try:
            first = worker.reconcile(empty)
            catch_up(worker, empty, first.operation_id)
            assert probe.end(probe.topic(EMPTY_TABLE)) == 0
            with probe.blocked_scan(f"DELETE FROM {POPULATED_TABLE} WHERE id = 1;"):
                interrupted = worker.reconcile(populated)
                assert interrupted.state == "submission_uncertain"
                chunk = probe.await_open_window(interrupted.operation_id)
                probe.kill_worker(interrupted.operation_id, chunk)
        finally:
            worker.journal.close()
        probe.start_worker()
        restarted = coordinator(tmp_path, signals)
        try:
            recovered = catch_up(restarted, populated, interrupted.operation_id)
            assert recovered.operation_id == interrupted.operation_id and len(signals.signals) == 2
            end = probe.await_records(probe.topic(POPULATED_TABLE), live_end + 3)
            changes = probe.changes(POPULATED_TABLE, probe.read(probe.topic(POPULATED_TABLE), live_end, end))
            assert (1, "d", "false", "before-delete", None) in changes
            assert all(key != 1 or operation != "r" for key, operation, *_ in changes)
            assert {key for key, operation, *_ in changes if operation == "r"} == {2, 4}
            print(f"native_data operation={recovered.operation_id} partition=0 first={live_end} end={end} changes={changes}")
        finally:
            restarted.journal.close()
