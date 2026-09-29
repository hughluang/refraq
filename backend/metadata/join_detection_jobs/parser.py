"""Query anchoring and equi-join extraction for join detection."""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import ErrorLevel, TokenError
from sqlglot.optimizer.qualify import qualify
from sqlglot.tokens import TokenType

from backend.metadata.query.guards import dialect_for_engine

# Statements that can carry a FROM / USING clause. Closed by SQL grammar.
_QUERY_KEYWORDS = frozenset({"SELECT", "WITH", "UPDATE", "DELETE", "MERGE"})
_QUERY_TYPES = (exp.Query, exp.Update, exp.Delete, exp.Merge)
# sqlglot's signal that parsing stopped because the next token is not part of the statement.
_STOP_DESCRIPTION = "Invalid expression / Unexpected token"
# Tokens that only continue the current query. A stop on one of these is a truncated query.
_QUERY_CONTINUATION = frozenset(
    {
        TokenType.JOIN,
        TokenType.STRAIGHT_JOIN,
        TokenType.ON,
        TokenType.USING,
        TokenType.WHERE,
        TokenType.GROUP_BY,
        TokenType.HAVING,
        TokenType.ORDER_BY,
        TokenType.UNION,
        TokenType.EXCEPT,
        TokenType.INTERSECT,
        TokenType.COMMA,
        TokenType.AND,
        TokenType.OR,
        TokenType.FROM,
        TokenType.INTO,
        TokenType.APPLY,
        TokenType.PIVOT,
        TokenType.UNPIVOT,
        TokenType.QUALIFY,
        TokenType.WINDOW,
        TokenType.LIMIT,
        TokenType.OFFSET,
        TokenType.CONNECT_BY,
        TokenType.START_WITH,
        TokenType.PREWHERE,
        TokenType.EQ,
        TokenType.NEQ,
        TokenType.NULLSAFE_EQ,
        TokenType.LT,
        TokenType.GT,
        TokenType.LTE,
        TokenType.GTE,
        TokenType.PLUS,
        TokenType.DASH,
        TokenType.STAR,
        TokenType.SLASH,
        TokenType.MOD,
        TokenType.DOT,
    }
)

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


def _fold(value: str | None) -> str:
    return (value or "").casefold()


def _node_name(node: object) -> str:
    """sqlglot name properties raise when a node is only partly built."""
    try:
        name = node.name  # type: ignore[attr-defined]
    except AttributeError:
        return ""
    return str(name or "")


def _table_ref(table: exp.Table, default_schema: str | None) -> AliasTarget | None:
    name = _node_name(table)
    if not name:
        return None
    catalog = str(table.catalog) if table.catalog else None
    schema = str(table.db) if table.db else default_schema
    return (catalog, schema, name)


def _physical_alias_map(
    tree: exp.Expression, default_schema: str | None
) -> dict[str, AliasTarget]:
    """Map physical table aliases/names to (catalog, schema, table). Skips CTE names."""
    cte_names = {
        _fold(str(cte.alias))
        for cte in tree.find_all(exp.CTE)
        if cte.alias
    }
    alias_map: dict[str, AliasTarget] = {}
    for table in tree.find_all(exp.Table):
        table_name = _node_name(table)
        if not table_name or _fold(table_name) in cte_names:
            continue
        target = _table_ref(table, default_schema)
        if target is None:
            continue
        alias = table.alias_or_name
        if alias:
            alias_map[_fold(str(alias))] = target
        alias_map[_fold(table_name)] = target
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
    derived: dict[str, dict[str, list[ColumnOrigin]] | AliasTarget],
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
        folded = _fold(key)
        if folded in physical:
            return physical[folded]
        mapped = derived.get(folded)
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
    derived: dict[str, dict[str, list[ColumnOrigin]] | AliasTarget],
    default_schema: str | None,
) -> list[ColumnOrigin]:
    table = _fold(str(column.table)) if column.table else ""
    col_name = str(column.name)
    if table and table in physical:
        cat, schema, real = physical[table]
        return [(cat, schema or default_schema, real, col_name)]
    if table and table in derived:
        mapped = derived[table]
        if isinstance(mapped, tuple):
            cat, schema, real = mapped
            return [(cat, schema or default_schema, real, col_name)]
        found = mapped.get(_fold(col_name))
        if not found:
            return []
        return list(found)
    if not table and len(physical) == 1 and not derived:
        cat, schema, real = next(iter(physical.values()))
        return [(cat, schema or default_schema, real, col_name)]
    return []


