"""Entity database bootstrap: roles, schemas, acl functions, profile page, table move, RLS.

Run with ``python -m backend.entity.bootstrap``. Connects with
``ENTITY_ADMIN_DATABASE_URL`` only; runtime processes never read that URL.
The login roles take their passwords from ``ENTITY_DATABASE_URL`` (owner),
``ENTITY_READER_DATABASE_URL`` (reader), and ``ENTITY_SIGNER_DATABASE_URL``
(signer), so the live ``.env`` holds each secret once. Every run converges
the database to the same state and is safe to repeat.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url

from backend.core.config import Settings
from backend.entity.change_log import ensure_shared_relations
from backend.entity.data.capabilities import (
    FILTER_DEPTH_MAX,
    FILTER_IN_VALUES_MAX,
    FILTER_LEAVES_MAX,
    OFFSET_MAX,
    PAGE_LIMIT_MAX,
)
from backend.entity.ddl import (
    ACL_OWNER_ROLE,
    ACL_SCHEMA,
    CHANNEL_DATASET_SCHEMA,
    ENTITY_ACCESS_SCHEMA,
    ENTITY_CHANGE_LOG_SCHEMA,
    ENTITY_DATA_SCHEMA,
    ENTITY_OWNER_ROLE,
    EXPOSURE_OWNER_ROLE,
    EXPOSURE_POLICY,
    OWNER_POLICY,
    READER_ROLE,
    SIGNER_ROLE,
    ident,
    qualified_table,
    table_security_statements,
    view_security_statements,
)

__all__ = [
    "BootstrapPlanError",
    "acl_statements",
    "database_statements",
    "ensure_database",
    "main",
    "move_statements",
    "profile_page_statements",
    "retire_channel_reader_statements",
    "role_statements",
    "run_bootstrap",
    "schema_statements",
    "secure_existing_table_statements",
]

MIN_SERVER_VERSION_NUM = 180000
READER_STATEMENT_TIMEOUT = "30s"
READER_LOCK_TIMEOUT = "5s"
READER_IDLE_IN_TRANSACTION_TIMEOUT = "60s"
LEGACY_SCHEMA_DEFAULT = "public"

_ADVISORY_LOCK_KEY = 0x72656672_656E7462  # "refr" "entb"
_PHYSICAL_TABLE_RE = re.compile(r"__v[0-9]+__[0-9a-f]{16}$")
_PHYSICAL_TABLE_SQL_RE = "__v[0-9]+__[0-9a-f]{16}$"


class BootstrapPlanError(RuntimeError):
    """The target database or the supplied URLs cannot be bootstrapped."""


class BootstrapSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Settings.model_config.get("env_file"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    admin_url: str | None = Field(default=None, validation_alias="ENTITY_ADMIN_DATABASE_URL")
    owner_url: str | None = Field(default=None, validation_alias="ENTITY_DATABASE_URL")
    reader_url: str | None = Field(
        default=None, validation_alias="ENTITY_READER_DATABASE_URL"
    )
    signer_url: str | None = Field(
        default=None, validation_alias="ENTITY_SIGNER_DATABASE_URL"
    )


def _literal(value: str) -> str:
    if "\x00" in value:
        raise BootstrapPlanError("role password must not contain NUL")
    return "'" + value.replace("'", "''") + "'"


_RETIRED_CHANNEL_READER = "refraq_channel_reader"


def role_statements(
    *,
    owner_password: str,
    reader_password: str,
    signer_password: str,
    existing: frozenset[str],
) -> list[str]:
    """Create or converge the entity roles. Passwords are SQL literals; never log them.

    The signer is a login that may insert a signing key, so it does not take
    the reader's read-only default transaction.
    """
    common = "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
    specs = (
        (ENTITY_OWNER_ROLE, f"LOGIN {common} NOINHERIT", owner_password),
        (EXPOSURE_OWNER_ROLE, f"NOLOGIN {common} NOINHERIT", None),
        (ACL_OWNER_ROLE, f"NOLOGIN {common} NOINHERIT", None),
        (READER_ROLE, f"LOGIN {common} NOINHERIT", reader_password),
        (SIGNER_ROLE, f"LOGIN {common} NOINHERIT", signer_password),
    )
    statements: list[str] = []
    for role, attributes, password in specs:
        verb = "ALTER ROLE" if role in existing else "CREATE ROLE"
        secret = f" PASSWORD {_literal(password)}" if password is not None else ""
        statements.append(f"{verb} {ident(role)} WITH {attributes}{secret}")
    reader = ident(READER_ROLE)
    statements += [
        f"ALTER ROLE {reader} SET default_transaction_read_only = on",
        f"ALTER ROLE {reader} SET statement_timeout = {_literal(READER_STATEMENT_TIMEOUT)}",
        f"ALTER ROLE {reader} SET lock_timeout = {_literal(READER_LOCK_TIMEOUT)}",
        "ALTER ROLE "
        f"{reader} SET idle_in_transaction_session_timeout = "
        f"{_literal(READER_IDLE_IN_TRANSACTION_TIMEOUT)}",
        f"GRANT {ident(EXPOSURE_OWNER_ROLE)} TO {ident(ENTITY_OWNER_ROLE)} "
        "WITH INHERIT FALSE, SET TRUE",
    ]
    return statements


def retire_channel_reader_statements(existing: frozenset[str]) -> list[str]:
    """Drop the retired channel-reader login after revoking what it holds here."""
    if _RETIRED_CHANNEL_READER not in existing:
        return []
    role = ident(_RETIRED_CHANNEL_READER)
    return [f"DROP OWNED BY {role}", f"DROP ROLE {role}"]


def database_statements(database: str, *, has_public_schema: bool) -> list[str]:
    db = ident(database)
    statements = [
        f"REVOKE ALL ON DATABASE {db} FROM PUBLIC",
        f"GRANT CONNECT ON DATABASE {db} TO {ident(ENTITY_OWNER_ROLE)}, "
        f"{ident(READER_ROLE)}, {ident(SIGNER_ROLE)}",
    ]
    if has_public_schema:
        statements.append("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    return statements


def schema_statements() -> list[str]:
    owner = ident(ENTITY_OWNER_ROLE)
    exposure = ident(EXPOSURE_OWNER_ROLE)
    reader = ident(READER_ROLE)
    signer = ident(SIGNER_ROLE)
    data = ident(ENTITY_DATA_SCHEMA)
    access = ident(ENTITY_ACCESS_SCHEMA)
    acl = ident(ACL_SCHEMA)
    dataset = ident(CHANNEL_DATASET_SCHEMA)
    change_log = ident(ENTITY_CHANGE_LOG_SCHEMA)
    return [
        f"CREATE SCHEMA IF NOT EXISTS {data} AUTHORIZATION {owner}",
        f"CREATE SCHEMA IF NOT EXISTS {access} AUTHORIZATION {owner}",
        f"CREATE SCHEMA IF NOT EXISTS {acl} AUTHORIZATION {ident(ACL_OWNER_ROLE)}",
        f"CREATE SCHEMA IF NOT EXISTS {dataset} AUTHORIZATION {owner}",
        f"CREATE SCHEMA IF NOT EXISTS {change_log} AUTHORIZATION {owner}",
        f"ALTER SCHEMA {data} OWNER TO {owner}",
        f"ALTER SCHEMA {access} OWNER TO {owner}",
        f"ALTER SCHEMA {acl} OWNER TO {ident(ACL_OWNER_ROLE)}",
        f"ALTER SCHEMA {dataset} OWNER TO {owner}",
        f"ALTER SCHEMA {change_log} OWNER TO {owner}",
        f"REVOKE ALL ON SCHEMA {data}, {access}, {acl}, {change_log} FROM PUBLIC",
        f"REVOKE ALL ON SCHEMA {dataset} FROM PUBLIC",
        f"REVOKE ALL ON SCHEMA {data} FROM {reader}",
        f"REVOKE ALL ON SCHEMA {dataset} FROM {reader}",
        f"REVOKE ALL ON SCHEMA {change_log} FROM {reader}",
        f"REVOKE ALL ON SCHEMA {data}, {access}, {dataset}, {change_log} FROM {signer}",
        f"GRANT USAGE ON SCHEMA {data} TO {exposure}",
        f"GRANT USAGE, CREATE ON SCHEMA {access} TO {exposure}",
        f"GRANT USAGE ON SCHEMA {access} TO {reader}",
        f"GRANT USAGE ON SCHEMA {acl} TO {owner}, {exposure}, {reader}",
        f"REVOKE ALL ON SCHEMA {acl} FROM {signer}",
        f"GRANT USAGE ON SCHEMA {acl} TO {signer}",
    ]


_GUARD = "SECURITY DEFINER STABLE SET search_path = pg_catalog, pg_temp"

_READER_FUNCTIONS = (
    "acl.grant_active(text)",
    "acl.rev_ok(text, integer)",
    "acl.subject_text(text)",
    "acl.subject_text_array(text)",
    "acl.mask_partial(text, integer, integer)",
    "acl.mask_email(text)",
    "acl.mask_hash(text)",
    "acl.mask_redact(text)",
    "acl.mask_truncate_date(date, text)",
    "acl.mask_truncate_date(timestamp with time zone, text)",
    "acl.mask_bucket(bigint, numeric)",
    "acl.mask_bucket(numeric, numeric)",
    "acl.mask_bucket(double precision, numeric)",
)
_PRIVATE_FUNCTIONS = ("acl.ctx_payload()", "acl.subject_id()")
_OWNER_FUNCTIONS = (
    "acl.install_key(text, bytea)",
    "acl.ensure_signing_key()",
)

_FUNCTION_BODIES = (
    f"""
