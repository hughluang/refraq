"""Independent capture intent consumer with signed, scoped safety admission."""

import argparse
import json
import os
import signal
from threading import Event

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from backend.metadata.capture.authority import SignedAuthority
from backend.metadata.capture.delivery_composition import SourceDelivery
from backend.metadata.capture.credentials import CredentialFiles

from backend.core.config import get_settings
from backend.core.db import get_session_factory
from backend.core.errors import PlatformCapacityExceeded, PlatformTimeout
from backend.metadata.capture.control import (
    AUTHORITY_KEYS, allocate_owner, profile_matches_scope, reconcile_published_scope, record_applied_evidence,
    replace_owner, replacement_blocks_lifecycle, source_control_transaction,
)
from backend.metadata.capture.runtime_adapters import ConnectLifecycle, PrivateHTTP, ReadinessSignals, SnapshotGateway
from backend.metadata.capture.recovery_dispatch import dispatch_recovery
from backend.metadata.capture.postgresql import PostgreSQLCaptureProfile, TablePrerequisiteFailed
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked, protected_json, protected_read
from backend.metadata.capture.snapshot import SnapshotCoordinator
from backend.metadata.capture.store import list_operations, load_binding, save_binding
from backend.metadata.errors import SourceCaptureControlConflict
from backend.metadata.mirrors.service import (
    MirrorError, ObserveCommittedOpenPublication, OpenPublicationIdentity, read_dispatch_scope,
    reconcile_open_publication, lifecycle_checks, table_prerequisite_check, record_continuity_receipt,
)
from backend.metadata.mirrors.types import Authority
from backend.metadata.mirrors.recovery_store import RecoveryRow


