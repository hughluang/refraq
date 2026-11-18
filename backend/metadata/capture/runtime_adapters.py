"""Bounded private TLS adapters; Connect is lifecycle-only."""

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

    def request(self, method, path, payload=None):
        try:
            with self.client.stream(method, path, json=payload) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.limit:
                        raise RuntimeBlocked("response_bound_exceeded")
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
        self.path = "/connectors/" + connector_name

    def stop(self):
        # Stop preserves offsets and the connector. It is never delete/pause.
        self.http.request("PUT", self.path + "/stop")

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


STOP_PROOFS = {
    "target_fence_ref", "owner_exclusion_ref", "retired_commands_rejected_ref",
    "task_stopped_ref", "source_session_stopped_ref", "inflight_drained_ref",
}


class ReadinessSignals:
    """Read independently substantiated attestations from a deployment-owned gateway.

    The gateway must resolve proof objects, not echo caller-provided references.
    Snapshot terminal signals can be observed here but are not start authority.
    """

    def __init__(self, http, *, runtime_instance_id, max_age_seconds, required_checks):
        mandatory = {"profile_qualified", "source_pressure", "delivery_bounded",
                     "credential_valid", "alarm_drill", "owner_excluded", "target_fenced"}
        if (not runtime_instance_id or not 0 < max_age_seconds <= 3600
                or not mandatory.issubset(set(required_checks))):
            raise RuntimeBlocked("explicit_readiness_policy_required")
        self.http = http
        self.runtime_instance_id = runtime_instance_id
        self.max_age = max_age_seconds
        self.required = set(required_checks)

    def observation(self, command, phase):
        result = self.http.request("POST", "/v1/capture/observations", {
            "command": command, "phase": phase,
            "executor_instance_id": self.runtime_instance_id,
        })
        if not isinstance(result, dict):
            raise RuntimeBlocked("readiness_unknown")
        if result.get("authority") != {key: command[key] for key in AUTHORITY_KEYS}:
            raise RuntimeBlocked("observation_authority_mismatch")
        if (command["runtime_instance_id"] != self.runtime_instance_id
                or not isinstance(command["owner_epoch"], int) or command["owner_epoch"] <= 0):
            raise RuntimeBlocked("owner_assignment_unproven")
        try:
            observed = datetime.fromisoformat(result["observed_at"])
            requested = datetime.fromisoformat(command["requested_at"])
            age = (utc_now() - observed).total_seconds()
            valid = observed.tzinfo is not None and 0 <= age <= self.max_age and observed >= requested
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            raise RuntimeBlocked("observation_stale")
        checks = result.get("checks", {})
        if not isinstance(checks, dict) or any(checks.get(key) != "pass" for key in self.required):
            raise RuntimeBlocked("readiness_unknown_or_failed")
        proofs = result.get("proofs", {})
        required = (STOP_PROOFS | {"owner_assignment_ref"} if phase == "stopped"
                    else {"owner_assignment_ref", "owner_exclusion_ref", "target_fence_ref"})
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
            if key != "owner_assignment_ref":
                refs[key] = proof["ref"]
        return {**result["authority"], "operation_id": command["operation_id"],
                "observed_at": result["observed_at"], **refs}