CREATE OR REPLACE FUNCTION acl.ctx_payload() RETURNS jsonb
LANGUAGE plpgsql {_GUARD} AS $fn$
DECLARE
  raw text := current_setting('app.ctx', true);
  dot integer;
  body bytea;
  payload jsonb;
  signing_secret bytea;
BEGIN
  IF raw IS NULL OR raw = '' THEN
    RETURN NULL;
  END IF;
  dot := strpos(raw, '.');
  IF dot < 2 THEN
    RETURN NULL;
  END IF;
  body := decode(substr(raw, 1, dot - 1), 'base64');
  payload := convert_from(body, 'UTF8')::jsonb;
  IF jsonb_typeof(payload) <> 'object' OR jsonb_typeof(payload -> 'kid') <> 'string'
     OR jsonb_typeof(payload -> 'exp') <> 'number' THEN
    RETURN NULL;
  END IF;
  SELECT k.secret INTO signing_secret
  FROM acl.signing_keys AS k WHERE k.kid = payload ->> 'kid';
  IF signing_secret IS NULL THEN
    RETURN NULL;
  END IF;
  IF encode(acl.hmac(body, signing_secret, 'sha256'), 'hex')
     <> lower(substr(raw, dot + 1)) THEN
    RETURN NULL;
  END IF;
  IF (payload ->> 'exp')::numeric <= extract(epoch FROM now()) THEN
    RETURN NULL;
  END IF;
  RETURN payload;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.subject_id() RETURNS text
