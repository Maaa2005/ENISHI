# TwinLink 実装依頼書 v3

## 改訂履歴

* v3（2026-07-12）: 「TwinLink 方針修正」を軸に全体を再構成。中心を「本人から権限を委任されたAIエージェント同士が、安全かつ低コストで交渉・調整・協働する通信プラットフォーム」と定義し、Agent Identity・委任・Selective Disclosure・交渉・合意・人間承認を中核に昇格。クローン自動生成とCodex/Claude Code連携は拡張機能へ降格。末尾にあった方針修正セクションは本文へ統合。
* v2（2026-07-11）: Phase 0〜5の実装結果とAIレビュー（Fable×GPT-5.5×gpt-5.6-sol）を反映。§7脅威モデル、§8スキーマ管理、§17プライバシー境界・記憶削除の整合、§25信頼モデル・状態機械・Relay責務、§28測定仕様、§30非同期タスク実行、§31承認の失効、§35 Phase 6受入条件を追加。
* v1（2026-07-10）: 初版（Codex実装依頼書）。

## v2→v3 主要セクション対応（コードのdocstringは旧番号を参照している場合がある）

```text
v2 §7(ローカルファースト/脅威モデル)→§11 / §8(保存場所/スキーマ)→§12 / §9(Keychain)→§13
v2 §10-11(Local Core/Sidecar)→§14 / §12(ディレクトリ)→§15
v2 §14,18(クローン生成/モデル)→§29 / §15-17(記憶)→§19(機密度表は§18)
v2 §19(コーディング用クローン)→§20,§29 / §20(Context Package)→§30
v2 §21-24(CLI接続/安全設計/プロジェクト)→§30 / §25(プロトコル/信頼/状態機械/Relay)→§16,§21
v2 §26(所有者分離)→§17 / §27(日程調整)→§22 / §28(トークン比較)→§25
v2 §29(画面)→§31 / §30(API/非同期タスク)→§28,§30 / §31(承認)→§24
v2 §32(監査ログ)→§26 / §33(エラー)→§27 / §34(テスト)→§32 / §35-36(フェーズ/完成条件)→§33-34
```

---

# 第I部 製品定義

# 1. プロジェクト概要

プロジェクト名は **TwinLink** とする。

TwinLinkは、

**本人から権限を委任されたAIエージェント同士が、安全かつ低コストで交渉・調整・協働するための通信プラットフォーム**

である。

特定のAIモデルには依存せず、Codex、Claude、Gemini、OSSエージェントなどから利用できる設計にする。

ただし、汎用的なA2A通信規格を新しく作ること自体が目的ではない。既存規格を利用・拡張し、通信規格そのものの再発明は避ける。

TwinLink独自の価値は、通信の上に以下を加えることである。

* 誰の代理AIなのか
* 本人からどの権限を与えられているか
* どの情報を相手に公開できるか
* どの判断を自動化できるか
* どの段階で本人確認が必要か
* どの条件で合意したか
* 自然言語の往復をどれだけ削減できたか

最初のバージョンは、**macOS向けデスクトップアプリ**として実装する。ユーザーは現在Macを使用しているため、Windows版を先に作らない。最初にmacOS版を完成させ、その後に同じコードベースからWindows版へ展開できる構成にする。

---

# 2. 長期ビジョン

**世界中の人が本人代理AIを持ち、それらが企業やAIモデルの違いを越えて、本人から委任された範囲で仕事・交渉・協働できるインフラを構築する。**

TwinLinkはAIエージェントのインターネット全体を作るのではなく、

**人間をAIエージェントネットワークへ安全に接続する本人代理・委任・交渉レイヤー**

を担う。

本人代理AI同士は、メールのような長い自然言語を毎回交換するのではなく、意図、条件、制約、差分、承認状態などを構造化データとして交換する。これにより以下を実現する。

* 人間同士の調整作業を削減する
* AIの入出力トークンとLLM呼び出し回数を削減する
* 条件の解釈ミスを削減する
* 本人確認が必要な場合だけ人間へ通知する
* 異なる所有者・異なるAIモデルのエージェント同士を安全に接続する

---

# 3. 中核概念の位置付け

### 本人代理AI

TwinLinkを利用する主体であり、単なる追加機能ではない。本人の目的・予定・好み・価値観・判断ルール・委任された権限・本人確認が必要な境界を保持し、本人に代わって交渉する。

### 記憶・第二の脳

本人代理AIが判断するための情報源である。TwinLink自体を知識管理ツールにはしない。

### A2A通信

エージェント同士を接続する土台として利用する。既存規格を利用・拡張し、通信規格そのものの再発明は避ける。

### Codex・Claude Code

TwinLinkへ接続できるエージェントの例である。プロダクトの中心にはしない。Provider Adapterの1実装として扱う。

---

# 4. TwinLink Core構成

TwinLink Coreは以下で構成する。

```text
TwinLink Core
├── Agent Identity            … 誰の代理か（公開鍵由来ID・ペアリング・信頼）
├── Delegation and Permissions … 本人からの委任範囲・承認レベル
├── Selective Disclosure      … 相手ごとの情報公開設定
├── Negotiation Sessions      … 交渉セッション（日程調整・仕事依頼）
├── Human Approval            … 人間承認へのエスカレーションと失効
├── Structured Messaging      … 構造化メッセージ・delta差分・状態機械
├── Token Metrics             … トークン計測と自然言語方式との比較
├── Memory Connectors         … 記憶ソースへの接続（判断材料の供給）
└── Provider Adapters         … Codex / Claude Code / Mock などの交換可能な接続
```

Communication Engineだけを最上位に置くのではなく、

**本人性・権限・公開範囲・交渉状態**

