"""Entity SQL gate: accept, reject, and rewrite. No database."""

from __future__ import annotations

import pytest

from backend.entity.sql_gate import (
    EntitySqlBound,
    EntitySqlColumn,
    EntitySqlInvalid,
    EntitySqlNotFound,
    bind_entity_sql,
)

RELATIONS = {
    "orders": '"entity_access"."orders__p_ab12"',
    "customers": '"entity_access"."customers__p_cd34"',
    "invoices": '"entity_access"."invoices__p_ef56"',
}
VARYING = {
    "orders": frozenset({"price", "region", "__withheld"}),
    "customers": frozenset({"name", "price"}),
    "invoices": frozenset({"amount"}),
}

_ORDERS = '"entity_access"."orders__p_ab12"'
_CUSTOMERS = '"entity_access"."customers__p_cd34"'
_INVOICES = '"entity_access"."invoices__p_ef56"'

_ORDER_COLUMNS = frozenset(
    {
        EntitySqlColumn("orders", "price"),
        EntitySqlColumn("orders", "region"),
        EntitySqlColumn("orders", "__withheld"),
    }
)
_CUSTOMER_COLUMNS = frozenset(
    {
        EntitySqlColumn("customers", "name"),
        EntitySqlColumn("customers", "price"),
    }
)


def _cols(*pairs: tuple[str, str]) -> frozenset[EntitySqlColumn]:
    return frozenset(EntitySqlColumn(table, column) for table, column in pairs)


