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
   - `supports_remote: bool`（既定 `False`） — Relay経由の遠隔交渉ドライバ（`services/remote_negotiation.py`）
     に対応しているかどうか。**この値が `True` のドメインだけが、自ノードのAgent Cardの
     `supported_intents` へ宣言される**（`services/identity_cards.py`, Phase F3）。宣言は
     「相手から送られてきても処理できる」という約束であるため、遠隔ドライバの4フック
     （`build_remote_request_payload` / `derive_own_position` / `decide_remote_reply` /
     `remote_agreement_payload`。Phase F1）と `approval_context`（Phase F2、下記）を
     実装し終えるまでは `True` にしないこと。実装していないのに宣言すると、相手が実際に
     送ってきたときに壊れる。また `services/agent_requests.submit_agent_request` は、
     この値が `False` のintentへの自然言語遠隔依頼を、ピアの能力を見るより前に
     422 `INTENT_NOT_SUPPORTED_FOR_REMOTE_REQUEST` で拒否する（Phase F4-a）。
   - `payload_model` — `payload` を検証する pydantic モデル。`payload_schema` プロパティが
     ここから JSON Schema を生成し、`GET /v1/intents` で公開する。
   - `validate_request(body) -> DomainRequest` — `payload_model.model_validate(body.payload)` で
     検証し、ドメイン固有の入力オブジェクトへ変換する。失敗時は
     `EnishiError(code="INVALID_NEGOTIATION_PAYLOAD", status_code=422)` へ変換する。
   - `topic_of(request) -> str` — `NegotiationSession.topic` に入れる値。
   - `start(session_db, request) -> NegotiationSession` — 交渉を進行させる。
   - `approval_context(raw) -> dict`（Phase F2） — 遠隔交渉が人間承認を要するとき
     （`_request_human_decision`, `services/remote_negotiation.py`）、承認payloadに積む
     ドメイン非依存の2キー `proposal`（人間が是非を判断する対象）と `public_context`
     （承認画面向けの**公開可能な**補助情報）を組み立てる。留保価格・効用パラメータ・
     記憶の生データのような私的情報を `public_context` に入れないこと（`tests/test_cost_split.py`
     の `_assert_no_forbidden_keys` と同じ「最小情報の原則」がここにも適用される）。
     承認payloadは後方互換のため、ドメイン固有の旧キー（meetingなら `selected_slot` /
     `candidate_slots`）も並行して出力し続ける。読み側は `proposal` が無ければ
     旧キーへフォールバックする。

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

   これだけで、自然言語の依頼文をLLMが解釈する入口（`services/intent_interpreter.py`,
   Phase C）の intent 分類候補も自動で増える。`ClaudeInterpreter` は候補一覧を
   `registered_intents()` から動的に生成しており、intentをハードコードしていないため、
   新ドメインの登録がここでも「1ファイル+1行」で完結する。payload抽出も
   ここで定義した `payload_model` をそのまま `output_format` として再利用する
   （新しい抽出用スキーマを書き起こす必要はない）。

4. **テストを足す**: `tests/test_decision_domains.py` に倣い、
   レジストリへの登録・`validate_request` のエラー・`start` の結果を検証する。
   `tests/test_cost_split.py` は「最小情報の原則」（responder の予算・留保価格・効用パラメータを
   メッセージに載せない）を全メッセージ走査で検証する例として参照できる。

## 遠隔対応を追加する（`supports_remote = True` にする、Phase F1/F2/F5）

上の手順で作ったドメインは、まずローカル交渉（`start()` が両者のクローンを直接呼ぶ経路）だけに
対応した状態になる。Relay経由で別ノードの相手と交渉する（`services/remote_negotiation.py`）には、
以下の7フックすべてを実装してから `supports_remote = True` にする。**実装が終わるまでは
`False` のままにすること**（`False` の間は自ノードのAgent Cardにこのintentが宣言されず、
`submit_agent_request` も自然言語からの遠隔依頼を422で拒否するため、相手に「対応している」と
誤って伝わることがない）。

参考実装は `domains/meeting_schedule.py`（離散候補集合の交差）と `domains/cost_split.py`
（連続値の譲歩、Phase F5-b）の2つ。型が近い方を見ること。

1. **`build_remote_request_payload(request: dict) -> dict`** — Relay経由の初回REQUESTに乗せる
   ワイヤpayloadを組み立てる。ここに書いたキーはそのまま相手ノードへ送信されるため、
   最小情報の原則（下記）に反する私的な値を入れないこと。
