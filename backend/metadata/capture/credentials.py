"""Revision-scoped FileConfigProvider material, never connector plaintext."""

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from backend.core.secrets import decrypt_secret
from backend.metadata.capture.runtime_store import PROTECTED_FORBIDDEN_BITS, RuntimeBlocked, protected_read


def property_value(value):
    return "".join("\\u%04x" % unit for unit in (
        int.from_bytes(value.encode("utf-16-be")[i:i + 2], "big")
        for i in range(0, len(value.encode("utf-16-be")), 2)))


class CredentialFiles:
    def __init__(self, directory, *, provider_directory):
        self.directory = Path(directory)
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & PROTECTED_FORBIDDEN_BITS or not provider_directory.startswith("/")
                or any(c in provider_directory for c in ":${}\n\r")):
            raise RuntimeBlocked("private_credential_directory_required")
        self.provider_directory = provider_directory.rstrip("/")

    def install(self, command, source):
        if (source.capture_revision != command["credential_revision"]
                or not source.capture_credential_ciphertext):
            raise RuntimeBlocked("credential_revision_mismatch")
        try:
            secret = json.loads(decrypt_secret(source.capture_credential_ciphertext))
            if (set(secret) != {"username", "password"}
                    or any(not isinstance(v, str) or not v for v in secret.values())):
                raise ValueError()
            content = "".join(k + "=" + property_value(v) + "\n" for k, v in secret.items()).encode()
        except Exception:
            raise RuntimeBlocked("credential_unavailable") from None
        prefix = hashlib.sha256(command["source_id"].encode()).hexdigest() + "-"
        name = prefix + str(command["credential_revision"]) + ".properties"
        path = self.directory / name
        if path.exists():
            if protected_read(path) != content:
                raise RuntimeBlocked("credential_revision_conflict")
        else:
            fd, temporary = tempfile.mkstemp(dir=self.directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        self.revoke(command, keep=name)
        return {key: "${file:" + self.provider_directory + "/" + name + ":" + key + "}"
                for key in ("username", "password")}

    def revoke(self, command, *, keep=None):
        prefix = hashlib.sha256(command["source_id"].encode()).hexdigest() + "-"
        for path in self.directory.glob(prefix + "*.properties"):
            if path.name != keep:
                protected_read(path)
                path.unlink()
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