class CaptureRuntime:
    def __init__(self, *, journal, connect, signals, profile=None, credentials=None, delivery=None,
                 prepare_delivery=None, resume_retained=None, snapshot=None, publish_completed=None,
                 observe_committed_publication: ObserveCommittedOpenPublication | None = None):
        self.journal = journal
        self.connect = connect
        self.signals = signals
        self.profile = profile
        self.credentials = credentials
        self.delivery = delivery
        self.prepare_delivery = prepare_delivery
        self.resume_retained = resume_retained
        self.snapshot = snapshot
        self.publish_completed = publish_completed
        self.publication_changed = False
        self.observe_committed_publication = observe_committed_publication

    def reconcile_open_publication(self, *, mirror_id, operation_id, expected: OpenPublicationIdentity):
        """Explicitly reconcile publication under a qualified driver and Source exclusion.

        Ordinary polling needs to rehydrate applied delivery from durable evidence and
        safely resume from the sealed source and target positions before using this transition.
        """
        if not callable(self.observe_committed_publication):
            raise RuntimeBlocked("publication_observer_not_installed")
        if (not isinstance(expected, OpenPublicationIdentity) or not isinstance(expected.authority, Authority)
                or not isinstance(expected.authority.source_id, str) or not expected.authority.source_id):
            raise RuntimeBlocked("publication_observation_rejected")
        with self.journal.source_lock(expected.authority.source_id):
            try:
                return reconcile_open_publication(mirror_id=mirror_id, operation_id=operation_id, expected=expected,
                                                  observe_committed=self.observe_committed_publication)
            except (DBAPIError, MirrorError, PlatformCapacityExceeded, PlatformTimeout, RuntimeBlocked):
                raise RuntimeBlocked("publication_observation_rejected") from None

    def poll_once(self, source_id, *, owner_allocation_file=None, replacement_owner_file=None):
        try:
            if replacement_owner_file is not None:
                if owner_allocation_file is not None:
                    self.poll_source(source_id, containment_only=True)
                    raise RuntimeBlocked("conflicting_owner_request_files")
                try:
                    self.reconcile_replacement_owner(source_id, replacement_owner_file)
                except (RuntimeBlocked, SourceCaptureControlConflict):
                    self.poll_source(source_id, containment_only=True)
                    raise RuntimeBlocked("replacement_owner_blocked") from None
                if self.prepare_delivery is None or self.snapshot is None:
                    self.poll_source(source_id, containment_only=True)
                    return "applied"
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
        if self.delivery is not None and not self.publication_changed:
            self.delivery.poll_once()
        self.publication_changed = False
        return result

    def reconcile_owner(self, source_id, request_file):
        try:
            request = protected_json(request_file)
        except (OSError, RecursionError, TypeError, ValueError):
            raise RuntimeBlocked("owner_allocation_file_invalid") from None
        if not isinstance(request, dict) or request.keys() != {"operation_id", "signature"}:
            raise RuntimeBlocked("owner_allocation_file_invalid")
        signature = request["signature"]
        if not isinstance(signature, str) or not signature.isascii():
            raise RuntimeBlocked("owner_allocation_file_invalid")
        reconcile_published_scope(source_id)
        return allocate_owner(source_id=source_id, operation_id=request["operation_id"],
                              signed_proof=signature, signals=self.signals)

    def reconcile_replacement_owner(self, source_id, request_file):
        try:
            request = protected_json(request_file)
        except (OSError, RecursionError, TypeError, ValueError):
            raise RuntimeBlocked("replacement_owner_file_invalid") from None
        if not isinstance(request, dict) or request.keys() != {"recovery_operation_id", "signature"}:
            raise RuntimeBlocked("replacement_owner_file_invalid")
        with self.journal.source_lock(source_id):
            return replace_owner(source_id=source_id, operation_id=request["recovery_operation_id"],
                                 signed_proof=request["signature"], signals=self.signals,
                                 before_observation=self.delivery.retire if self.delivery is not None else None)

    def reconcile(self, command, source, phase, *, session):
        if self.profile is None or self.credentials is None or self.delivery is None:
            raise RuntimeBlocked("reconcile_adapter_not_installed")
        if (source.status != "active" or not source.capture_credential_ciphertext
                or source.capture_revision != command["credential_revision"]):
            raise RuntimeBlocked("current_source_not_authorized")
        if not profile_matches_scope(self.profile.scope, command["published_scope"]):
            raise RuntimeBlocked("connector_published_scope_mismatch")
        self.signals.observation(command, "before_start")
        self.delivery.validate_installation(command, session=session)
        refs = self.credentials.install(command, source)
        config = self.profile.configuration(command, source, refs)
        if not self.connect.configured(config):
            if phase != "pending":
                raise RuntimeBlocked("configuration_outcome_uncertain")
            self.signals.observation(command, "before_configure")
            self.delivery.validate_installation(command, session=session)
            self.journal.mark(command, "uncertain")
            self.connect.configure(config)
            if not self.connect.configured(config):
                raise RuntimeBlocked("configuration_outcome_uncertain")
        if not self.connect.running():
            if phase in {"resume_uncertain", "observed", "applied"}:
                raise RuntimeBlocked("resume_outcome_uncertain")
            self.signals.observation(command, "before_resume")
            self.delivery.validate_installation(command, session=session)
            self.journal.mark(command, "resume_uncertain")
            self.connect.resume()
            if not self.connect.running():
                raise RuntimeBlocked("resume_outcome_uncertain")
        return self.signals.observation(command, "running")

    def _current_command(self, session, source, *, include_applied=False, containment_only=False,
                         allow_replacement=False):
        state = load_binding(session, source.id)
        if state is None:
            return None
        current = [op["command"] for op in list_operations(session, source.id)
                   if (include_applied or op["evidence"] is None) and all(
                       op["command"].get(key) == state.get(key) for key in AUTHORITY_KEYS
                   )]
        if len(current) > 1:
            raise RuntimeBlocked("ambiguous_current_intent")
        command = current[0] if current else None
        replacement_build = (allow_replacement and command is not None and command["kind"] == "replace_owner"
                             and not state.get("pending_replacement") and state["desired"] == "configured"
                             and state.get("applied_revision") == command["control_revision"])
        if (not replacement_build and replacement_blocks_lifecycle(session, state)
                and (command is None or command["kind"] != "stop")):
            if containment_only:
                return None
            raise RuntimeBlocked("replacement_owner_requires_recovery")
        if command is None:
            return None
        if (command["owner_epoch"] <= 0 or command["runtime_instance_id"] != self.signals.runtime_instance_id):
            raise RuntimeBlocked("owner_assignment_unproven")
        if source.status == "active" and source.capture_credential_ciphertext:
            scope = read_dispatch_scope(session, source.id, state=state)
            if command.get("published_scope", []) != scope or state.get("published_scope", []) != scope:
                raise RuntimeBlocked("published_scope_changed")
        return command

    def poll_source(self, source_id, *, containment_only=False):
        result, prepared = self._poll_lifecycle(source_id, containment_only=containment_only)
        if result == "idle" and prepared is not None and prepared["kind"] == "reconcile":
            self._refresh_table_stops(prepared)
        if self.snapshot is not None and prepared is not None:
            bindings = self.delivery.snapshot_bindings(prepared)
            if not bindings:
                with source_control_transaction(source_id) as (session, _):
                    state = load_binding(session, source_id)
                    active = (state or {}).get("incremental_snapshots", {}).get("active")
                if active:
                    self.snapshot.poll_abandoned_slot(source_id)
            for binding in bindings:
                try:
                    snapshot = self.snapshot.reconcile(binding)
                    state = snapshot.state
                    if state == "catching_up" and self.publish_completed is not None:
                        if self.publish_completed(binding=binding, command=prepared, delivery=self.delivery, result=snapshot):
                            self.publication_changed = True
                except DBAPIError:
                    raise RuntimeBlocked("capture_snapshot_management_unconfirmed") from None
                if state == "blocked":
                    raise RuntimeBlocked("incremental_snapshot_blocked")
                if state in {"submission_uncertain", "snapshotting"}:
                    break
        return result

    def _refresh_table_stops(self, command):
        excluded = {entry["mirror_id"] for entry in command["published_scope"] if not entry["included"]}
        if not excluded:
            return
        source_id = command["source_id"]
        with source_control_transaction(source_id) as (session, source):
            state = load_binding(session, source_id)
            if (self._current_command(session, source, include_applied=True) != command or
                    excluded.issubset(state.get("table_stops", {}).get("confirmed", []))):
                return
        # A late table observation is independent of the already proven running command.
        try:
            evidence = self.signals.observation(command, "running")
            if evidence.get("table_exclusions"):
                record_applied_evidence(source_id=source_id, operation_id=command["operation_id"],
                                        evidence=evidence, refresh_table_exclusions=True)
        except (RuntimeBlocked, SourceCaptureControlConflict):
            return

    def recheck_snapshot(self, binding, *, session, source):
        checked = self.delivery.recheck_snapshot_allocation(binding, session=session)
        if isinstance(checked, dict) and checked.get("kind") == "reconcile":
            command, mode = checked, "window"
        elif isinstance(checked, tuple) and len(checked) == 2 and isinstance(checked[0], dict):
            command, mode = checked
        else:
            raise RuntimeBlocked("snapshot_dispatch_not_authorized")
        if mode not in ("run_now", "window") or (mode == "run_now" and command.get("kind") != "replace_owner"):
            raise RuntimeBlocked("snapshot_dispatch_not_authorized")
        if self._current_command(session, source, include_applied=True, allow_replacement=True) != command:
            raise RuntimeBlocked("snapshot_preparation_superseded")
        self._require_snapshot_connector(command, source)
        return mode

    def _require_snapshot_connector(self, command, source):
        if self.profile is None or self.credentials is None:
            raise RuntimeBlocked("snapshot_connector_not_current")
        refs = self.credentials.install(command, source)
        config = self.profile.configuration(command, source, refs)
        if not self.connect.configured(config) or not self.connect.running():
            raise RuntimeBlocked("snapshot_connector_not_current")

    def _poll_lifecycle(self, source_id, *, containment_only):
        with self.journal.source_lock(source_id):
            reconcile_published_scope(source_id)
            prepared = None
            retained = ()
            preparation_error = None
            if self.prepare_delivery is not None and not containment_only:
                try:
                    with source_control_transaction(source_id) as (session, source):
                        candidate = self._current_command(session, source, include_applied=True,
                                                          allow_replacement=self.snapshot is not None)
                    if candidate and candidate["kind"] in {"reconcile", "replace_owner"}:
                        if getattr(self.profile, "snapshot", None) is not None and candidate["kind"] == "reconcile":
                            self._check_table_access(candidate, source)
                        if self.profile is not None and candidate["kind"] == "reconcile":
                            self._ensure_scope_fence(candidate)
                        retained = self.prepare_delivery(candidate)
                        if retained:
                            if self.resume_retained is None:
                                raise RuntimeBlocked("retained_position_resume_driver_required")
                            with source_control_transaction(source_id) as (session, source):
                                if self._current_command(session, source, include_applied=True) != candidate:
                                    raise RuntimeBlocked("capture_preparation_superseded")
                                already_applied = self._current_command(session, source) is None
                            if already_applied:
                                self.resume_retained(candidate, retained)
                        prepared = candidate
                except RuntimeBlocked as exc:
                    preparation_error = exc
                except DBAPIError:
                    preparation_error = RuntimeBlocked("capture_preparation_management_unconfirmed")
            # Retain the same management Source lock through external dispatch.
            # PATCH cannot retire authority between validation and stop submission.
            with source_control_transaction(source_id) as (session, source):
                if (prepared is not None and prepared["kind"] == "replace_owner"
                        and source.status == "active" and source.capture_credential_ciphertext):
                    if self._current_command(session, source, include_applied=True, allow_replacement=True) != prepared:
                        raise RuntimeBlocked("capture_preparation_superseded")
                    self._require_snapshot_connector(prepared, source)
                    return "idle", prepared
                command = self._current_command(session, source, containment_only=containment_only)
                if command is None:
                    if preparation_error is not None:
                        raise preparation_error
                    return "idle", prepared
                if containment_only and command["kind"] != "stop":
                    return "idle", None
                if command["kind"] == "reconcile" and self.prepare_delivery is not None and prepared != command:
                    if preparation_error is not None:
                        raise preparation_error
                    raise RuntimeBlocked("capture_preparation_superseded")
                phase = self.journal.accept(command)
                if command["kind"] == "reconcile":
                    evidence = self.reconcile(command, source, phase, session=session)
                elif command["kind"] == "stop":
                    self.signals.observation(command, "before_stop")
                    if not self.connect.stopped():
                        if phase in {"uncertain", "observed", "applied"}:
                            raise RuntimeBlocked("stop_outcome_uncertain")
                        self.journal.mark(command, "uncertain")
                        self.connect.stop()
                        if not self.connect.stopped():
                            return "pending", None
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
            if retained and prepared == command:
                self.resume_retained(command, retained)
            return "applied", prepared if command["kind"] == "reconcile" else None

    def _check_table_access(self, command, source):
        checks = lifecycle_checks(source.id, command["published_scope"])
        try:
            self.profile.validate_source(source)
        except TablePrerequisiteFailed as exc:
            entry = next((entry for entry in command["published_scope"] if entry["qualified_table"] == exc.table), None)
            if entry and entry["mirror_id"] in checks:
                table_prerequisite_check(command, table=exc.table, cause=exc.cause, passed=False,
                                         request_id=checks[entry["mirror_id"]])
            raise
        for entry in command["published_scope"]:
            if entry["mirror_id"] in checks:
                table_prerequisite_check(command, table=entry["qualified_table"], cause="permission", passed=True,
                                         request_id=checks[entry["mirror_id"]])

    def _ensure_scope_fence(self, command):
        source_id = command["source_id"]
        with source_control_transaction(source_id) as (session, _):
            state = load_binding(session, source_id)
            allocation = state.get("allocation", {})
            cached = state.get("scope_fence", {})
            if allocation.get("command") == command or (
                    cached.get("operation_id") == command["operation_id"] and not cached.get("inconclusive_tables")):
                return
        checks = lifecycle_checks(source_id, command["published_scope"])
        fence = self.signals.scope_fence(command)
        with source_control_transaction(source_id) as (session, source):
            if self._current_command(session, source, include_applied=True) != command:
                raise RuntimeBlocked("capture_preparation_superseded")
            state = load_binding(session, source_id)
            if cached.get("operation_id") == command["operation_id"]:
                boundaries = fence.get("table_boundaries", {})
                unchecked = cached.get("inconclusive_tables", {}).keys() - boundaries.keys() - fence.get("inconclusive_tables", {}).keys()
                if (unchecked or cached["mirror_receipts"] != fence["mirror_receipts"]
                        or any(boundaries.get(mid) != boundary for mid, boundary in cached.get("table_boundaries", {}).items())):
                    raise RuntimeBlocked("scope_fence_unconfirmed")
            state["scope_fence"] = fence
            save_binding(session, state)
        if fence.get("inconclusive_tables"):
            authority = Authority(source_id, command["binding_id"], command["owner_epoch"], command["runtime_instance_id"],
                                  command["control_revision"], command["credential_revision"], str(command["capture_generation"]))
            for mid, ref in fence["inconclusive_tables"].items():
                if mid in checks:
                    record_continuity_receipt(authority=authority, scope=command["published_scope"], mirror_id=mid,
                                              check_id=checks[mid], decision=dict(result="unknown", evidence_ref=ref,
                                                                                  observed_at=fence["observed_at"]))



