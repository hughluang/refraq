"""A channel discards its own runs only when a keeping setting says so."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.role_store import get_role_store  # noqa: E402
from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.user_store import get_user_store  # noqa: E402
from backend.channel.channel_run import set_dispatcher  # noqa: E402
from backend.channel.tasks import run_job  # noqa: E402
from backend.jobs.store import get_job_store  # noqa: E402
from backend.main import app  # noqa: E402

_KEEP = ("keep_succeeded_runs", "keep_failed_runs", "keep_test_runs")


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
    with TestClient(app) as test_client:
        _login(test_client, "admin", "secret")
        yield test_client


def _manual_graph(**settings: object) -> dict:
    body = {
        "run_timeout_sec": None,
        "run_retry_limit": None,
        "error_channel_id": None,
    }
    body.update(settings)
    return {
        "nodes": [
            {
                "id": "nd_trigger",
                "ref": "run_manually",
                "type": "trigger.manual",
                "name": "Run manually",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            }
        ],
        "edges": [],
        "settings": body,
    }


def test_keep_settings_default_to_keep_and_the_draft_accepts_them(
    client: TestClient,
) -> None:
    created = client.post("/channels", json={"name": "Keep", "description": None})
    assert created.status_code == 201, created.text
    channel_id = created.json()["channel"]["id"]
    draft = client.get(f"/channels/{channel_id}/draft")
    assert draft.status_code == 200, draft.text
    stored = draft.json()["graph"]["settings"]
    assert {key: stored[key] for key in _KEEP} == {key: True for key in _KEEP}

    omitted = _manual_graph()
    for key in _KEEP:
        omitted["settings"].pop(key, None)
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": draft.json()["draft_revision"], "graph": omitted},
    )
    assert saved.status_code == 200, saved.text
    again = saved.json()["graph"]["settings"]
    assert {key: again[key] for key in _KEEP} == {key: True for key in _KEEP}

    turned_off = _manual_graph(
        keep_succeeded_runs=False,
        keep_failed_runs=False,
        keep_test_runs=False,
    )
    updated = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": saved.json()["draft_revision"], "graph": turned_off},
    )
    assert updated.status_code == 200, updated.text
    flags = updated.json()["graph"]["settings"]
    assert {key: flags[key] for key in _KEEP} == {key: False for key in _KEEP}


def _save(client: TestClient, channel_id: str, graph: dict, revision: int) -> int:
    saved = client.put(
        f"/channels/{channel_id}/draft",
        json={"base_revision": revision, "graph": graph},
    )
    assert saved.status_code == 200, saved.text
    return int(saved.json()["draft_revision"])


def _create(client: TestClient, name: str) -> tuple[str, int]:
    created = client.post("/channels", json={"name": name, "description": None})
    assert created.status_code == 201, created.text
    channel = created.json()["channel"]
    draft = client.get(f"/channels/{channel['id']}/draft")
    assert draft.status_code == 200, draft.text
    return channel["id"], int(draft.json()["draft_revision"])


def _run(client: TestClient, channel_id: str, **body: object) -> tuple[int, str | None]:
    previous = set_dispatcher(run_job)
    try:
        started = client.post(f"/channels/{channel_id}/runs", json=body or {"target": "draft"})
    finally:
        set_dispatcher(previous)
    job_id = None
    if started.status_code == 202:
        job_id = started.json()["run"]["job_id"]
    return started.status_code, job_id


def test_an_on_demand_success_is_deleted_only_when_test_runs_are_not_kept(
    client: TestClient,
) -> None:
    channel_id, revision = _create(client, "Test success")
    _save(
        client,
        channel_id,
        _manual_graph(keep_test_runs=False, keep_succeeded_runs=True),
        revision,
    )
    status, job_id = _run(client, channel_id, target="draft")
    assert status == 202
    assert job_id is not None
    assert client.get(f"/channels/{channel_id}/runs/{job_id}").status_code == 404
    assert client.get(f"/jobs/{job_id}").status_code == 404

    kept_id, kept_revision = _create(client, "Test success kept")
    _save(client, kept_id, _manual_graph(keep_test_runs=True), kept_revision)
    kept_status, kept_job = _run(client, kept_id, target="draft")
    assert kept_status == 202
    assert kept_job is not None
    detail = client.get(f"/channels/{kept_id}/runs/{kept_job}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"
    assert client.get(f"/jobs/{kept_job}").status_code == 200


def _code_graph(code: str, **settings: object) -> dict:
    graph = _manual_graph(**settings)
    graph["nodes"].append(
        {
            "id": "nd_code",
            "ref": "work",
            "type": "transform.code",
            "name": "Work",
            "position": {"x": 0, "y": 80},
            "config": {"code": code, "timeout_sec": 30},
            "on_error": "stop",
            "retry": None,
        }
    )
    graph["edges"].append(
        {
            "id": "ed_start_work",
            "source": {"node_id": "nd_trigger", "port": "main"},
            "target": {"node_id": "nd_code", "port": "main"},
        }
    )
    return graph


def _publish(client: TestClient, channel_id: str, revision: int) -> None:
    published = client.post(
        f"/channels/{channel_id}/publish",
        json={"draft_revision": revision},
    )
    assert published.status_code == 201, published.text


def test_an_on_demand_failure_is_deleted_when_test_runs_are_not_kept(
    client: TestClient,
) -> None:
    graph = _code_graph(
        "raise RuntimeError('boom')",
        keep_test_runs=False,
        keep_failed_runs=True,
    )
    draft_id, revision = _create(client, "Draft failure")
    _save(client, draft_id, graph, revision)
    status, job_id = _run(client, draft_id, target="draft")
    assert status == 202, status
    assert job_id is not None
    assert client.get(f"/channels/{draft_id}/runs/{job_id}").status_code == 404
    assert client.get(f"/jobs/{job_id}").status_code == 404

    published_id, published_revision = _create(client, "Published failure")
    saved = _save(client, published_id, graph, published_revision)
    _publish(client, published_id, saved)
    published_status, published_job = _run(client, published_id, target="published")
    assert published_status == 202, published_status
    assert published_job is not None
    assert client.get(f"/channels/{published_id}/runs/{published_job}").status_code == 404
    assert client.get(f"/jobs/{published_job}").status_code == 404


def _error_graph() -> dict:
    return {
        "nodes": [
            {
                "id": "nd_error",
                "ref": "failed_run",
                "type": "trigger.error",
                "name": "Failed run",
                "position": {"x": 0, "y": 0},
                "config": {},
                "on_error": "stop",
                "retry": None,
            }
        ],
        "edges": [],
        "settings": {
            "run_timeout_sec": None,
            "run_retry_limit": None,
            "error_channel_id": None,
        },
    }


def test_a_failed_chain_is_kept_until_retries_end_and_the_error_run_stays(
    client: TestClient,
) -> None:
    error_id, error_revision = _create(client, "Error workflow")
    saved_error = _save(client, error_id, _error_graph(), error_revision)
    _publish(client, error_id, saved_error)
    activated = client.post(f"/channels/{error_id}/activate")
    assert activated.status_code == 200, activated.text

    source_id, source_revision = _create(client, "Retries")
    saved_source = _save(
        client,
        source_id,
        _code_graph(
            "raise RuntimeError('boom')",
            run_retry_limit=1,
            error_channel_id=error_id,
            keep_failed_runs=False,
            keep_test_runs=False,
        ),
        source_revision,
    )
    _publish(client, source_id, saved_source)
    source_active = client.post(f"/channels/{source_id}/activate")
    assert source_active.status_code == 200, source_active.text

    held: list[str] = []

    def dispatch(job_id: str) -> None:
        job = get_job_store().get(job_id)
        if job is not None and job.trigger_kind == "retry":
            held.append(job_id)
            return
        run_job(job_id)

    previous = set_dispatcher(dispatch)
    try:
        started = client.post(
            f"/channels/{source_id}/runs", json={"target": "published"}
        )
    finally:
        set_dispatcher(previous)
    assert started.status_code == 202, started.text
    origin_id = started.json()["run"]["job_id"]
    assert held, "a retry Job should be waiting"
    origin = client.get(f"/channels/{source_id}/runs/{origin_id}")
    assert origin.status_code == 200, origin.text
    assert origin.json()["run"]["status"] == "failed"
    retry_id = held[0]
    assert client.get(f"/jobs/{retry_id}").status_code == 200

    previous = set_dispatcher(run_job)
    try:
        assert run_job(retry_id)["status"] == "failed"
    finally:
        set_dispatcher(previous)

    assert client.get(f"/channels/{source_id}/runs/{origin_id}").status_code == 404
    assert client.get(f"/jobs/{origin_id}").status_code == 404
    assert client.get(f"/channels/{source_id}/runs/{retry_id}").status_code == 404
    assert client.get(f"/jobs/{retry_id}").status_code == 404
    error_runs = client.get(f"/channels/{error_id}/runs")
    assert error_runs.status_code == 200, error_runs.text
    assert error_runs.json()["total"] == 1
    error_job = error_runs.json()["items"][0]["job_id"]
    error_detail = client.get(f"/channels/{error_id}/runs/{error_job}")
    assert error_detail.status_code == 200, error_detail.text
    assert error_detail.json()["run"]["status"] == "succeeded"
    assert client.get(f"/jobs/{error_job}").status_code == 200


def test_a_rerun_follows_the_failed_setting_not_the_test_setting(
    client: TestClient,
) -> None:
    channel_id, revision = _create(client, "Rerun")
    saved = _save(
        client,
        channel_id,
        _code_graph(
            "raise RuntimeError('boom')",
            run_retry_limit=0,
            keep_test_runs=True,
            keep_failed_runs=False,
        ),
        revision,
    )
    _publish(client, channel_id, saved)
    status, origin_id = _run(client, channel_id, target="published")
    assert status == 202
    assert origin_id is not None
    kept = client.get(f"/channels/{channel_id}/runs/{origin_id}")
    assert kept.status_code == 200, kept.text
    assert kept.json()["run"]["status"] == "failed"

    previous = set_dispatcher(run_job)
    try:
        rerun = client.post(f"/channels/{channel_id}/runs/{origin_id}/rerun")
    finally:
        set_dispatcher(previous)
    assert rerun.status_code == 202, rerun.text
    rerun_id = rerun.json()["run"]["job_id"]
    assert rerun_id != origin_id
    assert client.get(f"/channels/{channel_id}/runs/{origin_id}").status_code == 200
    assert client.get(f"/channels/{channel_id}/runs/{rerun_id}").status_code == 404
    assert client.get(f"/jobs/{rerun_id}").status_code == 404


def _changes_graph(**settings: object) -> dict:
    graph = _manual_graph(**settings)
    graph["nodes"].append(
        {
            "id": "nd_read",
            "ref": "changes",
            "type": "read.changes",
            "name": "Read changes",
            "position": {"x": 0, "y": 80},
            "config": {"entity_id": "ent_orders"},
            "on_error": "stop",
            "retry": None,
        }
    )
    graph["edges"].append(
        {
            "id": "ed_start_read",
            "source": {"node_id": "nd_trigger", "port": "main"},
            "target": {"node_id": "nd_read", "port": "main"},
        }
    )
    return graph


def _stub_change_log(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.entity.changes import ChangeEntry, ChangePage
    from backend.entity.heads import EntityHeadShape

    monkeypatch.setattr(
        "backend.channel.references.get_entity_head",
        lambda entity_id: EntityHeadShape(attributes=()),
    )
    monkeypatch.setattr(
        "backend.channel.change_range.recording_enabled",
        lambda entity_id: True,
    )
    monkeypatch.setattr(
        "backend.channel.change_range.purge_mark",
        lambda entity_id: None,
    )
    monkeypatch.setattr("backend.entity.changes.capture_bound", lambda _entity_id: 100)

    def read_changes(entity_id: str, *, after: object, bound: int, limit: int) -> ChangePage:
        del entity_id, after, bound, limit
        return ChangePage(
            entries=[
                ChangeEntry(
                    sequence=3,
                    xact=7,
                    operation="insert",
                    occurred_at="2026-11-01T00:00:00Z",
                    source=None,
                    subject=None,
                    physical_table="entity_data.orders",
                    row_id=1,
                    business_key=None,
                    has_business_key=False,
                    before=None,
                    after={"sku": "a"},
                )
            ],
            has_more=False,
        )

    monkeypatch.setattr("backend.channel.change_range.read_changes", read_changes)


def _failed_published_run(client: TestClient, channel_id: str) -> str:
    from backend.jobs.store import mark_failed

    previous = set_dispatcher(lambda _job_id: None)
    try:
        started = client.post(
            f"/channels/{channel_id}/runs", json={"target": "published"}
        )
    finally:
        set_dispatcher(previous)
    assert started.status_code == 202, started.text
    job_id = started.json()["run"]["job_id"]
    marked = mark_failed(job_id, error_code="CHANNEL_NODE_FAILED", error_summary="failed")
    assert marked is not None and marked.status == "failed"
    return job_id


def test_a_succeeded_rerun_advances_its_checkpoint_before_it_is_deleted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.channel.checkpoints import CheckpointPosition, get_checkpoint_store

    _stub_change_log(monkeypatch)
    channel_id, revision = _create(client, "Changes")
    saved = _save(
        client,
        channel_id,
        _changes_graph(
            keep_succeeded_runs=False,
            keep_failed_runs=True,
            keep_test_runs=True,
        ),
        revision,
    )
    _publish(client, channel_id, saved)
    origin_id = _failed_published_run(client, channel_id)
    previous = set_dispatcher(run_job)
    try:
        rerun = client.post(f"/channels/{channel_id}/runs/{origin_id}/rerun")
    finally:
        set_dispatcher(previous)
    assert rerun.status_code == 202, rerun.text
    rerun_id = rerun.json()["run"]["job_id"]
    assert get_checkpoint_store().read(
        channel_id, "nd_read", "ent_orders"
    ) == CheckpointPosition(xact=7, seq=3)
    assert client.get(f"/channels/{channel_id}/runs/{rerun_id}").status_code == 404
    assert client.get(f"/jobs/{rerun_id}").status_code == 404
    assert client.get(f"/channels/{channel_id}/runs/{origin_id}").status_code == 200


def test_a_succeeded_run_is_kept_when_checkpoint_advance_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_change_log(monkeypatch)

    def explode(run: object) -> None:
        del run
        raise RuntimeError("advance failed")

    monkeypatch.setattr("backend.channel.recovery.advance_from_run", explode)
    channel_id, revision = _create(client, "Advance fails")
    saved = _save(
        client,
        channel_id,
        _changes_graph(keep_succeeded_runs=False, keep_test_runs=False),
        revision,
    )
    _publish(client, channel_id, saved)
    origin_id = _failed_published_run(client, channel_id)
    previous = set_dispatcher(run_job)
    try:
        with pytest.raises(RuntimeError, match="advance failed"):
            client.post(f"/channels/{channel_id}/runs/{origin_id}/rerun")
    finally:
        set_dispatcher(previous)
    listed = client.get(f"/channels/{channel_id}/runs")
    assert listed.status_code == 200, listed.text
    job_ids = {item["job_id"] for item in listed.json()["items"]}
    assert origin_id in job_ids
    assert len(job_ids) == 2


def test_a_cancelled_run_is_kept_when_every_keep_setting_is_false(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.channel.runner import claim_for_execution

    channel_id, revision = _create(client, "Cancelled")
    _save(
        client,
        channel_id,
        _manual_graph(
            keep_succeeded_runs=False,
            keep_failed_runs=False,
            keep_test_runs=False,
        ),
        revision,
    )

    def claim_then_cancel(job_id: str, **kwargs: object) -> object:
        claimed = claim_for_execution(job_id, **kwargs)  # type: ignore[arg-type]
        if claimed is not None:
            claimed.status = "cancelled"
            get_job_store().save(claimed)
        return claimed

    monkeypatch.setattr("backend.channel.runner.claim_for_execution", claim_then_cancel)
    status, job_id = _run(client, channel_id, target="draft")
    assert status == 202
    assert job_id is not None
    detail = client.get(f"/channels/{channel_id}/runs/{job_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "cancelled"
    job = client.get(f"/jobs/{job_id}")
    assert job.status_code == 200, job.text
    assert job.json()["job"]["status"] == "cancelled"


def _for_graph(**settings: object) -> dict:
    graph = _manual_graph(**settings)
    graph["nodes"].extend(
        [
            {
                "id": "nd_walk",
                "ref": "walk",
                "type": "volume.for",
                "name": "Walk",
                "position": {"x": 0, "y": 80},
                "config": {"items": "[1]"},
                "on_error": "stop",
                "retry": None,
            },
            {
                "id": "nd_step",
                "ref": "step",
                "type": "transform.set_fields",
                "name": "Step",
                "position": {"x": 0, "y": 160},
                "config": {"fields": [{"name": "n", "value": "1"}]},
                "on_error": "stop",
                "retry": None,
                "parent": "nd_walk",
            },
        ]
    )
    graph["edges"].extend(
        [
            {
                "id": "ed_in",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_walk", "port": "main"},
            },
            {
                "id": "ed_each",
                "source": {"node_id": "nd_walk", "port": "each"},
                "target": {"node_id": "nd_step", "port": "main"},
            },
        ]
    )
    return graph


def test_a_discarded_run_drops_its_datasets_executions_and_rounds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    from backend.channel.dataset_registry import DatasetRecord, get_dataset_store
    from backend.channel.run_store import get_run_store

    monkeypatch.setattr(
        "backend.channel.dataset_registry.drop_relation", lambda relation: None
    )
    kept_id, kept_revision = _create(client, "Rounds kept")
    _save(client, kept_id, _for_graph(keep_test_runs=True), kept_revision)
    kept_status, kept_job = _run(client, kept_id, target="draft")
    assert kept_status == 202 and kept_job is not None
    kept_executions = client.get(f"/channels/{kept_id}/runs/{kept_job}/executions")
    assert kept_executions.status_code == 200, kept_executions.text
    walk = next(
        item for item in kept_executions.json()["items"] if item["node_id"] == "nd_walk"
    )
    rounds = client.get(
        f"/channels/{kept_id}/runs/{kept_job}/executions/{walk['seq']}/rounds"
    )
    assert rounds.status_code == 200, rounds.text
    assert rounds.json()["total"] == 1

    channel_id, revision = _create(client, "Rounds dropped")
    _save(
        client,
        channel_id,
        _for_graph(keep_test_runs=False, keep_succeeded_runs=True),
        revision,
    )

    def dispatch(job_id: str) -> None:
        get_dataset_store().save(
            DatasetRecord(
                id=f"dset_{job_id}",
                job_id=job_id,
                node_id="nd_walk",
                seq=1,
                relation='"channel_dataset"."ds_discarded"',
                columns=[{"name": "n", "type": "bigint", "normalized_type": "integer"}],
                row_count=1,
                size_bytes=1,
                status="ready",
                created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
            )
        )
        run_job(job_id)

    previous = set_dispatcher(dispatch)
    try:
        started = client.post(f"/channels/{channel_id}/runs", json={"target": "draft"})
    finally:
        set_dispatcher(previous)
    assert started.status_code == 202, started.text
    job_id = started.json()["run"]["job_id"]
    assert client.get(f"/channels/{channel_id}/runs/{job_id}").status_code == 404
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert client.get(f"/channels/{channel_id}/runs/{job_id}/executions").status_code == 404
    dataset = get_dataset_store().get(f"dset_{job_id}")
    assert dataset is not None and dataset.status == "dropped"
    assert get_run_store().list_executions(job_id) == []
    assert get_run_store().query_rounds(job_id, walk["seq"], limit=50, offset=0) == (
        [],
        0,
    )


def test_a_graph_saved_without_keep_keys_keeps_the_run(client: TestClient) -> None:
    from backend.channel.store import get_channel_store

    channel_id, revision = _create(client, "Old graph")
    _save(client, channel_id, _manual_graph(), revision)
    record = get_channel_store().get(channel_id)
    assert record is not None
    for key in _KEEP:
        record.draft_graph["settings"].pop(key, None)
    get_channel_store().save(record)
    status, job_id = _run(client, channel_id, target="draft")
    assert status == 202 and job_id is not None
    detail = client.get(f"/channels/{channel_id}/runs/{job_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["run"]["status"] == "succeeded"


def test_a_run_sees_keep_settings_on_the_channel(client: TestClient) -> None:
    channel_id, revision = _create(client, "Settings visible")
    _save(
        client,
        channel_id,
        _code_graph(
            "return {"
            "'keep_succeeded_runs': self.channel.settings['keep_succeeded_runs'],"
            "'keep_failed_runs': self.channel.settings['keep_failed_runs'],"
            "'keep_test_runs': self.channel.settings['keep_test_runs']"
            "}",
            keep_succeeded_runs=False,
            keep_failed_runs=False,
            keep_test_runs=True,
        ),
        revision,
    )
    status, job_id = _run(client, channel_id, target="draft")
    assert status == 202 and job_id is not None
    detail = client.get(f"/channels/{channel_id}/runs/{job_id}")
    assert detail.status_code == 200, detail.text
    executions = client.get(f"/channels/{channel_id}/runs/{job_id}/executions")
    assert executions.status_code == 200, executions.text
    code = next(
        item for item in executions.json()["items"] if item["node_id"] == "nd_code"
    )
    assert code["output_preview"] == {
        "keep_succeeded_runs": False,
        "keep_failed_runs": False,
        "keep_test_runs": True,
    }