を通信と同じ重要度で扱う。

---

# 5. MVP

MVPでは、異なる2人にそれぞれ本人代理AIを用意する。

実装する流れは以下とする。

1. ユーザー同士を接続する（公開鍵ペアリング・信頼フロー）
2. 相手ごとに公開可能な情報を設定する（Selective Disclosure）
3. 本人がテキストまたは音声で依頼する（音声は後回しでよい）
4. 本人代理AIが依頼を構造化する
5. 相手の本人代理AIと日程または仕事条件を交渉する
6. 許可された情報だけを利用する
7. 必要な場合だけ本人へ承認を求める
8. 合意内容を実行または確定する（Agreement）
9. Gmail型の自然言語通信とトークン数を比較する

### 最初のユースケース

* 日程調整（`meeting.schedule`）
* 簡単な仕事依頼（`task.request`）

---

# 6. MVPで後回しにするもの

* 世界規模のエージェント検索市場
* エージェントの売買や決済
* 高度なクローン自動生成
* Mac内の全記憶の収集
* Codex・Claude Codeの高度な操作
* 3D UIやアバター
* 汎用的な知識管理機能
* 独自A2A規格の全面的な開発
* 音声入力

クローン自動生成やコーディングエージェント連携は、基本交渉が動作した後に拡張する（第IV部）。

---

# 7. 機能追加の判断基準

新しい機能は、次の基準で判断する。

> **この機能は、異なる人の本人代理AI同士の交渉を、より速く、安全に、少ない人間操作とトークンで完了させるか。**

YESなら採用候補とする。NOならMVPでは実装しない。

さらに、特定のAIモデルに依存せず、Provider Adapterで交換可能かを確認する。

---

# 第II部 技術基盤

# 8. 製品形態と技術スタック

```text
TwinLink Desktop for macOS
```

UIはWeb技術で作成し、Tauri 2を利用してmacOSアプリとして動作させる。

```text
デスクトップフレームワーク：
Tauri 2

フロントエンド：
React / TypeScript / Vite / Zustand

OS連携：
Rust / Tauri Commands

AI・記憶・交渉処理：
Python 3.12 / FastAPI / Pydantic / SQLAlchemy / Alembic

ローカルデータベース：
SQLite

API通信：
HTTP / WebSocket

テスト：
pytest / cargo test / Vitest

コード品質：
Ruff / mypy / ESLint / Prettier
```

Tauriは、WebフロントエンドとRustを組み合わせ、同じコードベースからmacOS、Windows、Linuxなどへ展開できる。今回はmacOSを優先して実装する。

---

# 9. 対象macOSと開発環境

最低対応バージョンは **macOS 13 Ventura以上** とする（Claude CodeのmacOS要件と合わせるため）。

CPUアーキテクチャはApple Silicon（arm64）とIntel Mac（x86_64）の両方を考慮する。`uname -m` で判定し、開発と最初の動作確認は現在使用中のMacのアーキテクチャを優先する。

環境確認スクリプトは以下とする。

```text
scripts/check_macos_env.sh
```

確認対象: macOSバージョン / アーキテクチャ / Xcode Command Line Tools / Rust / Cargo / Node.js / npm / Python / Git / Codex CLI / Claude Code CLI / シェル / SQLite。

実装エージェントは不足しているツールを勝手にインストールしないこと。不足がある場合は一覧をユーザーへ表示し、インストールを依頼する。

---

# 10. 全体アーキテクチャ

```text
┌────────────────────────────────┐
│ TwinLink Desktop               │
│ Tauri 2 + React + TypeScript   │
│                                │
│ ・接続相手と公開設定            │
│ ・交渉タイムライン              │
│ ・合意一覧                      │
│ ・承認画面                      │
│ ・記憶管理                      │
│ ・トークン比較                  │
│ ・(拡張) Provider接続           │
└───────────────┬────────────────┘
                │ localhost
                │ HTTP / WebSocket
                ▼
┌────────────────────────────────┐
│ TwinLink Local Core            │
│ Python + FastAPI               │
│                                │
│ ・Agent Identity               │
│ ・Delegation / Policy Engine   │
│ ・Selective Disclosure         │
│ ・Negotiation Engine           │
│ ・Agreement管理                 │
│ ・Human Approval               │
│ ・Token Counter                │
│ ・Memory Engine                │
│ ・Provider Adapters            │
└───────────────┬────────────────┘
                │
       ┌────────┴────────┐
       ▼                 ▼
 TwinLink Relay      (拡張) Codex CLI /
 Server経由で        Claude Code CLI →
 他ノードと交渉      ローカルプロジェクト
```

他人の本人代理AIと通信する場合の構成:

```text
TwinLink Desktop A（本人Aのノード）
        │
        ▼
TwinLink Relay Server（配送のみ）
        │
        ▼
TwinLink Desktop B（本人Bのノード）
```

---

# 11. ローカルファーストと脅威モデル

本人の記憶は、原則としてMac内に保存する。クラウドへ本人の全記憶を送信してはならない。

ローカルへ保存する情報:

* 本人プロフィール / クローンプロフィール
* 本人の好み / 判断ルール / 過去の意思決定
* プロジェクト情報 / 実行履歴 / 承認・拒否履歴
* 構造化された本人の記憶
* トークン使用量 / エージェント間通信履歴
* 接続先の公開情報

クラウド（Relay）へ送信可能な情報は以下に限定する。

* エージェントの公開ID / 公開名 / 公開能力 / 公開鍵
* 構造化された交渉メッセージ
* タスク状態 / 必要最小限の通知情報

以下をクラウドへ送信しない。

