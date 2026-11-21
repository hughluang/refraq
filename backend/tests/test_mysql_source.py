"""MySQL onboarding contracts through the existing Metadata seams."""

from backend.metadata.query.compile_sample import compile_sample_sql
from backend.metadata.type_mappings.seeds import ensure_product_type_mappings
from backend.metadata.type_mappings.service import resolve_normalized_type

import pytest

from backend.metadata.connectors.base import ConnectorError, SourceEndpoint
from backend.metadata.connectors.registry import get_connector
from backend.metadata.connectors.specs import get_connector_spec
from backend.metadata.errors import QueryNotReadonly, SourceAccessInvalid
from backend.metadata.query.guards import assert_readonly_single_statement
from backend.metadata.sources.access import validate_access, project_access


def access(**changes):
    return dict(
        host="db.invalid",
        port=3306,
        username="reader",
        password="unit-secret",
        database="Sales",
        ssl_mode="disable",
        **changes,
    )


def test_mysql_registered_spec_has_one_required_database_scope():
    spec = get_connector_spec("mysql")
    assert get_connector("mysql").engine == "mysql"
    assert "database" in spec["required"]
    assert "schema" not in spec["properties"]
    assert validate_access("mysql", access())["database"] == "Sales"
    assert "password" not in project_access("mysql", access())
    for invalid in [
        dict(access(), schema="other"),
        dict(access(), ssl_mode="require"),
        dict(access(), extra={"ssl": "ignored"}),
    ]:
        with pytest.raises(SourceAccessInvalid):
            validate_access("mysql", invalid)
    missing = access()
    del missing["database"]
    with pytest.raises(SourceAccessInvalid):
        validate_access("mysql", missing)


def test_mysql_guards_and_sample_use_native_dialect():
    assert assert_readonly_single_statement(
        "SELECT `order` FROM `Sales`.`select`", engine="mysql"
    )
    for sql in [
        "SELECT * FROM t FOR UPDATE",
        "SELECT 1 INTO OUTFILE '/tmp/x'",
        "SELECT GET_LOCK('x', 3)",
        "SELECT SLEEP(1)",
        "SELECT @x := 1",
        "SELECT /*+ MAX_EXECUTION_TIME(0) */ 1",
        "SELECT 1 /*! INTO OUTFILE '/tmp/x' */",
    ]:
        with pytest.raises(QueryNotReadonly):
            assert_readonly_single_statement(sql, engine="mysql")
    sql = compile_sample_sql(
        engine="mysql",
        schema_name="Sales",
        object_name="select",
        known_columns={"order"},
        columns=["order"],
        filters=[],
        order_by=[],
        offset=2,
        limit=5,
    )
    assert "`select`" in sql and "`order`" in sql
    assert "LIMIT 5" in sql and "OFFSET 2" in sql


@pytest.mark.parametrize(
    "native, expected",
    [
        ("decimal(20,6) unsigned", "decimal"),
        ("bigint unsigned", "decimal"),
        ("int(11) unsigned", "integer"),
        ("tinyint(1)", "integer"),
        ("time(6)", "interval"),
        ("varbinary(64)", "binary"),
        ("json", "json"),
        ("geometry", "unknown"),
    ],
)
def test_mysql_type_mapping_preserves_native_semantics(native, expected):
    ensure_product_type_mappings()
    assert resolve_normalized_type(engine="mysql", data_type=native) == expected


def test_mysql_driver_options_are_real_and_secrets_are_not_in_url(monkeypatch):
    from backend.metadata.connectors import mysql

    captured = {}
    monkeypatch.setattr(
        mysql, "create_engine", lambda url, **kw: captured.update(url=url, **kw)
    )
    endpoint = SourceEndpoint(
        engine="mysql",
        host="db.invalid",
        port=3306,
        username="reader",
        password="unit-secret",
        database_name="Sales",
        schema_filter="Sales",
        ssl_mode="disable",
    )
    get_connector("mysql")._engine(endpoint, timeout_sec=7)
    assert captured["url"].drivername == "mysql+pymysql"
    assert "unit-secret" not in str(captured["url"])
    assert captured["connect_args"]["read_timeout"] == 7
    assert captured["connect_args"]["local_infile"] is False
    assert captured["connect_args"]["ssl_disabled"] is True


