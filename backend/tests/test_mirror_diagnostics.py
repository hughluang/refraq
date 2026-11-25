"""Timestamped diagnostic receipts and target-counter sampling, without live services."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.metadata.capture.engines import engine_for_entry
from backend.core.time import utc_now
from backend.metadata.mirrors import diagnostics as d
from backend.metadata.mirrors.diagnostic_schemas import DiagnosticPolicy, LinkObservation, MirrorSample, RowSample, SourceReceipt
from backend.metadata.mirrors.diagnostic_store import DiagnosticStore


@pytest.fixture
def scope():
    now = utc_now()
    authority = dict(binding_id="binding", runtime_instance_id="runtime", owner_epoch=1,
                     capture_generation="capture", control_revision=2, credential_revision=1)
    mirror = dict(id="mirror", source_id="source", source_name="Sales", qualified_table="public.orders",
                  published_generation_id="generation", allocated_generation_id=None, estimated_rows=25)
    return SimpleNamespace(now=now, authority=authority, mirror=mirror,
                           store=DiagnosticStore(memory=True, transaction=None),
                           read_scope=lambda: ([mirror], {"source": authority}),
                           read_detail=lambda _: {"mirror": mirror})


def window(now):
    return dict(observed_at=now, valid_until=now + timedelta(seconds=60))


def sample(now, **kwargs):
    return MirrorSample(mirror_id="mirror", capture_generation="capture", generation_id="generation",
                        interval_start=now - timedelta(seconds=10), interval_end=now, **window(now), **kwargs)


def test_round_history_is_fixed_and_missing_round_is_empty(scope):
    now, authority = scope.now, scope.authority
    checks = {link: LinkObservation(outcome="healthy", **window(now)) for link in d.LINKS}
    d.record_source("source", authority, SourceReceipt(checks=checks), store=scope.store, now=now, round_id="first")
    d.record_source("source", authority, SourceReceipt(), store=scope.store, now=now + timedelta(seconds=1), round_id="empty")
    state = scope.store.read("source", "source")
    assert state["history"][0]["health"] == "healthy"
    assert all(c["health"] == "unobserved" for c in state["history"][1]["checks"])
    assert all(c["health"] == "healthy" for c in d.checks_at(state, now))
    assert all(c["health"] == "stale" for c in d.checks_at(state, now + timedelta(seconds=61)))
    for i in range(20):
        d.record_source("source", authority, SourceReceipt(), store=scope.store, now=now, round_id=f"round-{i}")
    assert len(scope.store.read("source", "source")["history"]) == 16


@pytest.mark.parametrize("link", d.LINKS)
def test_failure_expires_but_retains_safe_failure(scope, link):
    now, authority = scope.now, scope.authority
    good = LinkObservation(outcome="healthy", **window(now - timedelta(seconds=1)))
    d.record_source("source", authority, SourceReceipt(checks={link: good}), store=scope.store, now=now, round_id="good")
    bad = LinkObservation(outcome="failed", error_code=f"{link.upper()}_UNAVAILABLE", **window(now))
    d.record_source("source", authority, SourceReceipt(checks={link: bad}), store=scope.store, now=now, round_id="bad")
    check = next(c for c in d.checks_at(scope.store.read("source", "source"), now + timedelta(seconds=60)) if c["link"] == link)
    assert check["health"] == "stale"
    assert check["failure_at"] and check["last_success_at"] and check["error_code"]


def test_zero_missing_and_current_publication_are_distinct(scope):
    now, authority, mirror = scope.now, scope.authority, scope.mirror
    d.record_source("source", authority, SourceReceipt(samples=[sample(now, committed_events=0, write_state="idle", capture_state="blocked")]),
                    store=scope.store, now=now, round_id="idle")
    view = d.read_diagnostics(store=scope.store, read_scope=scope.read_scope, now=now)
    assert view["summary"]["committed_events"]["value"] == 0
    assert view["summary"]["pending_events"]["value"] is None
    assert view["summary"]["pending_events"]["missing"] == 1
    assert view["states"]["write"]["idle"] == 1 and view["states"]["capture"]["blocked"] == 1
    d.record_rows("mirror", RowSample(generation_id="old", row_count=8, **window(now)), store=scope.store)
    assert d.mirror_measurements("mirror", store=scope.store, read_scope=scope.read_scope, read_detail=scope.read_detail, now=now)["row_sample"] is None
    d.record_rows("mirror", RowSample(generation_id="generation", row_count=0, **window(now + timedelta(seconds=1))), store=scope.store)
    assert d.mirror_measurements("mirror", store=scope.store, read_scope=scope.read_scope, read_detail=scope.read_detail,
                                 now=now + timedelta(seconds=1))["row_sample"]["row_count"] == 0
    mirror["published_generation_id"] = "new"
    detail = d.mirror_measurements("mirror", store=scope.store, read_scope=scope.read_scope, read_detail=scope.read_detail, now=now)
    assert detail["sample"] is None and detail["estimated_rows"] == 25


def test_revision_change_and_expiry_remove_samples_from_coverage(scope):
    now, authority = scope.now, scope.authority
    d.record_source("source", authority, SourceReceipt(samples=[sample(now, committed_events=12)]), store=scope.store, now=now, round_id="observed")
    assert d.read_diagnostics(store=scope.store, read_scope=scope.read_scope, now=now)["summary"]["committed_events"]["sampled"] == 1
    assert d.read_diagnostics(store=scope.store, read_scope=scope.read_scope, now=now + timedelta(seconds=61))["summary"]["committed_events"]["sampled"] == 0
    authority["credential_revision"] += 1
    assert d.mirror_measurements("mirror", store=scope.store, read_scope=scope.read_scope, read_detail=scope.read_detail, now=now)["sample"] is None


def test_partial_scope_and_intervals_are_visible(scope):
    now, authority, mirror = scope.now, scope.authority, scope.mirror
    second = dict(mirror, id="second", qualified_table="public.lines")
    third = dict(mirror, id="third")
    scope.read_scope = lambda: ([mirror, second, third], {"source": authority})
    other = sample(now - timedelta(seconds=2), committed_events=4).model_copy(update={"mirror_id": "second"})
    d.record_source("source", authority, SourceReceipt(samples=[sample(now, committed_events=3), other]),
                    store=scope.store, now=now, round_id="partial")
    view = d.read_diagnostics(store=scope.store, read_scope=scope.read_scope, now=now)
    metric = view["summary"]["committed_events"]
    assert (metric["value"], metric["sampled"], metric["missing"]) == (7, 2, 1)
    assert metric["oldest_observation"] != metric["newest_observation"]
    assert len(view["intervals"]) == 3


def test_heartbeat_does_not_refresh_cycle(scope):
    now = scope.now
    d.record_runtime("runtime", "cycle", dict(**{k: v.isoformat() for k, v in window(now - timedelta(seconds=70)).items()},
                                              started_at=now.isoformat(), completed_at=now.isoformat(), duration_seconds=2), store=scope.store)
    d.record_runtime("runtime", "heartbeat", {k: v.isoformat() for k, v in window(now).items()}, store=scope.store)
    runtime, = d.read_diagnostics(store=scope.store, read_scope=scope.read_scope, now=now)["runtimes"]
    assert runtime["heartbeat_health"] == "healthy" and runtime["cycle_health"] == "stale"


def test_receipts_reject_unproven_freshness_and_raw_secrets(scope):
    now = scope.now
    with pytest.raises(ValidationError):
        sample(now, freshness_ms=0)
    with pytest.raises(ValidationError):
        SourceReceipt.model_validate({"checks": {}, "raw_connector": "secret"})
    with pytest.raises(ValidationError):
        LinkObservation(outcome="failed", error_code="password=secret", **window(now))


def policy():
    return DiagnosticPolicy(heartbeat_interval_seconds=5, heartbeat_valid_seconds=15,
        check_valid_seconds=60, sample_valid_seconds=60, round_valid_seconds=120,
        row_count_interval_seconds=300, row_count_timeout_ms=500, row_count_lock_timeout_ms=50)


def test_native_counter_baseline_idle_burst_and_authority_conversion(scope, monkeypatch):
    from backend.metadata.capture.diagnostics import RuntimeDiagnostics
    now, authority, mirror = scope.now, scope.authority, scope.mirror
    collector = RuntimeDiagnostics(policy=policy(), runtimes=[], wait_seconds=5, store=scope.store, read_scope=scope.read_scope)
    target_authority = dict(authority, resource_binding_id=authority["binding_id"])
    target_authority.pop("binding_id")
    progress = dict(mirror_id="mirror", generation_id="generation", authority=target_authority,
                    processed_events=10, processed_batches=2, applied_offset=15, last_target_commit_at=None)
    delivery = SimpleNamespace(clients=[], tables=[dict(mirror_id="mirror", generation_id="generation")], engine=object())
    monkeypatch.setattr(collector, "_read_target", lambda *args: progress if args[1] == "diagnostic_progress" else None)
    receipt = SourceReceipt()
    collector._target_samples(delivery, authority, [mirror], receipt)
    assert receipt.checks["storage"].outcome == "healthy" and not receipt.samples
    prior = scope.store.read("counter", "mirror")
    prior["observed_at"] = (now - timedelta(seconds=2)).isoformat()
    scope.store.update("counter", "mirror", lambda _: prior)
    collector._target_samples(delivery, authority, [mirror], receipt)
    assert receipt.samples[0].committed_events == 0 and receipt.samples[0].write_state == "idle"
    progress["processed_events"] = 100
    progress["processed_batches"] = 4
    monkeypatch.setattr("backend.metadata.capture.diagnostics.utc_now", lambda: now + timedelta(seconds=5))
    fresh = SourceReceipt()
    collector._target_samples(delivery, authority, [mirror], fresh)
    assert fresh.samples[0].committed_events == 90 and fresh.samples[0].pending_events is None


def test_authorized_operations_read_requires_no_source_data_permission(scope, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.admin.deps import get_current_user
    from backend.admin.role_store import get_role_store
    from backend.core.errors import AppError
    from backend.main import app_error_handler
    from backend.metadata.mirrors import router as mirror_router

    app = FastAPI()
    app.state.mirror_diagnostics = scope.store
    app.state.mirror_diagnostic_scope = scope.read_scope
    app.include_router(mirror_router.router)
    monkeypatch.setattr(mirror_router.service, "get_mirror_detail", scope.read_detail)
    app.add_exception_handler(AppError, app_error_handler)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="operator", role_id="role")
    permissions = ["mirror:read"]
    app.dependency_overrides[get_role_store] = lambda: SimpleNamespace(get_by_id=lambda _: SimpleNamespace(key="custom", permissions=permissions))
    with TestClient(app) as client:
        assert client.get("/mirror-diagnostics?source_id=source").status_code == 200
        assert client.get("/mirrors/mirror/measurements").status_code == 200
        assert client.get("/mirror-diagnostics?source_offset=-1").status_code == 422
        permissions.clear()
        assert client.get("/mirror-diagnostics?source_id=source").status_code == 403
        assert client.get("/mirrors/mirror/measurements").status_code == 403


def test_full_assignment_is_not_truncated_to_selected_source(scope):
    now, authority, mirror = scope.now, scope.authority, scope.mirror
    bindings = {f"source-{i}": dict(authority) for i in range(12)}
    bindings["source"] = authority
    scope.read_scope = lambda: ([mirror], bindings)
    stamp = {k: v.isoformat() for k, v in window(now).items()}
    d.record_runtime("runtime", "assignment", dict(**stamp, source_ids=list(bindings), end_of_cycle_wait_seconds=5), store=scope.store)
    view = d.read_diagnostics(store=scope.store, read_scope=scope.read_scope, source_id="source", assignment_offset=8, now=now)
    runtime, = view["runtimes"]
    assert runtime["total_sources"] == 13 and len(runtime["source_ids"]) == 5
    assert view["source_count"] == 1


def test_source_queue_coalesces_without_network_or_database_io(scope):
    from backend.metadata.capture.diagnostics import RuntimeDiagnostics
    collector = RuntimeDiagnostics(policy=policy(), runtimes=[], wait_seconds=5, store=scope.store, read_scope=scope.read_scope)
    runtime = SimpleNamespace(delivery=None, signals=object())
    collector.sample_source("source", runtime)
    collector.sample_source("source", runtime)
    assert len(collector.pending) == 1 and collector.wake.is_set()


def test_gateway_signature_binds_exact_scope_authority_and_round(scope):
    import jwt
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from backend.metadata.capture.authority import SignedAuthority
    from backend.metadata.capture.runtime_adapters import ReadinessSignals
    from backend.metadata.capture.runtime_store import RuntimeBlocked

    now, authority = scope.now, scope.authority
    key = Ed25519PrivateKey.generate()
    claims = dict(iss="observer", aud="runtime", iat=int(now.timestamp()) - 1, nbf=int(now.timestamp()) - 1,
                  exp=int(now.timestamp()) + 30, jti="receipt", purpose="observation:diagnostics",
                  authority=authority, scope={"tables": ["public.orders"]}, operation_id="round-one",
                  diagnostics={"checks": {}, "samples": []})
    def sign():
        return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": "observer"})
    signals = ReadinessSignals(engine=engine_for_entry({"postgresql_profile": {}}), http=SimpleNamespace(request=lambda *a, **kw: {"signature": sign()}), runtime_instance_id="runtime",
        max_age_seconds=30, required_checks={"profile_qualified", "source_pressure", "delivery_bounded", "credential_valid", "alarm_drill", "owner_excluded", "target_fenced"},
        scope=claims["scope"], verifier=SignedAuthority(keys={"observer": key.public_key()}, issuer="observer", audience="runtime"))
    assert signals.diagnostic_observation(authority, "round-one") == SourceReceipt()
    with pytest.raises(RuntimeBlocked):
        signals.diagnostic_observation(authority, "round-two")
    with pytest.raises(RuntimeBlocked):
        signals.diagnostic_observation(dict(authority, owner_epoch=2), "round-one")
    claims["diagnostics"]["password"] = "redacted-test-marker"
    with pytest.raises(ValidationError):
        signals.diagnostic_observation(authority, "round-one")


def test_owner_transition_resets_current_checks_but_preserves_round_history(scope):
    now, authority = scope.now, scope.authority
    d.record_source("source", authority, SourceReceipt(checks={"storage": LinkObservation(outcome="healthy", **window(now))}),
                    store=scope.store, now=now, round_id="prior-owner")
    authority["owner_epoch"] += 1
    d.record_source("source", authority, SourceReceipt(), store=scope.store, now=now, round_id="new-owner")
    state = scope.store.read("source", "source")
    assert len(state["history"]) == 2
    assert all(c["health"] == "unobserved" for c in d.checks_at(state, now))


def test_measurement_http_projection_excludes_internal_authority(scope):
    from backend.metadata.mirrors.diagnostic_schemas import MeasurementResponse, DiagnosticsResponse
    now, authority = scope.now, scope.authority
    d.record_source("source", authority, SourceReceipt(samples=[sample(now, captured_events=25, committed_events=20, pending_events=5)]),
                    store=scope.store, now=now, round_id="observed")
    view = MeasurementResponse.model_validate(d.mirror_measurements(
        "mirror", store=scope.store, read_scope=scope.read_scope, read_detail=scope.read_detail, now=now)).model_dump(mode="json")
    assert view["sample"]["committed_events"] == 20
    assert "authority" not in view["sample"]
    DiagnosticsResponse.model_validate(d.read_diagnostics(store=scope.store, read_scope=scope.read_scope, now=now))


def test_unallocated_table_does_not_discard_shared_healthy_check(scope, monkeypatch):
    from backend.metadata.capture.diagnostics import RuntimeDiagnostics
    now, authority, mirror = scope.now, scope.authority, scope.mirror
    collector = RuntimeDiagnostics(policy=policy(), runtimes=[], wait_seconds=5, store=scope.store, read_scope=scope.read_scope)
    mirror["published_generation_id"] = None
    receipt = SourceReceipt(checks={"replication": LinkObservation(outcome="healthy", **window(now))})
    delivery = SimpleNamespace(clients=[], tables=[{"topic": "pending-table"}], engine=object())
    monkeypatch.setattr(collector, "_read_target", lambda *args: pytest.fail("Unallocated target must not be queried"))
    collector._target_samples(delivery, authority, [mirror], receipt)
    assert receipt.checks["replication"].outcome == "healthy" and receipt.samples == []


def test_independent_stores_do_not_share_observations(scope):
    other = DiagnosticStore(memory=True, transaction=None)
    now, authority = scope.now, scope.authority
    d.record_source("source", authority, SourceReceipt(samples=[sample(now, committed_events=12)]),
                    store=scope.store, now=now, round_id="observed")
    first = d.read_diagnostics(store=scope.store, read_scope=scope.read_scope, now=now)
    second = d.read_diagnostics(store=other, read_scope=scope.read_scope, now=now)
    assert first["summary"]["committed_events"]["value"] == 12
    assert second["summary"]["committed_events"]["value"] is None
    assert second["sources"][0]["history"] == [None] * 16


def test_mixed_lineage_receipt_is_rejected_before_any_observation_is_written(scope):
    now, authority = scope.now, scope.authority
    valid = sample(now, committed_events=12)
    invalid = sample(now, committed_events=7).model_copy(update={"mirror_id": "other", "capture_generation": "retired"})
    receipt = SourceReceipt(checks={"storage": LinkObservation(outcome="healthy", **window(now))}, samples=[valid, invalid])
    with pytest.raises(ValueError, match="Sample capture lineage mismatch"):
        d.record_source("source", authority, receipt, store=scope.store, now=now, round_id="mixed")
    assert scope.store.read("source", "source") is None
    assert scope.store.all("sample") == {}


def test_older_observation_cannot_replace_a_new_sample(scope):
    now, authority = scope.now, scope.authority
    d.record_source("source", authority, SourceReceipt(samples=[sample(now, committed_events=12)]),
                    store=scope.store, now=now, round_id="newer")
    older = sample(now - timedelta(seconds=5), committed_events=1)
    d.record_source("source", authority, SourceReceipt(samples=[older]), store=scope.store, now=now, round_id="older")
    view = d.read_diagnostics(store=scope.store, read_scope=scope.read_scope, now=now)
    assert view["summary"]["committed_events"]["value"] == 12
    assert scope.store.read("sample", "mirror")["interval_end"] == sample(now).model_dump(mode="json")["interval_end"]


def test_restarted_runtime_retains_last_completed_cycle(scope, monkeypatch):
    from backend.metadata.capture.diagnostics import RuntimeDiagnostics

    observed = scope.now
    monkeypatch.setattr("backend.metadata.capture.diagnostics.utc_now", lambda: observed)
    runtimes = [("source", SimpleNamespace(signals=SimpleNamespace(runtime_instance_id="runtime")))]
    first = RuntimeDiagnostics(policy=policy(), runtimes=runtimes, wait_seconds=5, store=scope.store, read_scope=scope.read_scope)
    first.begin_round()
    observed += timedelta(seconds=2)
    first.end_round()
    d.record_runtime("runtime", "cycle", first.cycles["runtime"], store=scope.store)
    completed = scope.store.read("runtime_cycle", "runtime")

    observed += timedelta(seconds=3)
    restarted = RuntimeDiagnostics(policy=policy(), runtimes=runtimes, wait_seconds=5, store=scope.store, read_scope=scope.read_scope)
    restarted.begin_round()
    assert restarted.cycles["runtime"]["last_completed_at"] is None
    d.record_runtime("runtime", "cycle", restarted.cycles["runtime"], store=scope.store)
    current = scope.store.read("runtime_cycle", "runtime")
    assert current["completed_at"] is None and current["started_at"] != completed["started_at"]
    assert current["last_completed_at"] == completed["last_completed_at"]
    assert current["last_duration_seconds"] is None


def test_native_counter_baselines_are_isolated_between_stores(scope, monkeypatch):
    from backend.metadata.capture.diagnostics import RuntimeDiagnostics

    other = DiagnosticStore(memory=True, transaction=None)
    first = RuntimeDiagnostics(policy=policy(), runtimes=[], wait_seconds=5, store=scope.store, read_scope=scope.read_scope)
    second = RuntimeDiagnostics(policy=policy(), runtimes=[], wait_seconds=5, store=other, read_scope=scope.read_scope)
    observed = scope.now
    monkeypatch.setattr("backend.metadata.capture.diagnostics.utc_now", lambda: observed)
    progress = dict(mirror_id="mirror", generation_id="generation", authority={}, processed_events=10,
                    processed_batches=2, applied_offset=15, last_target_commit_at=None)
    first._activity(progress, None, scope.authority, SourceReceipt(), set())
    observed += timedelta(seconds=2)
    progress["processed_events"] += 4
    initial = SourceReceipt()
    second._activity(progress, None, scope.authority, initial, set())
    assert initial.samples == []
    continuing = SourceReceipt()
    first._activity(progress, None, scope.authority, continuing, set())
    assert continuing.samples[0].committed_events == 4


def test_repeated_round_does_not_duplicate_source_history(scope):
    receipt = SourceReceipt(checks={"storage": LinkObservation(outcome="healthy", **window(scope.now))})
    for _ in range(2):
        d.record_source("source", scope.authority, receipt, store=scope.store, now=scope.now, round_id="same")
    assert len(scope.store.read("source", "source")["history"]) == 1
