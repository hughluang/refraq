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
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
import jwt
import psycopg
from psycopg import sql
import pytest
from sqlalchemy import create_engine, text

from backend.core.time import utc_now
from backend.core.secrets import encrypt_secret
from backend.metadata.capture import control, delivery_composition, runtime
from backend.metadata.capture.postgresql import PostgreSQLCaptureProfile
from backend.metadata.capture.runtime_store import RuntimeBlocked
from backend.metadata.models import SourceRow
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


@pytest.fixture
def snapshot_source(target_dsn):
    with isolated_database(target_dsn) as dsn:
        connector, observer = (f"snapshot_{uuid4().hex}" for _ in range(2))
        with psycopg.connect(dsn) as connection:
            version, wal = connection.execute("SELECT current_setting('server_version_num'), "
                                              "current_setting('wal_level')").fetchone()
            assert (version, wal) == ("180006", "logical"), (
                "Snapshot preparation requires PostgreSQL 18.6 started with -c wal_level=logical"
            )
            connection.execute("CREATE TABLE public.items (id integer PRIMARY KEY, body text)")
            connection.execute("CREATE TABLE public.snapshot_signal ("
                               "id varchar(64) PRIMARY KEY, type varchar(32), data varchar(2048))")
            connection.execute("CREATE PUBLICATION capture_pub FOR TABLE public.items, public.snapshot_signal")
            for role, permissions in ((connector, "SELECT, INSERT"), (observer, "SELECT")):
                connection.execute(sql.SQL("CREATE ROLE {} {}").format(
                    sql.Identifier(role), sql.SQL("REPLICATION" if role == connector else "NOREPLICATION"),
                ))
                connection.execute(sql.SQL("GRANT {} ON public.snapshot_signal TO {}").format(
                    sql.SQL(permissions), sql.Identifier(role),
                ))
            connection.execute(sql.SQL("GRANT SELECT ON public.items TO {}").format(sql.Identifier(connector)))
            relation, = connection.execute("SELECT oid || ':' || 'public.snapshot_signal'::regclass::oid "
                                           "FROM pg_database WHERE datname = current_database()").fetchone()
        try:
            yield dsn, connector, observer, relation
        finally:
            with psycopg.connect(dsn) as connection:
                for role in (connector, observer):
                    connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                    connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


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
                                   "target_fence_drift", "withdraw_with_management_timeout",
                                   "snapshot_loss", "snapshot_wrong_table", "snapshot_wrong_signer",
                                   "snapshot_wrong_incarnation", "snapshot_replaced_relation", "snapshot_replacement_epoch"])
