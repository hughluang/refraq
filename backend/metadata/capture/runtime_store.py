"""Local durable execution journal and host-local Source exclusion."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat


# Group and other permission bits are refused. The mode itself is not a fixed value.
PROTECTED_FORBIDDEN_BITS = 0o077

# Only these operator-actionable codes may cross the process diagnostics boundary.
# Driver responses, evidence, and unrecognized exception text stay private.
REPORTED_FAULTS = frozenset({
    "conflicting_owner_request_files", "replacement_owner_blocked", "owner_allocation_blocked",
    "owner_assignment_unproven", "replacement_owner_requires_recovery", "published_scope_changed",
    "source_executor_busy", "capture_evidence_rejected", "capture_delivery_blocked",
    "open_generation_preparation_blocked", "capture_preparation_management_unconfirmed",
    "capture_snapshot_management_unconfirmed", "incremental_snapshot_blocked",
    "configuration_outcome_uncertain", "resume_outcome_uncertain", "stop_outcome_uncertain",
    "readiness_unknown_or_failed", "retained_position_resume_driver_required",
})


class RuntimeBlocked(Exception):
    """A safe runtime fault code, never an external response or credential."""


class TablePrerequisiteFailed(RuntimeBlocked):
    """One table's schema or permission prerequisite is observed failing (not merely unknown)."""

    def __init__(self, table, cause, code):
        super().__init__(code)
        self.table = table
        self.cause = cause


def protected_read(path, *, limit=1048576):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & PROTECTED_FORBIDDEN_BITS
            or info.st_nlink != 1
            or info.st_size > limit
        ):
            raise RuntimeBlocked("protected_file_required")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise RuntimeBlocked("protected_file_too_large")
        return data


def protected_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise RuntimeBlocked("protected_json_invalid")
            result[key] = value
        return result

    def invalid(value):
        raise RuntimeBlocked("protected_json_invalid")

    return json.loads(protected_read(path), object_pairs_hook=pairs, parse_constant=invalid)


class CommandJournal:
    def __init__(self, directory):
        self.directory = Path(directory)
        info = self.directory.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & PROTECTED_FORBIDDEN_BITS
        ):
            raise RuntimeBlocked("private_state_directory_required")
        path = self.directory / "commands.sqlite3"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        protected_read(path, limit=1073741824)
        self.db = sqlite3.connect(path, timeout=1)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS commands "
            "(operation_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
            "command TEXT NOT NULL, state TEXT NOT NULL)"
        )
        self.db.commit()

    def close(self):
        self.db.close()

    @contextmanager
    def source_lock(self, source_id):
        name = hashlib.sha256(source_id.encode()).hexdigest() + ".lock"
        fd = os.open(self.directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeBlocked("source_executor_busy") from None
            yield
        finally:
            os.close(fd)

    def accept(self, command):
        encoded = json.dumps(command, sort_keys=True, separators=(",", ":"))
        row = self.db.execute(
            "SELECT command, state FROM commands WHERE operation_id = ?",
            (command["operation_id"],),
        ).fetchone()
        if row and row[0] != encoded:
            raise RuntimeBlocked("operation_identity_conflict")
        for (previous,) in self.db.execute(
            "SELECT command FROM commands WHERE source_id = ?", (command["source_id"],)
        ):
            old = json.loads(previous)
            if old["binding_id"] != command["binding_id"] or any(
                command[key] < old[key]
                for key in ("owner_epoch", "capture_generation", "control_revision", "credential_revision")
            ):
                raise RuntimeBlocked("stale_authority")
            if (old["owner_epoch"] == command["owner_epoch"]
                    and old["runtime_instance_id"] != command["runtime_instance_id"]):
                raise RuntimeBlocked("owner_identity_conflict")
            if old["control_revision"] == command["control_revision"] and old != command:
                raise RuntimeBlocked("revision_identity_conflict")
        if row:
            return row[1]
        with self.db:
            self.db.execute(
                "INSERT INTO commands VALUES (?, ?, ?, 'pending')",
                (command["operation_id"], command["source_id"], encoded),
            )
        return "pending"

    def mark(self, command, state):
        if state not in {"uncertain", "resume_uncertain", "observed", "applied"}:
            raise RuntimeBlocked("invalid_journal_transition")
        with self.db:
            self.db.execute(
                "UPDATE commands SET state = ? WHERE operation_id = ?",
                (state, command["operation_id"]),
            )
