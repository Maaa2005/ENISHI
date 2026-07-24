# ENISHI Second Brain

ENISHIは、外部脳を置き換えず、利用可能な正本を自動選択する。

1. `~/Vault` などの既知の場所にObsidian Vaultがあれば、それを自動検出して正本にする。
2. 外部脳がなければ、ENISHIのSQLite記憶を内蔵セカンドブレイン兼正本として使う。
3. 外部脳を一度正本にした後で利用不能になった場合、内蔵メモリへ勝手に戻さず、新しい長期記憶を同期待ちとして保留する。
4. 外部脳が復旧したら、保留中と既存の内蔵長期記憶を外部正本へ移行できる。
5. `enishi-memory` MCPは保存先を意識せず検索・保存できる。
6. `enishi` MCPは必要ならLocal Coreをheadless起動し、交渉の観察と依頼を行う。承認・信頼確定・公開範囲変更はできない。

## 正本とキャッシュ

- 判断・好み・知識・プロジェクト情報などの長期記憶は、外部脳があればMarkdownへ書く。
- 予定、関係性、交渉などENISHIの動作に必要な構造化データはSQLiteへ保存する。
- 外部Markdownの本文は検索用にSQLiteへ同期するが、これは削除して再生成できる索引であり、正本ではない。
- 検索時は最大1分に1回、外部脳との差分を取り込む。
- ENISHIが作成するMarkdownには `enishi_id` を付け、`Decisions/`、`Preferences/`、`Projects/`、`Knowledge/` に分類する。

正本状態は次のいずれかになる。

- `internal_primary`: 外部脳がなく、ENISHI内蔵メモリが正本
- `external_primary`: 外部脳が正本
- `external_unavailable`: 外部正本が一時的に利用不能で、書き込みを保留
- `migrating`: 内蔵長期記憶を外部正本へ移行中

自動検出を止める場合は `ENISHI_AUTO_DISCOVER_EXTERNAL_MEMORY=false` を設定する。

## セットアップ

```sh
cd services/local-core
uv sync
../../scripts/install-agent-integrations.sh
```

登録スクリプトはCodexとClaude CodeのCLIが存在する方だけを設定する。グローバル設定を変更するため、内容を確認してから実行する。

Codexプラグインは `plugins/enishi` にある。MCPの実行ファイル `enishi-mcp` と `enishi-memory-mcp` がPATH上にある環境では、プラグイン単体でも起動できる。

## プライバシー

- 既知の標準パスは自動検出する。その他のMarkdownフォルダは明示的にパスを設定する。
- 外部Markdownは原本として扱い、ENISHIが管理する新規ノート以外を勝手に書き換えない。
- 外部Markdownの検索索引はローカルDBへprivateとして格納する。
- MCPはローカルstdio接続で、HTTPサーバーを公開しない。
- `secret` はMCP経由で保存できない。
- 交渉MCPはLocal Coreが生成する0600の `core.json` とMCP専用tokenを使う。Core未起動時はloopback限定でheadless起動し、Desktop起動時は同じDBをUI所有Coreへ安全に引き継ぐ。UI tokenはdiscoveryファイルへ保存しない。
- 相手由来テキストは `UNTRUSTED CONTENT` と表示し、命令として扱わない。
