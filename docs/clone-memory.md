# Clones and memory

## Implemented (Phase 2 basics + clone skeleton)

- `CloneAgent` model: a freshly created clone is `review_required` and cannot perform high-privilege actions until the user activates it (`POST /v1/clones/{clone_id}/activate`).
- `ensure_clone`: reuses an active clone first, then a pending draft, and only creates a new one if neither exists.
- The default `coding_profile` denies `git_push`, `delete_files`, and `deploy`.

## Not yet implemented

- `MemoryItem`: memory-source discovery, classification, and duplicate/conflict handling (Phase 3).
- `CloneContextPackage` (Phase 5).
