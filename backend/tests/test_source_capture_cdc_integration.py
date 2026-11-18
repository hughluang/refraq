import os

import pytest

from backend.tests.cdc.trial import disposable_profile


@pytest.mark.skipif(os.getenv('REFRAQ_CDC_TRIAL') != '1', reason='disposable Docker trial only')
def test_keyed_changes_replay_across_worker_restart():
    with disposable_profile() as profile:
        profile.await_stream()
        slot = profile.slot_identity()
        initial_lsn = profile.confirmed_lsn()
        assert profile.sql("INSERT INTO items VALUES (7,'first') RETURNING id;") == '7'
        assert profile.sql("UPDATE items SET value='second' WHERE id=7 RETURNING id;") == '7'
        assert profile.sql('DELETE FROM items WHERE id=7 RETURNING id;') == '7'
        first = profile.consume(3)
        assert first == [
            (0, {'id': 7}, 'c', None, {'id': 7, 'value': 'first'}),
            (1, {'id': 7}, 'u', {'id': 7, 'value': 'first'}, {'id': 7, 'value': 'second'}),
            (2, {'id': 7}, 'd', {'id': 7, 'value': 'second'}, None),
        ]
        checkpoint = profile.await_checkpoint(initial_lsn)
        assert profile.partition_end() == 3
        profile.restart_worker()
        assert profile.slot_identity() == slot
        assert profile.confirmed_lsn() >= checkpoint[0]
        assert profile.source_offset() == checkpoint[1]
        assert profile.sql("INSERT INTO items VALUES (8,'resumed') RETURNING id;") == '8'
        resumed = (3, {'id': 8}, 'c', None, {'id': 8, 'value': 'resumed'})
        assert profile.consume(4) == [*first, resumed]
        profile.await_checkpoint(*checkpoint)
        assert profile.partition_end() == 4
        assert profile.slot_identity() == slot
