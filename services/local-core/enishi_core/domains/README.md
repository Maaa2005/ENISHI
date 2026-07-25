# 意思決定ドメインの追加手順

ENISHI は「人間の価値観と権限を持つAIエージェント同士が、必要最小限の情報で交渉・意思決定を行うための基盤」です。
日程調整（`meeting.schedule`）・仕事依頼（`task.request`）・割り勘（`cost.split`）は、その3つの実装にすぎません。
新しい意思決定ドメインは、以下の手順で追加できます。

ワイヤ表現（`NegotiationCreate`）はドメイン語彙を持ちません（Phase B）。`intent` と不透明な
`payload: dict[str, Any]` だけを持ち、`payload` の中身を検証・解釈するのは各ドメインの責務です。

## 3つの型の実例

既存3ドメインは、交渉の構造として3つの型を表しています。新しいドメインを作るときは、
どの型に近いかで参考にする実装を選んでください。

- **離散候補集合の交差**（`domains/meeting_schedule.py`）: 双方の候補スロット集合の共通部分を
  多ラウンドの提案・逆提案で探す。二値判定（合う/合わない）。
- **閾値との比較**（`domains/task_request.py`）: 単発のポリシー判定（自動承諾／自動カウンター／要承認）。
  二値判定（閾値以下か超えるか）。
- **連続値の譲歩**（`domains/cost_split.py`）: 効用の理想点（`preferred_ratio` 由来の `target`）と
  留保価格（`reservation_ratio` 由来の `reservation`）の間で、`concession_ratio` に従って
  ラウンドごとに歩み寄る。二値判定ではなく連続値そのものが交渉の対象になる、Phase D
  （効用ベース譲歩戦略）への足場でもある。

## 手順

1. **ファイルを1つ作る**: `domains/<新ドメイン名>.py` を作成する。
   - 既存3ドメイン（`domains/meeting_schedule.py`, `domains/task_request.py`,
     `domains/cost_split.py`）を実例として参照する。
   - `payload` の形を表す pydantic モデル（例: `CostSplitPayload`）と、
     検証済みのドメイン固有入力を表す `dataclass`（例: `CostSplitRequest`）を定義する。

2. **`DecisionDomain` を実装する**（`domains/base.py` 参照。`BaseDecisionDomain` を継承すると
   `payload_schema` が `payload_model.model_json_schema()` から自動導出される）。
   - `intent: str` — ドメイン識別子（例 `"expense.approval"`）。
   - `delegation_key: str | None` — `policies.delegation_enabled()` に渡すキー。委任判定が不要なら `None`。
   - `payload_model` — `payload` を検証する pydantic モデル。`payload_schema` プロパティが
     ここから JSON Schema を生成し、`GET /v1/intents` で公開する。
   - `validate_request(body) -> DomainRequest` — `payload_model.model_validate(body.payload)` で
     検証し、ドメイン固有の入力オブジェクトへ変換する。失敗時は
     `EnishiError(code="INVALID_NEGOTIATION_PAYLOAD", status_code=422)` へ変換する。
   - `topic_of(request) -> str` — `NegotiationSession.topic` に入れる値。
   - `start(session_db, request) -> NegotiationSession` — 交渉を進行させる。

   `domains/common.py` の `require_active_clone` / `create_agreement` /
   `create_negotiation_approval` / `append_message` は、どの構造でも共通して使える。
   全ドメイン共通のガード（委任OFF／confidence閾値未満／relationship承認要求）が必要なら
   `enishi_core.services.decision_evaluator.evaluate_common_guards` を使う
   （`domains/cost_split.py` の `run_cost_split_negotiation` を参照）。

3. **`domains/__init__.py` で register する**:

   ```python
   from enishi_core.domains.expense_approval import ExpenseApprovalDomain

   register(ExpenseApprovalDomain())
   ```

4. **テストを足す**: `tests/test_decision_domains.py` に倣い、
   レジストリへの登録・`validate_request` のエラー・`start` の結果を検証する。
   `tests/test_cost_split.py` は「最小情報の原則」（responder の予算・留保価格・効用パラメータを
   メッセージに載せない）を全メッセージ走査で検証する例として参照できる。

## 注意

- `domains` パッケージは `schemas` を import しない（循環 import を避けるため）。
  `validate_request` の引数は `domains/base.py` の `NegotiationRequestLike` プロトコルで受ける。
  `DateRange` / `TimeRange` のような共通の値オブジェクトは `domains/value_objects.py` に置き、
  `schemas` 側がそれを再エクスポートする（逆向きの import を作らない）。
- DB スキーマ（`models/`）を変更する場合は別途 Alembic マイグレーションが必要。
- 依存の向きは `schemas → domains → services → models` の一方向を保つこと。
- responder 側のプライベートなポリシー・選好パラメータ（予算・留保価格・効用パラメータ等）は
  `NegotiationMessage.payload` / `delta` に決して載せない（Selective Disclosure）。