LANGUAGE sql {_GUARD} AS $fn$
  SELECT CASE WHEN jsonb_typeof(p -> 'sub') = 'string' THEN p ->> 'sub' END
  FROM (SELECT acl.ctx_payload() AS p) AS c
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.grant_active(grant_id text) RETURNS boolean
LANGUAGE sql {_GUARD} AS $fn$
  SELECT COALESCE(
    jsonb_typeof(p -> 'grants') = 'array' AND (p -> 'grants') ? grant_id,
    false
  )
  FROM (SELECT acl.ctx_payload() AS p) AS c
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.rev_ok(entity_id text, rev integer) RETURNS boolean
LANGUAGE sql {_GUARD} AS $fn$
  SELECT COALESCE(
    jsonb_typeof(p -> 'rev' -> entity_id) = 'number'
      AND (p -> 'rev' -> entity_id) = to_jsonb(rev),
    false
  )
  FROM (SELECT acl.ctx_payload() AS p) AS c
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.subject_text(attr_key text) RETURNS text
LANGUAGE sql {_GUARD} AS $fn$
  SELECT CASE jsonb_typeof(p -> 'attrs' -> attr_key)
    WHEN 'string' THEN p -> 'attrs' ->> attr_key
    WHEN 'number' THEN p -> 'attrs' ->> attr_key
  END
  FROM (SELECT acl.ctx_payload() AS p) AS c
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.subject_text_array(attr_key text) RETURNS text[]
LANGUAGE sql {_GUARD} AS $fn$
  SELECT CASE jsonb_typeof(p -> 'attrs' -> attr_key)
    WHEN 'array' THEN ARRAY(
      SELECT e #>> '{{}}'
      FROM jsonb_array_elements(p -> 'attrs' -> attr_key) AS e
      WHERE jsonb_typeof(e) IN ('string', 'number')
    )
    WHEN 'string' THEN ARRAY[p -> 'attrs' ->> attr_key]
    WHEN 'number' THEN ARRAY[p -> 'attrs' ->> attr_key]
  END
  FROM (SELECT acl.ctx_payload() AS p) AS c
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.mask_partial(v text, keep_first integer, keep_last integer)
RETURNS text LANGUAGE sql STRICT {_GUARD} AS $fn$
  SELECT CASE
    WHEN length(v) <= kf + kl THEN repeat('*', length(v))
    ELSE left(v, kf) || repeat('*', length(v) - kf - kl) || right(v, kl)
  END
  FROM (SELECT least(greatest(keep_first, 0), 64) AS kf,
               least(greatest(keep_last, 0), 64) AS kl) AS k
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.mask_email(v text) RETURNS text
LANGUAGE sql STRICT {_GUARD} AS $fn$
  SELECT CASE
    WHEN strpos(v, '@') = 0 THEN left(v, 1) || '***'
    ELSE left(split_part(v, '@', 1), 1) || '***@' || substr(v, strpos(v, '@') + 1)
  END
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.mask_hash(v text) RETURNS text
LANGUAGE sql STRICT {_GUARD} AS $fn$
  SELECT encode(acl.hmac(convert_to(v, 'UTF8'), m.secret, 'sha256'), 'hex')
  FROM acl.mask_key AS m
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.mask_redact(v text) RETURNS text
LANGUAGE sql STRICT {_GUARD} AS $fn$
  SELECT '[redacted]'::text
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.mask_truncate_date(v date, unit text) RETURNS date
LANGUAGE sql STRICT {_GUARD} AS $fn$
  SELECT CASE WHEN unit IN ('year', 'month', 'day') THEN date_trunc(unit, v)::date END
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.mask_truncate_date(v timestamp with time zone, unit text)
RETURNS timestamp with time zone LANGUAGE sql STRICT {_GUARD} SET TimeZone = 'UTC'
AS $fn$
  SELECT CASE WHEN unit IN ('year', 'month', 'day') THEN date_trunc(unit, v) END
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.mask_bucket(v bigint, width numeric) RETURNS bigint
LANGUAGE sql STRICT {_GUARD} AS $fn$
  SELECT CASE
    WHEN width > 0 AND r BETWEEN -9223372036854775808 AND 9223372036854775807
    THEN r::bigint
  END
  FROM (SELECT CASE WHEN width > 0 THEN floor(v / width) * width END AS r) AS b
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.mask_bucket(v numeric, width numeric) RETURNS numeric
LANGUAGE sql STRICT {_GUARD} AS $fn$
  SELECT CASE WHEN width > 0 AND v <> 'NaN'::numeric THEN floor(v / width) * width END
$fn$
""",
    f"""
CREATE OR REPLACE FUNCTION acl.mask_bucket(v double precision, width numeric)
RETURNS double precision LANGUAGE sql STRICT {_GUARD} AS $fn$
  SELECT CASE
    WHEN width > 0 AND v NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)
    THEN (floor(v::numeric / width) * width)::float8
  END
$fn$
""",
    """
CREATE OR REPLACE FUNCTION acl.ensure_signing_key()
RETURNS TABLE (kid text, secret bytea)
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
  found_kid text;
  found_secret bytea;
BEGIN
  SELECT k.kid, k.secret INTO found_kid, found_secret
  FROM acl.signing_keys AS k
  ORDER BY k.installed_at DESC, k.slot DESC
  LIMIT 1;
  IF found_kid IS NULL THEN
    INSERT INTO acl.signing_keys (slot, kid, secret, installed_at)
    VALUES (1, 'k' || encode(acl.gen_random_bytes(8), 'hex'), acl.gen_random_bytes(32), now())
    ON CONFLICT (slot) DO NOTHING;
    SELECT k.kid, k.secret INTO found_kid, found_secret
    FROM acl.signing_keys AS k
    ORDER BY k.installed_at DESC, k.slot DESC
    LIMIT 1;
  END IF;
  kid := found_kid;
  secret := found_secret;
  RETURN NEXT;
END
$fn$
""",
    """
CREATE OR REPLACE FUNCTION acl.install_key(new_kid text, new_secret bytea) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
  target smallint;