@pytest.mark.parametrize(
    "sql, expected_sql",
    [
        ("SELECT id FROM t", "SELECT id FROM t LIMIT 3"),
        ("SELECT id, id FROM t ORDER BY id", "SELECT id, id FROM t ORDER BY id LIMIT 3"),
        ("SELECT id FROM t LIMIT 1 OFFSET 2", "SELECT id FROM t LIMIT 1 OFFSET 2"),
        ("SELECT id FROM t LIMIT 100 OFFSET 2", "SELECT id FROM t LIMIT 3 OFFSET 2"),
        ("SELECT 1 UNION SELECT 2", "SELECT 1 UNION SELECT 2 LIMIT 3"),
        ("SELECT ':label /*+ 100%'", "SELECT ':label /*+ 100%' LIMIT 3"),
    ],
)
def test_mysql_readonly_applies_timeout_transaction_stream_and_cap(monkeypatch, sql, expected_sql):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from backend.metadata.connectors import mysql

    calls = []

    class Result:
        cursor = SimpleNamespace(description=[("id", 3, None, None, None, None, False)])

        def keys(self):
            return ["id"]

        def __iter__(self):
            return iter([(1,), (2,), (3,)])

    class Connection:
        def exec_driver_sql(self, sql):
            calls.append(sql)
            if sql.startswith("SELECT"):
                return Result()

        def execution_options(self, **options):
            assert options == {"stream_results": True, "no_parameters": True}
            return self

    class Engine:
        disposed = False

        def connect(self):
            return nullcontext(Connection())

        def dispose(self):
            self.disposed = True

    engine = Engine()
    monkeypatch.setattr(mysql, "create_engine", lambda *a, **kw: engine)
    endpoint = SourceEndpoint(
        engine="mysql",
        host="db.invalid",
        port=3306,
        username="reader",
        password="unit-secret",
        database_name="Sales",
        schema_filter="Sales",
        ssl_mode="disable",
    )
    outcome = get_connector("mysql").run_readonly(
        endpoint, sql, max_rows=2, timeout_sec=3
    )
    assert outcome.rows == [[1], [2]] and outcome.truncated
    assert calls == [
        "SET SESSION MAX_EXECUTION_TIME = 3000",
        "SET TRANSACTION READ ONLY",
        "START TRANSACTION READ ONLY",
        expected_sql,
    ]
    assert engine.disposed


