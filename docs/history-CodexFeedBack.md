## 総評

**ENISHIは、学生プロジェクトの範囲をかなり超えています。**
Tauri、FastAPI、SQLite、Relay、MCP、署名付きプロトコル、承認ゲートまで一貫しており、特に「Relayを信用しない」「必要な情報だけ開示する」「実行前に人間が承認する」という境界設計は明確です。READMEも設計思想をきちんと説明できています。人類はREADMEすら書かないことが多いので、そこは普通に強いです。 ([GitHub][1])

ただし現在は、**設計完成度に対して、運用耐性・相互運用性・公開プロダクトとしての導線が少し遅れている**状態です。

以下は静的レビューです。リポジトリをローカル実行しての動作検証までは行えていません。

---

# 優先度別の改善・修正点

## P0相当：公開前に直したい

### 1. Relayのリクエストサイズ制限が遅すぎる

現在はFastAPIがJSONを`dict`へ変換した後に、`json.dumps()`でサイズを計算しています。つまり巨大なJSONを送られた場合、**上限判定より先にJSON解析とメモリ確保が行われます**。Caddy側にもリクエストボディ上限がありません。認証トークンが漏えいした場合や、正規ノードが暴走した場合のDoS耐性が弱いです。 ([GitHub][2])

**修正内容**

* リバースプロキシ層で最大ボディサイズを制限する
* ASGIミドルウェアでもストリーム読み込み量を制限する
* `Content-Length`も事前検証する
* JSONの文字列長、ネスト深度、配列要素数にも上限を設ける
* Relayの受信モデルを`dict[str, Any]`ではなく、制限付きPydanticモデルにする

Caddyには`request_body max_size`がありますが、現行ドキュメントではCaddy 2.10以降の実験的機能です。現在の構成が2.8系なら、バージョン更新かアプリ層での制御が必要です。 ([Caddy Web Server][3])

---

### 2. Relayメールボックスに容量制限とページングがない

現在のRelayは送信者単位のレート制限はありますが、以下がありません。

* 受信者単位の未処理メッセージ数上限
* 受信者単位の合計バイト数上限
* Relay全体の保存容量上限
* `GET /v1/messages`の取得件数上限

SQLite実装では、対象受信者の全メッセージを`fetchall()`し、全JSONを復元して返しています。キューが膨らむと、DB、メモリ、レスポンスサイズがまとめて悲鳴を上げます。計算機は正直なので、人間より先に倒れます。 ([GitHub][4])

**修正内容**

```text
GET /v1/messages?limit=50&cursor=<cursor>
```

を基本にして、次を追加します。

* `limit`は最大100程度
* `stored_at + delivery_id`によるカーソルページング
* `max_pending_messages_per_receiver`
* `max_pending_bytes_per_receiver`
* `max_total_pending_bytes`
* 容量超過時は`429`または`507`
* pending messages / pending bytesをメトリクス化

---

### 3. リプレイ防止処理をアトミックにする

`check_and_record()`は現在、

1. 期限切れ行を削除
2. `session.get()`で存在確認
3. なければ追加
4. 関数内部で`commit()`

という構造です。これは並行処理時に、複数トランザクションが同時に「未登録」と判断する競合が起こり得ます。また、下位のセキュリティ関数が呼び出し側のトランザクションを勝手に`commit()`しているため、処理境界が崩れています。 ([GitHub][5])

**修正内容**

* `session.commit()`を`check_and_record()`から削除
* 主キーまたは一意制約を利用して直接INSERT
* `IntegrityError`を`MESSAGE_REPLAYED`へ変換
* コミットはメッセージ処理全体の呼び出し側で一度だけ行う
* 並行受信テストを追加する

概念的には次の形です。

```python
def record_message(session: Session, message_id: str, expires_at: datetime) -> None:
    try:
        session.add(SeenMessage(message_id=message_id, expires_at=expires_at))
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise EnishiError(
            code="MESSAGE_REPLAYED",
            message="同一メッセージを既に処理しています。",
            status_code=409,
        ) from exc
```

