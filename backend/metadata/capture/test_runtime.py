"""Offline runtime boundary tests; no external services are started."""

import hashlib
import json

import httpx
import pytest

from backend.core.config import get_settings
from backend.core.time import utc_now
from backend.metadata.capture.control import AUTHORITY_KEYS, capture_status
from backend.metadata.capture.runtime import CaptureRuntime, CommandJournal, RuntimeBlocked
from backend.metadata.capture.runtime_adapters import ConnectLifecycle, ReadinessSignals, STOP_PROOFS
from backend.metadata.capture.runtime_store import protected_read
from backend.metadata.sources.store import SourceRecord, get_source_store, reset_source_store


def command(revision=2):
    return {
        "source_id": "source-one", "binding_id": "cap_one", "owner_epoch": 1,
        "runtime_instance_id": "agent-one", "capture_generation": 1,
        "control_revision": revision, "credential_revision": 1,
        "operation_id": f"cop_{revision}", "kind": "stop",
        "snapshot_window": None, "requested_at": utc_now().isoformat(),
    }


def test_journal_survives_restart_and_rejects_stale_or_conflicting_commands(tmp_path):
    current = command()
    journal = CommandJournal(tmp_path)
    with journal.source_lock("source-one"):
        assert journal.accept(current) == "pending"
        journal.mark(current, "uncertain")
    journal.close()
    journal = CommandJournal(tmp_path)
    assert journal.accept(current) == "uncertain"
    with pytest.raises(RuntimeBlocked):
        journal.accept(command(1))
    with pytest.raises(RuntimeBlocked):
        journal.accept({**current, "kind": "reconcile"})
    second = CommandJournal(tmp_path)
    with journal.source_lock("source-one"):
        with pytest.raises(RuntimeBlocked):
            with second.source_lock("source-one"):
                pytest.fail("second executor entered the Source lock")
    second.close()
    journal.close()


def test_retired_duplicate_does_not_bypass_high_water_stamp(tmp_path):
    journal = CommandJournal(tmp_path)
    old = command(1)
    journal.accept(old)
    journal.accept(command(2))
    with pytest.raises(RuntimeBlocked):
        journal.accept(old)
    journal.close()


class FakeHTTP:
    """Fake only the external HTTP boundary, retaining real domain adapters."""

    def __init__(self, handler):
        self.client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://private")

    def request(self, method, path, payload=None):
        response = self.client.request(method, path, json=payload)
        return response.json() if response.content else None


def observation(cmd, phase):
    authority = {key: cmd[key] for key in AUTHORITY_KEYS}
    observed_at = utc_now().isoformat()
    proofs = {}
    for key in STOP_PROOFS | {"owner_assignment_ref"}:
        proof = {"authority": authority, "operation_id": cmd["operation_id"],
                 "observed_at": observed_at, "facts": {key.removesuffix("_ref"): True}}
        digest = hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        proofs[key] = {**proof, "ref": "sha256:" + digest, "verified": True}
    return {"authority": authority, "observed_at": observed_at, "proofs": proofs,
            "checks": {key: "pass" for key in CHECKS}}


CHECKS = ["profile_qualified", "source_pressure", "delivery_bounded", "credential_valid",
          "alarm_drill", "owner_excluded", "target_fenced"]


@pytest.fixture
def managed_command(monkeypatch):
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    get_settings.cache_clear()
    reset_source_store()
    cmd = command()
    store = get_source_store()
    now = utc_now()
    store.create_source(SourceRecord(
        id=cmd["source_id"], key="one", locator_key="one", name="One", kind="database",
        status="disabled", description=None, engine="postgresql", access_ciphertext=None,
        access_updated_at=None, created_at=now, updated_at=now,
    ))
    store.capture_bindings[cmd["source_id"]] = {
        **{key: cmd[key] for key in AUTHORITY_KEYS}, "desired": "stopped",
        "stop_ack": None, "observed_at": None, "applied_revision": None,
    }
    store.capture_operations[cmd["operation_id"]] = {"command": cmd, "evidence": None}
    yield cmd
    reset_source_store()
    get_settings.cache_clear()


