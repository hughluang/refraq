"""L4 SQL statement guards — dialect-aware AST allowlist, fail-closed."""

from __future__ import annotations

from sqlglot import exp, parse
from sqlglot.errors import ParseError

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


def _dialect_for_engine(engine: str) -> str:
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

    dialect = _dialect_for_engine(engine)
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
