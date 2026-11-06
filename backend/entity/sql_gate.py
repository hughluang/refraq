"""Entity SQL gate and name binding.

One PostgreSQL statement in, a bound statement or a rejection out. No database
access. Profile View lookup stays with the caller, who passes each visible
Entity ``table_name`` and the relation identifier to substitute.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Set as AbstractSet
from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError, SqlglotError, TokenError
from sqlglot.optimizer.scope import Scope, traverse_scope

from backend.core.sql_ast import READ_QUERY_ROOTS, WRITE_OR_DDL

_DIALECT = "postgres"
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_WRITE_LABELS: tuple[tuple[type[exp.Expression], str], ...] = (
    (exp.Insert, "INSERT"),
    (exp.Update, "UPDATE"),
    (exp.Delete, "DELETE"),
    (exp.Drop, "DROP"),
    (exp.Create, "CREATE"),
    (exp.Alter, "ALTER"),
    (exp.TruncateTable, "TRUNCATE"),
    (exp.Merge, "MERGE"),
    (exp.Copy, "COPY"),
)


class EntitySqlError(Exception):
    """A gate rejection. Callers map this; it is not an application error."""


class EntitySqlNotFound(EntitySqlError):
    """The relation name is unknown or not in the caller's visible set.

    ``name`` is the identifier text as written. Unquoted and quoted names that
    miss the visible set share this outcome.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.message = f"unknown name: {name}"
        super().__init__(self.message)


