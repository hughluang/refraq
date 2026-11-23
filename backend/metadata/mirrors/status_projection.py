"""Update the indexed lifecycle projection with its management evidence."""

from collections import defaultdict

from sqlalchemy import select

from backend.metadata.mirrors.lifecycle import dispatch_scope, open_evidence, registry_scope
from backend.metadata.mirrors.models import MirrorOperationRow, MirrorRow
from backend.metadata.models import SourceCaptureBindingRow


def pending_opens(session, mirror_ids):
    commands = MirrorOperationRow.command
    operations = defaultdict(list)
    if mirror_ids:
        query = select(MirrorOperationRow.mirror_id, commands).where(
            MirrorOperationRow.mirror_id.in_(mirror_ids),
            commands["kind"].as_string() == "open", commands["state"].as_string() == "pending",
        )
        for mirror_id, command in session.execute(query):
            operations[mirror_id].append(command)
    return operations


def refresh_source_status(session, source_id):
    mirrors = session.scalars(select(MirrorRow).where(MirrorRow.source_id == source_id)).all()
    if not mirrors:
        return
    operations = pending_opens(session, [row.id for row in mirrors])
    binding = session.get(SourceCaptureBindingRow, source_id)
    state = binding.state if binding else {}
    desired = registry_scope(row.state for row in mirrors)
    scope = dispatch_scope(desired, state, operations)
    for row in mirrors:
        status = open_evidence(row.state, operations[row.id], state, scope).status
        if row.effective_status != status:
            row.effective_status = status
    session.flush()