BEGIN
  IF EXISTS (SELECT 1 FROM acl.signing_keys WHERE kid = new_kid) THEN
    IF EXISTS (
      SELECT 1 FROM acl.signing_keys WHERE kid = new_kid AND secret = new_secret
    ) THEN
      RETURN;
    END IF;
    RAISE EXCEPTION 'signing key id is already installed with another secret';
  END IF;
  SELECT s INTO target FROM (VALUES (1::smallint), (2::smallint)) AS v(s)
  WHERE NOT EXISTS (SELECT 1 FROM acl.signing_keys WHERE slot = v.s)
  ORDER BY s LIMIT 1;
  IF target IS NULL THEN
    SELECT slot INTO target FROM acl.signing_keys ORDER BY installed_at, slot LIMIT 1;
  END IF;
  INSERT INTO acl.signing_keys AS k (slot, kid, secret, installed_at)
  VALUES (target, new_kid, new_secret, now())
  ON CONFLICT (slot) DO UPDATE
    SET kid = EXCLUDED.kid, secret = EXCLUDED.secret, installed_at = EXCLUDED.installed_at;
END
$fn$
""",
)


def acl_statements(*, pgcrypto_schema: str | None) -> list[str]:
    """pgcrypto inside acl, key tables, and the SECURITY DEFINER functions."""
    acl = ident(ACL_SCHEMA)
    acl_owner = ident(ACL_OWNER_ROLE)
    statements: list[str] = []
    if pgcrypto_schema is None:
        statements.append(f"CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA {acl}")
    elif pgcrypto_schema != ACL_SCHEMA:
        statements.append(f"ALTER EXTENSION pgcrypto SET SCHEMA {acl}")
    statements += [
        "CREATE TABLE IF NOT EXISTS acl.signing_keys ("
        "slot smallint PRIMARY KEY CHECK (slot IN (1, 2)), "
        "kid text NOT NULL UNIQUE CHECK (kid ~ '^[A-Za-z0-9_-]{1,64}$'), "
        "secret bytea NOT NULL CHECK (octet_length(secret) >= 32), "
        "installed_at timestamptz NOT NULL DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS acl.mask_key ("
        "id boolean PRIMARY KEY DEFAULT true CHECK (id), "
        "secret bytea NOT NULL CHECK (octet_length(secret) >= 32))",
        "INSERT INTO acl.mask_key (id, secret) "
        "SELECT true, acl.gen_random_bytes(32) "
        "WHERE NOT EXISTS (SELECT 1 FROM acl.mask_key)",
        f"ALTER TABLE acl.signing_keys OWNER TO {acl_owner}",
        f"ALTER TABLE acl.mask_key OWNER TO {acl_owner}",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA {acl} FROM PUBLIC",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA {acl} FROM {ident(SIGNER_ROLE)}",
        f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {acl} FROM PUBLIC",
        f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {acl} TO {acl_owner}",
    ]
    statements += [body.strip() for body in _FUNCTION_BODIES]
    for signature in (*_PRIVATE_FUNCTIONS, *_READER_FUNCTIONS, *_OWNER_FUNCTIONS):
        statements.append(f"ALTER FUNCTION {signature} OWNER TO {acl_owner}")
        statements.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    readers = f"{ident(EXPOSURE_OWNER_ROLE)}, {ident(READER_ROLE)}"
    for signature in _PRIVATE_FUNCTIONS:
        statements.append(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {readers}")
    for signature in _READER_FUNCTIONS:
        statements.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {readers}")
    for signature in _OWNER_FUNCTIONS:
        statements.append(
            f"GRANT EXECUTE ON FUNCTION {signature} TO {ident(ENTITY_OWNER_ROLE)}"
        )
    signer = ident(SIGNER_ROLE)
    statements.append(
        f"GRANT EXECUTE ON FUNCTION acl.ensure_signing_key() TO {signer}"
    )
    for signature in (*_PRIVATE_FUNCTIONS, *_READER_FUNCTIONS, "acl.install_key(text, bytea)"):
        statements.append(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {signer}")
    statements.append(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {acl_owner} IN SCHEMA {acl} "
        "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
    )
    return statements


_PROFILE_PAGE_LIMIT = PAGE_LIMIT_MAX + 1

# psycopg treats "%" as a placeholder, so each LIKE percent in this body is "%%".
_PROFILE_PAGE_SQL = r"""
CREATE OR REPLACE FUNCTION entity_access.profile_filter(
  p_view regclass,
  p_node jsonb,
  p_path text[],
  p_depth integer
) RETURNS TABLE (sql text, leaves integer, ins integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
  key_count integer;
  items jsonb;
  n integer;
  i integer;
  child jsonb;
  part_sql text;
  part_leaves integer;
  part_ins integer;
  parts text[] := ARRAY[]::text[];
  leaf_sum integer := 0;
  in_sum integer := 0;
  joiner text;
  field text;
  op text;
  typ text;
  is_jsonb boolean;
  path_lit text;
  page_col text;
  rhs text;
  expr text;
  in_count integer := 0;
  grouped text;
BEGIN
  IF p_depth > __DEPTH_CAP__ THEN
    RAISE EXCEPTION 'filter depth exceeds limit' USING ERRCODE = '22023';
  END IF;
  IF jsonb_typeof(p_node) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'filter node must be an object' USING ERRCODE = '22023';
  END IF;
  SELECT count(*) INTO key_count FROM jsonb_object_keys(p_node) AS k;
  IF (p_node ? 'all') OR (p_node ? 'any') THEN
    IF ((p_node ? 'all') AND (p_node ? 'any')) OR key_count <> 1 THEN
      RAISE EXCEPTION 'filter node must be a leaf or all/any group' USING ERRCODE = '22023';
    END IF;
    items := CASE WHEN p_node ? 'all' THEN p_node->'all' ELSE p_node->'any' END;
    IF jsonb_typeof(items) IS DISTINCT FROM 'array' OR jsonb_array_length(items) < 1 THEN
      RAISE EXCEPTION 'all/any must be a non-empty array' USING ERRCODE = '22023';
    END IF;
    n := jsonb_array_length(items);
    joiner := CASE WHEN p_node ? 'all' THEN ' AND ' ELSE ' OR ' END;
    FOR i IN 0..n - 1 LOOP
      child := items->i;
      SELECT f.sql, f.leaves, f.ins
        INTO part_sql, part_leaves, part_ins
      FROM entity_access.profile_filter(
        p_view, child, p_path || ARRAY[CASE WHEN p_node ? 'all' THEN 'all' ELSE 'any' END, i::text], p_depth + 1
      ) AS f;
      parts := parts || part_sql;
      leaf_sum := leaf_sum + part_leaves;
      in_sum := in_sum + part_ins;
      IF leaf_sum > __LEAVES_CAP__ THEN
        RAISE EXCEPTION 'filter leaf count exceeds limit' USING ERRCODE = '22023';
      END IF;
      IF in_sum > __IN_CAP__ THEN
        RAISE EXCEPTION 'in value count exceeds limit' USING ERRCODE = '22023';
      END IF;
    END LOOP;
    grouped := '(' || array_to_string(parts, joiner) || ')';
    RETURN QUERY SELECT grouped, leaf_sum, in_sum;
    RETURN;
  END IF;
  IF NOT (p_node ? 'field' AND p_node ? 'op')
     OR EXISTS (
       SELECT 1 FROM jsonb_object_keys(p_node) AS k
       WHERE k NOT IN ('field', 'op', 'value')
     ) THEN
    RAISE EXCEPTION 'filter node must be a leaf or all/any group' USING ERRCODE = '22023';
  END IF;
  IF jsonb_typeof(p_node->'field') IS DISTINCT FROM 'string'
     OR jsonb_typeof(p_node->'op') IS DISTINCT FROM 'string' THEN
    RAISE EXCEPTION 'filter field and op must be strings' USING ERRCODE = '22023';
  END IF;
  field := p_node->>'field';
  op := p_node->>'op';
  IF field !~ '^[A-Za-z_][A-Za-z0-9_]*$' THEN
    RAISE EXCEPTION 'filter field is not an identifier' USING ERRCODE = '22023';
  END IF;
  IF op NOT IN ('eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'contains', 'is_null') THEN
    RAISE EXCEPTION 'filter op is not allowed' USING ERRCODE = '22023';
  END IF;
  SELECT pg_catalog.format_type(a.atttypid, a.atttypmod),
         a.atttypid = 'pg_catalog.jsonb'::regtype
    INTO typ, is_jsonb
  FROM pg_catalog.pg_attribute a
  WHERE a.attrelid = p_view
    AND a.attname = field
    AND a.attnum > 0
    AND NOT a.attisdropped;
  IF typ IS NULL OR typ !~ '^[A-Za-z0-9_ ]+(\([0-9, ]+\))?$' THEN
    RAISE EXCEPTION 'filter field is not on the view' USING ERRCODE = '22023';
  END IF;
  page_col := 'page.' || pg_catalog.quote_ident(field);
  IF op = 'is_null' THEN
    IF p_node ? 'value' AND p_node->'value' <> 'null'::jsonb THEN
      RAISE EXCEPTION 'is_null must not carry a value' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY SELECT page_col || ' IS NULL', 1, 0;
    RETURN;
  END IF;
  IF NOT (p_node ? 'value') THEN
    RAISE EXCEPTION 'filter op requires value' USING ERRCODE = '22023';
  END IF;
  path_lit := '{' || array_to_string(p_path || ARRAY['value'], ',') || '}';
  IF op = 'contains' THEN
    IF is_jsonb OR jsonb_typeof(p_node->'value') IS DISTINCT FROM 'string' THEN
      RAISE EXCEPTION 'contains value must be a non-empty string' USING ERRCODE = '22023';
    END IF;
    IF (p_node->>'value') = '' THEN
      RAISE EXCEPTION 'contains value must be a non-empty string' USING ERRCODE = '22023';
    END IF;
    expr := page_col
      || ' ILIKE (''%%'' || replace(replace(replace($1 #>> '
      || pg_catalog.quote_literal(path_lit)
      || ', E''\\'', E''\\\\''), ''%%'', E''\\%%''), ''_'', E''\\_'') || ''%%'') ESCAPE E''\\''';
    RETURN QUERY SELECT expr, 1, 0;
    RETURN;
  END IF;
  IF op = 'in' THEN
    IF jsonb_typeof(p_node->'value') IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_node->'value') < 1 THEN
      RAISE EXCEPTION 'in value must be a non-empty array' USING ERRCODE = '22023';
    END IF;
    in_count := jsonb_array_length(p_node->'value');
    IF in_count > __IN_CAP__ THEN
      RAISE EXCEPTION 'in value count exceeds limit' USING ERRCODE = '22023';
    END IF;
    IF is_jsonb THEN
      expr := page_col || ' IN (SELECT v FROM jsonb_array_elements($1 #> '
        || pg_catalog.quote_literal(path_lit) || ') AS t(v))';
    ELSE
      expr := page_col || ' IN (SELECT v::' || typ || ' FROM jsonb_array_elements_text($1 #> '
        || pg_catalog.quote_literal(path_lit) || ') AS t(v))';
    END IF;
    RETURN QUERY SELECT expr, 1, in_count;
    RETURN;
  END IF;
  IF is_jsonb THEN
    rhs := '($1 #> ' || pg_catalog.quote_literal(path_lit) || ')';
  ELSE
    rhs := '($1 #>> ' || pg_catalog.quote_literal(path_lit) || ')::' || typ;
  END IF;
  expr := CASE op
    WHEN 'eq' THEN page_col || ' = ' || rhs
    WHEN 'ne' THEN page_col || ' IS DISTINCT FROM ' || rhs
    WHEN 'gt' THEN page_col || ' > ' || rhs
    WHEN 'gte' THEN page_col || ' >= ' || rhs
    WHEN 'lt' THEN page_col || ' < ' || rhs
    WHEN 'lte' THEN page_col || ' <= ' || rhs
  END;
  RETURN QUERY SELECT expr, 1, 0;
END
$fn$
""".strip()


_PROFILE_PAGE_SQL_FN = """
CREATE OR REPLACE FUNCTION entity_access.profile_page_sql(
  p_view regclass,
  p_columns text[],
  p_limit integer,
  p_offset integer,
  p_after bigint,
  p_filter jsonb
) RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
  kind "char";
  nsp text;
  rel_owner text;
  col text;
  cols text := '';
  def text;
  filt text;
  where_sql text := '';
  skip_filter boolean;
BEGIN
  IF p_limit IS NULL OR p_limit < 1 OR p_limit > __LIMIT_CAP__ THEN
    RAISE EXCEPTION 'page limit out of range' USING ERRCODE = '22023';
  END IF;
  IF p_offset IS NULL OR p_offset < 0 OR p_offset > __OFFSET_CAP__ THEN
    RAISE EXCEPTION 'page offset out of range' USING ERRCODE = '22023';
  END IF;
  IF p_after IS NOT NULL AND p_after < 1 THEN
    RAISE EXCEPTION 'page after out of range' USING ERRCODE = '22023';
  END IF;
  IF p_columns IS NULL OR cardinality(p_columns) < 1 OR cardinality(p_columns) > 512 THEN
    RAISE EXCEPTION 'page columns out of range' USING ERRCODE = '22023';
  END IF;
  SELECT c.relkind, n.nspname, r.rolname
    INTO kind, nsp, rel_owner
  FROM pg_catalog.pg_class c
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_catalog.pg_roles r ON r.oid = c.relowner
  WHERE c.oid = p_view;
  IF kind IS DISTINCT FROM 'v'
     OR nsp IS DISTINCT FROM 'entity_access'
     OR rel_owner IS DISTINCT FROM 'refraq_exposure_owner' THEN
    RAISE EXCEPTION 'page view is not an exposure profile' USING ERRCODE = '42501';
  END IF;
  IF NOT pg_catalog.has_table_privilege(session_user, p_view, 'SELECT') THEN
    RAISE EXCEPTION 'page view is not selectable' USING ERRCODE = '42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_attribute a
    WHERE a.attrelid = p_view AND a.attname = 'row_id' AND a.attnum > 0 AND NOT a.attisdropped
  ) THEN
    RAISE EXCEPTION 'page view has no row_id' USING ERRCODE = '22023';
  END IF;
  FOREACH col IN ARRAY p_columns LOOP
    IF col IS NULL OR col !~ '^[A-Za-z_][A-Za-z0-9_]*$' THEN
      RAISE EXCEPTION 'page column is not an identifier' USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
      SELECT 1 FROM pg_catalog.pg_attribute a
      WHERE a.attrelid = p_view AND a.attname = col AND a.attnum > 0 AND NOT a.attisdropped
    ) THEN
      RAISE EXCEPTION 'page column is not on the view' USING ERRCODE = '22023';
    END IF;
    IF cols <> '' THEN
      cols := cols || ', ';
    END IF;
    cols := cols || pg_catalog.quote_ident(col);
  END LOOP;
  def := btrim(pg_catalog.pg_get_viewdef(p_view, true));
  def := regexp_replace(def, ';[[:space:]]*$', '');
  skip_filter := p_filter IS NULL
    OR jsonb_typeof(p_filter) = 'null'
    OR p_filter = '{}'::jsonb;
  IF NOT skip_filter THEN
    SELECT f.sql INTO filt
    FROM entity_access.profile_filter(p_view, p_filter, ARRAY[]::text[], 1) AS f;
    where_sql := ' WHERE ' || filt;
  END IF;
  IF p_after IS NOT NULL THEN
    IF where_sql = '' THEN
      where_sql := ' WHERE page.row_id > ' || p_after::text;
    ELSE
      where_sql := where_sql || ' AND page.row_id > ' || p_after::text;
    END IF;
  END IF;
  RETURN 'SELECT ' || cols
    || ' FROM (' || def || ') AS page'
    || where_sql
    || ' ORDER BY page.row_id ASC LIMIT ' || p_limit::text
    || ' OFFSET ' || p_offset::text;
