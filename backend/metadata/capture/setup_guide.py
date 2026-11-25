"""Redacted deployment projection for the Console. No secrets and no Source state."""

import inspect

from backend.core.config import MIRROR_TARGET_DRIVER, MIRROR_TARGET_ROLES, MIRROR_TARGET_SSLMODE, MirrorTargetSettings
from backend.metadata.capture.credentials import CredentialFiles
from backend.metadata.capture.delivery_composition import DELIVERY_SETTINGS_KEYS
from backend.metadata.capture.engines import CONNECTOR_VERSION, _REGISTRY
from backend.metadata.capture.profile_support import BOOTSTRAP_SERVERS, CONNECTOR_NAME, TOPIC_PREFIX
from backend.metadata.capture.runtime import (
    MAX_ASSIGNED_SOURCES, MAX_POLL_INTERVAL_SECONDS, SNAPSHOT_OBSERVER_KEYS,
)
from backend.metadata.capture.runtime_adapters import (
    MANDATORY_READINESS_CHECKS, MAX_READINESS_AGE_SECONDS, MAX_TRANSPORT_RESPONSE_BYTES,
    MAX_TRANSPORT_TIMEOUT_SECONDS, PrivateHTTP, ReadinessSignals,
)
from backend.metadata.capture.runtime_store import PROTECTED_FORBIDDEN_BITS, REPORTED_FAULTS
from backend.metadata.mirrors.bootstrap import ROLES, TYPES, VERSION

# Expanded from the runtime's ``/v1/capture/snapshots/{step}`` calls.
GATEWAY_PATHS = (
    "/v1/capture/delivery-leases",
    "/v1/capture/delivery-leases/release",
    "/v1/capture/diagnostics",
    "/v1/capture/generation-allocations",
    "/v1/capture/observations",
    "/v1/capture/open-generation-bindings",
    "/v1/capture/owner-allocations",
    "/v1/capture/recovery-loss-observations",
    "/v1/capture/replacement-owner-allocations",
    "/v1/capture/retained-position-resume",
    "/v1/capture/scope-fences",
    "/v1/capture/snapshots/baseline",
    "/v1/capture/snapshots/notifications",
    "/v1/capture/snapshots/receipt",
    "/v1/capture/snapshots/submit",
)
OPTIONAL_GATEWAY_PATHS = ("/v1/capture/diagnostics",)
CONNECT_PATHS = (
    "/connectors/{name}/config",
    "/connectors/{name}/resume",
    "/connectors/{name}/status",
    "/connectors/{name}/stop",
)
SIGNING_TRUST_KEYS = ("public_key_files", "issuer", "audience")
STEPS = ("source", "transport", "target", "gateway", "config", "runtime", "verify")
COMPOSE_SERVICE = "api"
ADMIN_URL_ENV = "MIRROR_ADMIN_URL"
TARGET_SCHEMAS = ("source_mirror", "source_mirror_state")

_SITE_INPUTS = (
    {"token": "GATEWAY_ORIGIN", "kind": "https_origin"},
    {"token": "CONNECT_ORIGIN", "kind": "https_origin"},
    {"token": "RECEIPT_OBSERVER_ORIGIN", "kind": "https_origin"},
    {"token": "NOTIFICATION_OBSERVER_ORIGIN", "kind": "https_origin"},
    {"token": "KAFKA_BOOTSTRAP_SERVERS", "kind": "bootstrap_servers"},
    {"token": "RUNTIME_INSTANCE_ID", "kind": "identifier"},
    {"token": "CONNECTOR_NAME", "kind": "connector_name"},
    {"token": "TOPIC_PREFIX", "kind": "topic_prefix"},
    {"token": "CONFIG_DIRECTORY", "kind": "directory"},
)


def _required_names(func, exclude=()):
    """Required parameters of a constructor, in definition order."""
    skip = {"self", *exclude}
    return [name for name, param in inspect.signature(func).parameters.items()
            if name not in skip and param.default is inspect.Parameter.empty]


def _private_tls(origin_token):
    values = {
        "origin": f"<{origin_token}>",
        "ca_file": "<CONFIG_DIRECTORY>/ca.pem",
        "cert_file": "<CONFIG_DIRECTORY>/client.pem",
        "key_file": "<CONFIG_DIRECTORY>/client.key",
        "timeout_seconds": "<TIMEOUT_SECONDS>",
        "max_response_bytes": "<MAX_RESPONSE_BYTES>",
    }
    names = _required_names(PrivateHTTP.__init__)
    if set(values) != set(names):
        raise RuntimeError("private TLS skeleton does not match PrivateHTTP")
    return {name: values[name] for name in names}


def _readiness_policy():
    values = {
        "runtime_instance_id": "<RUNTIME_INSTANCE_ID>",
        "max_age_seconds": "<MAX_AGE_SECONDS>",
        "required_checks": sorted(MANDATORY_READINESS_CHECKS),
    }
    names = _required_names(ReadinessSignals.__init__, {"http", "engine", "verifier", "scope"})
    if set(values) != set(names):
        raise RuntimeError("readiness skeleton does not match ReadinessSignals")
    return {name: values[name] for name in names}


def _credential_files():
    values = {
        "directory": "<CONFIG_DIRECTORY>/credentials",
        "provider_directory": "<PROVIDER_DIRECTORY>",
    }
    names = _required_names(CredentialFiles.__init__)
    if set(values) != set(names):
        raise RuntimeError("credential skeleton does not match CredentialFiles")
    return {name: values[name] for name in names}


