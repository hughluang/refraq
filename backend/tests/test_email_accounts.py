"""Email Account catalog, SMTP delivery, and the action.email node."""

from __future__ import annotations

import os
import smtplib
import ssl

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import effective_permissions, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.channel.channel_run import mint_on_demand_run, set_dispatcher  # noqa: E402
from backend.channel.email_accounts import (  # noqa: E402
    TEST_BODY,
    TEST_SUBJECT,
    SmtpDeliveryError,
    create_email_account,
    deliver,
    prepare_message,
    set_opener,
)
from backend.channel.ids import new_channel_id  # noqa: E402
from backend.channel.run_store import get_run_store  # noqa: E402
from backend.channel.runner import run_channel_job  # noqa: E402
from backend.channel.store import ChannelRecord, get_channel_store  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402
from backend.worker.parameters import assemble_system_parameters  # noqa: E402

assemble_system_parameters()


class ProbeSmtp:
    def __init__(self, *, fail_starttls: bool = False, refuse: str | None = None) -> None:
        self.calls: list[object] = []
        self.context: ssl.SSLContext | None = None
        self.fail_starttls = fail_starttls
        self.refuse = refuse

    def ehlo(self) -> None:
        self.calls.append("ehlo")

    def starttls(self, *, context: ssl.SSLContext) -> None:
        self.calls.append("starttls")
        self.context = context
        if self.fail_starttls:
            raise smtplib.SMTPException("STARTTLS failed")

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user, password))

    def mail(self, sender: str) -> tuple[int, bytes]:
        self.calls.append(("mail", sender))
        return 250, b"ok"

    def rcpt(self, recipient: str) -> tuple[int, bytes]:
        self.calls.append(("rcpt", recipient))
        if recipient == self.refuse:
            return 550, b"refused"
        return 250, b"ok"

    def data(self, message: bytes) -> tuple[int, bytes]:
        self.calls.append(("data", message))
        return 250, b"queued"

    def rset(self) -> None:
        self.calls.append("rset")

    def quit(self) -> None:
        self.calls.append("quit")


class _Session:
    def __init__(self) -> None:
        self.probes: list[ProbeSmtp] = []
        self.contexts: list[ssl.SSLContext | None] = []

    def opener(self, record, context: ssl.SSLContext | None):  # type: ignore[no-untyped-def]
        self.contexts.append(context)
        probe = ProbeSmtp(
            fail_starttls=record.host == "fail-tls.example",
            refuse="bad@example.com" if record.host == "refuse.example" else None,
        )
        self.probes.append(probe)
        return probe


@pytest.fixture()
def client() -> TestClient:
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
        yield test_client


def _body(**overrides: object) -> dict:
    body: dict[str, object] = {
        "name": "Office mail",
        "host": "smtp.example.com",
        "port": 587,
        "encryption": "starttls",
        "username": "refraq",
        "password": "secret-pass",
        "from": "refraq@example.com",
    }
    body.update(overrides)
    return body


def _create(client: TestClient, **overrides: object) -> dict:
    created = client.post("/email-accounts", json=_body(**overrides))
    assert created.status_code == 201, created.text
    return created.json()["email_account"]


def test_create_hides_the_password_and_defaults_tls_verification(client: TestClient) -> None:
    created = client.post("/email-accounts", json=_body())
    assert created.status_code == 201, created.text
    assert "secret-pass" not in created.text
    account = created.json()["email_account"]
    assert "password" not in account
    assert account["password_set"] is True
    assert account["tls_skip_verify"] is False
    assert account["from"] == "refraq@example.com"
    assert account["encryption"] == "starttls"


def test_illegal_fields_are_refused(client: TestClient) -> None:
    for body in (
        _body(**{"from": "not an email"}),
        _body(host="smtp.example .com"),
        _body(encryption="ssl"),
        _body(port=0),
    ):
        response = client.post("/email-accounts", json=body)
        assert_problem(response, status=422, code="REQUEST_INVALID")


