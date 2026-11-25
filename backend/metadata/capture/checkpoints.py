"""Per-engine publication hand-off checkpoint evidence validation.

Every confirmer takes the signed evidence of a published Open and the pinned
profile scope, and returns the durable source checkpoint or blocks. The shared
part proves the Kafka transport placement; the engine part proves the source
log position (slot/LSN, binlog/GTID, change LSN, SCN). The gateway produces the
evidence; this module is the repository-side contract for what it must contain.
"""

import re

from backend.metadata.capture.runtime_store import RuntimeBlocked

BLOCKED = "published_open_checkpoint_unconfirmed"
_PARTITION_KEYS = {"runtime_cluster_id", "topic_incarnation_id", "partition"}


def _is_int(value):
    return type(value) is int


def _transport(evidence, scope, data_topics, data_partitions):
    checkpoint = evidence.get("durable_source_checkpoint")
    exclusion = evidence.get("producer_exclusion")
    if not isinstance(checkpoint, dict) or not isinstance(exclusion, dict):
        raise RuntimeBlocked(BLOCKED)
    topic = checkpoint.get("topic")
    partition = checkpoint.get("partition")
    notification = evidence["source_completion"]
    lineage = exclusion.get("source_lineage")
    if (not isinstance(topic, str) or not topic or topic in data_topics or topic == notification["notification_topic"]
            or not isinstance(partition, dict) or set(partition) != _PARTITION_KEYS
            or not isinstance(partition["topic_incarnation_id"], str) or not partition["topic_incarnation_id"]
            or not _is_int(partition["partition"]) or partition["partition"] != 0
            or any(partition["runtime_cluster_id"] != data.runtime_cluster_id
                   or partition["topic_incarnation_id"] == data.topic_incarnation_id for data in data_partitions)
            or partition["topic_incarnation_id"] == notification["notification_partition"]["topic_incarnation_id"]
            or checkpoint.get("key") != [scope["connector_name"], {"server": scope["topic_prefix"]}]
            or not isinstance(lineage, list) or len(lineage) != 4
            or any(not isinstance(value, str) or not value for value in lineage)
            or not _is_int(checkpoint.get("offset")) or not _is_int(checkpoint.get("eof"))):
        raise RuntimeBlocked(BLOCKED)
    return checkpoint, exclusion


def _witness_ordered(checkpoint, witness):
    previous = witness.get("previous_checkpoint_offset")
    return _is_int(previous) and 0 <= previous < checkpoint["offset"] < checkpoint["eof"]


def confirm_postgresql(evidence, scope, *, data_topics, data_partitions):
    checkpoint, exclusion = _transport(evidence, scope, data_topics, data_partitions)
    value = checkpoint.get("value")
    witness = checkpoint.get("wal_witness")
    if (exclusion.get("slot") != scope["slot"] or exclusion.get("publication") != scope["publication"]
            or not isinstance(value, dict) or not isinstance(witness, dict) or value.get("messageType") != "COMMIT"
            or any(not _is_int(value.get(key)) for key in ("txId", "lsn", "lsn_proc", "lsn_commit"))
            or any(not _is_int(witness.get(key))
                   for key in ("xid", "wal_start", "wal_end", "commit_lsn", "previous_checkpoint_offset"))
            or not _is_int(exclusion.get("confirmed_flush_lsn"))
            or not _witness_ordered(checkpoint, witness)
            or not 0 < witness["xid"] == value["txId"]
            or not 0 < witness["wal_start"] < witness["wal_end"] <= exclusion["confirmed_flush_lsn"]
            or not witness["wal_start"] <= witness["commit_lsn"] <= witness["wal_end"]
            or not witness["commit_lsn"] == value["lsn"] == value["lsn_proc"] == value["lsn_commit"]):
        raise RuntimeBlocked(BLOCKED)
    return checkpoint