* Gitリポジトリ全体 / 生のメール履歴 / 本人の会話履歴全体
* APIキー / パスワード / 秘密鍵
* ローカルファイル全体 / CLIの認証情報
* 本人のクローンプロフィール全体

## 脅威モデル

Relay Serverは、構造化された交渉メッセージの本文を見ることができる。これは「クラウドへ送信可能な情報」に含まれるため許容する。

ただし、以下はRelayにも流れないことを保証する。

* 記憶の本文（restricted / secret を含む）
* 候補を除外した理由
* busy予定の生の時間範囲

エンドツーエンド暗号化はMVPでは必須としない（将来SHOULDとして検討する）。MVPで必須なのは、署名によるなりすまし防止とリプレイ防止である（§16, §21）。

---

# 12. データ保存場所とスキーマ管理

macOSの標準的なディレクトリ構成に合わせる。

```text
アプリデータ: ~/Library/Application Support/TwinLink/
  twinlink.db / memory/ / snapshots/ / projects/ / exports/
キャッシュ:   ~/Library/Caches/TwinLink/
ログ:         ~/Library/Logs/TwinLink/
  twinlink-desktop.log / twinlink-core.log / agent-execution.log / audit.log
一時ファイル: OSの一時ディレクトリ（処理完了後に削除）
```

## スキーマ管理

SQLiteのスキーマは `create_all` に依存せず、Alembicでバージョン管理する。

* 初期スキーマをbaselineとして登録する（実装済み: `202607120001` baseline、`202607120002` disclosure/agreements）
* 起動時にスキーマバージョンを確認し、不一致なら自動アップグレードする
* アップグレード前に `twinlink.db` をバックアップする
* 破壊的マイグレーションはLevel 2承認の対象とする（§24）

---

# 13. macOS Keychain

以下の秘密情報はSQLiteやJSONファイルへ保存しない。

* APIキー / OAuthトークン / リレー接続トークン / 秘密鍵 / 一時認証情報

これらはmacOS Keychainへ保存する。サービス名は `com.twinlink.desktop`、保存キーの例は `openai_api_key` / `anthropic_api_key` / `relay_access_token` / `agent_private_key`。

フロントエンドへ秘密情報の実値を返してはならない。APIは以下のような状態のみ返す。

```json
{
  "provider": "openai",
  "configured": true
}
```

---

# 14. Local Coreプロセス

Pythonバックエンドは、macOS上でローカル専用プロセスとして動作させる。

* 待ち受けは必ず `127.0.0.1` に限定する（`0.0.0.0` 禁止）
* ポートは固定せず、利用可能なランダムポートを選択する
* Tauri側はPython起動時に一度だけ使うランダムなローカル認証トークンを渡す
  （`TWINLINK_LOCAL_TOKEN` / `TWINLINK_LOCAL_PORT`）
* すべてのローカルAPI呼び出しに `Authorization: Bearer <local-token>` を要求する
* アプリ終了時にはLocal Coreも終了させ、孤立プロセスを残さない

開発中は `uvicorn twinlink_core.main:app --host 127.0.0.1 --port 8765` で起動できる。製品版では単独のsidecarバイナリ `twinlink-core` としてパッケージ化し、Tauriから許可されたsidecarだけを起動する。

任意のシェル文字列（`/bin/zsh -c "<untrusted input>"`）を実行してはならない。コマンド名と引数を必ず分離する。

```python
# 悪い例
command = f"codex {user_input}"

# 良い例
command = [codex_path, *validated_arguments]
```

---

# 15. ディレクトリ構成

```text
twinlink/
├── README.md
├── .gitignore
├── .env.example
├── package.json
├── pyproject.toml
├── rust-toolchain.toml
│
├── apps/
│   └── desktop/
│       ├── src/
│       │   ├── main.tsx / App.tsx
│       │   ├── components/
│       │   ├── pages/
│       │   │   ├── HomePage.tsx
│       │   │   ├── OnboardingPage.tsx
│       │   │   ├── PeersPage.tsx          … 接続相手と公開設定
│       │   │   ├── NegotiationsPage.tsx   … 交渉タイムライン
│       │   │   ├── AgreementsPage.tsx     … 合意一覧
│       │   │   ├── ApprovalsPage.tsx
│       │   │   ├── MemoriesPage.tsx
│       │   │   ├── MetricsPage.tsx
│       │   │   ├── ClonePage.tsx          … (拡張)
│       │   │   ├── ProjectsPage.tsx       … (拡張)
│       │   │   ├── AgentsPage.tsx         … (拡張)
│       │   │   └── NewTaskPage.tsx        … (拡張)
│       │   ├── stores/ / hooks/ / services/ / types/ / utils/
│       └── src-tauri/
│           ├── Cargo.toml / tauri.conf.json / capabilities/
│           └── src/
│               ├── main.rs
│               ├── commands/（system / projects / keychain / sidecar / coding_agents）
│               ├── process/ / security/ / state/
│
├── services/
│   ├── local-core/
│   │   ├── twinlink_core/
│   │   │   ├── main.py / config.py / database.py
│   │   │   ├── api/ / models/ / schemas/ / services/
│   │   │   ├── memory/ / clone/ / negotiation/ / providers/
│   │   │   ├── policies/ / metrics/ / security/
│   │   ├── alembic_migrations/
│   │   └── tests/
│   └── relay/
│       ├── relay/
│       └── tests/
│
├── packages/
│   ├── protocol/（schemas/ / examples/）
│   └── shared-types/
│
├── scripts/
│   ├── check_macos_env.sh
│   ├── dev_desktop.sh / dev_core.sh
│   └── run_demo_relay.sh / run_demo_user_a.sh / run_demo_user_b.sh
│
└── docs/
    ├── architecture.md / security.md / protocol.md
    ├── clone-memory.md / demo.md
```

