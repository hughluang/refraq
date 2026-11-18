"""Independent, explicitly invoked capture command consumer.

This bounded slice executes proven stop only. Reconcile/start, credential
installation, Kafka application and snapshot dispatch remain blocked.
"""

import argparse
import json
import os
import time

from sqlalchemy.engine import make_url

from backend.core.config import get_settings
from backend.metadata.capture.control import record_applied_evidence, source_control_transaction
from backend.metadata.capture.runtime_adapters import ConnectLifecycle, PrivateHTTP, ReadinessSignals
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked, protected_read
from backend.metadata.capture.store import list_operations, load_binding


class CaptureRuntime:
    def __init__(self, *, journal, connect, signals):
        self.journal = journal
        self.connect = connect
        self.signals = signals

    def poll_source(self, source_id):
        with self.journal.source_lock(source_id):
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
                phase = self.journal.accept(command)
                if command["kind"] != "stop":
                    raise RuntimeBlocked("reconcile_adapter_not_installed")
                self.signals.observation(command, "before_stop")
                # Always reconcile before sending, including response-loss/crash
                # recovery. No second mutation while the first outcome is unknown.
                if not self.connect.stopped():
                    if phase in {"uncertain", "observed", "applied"}:
                        raise RuntimeBlocked("stop_outcome_uncertain")
                    self.journal.mark(command, "uncertain")
                    self.connect.stop()
                    if not self.connect.stopped():
                        return "pending"
                evidence = self.signals.observation(command, "stopped")
                self.journal.mark(command, "observed")
            # Acceptance reacquires and compares all current stamps. A concurrent
            # PATCH after dispatch cannot accidentally receive this stop ack.
            record_applied_evidence(
                source_id=source_id, operation_id=command["operation_id"], evidence=evidence,
            )
            self.journal.mark(command, "applied")
            return "applied"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-file", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    clients = []
    journal = None
    try:
        config = json.loads(protected_read(args.config_file))
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
            runtime = CaptureRuntime(
                journal=journal,
                connect=ConnectLifecycle(connect_http, entry["connector_name"]),
                signals=ReadinessSignals(signal_http, **entry["readiness_policy"]),
            )
            runtimes.append((entry["source_id"], runtime))
        while True:
            blocked = False
            for source_id, runtime in runtimes:
                try:
                    runtime.poll_source(source_id)
                except RuntimeBlocked:
                    blocked = True
            if args.once:
                return 2 if blocked else 0
            time.sleep(interval)
    except Exception:
        # Neither argv nor stderr contains private config/driver/HTTP exceptions.
        print("capture_runtime_blocked")
        return 2
    finally:
        for client in clients:
            client.close()
        if journal is not None:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