def _source_entry(engine):
    template = engine.profile.template()
    return {
        "source_id": "<SOURCE_ID>",
        "connector_name": "<CONNECTOR_NAME>",
        "connect_tls": _private_tls("CONNECT_ORIGIN"),
        "signals_tls": _private_tls("GATEWAY_ORIGIN"),
        "signing_trust": {
            "public_key_files": {"<SIGNING_KEY_ID>": "<CONFIG_DIRECTORY>/gateway.pub"},
            "issuer": "<SIGNING_ISSUER>",
            "audience": "<SIGNING_AUDIENCE>",
        },
        "readiness_policy": _readiness_policy(),
        "credential_files": _credential_files(),
        engine.profile_key: {"scope": template["scope"], "tls": template["tls"]},
    }


def setup_guide():
    """Contract literals and placeholders. The caller fills nothing from a Source."""
    readiness = _readiness_policy()
    credentials = _credential_files()
    tls_keys = list(_private_tls("CONNECT_ORIGIN"))
    return {
        "connector_version": CONNECTOR_VERSION,
        "compose_service": COMPOSE_SERVICE,
        "site_inputs": [dict(item) for item in _SITE_INPUTS],
        "steps": list(STEPS),
        "bounds": {
            "poll_interval_seconds_max": MAX_POLL_INTERVAL_SECONDS,
            "sources_max": MAX_ASSIGNED_SOURCES,
            "timeout_seconds_max": MAX_TRANSPORT_TIMEOUT_SECONDS,
            "max_response_bytes_max": MAX_TRANSPORT_RESPONSE_BYTES,
            "readiness_max_age_seconds": MAX_READINESS_AGE_SECONDS,
        },
        "patterns": {
            "connector_name": CONNECTOR_NAME.pattern,
            "topic_prefix": TOPIC_PREFIX.pattern,
            "bootstrap_servers": BOOTSTRAP_SERVERS.pattern,
        },
        "protected_forbidden_bits": PROTECTED_FORBIDDEN_BITS,
        "target": {
            "schema_version": VERSION,
            "schemas": list(TARGET_SCHEMAS),
            "roles": list(ROLES),
            "login_roles": list(MIRROR_TARGET_ROLES),
            "setting": "REFRAQ_MIRROR_TARGET",
            "setting_fields": list(MirrorTargetSettings.model_fields),
            "driver": MIRROR_TARGET_DRIVER,
            "sslmode": MIRROR_TARGET_SSLMODE,
            "url_template": (
                f"{MIRROR_TARGET_DRIVER}://<ROLE>:<PASSWORD>@<HOST>/<DATABASE>"
                f"?sslmode={MIRROR_TARGET_SSLMODE}&sslrootcert=<CA_FILE>"
            ),
            "bootstrap_env": ADMIN_URL_ENV,
        },
        "commands": {
            "bootstrap": {
                "argv": ["python", "-m", "backend.metadata.mirrors.bootstrap", "--admin-url-env", ADMIN_URL_ENV],
                "env": [ADMIN_URL_ENV],
                "mount": None,
                "host": False,
            },
            "directories": {
                "argv": ["install", "-d", "-m", "700", "<CONFIG_DIRECTORY>",
                         "<CONFIG_DIRECTORY>/state", "<CONFIG_DIRECTORY>/credentials"],
                "env": [],
                "mount": None,
                "host": True,
            },
            "check": {
                "argv": ["python", "-m", "backend.metadata.capture.runtime", "--config-file",
                         "<CONFIG_DIRECTORY>/runtime.json", "--once"],
                "env": [],
                "mount": "<CONFIG_DIRECTORY>",
                "host": False,
            },
            "start": {
                "argv": ["python", "-m", "backend.metadata.capture.runtime", "--config-file",
                         "<CONFIG_DIRECTORY>/runtime.json"],
                "env": [],
                "mount": "<CONFIG_DIRECTORY>",
                "host": False,
            },
        },
        "runtime_config": {
            "management_database_url_file": "<CONFIG_DIRECTORY>/management_database_url",
            "state_directory": "<CONFIG_DIRECTORY>/state",
            "poll_interval_seconds": "<POLL_INTERVAL_SECONDS>",
            "sources": ["<SOURCE_ENTRY>"],
        },
        "runtime": {
            "config_keys": ["management_database_url_file", "state_directory", "poll_interval_seconds", "sources"],
            "check_flag": "--once",
            "recovery_flag": "--dispatch-recovery",
            "exit_codes": {"ready": 0, "blocked": 2},
            "fatal_message": "capture_runtime_blocked",
            "fault_codes": sorted(REPORTED_FAULTS),
            "readiness_policy_keys": list(readiness),
            "credential_file_keys": list(credentials),
            "delivery_settings_keys": sorted(DELIVERY_SETTINGS_KEYS),
            "native_types": sorted(TYPES),
        },
        "gateway": {
            "paths": list(GATEWAY_PATHS),
            "optional_paths": list(OPTIONAL_GATEWAY_PATHS),
            "connect_paths": list(CONNECT_PATHS),
            "required_checks": sorted(MANDATORY_READINESS_CHECKS),
            "signing_trust_keys": list(SIGNING_TRUST_KEYS),
            "snapshot_observer_keys": sorted(SNAPSHOT_OBSERVER_KEYS),
        },
        "transport": {"tls_keys": tls_keys, "data_partition": 0},
        "deployment_owned": ["delivery_settings_file", "owner_allocation_file", "snapshot_observers"],
        "engines": [{
            "code": engine.code,
            "profile_key": engine.profile_key,
            "prerequisites": list(engine.profile.prerequisites),
            "snapshot_prerequisite": engine.profile.snapshot_prerequisite,
            "source_entry": _source_entry(engine),
        } for engine in _REGISTRY.values()],
    }