def test_referenced_delete_is_conflict_and_a_failed_test_keeps_the_account(
    client: TestClient,
) -> None:
    account = _create(client, host="fail-tls.example")
    session = _Session()
    previous = set_opener(session.opener)
    try:
        tested = client.post(
            f"/email-accounts/{account['id']}/test",
            json={"to": "ops@example.com"},
        )
    finally:
        set_opener(previous)
    assert tested.status_code == 200, tested.text
    body = tested.json()
    assert body["ok"] is False
    assert body["email_account"]["host"] == "fail-tls.example"
    assert body["email_account"]["password_set"] is True
    assert body["email_account"]["last_delivery_ok"] is False
    assert "data" not in session.probes[0].calls
    now = utc_now()
    channel = get_channel_store().create(
        ChannelRecord(
            id=new_channel_id(),
            name="Uses mail",
            description=None,
            active=False,
            draft_graph={
                "nodes": [
                    {
                        "id": "nd_mail",
                        "type": "action.email",
                        "config": {
                            "email_account_id": account["id"],
                            "to": "ops@example.com",
                            "subject": "Hi",
                            "body": "Body",
                        },
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
    refused = client.delete(f"/email-accounts/{account['id']}")
    assert_problem(refused, status=409, code="EMAIL_ACCOUNT_IN_USE")
    get_channel_store().delete(channel.id)
    deleted = client.delete(f"/email-accounts/{account['id']}")
    assert deleted.status_code == 204


def test_operator_cannot_list_email_accounts(client: TestClient) -> None:
    roles = get_role_store()
    operator = roles.get_by_key("operator")
    assert operator is not None
    assert "email_account:read" not in effective_permissions(operator)
    if get_user_store().get_by_account("mail-op") is None:
        get_user_store().create_user(
            account="mail-op",
            display_name="Mail Op",
            password_hash=hash_password("secret"),
            role_id=operator.id,
            status="active",
        )
    logged = client.post("/auth/login", json={"account": "mail-op", "password": "secret"})
    assert logged.status_code == 200, logged.text
    response = client.get("/email-accounts")
    assert response.status_code == 403


def test_smtp_sends_one_message_and_refuses_partial_delivery() -> None:
    session = _Session()
    previous = set_opener(session.opener)
    try:
        plain = _account(encryption="none", tls_skip_verify=True, host="plain.example")
        deliver(plain, ["a@example.com"], "Hi", "Body")
        assert session.contexts[-1] is None
        assert "starttls" not in session.probes[-1].calls
        assert any(
            isinstance(item, tuple) and item[0] == "data" for item in session.probes[-1].calls
        )
        with pytest.raises(SmtpDeliveryError):
            prepare_message("a@example.com", "x" * 999, "hi")

        starttls = _account(encryption="starttls", tls_skip_verify=False)
        result = deliver(starttls, ["a@example.com", "b@example.com"], "Hi", "Body")
        assert result.ok is True
        probe = session.probes[-1]
        assert probe.context is not None
        assert probe.context.verify_mode == ssl.CERT_REQUIRED
        data = [item for item in probe.calls if isinstance(item, tuple) and item[0] == "data"]
        assert len(data) == 1
        payload = data[0][1]
        assert isinstance(payload, bytes)
        assert b"Subject: Hi" in payload
        assert b"a@example.com" in payload
        assert b"b@example.com" in payload

        skipped = _account(encryption="starttls", tls_skip_verify=True, host="skip.example")
        deliver(skipped, ["a@example.com"], "Hi", "Body")
        assert session.probes[-1].context is not None
        assert session.probes[-1].context.verify_mode == ssl.CERT_NONE

        implicit = _account(encryption="implicit_tls", tls_skip_verify=False, host="imaps.example")
        deliver(implicit, ["a@example.com"], "Hi", "Body")
        assert "starttls" not in session.probes[-1].calls
        assert session.contexts[-1] is not None
        assert session.contexts[-1].verify_mode == ssl.CERT_REQUIRED

        broken = _account(encryption="starttls", host="fail-tls.example")
        failed = deliver(broken, ["a@example.com"], "Hi", "Body")
        assert failed.ok is False
        assert not any(
            isinstance(item, tuple) and item[0] == "data" for item in session.probes[-1].calls
        )

        refused = _account(encryption="none", host="refuse.example")
        refused_result = deliver(
            refused, ["a@example.com", "bad@example.com"], "Hi", "Body"
        )
        assert refused_result.ok is False
        calls = session.probes[-1].calls
        assert ("rcpt", "bad@example.com") in calls
        assert "rset" in calls
        assert not any(isinstance(item, tuple) and item[0] == "data" for item in calls)
    finally:
        set_opener(previous)


def test_email_node_sends_one_rendered_message_and_a_bad_address_does_not_connect() -> None:
    previous_dispatcher = set_dispatcher(lambda _job_id: None)
    session = _Session()
    previous_opener = set_opener(session.opener)
    try:
        account = create_email_account(
            name="Node",
            host="smtp.example.com",
            port=587,
            encryption="starttls",
            username=None,
            password=None,
            from_address="refraq@example.com",
            tls_skip_verify=False,
            actor_user_id="usr_test",
            actor_token_id=None,
        )
        now = utc_now()
        channel = get_channel_store().create(
            ChannelRecord(
                id=new_channel_id(),
                name="Mails",
                description=None,
                active=True,
                draft_graph={"nodes": [], "edges": [], "settings": {}},
                draft_revision=1,
                draft_updated_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        graph = _graph(account.id, "ops@example.com", "Run {{ self.run.id }}", "Hello")
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
        sent = [item for item in session.probes[-1].calls if isinstance(item, tuple) and item[0] == "data"]
        assert len(sent) == 1
        assert job.id.encode() in sent[0][1]
        assert TEST_SUBJECT.encode() not in sent[0][1]
        executions = get_run_store().list_executions(job.id)
        mailed = next(item for item in executions if item.node_id == "nd_mail")
        assert mailed.output == {"ok": True}

        current = get_channel_store().get(channel.id)
        assert current is not None
        bad = _graph(account.id, "not-an-email", "Hi", "Hello")
        before = len(session.probes)
        drafted = get_channel_store().replace_draft(
            channel.id, base_revision=current.draft_revision, graph=bad, now=utc_now()
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
        assert len(session.probes) == before
        failed = next(
            item for item in get_run_store().list_executions(failed_job.id) if item.node_id == "nd_mail"
        )
        assert failed.status == "failed"
    finally:
        set_opener(previous_opener)
        set_dispatcher(previous_dispatcher)


def _account(**overrides: object):
    fields = {
        "name": "Probe",
        "host": "smtp.example.com",
        "port": 587,
        "encryption": "starttls",
        "username": "refraq",
        "password": "secret-pass",
        "from_address": "refraq@example.com",
        "tls_skip_verify": False,
        "actor_user_id": "usr_test",
        "actor_token_id": None,
    }
    fields.update(overrides)
    return create_email_account(**fields)  # type: ignore[arg-type]


def _graph(account_id: str, to: str, subject: str, body: str) -> dict:
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
                "id": "nd_mail",
                "ref": "notify",
                "type": "action.email",
                "name": "Notify",
                "position": {"x": 0, "y": 120},
                "config": {
                    "email_account_id": account_id,
                    "to": to,
                    "subject": subject,
                    "body": body,
                },
                "on_error": "stop",
                "retry": None,
            },
        ],
        "edges": [
            {
                "id": "ed_start_mail",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_mail", "port": "main"},
            }
        ],
        "settings": {
            "run_timeout_sec": None,
            "run_retry_limit": None,
            "error_channel_id": None,
        },
    }


def test_fixed_test_copy_is_stable() -> None:
    assert TEST_SUBJECT == "refraq email test"
    assert TEST_BODY == "This is a test message from refraq."