@pytest.mark.parametrize("expression_parts", [None, [None], ["order", None]])
def test_mysql_collect_preserves_native_columns_keys_and_quoted_ddl(monkeypatch, expression_parts):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from sqlalchemy.dialects.mysql import dialect as mysql_dialect
    from backend.metadata.connectors import mysql

    calls = []

    class Result:
        def scalar(self):
            return "Sales"

        def mappings(self):
            return [
                {
                    "TABLE_NAME": "select`x",
                    "COLUMN_NAME": "order",
                    "ORDINAL_POSITION": 1,
                    "COLUMN_TYPE": "decimal(20,6) unsigned",
                    "IS_NULLABLE": "NO",
                    "COLUMN_DEFAULT": "0.000000",
                    "COLUMN_COMMENT": "Amount",
                }
            ]

        def first(self):
            return (
                "select`x",
                "CREATE TABLE `select``x` (`order` decimal(20,6) unsigned)",
            )

    class Connection:
        dialect = mysql_dialect()

        def execute(self, sql, params):
            assert params == {"database": "Sales"}
            calls.append(str(sql))
            if "information_schema.STATISTICS" in str(sql):
                parts = expression_parts if expression_parts is not None else ["order"]
                return SimpleNamespace(mappings=lambda: [
                    {"TABLE_NAME": "select`x", "INDEX_NAME": "uq", "COLUMN_NAME": part, "NON_UNIQUE": 0}
                    for part in parts
                ])
            return Result()

        def exec_driver_sql(self, sql):
            calls.append(sql)
            return Result()

    inspector = SimpleNamespace(
        get_table_names=lambda **kw: ["select`x"],
        get_view_names=lambda **kw: [],
        get_table_comment=lambda *a, **kw: {"text": "Table comment"},
        get_pk_constraint=lambda *a, **kw: {"constrained_columns": ["order"]},
        get_foreign_keys=lambda *a, **kw: [
            {
                "name": "fk",
                "constrained_columns": ["order"],
                "referred_schema": "Other",
                "referred_table": "parent",
                "referred_columns": ["id"],
            }
        ],
    )
    engine = SimpleNamespace(
        connect=lambda: nullcontext(Connection()), dispose=lambda: None
    )
    monkeypatch.setattr(mysql, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(mysql, "inspect", lambda conn: inspector)
    endpoint = SourceEndpoint(
        engine="mysql",
        host="db.invalid",
        port=3306,
        username="reader",
        password="unit-secret",
        database_name="Sales",
        schema_filter="Sales",
        ssl_mode="disable",
    )
    if expression_parts is not None:
        with pytest.raises(ConnectorError, match="expression indexes"):
            get_connector("mysql").collect_structure(endpoint)
        assert all(not call.startswith("SHOW CREATE") for call in calls)
        return
    (obj,) = get_connector("mysql").collect_structure(endpoint).objects
    assert obj.schema_name == "Sales" and obj.name == "select`x"
    assert obj.columns[0].data_type == "decimal(20,6) unsigned"
    assert obj.columns[0].default_value == "0.000000" and not obj.columns[0].nullable
    assert obj.primary_key == ["order"] and obj.indexes[0].is_unique
    assert obj.foreign_keys[0].ref_schema == "Other"
    assert calls[-1] == "SHOW CREATE TABLE `Sales`.`select``x`"
    assert obj.ddl.startswith("CREATE TABLE")


@pytest.mark.parametrize(
    "failure, expected",
    [
        (None, "JOB_ENDPOINT_FAILED"),
        (RuntimeError("credentials: unit-secret"), "JOB_ENDPOINT_FAILED"),
    ],
)
def test_mysql_probe_requires_scope_and_redacts_driver_fault(
    monkeypatch, failure, expected
):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from backend.metadata.connectors import mysql
    from backend.metadata.connectors.base import ConnectorError

    class Connection:
        def execute(self, sql, params):
            if failure:
                raise failure
            return SimpleNamespace(scalar=lambda: None)

    engine = SimpleNamespace(
        connect=lambda: nullcontext(Connection()), dispose=lambda: None
    )
    monkeypatch.setattr(mysql, "create_engine", lambda *a, **kw: engine)
    endpoint = SourceEndpoint(
        engine="mysql",
        host="db.invalid",
        port=3306,
        username="reader",
        password="unit-secret",
        database_name="Sales",
        schema_filter="Sales",
        ssl_mode="disable",
    )
    with pytest.raises(ConnectorError) as caught:
        get_connector("mysql").test_connection(endpoint)
    assert caught.value.code == expected
    assert "unit-secret" not in caught.value.message
    if failure is not None:
        import traceback

        assert "unit-secret" not in "".join(traceback.format_exception(caught.value))


def test_mysql_duration_column_preserves_signed_extended_hours(monkeypatch):
    from contextlib import nullcontext
    from datetime import timedelta
    from types import SimpleNamespace

    from pymysql.constants import FIELD_TYPE

    from backend.metadata.connectors import mysql
    from backend.metadata.query.service import _present_query

    value = timedelta(hours=-30, microseconds=-123456)

    class Result:
        cursor = SimpleNamespace(
            description=[("elapsed", FIELD_TYPE.TIME, None, None, None, 6, False)]
        )

        def keys(self):
            return ["elapsed"]

        def __iter__(self):
            return iter([(value,)])

    class Connection:
        def exec_driver_sql(self, sql):
            if sql.startswith("SELECT"):
                return Result()

        def execution_options(self, **options):
            return self

    engine = SimpleNamespace(connect=lambda: nullcontext(Connection()), dispose=lambda: None)
    monkeypatch.setattr(mysql, "create_engine", lambda *args, **kwargs: engine)
    endpoint = SourceEndpoint(
        engine="mysql", host="db.invalid", port=3306, username="reader", password="private",
        database_name="Sales", schema_filter="Sales", ssl_mode="disable",
    )
    result = get_connector("mysql").run_readonly(
        endpoint, "SELECT elapsed FROM t", max_rows=2, timeout_sec=3
    )
    declarations, rows = _present_query(result, "mysql")
    assert declarations[0]["temporal_kind"] == "interval"
    assert declarations[0]["precision"] == 6
    assert declarations[0]["nullable"] is False
    assert rows == [["-P1DT6H0.123456S"]]
