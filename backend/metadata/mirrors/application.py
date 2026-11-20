"""Runtime SQL adapter: the database function is the sole effects writer."""

from dataclasses import asdict
import json

from sqlalchemy import text

from backend.metadata.mirrors.publication import REQUIRED_EVIDENCE
from backend.metadata.mirrors.types import AnchoredProfile, AnchoredScan, Authority, PartitionIdentity, Record


def encode_resume(resume: dict, anchored_profile: AnchoredProfile | None) -> str:
    if (not isinstance(anchored_profile, AnchoredProfile)
            or anchored_profile.kind != "disposable_read_committed_v1"
            or type(anchored_profile.leader_epoch) is not int or anchored_profile.leader_epoch < 0):
        raise ValueError("Resume requires an enrolled anchored profile")
    if (not isinstance(resume, dict) or resume.keys() != {"certificate", "history_epoch"}
            or not isinstance(resume["history_epoch"], str) or not resume["history_epoch"]):
        raise ValueError("Invalid resume evidence")
    certificate = resume["certificate"]
    if (not isinstance(certificate, dict) or not REQUIRED_EVIDENCE <= certificate.keys()
            or any(certificate[key] is None for key in REQUIRED_EVIDENCE)
            or not isinstance(certificate["ordered_delivery_proof"], dict)
            or not isinstance(certificate["partition_identity"], dict)
            or type(certificate["end_offset"]) is not int):
        raise ValueError("Invalid resume certificate")
    try:
        return json.dumps(resume, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Invalid resume evidence JSON") from None


class Application:
    def __init__(self, engine):
        self.engine = engine

    def apply_batch(self, *, authority: Authority, generation_id: str,
                    partition_identity: PartitionIdentity, records: list[Record],
                    anchored_profile: AnchoredProfile | None = None, scan: AnchoredScan | None = None,
                    resume: dict | None = None):
        if scan is not None and anchored_profile is None:
            raise ValueError("Anchored scan requires an enrolled profile")
        if resume is not None and (type(scan) is not AnchoredScan or not records):
            raise ValueError("Resume requires a nonempty unsealed anchored scan")
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
        if resume is not None:
            arguments += ", CAST(:resume AS jsonb)"
            parameters["resume"] = encode_resume(resume, anchored_profile)
        with self.engine.begin() as connection:
            coverage = connection.execute(text(f"SELECT source_mirror_state.apply_batch({arguments})"),
                                          parameters).scalar_one()
        return coverage
