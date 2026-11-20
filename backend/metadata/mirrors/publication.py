"""Guarded target publication and observation of verified evidence."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
import json

from sqlalchemy import text

from backend.metadata.mirrors.service import CommittedOpenPublication, OpenGenerationBinding, OpenPublicationIdentity
from backend.metadata.mirrors.types import Authority


REQUIRED_EVIDENCE = frozenset({
    "operation_id", "generation_id", "table_identity", "capture_generation",
    "schema_fingerprint", "partition_identity", "end_offset", "source_completion",
    "producer_exclusion", "durable_source_checkpoint", "ordered_delivery_proof",
    "key_fingerprint", "empty_table_proof",
})


def persist_verified_certificate(connection, *, operation_id, authority, generation_id,
                                 certificate, verifier):
    """Administrative path only. Verifier checks actual profile-specific evidence, not flags.

    No default verifier exists: lack of a qualified evidence adapter blocks publication.
    The verifier returns its non-secret audit identity after authenticating every proof.
    """
    if not REQUIRED_EVIDENCE <= certificate.keys() or any(certificate[k] is None for k in REQUIRED_EVIDENCE):
        raise ValueError("Incomplete publication certificate")
    if certificate["operation_id"] != operation_id or certificate["generation_id"] != generation_id:
        raise ValueError("Publication operation mismatch")
    verified_by = verifier.verify(authority=authority, certificate=certificate)
    if not isinstance(verified_by, str) or not verified_by:
        raise ValueError("Publication evidence not authenticated")
    with connection.transaction():
        connection.execute("SET LOCAL ROLE refraq_mirror_owner")
        permitted = connection.execute(
            "SELECT generation.capture_generation = %s "
            "AND NOT (generation.capture_generation = ANY(mirror.excluded_capture_generations)) "
            "FROM source_mirror_state.generations generation "
            "JOIN source_mirror_state.mirrors mirror ON mirror.id = generation.mirror_id "
            "WHERE generation.id = %s FOR UPDATE OF mirror",
            (authority.capture_generation, generation_id)).fetchone()
        if permitted != (True,):
            raise ValueError("MIRROR_PUBLICATION_BLOCKED")
        connection.execute(
            "INSERT INTO source_mirror_state.certificates(operation_id, generation_id, authority, evidence, verified_by) "
            "VALUES (%s,%s,%s::jsonb,%s::jsonb,%s) ON CONFLICT DO NOTHING",
            (operation_id, generation_id, json.dumps(asdict(authority)), json.dumps(certificate), verified_by))
        existing = connection.execute(
            "SELECT generation_id, authority, evidence, verified_by FROM source_mirror_state.certificates WHERE operation_id = %s FOR UPDATE",
            (operation_id,)).fetchone()
        if existing != (generation_id, asdict(authority), certificate, verified_by):
            raise ValueError("Contradictory persisted publication certificate")


class Publication:
    def __init__(self, engine, *, timeout_ms: int = 5000):
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("A positive bounded target timeout is required")
        self.engine = engine
        self.timeout_ms = timeout_ms

    def publish_generation(self, *, operation_id: str, authority: Authority,
                           generation_id: str, certificate: dict):
        with self.engine.begin() as connection:
            observed = connection.execute(text(
                "SELECT source_mirror_state.publish_generation(:operation, CAST(:authority AS jsonb), "
                ":generation, CAST(:certificate AS jsonb))"
            ), {"operation": operation_id, "authority": json.dumps(asdict(authority)),
                "generation": generation_id, "certificate": json.dumps(certificate)}).scalar_one()
        return observed

    @contextmanager
    def observe_committed(
        self, *, mirror_id: str, operation_id: str, binding: OpenGenerationBinding,
        expected: OpenPublicationIdentity,
    ) -> Iterator[CommittedOpenPublication]:
        """Hold target publication locks through the caller's Management transaction."""
        if binding.authority != expected.authority or binding.history_epoch != expected.history_epoch:
            raise ValueError("MIRROR_PUBLICATION_BLOCKED")
        with self.engine.connect().execution_options(isolation_level="READ COMMITTED") as connection, connection.begin():
            connection.execute(text("SELECT set_config('statement_timeout', :timeout, true), "
                                    "set_config('lock_timeout', :timeout, true)"), {"timeout": str(self.timeout_ms)})
            observed = connection.execute(text(
                "SELECT source_mirror_state.observe_committed_publication(:mirror, :operation, :generation, "
                "CAST(:authority AS jsonb), :epoch)"
            ), {"mirror": mirror_id, "operation": operation_id, "generation": expected.generation_id,
                "authority": json.dumps(asdict(expected.authority)), "epoch": expected.history_epoch}).scalar_one()
            yield CommittedOpenPublication(**observed)