---

# 第III部 中核ドメイン

# 16. Agent Identityと信頼モデル

TwinLinkの中核は「誰の代理AIか」を保証することである。

* Agent IDは公開鍵から導出するか、IDと公開鍵の対応を初回ペアリングで相互確認する
* 初回ペアリングは、ユーザー承認付きの公開鍵フィンガープリント交換とする。フルPKI・CAは使わない
* 署名はEd25519とし、正規化したエンベロープ全体（message_id / session_id / 送受信者 / message_type / intent / session_version / created_at / payloadハッシュ / nonce）を署名対象にする
* 受信側は、署名・既知公開鍵・nonceとmessage_idの重複・タイムスタンプ許容範囲・sequence単調増加を検証する
* 検証済みのmessage_idをTTL付きで保持し、再送は冪等応答または拒否とする
* 鍵の失効と再ペアリングの手順を定義する
* エンドツーエンド暗号化はMVPでは必須としない（§11の脅威モデルを参照）

ピアの状態は `pending → trusted / blocked` で管理し、trustedのピアとのみ交渉できる。

---

# 17. ユーザー間の接続と所有者分離

1台のMac上でデモする場合でも、2体の本人代理AIを同じ所有者の内部エージェントとして扱ってはならない。

```text
User A Node                  User B Node
・独立したSQLite             ・独立したSQLite
・独立したエージェント        ・独立したエージェント
・独立した秘密鍵             ・独立した秘密鍵
・独立したポリシー            ・独立したポリシー
・独立したデータディレクトリ  ・独立したデータディレクトリ

Relay Server
・メッセージ配送のみ
・本人記憶を保持しない
```

デモ用データディレクトリと起動スクリプト:

```text
.tmp/demo-user-a/ / .tmp/demo-user-b/ / .tmp/demo-relay/
scripts/run_demo_user_a.sh / run_demo_user_b.sh / run_demo_relay.sh
```

---

# 18. Selective Disclosure（相手別の情報公開設定）

相手ごとに「何を公開してよいか」を設定し、交渉時に相手へ送るすべてのpayloadはこのポリシーを通す。

```python
class PeerDisclosurePolicy:
    peer_agent_id: str          # PeerAgentと1対1
    allowed_memory_types: list[str]
    max_sensitivity: str        # 既定 "internal"
    share_schedule: bool        # 既定 True。Falseなら日程照会自体を拒否
    share_skills: bool
    extra: dict
```

* API: `GET / PUT /v1/peers/{agent_id}/disclosure`
* 未設定のピアには最小公開の既定値を適用する（DBへは保存しない）
* 許可されていない `memory_type`、`max_sensitivity` を超える機密度の情報は、候補計算にもpayloadにも使わない

## 機密度と送信可否

| sensitivity | 外部LLM・相手エージェントへの送信 |
|---|---|
| public / internal | 送信可（Disclosureポリシーの範囲内で） |
| private | タスク単位で本人が明示許可した場合のみ可 |
| restricted | 本文・理由・生の時間範囲は送信不可。ローカル判定にのみ使用 |
| secret | 一切使用不可（表示は本人の明示操作のみ） |

restrictedの扱いは「漏洩の完全防止」ではなく「推論可能量の制限」を目標とする。

* 受信した候補はローカルで判定し、ACCEPT / COUNTER / REJECT だけを返す
* 除外理由・予定名・元の時間範囲を送らない
* 相手×期間ごとに累積照会回数の上限（照会予算）を設ける
* 時間を少しずつずらした近似照会の反復は拒否する
* カウンター候補の粗視化・少数化は補助策であり、匿名化とは主張しない

Disclosureポリシーはこの機密度ルールを緩和できない（restricted / secretはポリシーに関係なく非送信）。

---

# 19. 記憶モデルとMemory Connectors

記憶は本人代理AIの判断材料であり、TwinLinkを知識管理ツールにはしない。

```python
class MemoryItem:
    id: str
    user_id: str
    source_type: str
    source_reference: str | None

    memory_type: str        # identity / preference / skill / project / decision /
                            # policy / communication / environment /
                            # negative_preference / episodic / relationship / schedule
    title: str
    content: dict
    searchable_text: str | None

    confidence: float
    sensitivity: str        # public / internal / private / restricted / secret
    relevance_tags: list[str]

    effective_from: datetime | None
    effective_until: datetime | None

    status: str
    created_at: datetime
    updated_at: datetime
```

## 利用できる記憶ソース（MVP）

* TwinLink内の情報: プロフィール / 手動登録した好み・スキル / 判断ルール / 承認ルール / 過去の交渉・タスク・承認履歴
* （拡張）選択されたプロジェクトの `README.md` / `AGENTS.md` / `CLAUDE.md` / 設定ファイル類
* （拡張）Git情報: ブランチ / 最近のコミット / 変更中ファイル（git commit / push / reset等は勝手に実行しない）

## 「全記憶を使う」の意味

> TwinLinkが利用可能で、本人が明示的に許可した、目的に関連する全記憶を利用する。

Mac内の全ファイルを無断で読む・全メールを送信する・APIキーを組み込む・無関係な機微情報をタスクへ渡す、を意味しない。

## 記憶の削除と依存整合

エージェントプロフィール（クローン）は生成時に使用した記憶IDを追跡する（memory_snapshot）。

* 記憶を削除・大幅更新したとき、その記憶を使用したactiveクローンを `outdated` にする
* 削除済み記憶は、コンテキスト生成・交渉計算・LLM送信へ再利用しない
* 監査ログには記憶IDのみ残し、本文は残さない

