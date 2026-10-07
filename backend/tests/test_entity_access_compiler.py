"""Compiler unit tests and the combination-view property check."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.entity.access.compiler import (
    Policy,
    compile_policy,
    render_shape,
    subject_outcome,
)
from backend.entity.access.dsl import RuleProblem, eval_rule, rule_sql, validate_rule
from backend.entity.access.facts import (
    AttrFact,
    GrantSpec,
    Level,
    Person,
    ProfileSpec,
    RestrictionSpec,
    SubjectAttrFact,
)
from backend.entity.access.masks import ModeError, validate_levels
from backend.tests.entity_access_oracle import project_subject, render_grant_select

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)
SOURCE = 'entity_data."customer__v3__9f1c2a7b4d6e8f00"'


def _customer_policy() -> tuple[Policy, dict[str, Person]]:
    name = AttrFact("att_name", "name", "string", max_length=64)
    mobile = AttrFact("att_mobile", "mobile", "string", max_length=32)
    card = AttrFact("att_id_card", "id_card_no", "string", max_length=32)
    region = AttrFact(
        "att_region",
        "region",
        "dictionary",
        dictionary_id="dct_region",
        codes=("EAST", "SOUTH", "SW", "TEST"),
    )
    manager = AttrFact("att_manager", "account_manager", "string", max_length=64)
    credit = AttrFact("att_credit", "credit_limit", "decimal", precision=12, scale=2)
    attributes = (name, mobile, card, region, manager, credit)
    ladders = {
        "att_mobile": (
            Level("clear", "clear"),
            Level("mask3", {"type": "partial", "keep_first": 3, "keep_last": 4}),
        ),
        "att_id_card": (
            Level("clear", "clear"),
            Level("last4", {"type": "partial", "keep_first": 0, "keep_last": 4}),
        ),
    }
    sales = ProfileSpec(
        "eap_sales",
        "sales",
        (
            ("att_name", "clear"),
            ("att_mobile", "clear"),
            ("att_region", "clear"),
            ("att_manager", "clear"),
        ),
    )
    finance = ProfileSpec(
        "eap_finance",
        "finance",
        (
            ("att_name", "clear"),
            ("att_id_card", "last4"),
            ("att_region", "clear"),
            ("att_manager", "clear"),
            ("att_credit", "clear"),
        ),
    )
    service = ProfileSpec(
        "eap_service",
        "service",
        (
            ("att_name", "clear"),
            ("att_mobile", "mask3"),
            ("att_region", "clear"),
        ),
    )
    grants = (
        GrantSpec(
            "g_sales_region",
            "role",
            "role_sales",
            "eap_sales",
            {"in": {"attr": "att_region", "subject_attr": "regions"}},
            frozenset({"read", "mcp_query"}),
            "active",
            None,
        ),
        GrantSpec(
            "g_fin_audit",
            "role",
            "role_finance",
            "eap_finance",
            {"gte": {"attr": "att_credit", "value": 50000}},
            frozenset({"read", "mcp_query"}),
            "active",
            None,
        ),
        GrantSpec(
            "g_fin_user",
            "user",
            "user_liu",
            "eap_finance",
            {"gte": {"attr": "att_credit", "value": 50000}},
            frozenset({"read"}),
            "active",
            None,
        ),
        GrantSpec(
            "g_service_all",
            "group",
            "grp_service",
            "eap_service",
            None,
            frozenset({"read"}),
            "active",
            None,
        ),
    )
    people = {
        "wang": Person("user_wang", "role_sales", ()),
        "sun": Person("user_sun", "role_finance", ()),
        "liu": Person("user_liu", "role_sales", ()),
        "both": Person("user_both", "role_sales", ("grp_service",)),
    }
    policy = Policy(
        entity_id="ent_customer",
        table_name="customer",
        revision=42,
        source_sql=SOURCE,
        head_version_id="ver_customer",
        attributes=attributes,
        ladders=ladders,
        profiles=(sales, finance, service),
        grants=grants,
        restrictions=(
            RestrictionSpec(
                "r_no_test",
                "all",
                (),
                {"ne": {"attr": "att_region", "value": "TEST"}},
                (),
                (),
                frozenset({"read", "write", "export", "mcp_query"}),
            ),
        ),
        people=tuple(people.values()),
        subject_attrs={
            "regions": SubjectAttrFact("regions", "dictionary", "dct_region", True)
        },
        subject_values={
            "user_wang": {"regions": ("EAST",)},
            "user_sun": {},
            "user_liu": {"regions": ("EAST",)},
            "user_both": {"regions": ("EAST",)},
        },
        cap=64,
        existing_combos=frozenset(),
        now=NOW,
    )
    return policy, people


def _rows() -> list[dict]:
    return [
        {"row_id": 1, "name": "Zhang", "mobile": "13812345678", "id_card_no": "110101199001011234", "region": "EAST", "account_manager": "wangwu", "credit_limit": 200000},
        {"row_id": 2, "name": "Li", "mobile": "13987654321", "id_card_no": "310101198505052345", "region": "EAST", "account_manager": "zhaoliu", "credit_limit": 80000},
        {"row_id": 3, "name": "Wang", "mobile": "13700001111", "id_card_no": "440101199212123456", "region": "SOUTH", "account_manager": "wangwu", "credit_limit": 500000},
        {"row_id": 4, "name": "Chen", "mobile": "13600002222", "id_card_no": "510101198807074567", "region": "SW", "account_manager": "qianqi", "credit_limit": 30000},
        {"row_id": 5, "name": "Zhou", "mobile": "13500003333", "id_card_no": "320101199504045678", "region": "EAST", "account_manager": "zhaoliu", "credit_limit": 20000},
        {"row_id": 6, "name": "Test", "mobile": "13000000000", "id_card_no": "000000000000000000", "region": "TEST", "account_manager": "admin", "credit_limit": 999999},
    ]


def _stars(text: str, keep_first: int, keep_last: int) -> str:
    hidden = len(text) - keep_first - keep_last
    return text[:keep_first] + ("*" * hidden) + text[-keep_last:]


def test_customer_cells() -> None:
    policy, people = _customer_policy()
    compiled = compile_policy(policy)
    rows = _rows()
    wang = project_subject(compiled, policy, people["wang"], rows)
    sun = project_subject(compiled, policy, people["sun"], rows)
    liu = project_subject(compiled, policy, people["liu"], rows)
    assert [row["row_id"] for row in wang.rows or ()] == [1, 2, 5]
    assert [row["row_id"] for row in sun.rows or ()] == [1, 2, 3]
    assert [row["row_id"] for row in liu.rows or ()] == [1, 2, 3, 5]
    assert wang.withheld_field is None
    assert "credit_limit" not in (wang.rows or ({},))[0]
    assert sun.rows is not None and sun.rows[0]["id_card_no"] == _stars("110101199001011234", 0, 4)
    assert liu.withheld_field == "__withheld"
    by_id = {row["row_id"]: row for row in liu.rows or ()}
    assert by_id[1]["mobile"] == "13812345678"
    assert by_id[1]["id_card_no"] == _stars("110101199001011234", 0, 4)
    assert by_id[1]["credit_limit"] == 200000
    assert by_id[1]["__withheld"] == []
    assert by_id[3]["mobile"] is None
    assert by_id[3]["__withheld"] == ["mobile"]
    assert by_id[3]["credit_limit"] == 500000
    assert by_id[5]["mobile"] == "13500003333"
    assert by_id[5]["id_card_no"] is None
    assert by_id[5]["credit_limit"] is None
    assert by_id[5]["__withheld"] == ["id_card_no", "credit_limit"]
    assert by_id[1]["__sources"]["mobile"] == ["g_sales_region"]
    assert "g_fin_user" in by_id[1]["__sources"]["credit_limit"]


def test_customer_service_merge_takes_clearer_mobile() -> None:
    policy, people = _customer_policy()
    compiled = compile_policy(policy)
    both = project_subject(compiled, policy, people["both"], _rows())
    by_id = {row["row_id"]: row for row in both.rows or ()}
    assert by_id[1]["mobile"] == "13812345678"
    assert by_id[3]["mobile"] == _stars("13700001111", 3, 4)
    assert by_id[3]["__withheld"] == ["account_manager"]
    assert "id_card_no" not in by_id[3]


def test_customer_sql_matches_the_view_template() -> None:
    policy, _people = _customer_policy()
    compiled = compile_policy(policy)
    sales = next(
        shape
        for shape in compiled.shapes
        if shape.action == "read" and shape.profile_ids == ("eap_sales",)
    )
    combo = next(
        shape
        for shape in compiled.shapes
        if shape.action == "read" and shape.combo_key == "eap_finance,eap_sales"
    )
    sales_sql = render_shape(sales, policy, acl=True)
    combo_sql = render_shape(combo, policy, acl=True)
    assert "security_barrier = true" in sales_sql
    assert "acl.rev_ok('ent_customer', 42)" in sales_sql
    assert "acl.grant_active('g_sales_region')" in sales_sql
    assert "IS DISTINCT FROM 'TEST'" in sales_sql
    assert "__withheld" not in sales_sql
    assert "COALESCE(" in combo_sql
    assert "acl.mask_partial(" in combo_sql
    assert '__withheld' in combo_sql
    assert "OWNER TO" in combo_sql
    assert "refraq_reader" in combo_sql
    assert sales.view_name.startswith("customer__p_")
    assert len(sales.view_name) <= 63


def test_dsl_rejects_dictionary_mismatch_and_accepts_rel_time() -> None:
    region = AttrFact(
        "att_region", "region", "dictionary", dictionary_id="dct_a", codes=("EAST",)
    )
    when = AttrFact("att_when", "opened", "date")
    subjects = {
        "regions": SubjectAttrFact("regions", "dictionary", "dct_b", True),
        "home": SubjectAttrFact("home", "dictionary", "dct_a", False),
    }
    with pytest.raises(RuleProblem, match="dictionary_id"):
        validate_rule(
            {"in": {"attr": "att_region", "subject_attr": "regions"}},
            {"att_region": region},
            subjects,
        )
    validate_rule(
        {"in": {"attr": "att_region", "subject_attr": "home"}},
        {"att_region": region, "att_when": when},
        subjects,
    )
    validate_rule(
        {"lt": {"attr": "att_when", "rel_time": "-P30D"}},
        {"att_when": when},
        {},
    )
    with pytest.raises(RuleProblem, match="depth"):
        node: dict = {"eq": {"attr": "att_region", "value": "EAST"}}
        for _ in range(8):
            node = {"not": node}
        validate_rule(node, {"att_region": region}, {})


def test_mask_type_and_ladder_order() -> None:
    credit = AttrFact("att_credit", "credit_limit", "integer")
    with pytest.raises(ModeError, match="not accepted"):
        validate_levels(
            [
                {"key": "clear", "mode": "clear"},
                {"key": "mail", "mode": {"type": "email"}},
            ],
            credit,
        )
    levels = validate_levels(
        [
            {"key": "clear", "mode": "clear"},
            {"key": "band", "mode": {"type": "bucket", "width": 1000}},
        ],
        credit,
    )
    assert levels[0][0] == "clear"
    assert levels[1][1] == {"type": "bucket", "width": 1000}


def test_broken_grant_grants_nothing_and_broken_restriction_hides() -> None:
    policy, people = _customer_policy()
    broken_grant = GrantSpec(
        "g_broken",
        "user",
        "user_wang",
        "eap_sales",
        {"eq": {"attr": "att_missing", "value": "x"}},
        frozenset({"read"}),
        "active",
        None,
    )
    policy = replace(policy, grants=(*policy.grants, broken_grant))
    compiled = compile_policy(policy)
    assert "g_broken" in compiled.broken_grants
    wang = project_subject(compiled, policy, people["wang"], _rows())
    assert "g_broken" not in wang.grant_ids
    hidden = replace(
        policy,
        restrictions=(
            RestrictionSpec(
                "r_broken",
                "all",
                (),
                {"eq": {"attr": "att_missing", "value": "x"}},
                (),
                (),
                frozenset({"read"}),
            ),
        ),
    )
    compiled_hidden = compile_policy(hidden)
    outcome = project_subject(compiled_hidden, hidden, people["wang"], _rows())
    assert outcome.hidden
    assert outcome.rows is None


def test_r9_warning_names_the_hidden_column() -> None:
    policy, _people = _customer_policy()
    compiled = compile_policy(policy)
    warnings = compiled.grant_warnings["g_fin_audit"]
    assert any(item.attribute_id == "att_credit" for item in warnings) is False
    sales_rule = GrantSpec(
        "g_sales_credit",
        "role",
        "role_sales",
        "eap_sales",
        {"gte": {"attr": "att_credit", "value": 1}},
        frozenset({"read"}),
        "active",
        None,
    )
    warned = replace(policy, grants=(*policy.grants, sales_rule))
    compiled_warned = compile_policy(warned)
    messages = compiled_warned.grant_warnings["g_sales_credit"]
    assert messages and messages[0].attribute_id == "att_credit"
    assert "discloses" in messages[0].message


def test_combination_cap_prefers_existing_and_marks_the_rest() -> None:
    policy, _people = _customer_policy()
    profiles = tuple(
        ProfileSpec(f"eap_{name}", name, (("att_name", "clear"),))
        for name in ("a", "b", "c")
    )
    pairs = (("a", "b", "user_ab"), ("a", "c", "user_ac"), ("b", "c", "user_bc"))
    grants = []
    people = []
    for left, right, user_id in pairs:
        people.append(Person(user_id, None, ()))
        grants.append(
            GrantSpec(
                f"g_{user_id}_1",
                "user",
                user_id,
                f"eap_{left}",
                None,
                frozenset({"read"}),
                "active",
                None,
            )
        )
        grants.append(
            GrantSpec(
                f"g_{user_id}_2",
                "user",
                user_id,
                f"eap_{right}",
                None,
                frozenset({"read"}),
                "active",
                None,
            )
        )
    capped = replace(
        policy,
        profiles=profiles,
        grants=tuple(grants),
        restrictions=(),
        people=tuple(people),
        subject_values={person.user_id: {} for person in people},
        cap=1,
        existing_combos=frozenset({"eap_b,eap_c"}),
    )
    compiled = compile_policy(capped)
    assert compiled.emitted_combos == frozenset({"eap_b,eap_c"})
    assert compiled.subjects_over_limit == 2
    kept = project_subject(compiled, capped, people[2], [{"row_id": 1, "name": "A"}])
    assert kept.over_limit is False
    refused = project_subject(compiled, capped, people[0], [{"row_id": 1, "name": "A"}])
    assert refused.over_limit is True


def _merge_grant_rows(parts: list[tuple[set[str], list[dict]]], columns: list[str]) -> dict[int, dict]:
    merged: dict[int, dict] = {}
    for names, rows in parts:
        for row in rows:
            slot = merged.setdefault(row["row_id"], {"row_id": row["row_id"]})
            for name in names:
                if name not in row:
                    continue
                current = slot.get(name, _MISSING)
                incoming = row[name]
                if current is _MISSING or (incoming is not None and current is None):
                    slot[name] = incoming
    for slot in merged.values():
        for name in columns:
            slot.setdefault(name, None)
    return merged


class _Missing:
    pass


_MISSING = _Missing()


@settings(max_examples=20, deadline=None)
@given(
    st.lists(st.integers(min_value=0, max_value=50), min_size=1, max_size=8, unique=True)
)
def test_projection_matches_per_grant_outer_join(amounts: list[int]) -> None:
    amount = AttrFact("att_amount", "amount", "integer")
    label = AttrFact("att_label", "label", "string", max_length=8)
    low = ProfileSpec("eap_low", "low", (("att_label", "clear"),))
    high = ProfileSpec(
        "eap_high",
        "high",
        (("att_label", "clear"), ("att_amount", "clear")),
    )
    person = Person("user_one", None, ())
    grants = (
        GrantSpec(
            "g_low",
            "user",
            "user_one",
            "eap_low",
            {"lt": {"attr": "att_amount", "value": 20}},
            frozenset({"read"}),
            "active",
            None,
        ),
        GrantSpec(
            "g_high",
            "user",
            "user_one",
            "eap_high",
            {"gte": {"attr": "att_amount", "value": 10}},
            frozenset({"read"}),
            "active",
            None,
        ),
    )
    policy = Policy(
        entity_id="ent_prop",
        table_name="prop",
        revision=1,
        source_sql='entity_data."prop"',
        head_version_id="ver",
        attributes=(label, amount),
        ladders={},
        profiles=(low, high),
        grants=grants,
        restrictions=(),
        people=(person,),
        subject_attrs={},
        subject_values={"user_one": {}},
        cap=64,
        existing_combos=frozenset(),
        now=NOW,
    )
    rows = [
        {"row_id": index + 1, "label": "n", "amount": value}
        for index, value in enumerate(amounts)
    ]
    compiled = compile_policy(policy)
    combo = project_subject(compiled, policy, person, rows)
    per_grant = []
    for grant, names in (
        (grants[0], {"label"}),
        (grants[1], {"label", "amount"}),
    ):
        alone = replace(policy, grants=(grant,))
        compiled_one = compile_policy(alone)
        projected = project_subject(compiled_one, alone, person, rows)
        per_grant.append((names, list(projected.rows or ())))
    oracle = _merge_grant_rows(per_grant, ["label", "amount"])
    actual = {row["row_id"]: row for row in combo.rows or ()}
    assert set(actual) == set(oracle)
    for row_id, expected in oracle.items():
        for name in ("label", "amount"):
            assert actual[row_id][name] == expected[name]


def _postgres_url() -> str | None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return None
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    url = (
        os.getenv("REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL")
        or values.get("ENTITY_DATABASE_URL")
        or values.get("DATABASE_URL")
    )
    if not url or not url.startswith("postgres"):
        return None
    url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except Exception:
        return None
    return url


@pytest.fixture(scope="module")
def postgres_url() -> str:
    url = _postgres_url()
    if url is None:
        pytest.skip("PostgreSQL is not reachable")
    return url


@pytest.mark.integration
@settings(max_examples=8, deadline=None)
@given(
    st.lists(st.integers(min_value=0, max_value=40), min_size=1, max_size=6, unique=True)
)
def test_combination_sql_matches_per_grant_outer_join(postgres_url: str, amounts: list[int]) -> None:
    import psycopg

    amount = AttrFact("att_amount", "amount", "integer")
    label = AttrFact("att_label", "label", "string", max_length=8)
    low = ProfileSpec("eap_low", "low", (("att_label", "clear"),))
    high = ProfileSpec(
        "eap_high",
        "high",
        (("att_label", "clear"), ("att_amount", "clear")),
    )
    grants = (
        GrantSpec(
            "g_low",
            "user",
            "user_one",
            "eap_low",
            {"lt": {"attr": "att_amount", "value": 20}},
            frozenset({"read"}),
            "active",
            None,
        ),
        GrantSpec(
            "g_high",
            "user",
            "user_one",
            "eap_high",
            {"gte": {"attr": "att_amount", "value": 10}},
            frozenset({"read"}),
            "active",
            None,
        ),
    )
    policy = Policy(
        entity_id="ent_sql",
        table_name="prop",
        revision=1,
        source_sql='"access_probe"',
        head_version_id="ver",
        attributes=(label, amount),
        ladders={},
        profiles=(low, high),
        grants=grants,
        restrictions=(),
        people=(Person("user_one", None, ()),),
        subject_attrs={},
        subject_values={"user_one": {}},
        cap=64,
        existing_combos=frozenset(),
        now=NOW,
    )
    compiled = compile_policy(policy)
    combo_shape = next(
        shape
        for shape in compiled.shapes
        if shape.action == "read" and shape.combo_key == "eap_high,eap_low"
    )
    combo_sql = render_shape(combo_shape, policy, acl=False, active=None)
    grant_sql = [render_grant_select(policy, grant) for grant in grants]
    with psycopg.connect(postgres_url) as conn:
        conn.execute(
            'CREATE TEMP TABLE access_probe (row_id bigint, label text, amount bigint)'
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO access_probe (row_id, label, amount) VALUES (%s, %s, %s)",
                [(index + 1, "n", value) for index, value in enumerate(amounts)],
            )
        combo_rows = conn.execute(combo_sql).fetchall()
        low_rows = conn.execute(grant_sql[0]).fetchall()
        high_rows = conn.execute(grant_sql[1]).fetchall()
        conn.rollback()
    combo = {row[0]: {"label": row[1], "amount": row[2]} for row in combo_rows}
    oracle: dict[int, dict] = {}
    for row in low_rows:
        oracle.setdefault(row[0], {"label": None, "amount": None})
        oracle[row[0]]["label"] = row[1]
    for row in high_rows:
        slot = oracle.setdefault(row[0], {"label": None, "amount": None})
        slot["label"] = row[1]
        slot["amount"] = row[2]
    assert set(combo) == set(oracle)
    for row_id, expected in oracle.items():
        assert combo[row_id]["label"] == expected["label"]
        assert combo[row_id]["amount"] == expected["amount"]


def _restricted_policy(*restrictions: RestrictionSpec) -> tuple[Policy, Person, Person]:
    region = AttrFact("att_region", "region", "string", max_length=16)
    note = AttrFact("att_note", "note", "string", max_length=16)
    target = Person("user_target", None, ())
    other = Person("user_other", None, ())
    grants = tuple(
        GrantSpec(f"g_{person.user_id}", "user", person.user_id, "eap_all", None,
                  frozenset({"read"}), "active", None)
        for person in (target, other)
    )
    policy = Policy(
        entity_id="ent_r",
        table_name="probe",
        revision=1,
        source_sql='entity_data."probe__v1"',
        head_version_id="ver",
        attributes=(region, note),
        ladders={},
        profiles=(ProfileSpec("eap_all", "all", (("att_region", "clear"), ("att_note", "clear"))),),
        grants=grants,
        restrictions=restrictions,
        people=(target, other),
        subject_attrs={},
        subject_values={},
        cap=64,
        existing_combos=frozenset(),
        now=NOW,
    )
    return policy, target, other


_EAST_ONLY = {"eq": {"attr": "att_region", "value": "EAST"}}


@pytest.mark.parametrize("with_ceiling", [True, False])
def test_subject_restriction_row_rule_is_in_the_view(with_ceiling: bool) -> None:
    restriction = RestrictionSpec(
        "ear_east",
        "only",
        (("user", "user_target"),),
        _EAST_ONLY,
        ("att_note",) if with_ceiling else (),
        (),
        frozenset({"read"}),
    )
    policy, target, other = _restricted_policy(restriction)
    compiled = compile_policy(policy)
    mine = subject_outcome(compiled, policy, target, action="read", narrow=None)
    theirs = subject_outcome(compiled, policy, other, action="read", narrow=None)
    assert mine.shape is not None and theirs.shape is not None
    assert mine.shape.included_restrictions == ("ear_east",)
    assert mine.shape.view_name != theirs.shape.view_name
    mine_sql = render_shape(mine.shape, policy, acl=True)
    theirs_sql = render_shape(theirs.shape, policy, acl=True)
    assert "\"region\" = 'EAST'" in mine_sql
    assert "\"region\" = 'EAST'" not in theirs_sql
    assert "FALSE" not in mine_sql.split("WHERE", 1)[1]
    rows = [
        {"row_id": 1, "region": "EAST", "note": "a"},
        {"row_id": 2, "region": "WEST", "note": "b"},
    ]
    projected = project_subject(compiled, policy, target, rows)
    assert projected.rows is not None
    assert [row["row_id"] for row in projected.rows] == [1]


def test_not_over_a_null_leaf_matches_the_python_evaluator() -> None:
    attrs = {"att_region": AttrFact("att_region", "region", "string", max_length=16)}
    rule = {"not": {"eq": {"attr": "att_region", "value": "TEST"}}}
    sql = rule_sql(rule, attrs, alias="t", acl=False)
    assert sql == "(NOT COALESCE((t.\"region\" = 'TEST'), false))"
    assert eval_rule(rule, {"region": None}, attrs, subject_id=None, subject_values={}, now=NOW)
