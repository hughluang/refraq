"""SQL fragment splitting and equi-join extraction for join detection."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError, TokenError
from sqlglot.optimizer.qualify import qualify

from backend.metadata.query.guards import dialect_for_engine

_SQL_FRAGMENT_RE = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO)\b",
    re.IGNORECASE,
)
_CREATE_ROUTINE_RE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|PROC|FUNCTION)\b",
    re.IGNORECASE,
)
_PROCEDURAL_SKIP_RE = re.compile(
    r"^(?:SET\s+\w+|DECLARE\b|BEGIN\b|END\b|END\s+LOOP\b|NULL\b|GO\b)\b",
    re.IGNORECASE,
)
_DML_BOUNDARY_RE = re.compile(
    r"(?<![\w.])(SELECT|INSERT\s+INTO|UPDATE\b|DELETE\s+FROM|MERGE\s+INTO)\b",
    re.IGNORECASE,
)
_TRAILING_SET_LINE_RE = re.compile(r"^\s*SET\s+\w+", re.IGNORECASE | re.MULTILINE)

# Alias target: (catalog, schema, table)
AliasTarget = tuple[str | None, str | None, str]
# Derived column origin: (catalog, schema, table, column)
ColumnOrigin = tuple[str | None, str | None, str, str]


@dataclass(frozen=True)
class JoinLeaf:
    left_catalog: str | None
    left_schema: str | None
    left_table: str
    left_column: str
    right_catalog: str | None
    right_schema: str | None
    right_table: str
    right_column: str
    join_kind: str
    join_expression: str


@dataclass(frozen=True)
class DefinitionJoinParse:
    leaves: list[JoinLeaf]
    tokenize_errors: int
    parse_errors: int
    alias_unresolved: int = 0

    @property
    def fragment_errors(self) -> int:
        return self.tokenize_errors + self.parse_errors


def _strip_sql_comments(sql: str) -> str:
    out: list[str] = []
    i = 0
    n = len(sql)
    in_string = False
    quote: str | None = None
    while i < n:
        ch = sql[i]
        if in_string:
            out.append(ch)
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:
                    out.append(sql[i + 1])
                    i += 2
                    continue
                in_string = False
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = True
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] not in "\r\n":
                i += 1
            if i < n:
                out.append(sql[i])
                i += 1
            continue
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i + 1 < n and sql[i : i + 2] != "*/":
                i += 1
            i = min(i + 2, n)
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    quote: str | None = None
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_string:
            current.append(ch)
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:
                    current.append(sql[i + 1])
                    i += 2
                    continue
                in_string = False
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = True
            quote = ch
            current.append(ch)
            i += 1
            continue
        if ch in "([":
            depth += 1
            current.append(ch)
            i += 1
            continue
        if ch in ")]":
            depth = max(0, depth - 1)
            current.append(ch)
            i += 1
            continue
        if ch == ";" and depth == 0:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _split_on_dml_boundaries(sql: str) -> list[str]:
    stripped = sql.strip()
    if not stripped:
        return []
    boundaries: list[int] = [0]
    depth = 0
    in_string = False
    quote: str | None = None
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_string:
            if ch == quote:
                if i + 1 < n and sql[i + 1] == quote:
                    i += 2
                    continue
                in_string = False
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = True
            quote = ch
            i += 1
            continue
        if ch in "([":
            depth += 1
            i += 1
            continue
        if ch in ")]":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0:
            match = _DML_BOUNDARY_RE.match(sql, i)
            if match and match.start() > 0:
                boundaries.append(match.start())
        i += 1
    boundaries.append(n)
    statements: list[str] = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        stmt = sql[start:end].strip()
        if stmt:
            statements.append(stmt)
    return statements if len(statements) > 1 else [stripped]


def _split_routine_statements(body: str) -> list[str]:
    statements: list[str] = []
    for chunk in _split_statements(body):
        statements.extend(_split_on_dml_boundaries(chunk))
    return statements


def _strip_outer_begin_end(body: str) -> str:
    stripped = body.strip()
    begin = re.match(r"^BEGIN\s*", stripped, re.IGNORECASE)
    if not begin:
        return stripped
    inner = stripped[begin.end() :].strip()
    end = re.search(r"\s+END\s*$", inner, re.IGNORECASE)
    if end:
        inner = inner[: end.start()].strip()
    return inner


def _extract_routine_body(sql: str) -> str | None:
    match = _CREATE_ROUTINE_RE.search(sql)
    if not match:
        return None
    rest = sql[match.end() :]
    as_match = re.search(r"\bAS\b", rest, re.IGNORECASE)
    if not as_match:
        return rest.strip() or None
    body = rest[as_match.end() :].strip()
    return _strip_outer_begin_end(body)


def _trim_trailing_procedural(stmt: str) -> str:
    match = _TRAILING_SET_LINE_RE.search(stmt)
    if match and match.start() > 0:
        return stmt[: match.start()].strip()
    return stmt.strip()


def _is_skippable_statement(stmt: str) -> bool:
    if not stmt.strip():
        return True
    if _PROCEDURAL_SKIP_RE.match(stmt.strip()):
        return True
    return stmt.strip().upper().startswith("SET NOCOUNT")


def _extract_select_subqueries(stmt: str) -> list[str]:
    found: list[str] = []
    i = 0
    n = len(stmt)
    while i < n:
        if stmt[i] != "(":
            i += 1
            continue
        depth = 1
        j = i + 1
        inner_start = j
        while j < n and depth > 0:
            if stmt[j] == "(":
                depth += 1
            elif stmt[j] == ")":
                depth -= 1
            j += 1
        inner = stmt[inner_start : j - 1].strip()
        if re.match(r"SELECT\b", inner, re.IGNORECASE):
            found.append(inner)
        i = j
    return found


def iter_sql_fragments(definition: str) -> Iterable[str]:
    stripped = definition.strip()
    if not stripped:
        return
    uncommented = _strip_sql_comments(stripped).strip()
    if not uncommented:
        return
    routine_body = _extract_routine_body(uncommented)
    if routine_body is not None:
        for stmt in _split_routine_statements(routine_body):
            stmt = _trim_trailing_procedural(stmt)
            if _is_skippable_statement(stmt):
                continue
            yield stmt
            yield from _extract_select_subqueries(stmt)
        return
    upper = uncommented.upper()
    if upper.startswith(("SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "MERGE")):
        yield uncommented
        return
    if upper.startswith("CREATE") and not _CREATE_ROUTINE_RE.search(uncommented):
        yield uncommented
        return
    statements = _split_statements(uncommented)
    if len(statements) > 1:
        for stmt in statements:
            if _is_skippable_statement(stmt):
                yield from _extract_select_subqueries(stmt)
                continue
            if _SQL_FRAGMENT_RE.search(stmt):
                yield stmt
            yield from _extract_select_subqueries(stmt)
        return
    yield uncommented


def _fold(value: str | None) -> str:
    return (value or "").casefold()


def _table_ref(table: exp.Table, default_schema: str | None) -> AliasTarget:
    catalog = str(table.catalog) if table.catalog else None
    schema = str(table.db) if table.db else default_schema
    return (catalog, schema, str(table.name))


def _physical_alias_map(
    tree: exp.Expression, default_schema: str | None
) -> dict[str, AliasTarget]:
    """Map physical table aliases/names to (catalog, schema, table). Skips CTE names."""
    cte_names = {
        str(cte.alias).upper()
        for cte in tree.find_all(exp.CTE)
        if cte.alias
    }
    alias_map: dict[str, AliasTarget] = {}
    for table in tree.find_all(exp.Table):
        table_name = table.name
        if not table_name:
            continue
        if str(table_name).upper() in cte_names:
            continue
        target = _table_ref(table, default_schema)
        alias = table.alias_or_name
        if alias:
            alias_map[str(alias)] = target
        alias_map[str(table_name)] = target
    return alias_map


def _from_sources(select: exp.Select) -> list[exp.Expression]:
    """Immediate FROM / JOIN sources (tables and subqueries), not nested ones."""
    sources: list[exp.Expression] = []
    from_clause = select.args.get("from_") or select.args.get("from")
    if from_clause is not None and from_clause.this is not None:
        sources.append(from_clause.this)
    for join in select.args.get("joins") or []:
        this = join.this
        if this is not None:
            sources.append(this)
    return sources


def _star_passthrough_table(
    select: exp.Select,
    physical: dict[str, AliasTarget],
    derived: dict[str, dict[str, ColumnOrigin] | AliasTarget],
) -> AliasTarget | None:
    """If SELECT is only ``*`` / ``alias.*`` from one physical/passthrough source, return it."""
    exprs = list(select.expressions or [])
    if len(exprs) != 1:
        return None
    expr = exprs[0]
    table_key: str | None = None
    if isinstance(expr, exp.Star):
        table_key = None
    elif isinstance(expr, exp.Column) and isinstance(expr.this, exp.Star):
        table_key = str(expr.table) if expr.table else None
    else:
        return None

    def _lookup(key: str) -> AliasTarget | None:
        if key in physical:
            return physical[key]
        mapped = derived.get(key)
        if isinstance(mapped, tuple):
            return mapped
        return None

    if table_key:
        return _lookup(table_key)

    sources = _from_sources(select)
    if len(sources) != 1:
        return None
    source = sources[0]
    if isinstance(source, exp.Table):
        name = source.alias_or_name or source.name
        return _lookup(str(name)) if name else None
    if isinstance(source, exp.Subquery) and source.alias:
        return _lookup(str(source.alias))
    return None


def _origin_from_column(
    column: exp.Column,
    physical: dict[str, AliasTarget],
    derived: dict[str, dict[str, ColumnOrigin] | AliasTarget],
    default_schema: str | None,
) -> ColumnOrigin | None:
    table = str(column.table) if column.table else ""
    col_name = str(column.name)
    if table and table in physical:
        cat, schema, real = physical[table]
        return (cat, schema or default_schema, real, col_name)
    if table and table in derived:
        mapped = derived[table]
        if isinstance(mapped, tuple):
            cat, schema, real = mapped
            return (cat, schema or default_schema, real, col_name)
        origin = mapped.get(_fold(col_name))
        if origin is not None:
            return origin
        return None
    if not table and len(physical) == 1 and not derived:
        cat, schema, real = next(iter(physical.values()))
        return (cat, schema or default_schema, real, col_name)
    return None


def _select_output_origins(
    select: exp.Expression,
    physical: dict[str, AliasTarget],
    derived: dict[str, dict[str, ColumnOrigin] | AliasTarget],
    default_schema: str | None,
) -> dict[str, ColumnOrigin] | AliasTarget | None:
    if not isinstance(select, exp.Select):
        return None
    passthrough = _star_passthrough_table(select, physical, derived)
    if passthrough is not None:
        return passthrough
    origins: dict[str, ColumnOrigin] = {}
    for expr in select.expressions or []:
        output_name: str | None = None
        column: exp.Column | None = None
        if isinstance(expr, exp.Alias):
            output_name = str(expr.alias) if expr.alias else None
            if isinstance(expr.this, exp.Column):
                column = expr.this
        elif isinstance(expr, exp.Column):
            column = expr
            output_name = str(expr.alias_or_name)
        if column is None or not output_name:
            continue
        origin = _origin_from_column(column, physical, derived, default_schema)
        if origin is not None:
            origins[_fold(output_name)] = origin
    return origins


def _derived_alias_map(
    tree: exp.Expression,
    physical: dict[str, AliasTarget],
    default_schema: str | None,
) -> dict[str, dict[str, ColumnOrigin] | AliasTarget]:
    """Map CTE / subquery aliases to column origins or a passthrough base table."""
    derived: dict[str, dict[str, ColumnOrigin] | AliasTarget] = {}

    # CTEs in definition order so later CTEs can reference earlier ones.
    for cte in tree.find_all(exp.CTE):
        alias = str(cte.alias) if cte.alias else ""
        if not alias:
            continue
        select = cte.this
        # Nested physical aliases inside this CTE body.
        local_physical = dict(physical)
        local_physical.update(_physical_alias_map(select, default_schema))
        origins = _select_output_origins(
            select, local_physical, derived, default_schema
        )
        if origins is not None:
            derived[alias] = origins

    for subquery in tree.find_all(exp.Subquery):
        alias = str(subquery.alias) if subquery.alias else ""
        if not alias:
            continue
        select = subquery.this
        local_physical = dict(physical)
        local_physical.update(_physical_alias_map(select, default_schema))
        origins = _select_output_origins(
            select, local_physical, derived, default_schema
        )
        if origins is not None:
            derived[alias] = origins

    return derived


def _column_target(
    column: exp.Column,
    physical: dict[str, AliasTarget],
    derived: dict[str, dict[str, ColumnOrigin] | AliasTarget],
    default_schema: str | None,
) -> ColumnOrigin | None:
    """Resolve a join-side column to a base (catalog, schema, table, column).

    Unknown qualifiers are not treated as table names (no inventing endpoints).
    """
    return _origin_from_column(column, physical, derived, default_schema)


def _qualified_eq_sql(left: ColumnOrigin, right: ColumnOrigin) -> str:
    left_col = exp.column(left[3], table=left[2], db=left[1], catalog=left[0])
    right_col = exp.column(right[3], table=right[2], db=right[1], catalog=right[0])
    return exp.EQ(this=left_col, expression=right_col).sql()


def parse_join_leaves(
    tree: exp.Expression, *, default_schema: str | None
) -> tuple[list[JoinLeaf], int]:
    physical = _physical_alias_map(tree, default_schema)
    derived = _derived_alias_map(tree, physical, default_schema)
    leaves: list[JoinLeaf] = []
    alias_unresolved = 0
    seen_join_pair: set[tuple[str, str, str, str, str, str, str, str]] = set()

    def _is_column_pair_eq(node: exp.Expression) -> tuple[exp.Column, exp.Column] | None:
        if not isinstance(node, exp.EQ):
            return None
        left, right = node.left, node.right
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            return left, right
        return None

    def _append(
        *,
        left: exp.Column,
        right: exp.Column,
        join_kind: str,
        require_dedupe: bool,
    ) -> None:
        nonlocal alias_unresolved
        left_origin = _column_target(left, physical, derived, default_schema)
        right_origin = _column_target(right, physical, derived, default_schema)
        if left_origin is None or right_origin is None:
            alias_unresolved += 1
            return
        left_key = (
            _fold(left_origin[0]),
            _fold(left_origin[1]),
            _fold(left_origin[2]),
            _fold(left_origin[3]),
        )
        right_key = (
            _fold(right_origin[0]),
            _fold(right_origin[1]),
            _fold(right_origin[2]),
            _fold(right_origin[3]),
        )
        if left_key == right_key:
            return
        if require_dedupe:
            canonical = tuple(sorted((left_key, right_key)))
            dedupe_key = canonical[0] + canonical[1]
            if dedupe_key in seen_join_pair:
                return
            seen_join_pair.add(dedupe_key)
        leaves.append(
            JoinLeaf(
                left_catalog=left_origin[0],
                left_schema=left_origin[1],
                left_table=left_origin[2],
                left_column=left_origin[3],
                right_catalog=right_origin[0],
                right_schema=right_origin[1],
                right_table=right_origin[2],
                right_column=right_origin[3],
                join_kind=join_kind,
                join_expression=_qualified_eq_sql(left_origin, right_origin),
            )
        )

    for join in tree.find_all(exp.Join):
        on_expr = join.args.get("on")
        if on_expr is None:
            continue
        join_kind = str(join.args.get("kind") or "INNER").upper()
        for eq in on_expr.find_all(exp.EQ):
            pair = _is_column_pair_eq(eq)
            if pair is None:
                continue
            left, right = pair
            _append(left=left, right=right, join_kind=join_kind, require_dedupe=False)

    for where in tree.find_all(exp.Where):
        condition = where.this
        if condition is None:
            continue
        for eq in condition.find_all(exp.EQ):
            pair = _is_column_pair_eq(eq)
            if pair is None:
                continue
            left, right = pair
            _append(left=left, right=right, join_kind="IMPLICIT", require_dedupe=True)
    return leaves, alias_unresolved


def parse_definition_joins(
    ddl: str, *, engine: str, default_schema: str | None
) -> DefinitionJoinParse:
    dialect = dialect_for_engine(engine)
    leaves: list[JoinLeaf] = []
    tokenize_errors = 0
    parse_errors = 0
    alias_unresolved = 0
    for fragment in iter_sql_fragments(ddl):
        try:
            tree = parse_one(fragment, dialect=dialect)
        except TokenError:
            tokenize_errors += 1
            continue
        except (SqlglotError, ValueError):
            parse_errors += 1
            continue
        try:
            tree = qualify(
                tree,
                dialect=dialect,
                identify=False,
                validate_qualify_columns=False,
            )
        except Exception:  # noqa: BLE001 — still extract leaves from the unqualified tree
            parse_errors += 1
        frag_leaves, frag_alias = parse_join_leaves(tree, default_schema=default_schema)
        leaves.extend(frag_leaves)
        alias_unresolved += frag_alias
    return DefinitionJoinParse(
        leaves=leaves,
        tokenize_errors=tokenize_errors,
        parse_errors=parse_errors,
        alias_unresolved=alias_unresolved,
    )
