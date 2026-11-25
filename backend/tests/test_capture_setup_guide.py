"""The deployment projection is a reading of the capture contracts, not a second copy."""

import copy
import inspect
import json
import re
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.admin.deps import get_current_user, get_role_store
from backend.admin.roles import SUPER_ADMIN_KEY
from backend.core.config import MIRROR_TARGET_ROLES, MirrorTargetSettings
from backend.core.errors import AppError
from backend.main import app_error_handler
from backend.metadata.capture.credentials import CredentialFiles
from backend.metadata.capture.engines import engine_for_entry
from backend.metadata.capture.runtime import build_parser as runtime_parser
from backend.metadata.capture.runtime_adapters import PrivateHTTP, ReadinessSignals
from backend.metadata.capture.runtime_store import REPORTED_FAULTS
from backend.metadata.capture.setup_guide import setup_guide
from backend.metadata.mirrors.bootstrap import ROLES, VERSION, build_parser as bootstrap_parser
from backend.metadata.mirrors.router import router
from backend.tests.test_capture_engine_conformance import CASES, TLS

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "backend/metadata/capture"
LOCALES = ROOT / "frontend/src/locales"

ACCESS = {
    "postgresql": {"host": "db.internal", "port": 5432, "database": "sales", "schema": "public",
                   "username": "capture", "password": "secret"},
    "mysql": {"host": "db.internal", "port": 1433, "database": "sales", "username": "capture", "password": "secret"},
    "mssql": {"host": "db.internal", "port": 1433, "database": "sales", "schema": "dbo",
              "username": "capture", "password": "secret"},
    "oracle": {"host": "db.internal", "port": 1433, "service_name": "salespdb.internal", "owner": "APP",
               "username": "capture", "password": "secret"},
}
PG_SCOPE = {
    "source_id": "src_1", "connector_name": "cap-main", "host": "db.internal", "port": 5432,
    "database": "sales", "tables": ["public.orders"], "publication": "refraq_pub", "slot": "refraq_slot",
    "topic_prefix": "cap", "server_version_num": 180006,
}
PG_TLS = {"sslmode": "verify-full", "sslrootcert": "/etc/refraq/ca.pem"}


def required_names(func, exclude=()):
    skip = {"self", *exclude}
    return {name for name, param in inspect.signature(func).parameters.items()
            if name not in skip and param.default is inspect.Parameter.empty}


def good_scope(code):
    if code == "postgresql":
        return copy.deepcopy(PG_SCOPE)
    return next(case for case in CASES if case.code == code).scope()


def test_private_adapters_and_commands_match_the_running_code():
    guide = setup_guide()
    assert set(guide["transport"]["tls_keys"]) == required_names(PrivateHTTP.__init__)
    assert set(guide["runtime"]["readiness_policy_keys"]) == required_names(
        ReadinessSignals.__init__, {"http", "engine", "verifier", "scope"})
    assert set(guide["runtime"]["credential_file_keys"]) == required_names(CredentialFiles.__init__)
    for engine in guide["engines"]:
        entry = engine["source_entry"]
        assert set(entry["connect_tls"]) == set(entry["signals_tls"]) == set(guide["transport"]["tls_keys"])
        assert set(entry["readiness_policy"]) == set(guide["runtime"]["readiness_policy_keys"])
        assert set(entry["credential_files"]) == set(guide["runtime"]["credential_file_keys"])
        assert set(entry["signing_trust"]) == set(guide["gateway"]["signing_trust_keys"])
        assert entry["signals_tls"]["origin"] == "<GATEWAY_ORIGIN>"
        assert "password" not in entry and "username" not in entry

    trust_source = (CAPTURE / "runtime.py").read_text()
    assert set(re.findall(r'trust\["([a-z_]+)"\]', trust_source)) == set(guide["gateway"]["signing_trust_keys"])
    assert 'return 2 if blocked else 0' in trust_source
    assert 'print("capture_runtime_blocked")' in trust_source
    for key in guide["runtime"]["config_keys"]:
        assert f'config["{key}"]' in trust_source
    assert set(guide["runtime"]["fault_codes"]) == set(REPORTED_FAULTS)
    assert guide["runtime"]["exit_codes"] == {"ready": 0, "blocked": 2}
    assert guide["runtime"]["fatal_message"] == "capture_runtime_blocked"
    assert guide["target"]["schema_version"] == VERSION
    assert guide["target"]["roles"] == list(ROLES)
    assert guide["target"]["login_roles"] == list(MIRROR_TARGET_ROLES)
    assert set(MIRROR_TARGET_ROLES) == set(ROLES) - {"refraq_mirror_owner"}
    assert guide["target"]["setting_fields"] == list(MirrorTargetSettings.model_fields)
    assert guide["target"]["setting"] == "REFRAQ_MIRROR_TARGET"
    runtime_parser().parse_args(_flags(guide["commands"]["check"]["argv"]))
    runtime_parser().parse_args(_flags(guide["commands"]["start"]["argv"]))
    bootstrap_parser().parse_args(_flags(guide["commands"]["bootstrap"]["argv"]))
    compose = (ROOT / "deploy/compose.yaml").read_text()
    assert re.search(rf'^  {guide["compose_service"]}:$', compose, re.M)
    bootstrap_source = (ROOT / "backend/metadata/mirrors/bootstrap.py").read_text()
    for schema in guide["target"]["schemas"]:
        assert schema in bootstrap_source