def test_real_durable_intent_stop_recovers_response_loss_without_second_mutation(tmp_path, managed_command):
    cmd = managed_command
    external = {"stopped": False, "mutations": 0}

    def handler(request):
        if request.url.path == "/v1/capture/observations":
            payload = json.loads(request.content)
            return httpx.Response(200, json=observation(payload["command"], payload["phase"]))
        if request.method == "PUT":
            assert request.url.path.endswith("/stop")
            external["mutations"] += 1
            external["stopped"] = True
            raise RuntimeBlocked("private_http_uncertain")
        return httpx.Response(200, json={"connector": {"state": "STOPPED" if external["stopped"] else "RUNNING"}, "tasks": []})

    http = FakeHTTP(handler)
    journal = CommandJournal(tmp_path)
    def runtime(journal):
        return CaptureRuntime(journal=journal, connect=ConnectLifecycle(http, "cap_one"),
                              signals=ReadinessSignals(http, runtime_instance_id="agent-one",
                                                       max_age_seconds=30, required_checks=CHECKS))
    with pytest.raises(RuntimeBlocked, match="private_http_uncertain"):
        runtime(journal).poll_source(cmd["source_id"])
    assert capture_status(cmd["source_id"])["control"]["stop_ack"] is None
    journal.close()
    journal = CommandJournal(tmp_path)
    assert runtime(journal).poll_source(cmd["source_id"]) == "applied"
    assert external["mutations"] == 1
    assert capture_status(cmd["source_id"])["availability"] == "disabled"
    assert runtime(journal).poll_source(cmd["source_id"]) == "idle"
    journal.close()
    http.client.close()


@pytest.mark.parametrize("fault", ["unknown", "placeholder", "assignment", "owner", "stale", "tampered"])
def test_unverified_readiness_and_proofs_block_before_connect(tmp_path, managed_command, fault):
    cmd = managed_command
    def handler(request):
        assert request.url.path == "/v1/capture/observations", "Connect was reached before admission"
        result = observation(cmd, "before_stop")
        if fault == "unknown":
            result["checks"]["source_pressure"] = "unknown"
        elif fault == "placeholder":
            result["proofs"]["owner_exclusion_ref"] = "approved"
        elif fault == "assignment":
            result["proofs"].pop("owner_assignment_ref")
        elif fault == "owner":
            result["authority"]["runtime_instance_id"] = None
        elif fault == "stale":
            result["observed_at"] = "2020-01-01T00:00:00+00:00"
        else:
            result["proofs"]["target_fence_ref"]["facts"] = {"target_fence": False}
        return httpx.Response(200, json=result)
    http = FakeHTTP(handler)
    journal = CommandJournal(tmp_path)
    agent = CaptureRuntime(journal=journal, connect=ConnectLifecycle(http, "cap_one"),
                           signals=ReadinessSignals(http, runtime_instance_id="agent-one",
                                                    max_age_seconds=30, required_checks=CHECKS))
    with pytest.raises(RuntimeBlocked):
        agent.poll_source(cmd["source_id"])
    assert capture_status(cmd["source_id"])["control"]["stop_ack"] is None
    journal.close()
    http.client.close()


@pytest.mark.parametrize("payload", [{"connector": None, "tasks": []}, {"connector": {"state": "STOPPED"}, "tasks": [None]}, {}])
def test_unknown_connect_status_is_not_stop_proof(payload):
    http = FakeHTTP(lambda request: httpx.Response(200, json=payload))
    assert ConnectLifecycle(http, "cap_one").stopped() is False
    http.client.close()


def test_secret_permissions_and_connector_path_are_not_optional(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("do-not-disclose")
    secret.chmod(0o644)
    with pytest.raises(RuntimeBlocked, match="protected_file_required"):
        protected_read(secret)
    secret.chmod(0o600)
    assert protected_read(secret) == b"do-not-disclose"
    link = tmp_path / "link"
    link.symlink_to(secret)
    with pytest.raises(OSError):
        protected_read(link)
    with pytest.raises(RuntimeBlocked):
        ConnectLifecycle(None, "../other/snapshot")
