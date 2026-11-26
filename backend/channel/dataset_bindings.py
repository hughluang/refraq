"""In-process AST binding of run-scoped dataset aliases in entity SQL."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA
from backend.channel.dataset_registry import (
    DatasetRegistry,
    dataset_belongs_to_run,
    get_dataset_store,
)
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import EngineHooks, NodeResult, Problem
from backend.core.time import utc_now

__all__ = [
    "DATASETS_CONFIG_SCHEMA",
    "bind_dataset_sql",
    "resolve_dataset_bindings",
    "validate_dataset_bindings",
]

_DIALECT = "postgres"
_ALIAS_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")

DATASETS_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "Datasets",
    "description": (
        "SQL table aliases mapped to dataset references. "
        "Available only when source is entity."
    ),
    "additionalProperties": {
        "type": "string",
        "minLength": 1,
        "x-refraq-template": DATASET_REFERENCE_SCHEMA,
    },
}


def validate_dataset_bindings(config: Mapping[str, Any]) -> list[Problem]:
    """Validate optional ``datasets`` alias map in node configuration."""
    raw = config.get("datasets")
    if raw is None or raw == {}:
        return []
    if not isinstance(raw, Mapping):
        return [
            Problem(
                "CHANNEL_NODE_CONFIG_INVALID",
                "datasets must be an object mapping SQL aliases to dataset references",
                path=("datasets",),
            )
        ]
    source = config.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "entity":
        return [
            Problem(
                "CHANNEL_NODE_CONFIG_INVALID",
                "datasets is supported only when source is entity",
                path=("datasets",),
            )
        ]
    problems: list[Problem] = []
    for alias in raw:
        if not isinstance(alias, str) or not _ALIAS_RE.match(alias):
            problems.append(
                Problem(
                    "CHANNEL_NODE_CONFIG_INVALID",
                    f"Dataset alias is not a valid SQL identifier: {alias}",
                    path=("datasets", str(alias)),
                )
            )
    return problems


def resolve_dataset_bindings(
    raw: Any,
    hooks: EngineHooks,
) -> tuple[dict[str, str], NodeResult | None]:
    """Render and verify ``datasets`` templates into physical relation names."""
    if raw is None or raw == {}:
        return {}, None
    if not isinstance(raw, Mapping):
        return {}, NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_CONFIG_INVALID",
            error_message="datasets must be an object",
        )
    store = get_dataset_store()
    registry = DatasetRegistry(store)
    bindings: dict[str, str] = {}
    for alias, tmpl in raw.items():
        if not isinstance(alias, str) or not _ALIAS_RE.match(alias):
            return {}, NodeResult(
                status="failed",
                error_code="CHANNEL_NODE_CONFIG_INVALID",
                error_message=f"Dataset alias is not a valid SQL identifier: {alias}",
            )
        ref, error = render_field(
            hooks, tmpl, DATASET_REFERENCE_SCHEMA, path=f"datasets.{alias}"
        )
        if error is not None:
            return {}, error
        dataset_id = ref.get("dataset_id")
        if not isinstance(dataset_id, str) or dataset_id == "":
            return {}, _unavailable("not_found")
        record = store.get(dataset_id)
        if record is None:
            return {}, _unavailable("not_found")
        if not dataset_belongs_to_run(record, hooks.run_id):
            return {}, _unavailable("foreign_run")
        if record.expires_at is not None and record.expires_at <= utc_now():
            return {}, _unavailable("expired")
        if record.status != "ready":
            return {}, _unavailable("not_found")
        if registry.is_lost(dataset_id):
            return {}, _unavailable("lost")
        bindings[alias] = record.relation
    return bindings, None


def bind_dataset_sql(sql: str, bindings: Mapping[str, str]) -> str:
    """Rewrite unshadowed unqualified dataset table aliases to physical relations."""
    if not bindings:
        return sql
    cleaned = (sql or "").strip()
    trailing_semi = cleaned.endswith(";")
    body = cleaned[:-1].strip() if trailing_semi else cleaned
    if not body:
        raise ValueError("SQL must be a single statement when datasets are bound")
    try:
        statements = [
            item
            for item in parse(body, read=_DIALECT)
            if item is not None and not isinstance(item, exp.Semicolon)
        ]
    except SqlglotError as exc:
        raise ValueError(f"SQL could not be parsed for dataset binding: {exc}") from exc
    if len(statements) != 1:
        raise ValueError("SQL must be a single statement when datasets are bound")
    statement = statements[0]
    lowered = {key.lower(): value for key, value in bindings.items()}
    parsed_relations: dict[str, exp.Table] = {}
    for scope in traverse_scope(statement):
        cte_names = _cte_folded_names(scope)
        for table in scope.tables:
            if not isinstance(table.this, exp.Identifier):
                continue
            if table.args.get("db") or table.args.get("catalog"):
                continue
            folded = _fold_identifier(table.this)
            if folded in cte_names:
                continue
            relation_sql = _match_binding(table.this, bindings, lowered)
            if relation_sql is None:
                continue
            _rewrite_table(table, relation_sql, parsed_relations)
    rewritten = statement.sql(dialect=_DIALECT)
    return f"{rewritten};" if trailing_semi else rewritten


def _unavailable(reason: str) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_DATASET_UNAVAILABLE",
        error_message="Dataset is not available",
        error_detail={"reason": reason},
    )


def _fold_identifier(ident: exp.Identifier) -> str:
    return ident.this if ident.quoted else ident.this.lower()


def _cte_folded_names(scope: Scope) -> set[str]:
    names: set[str] = set()
    for cte in scope.ctes:
        alias = cte.args.get("alias")
        if isinstance(alias, exp.TableAlias) and isinstance(alias.this, exp.Identifier):
            names.add(_fold_identifier(alias.this))
    for name in scope.cte_sources:
        names.add(name.lower())
    return names


def _match_binding(
    ident: exp.Identifier,
    bindings: Mapping[str, str],
    lowered: Mapping[str, str],
) -> str | None:
    if ident.quoted:
        return bindings.get(ident.this)
    name = ident.this.lower()
    return bindings.get(name) or lowered.get(name)


def _rewrite_table(
    table: exp.Table,
    relation_sql: str,
    parsed: dict[str, exp.Table],
) -> None:
    relation = _relation_table(relation_sql, parsed)
    if table.args.get("alias") is None:
        table.set("alias", exp.TableAlias(this=table.this.copy()))
    table.set("this", relation.this.copy())
    db = relation.args.get("db")
    table.set("db", db.copy() if isinstance(db, exp.Expression) else None)
    catalog = relation.args.get("catalog")
    table.set("catalog", catalog.copy() if isinstance(catalog, exp.Expression) else None)


def _relation_table(text: str, parsed: dict[str, exp.Table]) -> exp.Table:
    found = parsed.get(text)
    if found is not None:
        return found
    statements = [
        item
        for item in parse(f"SELECT 1 FROM {text}", read=_DIALECT)
        if item is not None and not isinstance(item, exp.Semicolon)
    ]
    source = statements[0].args.get("from_") if len(statements) == 1 else None
    table = source.this if source is not None else None
    if not isinstance(table, exp.Table) or not isinstance(table.this, exp.Identifier):
        raise ValueError(f"relation identifier is not a table: {text}")
    parsed[text] = table
    return table
