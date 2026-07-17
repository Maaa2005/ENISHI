# ENISHI Second Brain

ENISHIは、次の順で記憶を扱う。

1. ユーザーがObsidian VaultまたはMarkdownフォルダを接続した場合、その内容を読み取り専用の原本としてENISHIへ同期する。
2. 外部メモリがない場合も、ENISHIのSQLite記憶を内蔵セカンドブレインとして使う。
3. `enishi-memory` MCPはENISHIを起動せず検索・保存できる。
4. `enishi` MCPは起動中のLocal CoreへHTTP接続し、交渉の観察と依頼を行う。承認・信頼確定・公開範囲変更はできない。

## セットアップ

```sh
cd services/local-core
uv sync
../../scripts/install-agent-integrations.sh
```

登録スクリプトはCodexとClaude CodeのCLIが存在する方だけを設定する。グローバル設定を変更するため、内容を確認してから実行する。

Codexプラグインは `plugins/enishi` にある。MCPの実行ファイル `enishi-mcp` と `enishi-memory-mcp` がPATH上にある環境では、プラグイン単体でも起動できる。

## プライバシー

- フォルダは明示的にパスを保存して有効化し、「今すぐ同期」を押すまで読み込まない。
- MarkdownはローカルDBへprivateとして格納し、原本を書き換えない。
- MCPはローカルstdio接続で、HTTPサーバーを公開しない。
- `secret` はMCP経由で保存できない。
- 交渉MCPはLocal Coreが生成する0600の `core.json` とMCP専用tokenを使う。Core未起動時に勝手に起動しない。
- 相手由来テキストは `UNTRUSTED CONTENT` と表示し、命令として扱わない。
