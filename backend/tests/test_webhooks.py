"""Webhook catalog, delivery, and the action.webhook node."""

from __future__ import annotations

import json
import os
import socket

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.tests.problem import assert_problem  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.channel.channel_run import mint_on_demand_run, set_dispatcher  # noqa: E402
from backend.channel.ids import new_channel_id  # noqa: E402
from backend.channel.runner import run_channel_job  # noqa: E402
from backend.channel.run_store import get_run_store  # noqa: E402
from backend.channel.store import ChannelRecord, get_channel_store  # noqa: E402
from backend.channel.webhooks import set_poster, set_resolver  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.main import app  # noqa: E402
from backend.worker.parameters import assemble_system_parameters  # noqa: E402

assemble_system_parameters()

PUBLIC = "https://hooks.example/refraq"


def _resolve(host: str, port: int, family: int, socktype: int) -> list:
    del family, socktype
    ip = "127.0.0.1" if host in {"localhost", "metadata.google.internal"} else "93.184.216.34"
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, port))]


@pytest.fixture()
def client() -> TestClient:
    previous_resolver = set_resolver(_resolve)
    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    if get_user_store().get_by_account("admin") is None:
        get_user_store().create_user(
            account="admin",
            display_name="Admin",
            password_hash=hash_password("secret"),
            role_id=admin.id,
            status="active",
        )
    with TestClient(app) as test_client:
        logged = test_client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert logged.status_code == 200, logged.text
        try:
            yield test_client
        finally:
            set_resolver(previous_resolver)


def _create(client: TestClient, name: str = "On-call", secret: str | None = "token") -> dict:
    body = {"name": name, "url": PUBLIC, "secret": secret}
    created = client.post("/webhooks", json=body)
    assert created.status_code == 201, created.text
    return created.json()["webhook"]


def test_illegal_addresses_are_refused(client: TestClient) -> None:
    for url in (
        "http://hooks.example/refraq",
        "https://user:pass@hooks.example/refraq",
        "https://127.0.0.1/hook",
        "https://10.1.2.3/hook",
        "https://169.254.169.254/latest",
        "https://localhost/hook",
    ):
        response = client.post("/webhooks", json={"name": "Bad", "url": url})
        assert_problem(response, status=422, code="WEBHOOK_URL_REJECTED")