SQLiteを前提にするなら、`INSERT OR IGNORE`と結果件数を使う方法もあります。

---

## P1：プロトコルと品質保証

### 4. 署名用JSON正規化を標準化する

現在の署名対象は、Pythonの以下のシリアライズに依存しています。

```python
json.dumps(
    obj,
    sort_keys=True,
    ensure_ascii=False,
    separators=(",", ":"),
)
```

Python同士では動きますが、AUN ProtocolをTypeScript、Rust、Goなどで実装すると、数値、Unicode、キー順序などの違いで同じJSONから異なる署名対象バイト列が生成される可能性があります。 ([GitHub][6])

AUNをプロトコルとして育てるなら、ここは**RFC 8785のJSON Canonicalization Schemeに寄せる**のが妥当です。RFC 8785は、暗号署名やハッシュのためにJSONを再現可能な不変形式へ変換する仕様です。 ([RFCエディター][7])

**修正内容**

* `canonical_bytes()`をJCS準拠実装へ置き換える
* Python、TypeScript、Rust共通のGolden Test Vectorを追加
* 絵文字、Unicode、浮動小数、ネストしたオブジェクトをテスト
* `NaN`、`Infinity`、重複キーなどを明示的に拒否
* AUN仕様書に「署名対象バイト列」を正式に記載

---

### 5. JSON SchemaとPython実装の二重管理をやめる

`packages/protocol`にはJSON Schemaがありますが、Local Coreでは別途Pythonで手書き検証しています。つまり、仕様変更時にSchemaだけ変えてPythonを忘れる、あるいはその逆が起こります。人間は二重管理を始めると、だいたい片方を置き去りにします。 ([GitHub][8])

また現在は、同じ`aun/0.1`内でノードIDありの新wireと、ノードIDなしの旧wireを共存させています。互換性維持としては理解できますが、セキュリティ上の意味が異なる形式を同一バージョンで扱うのは長期的に危険です。 ([GitHub][6])

**修正内容**

* JSON SchemaをSingle Source of Truthにする
* SchemaからPython・TypeScript型を生成する
* `aun/0.2`など明示的にバージョンを上げる
* `sender_node_id`と`receiver_node_id`を新バージョンでは必須化
* 旧wireの廃止予定を`docs/protocol.md`へ記載
* プロトコル互換性テストをCIに追加

---

### 6. 看板機能のE2EテストをCIで動かす

READMEでは`run_pairing_e2e.sh`により、署名済みAgent Card、指紋確認、人間承認、Relay配送、両ノードの合意保存まで検証できると説明しています。ところがCIではPython、React、Rustの個別テストとRelayイメージビルドだけで、そのE2Eスクリプトは実行されていません。 ([GitHub][1])

これは優先度が高いです。ENISHIの価値は各コンポーネント単体ではなく、**2ノード間で安全に交渉が成立すること**だからです。

**修正内容**

CIへ次のジョブを追加します。

```yaml
pairing-e2e:
  runs-on: macos-latest
  steps:
    - checkout
    - Python / Node / Rust setup
    - dependency install
    - run: ./scripts/run_pairing_e2e.sh
```

さらに以下を検証します。

* 信頼前の交渉拒否
* 不正署名の拒否
* リプレイの拒否
* 承認期限切れ
* Relay再配送時の冪等性
* Relay再起動後の未ACK復元
* 2ノードで合意内容が一致すること

---

## P2：保守性とユーザー体験

### 7. 設定値に範囲検証を入れる

Local Coreの設定は型だけ定義されており、ポート、ポーリング間隔、TTL、タイムアウトに正数制約がありません。現在のワーカー側では一部を`max(0.01, value)`で補正していますが、設定値の意味が場所によって変わります。 ([GitHub][9])