---

# 20. 委任と権限

本人は代理AIへ「何を任せるか」を明示的に委任する。委任は以下で表現する。

* ポリシープロフィール: 交渉の自動判定閾値（例: `task.request` の `max_hours_auto_accept` / `max_hours_auto_counter` / `min_deadline_margin_days`）
* 承認ルール: 操作カテゴリごとの可否（例）

```json
{
  "approval_rules": {
    "read_project_files": true,
    "create_files": true,
    "modify_files": true,
    "delete_files": false,
    "run_tests": true,
    "install_dependencies": false,
    "use_network": false,
    "git_commit": false,
    "git_push": false,
    "deploy": false
  }
}
```

委任範囲外の判断は自動化せず、必ず人間承認へエスカレーションする（§24）。

---

# 21. エージェント間プロトコル

プロトコル名: **TwinLink Protocol 0.1**

```json
{
  "protocol": "twinlink/0.1",
  "message_id": "msg_001",
  "session_id": "session_001",
  "sender_agent_id": "agent_a",
  "receiver_agent_id": "agent_b",
  "message_type": "PROPOSE",
  "intent": "meeting.schedule",
  "session_version": 1,
  "payload": {},
  "delta": {},
  "requires_human_approval": false,
  "created_at": "2026-07-10T12:00:00+09:00"
}
```

`message_type`:

```text
REQUEST / PROPOSE / COUNTER / ACCEPT / REJECT /
REQUEST_APPROVAL / APPROVAL_RESULT / EXECUTE / RECEIPT / ERROR
```

毎回、交渉履歴全体を送信しない。前回から変更された内容だけを `delta` へ入れる。

## プロトコル状態機械

署名が正しくても、状態として受け付けられないメッセージは拒否する。

```text
REQUEST → PROPOSE → ACCEPT（合意・終端）
                  → COUNTER → ACCEPT / COUNTER（ラウンド上限まで）
承認待ち → waiting_approval（人間承認の結果でACCEPT / REJECT）
任意時点 → REJECT / ERROR（終端）
```

* 終端したセッションへのメッセージは拒否する
* sequenceの逆行・重複は拒否する
* ACCEPT後のCOUNTERなど、許可されない遷移は `INVALID_STATE_TRANSITION` とする

## Relay Serverの責務

* 配送のみを行い、本文を改変しない
* 本人の記憶・秘密鍵を保持しない
* メッセージはTTL付きで保存し、期限後に削除する
* 接続はノードごとの認証を必須とする（デモでは事前共有トークンでよい）
* 宛先の認可・サイズ上限・レート制限・重複配送の抑止を行う
* ログは配送メタデータのみとし、本文を残さない

---

# 22. 交渉セッション

## 22.1 日程調整（meeting.schedule）

ユーザーAが「来週、田中さんとAIエージェントの企画について30分話したい。できれば午後がいい。」と入力すると、代理AIは以下へ変換する。

```json
{
  "intent": "meeting.schedule",
  "target_agent_id": "tanaka-agent",
  "topic": "AIエージェントの企画",
  "duration_minutes": 30,
  "date_range": { "start": "2026-07-13", "end": "2026-07-17" },
  "preferred_time_ranges": [ { "start": "13:00", "end": "18:00" } ]
}
```

日程計算はPythonコードで実行する。LLMに空き時間の共通部分を計算させない。相手の `share_schedule=False` の場合は照会自体を拒否する。

## 22.2 仕事依頼（task.request）

```json
{
  "intent": "task.request",
  "title": "ロゴ画像の作成",
  "description": "新サービスのロゴを3案",
  "deadline": "2026-07-20",
  "estimated_hours": 3.0,
  "conditions": {}
}
```

* 既存の状態機械・ラウンド上限・delta差分を再利用する（intentごとに状態機械を複製しない）
* 受信側はポリシープロフィールの閾値で自動判定する: 範囲内なら自動ACCEPT / COUNTER、範囲外は人間承認へエスカレーション（§24）

---

# 23. 合意状態の管理（Agreement）

交渉セッションがACCEPTで終端したとき、合意レコードを自動生成する（ローカル交渉・リモート交渉の両方）。

```python
class Agreement:
    id: str
    session_id: str
    intent: str
    initiator_agent_id: str
    responder_agent_id: str
    agreed_payload: dict
    status: str            # active / fulfilled / cancelled
    agreed_at: datetime
    updated_at: datetime
```

* API: `GET /v1/agreements`（status / intentでフィルタ）、`GET /v1/agreements/{id}`、`PATCH /v1/agreements/{id}`（status変更のみ）
* 監査ログにはagreement_idとintentのみ記録し、agreed_payloadの本文は残さない

「どの条件で合意したか」を後から確認・履行管理できることが、TwinLinkの信頼性の核である。

---

# 24. 人間承認とエスカレーション

## 承認レベル

```text
Level 0（自動許可）:
  情報の読み取り / コンテキスト生成 / 変更案の提示

Level 1（ルールにより自動許可可能）:
  既存ファイル編集 / 新規ソース作成 / テスト・Lint・型チェック実行 /
  委任閾値内の交渉自動判定

Level 2（本人承認必須）:
  委任閾値を超える交渉判断 / 依存パッケージ追加 / DBマイグレーション /
  ファイル削除 / 外部ネットワーク利用 / Git commit / 設定の大幅変更

Level 3（MVPでは禁止）:
  Git push / 本番デプロイ / 秘密情報の送信 / ホームディレクトリ全体の読み取り /
  Keychain情報の外部送信 / rm -rf / git reset --hard / git clean -fd / 管理者権限
```

## 交渉のエスカレーション