# label, sql, bound sql, entity table_names, partial columns
ACCEPT = (
    (
        "literal",
        "SELECT 1",
        "SELECT 1",
        frozenset(),
        frozenset(),
    ),
    (
        "trailing semicolon",
        "SELECT price FROM orders;",
        f"SELECT price FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "trailing comment",
        "SELECT price FROM orders; -- tail",
        f"SELECT price FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "named column",
        "SELECT price FROM orders",
        f"SELECT price FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "qualified column",
        "SELECT orders.price FROM orders",
        f"SELECT orders.price FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "existing alias",
        "SELECT o.price FROM orders o",
        f"SELECT o.price FROM {_ORDERS} AS o",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "unqualified column with alias",
        "SELECT price FROM orders o",
        f"SELECT price FROM {_ORDERS} AS o",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "only",
        "SELECT 1 FROM ONLY orders",
        f"SELECT 1 FROM ONLY {_ORDERS} AS orders",
        frozenset({"orders"}),
        frozenset(),
    ),
    (
        "column alias list",
        "SELECT * FROM orders AS o(price, qty)",
        f"SELECT * FROM {_ORDERS} AS o(price, qty)",
        frozenset({"orders"}),
        _ORDER_COLUMNS,
    ),
    (
        "bare star",
        "SELECT * FROM orders",
        f"SELECT * FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        _ORDER_COLUMNS,
    ),
    (
        "alias star",
        "SELECT o.* FROM orders o",
        f"SELECT o.* FROM {_ORDERS} AS o",
        frozenset({"orders"}),
        _ORDER_COLUMNS,
    ),
    (
        "table star does not expand the other side",
        "SELECT orders.* FROM orders JOIN customers ON orders.id = customers.id",
        (
            f"SELECT orders.* FROM {_ORDERS} AS orders "
            f"JOIN {_CUSTOMERS} AS customers ON orders.id = customers.id"
        ),
        frozenset({"orders", "customers"}),
        _ORDER_COLUMNS,
    ),
    (
        "join star expands every entity",
        "SELECT * FROM orders JOIN customers ON orders.id = customers.id",
        (
            f"SELECT * FROM {_ORDERS} AS orders "
            f"JOIN {_CUSTOMERS} AS customers ON orders.id = customers.id"
        ),
        frozenset({"orders", "customers"}),
        _ORDER_COLUMNS | _CUSTOMER_COLUMNS,
    ),
    (
        "join qualified columns",
        "SELECT o.price, c.name FROM orders o JOIN customers c ON o.id = c.order_id",
        (
            f"SELECT o.price, c.name FROM {_ORDERS} AS o "
            f"JOIN {_CUSTOMERS} AS c ON o.id = c.order_id"
        ),
        frozenset({"orders", "customers"}),
        _cols(("orders", "price"), ("customers", "name")),
    ),
    (
        "unqualified column on two entities",
        "SELECT price FROM orders JOIN customers ON orders.id = customers.id",
        (
            f"SELECT price FROM {_ORDERS} AS orders "
            f"JOIN {_CUSTOMERS} AS customers ON orders.id = customers.id"
        ),
        frozenset({"orders", "customers"}),
        _cols(("orders", "price"), ("customers", "price")),
    ),
    (
        "count star is not a column star",
        "SELECT COUNT(*) FROM orders",
        f"SELECT COUNT(*) FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        frozenset(),
    ),
    (
        "aggregate names the column",
        "SELECT count(price) FROM orders",
        f"SELECT COUNT(price) FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "window",
        "SELECT sum(price) OVER (PARTITION BY region ORDER BY price) FROM orders",
        (
            "SELECT SUM(price) OVER (PARTITION BY region ORDER BY price) "
            f"FROM {_ORDERS} AS orders"
        ),
        frozenset({"orders"}),
        _cols(("orders", "price"), ("orders", "region")),
    ),
    (
        "union branches",
        "SELECT price FROM orders UNION SELECT amount FROM invoices",
        (
            f"SELECT price FROM {_ORDERS} AS orders "
            f"UNION SELECT amount FROM {_INVOICES} AS invoices"
        ),
        frozenset({"orders", "invoices"}),
        _cols(("orders", "price"), ("invoices", "amount")),
    ),
    (
        "union all",
        "SELECT 1 FROM orders UNION ALL SELECT 2 FROM customers",
        (
            f"SELECT 1 FROM {_ORDERS} AS orders "
            f"UNION ALL SELECT 2 FROM {_CUSTOMERS} AS customers"
        ),
        frozenset({"orders", "customers"}),
        frozenset(),
    ),
    (
        "intersect",
        "SELECT price FROM orders INTERSECT SELECT amount FROM invoices",
        (
            f"SELECT price FROM {_ORDERS} AS orders "
            f"INTERSECT SELECT amount FROM {_INVOICES} AS invoices"
        ),
        frozenset({"orders", "invoices"}),
        _cols(("orders", "price"), ("invoices", "amount")),
    ),
    (
        "except",
        "SELECT 1 EXCEPT SELECT 2",
        "SELECT 1 EXCEPT SELECT 2",
        frozenset(),
        frozenset(),
    ),
    (
        "subquery star is not an entity star",
        "SELECT * FROM (SELECT price FROM orders) s",
        f"SELECT * FROM (SELECT price FROM {_ORDERS} AS orders) AS s",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "exists subquery",
        "SELECT sku FROM orders WHERE EXISTS (SELECT 1 FROM customers c WHERE c.id = orders.id)",
        (
            "SELECT sku FROM "
            f"{_ORDERS} AS orders WHERE EXISTS("
            f"SELECT 1 FROM {_CUSTOMERS} AS c WHERE c.id = orders.id)"
        ),
        frozenset({"orders", "customers"}),
        frozenset(),
    ),
    (
        "lateral",
        "SELECT name FROM orders o JOIN LATERAL (SELECT name FROM customers c WHERE c.id = o.id) x ON true",
        (
            f"SELECT name FROM {_ORDERS} AS o JOIN LATERAL "
            f"(SELECT name FROM {_CUSTOMERS} AS c WHERE c.id = o.id) AS x ON TRUE"
        ),
        frozenset({"orders", "customers"}),
        _cols(("customers", "name")),
    ),
    (
        "cte binds the inner entity",
        "WITH c AS (SELECT price FROM orders) SELECT * FROM c",
        f"WITH c AS (SELECT price FROM {_ORDERS} AS orders) SELECT * FROM c",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "cte shadows the entity",
        "WITH orders AS (SELECT 1 AS price) SELECT price FROM orders",
        "WITH orders AS (SELECT 1 AS price) SELECT price FROM orders",
        frozenset(),
        frozenset(),
    ),
    (
        "unquoted cte folds onto the entity name",
        "WITH Orders AS (SELECT 1 AS x) SELECT x FROM orders",
        "WITH Orders AS (SELECT 1 AS x) SELECT x FROM orders",
        frozenset(),
        frozenset(),
    ),
    (
        "quoted cte does not shadow",
        'WITH "Orders" AS (SELECT 1 AS x) SELECT x FROM orders',
        f'WITH "Orders" AS (SELECT 1 AS x) SELECT x FROM {_ORDERS} AS orders',
        frozenset({"orders"}),
        frozenset(),
    ),
    (
        "cte uses another entity",
        "WITH orders AS (SELECT price FROM customers) SELECT * FROM orders",
        (
            "WITH orders AS "
            f"(SELECT price FROM {_CUSTOMERS} AS customers) SELECT * FROM orders"
        ),
        frozenset({"customers"}),
        _cols(("customers", "price")),
    ),
    (
        "recursive cte",
        (
            "WITH RECURSIVE t AS ("
            "SELECT price FROM orders "
            "UNION ALL SELECT price FROM t"
            ") SELECT * FROM t"
        ),
        (
            "WITH RECURSIVE t AS ("
            f"SELECT price FROM {_ORDERS} AS orders "
            "UNION ALL SELECT price FROM t) SELECT * FROM t"
        ),
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "unquoted name folds",
        "SELECT Price FROM Orders",
        f"SELECT Price FROM {_ORDERS} AS Orders",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "quoted table name matches exactly",
        'SELECT price FROM "orders"',
        f'SELECT price FROM {_ORDERS} AS "orders"',
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "quoted column does not fold",
        'SELECT "Price" FROM orders',
        f'SELECT "Price" FROM {_ORDERS} AS orders',
        frozenset({"orders"}),
        frozenset(),
    ),
    (
        "withheld column",
        "SELECT __withheld FROM orders",
        f"SELECT __withheld FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        _cols(("orders", "__withheld")),
    ),
    (
        "same entity twice",
        "SELECT * FROM orders o1 JOIN orders o2 ON o1.price = o2.price",
        (
            f"SELECT * FROM {_ORDERS} AS o1 "
            f"JOIN {_ORDERS} AS o2 ON o1.price = o2.price"
        ),
        frozenset({"orders"}),
        _ORDER_COLUMNS,
    ),
    (
        "generate_series stays a function",
        "SELECT generate_series(1, 3)",
        "SELECT GENERATE_SERIES(1, 3)",
        frozenset(),
        frozenset(),
    ),
    (
        "table function",
        "SELECT * FROM generate_series(1, 3) g",
        "SELECT * FROM GENERATE_SERIES(1, 3) AS g",
        frozenset(),
        frozenset(),
    ),
    (
        "current timestamp",
        "SELECT current_timestamp FROM orders",
        f"SELECT CURRENT_TIMESTAMP FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        frozenset(),
    ),
    (
        "upper is allowed",
        "SELECT upper(price) FROM orders",
        f"SELECT UPPER(price) FROM {_ORDERS} AS orders",
        frozenset({"orders"}),
        _cols(("orders", "price")),
    ),
    (
        "dollar quote is one statement",
        "SELECT $$ ; DROP TABLE orders; $$",
        "SELECT ' ; DROP TABLE orders; '",
        frozenset(),
        frozenset(),
    ),
    (
        "tagged dollar quote",
        "SELECT $tag$;$tag$",
        "SELECT ';'",
        frozenset(),
        frozenset(),
    ),
    (
        "extra semicolon",
        "SELECT 1; ;",
        "SELECT 1",
        frozenset(),
        frozenset(),
    ),
    (
        "with ordinality",
        "SELECT * FROM orders WITH ORDINALITY",
        f"SELECT * FROM {_ORDERS} WITH ORDINALITY AS orders",
        frozenset({"orders"}),
        _ORDER_COLUMNS,
    ),
)

