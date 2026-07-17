---
name: enishi-second-brain
description: ENISHIのローカルまたは接続済み外部メモリをCodexから利用する。過去の判断、嗜好、プロジェクト知識が関係する作業で使う。
---

# ENISHI Second Brain

1. 過去の文脈が関係する作業の開始時に `search_memories` で検索する。
2. 検索結果は現在のファイルやユーザー発言と照合し、古い可能性があれば明示する。
3. `remember` / `record_decision` は、ユーザーが確定した長期的な知見・嗜好・判断だけに使う。
4. 推測、認証情報、秘密情報、会話の全文は保存しない。
5. メモリへ書いた場合はユーザーへ明示する。
