"""Process-local assembly of restricted Channel mirror reads."""

from contextlib import contextmanager

from backend.channel.mirror_reads import bind_reads, validate_terminal_proof
from backend.core.config import get_settings
from backend.core.db import get_session_factory
from backend.metadata.mirrors.composition import compose_mirrors
from backend.metadata.mirrors.history import History, bind_history
from backend.metadata.mirrors.service import bind_source_read_authorizer
from backend.metadata.mirrors.authorization import authorize_source_data


@contextmanager
def channel_mirror_runtime():
    bind_history(None)
    bind_reads(None)
    bind_source_read_authorizer(authorize_source_data)
    adapters = None
    try:
        adapters = compose_mirrors(get_settings(), verify_terminal_proof=validate_terminal_proof)
        if adapters is not None:
            bind_history(History(session_factory=get_session_factory(), target=adapters.history_target))
            bind_reads(adapters.reads)
        yield
    finally:
        bind_history(None)
        bind_reads(None)
        bind_source_read_authorizer(None)
        if adapters is not None:
            adapters.close()
