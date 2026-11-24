"""Authorized gateway over durable target-side run pins and keyset pages."""

import json

from sqlalchemy import text

from backend.metadata.mirrors.errors import MirrorError
from backend.metadata.mirrors.types import Pin


class Reads:
    def __init__(self, engine, *, authorize_source_read, verify_terminal_proof):
        self.engine = engine
        self.authorize_source_read = authorize_source_read
        self.verify_terminal_proof = verify_terminal_proof

    def _authorize(self, connection, mirror_id, execution_user_id):
        source = connection.execute(text("SELECT source_mirror_state.resolve_source(:mirror)"),
                                    {"mirror": mirror_id}).scalar_one()
        # The adapter must raise for missing bindings, inactive users or missing grants.
        self.authorize_source_read(execution_user_id=execution_user_id, source_id=source)
        return source

    def acquire_pin(self, *, run_id, mirror_id, execution_user_id):
        with self.engine.begin() as connection:
            self._authorize(connection, mirror_id, execution_user_id)
            value = connection.execute(text("SELECT source_mirror_state.acquire_pin(:run, :mirror)"),
                                       {"run": run_id, "mirror": mirror_id}).scalar_one()
        return Pin(**value)

    def read_page(self, *, pin: Pin, execution_user_id, after_key, limit):
        with self.engine.begin() as connection:
            source = self._authorize(connection, pin.mirror_id, execution_user_id)
            value = connection.execute(text(
                "SELECT source_mirror_state.read_page(:run, :mirror, CAST(:after AS jsonb), :limit)"
            ), {"run": pin.run_id, "mirror": pin.mirror_id,
                "after": None if after_key is None else json.dumps(after_key), "limit": limit}).scalar_one()
            if value["generation_id"] != pin.generation_id:
                raise ValueError("Mirror pin identity mismatch")
            value["source_ids"] = [source]
        return value

    def release_run_pins(self, *, run_id, terminal_proof):
        # Release requires proof that the reader is terminal and cannot resume.
        result = self.verify_terminal_proof(run_id=run_id, terminal_proof=terminal_proof)
        if result is not None:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
        with self.engine.begin() as connection:
            connection.execute(text("SELECT source_mirror_state.release_run_pins(:run)"), {"run": run_id})