def _dedupe_origins(*groups: list[ColumnOrigin]) -> list[ColumnOrigin]:
    seen: set[ColumnOrigin] = set()
    items: list[ColumnOrigin] = []
    for group in groups:
        for origin in group:
            if origin in seen:
                continue
            seen.add(origin)
            items.append(origin)
    return items


def _same_passthrough(left: AliasTarget, right: AliasTarget) -> bool:
    return (
        _fold(left[0]) == _fold(right[0])
        and _fold(left[1]) == _fold(right[1])
        and _fold(left[2]) == _fold(right[2])
    )


def _merge_named_with_passthrough(
    mapped: dict[str, list[ColumnOrigin]],
    passthrough: AliasTarget,
) -> dict[str, list[ColumnOrigin]] | None:
    """A star branch contributes the same output name on its one base table."""
    catalog, schema, table = passthrough
    merged: dict[str, list[ColumnOrigin]] = {}
    for name, origins in mapped.items():
        items = _dedupe_origins(origins, [(catalog, schema, table, name)])
        if items:
            merged[name] = items
    return merged or None


def _merge_output_origins(
    left: dict[str, list[ColumnOrigin]] | AliasTarget | None,
    right: dict[str, list[ColumnOrigin]] | AliasTarget | None,
) -> dict[str, list[ColumnOrigin]] | AliasTarget | None:
    """A set operation exposes one output column from every branch that defines it.

    Two different star passthroughs name no columns, so the output stays unresolved
    instead of keeping one side.
    """
    if isinstance(left, dict) and isinstance(right, dict):
        merged: dict[str, list[ColumnOrigin]] = {}
        for name in set(left) | set(right):
            items = _dedupe_origins(left.get(name, []), right.get(name, []))
            if items:
                merged[name] = items
        return merged or None
    if isinstance(left, dict) and right is None:
        return left
    if isinstance(right, dict) and left is None:
        return right
    if isinstance(left, tuple) and isinstance(right, tuple):
        return left if _same_passthrough(left, right) else None
    if isinstance(left, dict) and isinstance(right, tuple):
        return _merge_named_with_passthrough(left, right)
    if isinstance(right, dict) and isinstance(left, tuple):
        return _merge_named_with_passthrough(right, left)
    return None


def _select_output_origins(
    select: exp.Expression,
    physical: dict[str, AliasTarget],
    derived: dict[str, dict[str, list[ColumnOrigin]] | AliasTarget],
    default_schema: str | None,
) -> dict[str, list[ColumnOrigin]] | AliasTarget | None:
    if isinstance(select, (exp.Union, exp.Except, exp.Intersect)):
        left = _select_output_origins(
            select.this,
            _physical_alias_map(select.this, default_schema),
            derived,
            default_schema,
        )
        right_node = select.expression
        right = (
            _select_output_origins(
                right_node,
                _physical_alias_map(right_node, default_schema),
                derived,
                default_schema,
            )
            if right_node is not None
            else None
        )
        return _merge_output_origins(left, right)
    if not isinstance(select, exp.Select):
        return None
    passthrough = _star_passthrough_table(select, physical, derived)
    if passthrough is not None:
        return passthrough
    origins: dict[str, list[ColumnOrigin]] = {}
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
        found = _origin_from_column(column, physical, derived, default_schema)
        if found:
            origins[_fold(output_name)] = found
    return origins


def _derived_alias_map(
    tree: exp.Expression,
    default_schema: str | None,
) -> dict[str, dict[str, list[ColumnOrigin]] | AliasTarget]:
    """Map CTE / subquery aliases to column origins or a passthrough base table."""
    derived: dict[str, dict[str, list[ColumnOrigin]] | AliasTarget] = {}

    def _register(alias: str, select: exp.Expression) -> None:
        if not alias:
            return
        # Output columns resolve against this query's own tables. Outer tables
        # would make an unqualified column look ambiguous.
        origins = _select_output_origins(
            select,
            _physical_alias_map(select, default_schema),
            derived,
            default_schema,
        )
        if origins is not None:
            derived[_fold(alias)] = origins

    def _register_subqueries(root: exp.Expression) -> None:
        # Deepest first, so an outer select list can see an inner alias.
        for subquery in reversed(list(root.find_all(exp.Subquery))):
            _register(str(subquery.alias) if subquery.alias else "", subquery.this)

    # CTEs in definition order so later CTEs can reference earlier ones.
    for cte in tree.find_all(exp.CTE):
        _register_subqueries(cte.this)
        _register(str(cte.alias) if cte.alias else "", cte.this)

    _register_subqueries(tree)
    return derived