ポリシーで自動判定できない交渉（`task.request` の閾値超過、ラウンド上限到達時の最終判断など）は、`action_type="negotiation_decision"` のApprovalを作成し、セッションを `waiting_approval` にする。

* 承認 → ACCEPTを送出し合意処理へ
* 拒否 → REJECTで終端
* 失効 → REJECTで終端（古い承認で後から合意できない）
* エスカレーション経由のメッセージは `requires_human_approval=true` を実態どおり記録する

## 承認の失効

* すべての承認要求は `expires_at` を持つ
* 期限を過ぎた承認は `expired` とし、対象タスク・交渉は実行せず終端化する
* 古い承認を後から実行してはならない
* OS通知の実装は後回しでよいが、失効は安全要件として必須とする

---

# 25. トークン計測と比較

同じ調整を「構造化方式」と「メール方式」の2方式で処理し、比較する。

```json
{ "intent": "meeting.schedule", "duration_minutes": 30, "preferred_time": "afternoon" }
```

```text
田中様

お世話になっております。
来週、AIエージェントの企画について30分ほど
お話しする時間をいただきたいと考えております。
可能であれば午後を希望しております。
ご都合のよい時間をお知らせください。

よろしくお願いいたします。
```

測定項目: 入出力トークン / 合計トークン / LLM呼び出し回数 / メッセージ数 / 処理時間 / 人間承認回数 / 条件不一致数。

```python
reduction_rate = (email_total_tokens - structured_total_tokens) / email_total_tokens * 100
```

固定値を表示せず、実行結果から計算する。

## 測定仕様

この比較はデモ用の測定であり、一般的な削減率を保証しない。表示・記録には以下を含める。

* 使用したメール文面テンプレートと往復数（測定条件として保存する）
* 構造化方式のJSON全体・deltaの有無・履歴送信の有無
* 削減率だけでなく、総トークン数・メッセージ数・LLM呼び出し回数を併記する

---

# 26. 監査ログ

以下を必ず記録する。

* 交渉セッションの開始・終端・エスカレーション
* 合意の生成・状態変更（agreement_idのみ）
* タスクの開始・完了・失敗
* 使用したエージェントプロフィールとバージョン
* 使用した記憶カテゴリ（IDのみ・本文なし）
* 外部へ渡したコンテキストの規模
* 実行コマンド / 変更されたファイル
* 承認・拒否・失効の結果
* LLM利用量 / エラー

```json
{
  "event_type": "coding_agent_task_started",
  "user_id": "user_001",
  "clone_id": "clone_001",
  "provider": "codex",
  "task_id": "task_001",
  "permissions": ["read_files", "modify_files", "run_tests"],
  "context_tokens": 1420,
  "created_at": "2026-07-10T12:00:00+09:00"
}
```

APIキーや記憶本文全体をログへ保存しない。

---

# 27. エラーハンドリング

統一形式:

```json
{
  "error": {
    "code": "PROVIDER_NOT_INSTALLED",
    "message": "Codex CLIが見つかりません。",
    "details": {}
  }
}
```

主なコード:

```text
MACOS_VERSION_UNSUPPORTED / DEVELOPMENT_TOOL_MISSING
LOCAL_CORE_START_FAILED / LOCAL_CORE_UNAUTHORIZED
CLONE_NOT_FOUND / CLONE_REVIEW_REQUIRED
MEMORY_PERMISSION_DENIED
PROJECT_NOT_FOUND / PROJECT_PATH_NOT_ALLOWED
PROVIDER_NOT_INSTALLED / PROVIDER_NOT_AUTHENTICATED / PROVIDER_VERSION_UNSUPPORTED
TASK_PERMISSION_DENIED / APPROVAL_REQUIRED / COMMAND_NOT_ALLOWED
PATH_ESCAPE_DETECTED / CONTEXT_TOO_LARGE / NO_AVAILABLE_SLOT
INVALID_STATE_TRANSITION / RELAY_UNAVAILABLE / MESSAGE_SIGNATURE_INVALID
```

---

# 28. ローカルAPI

```text
GET  /health
GET  /v1/system/environment

GET  /v1/users
POST /v1/users

GET  /v1/peers
POST /v1/peers                      … 公開鍵ペアリング
POST /v1/peers/{agent_id}/trust
GET  /v1/peers/{agent_id}/disclosure
PUT  /v1/peers/{agent_id}/disclosure

POST /v1/negotiations
GET  /v1/negotiations/{session_id}
GET  /v1/negotiations/{session_id}/messages

GET  /v1/agreements
GET  /v1/agreements/{id}
PATCH /v1/agreements/{id}

GET  /v1/approvals
POST /v1/approvals/{approval_id}/approve
POST /v1/approvals/{approval_id}/reject

GET  /v1/memories
POST /v1/memories
DELETE /v1/memories/{memory_id}

GET  /v1/metrics/summary
GET  /v1/metrics/negotiations/{session_id}
GET  /v1/metrics/tasks/{task_id}

（拡張: クローン・プロジェクト・Provider・タスク）
GET  /v1/clones/{user_id}
POST /v1/clones/{user_id}/ensure
POST /v1/clones/{clone_id}/activate
POST /v1/clones/{clone_id}/rebuild
PATCH /v1/clones/{clone_id}

GET  /v1/projects
POST /v1/projects
GET  /v1/projects/{project_id}
PATCH /v1/projects/{project_id}

GET  /v1/providers
POST /v1/providers/{provider}/detect
POST /v1/providers/{provider}/connect

POST /v1/context-packages
GET  /v1/context-packages/{package_id}

POST /v1/tasks
GET  /v1/tasks/{task_id}
POST /v1/tasks/{task_id}/cancel
```

