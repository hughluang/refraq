"""Independent capture intent consumer with signed, scoped safety admission."""

import argparse
import os
import signal
from threading import Event
import time

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from sqlalchemy.engine import make_url

from backend.metadata.capture.authority import SignedAuthority
from backend.metadata.capture.delivery_composition import SourceDelivery
from backend.metadata.capture.credentials import CredentialFiles
from backend.metadata.capture.postgresql import PostgreSQLCaptureProfile

from backend.core.config import get_settings
from backend.metadata.capture.control import (
    allocate_owner, profile_matches_scope, reconcile_published_scope, record_applied_evidence,
    source_control_transaction,
)
from backend.metadata.capture.runtime_adapters import ConnectLifecycle, PrivateHTTP, ReadinessSignals
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked, protected_json, protected_read
from backend.metadata.capture.store import list_operations, load_binding
from backend.metadata.errors import SourceCaptureControlConflict
from backend.metadata.mirrors.service import read_published_scope


class CaptureRuntime:
    def __init__(self, *, journal, connect, signals, profile=None, credentials=None, delivery=None):
        self.journal = journal
        self.connect = connect
        self.signals = signals
        self.profile = profile
        self.credentials = credentials
        self.delivery = delivery

    def poll_once(self, source_id, *, owner_allocation_file=None):
        try:
            if owner_allocation_file is not None:
                try:
                    self.reconcile_owner(source_id, owner_allocation_file)
                except (RuntimeBlocked, SourceCaptureControlConflict):
                    self.poll_source(source_id, containment_only=True)
                    raise RuntimeBlocked("owner_allocation_blocked") from None
            result = self.poll_source(source_id)
        except Exception:
            if self.delivery is not None:
                self.delivery.retire()
            raise
        if self.delivery is not None:
            self.delivery.poll_once()
        return result

    def reconcile_owner(self, source_id, request_file):
        try:
            request = protected_json(request_file)
            operation_id = request["operation_id"]
            signature = request["signature"]
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeBlocked("owner_allocation_file_invalid") from None
        reconcile_published_scope(source_id)
        return allocate_owner(source_id=source_id, operation_id=operation_id,
                              signed_proof=signature, signals=self.signals)

    def reconcile(self, command, source, phase):
        if self.profile is None or self.credentials is None or self.delivery is None:
            raise RuntimeBlocked("reconcile_adapter_not_installed")
        if (source.status != "active" or not source.capture_credential_ciphertext
                or source.capture_revision != command["credential_revision"]):
            raise RuntimeBlocked("current_source_not_authorized")
        if not profile_matches_scope(self.profile.scope, command["published_scope"]):
            raise RuntimeBlocked("connector_published_scope_mismatch")
        self.signals.observation(command, "before_start")
        self.delivery.validate_installation(command)
        refs = self.credentials.install(command, source)
        config = self.profile.configuration(command, source, refs)
        if not self.connect.configured(config):
            if phase != "pending":
                raise RuntimeBlocked("configuration_outcome_uncertain")
            self.signals.observation(command, "before_configure")
            self.journal.mark(command, "uncertain")
            self.connect.configure(config)
            if not self.connect.configured(config):
                raise RuntimeBlocked("configuration_outcome_uncertain")
        if not self.connect.running():
            if phase in {"resume_uncertain", "observed", "applied"}:
                raise RuntimeBlocked("resume_outcome_uncertain")
            self.signals.observation(command, "before_resume")
            self.journal.mark(command, "resume_uncertain")
            self.connect.resume()
            if not self.connect.running():
                raise RuntimeBlocked("resume_outcome_uncertain")
        return self.signals.observation(command, "running")

    def poll_source(self, source_id, *, containment_only=False):
        with self.journal.source_lock(source_id):
            reconcile_published_scope(source_id)
            # Retain the same management Source lock through external dispatch.
            # PATCH cannot retire authority between validation and stop submission.
            with source_control_transaction(source_id) as (session, source):
                state = load_binding(session, source_id)
                if state is None:
                    return "idle"
                pending = [op for op in list_operations(session, source_id)
                           if op["evidence"] is None and all(
                               op["command"].get(key) == state.get(key)
                               for key in ("binding_id", "owner_epoch", "runtime_instance_id",
                                           "capture_generation", "control_revision", "credential_revision")
                           )]
                if not pending:
                    return "idle"
                if len(pending) != 1:
                    raise RuntimeBlocked("ambiguous_current_intent")
                command = pending[0]["command"]
                if containment_only and command["kind"] != "stop":
                    return "idle"
                if (command["owner_epoch"] <= 0
                        or command["runtime_instance_id"] != self.signals.runtime_instance_id):
                    raise RuntimeBlocked("owner_assignment_unproven")
                if source.status == "active" and source.capture_credential_ciphertext:
                    scope = read_published_scope(session, source_id)
                    if command.get("published_scope", []) != scope or state.get("published_scope", []) != scope:
                        raise RuntimeBlocked("published_scope_changed")
                phase = self.journal.accept(command)
                if command["kind"] == "reconcile":
                    evidence = self.reconcile(command, source, phase)
                elif command["kind"] == "stop":
                    self.signals.observation(command, "before_stop")
                    if not self.connect.stopped():
                        if phase in {"uncertain", "observed", "applied"}:
                            raise RuntimeBlocked("stop_outcome_uncertain")
                        self.journal.mark(command, "uncertain")
                        self.connect.stop()
                        if not self.connect.stopped():
                            return "pending"
                    if self.credentials is not None:
                        self.credentials.revoke(command)
                    evidence = self.signals.observation(command, "stopped")
                else:
                    raise RuntimeBlocked("unsupported_command")
                self.journal.mark(command, "observed")
            # Acceptance reacquires and compares all current stamps. A concurrent
            # PATCH after dispatch cannot accidentally receive this stop ack.
            try:
                record_applied_evidence(
                    source_id=source_id, operation_id=command["operation_id"], evidence=evidence,
                )
            except SourceCaptureControlConflict:
                raise RuntimeBlocked("capture_evidence_rejected") from None
            self.journal.mark(command, "applied")
            return "applied"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    clients = []
    runtimes = []
    stopping = Event()
    previous_handlers = {}

    def stop(signum, frame):
        stopping.set()
        for _, runtime, _ in runtimes:
            if runtime.delivery is not None:
                runtime.delivery.stop()

    journal = None
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, stop)
        config = protected_json(args.config_file)
        # This is a dedicated process configuration, not a new site-wide setting.
        database_url = protected_read(config["management_database_url_file"]).decode().strip()
        url = make_url(database_url)
        if (url.get_backend_name() != "postgresql"
                or url.query.get("sslmode") != "verify-full"):
            raise RuntimeBlocked("management_database_verified_tls_required")
        os.environ["DATABASE_URL"] = database_url
        os.environ["REFRAQ_STORE_BACKEND"] = "persistent"
        get_settings.cache_clear()
        interval = config["poll_interval_seconds"]
        sources = config["sources"]
        if not 0 < interval <= 3600 or not 0 < len(sources) <= 100:
            raise RuntimeBlocked("explicit_poll_bounds_required")
        if len({entry["source_id"] for entry in sources}) != len(sources):
            raise RuntimeBlocked("duplicate_source_assignment")
        journal = CommandJournal(config["state_directory"])
        runtimes = []
        for entry in sources:
            connect_http = PrivateHTTP(**entry["connect_tls"])
            clients.append(connect_http)
            signal_http = PrivateHTTP(**entry["signals_tls"])
            clients.append(signal_http)
            trust = entry["signing_trust"]
            verifier = SignedAuthority(
                keys={kid: load_pem_public_key(protected_read(path))
                      for kid, path in trust["public_key_files"].items()},
                issuer=trust["issuer"], audience=trust["audience"],
            )
            profile = PostgreSQLCaptureProfile(**entry["postgresql_profile"])
            if (profile.scope["source_id"] != entry["source_id"]
                    or profile.scope["connector_name"] != entry["connector_name"]):
                raise RuntimeBlocked("configured_scope_mismatch")
            runtime = CaptureRuntime(
                journal=journal,
                connect=ConnectLifecycle(connect_http, entry["connector_name"]),
                signals=ReadinessSignals(signal_http, verifier=verifier, scope=profile.scope,
                                         **entry["readiness_policy"]),
                profile=profile, credentials=CredentialFiles(**entry["credential_files"]),
            )
            runtime.delivery = SourceDelivery(
                settings_file=entry.get("delivery_settings_file"), source_id=entry["source_id"],
                journal=journal, signals=runtime.signals, verifier=verifier, profile=profile,
            )
            runtimes.append((entry["source_id"], runtime, entry.get("owner_allocation_file")))
        while not stopping.is_set():
            blocked = False
            for source_id, runtime, request_file in runtimes:
                try:
                    runtime.poll_once(source_id, owner_allocation_file=request_file)
                except RuntimeBlocked:
                    blocked = True
            if args.once:
                return 2 if blocked else 0
            stopping.wait(interval)
        return 0
    except Exception:
        # Neither argv nor stderr contains private config/driver/HTTP exceptions.
        print("capture_runtime_blocked")
        return 2
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        for _, runtime, _ in runtimes:
            if runtime.delivery is not None:
                runtime.delivery.close()
        for client in clients:
            client.close()
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