def _qualified_eq_sql(left: ColumnOrigin, right: ColumnOrigin) -> str:
    left_col = exp.column(left[3], table=left[2], db=left[1], catalog=left[0])
    right_col = exp.column(right[3], table=right[2], db=right[1], catalog=right[0])
    return exp.EQ(this=left_col, expression=right_col).sql()


def _as_column(node: exp.Expression) -> exp.Column | None:
    """A column, including a dotted name sqlglot left as identifiers.

    Assigned scalar subqueries (``SELECT @v = (SELECT ...)``) keep ``t.col`` as
    Dot nodes. Those are still column references. Longer identifier chains are
    catalog / schema qualifiers.
    """
    if isinstance(node, exp.Column):
        return node
    parts: list[str] = []
    cur = node
    while isinstance(cur, exp.Dot):
        if not isinstance(cur.expression, exp.Identifier):
            return None
        parts.append(cur.expression.name)
        cur = cur.this
    if not isinstance(cur, exp.Identifier) or not parts:
        return None
    parts.append(cur.name)
    parts.reverse()
    if len(parts) == 2:
        return exp.column(parts[1], table=parts[0])
    if len(parts) == 3:
        return exp.column(parts[2], table=parts[1], db=parts[0])
    if len(parts) == 4:
        return exp.column(parts[3], table=parts[2], db=parts[1], catalog=parts[0])
    return None


def _iter_spine_sources(node: exp.Expression):
    """Tables and subqueries on a FROM / JOIN spine, not sources inside them."""
    if isinstance(node, exp.From):
        if node.this is not None:
            yield from _iter_spine_sources(node.this)
        for join in node.args.get("joins") or []:
            yield from _iter_spine_sources(join)
        return
    if isinstance(node, exp.Join):
        if node.this is not None:
            yield from _iter_spine_sources(node.this)
        return
    if isinstance(node, exp.Table):
        yield node
        for join in node.args.get("joins") or []:
            yield from _iter_spine_sources(join)
        return
    if isinstance(node, exp.Subquery):
        yield node


def _iter_scope_sources(scope: exp.Expression):
    """Immediate inputs of one SELECT or DML statement."""
    if isinstance(scope, exp.Select):
        yield from _from_sources(scope)
        return
    if not isinstance(scope, (exp.Update, exp.Delete, exp.Merge)):
        return
    if scope.this is not None:
        yield scope.this
    from_clause = scope.args.get("from_")
    if from_clause is not None:
        yield from _iter_spine_sources(from_clause)
    for join in scope.args.get("joins") or []:
        yield from _iter_spine_sources(join)


def _is_temporary_table(table: exp.Table) -> bool:
    ident = table.this
    return isinstance(ident, exp.Identifier) and bool(ident.args.get("temporary"))


def _scope_bindings(
    scope: exp.Expression,
    default_schema: str | None,
    cte_names: set[str],
) -> tuple[dict[str, AliasTarget], dict[str, str], dict[str, exp.Expression]]:
    """Physical aliases, CTE-alias redirects, and this scope's subquery bodies.

    A temporary table is not a catalog table. The same alias in another UNION
    branch is a different binding: callers walk ancestor scopes only, and a
    subquery's outputs come from that scope's own body.
    """
    physical: dict[str, AliasTarget] = {}
    cte_alias: dict[str, str] = {}
    subqueries: dict[str, exp.Expression] = {}
    for source in _iter_scope_sources(scope):
        if isinstance(source, exp.Subquery):
            if source.alias:
                subqueries[_fold(str(source.alias))] = source.this
            continue
        if not isinstance(source, exp.Table) or _is_temporary_table(source):
            continue
        name = _node_name(source)
        if not name:
            continue
        alias = source.alias_or_name
        key = _fold(str(alias)) if alias else _fold(name)
        if _fold(name) in cte_names:
            cte_alias[key] = _fold(name)
            continue
        target = _table_ref(source, default_schema)
        if target is None:
            continue
        if alias:
            physical[_fold(str(alias))] = target
        physical[_fold(name)] = target
    return physical, cte_alias, subqueries