---

# 第IV部 拡張機能（基本交渉が動作した後に強化する）

以下は方針修正により優先度を下げた領域である。既存実装は削除せず維持するが、新規開発は第III部の中核が完成してから行う。

# 29. クローンプロフィールと自動生成

本人代理AIの実体はクローンプロフィールである。

```python
class CloneAgent:
    id: str
    user_id: str
    name: str
    version: int
    status: str            # draft / review_required / active / paused / outdated / deleted

    identity_profile: dict
    preference_profile: dict
    skill_profile: dict
    coding_profile: dict
    project_profile: dict
    policy_profile: dict
    communication_profile: dict

    memory_snapshot_id: str
    confidence_score: float

    created_at: datetime
    activated_at: datetime | None
    updated_at: datetime
```

* 生成直後は `review_required` とし、ユーザー確認前に高権限操作を許可しない
* 自動生成フロー（記憶ソース調査→使用許可→分類→重複・矛盾処理→生成→確認→有効化）は実装済みだが、MVPでは手動登録した最小プロフィールで十分とする
* 高度な自動生成（多様な記憶ソースの取り込み・要約）は中核完成後に強化する

# 30. Provider Adapters（Codex / Claude Code接続）

CodexやClaude Codeは「TwinLinkへ接続できるエージェントの例」であり、Adapterの1実装として閉じ込める。

```python
class CodingAgentAdapter(Protocol):
    async def detect(self) -> ProviderDetectionResult: ...
    async def get_version(self) -> str | None: ...
    async def check_authentication(self) -> AuthenticationStatus: ...
    async def get_capabilities(self) -> ProviderCapabilities: ...
    async def run_task(self, task: CodingTask, context: CloneContextPackage) -> CodingTaskResult: ...
    async def cancel_task(self, task_id: str) -> None: ...
```

実装: `CodexCliAdapter` / `ClaudeCodeAdapter` / `MockCodingAgentAdapter`。

* CLIの存在・バージョンは `which` / `--version` / `--help` で実際に確認し、オプションを決めつけない
* CLIの認証情報をTwinLinkが読み取り・保存してはならない（CLI既存の認証状態を利用する）
* 固有処理は必ず各Adapter内に閉じ込め、交換可能に保つ

## プロジェクトアクセス

* プロジェクトはmacOSのネイティブフォルダ選択画面から登録し、明示的に選択されたフォルダだけを読む
* ホームディレクトリ全体を自動走査してはならない
* パスは正規化し、シンボリックリンクで許可ルート外へ出ないよう検証する
* 権限は `LocalProject.permissions`（read / create / modify / delete / run_commands / use_network / git_commit / git_push）で管理する

## Clone Context Package

外部AIへ本人の全記憶を送らない。タスクごとに関連情報だけを抽出・圧縮した `CloneContextPackage`（task_goal / relevant_* / coding_rules / prohibited_actions / approval_requirements / estimated_tokens / content_hash）を作成して渡す。

## 非同期タスク実行

コーディングタスクは同期APIで完結させず、永続キューで実行する。

* CodingTaskテーブル自体をキューとして使う（外部キュー基盤は導入しない）
* 単一プロセス・単一ワーカー・並行数1をMVPの運用制約とする
* claimは `status='queued'` 条件付きUPDATEで原子的に行う
* **作成時に承認要否を先に判定し、初期statusを単一commitで確定する**（一瞬でも「承認が必要なのにqueued」でDBに見える状態を作らない。承認前実行の競合バグの再発防止）
* タイムアウトは既定600秒、プロバイダごとに設定可能とする
* タイムアウト・キャンセル時は子プロセスを実際に停止（terminate→猶予→kill）し、停止確認後に終端化する
* キャンセルは協調的とし、実行中は `cancelling` を経由する。終端後の再キャンセルは409
* 起動時に残った `running` タスクは `failed`（failure_code=`WORKER_INTERRUPTED`）にする

状態遷移:

```text
waiting_approval → queued → running → completed / failed
                        running → cancelling → cancelled
waiting_approval → expired / cancelled
```

タスクは `failure_code` / `failure_message` / `queued_at` / `started_at` / `finished_at` / `worker_id` / `heartbeat_at` / `timeout_seconds` を持つ。

## CLI実行の安全設計

実行ファイル・引数・作業ディレクトリ・環境変数・標準入力を分離して渡す。実行前に以下を検証する。

* CLIパスが実在し、許可された実行ファイルか
* 作業ディレクトリがユーザー選択済みで許可ルート内か
* 引数に不正な制御文字がないか
* タスクが付与権限内か（ネットワーク / 削除 / Git操作の有無）

---

# 第V部 実装計画

# 31. デスクトップ画面

中核（MVP）:

* **ホーム**: TwinLink / Local Core / 接続ピアの状態、未処理の承認、進行中の交渉、削減トークン数
* **接続相手（Peers）**: ペアリング（フィンガープリント確認）、信頼状態、相手別の公開設定（memory_type / 機密度上限 / スケジュール・スキル共有）
* **交渉**: 相手・セッション状態・タイムライン・JSONメッセージ・承認状態
* **合意**: Agreement一覧（intent / status / 合意内容）、状態変更
* **承認**: 交渉判断・ファイル変更・コマンド実行・ネットワーク・Git操作・外部送信、失効期限の表示
* **記憶**: 一覧・出典・信頼度・機密度・編集・削除・利用禁止
* **メトリクス**: トークン数・LLM呼び出し回数・処理時間・構造化方式との比較

拡張:

