"""Public /hooks/{path}: admission, an immediate answer, and the rejection list."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.channel.channel_run import set_dispatcher  # noqa: E402
from backend.channel.run_store import get_run_store  # noqa: E402
from backend.channel.tasks import run_job  # noqa: E402
from backend.core.errors import (  # noqa: E402
    CODE_HTTP_ERROR,
    CODE_HTTP_METHOD_NOT_ALLOWED,
    CODE_HTTP_NOT_FOUND,
    FIELD_VALUE_INVALID,
    FIELD_VALUE_MISSING,
)
from backend.core.time import UTC, FixedClock, format_instant, reset_clock, set_clock  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402

_MIB = 1024 * 1024
_KEEP = 16 * 1024
_SECRET = "hook-secret-9f3a"
_HMAC_SECRET = "hmac-secret-9f3a"
_WHEN = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _login(client: TestClient, account: str, password: str) -> None:
    response = client.post(
        "/auth/login", json={"account": account, "password": password}
    )
    assert response.status_code == 200, response.text


@pytest.fixture()
def client() -> TestClient:
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )
    previous = set_dispatcher(run_job)
    try:
        with TestClient(app) as test_client:
            _login(test_client, "admin", "secret")
            yield test_client
    finally:
        set_dispatcher(previous)


def _credential(
    client: TestClient,
    *,
    name: str,
    credential_type: str,
    secret: str,
    config: dict,
) -> str:
    created = client.post(
        "/inbound-credentials",
        json={
            "name": name,
            "type": credential_type,
            "secret": secret,
            "config": config,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["inbound_credential"]["id"]


def _token(
    client: TestClient,
    *,
    location: str = "header",
    name: str = "X-Hook-Token",
    secret: str = _SECRET,
) -> str:
    return _credential(
        client,
        name=f"Token {location} {name}",
        credential_type="token",
        secret=secret,
        config={"location": location, "name": name},
    )


def _hmac_credential(
    client: TestClient,
    *,
    encoding: str,
    prefix: str | None = None,
    timestamp_header: str | None = None,
    signature_header: str = "X-Signature",
) -> str:
    config: dict = {"signature_header": signature_header, "encoding": encoding}
    if prefix is not None:
        config["prefix"] = prefix
    if timestamp_header is not None:
        config["timestamp_header"] = timestamp_header
    return _credential(
        client,
        name=f"HMAC {encoding}",
        credential_type="hmac_sha256",
        secret=_HMAC_SECRET,
        config=config,
    )


def _node(credential_id: str, path: str, **config: object) -> dict:
    response = config.pop("response", None)
    if not isinstance(response, dict):
        response = {"mode": "immediate", "body": {"kind": "static", "text": "ok"}}
    body = {
        "path": path,
        "credential_id": credential_id,
        "response": response,
    }
    body.update(config)
    return {
        "id": "nd_hook",
        "ref": "hook",
        "type": "trigger.inbound",
        "name": "Inbound",
        "position": {"x": 0, "y": 0},
        "config": body,
        "on_error": "stop",
        "retry": None,
    }


def _graph(*nodes: dict, edges: list | None = None) -> dict:
    return {
        "nodes": list(nodes),
        "edges": [] if edges is None else edges,
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }


def _publish(client: TestClient, name: str, graph: dict) -> str:
    created = client.post("/channels", json={"name": name, "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    current = client.get(f"/channels/{channel_id}/draft")
    assert current.status_code == 200, current.text
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": current.json()["draft_revision"], "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    published = client.post(
        f"/channels/{channel_id}/publish",
        json={"draft_revision": saved.json()["draft_revision"]},
    )
    assert published.status_code == 201, published.text
    activated = client.post(f"/channels/{channel_id}/activate")
    assert activated.status_code == 200, activated.text
    return channel_id


def _live(client: TestClient, name: str, path: str, credential_id: str, **config: object) -> str:
    return _publish(client, name, _graph(_node(credential_id, path, **config)))


def _rejections(client: TestClient, channel_id: str, **params: object) -> dict:
    response = client.get(
        f"/channels/{channel_id}/inbound-rejections", params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def _runs(client: TestClient, channel_id: str) -> dict:
    response = client.get(f"/channels/{channel_id}/runs")
    assert response.status_code == 200, response.text
    return response.json()


def _edge(edge_id: str, source: str, target: str, *, source_port: str = "main") -> dict:
    return {
        "id": edge_id,
        "source": {"node_id": source, "port": source_port},
        "target": {"node_id": target, "port": "main"},
    }


def _respond(**config: object) -> dict:
    body = {"status": "200"}
    body.update(config)
    return {
        "id": "nd_reply",
        "ref": "reply",
        "type": "action.respond",
        "name": "Respond",
        "position": {"x": 240, "y": 0},
        "config": body,
        "on_error": "stop",
        "retry": None,
    }


def _after() -> dict:
    return {
        "id": "nd_after",
        "ref": "after",
        "type": "transform.set_fields",
        "name": "After",
        "position": {"x": 480, "y": 0},
        "config": {"fields": [{"name": "done", "value": "true"}]},
        "on_error": "stop",
        "retry": None,
    }


def _late_graph(credential_id: str, path: str, fallback: dict) -> dict:
    return _graph(
        _node(
            credential_id,
            path,
            response={
                "mode": "respond_node",
                "wait_sec": 1,
                "fallback": fallback,
            },
        ),
        {
            "id": "nd_delay",
            "ref": "delay",
            "type": "transform.code",
            "name": "Delay",
            "position": {"x": 160, "y": 0},
            "config": {"code": "raise RuntimeError('pause')", "timeout_sec": 30},
            "on_error": "continue",
            "retry": {"max_tries": 2, "wait_sec": 2},
        },
        _respond(status="200", content_type="text/plain", body='"late"'),
        _after(),
        edges=[
            _edge("ed_delay", "nd_hook", "nd_delay"),
            _edge("ed_reply", "nd_delay", "nd_reply"),
            _edge("ed_after", "nd_reply", "nd_after"),
        ],
    )


def _respond_graph(credential_id: str, path: str, **config: object) -> dict:
    return _graph(
        _node(credential_id, path, response={"mode": "respond_node"}),
        _respond(**config),
        edges=[_edge("ed_reply", "nd_hook", "nd_reply")],
    )


def _hook(client: TestClient, path: str):
    return client.post(
        f"/hooks/{path}",
        json={},
        headers={"X-Hook-Token": _SECRET},
    )


def _only_job(client: TestClient, channel_id: str) -> str:
    page = _runs(client, channel_id)
    assert page["total"] == 1
    return page["items"][0]["job_id"]


def _outputs_for(
    client: TestClient, channel_id: str, job_id: str, node_id: str
) -> list:
    listed = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions",
        params={"node_id": node_id},
    )
    assert listed.status_code == 200, listed.text
    values = []
    for item in listed.json()["items"]:
        output = client.get(
            f"/channels/{channel_id}/runs/{job_id}/executions/{item['seq']}/output"
        )
        assert output.status_code == 200, output.text
        values.append(output.json()["value"])
    return values


def _no_details(body: dict) -> None:
    assert "details" not in body


def _without_session(client: TestClient, call: Callable[[], object]) -> object:
    saved = client.cookies.get("refraq_sid")
    client.cookies.clear()
    try:
        return call()
    finally:
        if saved:
            client.cookies.set("refraq_sid", saved)


def _signature(message: bytes, *, encoding: str, prefix: str = "") -> str:
    digest = hmac.new(_HMAC_SECRET.encode("utf-8"), message, hashlib.sha256).digest()
    encoded = digest.hex() if encoding == "hex" else base64.b64encode(digest).decode("ascii")
    return f"{prefix}{encoded}"


def test_unknown_path_is_not_found_and_not_recorded(client: TestClient) -> None:
    credential_id = _token(client)
    channel_id = _live(client, "Orders", "orders", credential_id)
    response = client.post("/hooks/missing", json={"n": 1})
    body = assert_problem(response, status=404, code=CODE_HTTP_NOT_FOUND)
    _no_details(body)
    assert _rejections(client, channel_id)["total"] == 0
    assert _runs(client, channel_id)["total"] == 0


def test_inactive_channel_is_recorded_before_later_checks(client: TestClient) -> None:
    credential_id = _token(client)
    channel_id = _live(client, "Quiet", "quiet", credential_id)
    stopped = client.post(f"/channels/{channel_id}/deactivate")
    assert stopped.status_code == 200, stopped.text
    response = client.put(
        "/hooks/quiet",
        content=b"ignored",
        headers={"X-Hook-Token": "wrong", "content-type": "text/plain"},
    )
    body = assert_problem(response, status=503, code="CHANNEL_INBOUND_INACTIVE")
    _no_details(body)
    page = _rejections(client, channel_id)
    assert page["total"] == 1
    assert page["items"][0]["reason"] == "inactive"
    assert page["items"][0]["method"] == "PUT"
    assert page["items"][0]["path"] == "quiet"
    assert _runs(client, channel_id)["total"] == 0


def test_disallowed_method_is_recorded(client: TestClient) -> None:
    credential_id = _token(client)
    channel_id = _live(client, "Methods", "methods", credential_id)
    denied = client.get(
        "/hooks/methods", headers={"X-Hook-Token": _SECRET}
    )
    body = assert_problem(denied, status=405, code=CODE_HTTP_METHOD_NOT_ALLOWED)
    _no_details(body)
    assert _rejections(client, channel_id)["items"][0]["reason"] == "method_not_allowed"
    huge = client.put(
        "/hooks/methods",
        content=b"z" * (_MIB + 1),
        headers={"content-type": "text/plain"},
    )
    assert_problem(huge, status=405, code=CODE_HTTP_METHOD_NOT_ALLOWED)
    reasons = [item["reason"] for item in _rejections(client, channel_id)["items"]]
    assert reasons[0] == "method_not_allowed"
    assert "body_too_large" not in reasons
    assert _runs(client, channel_id)["total"] == 0


def test_body_over_one_mib_keeps_no_body(client: TestClient) -> None:
    credential_id = _token(client)
    channel_id = _live(client, "Large", "large", credential_id)
    response = client.post(
        "/hooks/large",
        content=b"z" * (_MIB + 1),
        headers={"X-Hook-Token": _SECRET, "content-type": "text/plain"},
    )
    body = assert_problem(response, status=413, code=CODE_HTTP_ERROR)
    _no_details(body)
    assert _SECRET not in response.text
    page = _rejections(client, channel_id)
    assert page["total"] == 1
    assert page["items"][0]["reason"] == "body_too_large"
    assert page["items"][0]["body"] is None
    assert _runs(client, channel_id)["total"] == 0


def test_bad_header_token_is_unauthenticated_and_strips_secrets(
    client: TestClient,
) -> None:
    credential_id = _token(client)
    channel_id = _live(
        client,
        "Tokens",
        "tokens",
        credential_id,
        input=[{"name": "order_id", "type": "string", "required": True}],
    )
    missing = client.post("/hooks/tokens", json={"order_id": "a"})
    missing_body = assert_problem(
        missing, status=401, code="CHANNEL_INBOUND_UNAUTHENTICATED"
    )
    _no_details(missing_body)
    wrong = client.post(
        "/hooks/tokens",
        content=b"a" * (_KEEP + 50),
        headers={
            "content-type": "text/plain",
            "X-Hook-Token": "nope",
            "Authorization": "Bearer other",
            "Cookie": "sid=1",
        },
    )
    wrong_body = assert_problem(
        wrong, status=401, code="CHANNEL_INBOUND_UNAUTHENTICATED"
    )
    assert wrong_body["detail"] == missing_body["detail"]
    assert "nope" not in wrong.text
    assert _SECRET not in wrong.text
    page = _rejections(client, channel_id)
    assert page["total"] == 2
    recorded = page["items"][0]
    assert recorded["reason"] == "unauthenticated"
    assert recorded["body"] == "a" * _KEEP
    assert "authorization" not in recorded["headers"]
    assert "cookie" not in recorded["headers"]
    assert "x-hook-token" not in recorded["headers"]
    assert _runs(client, channel_id)["total"] == 0


def test_query_token_and_hmac_signatures(client: TestClient) -> None:
    query_id = _token(client, location="query", name="access_token", secret=_SECRET)
    query_channel = _live(client, "Query token", "query-token", query_id)
    missing_query = client.post("/hooks/query-token", json={})
    assert_problem(
        missing_query, status=401, code="CHANNEL_INBOUND_UNAUTHENTICATED"
    )
    query_page = _rejections(client, query_channel)
    assert "access_token" not in query_page["items"][0]["query"]

    hex_id = _hmac_credential(client, encoding="hex", prefix="sha256=")
    hex_channel = _live(client, "HMAC hex", "hmac-hex", hex_id)
    raw = b'{"ok":true}'
    signed = client.post(
        "/hooks/hmac-hex",
        content=raw,
        headers={
            "content-type": "application/json",
            "X-Signature": _signature(raw, encoding="hex", prefix="sha256="),
            "Authorization": "Bearer other",
        },
    )
    assert signed.status_code == 200, signed.text
    assert signed.text == "ok"
    bad_prefix = client.post(
        "/hooks/hmac-hex",
        content=raw,
        headers={
            "content-type": "application/json",
            "X-Signature": _signature(raw, encoding="hex"),
            "X-Timestamp": "1",
            "Cookie": "sid=1",
        },
    )
    bad_body = assert_problem(
        bad_prefix, status=401, code="CHANNEL_INBOUND_UNAUTHENTICATED"
    )
    _no_details(bad_body)
    recorded = _rejections(client, hex_channel)["items"][0]
    assert recorded["reason"] == "unauthenticated"
    assert "x-signature" not in recorded["headers"]
    assert "authorization" not in recorded["headers"]
    assert "cookie" not in recorded["headers"]
    output = _trigger_output(client, hex_channel, _runs(client, hex_channel)["items"][0]["job_id"])
    assert "x-signature" not in output["headers"]
    assert output["headers"]["authorization"] == "Bearer other"

    b64_id = _hmac_credential(client, encoding="base64", signature_header="X-Hub")
    _live(client, "HMAC b64", "hmac-b64", b64_id)
    encoded = client.post(
        "/hooks/hmac-b64",
        content=raw,
        headers={
            "content-type": "application/json",
            "X-Hub": _signature(raw, encoding="base64"),
        },
    )
    assert encoded.status_code == 200, encoded.text

    stamped_id = _hmac_credential(
        client,
        encoding="hex",
        timestamp_header="X-Timestamp",
        signature_header="X-Stamp-Signature",
    )
    stamped_channel = _live(client, "HMAC time", "hmac-time", stamped_id)
    when = int(_WHEN.timestamp())
    set_clock(FixedClock(_WHEN))
    try:
        fresh = _timestamped(client, when, raw)
        assert fresh.status_code == 200, fresh.text
        edge = _timestamped(client, when + 300, raw)
        assert edge.status_code == 200, edge.text
        stale = _timestamped(client, when - 301, raw)
        early = _timestamped(client, when + 301, raw)
    finally:
        reset_clock()
    stale_body = assert_problem(
        stale, status=401, code="CHANNEL_INBOUND_UNAUTHENTICATED"
    )
    early_body = assert_problem(
        early, status=401, code="CHANNEL_INBOUND_UNAUTHENTICATED"
    )
    assert stale_body["detail"] == early_body["detail"]
    assert "timestamp" not in stale_body["detail"].lower()
    stamped_output = _trigger_output(
        client, stamped_channel, _runs(client, stamped_channel)["items"][0]["job_id"]
    )
    assert "x-stamp-signature" not in stamped_output["headers"]
    assert "x-timestamp" in stamped_output["headers"]
    assert _rejections(client, stamped_channel)["total"] == 2


def _timestamped(client: TestClient, stamp: int, raw: bytes):
    text = str(stamp)
    message = text.encode("utf-8") + b"." + raw
    return client.post(
        "/hooks/hmac-time",
        content=raw,
        headers={
            "content-type": "application/json",
            "X-Timestamp": text,
            "X-Stamp-Signature": _signature(message, encoding="hex"),
        },
    )


def test_declared_input_names_the_field_and_other_bodies_pass(
    client: TestClient,
) -> None:
    credential_id = _token(client)
    channel_id = _live(
        client,
        "Shapes",
        "shapes",
        credential_id,
        input=[
            {"name": "order_id", "type": "string", "required": True},
            {"name": "count", "type": "integer", "required": True},
        ],
    )
    bad_token = client.post("/hooks/shapes", json={"extra": True})
    assert_problem(bad_token, status=401, code="CHANNEL_INBOUND_UNAUTHENTICATED")
    missing = client.post(
        "/hooks/shapes",
        json={"count": "nope", "extra": True},
        headers={"X-Hook-Token": _SECRET, "content-type": "application/json"},
    )
    body = assert_problem(missing, status=422, code="CHANNEL_INBOUND_INPUT_INVALID")
    assert {(item["field"], item["code"]) for item in body["details"]} == {
        ("order_id", FIELD_VALUE_MISSING),
        ("count", FIELD_VALUE_INVALID),
    }
    for item in body["details"]:
        assert set(item) == {"field", "code", "message"}
        assert "extra" not in item["field"]
    assert _rejections(client, channel_id)["items"][0]["reason"] == "input_invalid"
    array = client.post(
        "/hooks/shapes",
        content=b"[1]",
        headers={
            "X-Hook-Token": _SECRET,
            "content-type": "application/json; charset=utf-8",
        },
    )
    array_body = assert_problem(
        array, status=422, code="CHANNEL_INBOUND_INPUT_INVALID"
    )
    assert array_body["details"][0]["field"] == "body"
    assert array_body["details"][0]["code"] == FIELD_VALUE_INVALID

    form = client.post(
        "/hooks/shapes",
        content=b"order_id=Ada&count=2&extra=1",
        headers={
            "X-Hook-Token": _SECRET,
            "content-type": "application/x-www-form-urlencoded",
        },
    )
    assert_problem(form, status=422, code="CHANNEL_INBOUND_INPUT_INVALID")

    loose_id = _token(client, name="X-Loose-Token")
    loose = _live(client, "Loose", "loose", loose_id)
    xml = b"<event>1</event>"
    raw = client.post(
        "/hooks/loose",
        content=xml,
        headers={"X-Loose-Token": _SECRET, "content-type": "application/xml"},
    )
    assert raw.status_code == 200, raw.text
    binary = client.post(
        "/hooks/loose",
        content=b"\xff\xfe",
        headers={"X-Loose-Token": _SECRET, "content-type": "application/octet-stream"},
    )
    assert binary.status_code == 200, binary.text
    runs = _runs(client, loose)
    assert runs["total"] == 2
    outputs = [
        _trigger_output(client, loose, item["job_id"]) for item in runs["items"]
    ]
    assert {item["body"] for item in outputs} == {None}
    assert {item["raw_body"] for item in outputs} == {None, xml.decode("utf-8")}
    assert _runs(client, channel_id)["total"] == 0


def test_immediate_call_creates_one_inbound_run(client: TestClient) -> None:
    credential_id = _token(client)
    channel_id = _live(
        client,
        "Ack",
        "ack",
        credential_id,
        input=[{"name": "order_id", "type": "string", "required": True}],
        event_id={"from": "body", "key": "meta.id"},
        response={
            "mode": "immediate",
            "status": 202,
            "content_type": "text/plain",
            "headers": {"X-Ack": "yes"},
            "body": {"kind": "static", "text": "acked"},
        },
    )
    raw = b'{"order_id":"a","meta":{"id":"evt-9"},"extra":1}'
    clock = FixedClock(_WHEN)
    set_clock(clock)
    try:
        response = _without_session(
            client,
            lambda: client.post(
                "/hooks/ack",
                content=raw,
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "X-Hook-Token": _SECRET,
                    "Authorization": "Bearer other",
                    "Cookie": "sid=1",
                },
            ),
        )
        clock.advance(timedelta(seconds=1))
        again = _without_session(
            client,
            lambda: client.post(
                "/hooks/ack",
                content=raw,
                headers={
                    "content-type": "application/json",
                    "X-Hook-Token": _SECRET,
                },
            ),
        )
    finally:
        reset_clock()
    assert response.status_code == 202, response.text
    assert response.text == "acked"
    assert response.headers["content-type"].split(";")[0] == "text/plain"
    assert response.headers["x-ack"] == "yes"
    assert again.status_code == 202, again.text
    runs = _runs(client, channel_id)
    assert runs["total"] == 2
    assert _rejections(client, channel_id)["total"] == 0
    first = next(
        item
        for item in runs["items"]
        if _trigger_output(client, channel_id, item["job_id"])["received_at"]
        == format_instant(_WHEN)
    )
    assert first["target"] == "published"
    assert first["trigger_kind"] == "inbound"
    assert first["trigger_ref"] == "ack"
    job = client.get(f"/jobs/{first['job_id']}")
    assert job.status_code == 200, job.text
    payload = job.json()["job"]
    assert payload["kind"] == "channel_run"
    assert payload["trigger_kind"] == "inbound"
    assert payload["trigger_ref"] == "ack"
    assert payload["input"]["target"] == "published"
    assert "pin_version" not in payload["input"]
    assert "version" not in payload["input"]
    assert "x-hook-token" not in payload["input"]["request"]["headers"]
    output = _trigger_output(client, channel_id, first["job_id"])
    assert output["method"] == "POST"
    assert output["body"] == {"order_id": "a", "meta": {"id": "evt-9"}, "extra": 1}
    assert output["raw_body"] == raw.decode("utf-8")
    assert output["event_id"] == "evt-9"
    assert output["query"] == {}
    assert output["received_at"] == format_instant(_WHEN)
    assert "x-hook-token" not in output["headers"]
    assert output["headers"]["authorization"] == "Bearer other"
    assert "sid=1" in output["headers"]["cookie"]
    stored = get_run_store().get_run(first["job_id"])
    assert stored is not None and stored.context is not None
    assert stored.context["run"]["triggered_by"] == {
        "id": "usr_system",
        "name": "System",
    }
    assert stored.context["run"]["trigger_kind"] == "inbound"


def test_immediate_echo_uses_query_or_body_and_allows_get(client: TestClient) -> None:
    credential_id = _token(client, location="query", name="access_token")
    channel_id = _live(
        client,
        "Echo",
        "echo",
        credential_id,
        allow_get=True,
        response={
            "mode": "immediate",
            "body": {"kind": "echo", "from": "query", "key": "echostr"},
        },
    )
    echoed = client.get(
        "/hooks/echo", params={"access_token": _SECRET, "echostr": "ping"}
    )
    assert echoed.status_code == 200, echoed.text
    assert echoed.text == "ping"
    assert echoed.headers["content-type"].split(";")[0] == "application/json"
    missing = client.get("/hooks/echo", params={"access_token": _SECRET})
    assert missing.status_code == 200, missing.text
    assert missing.content == b""
    posted = client.post(
        "/hooks/echo",
        params={"access_token": _SECRET},
        json={"echostr": "nope"},
    )
    assert posted.status_code == 200, posted.text
    assert posted.content == b""
    outputs = [
        _trigger_output(client, channel_id, item["job_id"])
        for item in _runs(client, channel_id)["items"]
    ]
    matched = next(item for item in outputs if item["query"].get("echostr") == "ping")
    assert matched["method"] == "GET"
    assert matched["query"] == {"echostr": "ping"}

    body_id = _token(client, name="X-Body-Token")
    _live(
        client,
        "Echo body",
        "echo-body",
        body_id,
        response={
            "mode": "immediate",
            "content_type": "text/plain",
            "body": {"kind": "echo", "from": "body", "key": "challenge.value"},
        },
    )
    nested = client.post(
        "/hooks/echo-body",
        json={"challenge": {"value": "handshake"}},
        headers={"X-Body-Token": _SECRET},
    )
    assert nested.status_code == 200, nested.text
    assert nested.text == "handshake"
    assert nested.headers["content-type"].split(";")[0] == "text/plain"


def test_rejection_list_is_newest_first_and_hides_accepted_calls(
    client: TestClient,
) -> None:
    credential_id = _token(client)
    channel_id = _live(client, "List", "listed", credential_id)
    clock = FixedClock(_WHEN)
    set_clock(clock)
    try:
        first = client.post("/hooks/listed", json={})
        clock.advance(timedelta(seconds=2))
        second = client.post("/hooks/listed", json={})
        accepted = client.post(
            "/hooks/listed",
            json={},
            headers={"X-Hook-Token": _SECRET},
        )
    finally:
        reset_clock()
    assert first.status_code == 401
    assert second.status_code == 401
    assert accepted.status_code == 200, accepted.text
    page = _rejections(client, channel_id, limit=1, offset=0)
    assert page["total"] == 2
    assert page["limit"] == 1
    assert page["offset"] == 0
    assert len(page["items"]) == 1
    assert "hit_count" not in page
    assert page["items"][0]["received_at"] == format_instant(_WHEN + timedelta(seconds=2))
    older = _rejections(client, channel_id, limit=1, offset=1)
    assert older["items"][0]["received_at"] == format_instant(_WHEN)
    assert _runs(client, channel_id)["total"] == 1


def test_rejection_list_requires_channel_read(client: TestClient) -> None:
    credential_id = _token(client)
    channel_id = _live(client, "Guarded", "guarded", credential_id)
    operator = get_role_store().get_by_key("operator")
    assert operator is not None
    get_user_store().create_user(
        account="op",
        display_name="Op",
        password_hash=hash_password("secret"),
        role_id=operator.id,
        status="active",
    )
    anon = client.get(f"/channels/{channel_id}/inbound-rejections")
    # The fixture client is signed in; a fresh client is not.
    with TestClient(app) as fresh:
        anonymous = fresh.get(f"/channels/{channel_id}/inbound-rejections")
        _login(fresh, "op", "secret")
        forbidden = fresh.get(f"/channels/{channel_id}/inbound-rejections")
    assert_problem(anonymous, status=401, code="AUTH_UNAUTHENTICATED")
    assert_problem(forbidden, status=403, code="AUTH_FORBIDDEN")
    assert anon.status_code == 200


def test_respond_node_answers_with_the_first_respond(client: TestClient) -> None:
    credential_id = _token(client)
    channel_id = _publish(
        client,
        "Wait",
        _graph(
            _node(
                credential_id,
                "wait",
                response={
                    "mode": "respond_node",
                    "wait_sec": 5,
                    "fallback": {"status": 503, "body": "fallback-text"},
                },
            ),
            _respond(
                status="201",
                content_type="text/plain",
                headers={"X-Trace": "abc"},
                body='"from-respond"',
            ),
            _after(),
            edges=[
                _edge("ed_reply", "nd_hook", "nd_reply"),
                _edge("ed_after", "nd_reply", "nd_after"),
            ],
        ),
    )
    response = client.post(
        "/hooks/wait",
        json={"n": 1},
        headers={"X-Hook-Token": _SECRET},
    )
    assert response.status_code == 201, response.text
    assert response.text == "from-respond"
    assert response.headers["content-type"].split(";")[0] == "text/plain"
    assert response.headers["x-trace"] == "abc"
    assert _rejections(client, channel_id)["total"] == 0
    job_id = _only_job(client, channel_id)
    detail = client.get(f"/channels/{channel_id}/runs/{job_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    assert _outputs_for(client, channel_id, job_id, "nd_reply") == [
        {
            "status": 201,
            "headers": {"X-Trace": "abc", "Content-Type": "text/plain"},
            "body": "from-respond",
            "delivered": True,
        }
    ]
    assert _outputs_for(client, channel_id, job_id, "nd_after") == [{"done": True}]


def test_respond_sends_a_string_as_text_and_other_json_as_json(
    client: TestClient,
) -> None:
    credential_id = _token(client)
    _publish(
        client,
        "String body",
        _respond_graph(
            credential_id,
            "string-body",
            status="200",
            content_type="application/json",
            body='"hello"',
        ),
    )
    text = _hook(client, "string-body")
    assert text.status_code == 200, text.text
    assert text.text == "hello"
    assert text.headers["content-type"].split(";")[0] == "application/json"

    _publish(
        client,
        "Object body",
        _respond_graph(
            credential_id,
            "object-body",
            status="200",
            content_type="text/plain",
            body='{"n":1}',
        ),
    )
    obj = _hook(client, "object-body")
    assert obj.status_code == 200, obj.text
    assert obj.text == '{"n":1}'
    assert obj.headers["content-type"].split(";")[0] == "text/plain"

    _publish(
        client,
        "False body",
        _respond_graph(
            credential_id,
            "false-body",
            status="200",
            content_type="application/json",
            body="false",
        ),
    )
    false_body = _hook(client, "false-body")
    assert false_body.status_code == 200, false_body.text
    assert false_body.text == "false"

    _publish(
        client,
        "Null body",
        _respond_graph(
            credential_id,
            "null-body",
            status="200",
            content_type="application/json",
            body="null",
        ),
    )
    null_body = _hook(client, "null-body")
    assert null_body.status_code == 200, null_body.text
    assert null_body.text == "null"

    _publish(
        client,
        "Array body",
        _respond_graph(
            credential_id,
            "array-body",
            status="200",
            content_type="application/json",
            body="[1,true]",
        ),
    )
    array_body = _hook(client, "array-body")
    assert array_body.status_code == 200, array_body.text
    assert array_body.text == "[1,true]"


def test_a_later_respond_inside_a_for_does_not_change_the_response(
    client: TestClient,
) -> None:
    credential_id = _token(client)
    again = {
        "id": "nd_again",
        "ref": "again",
        "type": "action.respond",
        "name": "Again",
        "position": {"x": 480, "y": 80},
        "config": {
            "status": "202",
            "content_type": "text/plain",
            "body": '"second"',
        },
        "on_error": "stop",
        "retry": None,
        "parent": "nd_walk",
    }
    channel_id = _publish(
        client,
        "Twice",
        _graph(
            _node(
                credential_id,
                "twice",
                response={"mode": "respond_node", "wait_sec": 5},
            ),
            _respond(
                status="201",
                content_type="text/plain",
                headers={"X-Trace": "one"},
                body='"first"',
            ),
            {
                "id": "nd_walk",
                "ref": "walk",
                "type": "volume.for",
                "name": "Walk",
                "position": {"x": 360, "y": 80},
                "config": {"items": "[1, 2]"},
                "on_error": "stop",
                "retry": None,
            },
            again,
            _after(),
            edges=[
                _edge("ed_reply", "nd_hook", "nd_reply"),
                _edge("ed_walk", "nd_reply", "nd_walk"),
                _edge("ed_each", "nd_walk", "nd_again", source_port="each"),
                _edge("ed_done", "nd_walk", "nd_after", source_port="done"),
            ],
        ),
    )
    response = _hook(client, "twice")
    assert response.status_code == 201, response.text
    assert response.text == "first"
    assert response.headers["x-trace"] == "one"
    job_id = _only_job(client, channel_id)
    assert _outputs_for(client, channel_id, job_id, "nd_reply") == [
        {
            "status": 201,
            "headers": {"X-Trace": "one", "Content-Type": "text/plain"},
            "body": "first",
            "delivered": True,
        }
    ]
    assert _outputs_for(client, channel_id, job_id, "nd_again") == [
        {
            "status": 202,
            "headers": {"Content-Type": "text/plain"},
            "body": "second",
            "delivered": False,
        },
        {
            "status": 202,
            "headers": {"Content-Type": "text/plain"},
            "body": "second",
            "delivered": False,
        },
    ]
    assert _outputs_for(client, channel_id, job_id, "nd_after") == [{"done": True}]


def test_a_respond_after_the_wait_returns_the_fallback(
    client: TestClient,
) -> None:
    credential_id = _token(client)
    channel_id = _publish(
        client,
        "Late",
        _late_graph(credential_id, "late", {"body": "fallback-text"}),
    )
    response = client.post(
        "/hooks/late",
        json={},
        headers={"X-Hook-Token": _SECRET},
    )
    assert response.status_code == 503, response.text
    assert response.text == "fallback-text"
    assert response.headers["content-type"].split(";")[0] == "text/plain"
    assert "late" not in response.text
    assert _rejections(client, channel_id)["total"] == 0
    job_id = _only_job(client, channel_id)
    detail = client.get(f"/channels/{channel_id}/runs/{job_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    assert _outputs_for(client, channel_id, job_id, "nd_reply") == [
        {
            "status": 200,
            "headers": {"Content-Type": "text/plain"},
            "body": "late",
            "delivered": False,
        }
    ]
    assert _outputs_for(client, channel_id, job_id, "nd_after") == [{"done": True}]

    chosen_id = _publish(
        client,
        "Late status",
        _late_graph(
            credential_id,
            "late-status",
            {"status": 429, "body": "retry-later"},
        ),
    )
    chosen = client.post(
        "/hooks/late-status",
        json={},
        headers={"X-Hook-Token": _SECRET},
    )
    assert chosen.status_code == 429, chosen.text
    assert chosen.text == "retry-later"
    chosen_job = _only_job(client, chosen_id)
    assert _outputs_for(client, chosen_id, chosen_job, "nd_reply")[0]["delivered"] is False


def test_rejection_retention_parameter_and_purge(client: TestClient) -> None:
    catalog = client.get("/settings")
    assert catalog.status_code == 200, catalog.text
    item = next(
        row
        for row in catalog.json()["parameters"]
        if row["key"] == "inbound_rejection_retention_days"
    )
    assert item["value"] == 7
    assert item["seed"] == 7
    assert item["constraint"]["minimum"] == 1
    assert item["constraint"]["maximum"] == 3650
    assert item["group"] == "data_channel"
    assert item["operator_action_required"] is False
    assert item["label_key"] == "settings.parameter.inbound_rejection_retention_days.label"

    from backend.worker.schedules import get_schedule_store

    row = get_schedule_store().get_by_key("channel_inbound_rejection_retention")
    assert row is not None
    assert row.hidden is True
    assert row.store_only is True
    assert row.locked is True
    assert row.undeletable is True
    assert row.enabled is True
    assert row.interval_seconds == 3600
    assert row.task_name == "backend.channel.tasks.purge_inbound_rejections"

    credential_id = _token(client)
    channel_id = _live(client, "Aged", "aged", credential_id)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FixedClock(start)
    set_clock(clock)
    try:
        assert client.post("/hooks/aged").status_code == 401
        clock.advance(timedelta(days=2))
        assert client.post("/hooks/aged").status_code == 401
        clock.set(start + timedelta(days=8))
        from backend.channel.tasks import purge_inbound_rejections

        deleted = purge_inbound_rejections()
    finally:
        reset_clock()
    assert deleted == {"deleted": 1}
    page = _rejections(client, channel_id)
    assert page["total"] == 1
    assert page["items"][0]["received_at"] == format_instant(start + timedelta(days=2))


def _trigger_output(client: TestClient, channel_id: str, job_id: str) -> dict:
    response = client.get(
        f"/channels/{channel_id}/runs/{job_id}/executions/1/output"
    )
    assert response.status_code == 200, response.text
    return response.json()["value"]