def _origins_from_derived(
    mapped: dict[str, list[ColumnOrigin]] | AliasTarget | None,
    col_name: str,
    default_schema: str | None,
) -> list[ColumnOrigin]:
    if isinstance(mapped, tuple):
        catalog, schema, table = mapped
        return [(catalog, schema or default_schema, table, col_name)]
    if not isinstance(mapped, dict):
        return []
    found = mapped.get(_fold(col_name))
    return list(found) if found else []


def _query_outputs(
    body: exp.Expression,
    derived: dict[str, dict[str, list[ColumnOrigin]] | AliasTarget],
    default_schema: str | None,
    cache: dict[int, dict[str, list[ColumnOrigin]] | AliasTarget | None],
) -> dict[str, list[ColumnOrigin]] | AliasTarget | None:
    """Output columns of one subquery body. Outer CTE bindings stay visible."""
    key = id(body)
    if key not in cache:
        local = _derived_alias_map(body, default_schema)
        cache[key] = _select_output_origins(
            body,
            _physical_alias_map(body, default_schema),
            {**derived, **local},
            default_schema,
        )
    return cache[key]


def _origins_in_scope(
    column: exp.Column,
    anchor: exp.Expression,
    derived: dict[str, dict[str, list[ColumnOrigin]] | AliasTarget],
    cte_names: set[str],
    default_schema: str | None,
    cache: dict[
        int, tuple[dict[str, AliasTarget], dict[str, str], dict[str, exp.Expression]]
    ],
    output_cache: dict[int, dict[str, list[ColumnOrigin]] | AliasTarget | None],
) -> list[ColumnOrigin]:
    """Resolve a column from its own SELECT outward, so sibling aliases do not collide."""
    table = _fold(str(column.table)) if column.table else ""
    col_name = str(column.name)
    first = True
    cur: exp.Expression | None = anchor
    while cur is not None:
        if isinstance(cur, (exp.Select, exp.Update, exp.Delete, exp.Merge)):
            key = id(cur)
            if key not in cache:
                cache[key] = _scope_bindings(cur, default_schema, cte_names)
            physical, cte_alias, subqueries = cache[key]
            if table and table in physical:
                catalog, schema, real = physical[table]
                return [(catalog, schema or default_schema, real, col_name)]
            if table and table in cte_alias:
                return _origins_from_derived(
                    derived.get(cte_alias[table]), col_name, default_schema
                )
            if table and table in subqueries:
                return _origins_from_derived(
                    _query_outputs(
                        subqueries[table], derived, default_schema, output_cache
                    ),
                    col_name,
                    default_schema,
                )
            if (
                first
                and not table
                and len(physical) == 1
                and not subqueries
                and not cte_alias
            ):
                catalog, schema, real = next(iter(physical.values()))
                return [(catalog, schema or default_schema, real, col_name)]
            first = False
        cur = cur.parent
    return []