def _flags(argv):
    assert argv[:2] == ["python", "-m"]
    return argv[3:]


def test_gateway_and_connect_paths_are_the_literals_the_runtime_calls():
    guide = setup_guide()
    literals, suffixes, steps = set(), set(), set()
    for path in CAPTURE.glob("*.py"):
        if path.name.startswith("test_") or path.name == "setup_guide.py":
            continue
        text = path.read_text()
        literals.update(re.findall(r'["\'](/v1/capture/[^"\']*)["\']', text))
        suffixes.update(re.findall(r'self\.path \+ "(/[A-Za-z0-9_-]+)"', text))
        steps.update(re.findall(r'self\._(?:observe|request)\([^,\n]+,\s*"([a-z]+)"', text))
    expanded = set()
    for literal in literals:
        if "{step}" in literal:
            expanded.update(literal.replace("{step}", step) for step in steps)
        else:
            expanded.add(literal)
    assert set(guide["gateway"]["paths"]) == expanded
    assert set(guide["gateway"]["optional_paths"]) <= expanded
    assert {f"/connectors/{{name}}{suffix}" for suffix in suffixes} == set(guide["gateway"]["connect_paths"])


@pytest.mark.parametrize("code", ["postgresql", "mysql", "mssql", "oracle"])
def test_same_name_access_fills_a_constructor_valid_profile(code):
    guide = setup_guide()
    projected = next(item for item in guide["engines"] if item["code"] == code)
    template = copy.deepcopy(projected["source_entry"][projected["profile_key"]]["scope"])
    good = good_scope(code)
    assert set(template) == set(good)
    access = ACCESS[code]
    scope = copy.deepcopy(template)
    for key, value in access.items():
        if key in scope:
            scope[key] = value
    for key in scope:
        if key not in access:
            scope[key] = copy.deepcopy(good[key])
    template_tls = projected["source_entry"][projected["profile_key"]]["tls"]
    assert set(template_tls) == set(PG_TLS if code == "postgresql" else TLS)
    tls = PG_TLS if code == "postgresql" else TLS
    engine = engine_for_entry({projected["profile_key"]: {}})
    built = engine.profile(scope=scope, tls=tls, connect=lambda **_options: nullcontext(object()))
    assert built._access_matches(access)
    for key, value in access.items():
        if key in template:
            assert built.scope[key] == value
    assert "username" not in built.scope
    assert "password" not in built.scope


def test_guide_terms_have_copy_in_both_locales():
    guide = setup_guide()
    catalogs = {name: json.loads((LOCALES / name / "common.json").read_text()) for name in ("en-US", "zh-CN")}
    required = set()
    for code in guide["runtime"]["fault_codes"]:
        required.add(f"mirrorSetup.fault.{code}")
    for engine in guide["engines"]:
        for name in (*engine["prerequisites"], engine["snapshot_prerequisite"]):
            required.add(f"mirrorSetup.prerequisite.{engine['code']}.{name}")
    for item in guide["site_inputs"]:
        required.add(f"mirrorSetup.input.{item['token']}")
    for step in guide["steps"]:
        required.add(f"mirrorSetup.step.{step}.title")
        required.add(f"mirrorSetup.step.{step}.body")
    for key in guide["deployment_owned"]:
        required.add(f"mirrorSetup.owned.{key}")
    missing = {name: sorted(key for key in required if key not in catalog) for name, catalog in catalogs.items()}
    assert missing == {"en-US": [], "zh-CN": []}


def test_mirror_setup_requires_mirror_read():
    from types import SimpleNamespace

    app = FastAPI()
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u", role_id="r")
    app.dependency_overrides[get_role_store] = lambda: SimpleNamespace(
        get_by_id=lambda _: SimpleNamespace(key="custom", permissions=[]))
    with TestClient(app) as client:
        denied = client.get("/mirror-setup")
        assert denied.status_code == 403
        assert denied.json()["code"] == "AUTH_FORBIDDEN"
        app.dependency_overrides[get_role_store] = lambda: SimpleNamespace(
            get_by_id=lambda _: SimpleNamespace(key=SUPER_ADMIN_KEY))
        allowed = client.get("/mirror-setup")
        assert allowed.status_code == 200
        body = allowed.json()
        blob = json.dumps(body)
        assert body["connector_version"] == setup_guide()["connector_version"]
        assert "<GATEWAY_ORIGIN>" in blob
        assert "username" not in blob
        assert "<PASSWORD>" in blob
