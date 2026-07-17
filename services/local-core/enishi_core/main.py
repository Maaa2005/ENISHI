"""ENISHI Local Core エントリポイント。

開発時:
    uvicorn enishi_core.main:app --host 127.0.0.1 --port 8765

127.0.0.1 以外で待ち受けてはならない（enishi.md §10）。
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from enishi_core import __version__
from enishi_core.api.routes import health_router, v1_router
from enishi_core.config import get_settings
from enishi_core.database import get_session, init_database
from enishi_core.errors import register_error_handlers
from enishi_core.services.relay_worker import worker_loop as relay_worker_loop
from enishi_core.services.tasks import recover_interrupted_tasks, worker_loop


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
    relay_worker = asyncio.create_task(relay_worker_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        await asyncio.gather(worker, relay_worker)


def create_app() -> FastAPI:
    app = FastAPI(title="ENISHI Local Core", version=__version__, lifespan=lifespan)
    # 発表用Vite UIは別のloopback portからLocal Coreへ接続する。
    # 任意originには開かず、ローカル開発UIのoriginだけを許可する。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(v1_router)
    return app


app = create_app()
