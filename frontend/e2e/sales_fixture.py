"""In-memory Source Mirror registry for the sales Catalog browser fixture."""

from contextlib import asynccontextmanager

from backend.main import app
from backend.metadata.mirrors.service import bind_management
from backend.metadata.mirrors.store import MemoryMirrorStore


def install():
    store = MemoryMirrorStore()
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with original(instance):
            bind_management(store=store)
            try:
                yield
            finally:
                bind_management()

    app.router.lifespan_context = lifespan
