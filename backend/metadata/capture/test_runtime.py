"""Offline runtime boundary tests; no external services are started."""

import hashlib
import json
from datetime import datetime, timedelta

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from backend.metadata.capture.authority import SignedAuthority

from backend.core.config import get_settings
from backend.core.time import utc_now
from backend.metadata.capture.control import AUTHORITY_KEYS, capture_status
from backend.metadata.capture.runtime import CaptureRuntime, CommandJournal, RuntimeBlocked
from backend.metadata.capture.runtime_adapters import ConnectLifecycle, ReadinessSignals, STOP_PROOFS
from backend.metadata.capture.runtime_store import protected_read
from backend.metadata.mirrors import service as mirrors
from backend.metadata.mirrors.store import MemoryMirrorStore
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

    def request(self, method, path, payload=None, **kwargs):
        response = self.client.request(method, path, json=payload)
        return response.json() if response.content else None


SIGNING_KEY = Ed25519PrivateKey.generate()
TRUST = SignedAuthority(keys={"trusted": SIGNING_KEY.public_key()}, issuer="gateway", audience="capture")
RUNNING_PROOFS = ("credential_installed_ref", "credential_revoked_ref", "task_running_ref")


def observation(cmd, phase, *, checks=None, omit_proofs=(), observed_at=None):
    authority = {key: cmd[key] for key in AUTHORITY_KEYS}
    observed_at = observed_at if observed_at is not None else utc_now().isoformat()
    proofs = {}
    for key in STOP_PROOFS | {"owner_assignment_ref", *RUNNING_PROOFS}:
        proof = {"authority": authority, "operation_id": cmd["operation_id"],
                 "observed_at": observed_at, "facts": {key.removesuffix("_ref"): True}}
        digest = hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        proofs[key] = {**proof, "ref": "sha256:" + digest, "verified": True}
    for key in omit_proofs:
        del proofs[key]
    result = {"authority": authority, "observed_at": observed_at, "proofs": proofs,
              "checks": {**dict.fromkeys(CHECKS, "pass"), **(checks or {})}}
    now = utc_now()
    result["signature"] = jwt.encode({
        "iss": "gateway", "aud": "capture", "iat": now, "nbf": now,
        "exp": now + timedelta(seconds=60), "jti": "fresh-proof",
        "purpose": "observation:" + phase, "authority": authority,
        "scope": None, "operation_id": cmd["operation_id"], "observation": dict(result),
    }, SIGNING_KEY, algorithm="EdDSA", headers={"kid": "trusted"})
    return result


CHECKS = ["profile_qualified", "source_pressure", "delivery_bounded", "credential_valid",
          "alarm_drill", "owner_excluded", "target_fenced"]


def allocation_observation(payload):
    cmd, previous = payload["command"], payload["previous_authority"]
    refs = ["sha256:" + hashlib.sha256(kind.encode()).hexdigest()
            for kind in ("agent", "task", "inventory")]
    return dict(
        command=cmd, previous_authority=previous, observed_at=utc_now().isoformat(),
        checks=dict.fromkeys(CHECKS, "pass"),
        exclusion=dict(method="terminated" if previous["owner_epoch"] else "initial_absence",
                       agent_receipt=refs[0], task_receipt=refs[1]),
        target_fence=dict(authority={key: cmd[key] for key in AUTHORITY_KEYS}, operation_id=cmd["operation_id"],
                          inventory_receipt=refs[2], mirror_receipts={
                              table["mirror_id"]: "sha256:" + hashlib.sha256(table["mirror_id"].encode()).hexdigest()
                              for table in cmd["published_scope"]
                          }),
    )


@pytest.fixture
def managed_command(monkeypatch, request):
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "memory")
    monkeypatch.setattr(mirrors, "_store", MemoryMirrorStore())
    monkeypatch.setattr(mirrors, "_target", None)
    get_settings.cache_clear()
    reset_source_store()
    request.addfinalizer(get_settings.cache_clear)
    request.addfinalizer(reset_source_store)
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
    return cmd


TERMINAL_STOP_PROOFS = (
    "retired_commands_rejected_ref", "task_stopped_ref", "source_session_stopped_ref",
    "inflight_drained_ref",
)


