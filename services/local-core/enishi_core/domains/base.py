"""意思決定ドメインの抽象。

1ドメイン = ある種類の意思決定を、エージェント同士が最小情報で交渉するための定義。
日程調整はその最初の実装にすぎない。
"""

from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from enishi_core.models import NegotiationSession


@runtime_checkable
class NegotiationRequestLike(Protocol):
    """`NegotiationCreate` 相当の入力を構造的に受け取るためのプロトコル。

    ワイヤ表現は intent + 不透明 payload のみを持つ（Phase B）。
    domains パッケージが schemas を import しない（循環 import を避ける）ための境界でもある。
    """

    intent: str
    initiator_user_id: str
    responder_user_id: str
    payload: dict[str, Any]


class DomainRequest(Protocol):
    """検証済みのドメイン固有入力オブジェクトを表すマーカー。

    各ドメインが自分の語彙（会議なら topic/duration_minutes、タスクなら title/deadline）を
    持つ具体クラス（dataclass等）を定義し、このプロトコルとして扱う。
    """


class DecisionDomain(Protocol):
    """意思決定ドメイン1つ分の振る舞い。"""

    intent: str
    delegation_key: str | None

    @property
    def payload_schema(self) -> dict[str, Any]:
        """この intent の payload が従う JSON Schema（`GET /v1/intents` で公開する）。"""
        ...

    def validate_request(self, body: NegotiationRequestLike) -> DomainRequest:
        """入力を検証し、ドメイン固有の入力オブジェクトへ変換する。

        不足時は `EnishiError(code="INVALID_NEGOTIATION_PAYLOAD", status_code=422)` を送出する。
        """
        ...

    def topic_of(self, request: DomainRequest) -> str:
        """`NegotiationSession.topic` に入れる値を返す。"""
        ...

    def start(self, session_db: Session, request: DomainRequest) -> NegotiationSession:
        """この交渉を進行させる。"""
        ...


class BaseDecisionDomain:
    """`DecisionDomain` の共通デフォルトを持つ基底クラス。"""

    intent: str
    delegation_key: str | None = None
    payload_model: Any = None

    @property
    def payload_schema(self) -> dict[str, Any]:
        if self.payload_model is None:
            raise NotImplementedError
        schema: dict[str, Any] = self.payload_model.model_json_schema()
        return schema

    def validate_request(self, body: NegotiationRequestLike) -> DomainRequest:
        raise NotImplementedError

    def topic_of(self, request: DomainRequest) -> str:
        raise NotImplementedError

    def start(self, session_db: Session, request: DomainRequest) -> NegotiationSession:
        raise NotImplementedError