2. **`derive_own_position(session_db, clone, request_payload, peer_agent_id) -> dict`** —
   送受信どちらの側でも「自分の私的な立ち位置」を組み立てる（**送信しない**、ローカル専用の
   中間値）。ローカル交渉と違い、リモートでは相手のクローンが手元にないため、判断に必要な
   自分側のポリシー・選好をここで一度だけ算出する。
3. **`build_remote_propose_delta(own_position: dict) -> dict`** — 初回PROPOSEのwire delta。
   `own_position` のうち、相手に見せてよい提示値だけを抜き出す。
4. **`decide_remote_reply(clone, own_position, received_public, *, role, round_number,
   peer_personal_agent_id, delegation_enabled, high_value_approval_required,
   own_last_delta) -> dict`** — 相手の提示（PROPOSE/COUNTER）に対する次の一手を決める、
   このフックの中核。戻り値の契約は `domains/base.py` の `DecisionDomain.decide_remote_reply`
   のdocstringに全フィールド（`outcome` / `reason_codes` / `evidence` / `confidence` /
   `policy_version` / `reply_delta` / `agreement_value` / `approval_raw` / `proposed_action`）が
   明記されているので、実装前に必ず読むこと。
   - **既存のローカル用「戦略」関数（例: `cost_split_strategy.next_action`）があるなら、
     判断ロジックを書き直さずそのまま呼ぶ**。ローカル/リモートで判断コードが分岐すると、
     片方だけ直してもう片方が古いままになる不具合源になる（上の「戦略と進行の分離」節と同じ
     教訓）。`Session` が必要な判定（`delegation_enabled` / `approval_required` など）は
     ドライバ（`services/remote_negotiation.py` の `_handle_envelope`）が先に評価し、bool
     だけを引数で渡す。
   - 委任OFF・confidence閾値未満・relationship承認要求の共通ガードは
     `domains/common.py` の `evaluate_common_guards` を使う。
5. **`remote_agreement_payload(agreed: Any) -> dict`** — 合意成立時、`Agreement.agreed_payload`
   に保存する形を組み立てる。
6. **`agreement_value_from_accept_delta(delta: dict, request_payload: dict) -> Any`**
   （Phase F5-a）— 相手から届いたACCEPTのwire deltaから合意値を取り出す。ACCEPTのdeltaは
   最小情報の原則により合意値そのもの（例 `agreed_share`）しか持たないことが多く、
   `title` / `total_amount` のような既に公開済みの文脈値は `request_payload`
   （このセッションのREQUESTペイロード、`services/remote_negotiation.py::_request_payload`
   経由で渡される）から補ってよい。取り出した値はそのまま `remote_agreement_payload()` へ渡される。
7. **`approval_context(raw: dict) -> {"proposal": dict, "public_context": dict}`**
   （Phase F2） — `decide_remote_reply` が `approval_required` を返したときに人間承認へ回す
   payloadを組み立てる。`raw`（`decide_remote_reply` の `approval_raw`）に私的情報を積んでいなければ
   このフックで漏れる心配はない。
8. **`approval_reply(*, approved, target_status, proposal, public_context, override) -> dict`**
   — 人間が承認/却下した結果から、送り返すwireメッセージ（`message_type` / `delta` /
   `agreement_value`）を組み立てる。

### 最小情報の原則の徹底（機械的に検証すること）

responder（あるいは応答する側）の予算・留保価格・効用パラメータ・選好の生値は、
**上記いずれのフックの戻り値にも一切含めない**。`derive_own_position` はこれらを含んでよい
（送信されないため）が、`build_remote_request_payload` / `build_remote_propose_delta` /
`decide_remote_reply` の `reply_delta` / `remote_agreement_payload` / `approval_context` の
戻り値には決して含めないこと。新しいドメインを追加したら、`tests/test_remote_cost_split.py`
（あるいは `tests/test_cost_split.py`）の禁止キー再帰走査パターンに倣い、全エンベロープの
`payload` / `delta` と承認payloadを走査するテストを追加すること。

## 注意

- `domains` パッケージは `schemas` を import しない（循環 import を避けるため）。
  `validate_request` の引数は `domains/base.py` の `NegotiationRequestLike` プロトコルで受ける。
  `DateRange` / `TimeRange` のような共通の値オブジェクトは `domains/value_objects.py` に置き、
  `schemas` 側がそれを再エクスポートする（逆向きの import を作らない）。
- DB スキーマ（`models/`）を変更する場合は別途 Alembic マイグレーションが必要。
- 依存の向きは `schemas → domains → services → models` の一方向を保つこと。
- responder 側のプライベートなポリシー・選好パラメータ（予算・留保価格・効用パラメータ等）は
  `NegotiationMessage.payload` / `delta` に決して載せない（Selective Disclosure）。
