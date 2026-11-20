"""Pinned PostgreSQL pgoutput profile; no automatic publication or slot DDL."""

import json
import re

import psycopg

from backend.core.secrets import decrypt_secret
from backend.metadata.capture.runtime_store import RuntimeBlocked


class PostgreSQLCaptureProfile:
    def __init__(self, *, scope, tls, connect=psycopg.connect):
        self.scope = scope
        self.tls = tls
        self.connect = connect
        required = {"source_id", "connector_name", "host", "port", "database", "tables",
                    "publication", "slot", "topic_prefix", "server_version_num"}
        if (set(scope) - {"snapshot", "transaction_metadata"} != required or set(tls) != {"sslmode", "sslrootcert"}
                or tls.get("sslmode") != "verify-full"
                or not tls.get("sslrootcert") or not scope["tables"]
                or any(not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", scope[k])
                       for k in ("publication", "slot"))
                or any(not re.fullmatch(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*", t)
                       for t in scope["tables"])):
            raise RuntimeBlocked("explicit_postgresql_profile_required")
        self.snapshot = scope.get("snapshot")
        if "transaction_metadata" in scope and (scope["transaction_metadata"] is not True or self.snapshot is None):
            raise RuntimeBlocked("explicit_transaction_metadata_profile_required")
        if "snapshot" in scope:
            snapshot = self.snapshot
            if (not isinstance(snapshot, dict) or set(snapshot) != {
                    "signal_table", "signal_relation_identity", "notification_topic", "notification_partition",
                } or scope["server_version_num"] != 180006
                    or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}\.[a-z_][a-z0-9_]{0,62}", snapshot["signal_table"])
                    or snapshot["signal_table"] in scope["tables"]
                    or not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", snapshot["signal_relation_identity"])
                    or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,249}", snapshot["notification_topic"])
                    or snapshot["notification_topic"] in {".", ".."}
                    or snapshot["notification_topic"] in {
                        f'{scope["topic_prefix"]}.{table}' for table in [*scope["tables"], snapshot["signal_table"]]
                    }):
                raise RuntimeBlocked("explicit_snapshot_profile_required")

    def validate_source(self, source):
        p = self.scope
        tables = self.included_tables
        if source.engine != "postgresql" or source.id != p["source_id"]:
            raise RuntimeBlocked("postgresql_scope_mismatch")
        try:
            access = json.loads(decrypt_secret(source.access_ciphertext))
            if (any(access.get(k) != p[k] for k in ("host", "port", "database"))
                    or any(table.split(".")[0] != access.get("schema") for table in p["tables"])):
                raise ValueError()
            credential = json.loads(decrypt_secret(source.capture_credential_ciphertext))
            with self.connect(host=p["host"], port=p["port"], dbname=p["database"],
                              user=credential["username"], password=credential["password"],
                              connect_timeout=10, options="-c statement_timeout=10000",
                              **self.tls) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT current_database(), current_setting('wal_level'), "
                                   "current_setting('server_version_num')::int, rolreplication, "
                                   "rolsuper FROM pg_roles WHERE rolname = current_user")
                    database, wal, version, replication, superuser = cursor.fetchone()
                    if (database != p["database"] or wal != "logical"
                            or version != p["server_version_num"] or not replication or superuser):
                        raise ValueError()
                    cursor.execute("SELECT puballtables, pubinsert, pubupdate, pubdelete, pubtruncate "
                                   "FROM pg_publication WHERE pubname = %s", (p["publication"],))
                    if cursor.fetchone() != (False, True, True, True, True):
                        raise ValueError()
                    cursor.execute("""
                        SELECT published.schemaname || '.' || published.tablename,
                               published.rowfilter IS NOT NULL, published.attnames,
                               attributes.names, attributes.has_generated
                        FROM pg_catalog.pg_publication_tables AS published
                        JOIN pg_catalog.pg_namespace AS namespace ON namespace.nspname = published.schemaname
                        JOIN pg_catalog.pg_class AS relation
                          ON relation.relnamespace = namespace.oid AND relation.relname = published.tablename
                        CROSS JOIN LATERAL (
                            SELECT array_agg(attname) AS names, bool_or(attgenerated <> '') AS has_generated
                            FROM pg_catalog.pg_attribute
                            WHERE attrelid = relation.oid AND attnum > 0 AND NOT attisdropped
                        ) AS attributes
                        WHERE published.pubname = %s
                        LIMIT %s
                    """, (p["publication"], len(tables) + 1))
                    published_tables = cursor.fetchall()
                    if (len(published_tables) != len(tables)
                            or {row[0] for row in published_tables} != set(tables)):
                        raise ValueError()
                    for _, filtered, published_columns, live_columns, has_generated in published_tables:
                        if (filtered is not False or has_generated is not False
                                or not published_columns or not live_columns
                                or set(published_columns) != set(live_columns)):
                            raise ValueError()
                    cursor.execute("SELECT plugin, database, active FROM pg_replication_slots "
                                   "WHERE slot_name = %s", (p["slot"],))
                    slot = cursor.fetchone()
                    if slot is not None and slot[:2] != ("pgoutput", p["database"]):
                        raise ValueError()
                    for table in p["tables"]:
                        cursor.execute("SELECT has_table_privilege(current_user, %s, 'SELECT')", (table,))
                        if cursor.fetchone() != (True,):
                            raise ValueError()
                    if self.snapshot is not None:
                        self._validate_signal_relation(cursor)
        except Exception:
            raise RuntimeBlocked("postgresql_readiness_unconfirmed") from None

    @property
    def included_tables(self):
        return [*self.scope["tables"], self.snapshot["signal_table"]] if self.snapshot else self.scope["tables"]

    def _validate_signal_relation(self, cursor):
        cursor.execute("""
            SELECT database.oid || ':' || relation.oid,
                   has_table_privilege(relation.oid, 'SELECT'), has_table_privilege(relation.oid, 'INSERT'),
                   array_agg(attribute.attname ORDER BY attribute.attnum),
                   bool_and(attribute.atttypid IN ('text'::regtype, 'varchar'::regtype)),
                   EXISTS (SELECT FROM pg_catalog.pg_constraint AS key
                           WHERE key.conrelid = relation.oid AND key.contype = 'p'
                             AND NOT key.condeferrable
                             AND key.conkey = ARRAY[min(attribute.attnum) FILTER (WHERE attribute.attname = 'id')])
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_attribute AS attribute ON attribute.attrelid = relation.oid
            CROSS JOIN pg_catalog.pg_database AS database
            WHERE database.datname = current_database() AND relation.oid = to_regclass(%s)
              AND relation.relkind = 'r' AND relation.relpersistence = 'p' AND NOT relation.relrowsecurity
              AND attribute.attnum > 0 AND NOT attribute.attisdropped
            GROUP BY database.oid, relation.oid
        """, (self.snapshot["signal_table"],))
        if cursor.fetchone() != (self.snapshot["signal_relation_identity"], True, True,
                                 ["id", "type", "data"], True, True):
            raise ValueError()

    def configuration(self, command, source, refs):
        self.validate_source(source)
        p = self.scope
        config = {
            "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
            "tasks.max": "1", "database.hostname": p["host"], "database.port": str(p["port"]),
            "database.dbname": p["database"], "database.user": refs["username"],
            "database.password": refs["password"], "database.sslmode": "verify-full",
            "database.sslrootcert": self.tls["sslrootcert"], "plugin.name": "pgoutput",
            "slot.name": p["slot"], "slot.drop.on.stop": "false",
            "publication.name": p["publication"], "publication.autocreate.mode": "disabled",
            "topic.prefix": p["topic_prefix"], "table.include.list": ",".join(
                re.escape(table) for table in self.included_tables),
            "snapshot.mode": "no_data", "tombstones.on.delete": "false",
            "decimal.handling.mode": "precise",
        }
        if self.snapshot is not None:
            config.update({
                "signal.enabled.channels": "source",
                "signal.data.collection": self.snapshot["signal_table"],
                "incremental.snapshot.watermarking.strategy": "insert_insert",
                "notification.enabled.channels": "sink",
                "notification.sink.topic.name": self.snapshot["notification_topic"],
            })
        if p.get("transaction_metadata"):
            config["provide.transaction.metadata"] = "true"
        return config