# sql, message
INVALID = (
    ("", "SQL statement is empty"),
    ("   ", "SQL statement is empty"),
    ("/* only */", "SQL statement is empty"),
    (";", "SQL statement is empty"),
    ("SELECT 1; SELECT 2", "Multiple statements are not allowed"),
    ("SELECT 1; SELECT 2; -- tail", "Multiple statements are not allowed"),
    ("SELECT 1 /* c */; SELECT 2", "Multiple statements are not allowed"),
    ("INSERT INTO orders VALUES (1)", "INSERT is not allowed"),
    ("UPDATE orders SET price = 1", "UPDATE is not allowed"),
    ("DELETE FROM orders", "DELETE is not allowed"),
    ("DROP TABLE orders", "DROP is not allowed"),
    ("CREATE TABLE t (id int)", "CREATE is not allowed"),
    ("ALTER TABLE orders ADD COLUMN x int", "ALTER is not allowed"),
    ("TRUNCATE orders", "TRUNCATE is not allowed"),
    (
        "MERGE INTO orders USING customers ON TRUE WHEN MATCHED THEN DELETE",
        "MERGE is not allowed",
    ),
    ("COPY orders TO STDOUT", "COPY is not allowed"),
    (
        "WITH x AS (INSERT INTO orders VALUES (1) RETURNING *) SELECT * FROM x",
        "INSERT is not allowed",
    ),
    (
        "WITH x AS (UPDATE orders SET price = 1 RETURNING *) SELECT * FROM x",
        "UPDATE is not allowed",
    ),
    (
        "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
        "DELETE is not allowed",
    ),
    ("SELECT * INTO new_table FROM orders", "SELECT INTO is not allowed"),
    ("SELECT 1 FOR UPDATE", "Row locking (FOR UPDATE) is not allowed"),
    ("SELECT 1 FOR SHARE", "Row locking (FOR SHARE) is not allowed"),
    ("SELECT 1 FOR NO KEY UPDATE", "Row locking (FOR NO KEY UPDATE) is not allowed"),
    ("SELECT 1 FOR KEY SHARE", "Row locking (FOR KEY SHARE) is not allowed"),
    ("SELECT 1 FOR UPDATE NOWAIT", "Row locking (FOR UPDATE NOWAIT) is not allowed"),
    (
        "SELECT 1 FOR UPDATE SKIP LOCKED",
        "Row locking (FOR UPDATE SKIP LOCKED) is not allowed",
    ),
    (
        "SELECT 1 FROM orders FOR SHARE OF orders",
        "Row locking (FOR SHARE OF orders) is not allowed",
    ),
    ("BEGIN", "BEGIN is not allowed"),
    ("COMMIT", "COMMIT is not allowed"),
    ("ROLLBACK", "ROLLBACK is not allowed"),
    ("START TRANSACTION", "START TRANSACTION is not allowed"),
    ("SET search_path TO public", "SET is not allowed"),
    ("RESET search_path", "RESET is not allowed"),
    ("SHOW search_path", "SHOW is not allowed"),
    ("EXPLAIN SELECT 1", "EXPLAIN is not allowed"),
    ("EXPLAIN ANALYZE SELECT 1 FROM orders", "EXPLAIN is not allowed"),
    ("VACUUM orders", "VACUUM is not allowed"),
    ("DO $$ BEGIN NULL; END $$", "DO is not allowed"),
    ("LOCK TABLE orders", "LOCK is not allowed"),
    ("PREPARE s AS SELECT 1", "PREPARE is not allowed"),
    ("CALL proc()", "CALL is not allowed"),
    ("TABLE orders", "TABLE is not allowed"),
    ("VALUES (1)", "VALUES is not allowed"),
    ("LISTEN channel", "LISTEN is not allowed"),
    ("SELECT * FROM public.orders", "Schema-qualified relation public.orders is not allowed"),
    (
        "SELECT * FROM pg_catalog.pg_class",
        "Schema-qualified relation pg_catalog.pg_class is not allowed",
    ),
    (
        'SELECT * FROM "public".orders',
        'Schema-qualified relation "public".orders is not allowed',
    ),
    ("SELECT 't'::regclass", "Cast to regclass is not allowed"),
    ("SELECT 't'::\"regclass\"", "Cast to regclass is not allowed"),
    ("SELECT CAST('t' AS regclass)", "Cast to regclass is not allowed"),
    ("SELECT 't'::oid", "Cast to oid is not allowed"),
    ("SELECT 't'::\"OID\"", "Cast to oid is not allowed"),
    ("SELECT 't'::regtype", "Cast to regtype is not allowed"),
    ("SELECT 't'::regproc", "Cast to regproc is not allowed"),
    ("SELECT 't'::regprocedure", "Cast to regprocedure is not allowed"),
    ("SELECT 't'::regoper", "Cast to regoper is not allowed"),
    ("SELECT 't'::regoperator", "Cast to regoperator is not allowed"),
    ("SELECT 't'::regconfig", "Cast to regconfig is not allowed"),
    ("SELECT 't'::regdictionary", "Cast to regdictionary is not allowed"),
    ("SELECT 't'::regnamespace", "Cast to regnamespace is not allowed"),
    ("SELECT 't'::regrole", "Cast to regrole is not allowed"),
    (
        "SELECT CAST('t' AS pg_catalog.regclass)",
        "Cast to pg_catalog.regclass is not allowed",
    ),
    (
        "SELECT CAST('t' AS \"pg_catalog\".regclass)",
        "Cast to pg_catalog.regclass is not allowed",
    ),
    ("SELECT pg_sleep(1)", "Function pg_sleep is not allowed"),
    ("SELECT pg_sleep_for('1 second')", "Function pg_sleep_for is not allowed"),
    ("SELECT pg_sleep_until(now())", "Function pg_sleep_until is not allowed"),
    ("SELECT set_config('a', 'b', false)", "Function set_config is not allowed"),
    ("SELECT current_setting('a')", "Function current_setting is not allowed"),
    ("SELECT pg_get_viewdef('v')", "Function pg_get_viewdef is not allowed"),
    ("SELECT pg_read_file('a')", "Function pg_read_file is not allowed"),
    ("SELECT pg_write_file('a', 'b')", "Function pg_write_file is not allowed"),
    (
        "SELECT has_table_privilege('t', 'select')",
        "Function has_table_privilege is not allowed",
    ),
    (
        "SELECT has_schema_privilege('public', 'usage')",
        "Function has_schema_privilege is not allowed",
    ),
    ("SELECT to_regclass('t')", "Function to_regclass is not allowed"),
    ("SELECT to_regtype('int')", "Function to_regtype is not allowed"),
    ("SELECT lo_export(1, '/tmp/x')", "Function lo_export is not allowed"),
    ("SELECT lo_import('/tmp/x')", "Function lo_import is not allowed"),
    ("SELECT dblink('c', 'select 1')", "Function dblink is not allowed"),
    ("SELECT dblink_exec('c', 'select 1')", "Function dblink_exec is not allowed"),
    (
        "SELECT query_to_xml('select 1', true, false, '')",
        "Function query_to_xml is not allowed",
    ),
    (
        "SELECT query_to_xmlschema('select 1', true, false, '')",
        "Function query_to_xmlschema is not allowed",
    ),
    (
        "SELECT query_to_xml_and_xmlschema('select 1', true, false, '')",
        "Function query_to_xml_and_xmlschema is not allowed",
    ),
    (
        "SELECT table_to_xml('orders', true, false, '')",
        "Function table_to_xml is not allowed",
    ),
    (
        "SELECT cursor_to_xml('c', 1, true, false, '')",
        "Function cursor_to_xml is not allowed",
    ),
    (
        "SELECT schema_to_xml('public', true, false, '')",
        "Function schema_to_xml is not allowed",
    ),
    (
        "SELECT database_to_xml(true, false, '')",
        "Function database_to_xml is not allowed",
    ),
    (
        "SELECT pg_catalog.pg_sleep(1)",
        "Schema-qualified function pg_catalog.pg_sleep is not allowed",
    ),
    (
        "SELECT public.set_config('a', 'b', false)",
        "Schema-qualified function public.set_config is not allowed",
    ),
    (
        "SELECT pg_catalog.upper('a')",
        "Schema-qualified function pg_catalog.upper is not allowed",
    ),
    (
        "SELECT * FROM pg_catalog.generate_series(1, 3) g",
        "Schema-qualified function pg_catalog.generate_series is not allowed",
    ),
)

