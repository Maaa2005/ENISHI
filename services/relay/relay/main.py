"""Relay Server（enishi.md §25 Relay Serverの責務 v2）。

* 配送のみを行い、本文を改変しない（署名検証は受信ノード側の責務）
* 本人の記憶・秘密鍵を保持しない
* ログは配送メタデータのみとし、本文を残さない
"""

import json
import logging
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from relay import __version__
from relay.config import RelaySettings, get_relay_settings
from relay.metrics import RelayMetrics
from relay.store import MailboxBackend, MailboxStore, SqliteMailboxStore

logger = logging.getLogger("enishi.relay")


class RelayError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def require_agent(authorization: str | None = Header(default=None)) -> str:
    """Bearerトークンを定数時間で照合し、対応するagent_idを返す。"""
    settings = get_relay_settings()
    provided = ""
    if authorization is not None and authorization.startswith("Bearer "):
        provided = authorization.removeprefix("Bearer ")
    agent_id = settings.authenticate(provided)
    if not provided or agent_id is None:
        raise RelayError(
            code="RELAY_UNAUTHORIZED",
            message="Relay認証トークンが不正です。",
            status_code=401,
        )
    return agent_id


def create_app(store: MailboxBackend | None = None) -> FastAPI:
    settings: RelaySettings = get_relay_settings()
    settings.validate_auth_configuration()
    if store is not None:
        mailbox = store
    elif settings.database_path:
        mailbox = SqliteMailboxStore(
            database_path=settings.database_path,
            ttl_seconds=settings.message_ttl_seconds,
            rate_limit_per_minute=settings.rate_limit_per_minute,
        )
    else:
        mailbox = MailboxStore(
            ttl_seconds=settings.message_ttl_seconds,
            rate_limit_per_minute=settings.rate_limit_per_minute,
        )

    app = FastAPI(
        title="ENISHI Relay",
        version=__version__,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.store = mailbox
    app.state.metrics = RelayMetrics()

    @app.exception_handler(RelayError)
    async def handle_relay_error(request: Request, exc: RelayError) -> JSONResponse:
        request.app.state.metrics.rejected(exc.code)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": exc.code, "message": exc.message, "details": exc.details}
            },
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
            "storage": mailbox.backend_name,
            "auth": settings.auth_mode(),
        }

    @app.get("/ready")
    def ready(request: Request) -> JSONResponse:
        try:
            mailbox.check_ready()
        except Exception:
            request.app.state.metrics.readiness_failed()
            logger.exception("relay readiness check failed")
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return JSONResponse(
            content={
                "status": "ready",
                "storage": mailbox.backend_name,
                "auth": settings.auth_mode(),
            }
        )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            app.state.metrics.render(mailbox.pending_count()),
            media_type="text/plain; version=0.0.4",
        )

    @app.post("/v1/messages", status_code=201)
    def post_message(
        envelope: dict[str, Any],
        agent_id: str = Depends(require_agent),
    ) -> dict[str, str]:
        current = get_relay_settings()
        # Relayは本人エージェントIDではなく、認証済み端末ノードを配送主体にする。
        # 旧エンベロープはagent_id=node_idとして受け入れる。
        sender = str(envelope.get("sender_node_id", envelope.get("sender_agent_id", "")))
        receiver = str(
            envelope.get("receiver_node_id", envelope.get("receiver_agent_id", ""))
        )

        if sender != agent_id:
            raise RelayError(
                code="RELAY_UNAUTHORIZED",
                message="認証済みagent_idと送信者が一致しません。",
                status_code=403,
                details={"sender_node_id": sender},
            )
        if receiver not in current.known_agents():
            raise RelayError(
                code="RELAY_UNKNOWN_RECEIVER",
                message="宛先エージェントが登録されていません。",
                status_code=404,
                details={"receiver_node_id": receiver},
            )

        size = len(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
        if size > current.max_message_bytes:
            raise RelayError(
                code="MESSAGE_TOO_LARGE",
                message="メッセージサイズが上限を超えています。",
                status_code=413,
                details={"size": size, "max": current.max_message_bytes},
            )
        if not mailbox.allow_send(sender):
            raise RelayError(
                code="RATE_LIMITED",
                message="レート制限を超過しました。",
                status_code=429,
                details={"sender_agent_id": sender},
            )

        delivery_id = mailbox.put(receiver, envelope)
        app.state.metrics.delivered()
        # ログは配送メタデータのみ。本文（payload/delta）は出力しない（§25）
        logger.info(
            "relay delivered message_id=%s sender=%s receiver=%s size=%d",
            envelope.get("message_id", ""),
            sender,
            receiver,
            size,
        )
        return {"delivery_id": delivery_id}

    @app.get("/v1/messages")
    def get_messages(agent_id: str = Depends(require_agent)) -> list[dict[str, Any]]:
        messages = mailbox.fetch(agent_id)
        app.state.metrics.fetched(len(messages))
        return [
            {
                "delivery_id": m.delivery_id,
                "envelope": m.envelope,
                "stored_at": m.stored_at,
            }
            for m in messages
        ]

    @app.post("/v1/messages/{delivery_id}/ack")
    def ack_message(
        delivery_id: str,
        agent_id: str = Depends(require_agent),
    ) -> dict[str, bool]:
        removed = mailbox.ack(agent_id, delivery_id)
        if not removed:
            raise RelayError(
                code="DELIVERY_NOT_FOUND",
                message="配送IDが見つかりません。",
                status_code=404,
                details={"delivery_id": delivery_id},
            )
        app.state.metrics.acknowledged()
        return {"acknowledged": True}

    return app


app = create_app()