def confirm_mysql(evidence, scope, *, data_topics, data_partitions):
    """Binlog file and position, plus the GTID set in GTID lineage mode, bound to the pinned server."""
    checkpoint, exclusion = _transport(evidence, scope, data_topics, data_partitions)
    value = checkpoint.get("value")
    witness = checkpoint.get("binlog_witness")
    if (not isinstance(value, dict) or not isinstance(witness, dict)
            or exclusion.get("server_uuid") != scope["server_uuid"]
            or exclusion.get("connector_server_id") != scope["connector_server_id"]
            or not isinstance(witness.get("file"), str) or not witness["file"]
            or value.get("file") != witness["file"] or exclusion.get("binlog_file") != witness["file"]
            or any(not _is_int(witness.get(key)) for key in ("start", "end", "commit_pos"))
            or not _is_int(value.get("pos")) or not _is_int(exclusion.get("binlog_position"))
            or not _witness_ordered(checkpoint, witness)
            or not 4 <= witness["start"] < witness["end"] <= exclusion["binlog_position"]
            or not witness["start"] <= witness["commit_pos"] <= witness["end"]
            or witness["commit_pos"] != value["pos"]):
        raise RuntimeBlocked(BLOCKED)
    if scope["lineage_mode"] == "gtid" and (not isinstance(value.get("gtids"), str) or not value["gtids"]):
        raise RuntimeBlocked(BLOCKED)
    return checkpoint


_LSN = re.compile(r"[0-9a-f]{8}:[0-9a-f]{8}:[0-9a-f]{4}")


def _lsn(value):
    if not isinstance(value, str) or not _LSN.fullmatch(value):
        raise RuntimeBlocked(BLOCKED)
    return value


def confirm_mssql(evidence, scope, *, data_topics, data_partitions):
    """Commit and change LSN of the CDC log, bounded by the maximum LSN proven under exclusion."""
    checkpoint, exclusion = _transport(evidence, scope, data_topics, data_partitions)
    value = checkpoint.get("value")
    witness = checkpoint.get("lsn_witness")
    if (not isinstance(value, dict) or not isinstance(witness, dict)
            or exclusion.get("database") != scope["database"]
            or not isinstance(exclusion.get("capture_instances"), list) or not exclusion["capture_instances"]
            or any(not isinstance(name, str) or not name for name in exclusion["capture_instances"])
            or not _witness_ordered(checkpoint, witness)):
        raise RuntimeBlocked(BLOCKED)
    commit, change, maximum, proven = (_lsn(value.get("commit_lsn")), _lsn(witness.get("change_lsn")),
                                       _lsn(witness.get("max_lsn")), _lsn(exclusion.get("max_lsn")))
    # Fixed-width lowercase hex makes lexical order equal numeric LSN order.
    if (witness.get("commit_lsn") != commit or value.get("change_lsn") != change
            or not change <= commit <= maximum <= proven):
        raise RuntimeBlocked(BLOCKED)
    return checkpoint


def _scn(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,38}", value):
        return int(value)
    if _is_int(value) and value > 0:
        return value
    raise RuntimeBlocked(BLOCKED)


def confirm_oracle(evidence, scope, *, data_topics, data_partitions):
    """SCN and commit SCN of the mined redo, bounded by the flushed SCN proven under exclusion."""
    checkpoint, exclusion = _transport(evidence, scope, data_topics, data_partitions)
    value = checkpoint.get("value")
    witness = checkpoint.get("scn_witness")
    if (not isinstance(value, dict) or not isinstance(witness, dict)
            or exclusion.get("container") != scope["database"]
            or not _is_int(witness.get("redo_thread")) or witness["redo_thread"] < 1
            or not _witness_ordered(checkpoint, witness)):
        raise RuntimeBlocked(BLOCKED)
    scn, commit = _scn(value.get("scn")), _scn(value.get("commit_scn"))
    flushed = _scn(exclusion.get("flushed_scn"))
    if (_scn(witness.get("scn")) != scn or _scn(witness.get("commit_scn")) != commit
            or not 0 < scn <= commit <= flushed):
        raise RuntimeBlocked(BLOCKED)
    return checkpoint