END
$fn$
""".strip()


_PROFILE_PAGE_FN = """
CREATE OR REPLACE FUNCTION entity_access.profile_page(
  p_view regclass,
  p_columns text[],
  p_limit integer,
  p_offset integer,
  p_after bigint,
  p_filter jsonb
) RETURNS SETOF record
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET row_security = on
AS $fn$
DECLARE
  query text;
  skip_filter boolean;
BEGIN
  query := entity_access.profile_page_sql(
    p_view, p_columns, p_limit, p_offset, p_after, p_filter
  );
  skip_filter := p_filter IS NULL
    OR jsonb_typeof(p_filter) = 'null'
    OR p_filter = '{}'::jsonb;
  IF skip_filter THEN
    RETURN QUERY EXECUTE query;
  ELSE
    RETURN QUERY EXECUTE query USING p_filter;
  END IF;
END
$fn$
""".strip()


def profile_page_statements() -> list[str]:
    """Exposure-owner page function. The reader passes a view, not a SQL string."""
    body = (
        _PROFILE_PAGE_SQL.replace("__DEPTH_CAP__", str(FILTER_DEPTH_MAX))
        .replace("__LEAVES_CAP__", str(FILTER_LEAVES_MAX))
        .replace("__IN_CAP__", str(FILTER_IN_VALUES_MAX))
    )
    sql_fn = (
        _PROFILE_PAGE_SQL_FN.replace("__LIMIT_CAP__", str(_PROFILE_PAGE_LIMIT))
        .replace("__OFFSET_CAP__", str(OFFSET_MAX))
    )
    exposure = ident(EXPOSURE_OWNER_ROLE)
    reader = ident(READER_ROLE)
    signatures = (
        "entity_access.profile_filter(regclass, jsonb, text[], integer)",
        "entity_access.profile_page_sql(regclass, text[], integer, integer, bigint, jsonb)",
        "entity_access.profile_page(regclass, text[], integer, integer, bigint, jsonb)",
    )
    statements = [body, sql_fn, _PROFILE_PAGE_FN]
    for signature in signatures:
        statements.append(f"ALTER FUNCTION {signature} OWNER TO {exposure}")
        statements.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    statements.append(
        "REVOKE ALL ON FUNCTION entity_access.profile_filter(regclass, jsonb, text[], integer) "
        f"FROM {reader}"
    )
    statements.append(
        "REVOKE ALL ON FUNCTION entity_access.profile_page_sql"
        "(regclass, text[], integer, integer, bigint, jsonb) "
        f"FROM {reader}"
    )
    statements.append(
        "GRANT EXECUTE ON FUNCTION entity_access.profile_page"
        "(regclass, text[], integer, integer, bigint, jsonb) "
        f"TO {reader}"
    )
    return statements


@dataclass(frozen=True, slots=True)
class LegacyRelation:
    name: str
    kind: str


def move_statements(
    legacy_schema: str,
    relations: list[LegacyRelation],
    *,
    occupied: frozenset[str],
) -> list[str]:
    """Move Entity Tables and stem views from the legacy schema into entity_data."""
    if legacy_schema == ENTITY_DATA_SCHEMA:
        return []
    clash = sorted(item.name for item in relations if item.name in occupied)
    if clash:
        raise BootstrapPlanError(
            f"{ENTITY_DATA_SCHEMA} already holds relation(s) named "
            + ", ".join(clash)
            + f"; resolve them before moving from {legacy_schema}"
        )
    statements: list[str] = []
    for item in sorted(relations, key=lambda rel: (rel.kind != "r", rel.name)):
        verb = "ALTER TABLE" if item.kind == "r" else "ALTER VIEW"
        statements.append(
            f"{verb} {qualified_table(legacy_schema, item.name)} "
            f"SET SCHEMA {ident(ENTITY_DATA_SCHEMA)}"
        )
    return statements


def secure_existing_table_statements(
    tables: list[str], views: list[str]
) -> list[str]:
    """Converge owner, RLS, policies, and grants on every relation in entity_data."""
    statements: list[str] = []
    for table in sorted(tables):
        q = qualified_table(ENTITY_DATA_SCHEMA, table)
        statements += [
            f"DROP POLICY IF EXISTS {ident(EXPOSURE_POLICY)} ON {q}",
            f"DROP POLICY IF EXISTS {ident(OWNER_POLICY)} ON {q}",
            *table_security_statements(ENTITY_DATA_SCHEMA, table),
        ]
    for view in sorted(views):
        statements += view_security_statements(ENTITY_DATA_SCHEMA, view)
    return statements


@dataclass(frozen=True, slots=True)
class BootstrapReport:
    database: str
    moved: int
    secured_tables: int
    secured_views: int


def ensure_database(admin_url: str) -> bool:
    """Create the entity database when missing. Returns True when it was created."""
    target = make_url(admin_url)
    database = target.database or ""
    engine = create_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with engine.connect() as conn:
            found = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": database},
            ).scalar()
            if found:
                return False
            conn.exec_driver_sql(f"CREATE DATABASE {ident(database)}")
            return True
    finally:
        engine.dispose()


def _login(url: str, *, role: str, setting: str) -> str:
    parsed = make_url(url)
    if parsed.username != role:
        raise BootstrapPlanError(f"{setting} must log in as {role}")
    if not parsed.password:
        raise BootstrapPlanError(f"{setting} must carry the {role} password")
    return parsed.password


def _same_database(left: str, right: str) -> bool:
    a, b = make_url(left), make_url(right)
    return (a.database or "") == (b.database or "")


def run_bootstrap(
    admin_url: str,
    owner_url: str,
    reader_url: str,
    signer_url: str,
    *,
    legacy_schema: str = LEGACY_SCHEMA_DEFAULT,
) -> BootstrapReport:
    owner_password = _login(owner_url, role=ENTITY_OWNER_ROLE, setting="ENTITY_DATABASE_URL")
    reader_password = _login(
        reader_url, role=READER_ROLE, setting="ENTITY_READER_DATABASE_URL"
    )
    signer_password = _login(
        signer_url, role=SIGNER_ROLE, setting="ENTITY_SIGNER_DATABASE_URL"
    )
    for setting, url in (
        ("ENTITY_DATABASE_URL", owner_url),
        ("ENTITY_READER_DATABASE_URL", reader_url),
        ("ENTITY_SIGNER_DATABASE_URL", signer_url),
    ):
        if not _same_database(admin_url, url):
            raise BootstrapPlanError(
                f"{setting} must name the database of ENTITY_ADMIN_DATABASE_URL"
            )
    engine = create_engine(admin_url)
    try:
        with engine.begin() as conn:
            return _converge(
                conn,
                owner_password=owner_password,
                reader_password=reader_password,
                signer_password=signer_password,
                legacy_schema=legacy_schema,
            )
    finally:
        engine.dispose()


def _converge(
    conn: Connection,
    *,
    owner_password: str,
    reader_password: str,
    signer_password: str,
    legacy_schema: str,
) -> BootstrapReport:
    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
    version = int(conn.execute(text("SHOW server_version_num")).scalar_one())
    if version < MIN_SERVER_VERSION_NUM:
        raise BootstrapPlanError("the entity database requires PostgreSQL 18 or newer")
    if conn.execute(
        text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    ).scalar():
        raise BootstrapPlanError(
            "the target is the metadata database (alembic_version present); "
            "the entity database must be a separate database"
        )
    database = str(conn.execute(text("SELECT current_database()")).scalar_one())
    existing = frozenset(
        conn.execute(
            text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:names)"),
            {
                "names": [
                    ENTITY_OWNER_ROLE,
                    EXPOSURE_OWNER_ROLE,
                    ACL_OWNER_ROLE,
                    READER_ROLE,
                    SIGNER_ROLE,
                    _RETIRED_CHANNEL_READER,
                ]
            },
        ).scalars()
    )
    _apply(
        conn,
        role_statements(
            owner_password=owner_password,
            reader_password=reader_password,
            signer_password=signer_password,
            existing=existing,
        ),
    )
    _apply(conn, retire_channel_reader_statements(existing))
    has_public = bool(
        conn.execute(text("SELECT to_regnamespace('public') IS NOT NULL")).scalar()
    )
    _apply(conn, database_statements(database, has_public_schema=has_public))
    _apply(conn, schema_statements())
    pgcrypto_schema = conn.execute(
        text(
            "SELECT n.nspname FROM pg_extension e "
            "JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'pgcrypto'"
        )
    ).scalar()
    _apply(conn, acl_statements(pgcrypto_schema=pgcrypto_schema))
    _apply(conn, profile_page_statements())
    relations = _legacy_relations(conn, legacy_schema)
    occupied = frozenset(_relation_names(conn, ENTITY_DATA_SCHEMA, ("r", "v", "m", "p", "f")))
    _apply(conn, move_statements(legacy_schema, relations, occupied=occupied))
    tables = _relation_names(conn, ENTITY_DATA_SCHEMA, ("r",))
    views = _relation_names(conn, ENTITY_DATA_SCHEMA, ("v",))
    _apply(conn, secure_existing_table_statements(tables, views))
    ensure_shared_relations(conn)
    return BootstrapReport(
        database=database,
        moved=len(relations) if legacy_schema != ENTITY_DATA_SCHEMA else 0,
        secured_tables=len(tables),
        secured_views=len(views),
    )


def _apply(conn: Connection, statements: list[str]) -> None:
    # exec_driver_sql does not bind ":name". psycopg still treats "%" as a
    # placeholder, so a literal percent in a statement is written "%%".
    for sql in statements:
        conn.exec_driver_sql(sql)


def _relation_names(conn: Connection, schema: str, kinds: tuple[str, ...]) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relkind::text = ANY(:kinds) "
                "ORDER BY c.relname"
            ),
            {"schema": schema, "kinds": list(kinds)},
        ).scalars()
    )


def _legacy_relations(conn: Connection, schema: str) -> list[LegacyRelation]:
    """Physical Entity Tables by name, plus views that select only from them."""
    if schema == ENTITY_DATA_SCHEMA:
        return []
    tables = [
        LegacyRelation(name=name, kind="r")
        for name in conn.execute(
            text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relkind = 'r' AND c.relname ~ :pattern"
            ),
            {"schema": schema, "pattern": _PHYSICAL_TABLE_SQL_RE},
        ).scalars()
    ]
    rows = conn.execute(
        text(
            "SELECT v.relname, refn.nspname, ref.relname "
            "FROM pg_class v "
            "JOIN pg_namespace n ON n.oid = v.relnamespace "
            "JOIN pg_rewrite rw ON rw.ev_class = v.oid "
            "JOIN pg_depend d ON d.objid = rw.oid AND d.classid = 'pg_rewrite'::regclass "
            "AND d.refclassid = 'pg_class'::regclass "
            "JOIN pg_class ref ON ref.oid = d.refobjid AND ref.oid <> v.oid "
            "JOIN pg_namespace refn ON refn.oid = ref.relnamespace "
            "WHERE n.nspname = :schema AND v.relkind = 'v'"
        ),
        {"schema": schema},
    ).all()
    refs: dict[str, list[tuple[str, str]]] = {}
    for view, ref_schema, ref_name in rows:
        refs.setdefault(str(view), []).append((str(ref_schema), str(ref_name)))
    views = [
        LegacyRelation(name=view, kind="v")
        for view, targets in sorted(refs.items())
        if all(
            ref_schema == schema and _PHYSICAL_TABLE_RE.search(ref_name)
            for ref_schema, ref_name in set(targets)
        )
    ]
    return tables + views


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.entity.bootstrap",
        description="Create entity-database roles, schemas, acl functions; move tables.",
    )
    parser.add_argument(
        "--legacy-schema",
        default=LEGACY_SCHEMA_DEFAULT,
        help="schema that held Entity Tables before entity_data (default: public)",
    )
    parser.add_argument(
        "--create-database",
        action="store_true",
        help="create the database named by ENTITY_ADMIN_DATABASE_URL when missing",
    )
    args = parser.parse_args(argv)
    settings = BootstrapSettings()
    missing = [
        name
        for name, value in (
            ("ENTITY_ADMIN_DATABASE_URL", settings.admin_url),
            ("ENTITY_DATABASE_URL", settings.owner_url),
            ("ENTITY_READER_DATABASE_URL", settings.reader_url),
            ("ENTITY_SIGNER_DATABASE_URL", settings.signer_url),
        )
        if not (value or "").strip()
    ]
    if missing:
        print("entity bootstrap requires " + ", ".join(missing), file=sys.stderr)
        return 2
    assert (
        settings.admin_url
        and settings.owner_url
        and settings.reader_url
        and settings.signer_url
    )
    try:
        if args.create_database and ensure_database(settings.admin_url):
            print("entity bootstrap created database")
        report = run_bootstrap(
            settings.admin_url,
            settings.owner_url,
            settings.reader_url,
            settings.signer_url,
            legacy_schema=args.legacy_schema,
        )
    except BootstrapPlanError as exc:
        print(f"entity bootstrap refused: {exc}", file=sys.stderr)
        return 1
    print(
        f"entity bootstrap ok database={report.database} moved={report.moved} "
        f"tables={report.secured_tables} views={report.secured_views}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