**修正内容**

```python
from pydantic import Field

local_port: int = Field(default=8765, ge=1, le=65535)
relay_poll_interval_seconds: float = Field(default=2.0, gt=0)
relay_poll_backoff_max_seconds: float = Field(default=60.0, gt=0)
approval_ttl_seconds: int = Field(default=3600, gt=0)
task_timeout_seconds: int = Field(default=600, gt=0)
```

さらに、

* `relay_url`はURL型で検証
* 本番RelayはHTTPS必須
* `backoff_max >= poll_interval`
* provider timeoutは`None`と`0`を明確に区別

を入れるべきです。

---

### 8. フロントエンドのエラー握りつぶしをやめる

`App.tsx`ではDeep Link初期化エラーを次のように完全に無視しています。

```typescript
.catch(() => undefined)
```

そのため、招待リンクが動作しなかった場合に、ユーザーにも監査ログにも何も残りません。障害が発生しているのに画面だけ静かな状態は、落ち着いているのではなく証拠隠滅に近いです。 ([GitHub][10])

**修正内容**

* 秘密情報を除去した上でログへ記録
* UIに「招待リンクを開けませんでした」と表示
* React Error Boundaryを追加
* Deep Link処理を専用Hookへ分離
* ページを`React.lazy()`で遅延ロード
* 文字列タブ管理をルート設定オブジェクトへ統合

現在の12画面を`App.tsx`から直接importしている構造は、規模が拡大すると初期バンドルと変更影響範囲が増えます。 ([GitHub][10])

---

## P2：GitHub公開・プロダクト面

### 9. LICENSEを追加する

ルートの公開ファイル一覧とREADME上では、LICENSEが確認できませんでした。GitHubも公開リポジトリには`LICENSE`または`LICENSE.md`を追加する方式を案内しています。 ([GitHub][1])

AUN Protocolを外部にも実装してほしいなら、ライセンス不明はかなり大きな摩擦です。

**推奨**

* プロトコル・OSSとして普及重視：`Apache-2.0`
* とにかく利用障壁を下げる：`MIT`
* 商用版を別管理する予定：コードとプロトコル仕様のライセンスを分ける

このプロジェクトなら、特許条項を含む**Apache-2.0が比較的相性がよい**と考えます。

---

### 10. READMEを「設計説明」から「使ってみたくなる入口」にする

現在のREADMEは内容自体は充実していますが、初見ユーザーにとって情報量が多く、以下が不足しています。

* 画面スクリーンショット
* 30～60秒のデモGIF
* 3ステップのQuick Start
* ENISHIを使う前と後の比較
* 現在できること／まだできないこと
* アーキテクチャ図
* リリースされたDMGへの導線

READMEでは「デモ可能」「パッケージング済み」と説明されていますが、GitHub Releases欄には公開リリースが表示されていません。また、署名・公証・更新配布などが残作業として明記されています。 ([GitHub][1])

**README冒頭の推奨構造**

```text
1. 一文で価値
2. デモGIF
3. ENISHIが解決する問題
4. 3ステップQuick Start
5. セキュリティ境界
6. アーキテクチャ
7. 開発者向け詳細
```

今の設計説明は削除せず、後半か`docs/`へ移すのがよいです。

---

### 11. GitHub ActionsをSHA固定する

`setup-uv`は完全なコミットSHAで固定されていますが、`actions/checkout@v7`と`actions/setup-node@v6`はタグ指定です。統一した方がよいです。GitHubも、完全なコミットSHAがActionを不変な状態で参照する唯一の方法だと説明しています。 ([GitHub][11])

**修正内容**

* すべてのActionを完全SHAで固定
* DependabotまたはRenovateで更新
* `pip-audit`
* `npm audit`
* `cargo audit`
* CodeQL
* GitHub Dependency Review
* リリース時のSBOM生成
* ビルド成果物のprovenance／attestation

をCIへ追加します。

