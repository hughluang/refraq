"""Administrative target installer. Serving identities never execute this DDL."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re

import psycopg
from psycopg import sql

from backend.metadata.mirrors.types import Authority, PartitionIdentity
from dataclasses import asdict


VERSION = 1
ROLES = ("refraq_mirror_owner", "refraq_mirror_applier", "refraq_mirror_gateway")
TYPES = {"bigint", "integer", "smallint", "boolean", "text", "uuid", "date", "bytea", "jsonb", "timestamp", "timestamptz"}
FUNCTIONS = {
    "apply_batch(jsonb,text,jsonb,jsonb)": "refraq_mirror_applier",
    "delivery_metadata(text)": "refraq_mirror_applier",
    "publish_generation(text,jsonb,text,jsonb)": "refraq_mirror_applier",
    "observe_committed_publication(text,text,text,jsonb,text)": "refraq_mirror_applier",
    "acquire_pin(text,text)": "refraq_mirror_gateway",
    "resolve_source(text)": "refraq_mirror_gateway",
    "read_page(text,text,jsonb,integer)": "refraq_mirror_gateway",
    "release_run_pins(text)": "refraq_mirror_gateway",
    "history_version()": "refraq_mirror_gateway",
    "history_bound(text)": "refraq_mirror_gateway",
    "history_page(text,jsonb,jsonb,integer)": "refraq_mirror_gateway",
    "invalidate_history(text,jsonb)": "refraq_mirror_applier",
}


def install(connection):
    with connection.transaction():
        for role in ROLES:
            existing = connection.execute(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication, rolinherit, rolcanlogin "
                "FROM pg_roles WHERE rolname = %s", (role,)
            ).fetchone()
            expected = (False, False, False, False, False, False, role != ROLES[0])
            if existing is not None and tuple(existing) != expected:
                raise ValueError("Mirror role configuration mismatch")
            if existing is None:
                connection.execute(sql.SQL("CREATE ROLE {} {} NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION NOINHERIT").format(
                    sql.Identifier(role), sql.SQL("NOLOGIN" if role == ROLES[0] else "LOGIN")))
            if connection.execute(
                "SELECT 1 FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname = %s)", (role,)
            ).fetchone():
                raise ValueError("Mirror roles must not inherit memberships")
        for schema in ("source_mirror", "source_mirror_state"):
            connection.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} AUTHORIZATION refraq_mirror_owner").format(sql.Identifier(schema)))
            owner = connection.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone()[0]
            if owner != ROLES[0]:
                raise ValueError("Mirror schema owner mismatch")
            connection.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM PUBLIC, refraq_mirror_applier, refraq_mirror_gateway").format(sql.Identifier(schema)))
        connection.execute("SET LOCAL ROLE refraq_mirror_owner")
        marker = connection.execute("SELECT to_regclass('source_mirror_state.version')").fetchone()[0]
        if marker and connection.execute("SELECT version FROM source_mirror_state.version").fetchone() != (VERSION,):
            raise ValueError("Mirror target version mismatch")
        connection.execute(Path(__file__).with_name("target.sql").read_text())
        connection.execute(Path(__file__).with_name("history.sql").read_text())
        connection.execute("REVOKE ALL ON ALL TABLES IN SCHEMA source_mirror, source_mirror_state FROM PUBLIC, refraq_mirror_applier, refraq_mirror_gateway")
        connection.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA source_mirror_state FROM PUBLIC, refraq_mirror_applier, refraq_mirror_gateway")
        connection.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA source_mirror_state REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC")
        connection.execute("GRANT USAGE ON SCHEMA source_mirror_state TO refraq_mirror_applier, refraq_mirror_gateway")
        connection.execute("GRANT EXECUTE ON FUNCTION source_mirror_state.target_version() TO refraq_mirror_applier, refraq_mirror_gateway")
        for signature, role in FUNCTIONS.items():
            connection.execute(sql.SQL("GRANT EXECUTE ON FUNCTION source_mirror_state.{} TO {}").format(sql.SQL(signature), sql.Identifier(role)))


def create_generation(connection, *, mirror_id: str, generation_id: str, authority: Authority,
                      table_identity: str, history_epoch: str, operation_id: str,
                      schema_fingerprint: str, columns: dict[str, str], key_columns: tuple[str, ...],
                      partition_identity: PartitionIdentity, start_offset: int,
                      require_prepared_fence: bool = False) -> str:
    """Allocate or recover an exact binding in an admin-owned target transaction.

    Managed opens require a preinstalled mirror row for the exact mirror, Source,
    catalog table, history epoch and accepted Authority. Authority includes the
    Source binding, owner term and runtime, control and credential revisions, and
    capture lineage. The deployment adapter installs the fence and supplies an idle
    administrative connection so this function can commit the allocation itself.
    """
    if require_prepared_fence and connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise ValueError("Managed generation allocation requires a top-level target transaction")
    if not re.fullmatch(r"mir_[a-f0-9]{32}", mirror_id) or not re.fullmatch(r"[a-f0-9]{32}", generation_id):
        raise ValueError("Target ids must match management mirror and generation identities")
    if partition_identity.partition != 0 or start_offset < -1:
        raise ValueError("Only admitted single-partition contiguous delivery is supported")
    if not key_columns or len(set(key_columns)) != len(key_columns) or not set(key_columns) <= columns.keys():
        raise ValueError("Admitted key columns required")
    native_types = []
    type_aliases = {"timestamp": "timestamp without time zone", "timestamptz": "timestamp with time zone"}
    for name, native_type in columns.items():
        if not name or len(name.encode()) > 63 or "\x00" in name:
            raise ValueError("Persist an ordinal column mapping before allocation")
        numeric = re.fullmatch(r"numeric\(([1-9][0-9]{0,2}),([0-9]{1,3})\)", native_type)
        if native_type not in TYPES and not numeric:
            raise ValueError("Unsupported native target type")
        canonical_type = (f"numeric({int(numeric[1])},{int(numeric[2])})" if numeric
                          else type_aliases.get(native_type, native_type))
        native_types.append((name, canonical_type, name in key_columns))
    # Two full ids exceed PostgreSQL's identifier limit. The mirror prefix plus full
    # generation remains generated, collision-detected by the registry unique key.
    table_name = f"m_{mirror_id[4:20]}_{generation_id}"
    target_table = sql.Identifier("source_mirror", table_name)
    authority_data = asdict(authority)
    partition_data = asdict(partition_identity)
    allocation_stamp = json.dumps(dict(authority=authority_data, history_epoch=history_epoch,
                                       start_offset=start_offset, native_types=native_types), sort_keys=True)
    generation = (generation_id, mirror_id, authority.capture_generation, operation_id, table_name,
                  schema_fingerprint, list(key_columns), list(columns), partition_data)
    definitions = [sql.SQL("{} {} {}").format(sql.Identifier(name), sql.SQL(native_type),
                   sql.SQL("NOT NULL" if name in key_columns else "")) for name, native_type in columns.items()]
    definitions.append(sql.SQL("PRIMARY KEY ({})").format(sql.SQL(", ").join(map(sql.Identifier, key_columns))))
    with connection.transaction():
        connection.execute("SET LOCAL ROLE refraq_mirror_owner")
        if not require_prepared_fence:
            connection.execute(
                "INSERT INTO source_mirror_state.mirrors(id, source_id, table_identity, authority, history_epoch) "
                "VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
                (mirror_id, authority.source_id, table_identity, json.dumps(authority_data), history_epoch))
        mirror = connection.execute(
            sql.SQL("SELECT source_id, table_identity, authority FROM source_mirror_state.mirrors "
                    "WHERE id = %s AND history_epoch = {} FOR UPDATE").format(sql.Literal(history_epoch)),
            (mirror_id,)).fetchone()
        if mirror != (authority.source_id, table_identity, authority_data):
            raise ValueError("Mirror fence or immutable binding mismatch")
        existing = connection.execute(
            "SELECT id, mirror_id, capture_generation, operation_id, table_name, schema_fingerprint, "
            "key_columns, column_names, partition_identity, status, cleanup_pending FROM source_mirror_state.generations "
            "WHERE id = %s OR operation_id = %s", (generation_id, operation_id)).fetchone()
        if existing is not None:
            if existing[:-2] != generation:
                raise ValueError("Generation allocation binding mismatch")
            if existing[-2] == "retired" or existing[-1]:
                raise ValueError("Generation allocation binding is retired or pending cleanup")
            relation = connection.execute(
                "SELECT oid, obj_description(oid, 'pg_class') FROM pg_class "
                "WHERE relnamespace = 'source_mirror'::regnamespace AND relname = %s "
                "AND relkind = 'r' AND relowner = 'refraq_mirror_owner'::regrole", (table_name,)).fetchone()
            if relation is None or relation[1] != allocation_stamp:
                raise ValueError("Generation allocation binding unconfirmed")
            relation_id = relation[0]
            actual_types = connection.execute(
                "SELECT attname, format_type(atttypid, atttypmod), attnotnull FROM pg_attribute "
                "WHERE attrelid = %s AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
                (relation_id,)).fetchall()
            actual_key = connection.execute(
                "SELECT array_agg(a.attname::text ORDER BY k.ordinality) FROM pg_constraint c "
                "CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) "
                "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
                "WHERE c.conrelid = %s AND c.contype = 'p'", (relation_id,)).fetchone()
            if actual_types != native_types or actual_key != (list(key_columns),):
                raise ValueError("Generation allocation schema binding mismatch")
        else:
            try:
                connection.execute(
                    "INSERT INTO source_mirror_state.generations "
                    "(id, mirror_id, capture_generation, operation_id, table_name, schema_fingerprint, "
                    "key_columns, column_names, partition_identity, applied_offset, status, cleanup_pending) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'building',false)",
                    (*generation[:-1], json.dumps(partition_data), start_offset))
            except psycopg.errors.UniqueViolation as exc:
                raise ValueError("Generation allocation binding conflict") from exc
            connection.execute(sql.SQL("CREATE TABLE {} ({})").format(target_table, sql.SQL(", ").join(definitions)))
            connection.execute(sql.SQL("COMMENT ON TABLE {} IS {}").format(target_table, sql.Literal(allocation_stamp)))
    return generation_id


def _check_authority_transition(expected_authority, authority):
    if (authority.source_id, authority.resource_binding_id) != (expected_authority.source_id, expected_authority.resource_binding_id):
        raise ValueError("Immutable resource binding mismatch")
    if authority.owner_epoch < expected_authority.owner_epoch:
        raise ValueError("Stale owner epoch")
    if authority != expected_authority and authority.owner_epoch == expected_authority.owner_epoch:
        if (authority.runtime_instance_id != expected_authority.runtime_instance_id
                or authority.control_revision <= expected_authority.control_revision):
            raise ValueError("Stale authority revision")


def prepare_authority(connection, *, mirror_id, table_identity, history_epoch, operation_id,
                      expected_authority, authority, exclusion_proof, verify_exclusion):
    """Commit or recover an exact target fence through the privileged deployment adapter."""
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise ValueError("Fence preparation requires a top-level target transaction")
    if (not re.fullmatch(r"mir_[a-f0-9]{32}", mirror_id) or not table_identity or not history_epoch
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", operation_id) or authority.owner_epoch < 1
            or not all((authority.source_id, authority.resource_binding_id, authority.runtime_instance_id,
                        authority.capture_generation))):
        raise ValueError("Incomplete fence identity")
    if expected_authority is not None:
        if expected_authority == authority:
            raise ValueError("Fence preparation requires a new authority")
        _check_authority_transition(expected_authority, authority)
    if verify_exclusion(expected_authority, authority, exclusion_proof) is not True:
        raise ValueError("Producer exclusion unverified")
    candidate = asdict(authority)
    previous = asdict(expected_authority) if expected_authority is not None else None
    request = dict(mirror_id=mirror_id, table_identity=table_identity, history_epoch=history_epoch,
                   operation_id=operation_id, expected_authority=previous, authority=candidate)
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":"))
    receipt_ref = "sha256:" + sha256(encoded.encode()).hexdigest()
    identity = (authority.source_id, table_identity, history_epoch)
    with connection.transaction():
        connection.execute("SET LOCAL ROLE refraq_mirror_owner")
        inserted = False
        if previous is None:
            inserted = connection.execute(
                "INSERT INTO source_mirror_state.mirrors(id, source_id, table_identity, history_epoch, authority) "
                "VALUES (%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING",
                (mirror_id, *identity, json.dumps(candidate)),
            ).rowcount == 1
        current = connection.execute(
            "SELECT source_id, table_identity, history_epoch, authority FROM source_mirror_state.mirrors "
            "WHERE id = %s FOR UPDATE", (mirror_id,),
        ).fetchone()
        if current is None or current[:3] != identity:
            raise ValueError("Mirror fence identity mismatch")
        receipt = connection.execute(
            "SELECT request, receipt_ref FROM source_mirror_state.fence_receipts WHERE mirror_id = %s AND operation_id = %s",
            (mirror_id, operation_id),
        ).fetchone()
        if receipt is not None:
            if receipt != (request, receipt_ref) or current[3] != candidate:
                raise ValueError("Fence receipt is no longer exact")
        else:
            if not inserted:
                if previous is None or current[3] != previous:
                    raise ValueError("Mirror authority changed")
                connection.execute("UPDATE source_mirror_state.mirrors SET authority = %s::jsonb WHERE id = %s",
                                   (json.dumps(candidate), mirror_id))
            connection.execute("INSERT INTO source_mirror_state.fence_receipts VALUES (%s,%s,%s::jsonb,%s)",
                               (mirror_id, operation_id, encoded, receipt_ref))
    return receipt_ref


def install_authority(connection, *, mirror_id, expected_authority, authority, exclusion_proof, verify_exclusion):
    """The deployer's trusted verifier must establish old-producer exclusion."""
    verify_exclusion(expected_authority, authority, exclusion_proof)
    _check_authority_transition(expected_authority, authority)
    with connection.transaction():
        connection.execute("SET LOCAL ROLE refraq_mirror_owner")
        current = connection.execute("SELECT authority FROM source_mirror_state.mirrors WHERE id = %s FOR UPDATE", (mirror_id,)).fetchone()
        if current != (asdict(expected_authority),):
            raise ValueError("Mirror authority changed")
        connection.execute("UPDATE source_mirror_state.mirrors SET authority = %s::jsonb WHERE id = %s", (json.dumps(asdict(authority)), mirror_id))


def validate_target(connection, *, expected_role):
    if expected_role not in ROLES[1:]:
        raise ValueError("Serving requires a restricted mirror role")
    current = connection.execute("SELECT current_user").fetchone()[0]
    if current != expected_role:
        raise ValueError("Mirror serving identity mismatch")
    role = connection.execute("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication FROM pg_roles WHERE rolname = current_user").fetchone()
    if any(role):
        raise ValueError("Privileged mirror serving identity")
    # Version is deliberately not exposed as a raw table grant.
    if connection.execute("SELECT source_mirror_state.target_version()").fetchone() != (VERSION,):
        raise ValueError("Mirror target version mismatch")


def main():
    parser = argparse.ArgumentParser(description="Install Metadata-owned mirror target using administrative credentials")
    parser.add_argument("--admin-url-env", required=True, help="Name of a protected environment variable; never a credential value")
    args = parser.parse_args()
    with psycopg.connect(os.environ[args.admin_url_env]) as connection:
        install(connection)


if __name__ == "__main__":
    main()