def parse_join_leaves(
    tree: exp.Expression, *, default_schema: str | None
) -> tuple[list[JoinLeaf], int]:
    derived = _derived_alias_map(tree, default_schema)
    cte_names = {
        _fold(str(cte.alias)) for cte in tree.find_all(exp.CTE) if cte.alias
    }
    scope_cache: dict[
        int, tuple[dict[str, AliasTarget], dict[str, str], dict[str, exp.Expression]]
    ] = {}
    output_cache: dict[int, dict[str, list[ColumnOrigin]] | AliasTarget | None] = {}
    leaves: list[JoinLeaf] = []
    alias_unresolved = 0
    seen_join_pair: set[tuple[str, str, str, str, str, str, str, str]] = set()

    def _is_column_pair_eq(node: exp.Expression) -> tuple[exp.Column, exp.Column] | None:
        if not isinstance(node, exp.EQ):
            return None
        left, right = _as_column(node.left), _as_column(node.right)
        if left is not None and right is not None:
            return left, right
        return None

    def _append(
        *,
        left: exp.Column,
        right: exp.Column,
        anchor: exp.Expression,
        join_kind: str,
        require_dedupe: bool,
    ) -> None:
        nonlocal alias_unresolved
        left_origins = _origins_in_scope(
            left, anchor, derived, cte_names, default_schema, scope_cache, output_cache
        )
        right_origins = _origins_in_scope(
            right, anchor, derived, cte_names, default_schema, scope_cache, output_cache
        )
        if not left_origins or not right_origins:
            alias_unresolved += 1
            return
        for left_origin in left_origins:
            for right_origin in right_origins:
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
                    continue
                if require_dedupe:
                    canonical = tuple(sorted((left_key, right_key)))
                    dedupe_key = canonical[0] + canonical[1]
                    if dedupe_key in seen_join_pair:
                        continue
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
            _append(
                left=left, right=right, anchor=eq, join_kind=join_kind, require_dedupe=False
            )

    for where in tree.find_all(exp.Where):
        condition = where.this
        if condition is None:
            continue
        for eq in condition.find_all(exp.EQ):
            pair = _is_column_pair_eq(eq)
            if pair is None:
                continue
            left, right = pair
            _append(
                left=left,
                right=right,
                anchor=eq,
                join_kind="IMPLICIT",
                require_dedupe=True,
            )
    return leaves, alias_unresolved


def _leaf_key(leaf: JoinLeaf) -> tuple:
    left = (
        _fold(leaf.left_catalog),
        _fold(leaf.left_schema),
        _fold(leaf.left_table),
        _fold(leaf.left_column),
    )
    right = (
        _fold(leaf.right_catalog),
        _fold(leaf.right_schema),
        _fold(leaf.right_table),
        _fold(leaf.right_column),
    )
    return tuple(sorted((left, right)))


def _joins_without_source(tree: exp.Expression) -> bool:
    """A JOIN whose SELECT has no FROM is not a query; sqlglot still builds the tree."""
    for select in tree.find_all(exp.Select):
        has_from = select.args.get("from_")
        if select.args.get("joins") and not has_from:
            return True
    return False


class _JoinAcc:
    def __init__(self) -> None:
        self.leaves: list[JoinLeaf] = []
        self.seen: set[tuple] = set()
        self.tokenize_errors = 0
        self.parse_errors = 0
        self.alias_unresolved = 0

    def add_leaves(self, leaves: list[JoinLeaf]) -> None:
        for leaf in leaves:
            key = _leaf_key(leaf)
            if key in self.seen:
                continue
            self.seen.add(key)
            self.leaves.append(leaf)


def _scan_queries(sql: str) -> tuple[list[tuple[int, int]], list[str]]:
    """Locate query spans and single-quoted literal contents.

    The scan only knows quotes, comments, parentheses, and semicolons. A span
    runs from a query keyword to the next semicolon or to the parenthesis that
    closes the subquery containing it. Literal contents are already unescaped
    (``''`` -> ``'``).
    """
    spans_at: list[tuple[int, int]] = []
    events: list[tuple[int, str, int]] = []
    literals: list[str] = []
    i = 0
    n = len(sql)
    depth = 0
    while i < n:
        if sql.startswith("--", i):
            newline = sql.find("\n", i)
            i = n if newline < 0 else newline + 1
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        ch = sql[i]
        if ch == "'":
            i += 1
            buf: list[str] = []
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(sql[i])
                i += 1
            if buf:
                literals.append("".join(buf))
            continue
        if ch == '"':
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            events.append((i, "close", depth))
            depth = max(0, depth - 1)
            i += 1
            continue
        if ch == ";":
            events.append((i, "semi", depth))
            i += 1
            continue
        if ch.isascii() and ch.isalpha():
            boundary = i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] in "_@#$.")
            j = i + 1
            while j < n and sql[j].isascii() and sql[j].isalpha():
                j += 1
            word = sql[i:j].upper()
            trailed = j < n and (sql[j].isalnum() or sql[j] in "_@#$")
            if boundary and word in _QUERY_KEYWORDS and not trailed:
                spans_at.append((i, depth))
            i = j
            continue
        i += 1
    spans: list[tuple[int, int]] = []
    for start, anchor_depth in spans_at:
        end = n
        for pos, kind, event_depth in events:
            if pos <= start:
                continue
            if kind == "semi" or (kind == "close" and event_depth <= anchor_depth):
                end = pos
                break
        spans.append((start, end))
    return spans, literals