Dockerfile自体は、ハッシュ付き依存関係、非rootユーザー、ヘルスチェックを採用しており、かなり堅実です。ここは褒めてよい部分です。 ([GitHub][12])

---

# 修正順序

実際に進めるなら、以下の順番が妥当です。

1. **Relayの受信サイズ制限**
2. **Relayのキュー容量制限とページング**
3. **リプレイ記録のアトミック化**
4. **Pairing E2EをCIへ追加**
5. **JCS採用とGolden Test Vector**
6. **AUN Protocol 0.2へのバージョン分離**
7. **設定値バリデーション**
8. **Deep Linkエラー処理**
9. **LICENSEとREADME改善**
10. **v0.1.0の署名済みRelease公開**

## 最終評価

* **アイデア・差別化：強い**
* **アーキテクチャ：かなり良い**
* **セキュリティ思想：良い**
* **実装品質：良いが、トランザクションとRelay負荷制御に修正余地あり**
* **OSSとしての公開準備：不足**
* **プロダクトとしての伝わりやすさ：改善余地が大きい**

コードを全面的に作り直す必要はありません。基礎設計は維持し、**境界部分の堅牢化と、第三者が触れるための入口整備**に集中する段階です。設計の芯はできています。今必要なのは機能追加という名の逃避ではなく、地味で効く仕上げです。

[1]: https://github.com/Maaa2005/ENISHI "GitHub - Maaa2005/ENISHI: ENISHI (縁, a bond between people): a macOS platform where your personal AI agent handles the back-and-forth with other people's agents — negotiating, scheduling, and coordinating on your behalf over a structured protocol (AUN Protocol). Shares only what's needed, never acts without your approval. · GitHub"
[2]: https://github.com/Maaa2005/ENISHI/blob/main/services/relay/relay/main.py "ENISHI/services/relay/relay/main.py at main · Maaa2005/ENISHI · GitHub"
[3]: https://caddyserver.com/docs/caddyfile/directives/request_body?utm_source=chatgpt.com "request_body (Caddyfile directive)"
[4]: https://github.com/Maaa2005/ENISHI/blob/main/services/relay/relay/store.py "ENISHI/services/relay/relay/store.py at main · Maaa2005/ENISHI · GitHub"
[5]: https://github.com/Maaa2005/ENISHI/blob/main/services/local-core/enishi_core/security/replay.py "ENISHI/services/local-core/enishi_core/security/replay.py at main · Maaa2005/ENISHI · GitHub"
[6]: https://github.com/Maaa2005/ENISHI/blob/main/services/local-core/enishi_core/security/envelope.py "ENISHI/services/local-core/enishi_core/security/envelope.py at main · Maaa2005/ENISHI · GitHub"
[7]: https://www.rfc-editor.org/rfc/rfc8785.html "RFC 8785: JSON Canonicalization Scheme (JCS)"
[8]: https://github.com/Maaa2005/ENISHI/raw/refs/heads/main/packages/protocol/schemas/negotiation-message.schema.json "raw.githubusercontent.com"
[9]: https://github.com/Maaa2005/ENISHI/blob/main/services/local-core/enishi_core/config.py "ENISHI/services/local-core/enishi_core/config.py at main · Maaa2005/ENISHI · GitHub"
[10]: https://github.com/Maaa2005/ENISHI/blob/main/apps/desktop/src/App.tsx "ENISHI/apps/desktop/src/App.tsx at main · Maaa2005/ENISHI · GitHub"
[11]: https://github.com/Maaa2005/ENISHI/blob/main/.github/workflows/ci.yml "ENISHI/.github/workflows/ci.yml at main · Maaa2005/ENISHI · GitHub"
[12]: https://github.com/Maaa2005/ENISHI/blob/main/deploy/relay/Dockerfile "ENISHI/deploy/relay/Dockerfile at main · Maaa2005/ENISHI · GitHub"