* **クローン**: プロフィール・バージョン・信頼度・権限・有効化/停止
* **プロジェクト**: フォルダ選択・Git状態・許可権限
* **外部エージェント**: Codex / Claude Code / Mockの検出・バージョン・認証状態・接続
* **新規タスク**: 対象プロジェクト・エージェント・タスク説明・許可操作・実行

---

# 32. テスト要件

## Python（pytest / ruff / mypy）

* ペアリング・信頼フロー / 署名・リプレイ検証
* Selective Disclosureのフィルタ（機密度超過・非許可memory_typeの非送信、share_schedule=False拒否）
* 交渉状態遷移（順序違反・終端後拒否・INVALID_STATE_TRANSITION）
* task.requestの自動判定3経路（ACCEPT / COUNTER / エスカレーション）
* Agreement生成・状態遷移
* 承認の失効（期限切れ承認で実行・合意できない）
* タスクキュー（原子的claim・承認前にclaim不可・キャンセル・リカバリ）
* 日程計算 / トークン計算 / API認証 / パストラバーサル防止
* 記憶削除→クローンoutdated整合

## Rust（cargo test / cargo clippy）

* Keychainラッパー / sidecar起動 / CLI検出 / パス検証 / 許可コマンド検証 / プロセス終了

## TypeScript（vitest / eslint / tsc）

* APIクライアント / 状態管理 / 承認UI / 交渉タイムライン / エラー表示

---

# 33. 実装フェーズと現状

## 実装済み（2026-07-12時点）

* Phase 0–2: 環境確認 / Tauriシェル / Local Core / SQLiteデータ基盤（Alembic管理）
* Phase 3: クローン自動生成（記憶分類・重複・矛盾処理）
* Phase 4: TwinLink Protocol 0.1・日程調整交渉・トークン比較
* Phase 5: Provider Adapters（Codex / Claude Code / Mock）・Context Package・非同期タスクキュー・承認ゲート
* Phase 6: 別所有者ノード・Relay・Ed25519署名・リプレイ防止・状態機械
* 方針修正反映: Selective Disclosure・task.request・Agreement・交渉エスカレーション・承認失効

## 次フェーズ

### Phase 7: 中核MVPの完成

* フロントエンドUI: Peers（ペアリング・公開設定）/ 交渉 / 合意 / 承認画面を中核フローに合わせて実装
* 2ノード＋Relayのデモをスクリプト一発で起動できるようにする
* メール方式との比較実験を画面から実行・記録できるようにする
* 受入条件:
  * 改ざんされた署名・未知の鍵・期限切れ・リプレイを拒否する
  * 順序違反と終端後メッセージを拒否する
  * Relayの再送で処理が二重実行されない / Relay保存データがTTL後に削除される
  * restrictedの本文・理由・生時間範囲が通信ログとRelayに残らない
  * 相手別公開設定が候補計算とpayloadに実際に効いている

### Phase 8: Rust側の完成

* Rustツールチェーン導入後: `cargo test` / `tauri dev` の実機確認
* Keychain連携 / sidecarパッケージ化 / プロセス管理

### Phase 9: 完成度向上と配布

* エラーハンドリング・ログ・デモデータ・ドキュメント
* `.app` / `.dmg`・アイコン・コード署名・Notarization（授業内デモまでは `npm run tauri dev` でよい）

---

# 34. MVP完成条件

以下を満たした時点で、macOS版MVP完成とする。

1. Mac上でTwinLink Desktopが起動し、TauriからLocal Coreを起動・終了できる
2. ユーザーを登録し、本人代理AI（最小プロフィール）を用意できる
3. 2つの独立ノードが公開鍵ペアリングで接続できる（ユーザー承認付きフィンガープリント確認）
4. 相手ごとの公開設定を画面から編集でき、交渉に実際に反映される
5. 日程調整（meeting.schedule）をRelay経由で合意まで実行できる
6. 仕事依頼（task.request)を自動判定またはエスカレーション経由で合意まで実行できる
7. 合意がAgreementとして記録され、一覧・状態変更できる
8. 委任範囲外の判断が承認待ちになり、失効した承認では実行できない
9. エージェント間メッセージをJSONタイムラインで表示できる
10. メール方式とのトークン比較を実測で表示できる
11. 署名・リプレイ・順序違反・終端後メッセージの拒否がテストで保証されている
12. restrictedの本文・理由・生時間範囲が通信ログとRelayに残らない
13. APIキーなしでMockモードが動作する
14. pytest / cargo test / TypeScriptテストが通る
15. READMEだけでMac上の起動手順が分かる

---

# 35. 実装エージェントへのルール

実装をCodex・Claude Code等のエージェントへ委譲する場合、以下を必ず守らせること。

* macOSを第一対象にし、Windows固有コードを最初に入れない
* ユーザーのMacへ勝手にパッケージをインストールしない
* ユーザーのホームディレクトリ全体を走査せず、選択されたプロジェクトだけを読む
* APIキーをファイルへ保存せず、macOS Keychainを利用する
* Local Coreを外部ネットワークへ公開しない（`127.0.0.1` のみ）
* 任意のシェル文字列を実行せず、CLI引数を配列として渡す
* 不明なCLIオプションを決めつけず、実際に `--help` で確認する
* 認証情報をTwinLinkへコピーしない
* 外部エージェントへ全記憶を送らず、タスクに関連する記憶だけを渡す
* 危険操作は承認待ちにし、Git push・ファイル削除を自動実行しない
* 実行内容を監査ログへ記録する
* 型を付け、テストを書き、大きな1ファイル実装を避ける
* 各フェーズ終了時にテストを実行し、実装途中でも起動可能な状態を維持する
* 仕様と実装が矛盾したら本書（twinlink.md）を正とし、変更が必要なら本書を先に改訂する