def _stop_offset(tokens: list, errors: list[dict]) -> tuple[int | None, bool]:
    """Char offset where parsing stopped, and whether that token only continues a query."""
    stopped = [err for err in errors if err.get("description") == _STOP_DESCRIPTION]
    if not stopped:
        return None, False
    err = stopped[-1]
    token = next(
        (
            tok
            for tok in tokens
            if tok.line == err.get("line") and tok.col == err.get("col")
        ),
        None,
    )
    if token is None:
        return None, False
    return token.start, token.token_type in _QUERY_CONTINUATION


def _consume_queries(
    sql: str,
    dialect: Dialect,
    dialect_name: str,
    default_schema: str | None,
    acc: _JoinAcc,
) -> None:
    spans, literals = _scan_queries(sql)
    covered = -1
    for start, end in spans:
        if start < covered:
            continue
        text = sql[start:end]
        if not text.strip():
            continue
        try:
            tokens = dialect.tokenize(text)
        except TokenError:
            acc.tokenize_errors += 1
            continue
        except Exception:  # noqa: BLE001 — one query must not fail the definition
            acc.parse_errors += 1
            continue
        parser = dialect.parser(error_level=ErrorLevel.IGNORE)
        try:
            trees = parser.parse(tokens, text)
        except TokenError:
            acc.tokenize_errors += 1
            continue
        except Exception:  # noqa: BLE001 — one query must not fail the definition
            acc.parse_errors += 1
            continue
        tree = trees[0] if trees else None
        errors = [err.errors[0] for err in parser.errors if getattr(err, "errors", None)]
        internal = [err for err in errors if err.get("description") != _STOP_DESCRIPTION]
        stop_at, continues = _stop_offset(tokens, errors)
        if (
            tree is None
            or not isinstance(tree, _QUERY_TYPES)
            or internal
            or continues
            or _joins_without_source(tree)
        ):
            acc.parse_errors += 1
            continue
        try:
            raw_leaves, raw_unresolved = parse_join_leaves(
                tree, default_schema=default_schema
            )
        except Exception:  # noqa: BLE001 — one query must not fail the definition
            acc.parse_errors += 1
            continue
        try:
            qualified = qualify(
                tree.copy(),
                dialect=dialect_name,
                identify=False,
                validate_qualify_columns=False,
            )
        except Exception:  # noqa: BLE001 — qualify only adds leaves; the raw tree stands
            qualified = None
        if qualified is not None:
            # qualify rewrites derived-table columns the raw tree cannot resolve,
            # and sometimes rewrites a correlated name so the raw tree is the one
            # that still has the join. Keep both leaves; count misses on the
            # rewritten tree, which is what a single qualify-then-extract pass did.
            try:
                extra, qualified_unresolved = parse_join_leaves(
                    qualified, default_schema=default_schema
                )
            except Exception:  # noqa: BLE001 — raw leaves still stand
                extra, qualified_unresolved = [], raw_unresolved
            acc.alias_unresolved += qualified_unresolved
            acc.add_leaves(extra)
            # Inner queries of this tree are already resolved. When qualify
            # fails, keep them eligible: a smaller inner query often still qualifies.
            # A stop inside the next statement (the error token is past that
            # statement's anchor) must not hide the next statement.
            cover_end = start + (stop_at if stop_at is not None else len(text))
            if stop_at is not None:
                for later, _later_end in spans:
                    if start < later < cover_end:
                        cover_end = later
                        break
            covered = cover_end
        else:
            acc.alias_unresolved += raw_unresolved
        acc.add_leaves(raw_leaves)
    # Same rules as the surrounding text, including failure counts.
    for literal in literals:
        _consume_queries(literal, dialect, dialect_name, default_schema, acc)


def parse_definition_joins(
    ddl: str, *, engine: str, default_schema: str | None
) -> DefinitionJoinParse:
    dialect_name = dialect_for_engine(engine)
    acc = _JoinAcc()
    _consume_queries(ddl, Dialect.get_or_raise(dialect_name), dialect_name, default_schema, acc)
    return DefinitionJoinParse(
        leaves=acc.leaves,
        tokenize_errors=acc.tokenize_errors,
        parse_errors=acc.parse_errors,
        alias_unresolved=acc.alias_unresolved,
    )
