# セキュリティ方針

正は [twinlink.md §7–§11, §23, §31](../twinlink.md)。実装済みの要点:

- Local Coreは `127.0.0.1` のみで待ち受け（`0.0.0.0` 禁止）
- `/v1/*` はBearerトークン必須。トークンは起動ごとにTauriが生成
- トークン比較は定数時間比較（`secrets.compare_digest`）
- 子プロセス起動はコマンド名＋引数配列（シェル文字列連結禁止）
- CLI検出は `shutil.which` ＋ `--version` のみ。認証情報は読まない
- 秘密情報はSQLite/JSONへ保存しない。Keychain（`com.twinlink.desktop`）を使う（Phase 5で実装）
- アプリ終了時にLocal Coreを終了し、孤立プロセスを残さない
