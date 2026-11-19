"""Bounded private TLS adapters; Connect is lifecycle-only."""

from dataclasses import asdict
import hashlib
import json
import re
import ssl
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from backend.core.time import utc_now
from backend.metadata.capture.control import AUTHORITY_KEYS
from backend.metadata.capture.runtime_store import RuntimeBlocked, protected_read


class PrivateHTTP:
    def __init__(self, *, origin, ca_file, cert_file, key_file, timeout_seconds,
                 max_response_bytes, transport=None):
        url = urlsplit(origin)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path not in {"", "/"} or url.query or url.fragment):
            raise RuntimeBlocked("private_https_origin_required")
        if not 0 < timeout_seconds <= 120 or not 0 < max_response_bytes <= 1048576:
            raise RuntimeBlocked("invalid_transport_bounds")
        protected_read(ca_file)
        protected_read(cert_file)
        protected_read(key_file)
        context = ssl.create_default_context(cafile=str(ca_file))
        context.load_cert_chain(str(cert_file), str(key_file))
        self.client = httpx.Client(
            base_url=origin.rstrip("/"), verify=context, timeout=timeout_seconds,
            follow_redirects=False, trust_env=False, transport=transport,
        )
        self.limit = max_response_bytes

    def request(self, method, path, payload=None, *, missing=False):
        try:
            with self.client.stream(method, path, json=payload) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.limit:
                        raise RuntimeBlocked("response_bound_exceeded")
                if missing and response.status_code == 404:
                    return None
                if response.status_code not in {200, 201, 202, 204}:
                    raise RuntimeBlocked("private_http_unconfirmed")
                return json.loads(body) if body else None
        except (httpx.HTTPError, ValueError):
            raise RuntimeBlocked("private_http_uncertain") from None

    def close(self):
        self.client.close()


class ConnectLifecycle:
    def __init__(self, http, connector_name):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", connector_name):
            raise RuntimeBlocked("connector_not_allowlisted")
        self.http = http
        self.name = connector_name
        self.path = "/connectors/" + connector_name

    def stop(self):
        # Stop preserves offsets and the connector. It is never delete/pause.
        self.http.request("PUT", self.path + "/stop")

    def configure(self, config):
        self.http.request("PUT", self.path + "/config", config)

    def configured(self, config):
        observed = self.http.request("GET", self.path + "/config", missing=True)
        return observed == config or observed == {**config, "name": self.name}

    def resume(self):
        self.http.request("PUT", self.path + "/resume")

    def running(self):
        status = self.http.request("GET", self.path + "/status")
        return (isinstance(status, dict) and isinstance(status.get("connector"), dict)
                and status["connector"].get("state") == "RUNNING"
                and isinstance(status.get("tasks"), list) and bool(status["tasks"])
                and all(isinstance(task, dict) and task.get("state") == "RUNNING"
                        for task in status["tasks"]))

    def stopped(self):
        status = self.http.request("GET", self.path + "/status")
        return (
            isinstance(status, dict)
            and isinstance(status.get("connector"), dict)
            and status["connector"].get("state") == "STOPPED"
            and isinstance(status.get("tasks"), list)
            and all(isinstance(task, dict) and task.get("state") == "STOPPED"
                    for task in status["tasks"])
        )


class SnapshotGateway:
    def __init__(self, *, dispatch, receipt, notification):
        self.dispatch = dispatch
        self.receipt_observer = receipt
        self.notification_observer = notification

    @staticmethod
    def _request(http, step, binding, operation_id, *, missing=False, **payload):
        scope = asdict(binding)
        return http.request("POST", f"/v1/capture/snapshots/{step}", {
            "authority": scope["authority"], "scope": scope, "operation_id": operation_id, **payload,
        }, missing=missing)

    def _observe(self, http, step, binding, operation_id, **payload):
        response = self._request(http, step, binding, operation_id, missing=True, **payload)
        if response is None:
            return None
        if not isinstance(response, dict) or not isinstance(response.get("signature"), str):
            raise RuntimeBlocked("snapshot_observation_invalid")
        return response["signature"]

    def baseline(self, binding, operation_id, *, challenge):
        return self._observe(self.notification_observer, "baseline", binding, operation_id, challenge=challenge)

    def submit(self, binding, signal):
        try:
            self._request(self.dispatch, "submit", binding, signal["id"], signal=signal)
        except RuntimeBlocked:
            raise TimeoutError() from None

    def receipt(self, binding, operation_id):
        return self._observe(self.receipt_observer, "receipt", binding, operation_id)

    def notifications(self, binding, operation_id, offset, *, challenge):
        return self._observe(self.notification_observer, "notifications", binding, operation_id,
                             offset=offset, challenge=challenge)