class EntitySqlInvalid(EntitySqlError):
    """The statement is not a single read-only Entity query.

    ``message`` names the rejected construct in English.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class EntitySqlColumn:
    """One row-varying column the statement names."""

    table_name: str
    column: str


@dataclass(frozen=True, slots=True)
class EntitySqlBound:
    """A statement the gate accepted.

    ``bound_sql`` is the rewritten text. ``entities`` are the referenced
    Entity ``table_name`` values. ``partial_columns`` are the row-varying
    columns the statement names, including every row-varying column of an
    Entity selected with ``*``.
    """

    bound_sql: str
    entities: frozenset[str]
    partial_columns: frozenset[EntitySqlColumn]


@dataclass(frozen=True, slots=True)
class _TableFact:
    kind: str
    source_key: str | None
    entity: str | None


def bind_entity_sql(
    sql: str,
    *,
    relations: Mapping[str, str],
    row_varying_columns: Mapping[str, AbstractSet[str]] | None = None,
) -> EntitySqlBound:
    """Gate ``sql`` and bind each visible Entity reference.

    ``relations`` maps a visible Entity ``table_name`` to the caller's
    relation identifier (the Profile View), for example
    ``"entity_access"."orders__p_ab12"``. Keys are the visible set. A
    referenced name that is not a key is not found, whether or not an Entity
    by that name exists.

    ``row_varying_columns`` maps a ``table_name`` to the column names that
    vary by row. A missing key means that Entity has none. Unquoted SQL
    identifiers are folded to lower case before they are matched; quoted
    identifiers are matched as written. ``table_name`` keys are already the
    caller's canonical names.
    """
    statement = _parse_one(sql)
    _reject_shape(statement, sql)
    _reject_casts(statement)
    _reject_functions(statement)
    varying = {
        name: frozenset(columns)
        for name, columns in (row_varying_columns or {}).items()
    }
    referenced, columns = _bind(statement, relations, varying)
    return EntitySqlBound(
        bound_sql=statement.sql(dialect=_DIALECT),
        entities=frozenset(referenced),
        partial_columns=frozenset(columns),
    )


def _parse_one(sql: str) -> exp.Expression:
    if not sql.strip():
        raise EntitySqlInvalid("SQL statement is empty")
    try:
        statements = [item for item in parse(sql, read=_DIALECT) if item is not None]
    except ParseError as exc:
        raise EntitySqlInvalid(_plain_invalid_sql(exc)) from exc
    except TokenError as exc:
        raise EntitySqlInvalid(_plain_invalid_sql(exc)) from exc
    real = [item for item in statements if not isinstance(item, exp.Semicolon)]
    if not real:
        raise EntitySqlInvalid("SQL statement is empty")
    if len(real) > 1:
        raise EntitySqlInvalid("Multiple statements are not allowed")
    return real[0]


def _plain_invalid_sql(exc: SqlglotError) -> str:
    """One English line. ``str(ParseError)`` appends a highlighted SQL snippet."""
    if isinstance(exc, ParseError):
        detail = _parse_error_detail(exc)
    else:
        detail = _token_error_detail(exc)
    detail = _ANSI.sub("", detail)
    detail = " ".join(detail.split())
    if not detail:
        detail = "SQL could not be parsed"
    return f"Invalid SQL: {detail}"


def _token_error_detail(exc: TokenError) -> str:
    """The cause names the missing closer. ``str(TokenError)`` quotes a truncated snippet."""
    cause = exc.__cause__
    if isinstance(cause, TokenError):
        text = str(cause).strip()
        if text:
            return text
    return str(exc)


def _parse_error_detail(exc: ParseError) -> str:
    error = exc.errors[0] if exc.errors else None
    if isinstance(error, dict):
        description = str(error.get("description") or "").strip()
        line = error.get("line")
        column = error.get("col")
        if description and line is not None and column is not None:
            return f"{description} at line {line}, column {column}"
        if description:
            return description
    return str(exc)


def _reject_shape(statement: exp.Expression, sql: str) -> None:
    if not isinstance(statement, READ_QUERY_ROOTS):
        raise EntitySqlInvalid(f"{_statement_label(statement, sql)} is not allowed")
    for node in statement.walk():
        if isinstance(node, exp.Into):
            raise EntitySqlInvalid("SELECT INTO is not allowed")
        if isinstance(node, exp.Lock):
            clause = node.sql(dialect=_DIALECT).strip()
            raise EntitySqlInvalid(f"Row locking ({clause}) is not allowed")
        if isinstance(node, (exp.Set, exp.Transaction, exp.Commit, exp.Rollback, exp.Command)):
            raise EntitySqlInvalid(f"{_statement_label(node)} is not allowed")
        if isinstance(node, WRITE_OR_DDL):
            raise EntitySqlInvalid(f"{_statement_label(node)} is not allowed")


def _statement_label(node: exp.Expression, sql: str | None = None) -> str:
    if isinstance(node, exp.Command):
        return str(node.this or "COMMAND")
    if isinstance(node, exp.Set):
        return "SET"
    if isinstance(node, exp.Transaction):
        return "BEGIN"
    if isinstance(node, exp.Commit):
        return "COMMIT"
    if isinstance(node, exp.Rollback):
        return "ROLLBACK"
    for kind, label in _WRITE_LABELS:
        if isinstance(node, kind):
            return label
    if sql is not None:
        return _leading_keyword(sql)
    return "SQL"


def _leading_keyword(sql: str) -> str:
    words = _leading_words(sql, 2)
    if len(words) >= 2 and words[0] == "START" and words[1] == "TRANSACTION":
        return "START TRANSACTION"
    if not words:
        return "SQL"
    return words[0]


def _leading_words(sql: str, count: int) -> list[str]:
    words: list[str] = []
    index = 0
    length = len(sql)
    while index < length and len(words) < count:
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            index = length if end < 0 else end + 1
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < length and (sql[index].isalnum() or sql[index] == "_"):
                index += 1
            words.append(sql[start:index].upper())
            continue
        index += 1
    return words


def _reject_casts(statement: exp.Expression) -> None:
    for node in statement.walk():
        if not isinstance(node, exp.Cast):
            continue
        label = _registry_cast(node.args.get("to"))
        if label is not None:
            raise EntitySqlInvalid(f"Cast to {label} is not allowed")


def _registry_cast(target: exp.Expression | None) -> str | None:
    if target is None:
        return None
    if type(target).__name__ == "ObjectIdentifier":
        token = str(target.this).lower()
        if token == "oid" or token.startswith("reg"):
            return token
        return None
    if (
        isinstance(target, exp.DataType)
        and target.this == exp.DataType.Type.USERDEFINED
    ):
        label = _type_label(target.args.get("kind"))
        leaf = label.rsplit(".", 1)[-1].strip('"')
        if leaf == "oid" or leaf.startswith("reg"):
            return label
        return None
    return None


def _type_label(node: exp.Expression | None) -> str:
    if isinstance(node, exp.Identifier):
        return node.this.lower()
    if isinstance(node, exp.Dot):
        return f"{_type_label(node.this)}.{_type_label(node.expression)}"
    if node is None:
        return "unknown"
    return node.sql(dialect=_DIALECT).replace('"', "").lower()


def _reject_functions(statement: exp.Expression) -> None:
    for node in statement.walk():
        if isinstance(node, exp.Func):
            _reject_function(node)


def _reject_function(node: exp.Func) -> None:
    schema = _schema_of_call(node)
    display = _function_display(node)
    if schema:
        raise EntitySqlInvalid(
            f"Schema-qualified function {schema}.{display} is not allowed"
        )
    names = _function_names(node)
    if any(_blocked_function(name) for name in names):
        shown = display if _blocked_function(display) else next(
            name for name in names if _blocked_function(name)
        )
        raise EntitySqlInvalid(f"Function {shown} is not allowed")


def _schema_of_call(node: exp.Func) -> str | None:
    parent = node.parent
    if isinstance(parent, exp.Dot) and parent.expression is node:
        return _qualifier_label(parent.this)
    if (
        isinstance(parent, exp.Table)
        and parent.this is node
        and (parent.args.get("db") or parent.args.get("catalog"))
    ):
        return _table_qualifier(parent)
    return None


def _function_display(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    this = node.this
    if isinstance(this, exp.Identifier):
        return this.this.lower()
    if isinstance(this, str) and this:
        return this.lower()
    words = _leading_words(node.sql(dialect=_DIALECT), 1)
    if words:
        return words[0].lower()
    return node.sql_name().lower()


def _function_names(node: exp.Func) -> list[str]:
    names: list[str] = [_function_display(node)]
    if not isinstance(node, exp.Anonymous):
        names.append(node.sql_name().lower())
        names.append(type(node).__name__.lower())
    return [name for name in names if name]


def _blocked_function(name: str) -> bool:
    if name in {"set_config", "current_setting"}:
        return True
    if name.startswith("pg_"):
        return True
    if name.startswith("has_") and name.endswith("_privilege"):
        return True
    if name.startswith("to_reg"):
        return True
    if name.startswith("lo_"):
        return True
    if name.startswith("dblink"):
        return True
    if name.startswith(
        ("query_to_xml", "table_to_xml", "cursor_to_xml", "schema_to_xml", "database_to_xml")
    ):
        return True
    return False


def _qualifier_label(node: exp.Expression) -> str:
    if isinstance(node, exp.Identifier):
        return node.this.lower()
    if isinstance(node, exp.Dot):
        return f"{_qualifier_label(node.this)}.{_qualifier_label(node.expression)}"
    return node.sql(dialect=_DIALECT).replace('"', "").lower()


def _table_qualifier(table: exp.Table) -> str:
    parts: list[str] = []
    for key in ("catalog", "db"):
        ident = table.args.get(key)
        if isinstance(ident, exp.Identifier):
            parts.append(ident.this.lower())
    return ".".join(parts)


def _bind(
    statement: exp.Expression,
    relations: Mapping[str, str],
    varying: Mapping[str, frozenset[str]],
) -> tuple[set[str], set[EntitySqlColumn]]:
    scopes = list(traverse_scope(statement))
    facts: dict[int, _TableFact] = {}
    entity_maps: dict[int, dict[str, str]] = {}
    blockers: dict[int, set[str]] = {}
    referenced: set[str] = set()
    parsed: dict[str, exp.Table] = {}

    for scope in scopes:
        entities: dict[str, str] = {}
        blocked: set[str] = set()
        cte_names = _cte_folded_names(scope)
        for table in scope.tables:
            fact = facts.get(id(table))
            if fact is None:
                fact = _classify_table(table, cte_names, relations, referenced, parsed)
                facts[id(table)] = fact
            if fact.kind == "entity" and fact.source_key and fact.entity:
                entities[fact.source_key] = fact.entity
            elif fact.source_key:
                blocked.add(fact.source_key)
        for key in scope.sources:
            if key not in entities and key.lower() not in entities:
                blocked.add(key)
                blocked.add(key.lower())
        entity_maps[id(scope)] = entities
        blockers[id(scope)] = blocked

    columns: set[EntitySqlColumn] = set()
    for scope in scopes:
        _collect_columns(scope, entity_maps, blockers, varying, columns)
    return referenced, columns


def _classify_table(
    table: exp.Table,
    cte_names: set[str],
    relations: Mapping[str, str],
    referenced: set[str],
    parsed: dict[str, exp.Table],
) -> _TableFact:
    source_key = _source_key(table)
    if not isinstance(table.this, exp.Identifier):
        return _TableFact("function", source_key, None)
    if table.args.get("db") or table.args.get("catalog"):
        raise EntitySqlInvalid(
            f"Schema-qualified relation {_relation_label(table)} is not allowed"
        )
    folded = _fold_identifier(table.this)
    if folded in cte_names:
        return _TableFact("cte", source_key, None)
    relation = relations.get(folded)
    if relation is None:
        raise EntitySqlNotFound(table.this.this)
    _rewrite(table, relation, parsed)
    referenced.add(folded)
    return _TableFact("entity", source_key, folded)


def _rewrite(table: exp.Table, relation_sql: str, parsed: dict[str, exp.Table]) -> None:
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
    table = _parse_relation(text)
    parsed[text] = table
    return table


def _parse_relation(text: str) -> exp.Table:
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"relation identifier is not a table: {text}")
    try:
        statements = [
            item
            for item in parse(f"SELECT 1 FROM {text}", read=_DIALECT)
            if item is not None and not isinstance(item, exp.Semicolon)
        ]
    except SqlglotError as exc:
        raise ValueError(f"relation identifier is not a table: {text}") from exc
    source = statements[0].args.get("from_") if len(statements) == 1 else None
    table = source.this if source is not None else None
    if (
        not isinstance(table, exp.Table)
        or not isinstance(table.this, exp.Identifier)
        or table.args.get("alias") is not None
        or table.args.get("only")
    ):
        raise ValueError(f"relation identifier is not a table: {text}")
    return table


def _collect_columns(
    scope: Scope,
    entity_maps: dict[int, dict[str, str]],
    blockers: dict[int, set[str]],
    varying: Mapping[str, frozenset[str]],
    found: set[EntitySqlColumn],
) -> None:
    expression = scope.expression
    if isinstance(expression, exp.Select):
        for projection in expression.selects:
            node = _unwrap_projection(projection)
            if isinstance(node, exp.Star):
                _add_star(scope, None, entity_maps, blockers, varying, found)
            elif isinstance(node, exp.Column) and node.name == "*":
                _add_star(
                    scope,
                    _column_qualifier(node),
                    entity_maps,
                    blockers,
                    varying,
                    found,
                )
    for column in scope.columns:
        if not isinstance(column, exp.Column) or column.name == "*":
            continue
        if column.args.get("db"):
            raise EntitySqlInvalid(
                f"Schema-qualified relation {_column_relation(column)} is not allowed"
            )
        name = (
            _fold_identifier(column.this)
            if isinstance(column.this, exp.Identifier)
            else column.name.lower()
        )
        qualifier = _column_qualifier(column)
        if qualifier is not None:
            entity = _lookup_qualified(scope, qualifier, entity_maps, blockers)
            if entity is not None and name in varying.get(entity, frozenset()):
                found.add(EntitySqlColumn(entity, name))
            continue
        for entity in _lookup_unqualified(scope, name, entity_maps, varying):
            found.add(EntitySqlColumn(entity, name))


def _unwrap_projection(node: exp.Expression) -> exp.Expression:
    for _ in range(5):
        if isinstance(node, (exp.Alias, exp.Paren)):
            node = node.this
            continue
        break
    return node


def _add_star(
    scope: Scope,
    qualifier: str | None,
    entity_maps: dict[int, dict[str, str]],
    blockers: dict[int, set[str]],
    varying: Mapping[str, frozenset[str]],
    found: set[EntitySqlColumn],
) -> None:
    if qualifier is None:
        names = set(entity_maps.get(id(scope), {}).values())
    else:
        entity = _lookup_qualified(scope, qualifier, entity_maps, blockers)
        names = set() if entity is None else {entity}
    for entity in names:
        for column in varying.get(entity, frozenset()):
            found.add(EntitySqlColumn(entity, column))


def _lookup_qualified(
    scope: Scope,
    key: str,
    entity_maps: dict[int, dict[str, str]],
    blockers: dict[int, set[str]],
) -> str | None:
    current: Scope | None = scope
    while current is not None:
        entities = entity_maps.get(id(current), {})
        if key in entities:
            return entities[key]
        if key in blockers.get(id(current), ()):
            return None
        current = current.parent
    return None


def _lookup_unqualified(
    scope: Scope,
    column: str,
    entity_maps: dict[int, dict[str, str]],
    varying: Mapping[str, frozenset[str]],
) -> list[str]:
    current: Scope | None = scope
    while current is not None:
        hits: list[str] = []
        seen: set[str] = set()
        for entity in entity_maps.get(id(current), {}).values():
            if entity in seen:
                continue
            seen.add(entity)
            if column in varying.get(entity, frozenset()):
                hits.append(entity)
        if hits:
            return hits
        current = current.parent
    return []


def _cte_folded_names(scope: Scope) -> set[str]:
    names: set[str] = set()
    for cte_scope in scope.cte_sources.values():
        ident = _cte_identifier(cte_scope)
        if ident is not None:
            names.add(_fold_identifier(ident))
    return names


def _cte_identifier(cte_scope: Scope) -> exp.Identifier | None:
    node: exp.Expression | None = cte_scope.expression
    for _ in range(6):
        if node is None:
            return None
        if isinstance(node, exp.CTE):
            alias = node.args.get("alias")
            ident = alias.this if alias is not None else None
            if isinstance(ident, exp.Identifier):
                return ident
            return None
        node = node.parent
    return None


def _source_key(table: exp.Table) -> str | None:
    alias = table.args.get("alias")
    if alias is not None and isinstance(alias.this, exp.Identifier):
        return _fold_identifier(alias.this)
    if isinstance(table.this, exp.Identifier):
        return _fold_identifier(table.this)
    if table.alias:
        return table.alias.lower()
    return None


def _fold_identifier(identifier: exp.Identifier) -> str:
    if identifier.quoted:
        return identifier.this
    return identifier.this.lower()


def _relation_label(table: exp.Table) -> str:
    parts: list[str] = []
    for key in ("catalog", "db"):
        ident = table.args.get(key)
        if isinstance(ident, exp.Identifier):
            parts.append(_sql_ident(ident))
    if isinstance(table.this, exp.Identifier):
        parts.append(_sql_ident(table.this))
    return ".".join(parts)


def _column_qualifier(column: exp.Column) -> str | None:
    ident = column.args.get("table")
    if isinstance(ident, exp.Identifier):
        return _fold_identifier(ident)
    if column.table:
        return column.table.lower()
    return None


def _column_relation(column: exp.Column) -> str:
    parts: list[str] = []
    for key in ("db", "table"):
        ident = column.args.get(key)
        if isinstance(ident, exp.Identifier):
            parts.append(_sql_ident(ident))
    return ".".join(parts)


def _sql_ident(identifier: exp.Identifier) -> str:
    if identifier.quoted:
        return f'"{identifier.this}"'
    return identifier.this


__all__ = [
    "EntitySqlBound",
    "EntitySqlColumn",
    "EntitySqlError",
    "EntitySqlInvalid",
    "EntitySqlNotFound",
    "bind_entity_sql",
]
