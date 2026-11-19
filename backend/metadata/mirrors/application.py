"""Runtime SQL adapter: the database function is the sole effects writer."""

from dataclasses import asdict
import json

from sqlalchemy import text

from backend.metadata.mirrors.types import AnchoredProfile, AnchoredScan, Authority, PartitionIdentity, Record


class Application:
    def __init__(self, engine):
        self.engine = engine

    def apply_batch(self, *, authority: Authority, generation_id: str,
                    partition_identity: PartitionIdentity, records: list[Record],
                    anchored_profile: AnchoredProfile | None = None, scan: AnchoredScan | None = None):
        if scan is not None and anchored_profile is None:
            raise ValueError("Anchored scan requires an enrolled profile")
        for record in records:
            if type(record.offset) is not int or record.offset < 0:
                raise ValueError("Invalid delivery offset")
            if record.operation not in {"upsert", "delete", "control", "tombstone"}:
                raise ValueError("Unsupported mirror operation")
            if record.origin not in {"live", "baseline", "recovery"}:
                raise ValueError("Unsupported mirror origin")
        parameters = {"authority": json.dumps(asdict(authority)), "generation": generation_id,
                      "partition": json.dumps(asdict(partition_identity)),
                      "records": json.dumps([asdict(record) for record in records], allow_nan=False)}
        arguments = "CAST(:authority AS jsonb), :generation, CAST(:partition AS jsonb), CAST(:records AS jsonb)"
        if anchored_profile is not None:
            arguments += ", CAST(:profile AS jsonb), CAST(:scan AS jsonb)"
            parameters.update(profile=json.dumps(asdict(anchored_profile)),
                              scan=None if scan is None else json.dumps(asdict(scan)))
        with self.engine.begin() as connection:
            coverage = connection.execute(text(f"SELECT source_mirror_state.apply_batch({arguments})"),
                                          parameters).scalar_one()
        return coverage