# Only these operator-actionable codes may cross the process diagnostics boundary.
# Driver responses, evidence, and unrecognized exception text stay private.
_REPORTED_FAULTS = frozenset({
    "conflicting_owner_request_files", "replacement_owner_blocked", "owner_allocation_blocked",
    "owner_assignment_unproven", "replacement_owner_requires_recovery", "published_scope_changed",
    "source_executor_busy", "capture_evidence_rejected", "capture_delivery_blocked",
    "open_generation_preparation_blocked", "capture_preparation_management_unconfirmed",
    "capture_snapshot_management_unconfirmed", "incremental_snapshot_blocked",
    "configuration_outcome_uncertain", "resume_outcome_uncertain", "stop_outcome_uncertain",
    "readiness_unknown_or_failed", "retained_position_resume_driver_required",
})


def poll_sources(runtimes, previous_faults):
    for source_id, runtime, request_file, replacement_file in runtimes:
        try:
            runtime.poll_once(source_id, owner_allocation_file=request_file, replacement_owner_file=replacement_file)
        except RuntimeBlocked as exc:
            code = str(exc)
            if code not in _REPORTED_FAULTS:
                code = "capture_runtime_blocked"
            if previous_faults.get(source_id) != code:
                print(json.dumps({"source_id": source_id, "state": "blocked", "code": code}), flush=True)
            previous_faults[source_id] = code
        else:
            if previous_faults.pop(source_id, None) is not None:
                print(json.dumps({"source_id": source_id, "state": "recovered"}), flush=True)
    return bool(previous_faults)


