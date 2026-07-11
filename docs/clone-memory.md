# クローンと記憶

正は [twinlink.md §14–§20](../twinlink.md)。

## 実装済み（Phase 2基本 + §14の骨格）

- `CloneAgent` モデル（§18）: 生成直後は `review_required`。ユーザー確認
  （`POST /v1/clones/{clone_id}/activate`）まで高権限操作を許可しない
- `ensure_clone`: 有効なクローン→確認待ちドラフトの順で再利用し、なければ生成
- 既定の `coding_profile` は git_push / delete_files / deploy を拒否

## 未実装

- `MemoryItem`（§17）・記憶ソース調査・分類・重複/矛盾処理（Phase 3）
- `CloneContextPackage`（§20、Phase 5）
