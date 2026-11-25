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
from backend.metadata.capture.control import table_exclusion_refs
from backend.metadata.capture.profile_support import CONNECTOR_NAME
from backend.metadata.capture.runtime_store import RuntimeBlocked, protected_read
from backend.metadata.capture.scope import AUTHORITY_KEYS
from backend.metadata.errors import SourceCaptureControlConflict


MAX_TRANSPORT_TIMEOUT_SECONDS = 120
MAX_TRANSPORT_RESPONSE_BYTES = 1048576


class PrivateHTTP:
    def __init__(self, *, origin, ca_file, cert_file, key_file, timeout_seconds,
                 max_response_bytes, transport=None):
        url = urlsplit(origin)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path not in {"", "/"} or url.query or url.fragment):
            raise RuntimeBlocked("private_https_origin_required")
        if (not 0 < timeout_seconds <= MAX_TRANSPORT_TIMEOUT_SECONDS
                or not 0 < max_response_bytes <= MAX_TRANSPORT_RESPONSE_BYTES):
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
        if CONNECTOR_NAME.fullmatch(connector_name) is None:
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


MANDATORY_READINESS_CHECKS = frozenset({
    "profile_qualified", "source_pressure", "delivery_bounded",
    "credential_valid", "alarm_drill", "owner_excluded", "target_fenced",
})
MAX_READINESS_AGE_SECONDS = 3600

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

    def __init__(self, http, *, engine, runtime_instance_id, max_age_seconds, required_checks,
                 verifier=None, scope=None):
        if (not runtime_instance_id or not 0 < max_age_seconds <= MAX_READINESS_AGE_SECONDS
                or not MANDATORY_READINESS_CHECKS.issubset(set(required_checks))):
            raise RuntimeBlocked("explicit_readiness_policy_required")
        self.http = http
        self.engine = engine
        self.runtime_instance_id = runtime_instance_id
        self.max_age = max_age_seconds
        self.required = set(required_checks)
        self.verifier = verifier
        self.scope = scope

    def diagnostic_observation(self, authority, operation_id):
        """Optional independently measured telemetry; never a readiness proof."""
        from backend.metadata.mirrors.diagnostic_schemas import SourceReceipt

        request = dict(authority=authority, scope=self.scope, operation_id=operation_id)
        response = self.http.request("POST", "/v1/capture/diagnostics", request, missing=True)
        if response is None:
            return SourceReceipt()
        if not isinstance(response, dict) or self.verifier is None:
            raise RuntimeBlocked("diagnostic_observation_unverified")
        claims = self.verifier.verify(response.get("signature"), purpose="observation:diagnostics", **request)
        return SourceReceipt.model_validate(claims.get("diagnostics"))

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

    def scope_fence(self, command):
        authority = {key: command[key] for key in AUTHORITY_KEYS}
        scope = dict(profile=self.scope, published_scope=command["published_scope"])
        request = dict(authority=authority, operation_id=command["operation_id"], scope=scope)
        result = self.http.request("POST", "/v1/capture/scope-fences", request)
        if not isinstance(result, dict) or self.verifier is None:
            raise RuntimeBlocked("scope_fence_unconfirmed")
        proof = self.verifier.verify(result.get("signature"), purpose="observation:scope_fence", **request)
        self._require_fresh(proof, command)
        receipts = proof.get("mirror_receipts")
        required = {row["mirror_id"] for row in command["published_scope"] if row["qualified_table"] in self.scope["tables"]}
        if (proof.get("verified") is not True or not isinstance(receipts, dict)
                or receipts.keys() != required or not all(_digest_ref(ref) for ref in receipts.values())):
            raise RuntimeBlocked("scope_fence_unconfirmed")
        result = dict(authority=authority, operation_id=command["operation_id"], mirror_receipts=receipts)
        if boundaries := proof.get("table_boundaries"):
            included = {entry["mirror_id"]: entry["mirror_revision"] for entry in command["published_scope"]
                        if entry["included"] and entry["mirror_id"] in required}
            if not isinstance(boundaries, dict) or not boundaries.keys() <= included.keys():
                raise RuntimeBlocked("scope_fence_unconfirmed")
            for mirror_id, boundary in boundaries.items():
                if (not isinstance(boundary, dict)
                        or boundary.keys() != {"mirror_revision", "partition_identity", "start_offset", "evidence_ref"}
                        or type(boundary["mirror_revision"]) is not int or boundary["mirror_revision"] != included[mirror_id]
                        or type(boundary["start_offset"]) is not int or boundary["start_offset"] < -1
                        or not _digest_ref(boundary["evidence_ref"])):
                    raise RuntimeBlocked("scope_fence_unconfirmed")
                part = boundary["partition_identity"]
                if (not isinstance(part, dict) or part.keys() != {"runtime_cluster_id", "topic_incarnation_id", "partition"}
                        or type(part["partition"]) is not int or part["partition"] != 0 or
                        any(not isinstance(part[k], str) or not part[k] for k in ("runtime_cluster_id","topic_incarnation_id"))):
                    raise RuntimeBlocked("scope_fence_unconfirmed")
            result["table_boundaries"] = boundaries
        if "inconclusive_tables" in proof:
            inconclusive = proof["inconclusive_tables"]
            included = {entry["mirror_id"] for entry in command["published_scope"]
                        if entry["included"] and entry["mirror_id"] in required}
            if (not isinstance(inconclusive, dict) or not inconclusive.keys() <= included
                    or inconclusive.keys() & result.get("table_boundaries", {}).keys()
                    or any(not _digest_ref(ref) for ref in inconclusive.values())):
                raise RuntimeBlocked("scope_fence_unconfirmed")
            result["inconclusive_tables"] = inconclusive
            result["observed_at"] = proof["observed_at"]
        return result

    def replacement_observation(self, command, authorization):
        reservation = command["replacement"]
        scope = reservation["scope"]
        authority = {key: command[key] for key in AUTHORITY_KEYS}
        result = self.http.request("POST", "/v1/capture/replacement-owner-allocations", {
            "command": command, "authorization": authorization,
        })
        if not isinstance(result, dict) or self.verifier is None:
            raise RuntimeBlocked("replacement_evidence_unknown")
        signature = result.get("signature")
        signed = self.verifier.verify(
            signature, purpose="observation:replacement_owner", authority=authority,
            scope=scope, operation_id=command["operation_id"],
        )
        observation = signed.get("observation")
        if not isinstance(observation, dict) or json.dumps(
            [signed.get("authority"), signed.get("scope"), observation.get("command")], sort_keys=True
        ) != json.dumps([authority, scope, command], sort_keys=True):
            raise RuntimeBlocked("replacement_observation_mismatch")
        self._require_fresh(observation, command)
        self._require_readiness(observation)

        exclusion = observation.get("exclusion")
        if (not isinstance(exclusion, dict) or exclusion.get("method") not in ("terminated", "authority_revoked")
                or any(not _digest_ref(exclusion.get(key)) for key in (
                    "agent_receipt", "task_receipt", "source_session_receipt", "inflight_drained_receipt"
                ))):
            raise RuntimeBlocked("replacement_exclusion_unproven")
        baseline = observation.get("candidate_baseline")
        if (not isinstance(baseline, dict)
                or set(baseline) != self.engine.baseline_keys
                or not all(_digest_ref(ref) for ref in baseline.values())):
            raise RuntimeBlocked("replacement_baseline_unproven")
        fence = observation.get("target_fence")
        if not isinstance(fence, dict) or not _digest_ref(fence.get("inventory_receipt")):
            raise RuntimeBlocked("replacement_fence_unproven")
        for key, required_ids in (
            ("loss_receipts", {change["mirror_id"] for change in scope["history_loss"]}),
            ("mirror_receipts", set(scope["target_inventory"])),
        ):
            receipts = fence.get(key)
            if (not isinstance(receipts, dict) or receipts.keys() != required_ids
                    or not all(_digest_ref(ref) for ref in receipts.values())):
                raise RuntimeBlocked("replacement_fence_unproven")
        return dict(observed_at=observation["observed_at"], observation_digest=hashlib.sha256(signature.encode()).hexdigest(),
                    exclusion={key: exclusion[key] for key in (
                        "method", "agent_receipt", "task_receipt", "source_session_receipt", "inflight_drained_receipt"
                    )}, candidate_baseline=baseline,
                    target_fence=dict(authority=authority, operation_id=command["operation_id"], **{
                        key: fence[key] for key in ("inventory_receipt", "loss_receipts", "mirror_receipts")
                    }))

    def resume_retained(self, command, request):
        result = self.http.request("POST", "/v1/capture/retained-position-resume", request)
        if not isinstance(result, dict) or self.verifier is None:
            raise RuntimeBlocked("retained_position_resume_unconfirmed")
        proof = self.verifier.verify(result.get("signature"), purpose="retained_position_resume", **request)
        self._require_fresh(proof, command)
        if proof.get("verified") is not True:
            raise RuntimeBlocked("retained_position_resume_unconfirmed")
        decisions = proof.get("table_continuity")
        if decisions is not None:
            candidates = {candidate["mirror_id"]: candidate for candidate in request["scope"]["candidates"]}
            if not isinstance(decisions, dict) or decisions.keys() != candidates.keys():
                raise RuntimeBlocked("retained_position_resume_unconfirmed")
            for mid, value in decisions.items():
                if not isinstance(value, dict) or not _digest_ref(value.get("evidence_ref")):
                    raise RuntimeBlocked("retained_position_resume_unconfirmed")
                if value.get("result") == "gap":
                    if (set(value) != {"result", "evidence_ref", "start_offset", "partition_identity"}
                            or type(value["start_offset"]) is not int
                            or value["start_offset"] < candidates[mid]["target_seek_offset"] - 1
                            or value["partition_identity"] != candidates[mid]["binding"]["partition_identity"]):
                        raise RuntimeBlocked("retained_position_resume_unconfirmed")
                elif value.get("result") not in {"continuous", "unknown"} or set(value) != {"result", "evidence_ref"}:
                    raise RuntimeBlocked("retained_position_resume_unconfirmed")
            return {mid: {**value, "observed_at": proof["observed_at"]} for mid, value in decisions.items()}
        return None

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
        if phase == "running" and "table_exclusions" in result:
            try:
                table_exclusion_refs(command["published_scope"], result["table_exclusions"])
            except SourceCaptureControlConflict:
                raise RuntimeBlocked("table_exclusion_unconfirmed") from None
            refs["table_exclusions"] = result["table_exclusions"]
        return {**result["authority"], "operation_id": command["operation_id"],
                "observed_at": result["observed_at"], **refs}