def _signing_authority(trust):
    return SignedAuthority(
        keys={kid: load_pem_public_key(protected_read(path)) for kid, path in trust["public_key_files"].items()},
        issuer=trust["issuer"], audience=trust["audience"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dispatch-recovery", metavar="OPERATION_ID")
    args = parser.parse_args()
    clients = []
    runtimes = []
    stopping = Event()
    previous_handlers = {}

    def stop(signum, frame):
        stopping.set()
        for _, runtime, _, _ in runtimes:
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
        if args.dispatch_recovery is not None:
            session_factory = get_session_factory()
            with session_factory() as session:
                operation = session.get(RecoveryRow, args.dispatch_recovery)
                entry = next((entry for entry in sources if operation is not None
                              and operation.source_id == entry["source_id"]), None)
            if entry is None:
                raise RuntimeBlocked("recovery_source_not_assigned")
            signal_http = PrivateHTTP(**entry["signals_tls"])
            clients.append(signal_http)
            profile = PostgreSQLCaptureProfile(**entry["postgresql_profile"])
            signals = ReadinessSignals(signal_http, verifier=_signing_authority(entry["signing_trust"]),
                                       scope=profile.scope, **entry["readiness_policy"])
            state = dispatch_recovery(settings=get_settings(), session_factory=session_factory,
                                      operation_id=args.dispatch_recovery, source_id=entry["source_id"], signals=signals)
            print(state)
            return 0 if state in {"invalidated", "dispatched", "applied"} else 2
        journal = CommandJournal(config["state_directory"])
        runtimes = []
        for entry in sources:
            connect_http = PrivateHTTP(**entry["connect_tls"])
            clients.append(connect_http)
            signal_http = PrivateHTTP(**entry["signals_tls"])
            clients.append(signal_http)
            verifier = _signing_authority(entry["signing_trust"])
            profile = PostgreSQLCaptureProfile(**entry["postgresql_profile"])
            if (profile.scope["source_id"] != entry["source_id"]
                    or profile.scope["connector_name"] != entry["connector_name"]):
                raise RuntimeBlocked("configured_scope_mismatch")
            signals = ReadinessSignals(signal_http, verifier=verifier, scope=profile.scope, **entry["readiness_policy"])
            delivery = SourceDelivery(
                settings_file=entry.get("delivery_settings_file"), source_id=entry["source_id"],
                journal=journal, signals=signals, verifier=verifier, profile=profile,
            )
            retained_resume = entry.get("retained_position_resume", False)
            if type(retained_resume) is not bool or (retained_resume and profile.snapshot is None):
                raise RuntimeBlocked("retained_position_resume_configuration_invalid")
            runtime = CaptureRuntime(
                journal=journal, connect=ConnectLifecycle(connect_http, entry["connector_name"]), signals=signals,
                profile=profile, credentials=CredentialFiles(**entry["credential_files"]),
                delivery=delivery, prepare_delivery=delivery.prepare,
                resume_retained=delivery.resume_retained if retained_resume else None,
            )
            runtimes.append((entry["source_id"], runtime, entry.get("owner_allocation_file"),
                             entry.get("replacement_owner_file")))
            observers = entry.get("snapshot_observers")
            if (profile.snapshot is None) != (observers is None):
                raise RuntimeBlocked("snapshot_observer_configuration_required")
            if observers is not None:
                from backend.metadata.capture.completed_publication import publish_completed

                if set(observers) != {"receipt", "notification", "max_age_seconds"}:
                    raise RuntimeBlocked("snapshot_observer_configuration_invalid")
                observation_clients = {}
                for role in ("receipt", "notification"):
                    observer = PrivateHTTP(**observers[role]["tls"])
                    clients.append(observer)
                    observation_clients[role] = observer
                runtime.snapshot = SnapshotCoordinator(
                    journal=journal, signals=SnapshotGateway(dispatch=signal_http, **observation_clients),
                    receipt_trust=_signing_authority(observers["receipt"]["signing_trust"]),
                    notification_trust=_signing_authority(observers["notification"]["signing_trust"]),
                    max_observation_age_seconds=observers["max_age_seconds"], recheck=runtime.recheck_snapshot,
                )
                runtime.publish_completed = publish_completed
        previous_faults = {}
        while not stopping.is_set():
            blocked = poll_sources(runtimes, previous_faults)
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
        for _, runtime, _, _ in runtimes:
            if runtime.delivery is not None:
                runtime.delivery.close()
        for client in clients:
            client.close()
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
