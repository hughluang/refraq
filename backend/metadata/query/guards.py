"""L4 SQL statement guards — dialect-aware AST allowlist, fail-closed."""

from __future__ import annotations

import re

from sqlglot import exp, parse
from sqlglot.errors import ParseError, SqlglotError

from backend.metadata.errors import QueryMultiStatement, QueryNotReadonly

_DIALECT_BY_ENGINE: dict[str, str] = {
    "postgresql": "postgres",
    "mssql": "tsql",
    "oracle": "oracle",
}

_ALLOWED_ROOT_TYPES = (exp.Select, exp.Union, exp.Intersect, exp.Except)

_FORBIDDEN_EXPRESSION_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Merge,
    exp.Copy,
    exp.Command,
    exp.Transaction,
    exp.Lock,
)

_BLOCKED_FUNCTION_NAMES = frozenset(
    {
        "pg_read_file",
        "pg_write_file",
        "pg_sleep",
        "lo_export",
        "dblink",
        "dblink_exec",
        "openrowset",
        "xp_cmdshell",
        "sp_executesql",
    }
)


class SqlNotOneStatement(Exception):
    """The text is empty, unreadable, or more than one statement.

    This is a count, not a Controlled Query guard. Callers must not map it to
    ``QUERY_MULTI_STATEMENT`` or ``QUERY_NOT_READONLY``.
    """


_PERCENT_S = re.compile(r"%s")
_ORACLE_POSITIONAL = re.compile(r":[1-9]\d*")
_STATEMENT_BREAK = re.compile(r";")


def prove_one_statement(sql: str, *, engine: str) -> None:
    """Reject text that is not exactly one statement for ``engine``.

    One trailing semicolon is ignored. The statement is not rewritten, and
    statement kind is not restricted. An engine bind marker (``%s`` or
    ``:1``, ``:2``, ...) does not split or reject that one statement.
    Hiding a marker for the count does not hide a later statement.
    """
    dialect = _DIALECT_BY_ENGINE.get((engine or "").strip().lower())
    if dialect is None or not _exactly_one_statement(sql, dialect):
        raise SqlNotOneStatement("SQL must be exactly one statement")


def _exactly_one_statement(sql: str, dialect: str) -> bool:
    cleaned = (sql or "").strip()
    body = cleaned[:-1].strip() if cleaned.endswith(";") else cleaned
    if not body:
        return False
    count = _statement_count(body, dialect)
    if count is not None:
        return count == 1
    masked = _mask_bind_placeholders(body, dialect)
    if masked == body:
        return False
    count = _statement_count(masked, dialect)
    if count != 1:
        return False
    # sqlglot folds `IF cond stmt; DROP` into one node once `%s` parses as a
    # placeholder. A break outside quotes and comments is still another statement.
    # Execution keeps `body`.
    return _replace_outside_literals(body, _STATEMENT_BREAK) == body


def _statement_count(body: str, dialect: str) -> int | None:
    try:
        statements = [item for item in parse(body, read=dialect) if item is not None]
    except SqlglotError:
        return None
    return len(statements)


def _mask_bind_placeholders(sql: str, dialect: str) -> str:
    """Copy with bind markers hidden, for the statement count only.

    sqlglot reads MSSQL ``%s`` as modulo and rejects Oracle ``:1``. Markers
    inside quotes and comments stay, so a semicolon in text is still data.
    """
    if dialect == "tsql":
        return _replace_outside_literals(sql, _PERCENT_S)
    if dialect == "oracle":
        return _replace_outside_literals(sql, _ORACLE_POSITIONAL)
    return sql


def _replace_outside_literals(sql: str, pattern: re.Pattern[str]) -> str:
    parts: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            if end < 0:
                parts.append(sql[index:])
                break
            parts.append(sql[index:end])
            index = end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end < 0:
                parts.append(sql[index:])
                break
            parts.append(sql[index : end + 2])
            index = end + 2
            continue
        char = sql[index]
        if char in {"'", '"'}:
            end = _quoted_end(sql, index, char)
            parts.append(sql[index:end])
            index = end
            continue
        match = pattern.match(sql, index)
        if match is not None:
            parts.append("?")
            index = match.end()
            continue
        parts.append(char)
        index += 1
    return "".join(parts)


def _quoted_end(sql: str, index: int, quote: str) -> int:
    cursor = index + 1
    length = len(sql)
    while cursor < length:
        if sql[cursor] == quote:
            if cursor + 1 < length and sql[cursor + 1] == quote:
                cursor += 2
                continue
            return cursor + 1
        cursor += 1
    return length


def dialect_for_engine(engine: str) -> str:
    key = (engine or "").strip().lower()
    dialect = _DIALECT_BY_ENGINE.get(key)
    if dialect is None:
        raise QueryNotReadonly(f"Unsupported engine for SQL guards: {engine}")
    return dialect


def _iter_function_names(statement: exp.Expression) -> set[str]:
    names: set[str] = set()
    for node in statement.walk():
        if isinstance(node, exp.Anonymous):
            names.add(str(node.this).lower())
            continue
        if isinstance(node, exp.Func):
            fn = node.this
            if isinstance(fn, exp.Identifier):
                names.add(str(fn.this).lower())
            elif isinstance(fn, str):
                names.add(fn.lower())
    return names


def assert_readonly_single_statement(sql: str, *, engine: str) -> str:
    """Validate SQL is a single read-only SELECT / set-op via AST.

    Returns the author SQL (trimmed, trailing ``;`` removed) on success.
    Does not rewrite via sqlglot — AST is validation-only.
    """
    cleaned = (sql or "").strip()
    body = cleaned.rstrip(";").strip()
    if not body:
        raise QueryNotReadonly("SQL statement is empty")

    dialect = dialect_for_engine(engine)
    try:
        statements = parse(body, read=dialect)
    except ParseError as exc:
        raise QueryNotReadonly(f"Invalid SQL: {exc}") from exc

    if not statements:
        raise QueryNotReadonly("SQL statement is empty")
    if len(statements) > 1:
        raise QueryMultiStatement()

    statement = statements[0]
    if not isinstance(statement, _ALLOWED_ROOT_TYPES):
        raise QueryNotReadonly()

    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_EXPRESSION_TYPES):
            if isinstance(node, exp.Lock):
                raise QueryNotReadonly("Row locking (FOR UPDATE) is not allowed")
            raise QueryNotReadonly()
        if isinstance(node, exp.Into):
            raise QueryNotReadonly("SELECT INTO is not allowed")

    for function_name in _iter_function_names(statement):
        if function_name in _BLOCKED_FUNCTION_NAMES:
            raise QueryNotReadonly(
                f"Function {function_name} is not allowed in readonly SQL"
            )

    return body
