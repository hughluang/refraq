"""Memory capture target for the browser test. Channel execution and output use production stores."""

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends

from backend.admin.deps import require_permission
from backend.channel.channel_run import set_dispatcher
from backend.channel.mirror_reads import bind_reads
from backend.channel.runner import run_channel_job
from backend.channel import runner
from backend.channel.store import get_channel_store
from backend.main import app
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.service import bind_management, bind_source_read_authorizer
from backend.metadata.mirrors.store import MemoryMirrorStore
from backend.metadata.mirrors.types import Pin
from backend.metadata.source_access import allows
from backend.admin.errors import AuthForbidden


def authorize(*, execution_user_id, source_id, session=None):
    if not allows(execution_user_id, source_id, "sources:data_read"):
        raise AuthForbidden()


class SalesReads(Reads):
    def __init__(self, store):
        self.store = store
        self.amounts = {}

    def acquire_pin(self, *, run_id, mirror_id, execution_user_id):
        mirror = self.store.mirrors[mirror_id]
        authorize(execution_user_id=execution_user_id, source_id=mirror["source_id"])
        return Pin(run_id, mirror_id, mirror["published_generation_id"], mirror["source_id"])

    def read_page(self, *, pin, execution_user_id, after_key, limit):
        authorize(execution_user_id=execution_user_id, source_id=pin.source_id)
        return dict(rows=[{"order_key": "ORD-104", "amount": self.amounts[pin.generation_id]}],
                    freshness={"status": "unknown"}, next_key=None, source_ids=[pin.source_id],
                    generation_id=pin.generation_id)

    def release_run_pins(self, *, run_id, terminal_proof):
        pass


def install():
    store = MemoryMirrorStore()
    reads = SalesReads(store)
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with original(instance):
            bind_management(store=store)
            bind_reads(reads)
            bind_source_read_authorizer(authorize)
            channels = get_channel_store()
            publish = channels.publish_version

            def publish_with_memory_transaction(channel_id, *, after=None, **fields):
                with store.transaction() as session:
                    callback = (lambda _, version, previous: after(session, version, previous)) if after else None
                    return publish(channel_id, after=callback, **fields)

            channels.publish_version = publish_with_memory_transaction
            sql_scope = runner.session_scope
            runner.session_scope = store.transaction
            previous = set_dispatcher(run_channel_job)
            try:
                yield
            finally:
                runner.session_scope = sql_scope
                channels.publish_version = publish
                set_dispatcher(previous)
                bind_management()

    app.router.lifespan_context = lifespan

    @app.post("/e2e/sales/{mirror_id}/copy", dependencies=[Depends(require_permission("mirror:write"))])
    def publish_fixture_copy(mirror_id: str, amount: Literal["24.60", "26.75"]):
        with store.transaction() as session:
            mirror = store.mirrors[mirror_id]
            assert mirror["source_id"] in ("src_sales-en", "src_sales-zh")
            generation = f"fixture-{mirror_id}-{amount}"
            reads.amounts[generation] = amount
            mirror.update(published_generation_id=generation, status="unknown")
            for operation in store.operations.values():
                if operation["mirror_id"] == mirror_id:
                    operation["state"] = "applied"
            store.save(session, mirror)
        return {"amount": amount}
