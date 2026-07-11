"""TwinLink Local Core エントリポイント。

開発時:
    uvicorn twinlink_core.main:app --host 127.0.0.1 --port 8765

127.0.0.1 以外で待ち受けてはならない（twinlink.md §10）。
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from twinlink_core import __version__
from twinlink_core.api.routes import health_router, v1_router
from twinlink_core.config import get_settings
from twinlink_core.database import get_session, init_database
from twinlink_core.errors import register_error_handlers
from twinlink_core.services.tasks import recover_interrupted_tasks, worker_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.ensure_directories()
    init_database()
    session = next(get_session())
    try:
        recover_interrupted_tasks(session)
    finally:
        session.close()

    stop_event = asyncio.Event()
    worker = asyncio.create_task(worker_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await worker


def create_app() -> FastAPI:
    app = FastAPI(title="TwinLink Local Core", version=__version__, lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    return app


app = create_app()