@pytest.mark.parametrize(("readiness", "terminal_fault", "reason"), [
    ("fail", None, None),
    ("unknown", None, None),
    *(("unknown", proof, "proof_unverified") for proof in TERMINAL_STOP_PROOFS),
    ("unknown", "owner_assignment_ref", "proof_unverified"),
    ("unknown", "unsigned", "signed_authority_unverified"),
    ("unknown", "wrong_phase", "signed_authority_unverified"),
    ("unknown", "stale", "observation_stale"),
])
def test_current_owner_can_stop_but_needs_terminal_proof_to_ack(
    tmp_path, managed_command, readiness, terminal_fault, reason,
):
    stop_requests = []

    def handler(request):
        if request.url.path == "/v1/capture/observations":
            payload = json.loads(request.content)
            cmd = payload["command"]
            checks = {"source_pressure": readiness, "credential_valid": readiness}
            if payload["phase"] == "before_stop":
                return httpx.Response(200, json=observation(
                    cmd, "before_stop", checks=checks, omit_proofs=(*TERMINAL_STOP_PROOFS, *RUNNING_PROOFS),
                ))
            assert payload["phase"] == "stopped"
            fault = terminal_fault or ""
            observed_at = None
            if fault == "stale":
                observed_at = (datetime.fromisoformat(cmd["requested_at"]) - timedelta(seconds=1)).isoformat()
            result = observation(
                cmd, "before_stop" if fault == "wrong_phase" else "stopped", checks=checks,
                omit_proofs=(fault,) if fault.endswith("_ref") else (), observed_at=observed_at,
            )
            if fault == "unsigned":
                del result["signature"]
            return httpx.Response(200, json=result)
        if request.method == "PUT":
            assert request.url.path == "/connectors/cap_one/stop"
            stop_requests.append(request.url.path)
        state = "STOPPED" if stop_requests else "RUNNING"
        return httpx.Response(200, json={"connector": {"state": state}, "tasks": []})

    http = FakeHTTP(handler)
    journal = CommandJournal(tmp_path)
    try:
        runtime = CaptureRuntime(journal=journal, connect=ConnectLifecycle(http, "cap_one"),
                                 signals=ReadinessSignals(http, verifier=TRUST, runtime_instance_id="agent-one",
                                                          max_age_seconds=30, required_checks=CHECKS))
        source_id = managed_command["source_id"]
        if reason is None:
            assert runtime.poll_source(source_id) == "applied"
            assert capture_status(source_id)["control"]["stop_ack"]["operation_id"] == managed_command["operation_id"]
        else:
            with pytest.raises(RuntimeBlocked, match=reason):
                runtime.poll_source(source_id)
            assert capture_status(source_id)["control"]["stop_ack"] is None
        assert len(stop_requests) == 1
    finally:
        journal.close()
        http.client.close()


@pytest.mark.parametrize("phase", ["before_start", "before_configure", "before_resume", "running"])
@pytest.mark.parametrize("failed_check", ["source_pressure", "credential_valid"])
@pytest.mark.parametrize("readiness", ["fail", "unknown"])
def test_running_state_requires_signed_start_readiness(phase, failed_check, readiness):
    cmd = {**command(), "kind": "reconcile"}

    def handler(request):
        payload = json.loads(request.content)
        return httpx.Response(200, json=observation(
            payload["command"], payload["phase"], checks={failed_check: readiness},
        ))

    http = FakeHTTP(handler)
    try:
        signals = ReadinessSignals(http, verifier=TRUST, runtime_instance_id="agent-one",
                                   max_age_seconds=30, required_checks=CHECKS)
        with pytest.raises(RuntimeBlocked, match="readiness_unknown_or_failed"):
            signals.observation(cmd, phase)
    finally:
        http.client.close()


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
                              signals=ReadinessSignals(http, verifier=TRUST, runtime_instance_id="agent-one",
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


@pytest.mark.parametrize(("fault", "reason"), [
    ("unknown", "signed_observation_mismatch"),
    ("placeholder", "signed_observation_mismatch"),
    ("owner_assignment_ref", "proof_unverified"),
    ("owner_exclusion_ref", "proof_unverified"),
    ("target_fence_ref", "proof_unverified"),
    ("owner", "signed_authority_unverified"),
    ("unsigned", "signed_authority_unverified"),
    ("stale", "observation_stale"),
    ("tampered", "signed_observation_mismatch"),
])
def test_unverified_readiness_and_proofs_block_before_connect(tmp_path, managed_command, fault, reason):
    cmd = managed_command
    def handler(request):
        assert request.url.path == "/v1/capture/observations", "Connect was reached before admission"
        result = observation(
            {**cmd, "owner_epoch": cmd["owner_epoch"] - 1} if fault == "owner" else cmd,
            "before_stop",
            omit_proofs=(fault,) if fault.endswith("_ref") else (),
            observed_at="2020-01-01T00:00:00+00:00" if fault == "stale" else None,
        )
        if fault == "unknown":
            result["checks"]["source_pressure"] = "unknown"
        elif fault == "placeholder":
            result["proofs"]["owner_exclusion_ref"] = "approved"
        elif fault == "unsigned":
            del result["signature"]
        elif fault == "tampered":
            result["proofs"]["target_fence_ref"]["facts"] = {"target_fence": False}
        return httpx.Response(200, json=result)
    http = FakeHTTP(handler)
    journal = CommandJournal(tmp_path)
    agent = CaptureRuntime(journal=journal, connect=ConnectLifecycle(http, "cap_one"),
                           signals=ReadinessSignals(http, verifier=TRUST, runtime_instance_id="agent-one",
                                                    max_age_seconds=30, required_checks=CHECKS))
    with pytest.raises(RuntimeBlocked, match=reason):
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
