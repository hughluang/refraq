"""Native target and protected runtime gates for open preparation."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
import json
import ssl
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import jwt
import psycopg
from psycopg import sql
import pytest
from sqlalchemy import create_engine, text

from backend.core.time import utc_now
from backend.metadata.capture import control, delivery_composition, runtime
from backend.metadata.capture.test_delivery import KEY, SCHEMA
from backend.metadata.capture.test_published_scope import SOURCE, management as management, publish
from backend.metadata.capture.test_runtime import CHECKS, SIGNING_KEY, TRUST, allocation_observation, observation
from backend.metadata.mirrors import bootstrap, service
from backend.metadata.mirrors.types import Authority, PartitionIdentity
from backend.tests.test_mirror_generation_allocation import target_dsn as target_dsn


@pytest.mark.integration
def test_fence_receipt_is_exact_durable_and_owner_only(target_dsn):
    mirror_id = f"mir_{uuid4().hex}"
    authority = Authority(uuid4().hex, "resource", 1, "first", 3, 1, "1")
    request = dict(mirror_id=mirror_id, table_identity="catalog-table", history_epoch="initial-history",
                   operation_id="first-operation", expected_authority=None, authority=authority,
                   exclusion_proof="independent-proof", verify_exclusion=lambda *facts: True)
    with psycopg.connect(target_dsn) as connection:
        receipt = bootstrap.prepare_authority(connection, **request)
    with psycopg.connect(target_dsn) as connection:
        assert bootstrap.prepare_authority(connection, **request) == receipt
        assert receipt.startswith("sha256:")
        for changes in ({"history_epoch": "other"}, {"operation_id": "other"},
                        {"table_identity": "other"}, {"authority": replace(authority, runtime_instance_id="other")},
                        {"operation_id": "other", "expected_authority": authority}):
            with pytest.raises(ValueError):
                bootstrap.prepare_authority(connection, **(request | changes))
        with connection.transaction():
            assert connection.execute(
                "SELECT authority, published_generation_id FROM source_mirror_state.mirrors WHERE id = %s",
                (mirror_id,),
            ).fetchone() == (asdict(authority), None)
            assert connection.execute(
                "SELECT count(*) FROM source_mirror_state.generations WHERE mirror_id = %s", (mirror_id,),
            ).fetchone() == (0,)
        replacement = request | {"operation_id": "second-operation", "expected_authority": authority,
                                 "authority": replace(authority, owner_epoch=2, runtime_instance_id="second")}
        with pytest.raises(ValueError):
            bootstrap.prepare_authority(connection, **(replacement | {"verify_exclusion": lambda *facts: False}))
        next_receipt = bootstrap.prepare_authority(connection, **replacement)
        assert next_receipt != receipt
        assert bootstrap.prepare_authority(connection, **replacement) == next_receipt
        with pytest.raises(ValueError):
            bootstrap.prepare_authority(connection, **request)
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        connection.execute("SET SESSION AUTHORIZATION refraq_mirror_applier")
        for relation in ("fence_receipts", "mirrors", "generations"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(sql.SQL("SELECT * FROM source_mirror_state.{}").format(sql.Identifier(relation)))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            bootstrap.prepare_authority(connection, **replacement)
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        connection.execute("SET SESSION AUTHORIZATION refraq_mirror_gateway")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("SELECT source_mirror_state.delivery_metadata('missing')")


@contextmanager
def isolated_database(target_dsn):
    database = "capture_" + uuid4().hex
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        yield psycopg.conninfo.make_conninfo(target_dsn, dbname=database)
    finally:
        with psycopg.connect(target_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


@pytest.fixture
def management_engine(target_dsn):
    with isolated_database(target_dsn) as dsn:
        engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn))
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def native_target(target_dsn):
    with isolated_database(target_dsn) as dsn:
        with psycopg.connect(dsn, autocommit=True) as connection:
            bootstrap.install(connection)
        yield dsn


@contextmanager
def private_gateway(private, dispatch):
    now = utc_now()

    def key_and_certificate(name, issuer=None, ca=False):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        issuer_key, issuer_subject = issuer or (key, subject)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
        if name == "gateway":
            cert = cert.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1"))]), False)
        signed = cert.sign(issuer_key, hashes.SHA256())
        pem = serialization.Encoding.PEM
        return ((key, subject), private(name + ".crt", signed.public_bytes(pem)), private(name + ".key", key.private_bytes(
            pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
        )))

    issuer, ca_file, _ = key_and_certificate("capture-ca", ca=True)
    _, server_cert, server_key = key_and_certificate("gateway", issuer)
    _, cert_file, key_file = key_and_certificate("capture-runtime", issuer)
    errors = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                assert self.connection.getpeercert()["subject"] == ((("commonName", "capture-runtime"),),)
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                response = dispatch(self.path, payload)
                if response is None:
                    return
                body = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                errors.append(exc)
                self.send_error(500)

        def log_message(self, *args):
            return None

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(server_cert, server_key)
        context.load_verify_locations(ca_file)
        context.verify_mode = ssl.CERT_REQUIRED
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        thread.start()
        try:
            yield dict(origin=f"https://127.0.0.1:{server.server_port}", ca_file=ca_file, cert_file=cert_file,
                       key_file=key_file, timeout_seconds=3, max_response_bytes=262144)
        finally:
            server.shutdown()
            thread.join()
            assert not errors, errors


@pytest.mark.integration
@pytest.mark.parametrize("case", ["success", "loss", "bad_incarnation", "bad_key", "bad_metadata", "drift_before_resume",
                                   "withdraw_during_allocation", "takeover", "prefilled_manifest", "history_gate_race",
                                   "wrong_fence", "different_allocation_fence", "wrong_start_offset", "target_key_drift",
                                   "wrong_owner_receipt", "grant_loss", "authority_during_binding", "cross_source_binding",
                                   "target_fence_drift", "withdraw_with_management_timeout"])
def test_protected_executable_prepares_current_open(case, native_target, management, monkeypatch, tmp_path):
    target_dsn = native_target
    transaction, _ = management
    with transaction() as session:
        opened, = publish(session, "native-workflow", 1, ["items"])
    control.reconcile_published_scope(SOURCE)
    mirror_id = opened["mirror_id"]
    profile = dict(source_id=SOURCE, connector_name="cap_one", host="pg.internal", port=5432, database="db",
                   tables=["public.items"], publication="capture_pub", slot="capture_slot", topic_prefix="cap",
                   server_version_num=180000)
    table = dict(partition_identity=dict(runtime_cluster_id="cluster", topic_incarnation_id="incarnation", partition=0),
                 topic="cap.public.items", schema_fingerprint="fingerprint", native_types={"id": "integer", "body": "text"},
                 start_offset=-1, decoder=dict(table_identity="items", database="db", namespace="cap", schema_name="public",
                                              table_name="items", connector_version="3.4.0.Final", key_schema=KEY,
                                              value_schema=SCHEMA))

    def private(name, value):
        path = tmp_path / name
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        path.chmod(0o600)
        return str(path)

    def signed(purpose, authority, scope, operation_id, **extra):
        now = utc_now()
        return jwt.encode(dict(iss="gateway", aud="capture", iat=now, nbf=now, exp=now + timedelta(seconds=60),
                               jti=uuid4().hex, authority=authority, scope=scope, operation_id=operation_id,
                               purpose=purpose, **extra), SIGNING_KEY, algorithm="EdDSA", headers={"kid": "trusted"})

    def target_authority(stamp):
        return Authority(stamp["source_id"], stamp["binding_id"], stamp["owner_epoch"], stamp["runtime_instance_id"],
                         stamp["control_revision"], stamp["credential_revision"], str(stamp["capture_generation"]))

    def owner_request(operation_id, instance):
        with control.source_control_transaction(SOURCE) as (session, _):
            state = control.load_binding(session, SOURCE)
        previous = {key: state[key] for key in control.AUTHORITY_KEYS}
        candidate = dict(previous, owner_epoch=previous["owner_epoch"] + 1, runtime_instance_id=instance,
                         control_revision=previous["control_revision"] + 1)
        scope = dict(profile=profile, published_scope=state["published_scope"])
        return private("owner.json", dict(operation_id=operation_id, signature=signed(
            "owner_allocation", candidate, scope, operation_id, previous_authority=previous,
        )))

    applier_password = uuid4().hex
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("ALTER ROLE refraq_mirror_applier PASSWORD {}").format(sql.Literal(applier_password)))
    restricted = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(
        target_dsn, user="refraq_mirror_applier", password=applier_password, connect_timeout=3,
        options="-c statement_timeout=3000 -c lock_timeout=3000",
    ))
    monkeypatch.setattr(delivery_composition, "applier_engine", lambda settings: restricted)
    monkeypatch.setattr(delivery_composition, "open_delivery", lambda **kwargs: SimpleNamespace(poll_once=lambda: 0, close=lambda: None))
    monkeypatch.setattr(runtime.PostgreSQLCaptureProfile, "configuration", lambda *args: {"fixture": "generated config"})
    attempts, mutations, owner_receipts = [], [], []
    fenced = receipt = installed = None
    running = False

    def withdraw():
        with transaction() as session:
            service.reconcile_references(session, channel_id="native-workflow", channel_version=2, object_ids=[])
        control.reconcile_published_scope(SOURCE)

    if case == "withdraw_with_management_timeout":
        read_open = service._current_open_operation

        def read_open_with_timeout(session, *args):
            if attempts:
                session.execute(text("SET LOCAL statement_timeout = '10ms'"))
                session.execute(text("SELECT pg_sleep(1)"))
            return read_open(session, *args)

        monkeypatch.setattr(service, "_current_open_operation", read_open_with_timeout)

    def dispatch(path, payload):
        nonlocal fenced, receipt
        if path.endswith("owner-allocations"):
            command, scope = payload["command"], payload["scope"]
            authority = {key: command[key] for key in control.AUTHORITY_KEYS}
            operation_id = command["operation_id"]
            TRUST.verify(payload["authorization"], purpose="owner_allocation", authority=authority,
                         scope=scope, operation_id=operation_id)
            candidate = target_authority(authority)
            with psycopg.connect(target_dsn) as connection:
                receipt = bootstrap.prepare_authority(
                    connection, mirror_id=mirror_id, table_identity="items", history_epoch=service.initial_history_epoch(mirror_id),
                    operation_id=operation_id, expected_authority=fenced, authority=candidate,
                    exclusion_proof=(fenced, candidate), verify_exclusion=lambda old, new, evidence: evidence == (old, new),
                )
            fenced = candidate
            owner_receipts.append(receipt)
            observed = allocation_observation(payload)
            observed["target_fence"]["mirror_receipts"] = {
                mirror_id: "sha256:" + "a" * 64 if case == "wrong_owner_receipt" else receipt,
            }
            return {"signature": signed("observation:owner_allocation", authority, scope, operation_id, observation=observed)}
        if path.endswith("observations"):
            command, phase = payload["command"], payload["phase"]
            if phase == "before_start" and case == "history_gate_race":
                with transaction() as session:
                    session.add(service.HistoryGateRow(mirror_id=mirror_id, history_epoch="next-epoch",
                                                      status="invalidating", lower_commit_seq=0, lower_entry_seq=0))
            if phase == "before_resume" and case == "drift_before_resume":
                with psycopg.connect(target_dsn) as connection:
                    connection.execute("UPDATE source_mirror_state.mirrors SET history_epoch = 'drift' WHERE id = %s", (mirror_id,))
            if phase == "before_resume" and case == "target_fence_drift":
                with psycopg.connect(target_dsn) as connection:
                    connection.execute("UPDATE source_mirror_state.fence_receipts SET receipt_ref = %s WHERE mirror_id = %s",
                                       ("sha256:" + "a" * 64, mirror_id))
            observed = observation(command, phase)
            observed.pop("signature")
            return {**observed, "signature": signed("observation:" + phase, observed["authority"], profile,
                                                    command["operation_id"], observation=observed)}
        scope, stamp, operation = payload["scope"], payload["authority"], payload["operation_id"]
        assert target_authority(stamp) == fenced
        assert scope["table"] == table and scope["opened"]["mirror_id"] == mirror_id
        if path.endswith("open-generation-bindings"):
            purpose = "observation:open_generation_binding"
            if case == "bad_incarnation":
                scope = deepcopy(scope)
                scope["table"]["partition_identity"]["topic_incarnation_id"] = "different"
            if case == "bad_key":
                scope = deepcopy(scope)
                scope["table"]["decoder"]["key_schema"]["fields"][0]["optional"] = True
            if case == "cross_source_binding":
                stamp = dict(stamp, source_id="other-source")
            if case == "authority_during_binding":
                with control.source_control_transaction(SOURCE) as (session, source):
                    control.record_source_intent(session, source, replace(source, snapshot_window={"fixture": True}),
                                                 actor_user_id=None, actor_token_id=None)
        else:
            assert path.endswith("generation-allocations")
            purpose = "observation:generation_allocation"
            generation_id = scope["generation_id"]
            binding_scope = {key: value for key, value in scope.items() if key != "generation_id"}
            TRUST.verify(payload["binding_proof"], purpose="observation:open_generation_binding", authority=stamp,
                         scope=binding_scope, operation_id=operation)
            with psycopg.connect(target_dsn) as connection:
                bootstrap.create_generation(
                    connection, mirror_id=mirror_id, operation_id=operation, generation_id=generation_id, authority=fenced,
                    table_identity="items", history_epoch=scope["opened"]["history_epoch"], require_prepared_fence=True,
                    schema_fingerprint="wrong-fingerprint" if case == "bad_metadata" else table["schema_fingerprint"],
                    columns=table["native_types"], key_columns=("id",),
                    start_offset=table["start_offset"] + (case == "wrong_start_offset"),
                    partition_identity=PartitionIdentity(**table["partition_identity"]),
                )
                if case == "target_key_drift":
                    target_table = connection.execute(
                        "SELECT table_name FROM source_mirror_state.generations WHERE id = %s", (generation_id,),
                    ).fetchone()[0]
                    connection.execute(sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}").format(
                        sql.Identifier("source_mirror", target_table), sql.Identifier(target_table + "_pkey"),
                    ))
                if case == "grant_loss" and not attempts:
                    connection.execute("REVOKE EXECUTE ON FUNCTION source_mirror_state.delivery_metadata(text) "
                                       "FROM refraq_mirror_applier")
            attempts.append((operation, generation_id))
            if case in {"withdraw_during_allocation", "withdraw_with_management_timeout"}:
                withdraw()
            if case in {"loss", "takeover"} and len(attempts) == 1:
                return None
        signed_receipt = ("sha256:" + "a" * 64 if case == "wrong_fence"
                          or (case == "different_allocation_fence" and scope.get("generation_id")) else receipt)
        return {"signature": signed(purpose, stamp, scope, operation, fence_receipt=signed_receipt,
                                    verified=True, observed_at=utc_now().isoformat())}

    class Connect:
        def __init__(self, http, name):
            assert name == "cap_one"

        def configured(self, config):
            return installed == config

        def configure(self, config):
            nonlocal installed
            _operation, generation = attempts[-1]
            metadata = delivery_composition.target_metadata(restricted, generation)
            assert metadata["mirror_id"] == mirror_id and metadata["authority"] == asdict(fenced)
            mutations.append("configure")
            installed = config

        def running(self):
            return running

        def resume(self):
            nonlocal running
            mutations.append("resume")
            running = True

        def stopped(self):
            return not running

        def stop(self):
            nonlocal running
            mutations.append("stop")
            running = False

    monkeypatch.setattr(runtime, "ConnectLifecycle", Connect)
    signing_key = private("signing.pem", SIGNING_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    with private_gateway(private, dispatch) as tls:
        manifest = dict(table, generation_id="prefilled") if case == "prefilled_manifest" else table
        entry = dict(source_id=SOURCE, connector_name="cap_one", connect_tls=tls, signals_tls=tls,
                     signing_trust=dict(public_key_files={"trusted": signing_key}, issuer="gateway", audience="capture"),
                     postgresql_profile=dict(scope=profile, tls=dict(sslmode="verify-full", sslrootcert=tls["ca_file"])),
                     readiness_policy=dict(runtime_instance_id="agent-one", max_age_seconds=30, required_checks=CHECKS),
                     credential_files=dict(directory=str(tmp_path), provider_directory="/private/capture"),
                     delivery_settings_file=private("delivery.json", dict(target={}, tables=[manifest], kafka={},
                                                                           group_id="native", limits={}, max_age_seconds=30)),
                     owner_allocation_file=owner_request("first-owner", "agent-one"))
        config = dict(state_directory=str(tmp_path), poll_interval_seconds=1, sources=[entry],
                      management_database_url_file=private("management.url", b"postgresql://fixture/management?sslmode=verify-full"))
        config_file = private("runtime.json", config)
        monkeypatch.setattr("sys.argv", ["runtime", "--config-file", config_file, "--once"])
        contained = case in {"withdraw_during_allocation", "withdraw_with_management_timeout"}
        assert runtime.main() == (0 if case == "success" or contained else 2)
        if case in {"loss", "takeover", "grant_loss"}:
            assert mutations == []
            if case == "grant_loss":
                with psycopg.connect(target_dsn) as connection:
                    connection.execute("GRANT EXECUTE ON FUNCTION source_mirror_state.delivery_metadata(text) "
                                       "TO refraq_mirror_applier")
            if case == "takeover":
                entry["owner_allocation_file"] = owner_request("replacement-owner", "agent-two")
                entry["readiness_policy"]["runtime_instance_id"] = "agent-two"
                private("runtime.json", config)
            assert runtime.main() == 0
            assert len(attempts) == 2
            assert (attempts[0] == attempts[1]) is (case != "takeover")
            if case == "takeover":
                assert len(owner_receipts) == 2
                with restricted.begin() as connection, pytest.raises(Exception, match="MIRROR_CONTROL_CONFLICT"):
                    old_authority = dict(asdict(fenced), owner_epoch=1, runtime_instance_id="agent-one",
                                         control_revision=fenced.control_revision - 1)
                    connection.exec_driver_sql("SELECT source_mirror_state.apply_batch(%s::jsonb,%s,%s::jsonb,'[]'::jsonb)",
                                               (json.dumps(old_authority), attempts[0][1], json.dumps(table["partition_identity"])))
        if case in {"success", "loss", "takeover", "grant_loss"}:
            assert mutations == ["configure", "resume"]
            assert runtime.main() == 0
            withdraw()
            assert runtime.main() == 0
            assert mutations == ["configure", "resume", "stop"]
            assert len(attempts) == (1 if case == "success" else 2)
        elif case in {"drift_before_resume", "target_fence_drift"}:
            assert mutations == ["configure"]
        else:
            assert mutations == []
            before_allocation = {"bad_incarnation", "bad_key", "prefilled_manifest", "wrong_owner_receipt", "wrong_fence",
                                 "authority_during_binding", "cross_source_binding"}
            assert len(attempts) == (0 if case in before_allocation else 1)
            if contained:
                assert control.capture_status(SOURCE)["control"]["stop_ack"] is not None
    with psycopg.connect(target_dsn) as connection:
        assert connection.execute("SELECT published_generation_id FROM source_mirror_state.mirrors WHERE id = %s",
                                  (mirror_id,)).fetchone() == (None,)
        assert set(connection.execute("SELECT id FROM source_mirror_state.generations WHERE mirror_id = %s", (mirror_id,))) == {
            (generation,) for _, generation in attempts
        }
