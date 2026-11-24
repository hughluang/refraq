"""Independent heartbeat and bounded read-only capture telemetry collection."""

from collections.abc import Callable
from copy import deepcopy
from datetime import timedelta
from threading import Event, Lock, Thread
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from confluent_kafka import IsolationLevel, TopicPartition
from confluent_kafka.admin import OffsetSpec
from sqlalchemy import text

from backend.core.time import format_instant, parse_instant, utc_now
from backend.metadata.capture.control import AUTHORITY_KEYS
from backend.metadata.capture.delivery_composition import applier_engine
from backend.metadata.mirrors import diagnostics
from backend.metadata.mirrors.diagnostic_schemas import DiagnosticPolicy, LinkObservation, MirrorSample, RowSample, SourceReceipt
from backend.metadata.mirrors.diagnostic_store import DiagnosticStore


class RuntimeDiagnostics:
    def __init__(self, *, policy: DiagnosticPolicy, runtimes, wait_seconds,
                 store: DiagnosticStore, read_scope: Callable):
        self.policy = policy
        self.store = store
        self.read_scope = read_scope
        self.wait_seconds = wait_seconds
        self.stop = Event()
        self.thread = None
        self.worker = None
        self.lock = Lock()
        self.wake = Event()
        self.pending = {}
        self.cycles = {}
        self.engines = {}
        self.started = None
        self.started_clock = None
        self.count_due = {}
        self.groups = {}
        for sid, runtime, *_ in runtimes:
            self.groups.setdefault(runtime.signals.runtime_instance_id, []).append(sid)

    def _window(self, seconds, *, now=None):
        now = now or utc_now()
        return dict(observed_at=format_instant(now, timespec="microseconds"),
                    valid_until=format_instant(now + timedelta(seconds=seconds), timespec="microseconds"))

    def start(self):
        self.thread = Thread(target=self._heartbeat, name="capture-diagnostic-heartbeat", daemon=True)
        self.thread.start()
        self.worker = Thread(target=self._collect, name="capture-diagnostic-samples", daemon=True)
        self.worker.start()

    def _heartbeat(self):
        while not self.stop.is_set():
            try:
                for rid in self.groups:
                    diagnostics.record_runtime(rid, "heartbeat", self._window(self.policy.heartbeat_valid_seconds),
                                               store=self.store)
                    diagnostics.record_runtime(rid, "assignment", dict(**self._window(self.policy.round_valid_seconds),
                                               source_ids=self.groups[rid], end_of_cycle_wait_seconds=self.wait_seconds),
                                               store=self.store)
                    with self.lock:
                        cycle = deepcopy(self.cycles.get(rid))
                    if cycle:
                        diagnostics.record_runtime(rid, "cycle", cycle, store=self.store)
            except Exception:
                # Diagnostic persistence never substitutes for mandatory local safety.
                print("capture_diagnostic_heartbeat_unavailable", flush=True)
            self.stop.wait(self.policy.heartbeat_interval_seconds)

    def begin_round(self):
        self.started = utc_now()
        self.started_clock = monotonic()
        with self.lock:
            for rid in self.groups:
                prior = self.cycles.get(rid, {})
                self.cycles[rid] = dict(**self._window(self.policy.round_valid_seconds),
                    started_at=format_instant(self.started), completed_at=None, duration_seconds=None,
                    last_completed_at=prior.get("last_completed_at"), last_duration_seconds=prior.get("last_duration_seconds"))

    def end_round(self):
        now = utc_now()
        with self.lock:
            for rid in self.groups:
                duration = monotonic() - self.started_clock
                self.cycles[rid] = dict(**self._window(self.policy.round_valid_seconds, now=now),
                    started_at=format_instant(self.started), completed_at=format_instant(now), duration_seconds=duration,
                    last_completed_at=format_instant(now), last_duration_seconds=duration)

    def sample_source(self, source_id, runtime):
        """Queue only the latest immutable installation; never block capture on I/O."""
        delivery = runtime.delivery
        snapshot = None
        if delivery is not None and delivery.engine is not None:
            snapshot = SimpleNamespace(settings=deepcopy(delivery.settings), tables=deepcopy(delivery.tables),
                clients=[SimpleNamespace(binding=c.binding, identity=c.identity, limits=c.limits) for c in delivery.clients])
        with self.lock:
            self.pending[source_id] = (runtime.signals, snapshot)
        self.wake.set()

    def _collect(self):
        try:
            while not self.stop.is_set():
                self.wake.wait(1)
                with self.lock:
                    pending, self.pending = self.pending, {}
                    self.wake.clear()
                for sid, (signals, delivery) in pending.items():
                    if self.stop.is_set():
                        break
                    try:
                        if delivery:
                            if sid not in self.engines:
                                self.engines[sid] = applier_engine(delivery.settings["target"])
                            delivery.engine = self.engines[sid]
                        self._sample_source(sid, signals, delivery)
                    except Exception:
                        print("capture_diagnostic_sample_unavailable", flush=True)
        finally:
            for engine in self.engines.values():
                engine.dispose()

    def _sample_source(self, source_id, signals, delivery):
        mirrors, bindings = self.read_scope()
        state = bindings.get(source_id)
        if not state or state.get("runtime_instance_id") != signals.runtime_instance_id:
            return
        authority = {key: state[key] for key in AUTHORITY_KEYS}
        round_id = uuid4().hex
        rows = [m for m in mirrors if m["source_id"] == source_id]
        allowed = {m["id"] for m in rows}
        try:
            receipt = signals.diagnostic_observation(authority, round_id)
            now = utc_now()
            if any(s.mirror_id not in allowed or s.observed_at > now or
                   s.valid_until > s.observed_at + timedelta(seconds=self.policy.sample_valid_seconds) for s in receipt.samples):
                raise ValueError("Diagnostic sample scope or validity mismatch")
            if any(c.observed_at > now or c.valid_until > c.observed_at + timedelta(seconds=self.policy.check_valid_seconds) for c in receipt.checks.values()):
                raise ValueError("Diagnostic link validity exceeds approved policy")
        except Exception:
            receipt = SourceReceipt()
        if delivery is not None and delivery.engine is not None:
            self._target_samples(delivery, authority, rows, receipt)
        diagnostics.record_source(source_id, authority, receipt, round_id=round_id, store=self.store)

    def _read_target(self, engine, function, identity):
        with engine.begin() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            timeout = self.policy.row_count_timeout_ms
            lock = self.policy.row_count_lock_timeout_ms
            connection.execute(text("SELECT set_config('statement_timeout', :timeout, true), "
                                    "set_config('lock_timeout', :lock, true)"),
                               dict(timeout=str(timeout), lock=str(lock)))
            return connection.execute(text(f"SELECT source_mirror_state.{function}(:identity)"),
                                      dict(identity=identity)).scalar_one()

    def _target_samples(self, delivery, authority, mirrors, receipt):
        external = {s.mirror_id for s in receipt.samples}
        clients = {c.binding.generation_id: c for c in delivery.clients}
        target_authority = dict(authority, capture_generation=str(authority["capture_generation"]))
        target_authority["resource_binding_id"] = target_authority.pop("binding_id")
        for table in delivery.tables:
            if self.stop.is_set():
                break
            mid, gid = table.get("mirror_id"), table.get("generation_id")
            if mid is None or gid is None:
                # Pending or blocked installation has no target binding to query.
                continue
            mirror = next((m for m in mirrors if m["id"] == mid), None)
            if mirror is None:
                continue
            try:
                progress = self._read_target(delivery.engine, "diagnostic_progress", gid)
            except Exception:
                receipt.checks["storage"] = LinkObservation(outcome="failed", error_code="STORAGE_UNAVAILABLE",
                                           **self._window(self.policy.check_valid_seconds))
            else:
                receipt.checks.setdefault("storage", LinkObservation(outcome="healthy", **self._window(self.policy.check_valid_seconds)))
                if progress and progress["authority"] == target_authority:
                    self._activity(progress, clients.get(gid), authority, receipt, external)
        for mirror in mirrors:
            if self.stop.is_set():
                break
            mid = mirror["id"]
            if mirror.get("published_generation_id") and monotonic() >= self.count_due.get(mid, 0):
                self.count_due[mid] = monotonic() + self.policy.row_count_interval_seconds
                try:
                    rows = self._read_target(delivery.engine, "diagnostic_row_count", mid)
                    if rows:
                        at = parse_instant(rows["observed_at"])
                        diagnostics.record_rows(mid, RowSample(**rows, valid_until=at + timedelta(seconds=self.policy.sample_valid_seconds)),
                                                store=self.store)
                except Exception:
                    # A timeout, superseding publication or DROP is a missing sample.
                    pass
                break

    def _activity(self, progress, client, authority, receipt, external):
        now = parse_instant(format_instant(utc_now()))
        mid = progress["mirror_id"]
        previous = self.store.read("counter", mid)
        stamp = dict(**progress, observed_at=format_instant(now, timespec="microseconds"))
        if mid in external or not previous or previous["generation_id"] != progress["generation_id"] or previous["authority"] != progress["authority"]:
            self.store.update("counter", mid, lambda _: stamp)
            return
        start = parse_instant(previous["observed_at"])
        if start >= now or any(progress[key] < previous[key] for key in ("processed_events", "processed_batches")):
            return
        self.store.update("counter", mid, lambda _: stamp)
        lag = None
        if client is not None:
            try:
                client.identity.verify(client.binding, client.limits.metadata_seconds)
                partition = TopicPartition(client.binding.topic, client.binding.partition_identity.partition)
                first, end = [client.identity.admin.list_offsets({partition: spec}, isolation_level=IsolationLevel.READ_COMMITTED,
                              request_timeout=client.limits.metadata_seconds)[partition].result(timeout=client.limits.metadata_seconds).offset
                              for spec in (OffsetSpec.earliest(), OffsetSpec.latest())]
                if first <= progress["applied_offset"] + 1 <= end:
                    lag = end - progress["applied_offset"] - 1
            except Exception:
                pass
        events = progress["processed_events"] - previous["processed_events"]
        current_bytes, previous_bytes = progress.get("processed_bytes"), previous.get("processed_bytes")
        committed_bytes = (current_bytes - previous_bytes if current_bytes is not None and previous_bytes is not None
                           and current_bytes >= previous_bytes else None)
        observed = utc_now()
        receipt.samples.append(MirrorSample(
            mirror_id=mid, generation_id=progress["generation_id"], capture_generation=str(authority["capture_generation"]),
            interval_start=start, interval_end=now, **self._window(self.policy.sample_valid_seconds, now=observed),
            committed_events=events, committed_batches=progress["processed_batches"] - previous["processed_batches"],
            committed_bytes=committed_bytes,
            position_lag=lag, last_target_commit_at=progress["last_target_commit_at"],
            write_state="active" if events else "idle",
        ))

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()
        self.wake.set()
        if self.worker:
            self.worker.join()
