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
- **連続値の譲歩**（`domains/cost_split.py`）: 効用の理想点（`preferred_ratio` 由来の `open_r`）と
  留保価格（`reservation_ratio` 由来の `U`/`L`）の間で、`concession_ratio` に従ってラウンドごとに
  双方が歩み寄る（Phase D）。二値判定ではなく連続値そのものが交渉の対象になる。

## 戦略と進行の分離（Phase D）

`cost.split` は、**戦略（次の一手を決める判断）**と**進行（メッセージ保存・承認生成・合意生成という
副作用）**を、はっきり別のコード単位に分けている。

- **戦略** = `domains/cost_split_strategy.py` の `next_action`。**副作用を一切持たない純粋関数**で、
  受け取るのは自分の `CloneAgent` と、双方が見てよい公開情報（`OfferState` など）だけ。
  相手の `CloneAgent` も `Session` も受け取らない（型シグネチャで担保する）。
  `approval_required` のように `Session` が必要な判定は、**呼び出し側（ドライバ）が先に評価し、
  その結果（bool）だけを引数として渡す**。DBアクセス・commit は一切行わない。
- **進行（ドライバ）** = `domains/cost_split.py` の `run_cost_split_negotiation`。両者の
  `next_action` を交互に呼び、返ってきた `StrategyAction`（accept/counter/escalate/reject）を
  解釈して `append_message` / `create_agreement` / `create_negotiation_approval` / commit を行う。
  ZOPA（合意可能領域）の事前判定のように「両者のクローンがローカルに揃っているドライバでしか
  行えない最適化」はドライバ側に置き、`next_action` には持ち込まない。

**この境界がある理由**: 戦略が自分のクローンと公開情報だけで完結していれば、ローカル交渉（両者の
`next_action` を呼ぶ）とリモート交渉（自分の分だけ呼んで結果を送信する）で、**ドライバが違うだけで
判断は同一のコードにできる**（`services/remote_negotiation.py` はローカルに相手のクローンを
持たない）。新しいドメインが多ラウンドの交渉を実装するとき、特に双方が譲歩しうる構造なら、
`next_action` パターン（純粋な戦略関数 + 副作用を持つドライバ）に倣うこと。

### 終端判断（accept/counter/escalate）の集約先はドメイン、呼び出しはレジストリ経由（Phase E, E3-a）

`next_action`（`cost.split`）と同じ形の教訓が、判断そのもの（例: 「共通スロットを承諾してよいか」）
にも当てはまる。`meeting.schedule` では、この判断が一時期 `services/decision_evaluator.py`
（ローカル用の想定）と `services/remote_negotiation.py`（リモート用に別実装）へ分かれて
重複しかけたことがある。同じ「委任OFF／confidence閾値未満／relationship承認要求」というガードと
「時間帯の好み」という判断を、ローカルとリモートで別々にメンテナンスする状態は、片方だけ直して
もう片方が古いままになる典型的な不具合源になる。

これを避けるため、**終端判断の実体はドメイン本体（`domains/<name>.py`）に置き、
`DecisionDomain.evaluate_decision(**kwargs)`（`domains/base.py`）として公開する**。
ローカル・リモートどちらのドライバも、判断が必要な箇所では
`get_domain(intent).evaluate_decision(...)` をレジストリ経由で呼ぶ（`meeting_schedule.py` の
`evaluate_meeting_schedule` を直接 import しない）。`services/decision_evaluator.py` の
`evaluate_meeting_schedule` は後方互換の薄いラッパ（`tests/test_agent_decisions.py` が直接
import しているため残す）で、実体は持たない。全ドメイン共通のガード（`evaluate_common_guards` /
`CONFIDENCE_THRESHOLD` / `DecisionEvaluation`）も、ドメイン側から循環 import なしに参照できるよう
`domains/common.py` に置く。

進行（ループ・メッセージ送受信）はこれまでどおりドライバ（`run_negotiation` /
`remote_negotiation.py`）側に残る。「進行」と「終端判断」の分離という発想自体は上の
戦略/進行の分離と同じだが、`cost.split` の `next_action` は毎手番の一手を決める関数であるのに対し、
`meeting.schedule` の `evaluate_decision` は「見つかった共通スロットを所有者の権限で承諾してよいか」
という一点だけを判断する点が異なる（`run_negotiation` は共通スロットが見つかった直後に必ずこの
判断を通してから ACCEPT する。所有者の権限を無視して即 ACCEPT していた旧挙動は、ENISHI の
「人間の価値観と権限を持つエージェント」という定義に反するため、Phase E で意図的に変更した）。

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
   `enishi_core.domains.common.evaluate_common_guards` を使う
   （`domains/cost_split.py` の `run_cost_split_negotiation` を参照）。終端判断そのもの
   （accept/counter/escalate 等）をレジストリ経由で公開する場合は上の「終端判断の集約先」節も参照。

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