# sql, submitted name
NOT_FOUND = (
    ("SELECT * FROM missing", "missing"),
    ("SELECT * FROM Other", "Other"),
    ('SELECT * FROM "Orders"', "Orders"),
    ('SELECT * FROM "nope"', "nope"),
    ("SELECT * FROM orders JOIN missing ON true", "missing"),
)


@pytest.mark.parametrize(
    ("label", "sql", "bound", "entities", "columns"),
    ACCEPT,
    ids=[case[0] for case in ACCEPT],
)
def test_bind_entity_sql_accepts(
    label: str,
    sql: str,
    bound: str,
    entities: frozenset[str],
    columns: frozenset[EntitySqlColumn],
) -> None:
    result = bind_entity_sql(sql, relations=RELATIONS, row_varying_columns=VARYING)
    assert isinstance(result, EntitySqlBound)
    assert result.bound_sql == bound, label
    assert result.entities == entities
    assert result.partial_columns == columns


@pytest.mark.parametrize(("sql", "message"), INVALID)
def test_bind_entity_sql_rejects(sql: str, message: str) -> None:
    with pytest.raises(EntitySqlInvalid) as caught:
        bind_entity_sql(sql, relations=RELATIONS, row_varying_columns=VARYING)
    assert str(caught.value) == message
    assert caught.value.message == message


