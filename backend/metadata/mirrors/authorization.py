"""Current Source-wide data grants for trusted mirror gateways."""

from backend.admin.role_store import get_role_store
from backend.admin.roles import effective_permissions
from backend.admin.user_store import get_user_store
from backend.metadata import source_access
from backend.metadata.errors import SourceNotFound
from backend.metadata.mirrors.store import MemoryMirrorStore
from backend.metadata.mirrors.errors import MirrorError

__all__ = ["authorize_source_data"]


def authorize_source_data(*, execution_user_id: str, source_id: str | None, session=None) -> None:
    if session is not None and not isinstance(session, MemoryMirrorStore):
        try:
            source_access.authorize_source_read_on(
                session=session, execution_user_id=execution_user_id, source_id=source_id,
            )
        except SourceNotFound:
            raise MirrorError("MIRROR_NOT_FOUND", 404) from None
        return
    user = get_user_store().get_by_id(execution_user_id)
    if user is None or user.status != "active" or user.identity_source == "system":
        raise MirrorError("AUTH_FORBIDDEN", 403)
    role = get_role_store().get_by_id(user.role_id) if user.role_id else None
    if role is None or "sources:data_read" not in effective_permissions(role):
        raise MirrorError("AUTH_FORBIDDEN", 403)
    if source_id is None or source_access.effective_level(user.id, source_id) is None:
        raise MirrorError("MIRROR_NOT_FOUND", 404)
    if "sources:data_read" not in source_access.effective_permissions(user.id, source_id):
        raise MirrorError("AUTH_FORBIDDEN", 403)
