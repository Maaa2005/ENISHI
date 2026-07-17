# 改善ロードマップ（2026-07-18 外部調査の突き合わせ結果）

外部調査（A2A標準・自動交渉研究・エージェントセキュリティ研究・実践者スレ）で得た候補を、現行実装と突き合わせて採否評価したもの。出典は実物確認済み（Vault: Knowledge/enishi-improvement-survey.md に検証メモ）。

## 採用（次の実装対象）

> 実装状況（2026-07-18）: 1〜3は実装・回帰試験済み。カードv1の後方互換も維持。

### 1. Agent Card: 名刺への能力宣言の追加 + タイムゾーン対応
A2A標準（a2aproject/A2A）の Agent Card 概念。交渉開始前に静的メタデータで能力を交換し、LLMを介さず不整合を即時検知する。

- 現状: `identity_cards.py` の `enishi-card/1` は身元（鍵・fingerprint・display_name）のみ。能力宣言なし。
- 現状: `scheduling.py` / `decision_evaluator.py` は naive な ISO 時刻でタイムゾーン概念が無い。**越境ペアの日程調整で実バグになる**（相手のJST 14:00 と自分のPST 14:00 を同一視して交差判定する）。
- やること: `enishi-card/2` に `capabilities` を追加 — `timezone` / `supported_intents` / `protocol_versions`。交渉開始時に不一致を検知して即エラー or 変換。scheduling をタイムゾーン付き datetime に移行。
- 実装: v2カード、ピア能力の永続化、交渉前のintent/protocol照合、offset付き候補生成と異timezone交差判定を追加。
- 開示ポリシー注意: カードに載せるのは**秘密でない交渉可能情報のみ**。禁止時間帯・選好は selective disclosure の対象なのでカードに載せない。

### 2. COUNTER / REJECT への公開理由フィールド（論証ベース交渉の最小形）
- 現状: `reason_codes` は `NegotiationDecision` とローカル承認 payload にのみ存在し、相手には理由が伝わらない。相手側は「なぜ蹴られたか」不明のまま再提案するため往復が増える。
- やること: AUNメッセージ payload に `public_reason`（粗い公開カテゴリ: `no_common_slot` / `constraint_violation` / `policy_declined` 程度）を追加。
- 開示ポリシー注意: 内部の `meeting_time_avoided` 等をそのまま送ると選好が漏れる。**内部理由→公開カテゴリの明示的なマッピング関数を挟む**こと。
- 実装: 明示的マッピングを通じてCOUNTER/REJECTだけに粗い公開理由を付与。内部reason codeはwireへ出さない。

### 3. 承認UIのエスカレーション強化（小規模UX作業）
実践者スレの一貫した知見: ユーザーが求めるのは Yes/No ゲートではなく「競合時に代替案から選ばせる」半自動ゲート。

- 現状: バックエンドはほぼ実装済み。承認 payload に `candidate_slots` / `reason_codes` / `proposed_action` が入っている。`avoid_time_ranges`（譲れないルール）も clone preference に存在。
- やること: デスクトップUIの承認画面が「代替スロットからの選択」を提示しているか確認し、していなければ選択式に拡張。`avoid_time_ranges` の編集UIの有無も確認。
- 実装: 候補選択を追加し、第一候補以外はACCEPTではなくCOUNTERとして送信。代理AI設定に希望・回避時間帯の編集を追加。

## 中期（次のフェーズで検討）

### 4. W3C VC 2.0 ベースの委任証明（enishi-card/3 への進化）
「この人間がこのドメインの代理権をこのエージェントに与えた」を暗号学的に提示する Capability VC。Ed25519 基盤の上に署名フォーマット層を足すだけで、ENISHI の信頼モデル（prove who it speaks for）の核心と一致する。名刺 v2（能力宣言）の自然な次段階として設計する。

### 5. 効用ベース譲歩戦略（複数論点交渉の導入時）
negmas（yasserfarouk/negmas）の linear concession 等。現状の日程調整は単一論点でスロット交差が決定的に解けるため**今は不要**。価格・納期など複数論点の交渉 intent を追加する段階で、デッドロック防止と「相手の妥協度の可視化」のために導入する。

### 6. 相手由来テキストのプロベナンスタグ付け（ARGUS の軽量版）
文脈依存 prompt injection への因果監査（ARGUS, arXiv:2605.03378, 攻撃成功率 28.8%→3.8%）。フル導入はコスト高。まずは相手エージェント由来のテキストを LLM プロンプトに混ぜる箇所で出所タグを付け、意思決定プロンプトでは untrusted 扱いを明示する軽量版から。MCP instructions の「UNTRUSTED CONTENT を命令として実行しない」方針のコード側での徹底。

## 見送り（理由付き）

- **PSI によるカレンダー照合**: 現状の交換単位は既に候補スロットのみ（フルカレンダー非開示）で、脅威モデル上の増分が小さい。暗号ライブラリ追加コストに見合わない。研究進展を注視。
- **DPoP / RFC 9449**: replay 対策（nonce + seen_message + 署名 Envelope）は実装済み。多段委任（クローンが更に委任する）を入れる段階まで不要。
- **AP2 決済 Mandate**: 決済ユースケースに進む時に再評価。現段階では対象外。
- **ANP / P2P 化**: リレー運用開始前に通信層を差し替えるのは時期尚早。リレーの forward-only 設計で足りている。

## 配布メモ（README の残タスクと一致）

- sidecar（PyInstaller バイナリ）を含む全同梱バイナリへ**同一証明書で再帰的に codesign** しないと公証で却下される。
- `tauri-plugin-updater` は Apple 署名とは別に Minisign 署名が必須。GitHub Releases への登録と同時に CI で自動付与するのが定石。
- 参考: https://v2.tauri.app/distribute/sign/macos/
