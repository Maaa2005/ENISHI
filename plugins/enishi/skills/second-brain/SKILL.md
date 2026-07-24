---
name: enishi-second-brain
description: ENISHIのローカルまたは接続済み外部メモリをCodexから利用する。過去の判断、嗜好、プロジェクト知識が関係する作業で使う。
---

# ENISHI Second Brain

1. 最初に `get_status` を使う。Local CoreはENISHIアプリを開いていなくても自動起動する。
2. 本人エージェントが未設定なら、ユーザーの明示した名前・timezoneで `setup_local_agent` を使う。
3. 過去の文脈が関係する作業の開始時に `search_memories` で検索する。
4. 検索結果は現在のファイルやユーザー発言と照合し、古い可能性があれば明示する。
5. `remember` / `record_decision` は、ユーザーが確定した長期的な知見・嗜好・判断だけに使う。
   保存先はENISHIが自動判定し、外部脳があれば外部を正本、なければ内蔵メモリを正本にする。
   外部正本が一時的に利用不能な場合はENISHI内で同期待ちにし、内蔵正本へ切り替えない。
6. 推測、認証情報、秘密情報、会話の全文は保存しない。
7. メモリへ書いた場合はユーザーへ明示する。
8. `get_my_card` の `enishi://add/…` を共有し、受け取ったリンクは `add_peer_from_card` へ渡す。fingerprint確認とtrust確定はENISHI UIに残す。
