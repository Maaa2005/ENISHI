"""意思決定ドメインの抽象。

1ドメイン = ある種類の意思決定を、エージェント同士が最小情報で交渉するための定義。
日程調整はその最初の実装にすぎない。
"""

from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from enishi_core.models import CloneAgent, NegotiationSession


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
    supports_remote: bool
    remote_rounds_exhausted_code: str

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

    def evaluate_decision(self, **kwargs: Any) -> Any:
        """交渉の終端判断を評価する（対応しないドメインは `NotImplementedError`）。

        E3-a: ローカル/リモートの両ドライバが同じ判断コードへレジストリ経由で
        たどり着けるようにするための継ぎ目。全ドメインが判断評価を持つわけではない
        （`cost.split` は `next_action` という別形の純粋関数を使う）ため、
        戻り値は `Any`（実際は各ドメインが定義する評価結果の型）。
        """
        ...

    def build_remote_request_payload(self, request: dict[str, Any]) -> dict[str, Any]:
        """Relay経由の初回REQUESTに載せるワイヤpayloadを組み立てる（Phase F1）。

        `request` はドライバが持つ生の入力値（トピック等）。返り値のキー集合・値は
        現行の送信内容と完全一致させること（ワイヤ互換のため）。
        """
        ...

    def derive_own_position(
        self,
        session_db: Session,
        clone: CloneAgent,
        request_payload: dict[str, Any],
        peer_agent_id: str,
    ) -> dict[str, Any]:
        """自分側の私的な立ち位置を導出する（Phase F1）。送信しないローカル専用データ。

        Phase D の純粋関数の思想（自分のクローンと公開情報だけを受け取る）に寄せる。
        `Session` はここでしか使わない自分自身のデータ（記憶・ポリシー）を読むためだけに渡す。
        """
        ...

    def build_remote_propose_delta(self, own_position: dict[str, Any]) -> dict[str, Any]:
        """初回PROPOSEのwire delta（Phase F5, F5-a）。

        `own_position` は `derive_own_position` の戻り値。スライス（`meeting` の
        `_OFFER_SIZE` 等）もここへ入れる。ドライバは `own_position` の中身を
        添字アクセスしない（ドメイン非依存を保つため）。
        """
        ...

    def decide_remote_reply(
        self,
        clone: CloneAgent,
        own_position: dict[str, Any],
        received_public: dict[str, Any],
        *,
        role: str,
        round_number: int,
        peer_personal_agent_id: str,
        delegation_enabled: bool,
        high_value_approval_required: bool,
        own_last_delta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """相手の公開提示（受信envelopeのdelta）に対する次の一手を決める（Phase F1, F5-a）。

        `own_position` は `derive_own_position` の戻り値。相手の `CloneAgent` は
        受け取らない（Phase D の原則）。`Session` を要する判定
        （`delegation_enabled` / `high_value_approval_required` 等）はドライバが
        先に評価し、bool だけをここへ渡す。

        戻り値は次のキーを持つ dict（ドメインをまたいで共通の契約）:
        - `outcome`: `"auto_accept" | "counter" | "approval_required" | "reject"`
          （`NegotiationDecision.outcome` と同じ語彙）
        - `reason_codes` / `evidence` / `confidence` / `policy_version`:
          `NegotiationDecision` へそのまま保存する評価根拠
        - `reply_delta`: `outcome` が `auto_accept`（ACCEPT）/ `counter`（COUNTER）/
          `reject`（REJECT）のときにそのまま wire delta として送る辞書
        - `agreement_value`: `outcome == "auto_accept"` のときに
          `remote_agreement_payload()` へ渡す値（それ以外は無視してよい）
        - `approval_raw`: `outcome == "approval_required"` のときに
          `approval_context()` へ渡す生データ
        - `proposed_action`: 承認画面のデフォルト操作（`"ACCEPT" | "COUNTER"`）
        """
        ...

    def remote_agreement_payload(self, agreed: dict[str, Any]) -> dict[str, Any]:
        """遠隔交渉が合意に達したときの `Agreement.agreed_payload` を組み立てる（Phase F1）。"""
        ...

    def agreement_value_from_accept_delta(
        self, delta: dict[str, Any], request_payload: dict[str, Any]
    ) -> Any:
        """相手から届いたACCEPTのwire deltaから、合意値を取り出す（Phase F5-a）。

        取り出した値は `remote_agreement_payload()` へそのまま渡す。ドライバ
        （`services/remote_negotiation.py`）が `selected_slot` / `agreed_share` 等の
        ドメイン固有キーを直接読まずに済むようにするための継ぎ目。`request_payload`
        （このセッションのREQUESTペイロード）は、ACCEPTのdelta単体には含まれない
        `title` / `total_amount` のような公開済みの文脈値を補うために渡す。
        """
        ...

    def approval_context(self, raw: dict[str, Any]) -> dict[str, Any]:
        """人間承認payloadの `proposal` / `public_context` を組み立てる（Phase F2）。

        `raw` はドライバ（`services/remote_negotiation.py`）が持つドメイン固有の生の
        意思決定材料（meeting なら `selected_slot` / `candidate_slots`）。戻り値は
        `{"proposal": ..., "public_context": ...}` の2キーを持つ辞書。

        - `proposal` — その承認で人間が是非を判断する対象。
        - `public_context` — 承認画面に出す**公開可能な**補助情報。
          留保価格・効用パラメータ・記憶の生データのような私的情報を絶対に入れないこと。
        """
        ...

    def approval_reply(
        self,
        *,
        approved: bool,
        target_status: str,
        proposal: dict[str, Any],
        public_context: dict[str, Any],
        override: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """人間による承認解決の結果から、返信のwireメッセージを組み立てる（Phase F5-a）。

        `proposal` / `public_context` は `approval_context()` が組み立てたもの
        （読み側の後方互換で旧キーからの復元を含みうる）。`override` は人間が候補を
        上書きした場合の値（`resolve_remote_approval` の `proposal_override`）。

        戻り値: `{"message_type": "ACCEPT"|"COUNTER"|"REJECT", "delta": {...},
        "agreement_value": <remote_agreement_payload()へ渡す値 | None>}`。
        """
        ...


class BaseDecisionDomain:
    """`DecisionDomain` の共通デフォルトを持つ基底クラス。"""

    intent: str
    delegation_key: str | None = None
    supports_remote: bool = False
    payload_model: Any = None
    remote_rounds_exhausted_code: str = "NEGOTIATION_ROUNDS_EXHAUSTED"

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

    def evaluate_decision(self, **kwargs: Any) -> Any:
        raise NotImplementedError

    def build_remote_request_payload(self, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def derive_own_position(
        self,
        session_db: Session,
        clone: CloneAgent,
        request_payload: dict[str, Any],
        peer_agent_id: str,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def build_remote_propose_delta(self, own_position: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def decide_remote_reply(
        self,
        clone: CloneAgent,
        own_position: dict[str, Any],
        received_public: dict[str, Any],
        *,
        role: str,
        round_number: int,
        peer_personal_agent_id: str,
        delegation_enabled: bool,
        high_value_approval_required: bool,
        own_last_delta: dict[str, Any] | None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def remote_agreement_payload(self, agreed: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def agreement_value_from_accept_delta(
        self, delta: dict[str, Any], request_payload: dict[str, Any]
    ) -> Any:
        raise NotImplementedError

    def approval_context(self, raw: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def approval_reply(
        self,
        *,
        approved: bool,
        target_status: str,
        proposal: dict[str, Any],
        public_context: dict[str, Any],
        override: dict[str, Any] | None,
    ) -> dict[str, Any]:
        raise NotImplementedError