def test_referenced_delete_is_conflict_and_a_failed_test_keeps_the_url(
    client: TestClient,
) -> None:
    webhook = _create(client)
    calls: list[dict] = []

    def poster(url: str, payload: dict, headers: dict) -> tuple[int, str | None]:
        calls.append({"url": url, "payload": payload, "headers": headers})
        return 500, "HTTP 500"

    previous = set_poster(poster)
    try:
        tested = client.post(f"/webhooks/{webhook['id']}/test")
    finally:
        set_poster(previous)
    assert tested.status_code == 200, tested.text
    body = tested.json()
    assert body["ok"] is False
    assert body["status_code"] == 500
    assert body["webhook"]["url"] == PUBLIC
    assert body["webhook"]["name"] == "On-call"
    assert body["webhook"]["secret_set"] is True
    assert calls[0]["payload"] == {"event": "webhook.test", "webhook_id": webhook["id"]}
    assert calls[0]["headers"]["Authorization"] == "Bearer token"
    now = utc_now()
    channel = get_channel_store().create(
        ChannelRecord(
            id=new_channel_id(),
            name="Uses hook",
            description=None,
            active=False,
            draft_graph={
                "nodes": [
                    {
                        "id": "nd_hook",
                        "type": "action.webhook",
                        "config": {"webhook_id": webhook["id"], "body": "{}"},
                    }
                ],
                "edges": [],
                "settings": {},
            },
            draft_revision=1,
            draft_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    refused = client.delete(f"/webhooks/{webhook['id']}")
    assert_problem(refused, status=409, code="WEBHOOK_IN_USE")
    get_channel_store().delete(channel.id)
    deleted = client.delete(f"/webhooks/{webhook['id']}")
    assert deleted.status_code == 204


def test_webhook_node_posts_the_rendered_body_and_a_delivery_failure_fails_the_node() -> None:
    previous_resolver = set_resolver(_resolve)
    previous_dispatcher = set_dispatcher(lambda _job_id: None)
    calls: list[dict] = []

    def poster(url: str, payload: dict, headers: dict) -> tuple[int, str | None]:
        del headers
        calls.append({"url": url, "payload": payload})
        if payload.get("fail"):
            return 502, "HTTP 502"
        return 204, None

    previous_poster = set_poster(poster)
    try:
        from backend.channel.webhooks import create_webhook

        webhook = create_webhook(
            name="Node",
            url=PUBLIC,
            secret=None,
            actor_user_id="usr_test",
            actor_token_id=None,
        )
        now = utc_now()
        channel = get_channel_store().create(
            ChannelRecord(
                id=new_channel_id(),
                name="Posts",
                description=None,
                active=True,
                draft_graph={"nodes": [], "edges": [], "settings": {}},
                draft_revision=1,
                draft_updated_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        graph = _graph(webhook.id, '{"job":"{{ self.run.id }}"}')
        drafted = get_channel_store().replace_draft(
            channel.id, base_revision=1, graph=graph, now=utc_now()
        )
        get_channel_store().publish_version(
            channel.id,
            draft_revision=drafted.draft_revision,
            published_at=utc_now(),
            published_by_user_id="usr_test",
        )
        job, _record = mint_on_demand_run(
            channel_id=channel.id,
            channel_name=channel.name,
            target="published",
            ignore_checkpoints=False,
            actor_id="usr_author",
            trigger_node_id="nd_trigger",
            version=None,
            draft_revision=None,
            graph=None,
            stop_at_node_id=None,
        )
        assert run_channel_job(job.id) == {"status": "succeeded"}
        assert calls[-1]["url"] == PUBLIC
        assert calls[-1]["payload"] == {"job": job.id}
        failing = _graph(webhook.id, '{"fail": true}')
        current = get_channel_store().get(channel.id)
        assert current is not None
        drafted = get_channel_store().replace_draft(
            channel.id, base_revision=current.draft_revision, graph=failing, now=utc_now()
        )
        get_channel_store().publish_version(
            channel.id,
            draft_revision=drafted.draft_revision,
            published_at=utc_now(),
            published_by_user_id="usr_test",
        )
        failed_job, _record = mint_on_demand_run(
            channel_id=channel.id,
            channel_name=channel.name,
            target="published",
            ignore_checkpoints=False,
            actor_id="usr_author",
            trigger_node_id="nd_trigger",
            version=None,
            draft_revision=None,
            graph=None,
            stop_at_node_id=None,
        )
        assert run_channel_job(failed_job.id) == {"status": "failed"}
        executions = get_run_store().list_executions(failed_job.id)
        hook = next(item for item in executions if item.node_id == "nd_hook")
        assert hook.status == "failed"
        assert calls[-1]["payload"] == {"fail": True}
    finally:
        set_poster(previous_poster)
        set_dispatcher(previous_dispatcher)
        set_resolver(previous_resolver)


def _graph(webhook_id: str, body: str) -> dict:
    json.loads(body.replace("{{ self.run.id }}", "job_x"))
    return {
        "nodes": [
            {
                "id": "nd_trigger",
                "ref": "start",
                "type": "trigger.manual",
                "name": "Start",
                "position": {"x": 0, "y": 0},
                "config": {"payload": {}},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_hook",
                "ref": "notify",
                "type": "action.webhook",
                "name": "Notify",
                "position": {"x": 0, "y": 120},
                "config": {"webhook_id": webhook_id, "body": body},
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "ed_start_hook",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_hook", "port": "main"},
            }
        ],
        "settings": {
            "run_timeout_sec": None,
            "run_retry_limit": None,
            "error_channel_id": None,
        },
    }
