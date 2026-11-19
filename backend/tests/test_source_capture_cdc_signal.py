import os

import pytest

from backend.tests.cdc.signal import EMPTY_TABLE, POPULATED_TABLE, SnapshotSignalProbe
from backend.tests.cdc.trial import disposable_profile


pytestmark = pytest.mark.skipif(os.getenv('REFRAQ_CDC_SIGNAL_TRIAL') != '1', reason='disposable Docker signal trial only')


@pytest.fixture
def snapshot_probe():
    profile = None
    try:
        with disposable_profile() as profile:
            probe = SnapshotSignalProbe(profile)
            probe.configure()
            yield probe
    finally:
        if profile is not None:
            counts = {
                kind: len(profile.docker(kind, 'ls', *(['-a'] if kind == 'container' else []), '-q',
                                         '--filter', 'label='+profile.label).splitlines())
                for kind in ('container', 'volume', 'network')
            }
            counts['temporary_directory'] = int(profile.root.exists())
            print(f'cleanup {counts}')
            assert not any(counts.values())


def test_source_signal_correlates_table_and_aggregate_completion(snapshot_probe):
    probe = snapshot_probe
    lineage = probe.lineage()
    live_end, _ = probe.seed_live_stream(POPULATED_TABLE)
    empty = probe.submit(EMPTY_TABLE)
    decisive = probe.terminal_notifications(empty, EMPTY_TABLE, 'EMPTY', rows=0)
    probe.verify_terminal_watermark(empty, EMPTY_TABLE, decisive, closed_windows=1)
    assert probe.end(probe.topic(EMPTY_TABLE)) == 0
    operation, chunk = probe.change_while_scan_blocked()
    decisive = probe.terminal_notifications(operation, POPULATED_TABLE, 'SUCCEEDED', rows=3)
    probe.verify_terminal_watermark(operation, POPULATED_TABLE, decisive, closed_windows=2)
    probe.verify_interleaving(operation, chunk, decisive, live_end)
    assert probe.lineage() == lineage


def test_source_signal_recovers_committed_operation_across_worker_restart(snapshot_probe):
    probe = snapshot_probe
    lineage = probe.lineage()
    live_end, baseline_lsn = probe.seed_live_stream(POPULATED_TABLE)
    probe.await_checkpoint(baseline_lsn)
    with probe.blocked_scan():
        operation = probe.submit(POPULATED_TABLE, lose_response=True)
        chunk = probe.await_open_window(operation)
        probe.kill_worker(operation, chunk)
    assert probe.retry_submission(operation, POPULATED_TABLE) is False
    assert probe.end(probe.topic(POPULATED_TABLE)) == live_end, 'Scan data was already present before restart'
    restart_offset = probe.end(probe.notifications)
    print(f'pre_restart operation={operation} data_end={live_end} notification_end={restart_offset}')
    probe.start_worker()
    decisive = probe.terminal_notifications(operation, POPULATED_TABLE, 'SUCCEEDED', rows=3,
                                            restart_offset=restart_offset)
    probe.verify_terminal_watermark(operation, POPULATED_TABLE, decisive, closed_windows=2)
    probe.verify_restart_stream(live_end)
    assert probe.lineage() == lineage