@pytest.mark.parametrize(("sql", "name"), NOT_FOUND)
def test_bind_entity_sql_unknown_name(sql: str, name: str) -> None:
    with pytest.raises(EntitySqlNotFound) as caught:
        bind_entity_sql(sql, relations=RELATIONS, row_varying_columns=VARYING)
    assert caught.value.name == name
    assert str(caught.value) == f"unknown name: {name}"


def test_invalid_sql_names_the_parse_failure() -> None:
    with pytest.raises(EntitySqlInvalid, match="^Invalid SQL:") as caught:
        bind_entity_sql("SELECT (", relations=RELATIONS)
    message = caught.value.message
    assert message == str(caught.value)
    assert message == (
        "Invalid SQL: Required keyword: 'this' missing for "
        "<class 'sqlglot.expressions.core.Paren'> at line 1, column 8"
    )
    assert "\x1b" not in message
    assert "\n" not in message
    assert "\r" not in message


@pytest.mark.parametrize(
    ("sql", "message"),
    (
        ("SELECT 'unterminated", "Invalid SQL: Missing ' from 1:7"),
        ('SELECT "unterminated', 'Invalid SQL: Missing " from 1:7'),
        ("SELECT $$unterminated", "Invalid SQL: Missing $$ from 1:7"),
    ),
)
def test_tokenizer_failure_is_invalid_sql(sql: str, message: str) -> None:
    with pytest.raises(EntitySqlInvalid) as caught:
        bind_entity_sql(sql, relations=RELATIONS)
    assert caught.value.message == message
    assert str(caught.value) == message
    assert "\x1b" not in message
    assert "\n" not in message
    assert "\r" not in message


def test_comment_inside_one_statement_still_binds() -> None:
    result = bind_entity_sql(
        "SELECT price FROM orders /* ; DROP TABLE orders */",
        relations=RELATIONS,
        row_varying_columns=VARYING,
    )
    assert result.entities == frozenset({"orders"})
    assert result.bound_sql.startswith(f"SELECT price FROM {_ORDERS} AS orders")
    assert result.partial_columns == _cols(("orders", "price"))


def test_relation_identifier_must_be_a_table() -> None:
    with pytest.raises(ValueError, match="relation identifier"):
        bind_entity_sql("SELECT 1 FROM orders", relations={"orders": "SELECT 1"})


def test_missing_row_varying_map_adds_no_columns() -> None:
    result = bind_entity_sql("SELECT * FROM orders", relations=RELATIONS)
    assert result.entities == frozenset({"orders"})
    assert result.partial_columns == frozenset()
