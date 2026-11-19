"""Administrative target installer. Serving identities never execute this DDL."""

import argparse
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
                      partition_identity: PartitionIdentity, start_offset: int):
    """Admin-only allocation after profile/key admission; start offset is the last covered offset."""
    if not re.fullmatch(r"mir_[a-f0-9]{32}", mirror_id) or not re.fullmatch(r"[a-f0-9]{32}", generation_id):
        raise ValueError("Target ids must match management mirror and generation identities")
    if partition_identity.partition != 0 or start_offset < -1:
        raise ValueError("Only admitted single-partition contiguous delivery is supported")
    if not key_columns or not set(key_columns) <= columns.keys() or not columns:
        raise ValueError("Admitted key columns required")
    for name, native_type in columns.items():
        if not name or len(name.encode()) > 63 or "\x00" in name:
            raise ValueError("Persist an ordinal column mapping before allocation")
        if native_type not in TYPES and not re.fullmatch(r"numeric\([1-9][0-9]{0,2},[0-9]{1,3}\)", native_type):
            raise ValueError("Unsupported native target type")
    # Two full ids exceed PostgreSQL's identifier limit. The mirror prefix plus full
    # generation remains generated, collision-detected by the registry unique key.
    table_name = f"m_{mirror_id[4:20]}_{generation_id}"
    definitions = [sql.SQL("{} {} {}").format(sql.Identifier(name), sql.SQL(native_type),
                   sql.SQL("NOT NULL" if name in key_columns else "")) for name, native_type in columns.items()]
    definitions.append(sql.SQL("PRIMARY KEY ({})").format(sql.SQL(", ").join(map(sql.Identifier, key_columns))))
    with connection.transaction():
        connection.execute("SET LOCAL ROLE refraq_mirror_owner")
        connection.execute(
            "INSERT INTO source_mirror_state.mirrors(id, source_id, table_identity, authority, history_epoch) "
            "VALUES (%s,%s,%s,%s::jsonb,%s) ON CONFLICT DO NOTHING",
            (mirror_id, authority.source_id, table_identity, json.dumps(asdict(authority)), history_epoch))
        mirror = connection.execute("SELECT source_id, table_identity, authority FROM source_mirror_state.mirrors WHERE id = %s FOR UPDATE", (mirror_id,)).fetchone()
        if mirror != (authority.source_id, table_identity, asdict(authority)):
            raise ValueError("Mirror immutable binding or authority mismatch")
        if connection.execute("SELECT 1 FROM source_mirror_state.generations WHERE id = %s", (generation_id,)).fetchone():
            raise ValueError("Generation already allocated; recover its durable operation instead")
        connection.execute(sql.SQL("CREATE TABLE source_mirror.{} ({})").format(sql.Identifier(table_name), sql.SQL(", ").join(definitions)))
        connection.execute(
            "INSERT INTO source_mirror_state.generations VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'building',false)",
            (generation_id, mirror_id, authority.capture_generation, operation_id, table_name,
             schema_fingerprint, list(key_columns), list(columns), json.dumps(asdict(partition_identity)), start_offset))


def install_authority(connection, *, mirror_id, expected_authority, authority, exclusion_proof, verify_exclusion):
    """The deployer's trusted verifier must establish old-producer exclusion."""
    verify_exclusion(expected_authority, authority, exclusion_proof)
    if authority.owner_epoch < expected_authority.owner_epoch:
        raise ValueError("Stale owner epoch")
    if authority != expected_authority and authority.owner_epoch == expected_authority.owner_epoch:
        if (authority.runtime_instance_id != expected_authority.runtime_instance_id
                or authority.control_revision <= expected_authority.control_revision):
            raise ValueError("Stale authority revision")
    with connection.transaction():
        connection.execute("SET LOCAL ROLE refraq_mirror_owner")
        current = connection.execute("SELECT authority FROM source_mirror_state.mirrors WHERE id = %s FOR UPDATE", (mirror_id,)).fetchone()
        if current != (asdict(expected_authority),):
            raise ValueError("Mirror authority changed")
        if (authority.source_id, authority.resource_binding_id) != (expected_authority.source_id, expected_authority.resource_binding_id):
            raise ValueError("Immutable resource binding mismatch")
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
