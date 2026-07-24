"""Relay Server（enishi.md §25 Relay Serverの責務 v2）。

* 配送のみを行い、本文を改変しない（署名検証は受信ノード側の責務）
* 本人の記憶・秘密鍵を保持しない
* ログは配送メタデータのみとし、本文を残さない
"""

import json
import logging
import math
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from relay import __version__
from relay.config import RelaySettings, get_relay_settings
from relay.metrics import RelayMetrics
from relay.store import (
    MailboxBackend,
    MailboxCapacityExceeded,
    MailboxStore,
    SqliteMailboxStore,
)

logger = logging.getLogger("enishi.relay")


class InvalidJsonEnvelope(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidJsonEnvelope("duplicate key")
        result[key] = value
    return result


def _reject_non_finite_constant(_value: str) -> None:
    raise InvalidJsonEnvelope("non-finite number")


class RelayEnvelope(BaseModel):
    """Relayが配送に必要なwire項目だけを受け入れる制限付きモデル。"""

    model_config = ConfigDict(extra="forbid")

    protocol: str = Field(min_length=1, max_length=32)
    message_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    sender_agent_id: str = Field(min_length=1, max_length=256)
    receiver_agent_id: str = Field(min_length=1, max_length=256)
    sender_node_id: str | None = Field(default=None, min_length=1, max_length=256)
    receiver_node_id: str | None = Field(default=None, min_length=1, max_length=256)
    message_type: str = Field(min_length=1, max_length=64)
    intent: str = Field(min_length=1, max_length=256)
    session_version: int = Field(ge=1, strict=True)
    sequence: int = Field(ge=1, strict=True)
    payload: dict[str, Any]
    delta: dict[str, Any]
    requires_human_approval: bool
    nonce: str = Field(min_length=1, max_length=256)
    created_at: str = Field(min_length=1, max_length=64)
    payload_hash: str = Field(min_length=1, max_length=256)
    signature: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def node_ids_are_a_pair(self) -> "RelayEnvelope":
        if (self.sender_node_id is None) != (self.receiver_node_id is None):
            raise ValueError("sender_node_id and receiver_node_id must be provided together")
        return self


class RequestBodyLimitMiddleware:
    """JSON解析前にContent-Lengthと受信ストリームの両方を制限する。"""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/v1/messages"
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError:
                await self._reject(scope, receive, send, "Content-Lengthが不正です。", 400)
                return
            if content_length < 0:
                await self._reject(scope, receive, send, "Content-Lengthが不正です。", 400)
                return
            if content_length > self.max_bytes:
                await self._reject(
                    scope, receive, send, "メッセージサイズが上限を超えています。", 413
                )
                return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await self._reject(
                    scope, receive, send, "メッセージサイズが上限を超えています。", 413
                )
                return
            body.extend(chunk)
            more_body = bool(message.get("more_body", False))

        try:
            json.loads(
                body,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite_constant,
            )
        except (json.JSONDecodeError, UnicodeDecodeError, InvalidJsonEnvelope):
            await self._reject(
                scope,
                receive,
                send,
                "JSON形式が不正です。",
                400,
                code="MESSAGE_JSON_INVALID",
            )
            return

        delivered = False

        async def replay_receive() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_receive, send)

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        message: str,
        status_code: int,
        *,
        code: str | None = None,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code
                    or (
                        "MESSAGE_TOO_LARGE"
                        if status_code == 413
                        else "INVALID_CONTENT_LENGTH"
                    ),
                    "message": message,
                    "details": {"max": self.max_bytes},
                }
            },
        )
        await response(scope, receive, send)


def _validate_json_shape(value: Any, settings: RelaySettings) -> None:
    item_count = 0

    def visit(current: Any, depth: int) -> None:
        nonlocal item_count
        if depth > settings.max_json_depth:
            raise RelayError(
                "MESSAGE_STRUCTURE_INVALID",
                "JSONのネストが上限を超えています。",
                413,
                {"max_depth": settings.max_json_depth},
            )
        if isinstance(current, str) and len(current) > settings.max_string_length:
            raise RelayError(
                "MESSAGE_STRUCTURE_INVALID",
                "JSON文字列が上限を超えています。",
                413,
                {"max_string_length": settings.max_string_length},
            )
        if isinstance(current, float) and not math.isfinite(current):
            raise RelayError(
                "MESSAGE_STRUCTURE_INVALID",
                "JSONに非有限数は使用できません。",
                422,
            )
        if isinstance(current, dict):
            item_count += len(current)
            for key, child in current.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(current, list):
            item_count += len(current)
            for child in current:
                visit(child, depth + 1)
        if item_count > settings.max_json_items:
            raise RelayError(
                "MESSAGE_STRUCTURE_INVALID",
                "JSON要素数が上限を超えています。",
                413,
                {"max_items": settings.max_json_items},
            )

    visit(value, 1)


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
            max_pending_messages_per_receiver=settings.max_pending_messages_per_receiver,
            max_pending_bytes_per_receiver=settings.max_pending_bytes_per_receiver,
            max_total_pending_bytes=settings.max_total_pending_bytes,
        )
    else:
        mailbox = MailboxStore(
            ttl_seconds=settings.message_ttl_seconds,
            rate_limit_per_minute=settings.rate_limit_per_minute,
            max_pending_messages_per_receiver=settings.max_pending_messages_per_receiver,
            max_pending_bytes_per_receiver=settings.max_pending_bytes_per_receiver,
            max_total_pending_bytes=settings.max_total_pending_bytes,
        )

    app = FastAPI(
        title="ENISHI Relay",
        version=__version__,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=settings.max_message_bytes)
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
        pending_messages, pending_bytes = mailbox.pending_stats()
        return PlainTextResponse(
            app.state.metrics.render(pending_messages, pending_bytes),
            media_type="text/plain; version=0.0.4",
        )

    @app.post("/v1/messages", status_code=201)
    def post_message(
        envelope_model: RelayEnvelope,
        agent_id: str = Depends(require_agent),
    ) -> dict[str, str]:
        current = get_relay_settings()
        envelope = envelope_model.model_dump(exclude_none=True)
        _validate_json_shape(envelope, current)
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

        try:
            delivery_id = mailbox.put(receiver, envelope, size)
        except MailboxCapacityExceeded as exc:
            status_code = 507 if exc.scope == "total_bytes" else 429
            raise RelayError(
                code="MAILBOX_CAPACITY_EXCEEDED",
                message="Relayメールボックスの容量上限を超えています。",
                status_code=status_code,
                details={"scope": exc.scope},
            ) from exc
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
    def get_messages(
        agent_id: str = Depends(require_agent),
        limit: int | None = Query(default=None, ge=1),
        cursor: str | None = Query(default=None, min_length=1, max_length=512),
    ) -> dict[str, Any]:
        current = get_relay_settings()
        page_limit = limit or current.fetch_default_limit
        if page_limit > current.fetch_max_limit:
            raise RelayError(
                code="INVALID_PAGE_LIMIT",
                message="取得件数が上限を超えています。",
                status_code=422,
                details={"max": current.fetch_max_limit},
            )
        try:
            page = mailbox.fetch(agent_id, page_limit, cursor)
        except ValueError as exc:
            raise RelayError(
                code="INVALID_CURSOR",
                message="カーソルが不正です。",
                status_code=400,
            ) from exc
        app.state.metrics.fetched(len(page.items))
        return {
            "items": [
                {
                    "delivery_id": message.delivery_id,
                    "envelope": message.envelope,
                    "stored_at": message.stored_at,
                }
                for message in page.items
            ],
            "next_cursor": page.next_cursor,
        }

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