def test_protected_executable_prepares_current_open(case, native_target, management, monkeypatch, tmp_path, request):
    target_dsn = native_target
    transaction, _ = management
    with transaction() as session:
        opened, = publish(session, "native-workflow", 1, ["items"])
    control.reconcile_published_scope(SOURCE)
    mirror_id = opened["mirror_id"]
    history_epoch = service.initial_history_epoch(mirror_id)
    if case == "snapshot_replacement_epoch":
        history_epoch = uuid4().hex
        with transaction() as session:
            session.add(service.HistoryGateRow(mirror_id=mirror_id, history_epoch=history_epoch, status="available",
                                               lower_commit_seq=0, lower_entry_seq=0))
        snapshot_faults = []
        recheck = runtime.CaptureRuntime.recheck_snapshot

        def record_snapshot_fault(capture, binding, *, session, source):
            try:
                return recheck(capture, binding, session=session, source=source)
            except RuntimeBlocked as error:
                snapshot_faults.append((binding.history_epoch, str(error)))
                raise

        monkeypatch.setattr(runtime.CaptureRuntime, "recheck_snapshot", record_snapshot_fault)
    profile = dict(source_id=SOURCE, connector_name="cap_one", host="pg.internal", port=5432, database="db",
                   tables=["public.items"], publication="capture_pub", slot="capture_slot", topic_prefix="cap",
                   server_version_num=180000)
    table = dict(partition_identity=dict(runtime_cluster_id="cluster", topic_incarnation_id="incarnation", partition=0),
                 topic="cap.public.items", schema_fingerprint="fingerprint", native_types={"id": "integer", "body": "text"},
                 start_offset=-1, decoder=dict(table_identity="items", database="db", namespace="cap", schema_name="public",
                                              table_name="items", connector_version="3.4.0.Final", key_schema=KEY,
                                              value_schema=SCHEMA))

    snapshots = case.startswith("snapshot_")
    if snapshots:
        source_dsn, connector_role, receipt_role, relation = request.getfixturevalue("snapshot_source")
        database = psycopg.conninfo.conninfo_to_dict(source_dsn)["dbname"]
        profile["database"] = table["decoder"]["database"] = database
        with transaction() as session:
            session.get(SourceRow, SOURCE).access_ciphertext = encrypt_secret(json.dumps(
                dict(host="pg.internal", port=5432, database=database, schema="public"),
            ))
        profile["server_version_num"] = 180006
        profile["snapshot"] = dict(signal_table="public.snapshot_signal", signal_relation_identity=relation,
                                   notification_topic="cap.notifications", notification_partition={
                                       "runtime_cluster_id": "cluster", "topic_incarnation_id": "notifications", "partition": 0,
                                   })
        table["decoder"]["connector_version"] = "3.7.1.Final"
        snapshot_keys = {role: Ed25519PrivateKey.generate() for role in ("receipt", "notification")}
        submissions, snapshot_reads = [], []
        receipt_checks = []

    def private(name, value):
        path = tmp_path / name
        path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
        path.chmod(0o600)
        return str(path)

    def signed(purpose, authority, scope, operation_id, *, role=None, **extra):
        now = utc_now()
        return jwt.encode(dict(iss=role or "gateway", aud="capture", iat=now, nbf=now, exp=now + timedelta(seconds=60),
                               jti=uuid4().hex, authority=authority, scope=scope, operation_id=operation_id,
                               purpose=purpose, **extra), snapshot_keys[role] if role else SIGNING_KEY,
                          algorithm="EdDSA", headers={"kid": "trusted"})

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
    if snapshots:
        def source_connection(**options):
            assert options["sslmode"] == "verify-full" and options["host"] == "pg.internal"
            connection = psycopg.connect(source_dsn, connect_timeout=3,
                                         options="-c statement_timeout=3000 -c lock_timeout=3000")
            connection.execute(sql.SQL("SET SESSION AUTHORIZATION {}").format(sql.Identifier(connector_role)))
            return connection

        monkeypatch.setattr(runtime, "PostgreSQLCaptureProfile", lambda **options: PostgreSQLCaptureProfile(
            **options, connect=source_connection,
        ))
    else:
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
        if path.startswith("/v1/capture/snapshots/"):
            assert snapshots and running
            step = path.rsplit("/", 1)[-1]
            scope, operation = payload["scope"], payload["operation_id"]
            stamp = scope["authority"]
            assert stamp == asdict(fenced) and scope["generation_id"] == attempts[-1][1]
            assert scope["allocation_operation_id"] == attempts[-1][0] and scope["mirror_id"] == mirror_id
            expected_snapshot = profile["snapshot"]
            assert all(scope[key] == value for key, value in expected_snapshot.items())
            assert scope["connector_name"] == "cap" and scope["qualified_table"] == "public.items"
            if step == "submit":
                signal = payload["signal"]
                assert signal == {"id": operation, "type": "execute-snapshot",
                                  "data": {"type": "incremental", "data-collections": [r"public\.items"]}}
                with transaction() as session:
                    ledger = control.load_binding(session, SOURCE)["incremental_snapshots"]
                    pending = ledger["generations"][scope["generation_id"]]
                    assert pending["id"] == operation and pending["state"] == "submission_uncertain"
                with psycopg.connect(source_dsn) as connection:
                    assert connection.execute("INSERT INTO public.snapshot_signal VALUES (%s, %s, %s) "
                                              "ON CONFLICT (id) DO NOTHING RETURNING id",
                                              (operation, signal["type"], json.dumps(signal["data"]))).fetchone() == (operation,)
                submissions.append(operation)
                return None
            snapshot_reads.append(step)
            if step == "receipt":
                receipt_checks.append(operation)
                with psycopg.connect(source_dsn) as connection:
                    connection.execute(sql.SQL("SET SESSION AUTHORIZATION {}").format(sql.Identifier(receipt_role)))
                    row = connection.execute("SELECT id, type, data FROM public.snapshot_signal WHERE id = %s",
                                             (operation,)).fetchone()
                assert row is not None
                return {"signature": signed("snapshot:receipt", stamp, scope, operation, role="receipt",
                                            evidence=dict(id=row[0], type=row[1], data=json.loads(row[2])))}
            if step == "baseline":
                assert not submissions
                return {"signature": signed("snapshot:baseline", stamp, scope, operation, role="notification",
                                            challenge=payload["challenge"],
                                            evidence=dict(offset=9, idle=True, exclusive=True))}
            assert step == "notifications" and payload["offset"] == 9
            now_ms = int(utc_now().timestamp() * 1000)
            records = [{"offset": offset, "key": {"id": operation}, "value": {
                "id": operation, "aggregate_type": "Incremental Snapshot", "type": kind, "timestamp": now_ms,
                "additional_data": {"connector_name": "cap"} | facts,
            }} for offset, kind, facts in (
                (9, "STARTED", dict(data_collections="public.items")),
                (10, "DATA_COLLECTIONS_RESOLVED", dict(data_collections="public.items")),
                (11, "TABLE_SCAN_COMPLETED", dict(scanned_collection="public.other" if case == "snapshot_wrong_table"
                                                  else "public.items", status="EMPTY", total_rows_scanned="0")),
                (12, "COMPLETED", {}),
            )]
            if case == "snapshot_wrong_incarnation":
                scope["notification_partition"]["topic_incarnation_id"] = "foreign-topic"
            return {"signature": signed("snapshot:notifications", stamp, scope, operation,
                                        role="receipt" if case == "snapshot_wrong_signer" else "notification",
                                        challenge=payload["challenge"], evidence=dict(start=9, end=13, high_water=13,
                                                                                     exclusive=True, records=records))}
        if path.endswith("owner-allocations"):
            command, scope = payload["command"], payload["scope"]
            authority = {key: command[key] for key in control.AUTHORITY_KEYS}
            operation_id = command["operation_id"]
            TRUST.verify(payload["authorization"], purpose="owner_allocation", authority=authority,
                         scope=scope, operation_id=operation_id)
            candidate = target_authority(authority)
            with psycopg.connect(target_dsn) as connection:
                receipt = bootstrap.prepare_authority(
                    connection, mirror_id=mirror_id, table_identity="items", history_epoch=history_epoch,
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
            if snapshots:
                assert config["table.include.list"] == r"public\.items,public\.snapshot_signal"
                assert config["signal.data.collection"] == "public.snapshot_signal"
                assert config["signal.enabled.channels"] == "source"
                assert config["incremental.snapshot.watermarking.strategy"] == "insert_insert"
                assert config["notification.enabled.channels"] == "sink"
                assert config["notification.sink.topic.name"] == "cap.notifications"
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
        if snapshots:
            def observer_configuration(role):
                key_file = private(f"{role}.pem", snapshot_keys[role].public_key().public_bytes(
                    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
                ))
                return dict(tls=tls, signing_trust=dict(public_key_files={"trusted": key_file}, issuer=role,
                                                       audience="capture"))

            entry["snapshot_observers"] = dict(receipt=observer_configuration("receipt"),
                                               notification=observer_configuration("notification"), max_age_seconds=30)
        config = dict(state_directory=str(tmp_path), poll_interval_seconds=1, sources=[entry],
                      management_database_url_file=private("management.url", b"postgresql://fixture/management?sslmode=verify-full"))
        config_file = private("runtime.json", config)
        monkeypatch.setattr("sys.argv", ["runtime", "--config-file", config_file, "--once"])
        contained = case in {"withdraw_during_allocation", "withdraw_with_management_timeout"}
        if case == "snapshot_replacement_epoch":
            assert runtime.main() == 2
            assert mutations == ["configure", "resume"]
            assert snapshot_faults == [(history_epoch, "snapshot_replacement_allocation_unconfirmed")]
            assert snapshot_reads == submissions == []
            with transaction() as session:
                assert "incremental_snapshots" not in control.load_binding(session, SOURCE)
        elif snapshots:
            assert runtime.main() == 0
            assert mutations == ["configure", "resume"] and len(submissions) == 1
            entry.pop("owner_allocation_file")
            private("runtime.json", config)
            if case == "snapshot_replaced_relation":
                with psycopg.connect(source_dsn) as connection:
                    connection.execute("ALTER TABLE public.snapshot_signal RENAME TO replaced_signal")
                    connection.execute("CREATE TABLE public.snapshot_signal (LIKE public.replaced_signal INCLUDING ALL)")
                    connection.execute(sql.SQL("GRANT SELECT, INSERT ON public.snapshot_signal TO {}").format(
                        sql.Identifier(connector_role),
                    ))
                    connection.execute("ALTER PUBLICATION capture_pub SET TABLE public.items, public.snapshot_signal")
            assert runtime.main() == (0 if case == "snapshot_loss" else 2)
            with transaction() as session:
                result = control.load_binding(session, SOURCE)["incremental_snapshots"]["generations"][attempts[-1][1]]
                assert result["id"] == submissions[0]
                assert result["state"] == ("catching_up" if case == "snapshot_loss" else
                                           "blocked" if case == "snapshot_wrong_table" else "submission_uncertain")
            assert "incremental_snapshots" not in control.capture_status(SOURCE)["control"]
            assert receipt_checks == ([] if case == "snapshot_replaced_relation" else submissions)
            with psycopg.connect(source_dsn) as connection:
                relation_name = "replaced_signal" if case == "snapshot_replaced_relation" else "snapshot_signal"
                assert connection.execute(sql.SQL("SELECT id FROM public.{}").format(sql.Identifier(relation_name))).fetchall() == [
                    (submissions[0],),
                ]
            reads_before_stop = list(snapshot_reads)
            withdraw()
            assert runtime.main() == 0
            assert mutations == ["configure", "resume", "stop"] and snapshot_reads == reads_before_stop
            assert control.capture_status(SOURCE)["control"]["stop_ack"] is not None
        else:
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
        if snapshots:
            assert len(attempts) == 1
        elif case in {"success", "loss", "takeover", "grant_loss"}:
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