STOP_PROOFS = {
    "target_fence_ref", "owner_exclusion_ref", "retired_commands_rejected_ref",
    "task_stopped_ref", "source_session_stopped_ref", "inflight_drained_ref",
}


def _digest_ref(value):
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


class ReadinessSignals:
    """Read independently substantiated attestations from a deployment-owned gateway.

    The gateway must resolve proof objects, not echo caller-provided references.
    Snapshot terminal signals can be observed here but are not start authority.
    """

    def __init__(self, http, *, runtime_instance_id, max_age_seconds, required_checks,
                 verifier=None, scope=None):
        mandatory = {"profile_qualified", "source_pressure", "delivery_bounded",
                     "credential_valid", "alarm_drill", "owner_excluded", "target_fenced"}
        if (not runtime_instance_id or not 0 < max_age_seconds <= 3600
                or not mandatory.issubset(set(required_checks))):
            raise RuntimeBlocked("explicit_readiness_policy_required")
        self.http = http
        self.runtime_instance_id = runtime_instance_id
        self.max_age = max_age_seconds
        self.required = set(required_checks)
        self.verifier = verifier
        self.scope = scope

    def allocation_observation(self, pending, authorization):
        command = pending["command"]
        authority = {key: command[key] for key in AUTHORITY_KEYS}
        previous = pending["previous_authority"]
        result = self.http.request("POST", "/v1/capture/owner-allocations", {
            "command": command, "previous_authority": previous, "scope": pending["scope"],
            "authorization": authorization,
        })
        if not isinstance(result, dict):
            raise RuntimeBlocked("allocation_evidence_unknown")
        signed = self.verifier.verify(
            result.get("signature"), purpose="observation:owner_allocation", authority=authority,
            scope=pending["scope"], operation_id=command["operation_id"],
        )
        observation = signed.get("observation")
        if (not isinstance(observation, dict) or observation.get("command") != command
                or observation.get("previous_authority") != previous):
            raise RuntimeBlocked("allocation_observation_mismatch")
        self._require_fresh(observation, command)
        if command["kind"] == "reconcile":
            self._require_readiness(observation)

        exclusion = observation.get("exclusion")
        methods = ("terminated", "authority_revoked") if previous["owner_epoch"] else ("initial_absence",)
        if (not isinstance(exclusion, dict) or exclusion.get("method") not in methods
                or not _digest_ref(exclusion.get("agent_receipt"))
                or not _digest_ref(exclusion.get("task_receipt"))):
            raise RuntimeBlocked("allocation_exclusion_unproven")
        fence = observation.get("target_fence")
        mirrors = {table["mirror_id"] for table in command["published_scope"]}
        if (not isinstance(fence, dict) or fence.get("authority") != authority
                or fence.get("operation_id") != command["operation_id"]
                or not _digest_ref(fence.get("inventory_receipt"))
                or not isinstance(fence.get("mirror_receipts"), dict)
                or not mirrors.issubset(fence["mirror_receipts"])
                or not all(_digest_ref(ref) for ref in fence["mirror_receipts"].values())):
            raise RuntimeBlocked("allocation_target_fence_unproven")
        return {"observed_at": observation["observed_at"], "exclusion": exclusion, "target_fence": fence}

    def open_generation_proof(self, command, opened, table):
        scope = dict(profile=self.scope, published_scope=command["published_scope"], opened=opened, table=table)
        authority = {key: command[key] for key in AUTHORITY_KEYS}
        operation_id = opened["operation_id"]
        request = dict(scope=scope, authority=authority, operation_id=operation_id)
        proof, fence = self._generation_observation("/v1/capture/open-generation-bindings", request,
                                                    "observation:open_generation_binding", command)
        return request, proof, fence

    def allocate_generation(self, command, request, proof, fence, generation_id):
        request = {**request, "scope": {**request["scope"], "generation_id": generation_id}}
        _, committed_fence = self._generation_observation("/v1/capture/generation-allocations", request,
                                                          "observation:generation_allocation", command,
                                                          binding_proof=proof)
        if committed_fence != fence:
            raise RuntimeBlocked("generation_fence_changed")

    def _generation_observation(self, path, request, purpose, command, **payload):
        result = self.http.request("POST", path, {**request, **payload})
        if not isinstance(result, dict) or self.verifier is None:
            raise RuntimeBlocked("generation_evidence_unknown")
        signature = result.get("signature")
        claims = self.verifier.verify(signature, purpose=purpose, **request)
        self._require_fresh(claims, command)
        if json.dumps({key: claims[key] for key in request}, sort_keys=True) != json.dumps(request, sort_keys=True):
            raise RuntimeBlocked("generation_evidence_mismatch")
        if claims.get("verified") is not True or not _digest_ref(claims.get("fence_receipt")):
            raise RuntimeBlocked("generation_evidence_unproven")
        return signature, claims["fence_receipt"]

    def _require_fresh(self, observation, command):
        try:
            observed = datetime.fromisoformat(observation["observed_at"])
            requested = datetime.fromisoformat(command["requested_at"])
            age = (utc_now() - observed).total_seconds()
            valid = observed.tzinfo is not None and 0 <= age <= self.max_age and observed >= requested
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            raise RuntimeBlocked("observation_stale")

    def _require_readiness(self, observation):
        checks = observation.get("checks", {})
        if not isinstance(checks, dict) or any(checks.get(key) != "pass" for key in self.required):
            raise RuntimeBlocked("readiness_unknown_or_failed")

    def observation(self, command, phase):
        result = self.http.request("POST", "/v1/capture/observations", {
            "command": command, "phase": phase,
            "executor_instance_id": self.runtime_instance_id,
        })
        if not isinstance(result, dict):
            raise RuntimeBlocked("readiness_unknown")
        if self.verifier is None:
            raise RuntimeBlocked("signing_trust_required")
        signed = self.verifier.verify(
            result.get("signature"), purpose="observation:" + phase,
            authority={key: command[key] for key in AUTHORITY_KEYS}, scope=self.scope,
            operation_id=command["operation_id"],
        )
        if signed.get("observation") != {key: value for key, value in result.items() if key != "signature"}:
            raise RuntimeBlocked("signed_observation_mismatch")
        if result.get("authority") != {key: command[key] for key in AUTHORITY_KEYS}:
            raise RuntimeBlocked("observation_authority_mismatch")
        if (command["runtime_instance_id"] != self.runtime_instance_id
                or not isinstance(command["owner_epoch"], int) or command["owner_epoch"] <= 0):
            raise RuntimeBlocked("owner_assignment_unproven")
        self._require_fresh(result, command)
        if phase not in {"before_stop", "stopped"}:
            self._require_readiness(result)
        proofs = result.get("proofs", {})
        required = (STOP_PROOFS | {"owner_assignment_ref"} if phase == "stopped"
                    else {"owner_assignment_ref", "owner_exclusion_ref", "target_fence_ref"})
        if phase == "running":
            required |= {"credential_installed_ref", "credential_revoked_ref", "task_running_ref"}
        if not isinstance(proofs, dict):
            raise RuntimeBlocked("proof_unverified")
        refs = {}
        for key in required:
            proof = proofs.get(key)
            if not isinstance(proof, dict) or proof.get("verified") is not True:
                raise RuntimeBlocked("proof_unverified")
            # Digest-addressed resolved objects and exact authority, not arbitrary
            # non-empty strings, constitute the private gateway's proof protocol.
            if (not isinstance(proof.get("ref"), str)
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", proof["ref"])
                    or proof.get("authority") != result["authority"]
                    or proof.get("operation_id") != command["operation_id"]
                    or proof.get("observed_at") != result["observed_at"]
                    or not isinstance(proof.get("facts"), dict)
                    or not proof["facts"]
                    or proof["ref"] != "sha256:" + hashlib.sha256(json.dumps(
                        {field: proof[field] for field in (
                            "authority", "operation_id", "observed_at", "facts"
                        )}, sort_keys=True, separators=(",", ":")
                    ).encode()).hexdigest()):
                raise RuntimeBlocked("proof_unverified")
            expected_fact = key.removesuffix("_ref")
            if proof["facts"].get(expected_fact) is not True:
                raise RuntimeBlocked("proof_fact_missing")
            if key not in {"owner_assignment_ref", "task_running_ref"}:
                refs[key] = proof["ref"]
        return {**result["authority"], "operation_id": command["operation_id"],
                "observed_at": result["observed_at"], **refs}
